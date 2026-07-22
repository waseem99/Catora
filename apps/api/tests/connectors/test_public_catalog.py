from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from catora_api.connectors.public_catalog import (
    PublicCatalogConnector,
    PublicCatalogConnectorConfig,
    PublicCatalogConnectorError,
)

PUBLIC_IP = "93.184.216.34"


async def public_resolver(_: str) -> Sequence[str]:
    return (PUBLIC_IP,)


async def private_resolver(_: str) -> Sequence[str]:
    return ("127.0.0.1",)


def product_html(*, canonical: str = "/products/cloud-sofa") -> str:
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Cloud Sofa",
        "sku": "SOFA-1",
        "offers": {
            "@type": "Offer",
            "price": "1299.00",
            "priceCurrency": "USD",
        },
    }
    return f"""
    <html>
      <head>
        <title>Cloud Sofa</title>
        <link rel="canonical" href="{canonical}">
        <meta name="description" content="A comfortable three-seat sofa">
        <script type="application/ld+json">{json.dumps(product)}</script>
      </head>
      <body><h1>Cloud Sofa</h1><p>Comfortable boucle seating.</p></body>
    </html>
    """


def robots(*, disallow: str = "") -> str:
    return f"User-agent: *\nDisallow: {disallow}\n"


def url_config(**overrides: Any) -> PublicCatalogConnectorConfig:
    values: dict[str, Any] = {
        "source_type": "urls",
        "product_urls": ("https://shop.example.com/products/cloud-sofa",),
        "authorized_domain_confirmed": True,
        "crawl_delay_seconds": 0,
    }
    values.update(overrides)
    return PublicCatalogConnectorConfig(**values)


@pytest.mark.asyncio
async def test_url_connector_extracts_json_ld_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots(), headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            text=product_html(),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = PublicCatalogConnector(
            url_config(),
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    assert len(pages) == 1
    record = pages[0].records[0]
    assert record.external_id == "https://shop.example.com/products/cloud-sofa"
    assert record.payload["extraction_method"] == "json_ld"
    assert record.payload["products"][0]["name"] == "Cloud Sofa"
    assert pages[0].rejections == ()


@pytest.mark.asyncio
async def test_html_fallback_is_retained_when_json_ld_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            text=(
                "<html><head><title>Desk Lamp</title>"
                '<meta property="og:image" content="https://shop.example.com/lamp.jpg">'
                "</head><body><h1>Desk Lamp</h1></body></html>"
            ),
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = PublicCatalogConnector(
            url_config(product_urls=("https://shop.example.com/products/lamp",)),
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    record = pages[0].records[0]
    assert record.payload["extraction_method"] == "html_fallback"
    assert record.payload["html_fallback"]["title"] == "Desk Lamp"


@pytest.mark.asyncio
async def test_robots_disallow_creates_rejection_without_fetching_product() -> None:
    product_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal product_requests
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text=robots(disallow="/products/"),
                headers={"content-type": "text/plain"},
            )
        product_requests += 1
        return httpx.Response(
            200,
            text=product_html(),
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = PublicCatalogConnector(
            url_config(),
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    assert product_requests == 0
    assert pages[0].records == ()
    assert pages[0].rejections[0].reason == "Blocked by robots.txt"


@pytest.mark.asyncio
async def test_sitemap_index_discovers_bounded_same_host_products() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            body = """
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://shop.example.com/products.xml</loc></sitemap>
            </sitemapindex>
            """
            return httpx.Response(200, text=body, headers={"content-type": "application/xml"})
        if request.url.path == "/products.xml":
            body = """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://shop.example.com/products/one</loc></url>
              <url><loc>https://shop.example.com/products/two</loc></url>
            </urlset>
            """
            return httpx.Response(200, text=body, headers={"content-type": "application/xml"})
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            text=product_html(canonical=request.url.path),
            headers={"content-type": "text/html"},
        )

    config = PublicCatalogConnectorConfig(
        source_type="sitemap",
        start_url="https://shop.example.com/sitemap.xml",
        authorized_domain_confirmed=True,
        max_products=1,
        crawl_delay_seconds=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = PublicCatalogConnector(
            config,
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    assert len(pages[0].records) == 1
    assert pages[0].records[0].external_id.endswith("/products/one")


@pytest.mark.asyncio
async def test_private_ip_and_cross_host_urls_are_rejected() -> None:
    private = PublicCatalogConnector(url_config(), resolve_host=private_resolver)
    validation = await private.validate()
    assert not validation.valid
    assert validation.errors == ("Catalog host must resolve to public IP addresses",)

    cross_host = PublicCatalogConnector(
        url_config(
            product_urls=(
                "https://shop.example.com/products/one",
                "https://other.example.com/products/two",
            )
        ),
        resolve_host=public_resolver,
    )
    validation = await cross_host.validate()
    assert not validation.valid
    assert validation.errors == ("Cross-host catalog URLs are not allowed",)


@pytest.mark.asyncio
async def test_redirect_target_is_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        return httpx.Response(302, headers={"location": "https://other.example.com/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = PublicCatalogConnector(
            url_config(),
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    assert pages[0].records == ()
    assert pages[0].rejections[0].reason == "Cross-host catalog URLs are not allowed"


@pytest.mark.asyncio
async def test_resume_rejects_changed_url_set() -> None:
    connector = PublicCatalogConnector(
        url_config(),
        resolve_host=public_resolver,
    )

    with pytest.raises(PublicCatalogConnectorError, match="URL set changed"):
        _ = [
            page
            async for page in connector.pages(
                checkpoint={"index": 1, "url_set_hash": "wrong"}
            )
        ]


def test_config_requires_authorization_and_https() -> None:
    with pytest.raises(ValueError, match="authorization"):
        PublicCatalogConnectorConfig(
            source_type="urls",
            product_urls=("https://shop.example.com/product",),
        )
    with pytest.raises(PublicCatalogConnectorError, match="HTTPS"):
        PublicCatalogConnector(
            url_config(product_urls=("http://shop.example.com/product",)),
            resolve_host=public_resolver,
        )
