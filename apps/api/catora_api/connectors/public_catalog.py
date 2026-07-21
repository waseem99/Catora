from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorRejection,
    ConnectorValidation,
)

ResolveHost = Callable[[str], Awaitable[Sequence[str]]]
SleepCallable = Callable[[float], Awaitable[None]]
USER_AGENT = "CatoraCatalogBot/0.1"
_MAX_SITEMAP_BYTES = 2 * 1024 * 1024
_MAX_HTML_BYTES = 5 * 1024 * 1024
_MAX_ROBOTS_BYTES = 512 * 1024
_MAX_REDIRECTS = 3


class PublicCatalogConnectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublicCatalogConnectorConfig:
    source_type: str
    start_url: str | None = None
    product_urls: tuple[str, ...] = ()
    authorized_domain_confirmed: bool = False
    max_products: int = 100
    max_sitemaps: int = 10
    crawl_delay_seconds: float = 0.5
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if self.source_type not in {"sitemap", "urls"}:
            raise ValueError("source_type must be sitemap or urls")
        if not self.authorized_domain_confirmed:
            raise ValueError("Domain authorization confirmation is required")
        if self.source_type == "sitemap" and not self.start_url:
            raise ValueError("start_url is required for sitemap sources")
        if self.source_type == "urls" and not self.product_urls:
            raise ValueError("product_urls are required for URL sources")
        if not 1 <= self.max_products <= 1000:
            raise ValueError("max_products must be between 1 and 1000")
        if not 1 <= self.max_sitemaps <= 50:
            raise ValueError("max_sitemaps must be between 1 and 50")
        if self.crawl_delay_seconds < 0:
            raise ValueError("crawl_delay_seconds cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class _ProductHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.title_parts: list[str] = []
        self.visible_parts: list[str] = []
        self._script_type: str | None = None
        self._script_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0
        self._visible_length = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        lowered_tag = tag.lower()
        if lowered_tag in {"style", "noscript", "svg"}:
            self._ignored_depth += 1
        if lowered_tag == "script":
            self._script_type = (attributes.get("type") or "").lower()
            self._script_parts = []
            self._ignored_depth += 1
        elif lowered_tag == "title":
            self._in_title = True
        elif lowered_tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        elif lowered_tag == "link":
            relationship = (attributes.get("rel") or "").lower().split()
            href = attributes.get("href")
            if "canonical" in relationship and href:
                self.canonical_url = href.strip()

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if lowered_tag == "script":
            if self._script_type == "application/ld+json":
                block = "".join(self._script_parts).strip()
                if block:
                    self.json_ld_blocks.append(block)
            self._script_type = None
            self._script_parts = []
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif lowered_tag in {"style", "noscript", "svg"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif lowered_tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_parts.append(data)
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._ignored_depth == 0 and self._visible_length < 12_000:
            remaining = 12_000 - self._visible_length
            accepted = text[:remaining]
            self.visible_parts.append(accepted)
            self._visible_length += len(accepted) + 1


def _default_resolve_host(host: str) -> Awaitable[Sequence[str]]:
    async def resolve() -> Sequence[str]:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            443,
            type=socket.SOCK_STREAM,
        )
        addresses: set[str] = set()
        for record in records:
            address = record[4][0]
            if isinstance(address, str):
                addresses.add(address)
        return tuple(sorted(addresses))

    return resolve()


class PublicCatalogConnector(CatalogConnector):
    capabilities = ConnectorCapabilities(
        supports_incremental_sync=False,
        supports_resume=True,
        supports_schema_discovery=True,
        supports_remote_validation=True,
    )

    def __init__(
        self,
        config: PublicCatalogConnectorConfig,
        *,
        client: httpx.AsyncClient | None = None,
        resolve_host: ResolveHost = _default_resolve_host,
        sleep: SleepCallable = asyncio.sleep,
    ) -> None:
        self.config = config
        self.source_type = config.source_type
        self._client = client
        self._resolve_host = resolve_host
        self._sleep = sleep
        self._robots: dict[str, RobotFileParser] = {}
        self._robot_delays: dict[str, float] = {}
        seed = config.start_url or config.product_urls[0]
        self._seed_url = self._normalize_url(seed)
        self._allowed_host = cast(str, urlparse(self._seed_url).hostname)

    async def validate(self) -> ConnectorValidation:
        try:
            urls = await self._discover_urls(validation_only=True)
            if not urls:
                return ConnectorValidation(
                    valid=False,
                    errors=("No authorized product URLs were discovered",),
                )
            if not await self._can_fetch(urls[0]):
                return ConnectorValidation(
                    valid=False,
                    errors=("Product URLs are blocked by robots.txt",),
                )
            return ConnectorValidation(
                valid=True,
                discovered_fields=(
                    "url",
                    "canonical_url",
                    "json_ld_product",
                    "html_fallback",
                ),
            )
        except PublicCatalogConnectorError as exc:
            return ConnectorValidation(valid=False, errors=(str(exc),))
        except httpx.HTTPError:
            return ConnectorValidation(
                valid=False,
                errors=("Public catalog connection validation failed",),
            )

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        urls = await self._discover_urls(validation_only=False)
        url_set_hash = hashlib.sha256(
            "\n".join(urls).encode("utf-8")
        ).hexdigest()
        prior_hash = (checkpoint or {}).get("url_set_hash")
        if prior_hash is not None and prior_hash != url_set_hash:
            raise PublicCatalogConnectorError(
                "Discovered URL set changed; restart the ingestion job"
            )
        start_index = int((checkpoint or {}).get("index", 0))
        records: list[ConnectorRecord] = []
        rejections: list[ConnectorRejection] = []
        processed = 0

        for index, url in enumerate(urls[start_index:], start=start_index):
            try:
                if not await self._can_fetch(url):
                    raise PublicCatalogConnectorError("Blocked by robots.txt")
                response = await self._request(url, expected="html")
                record = self._record_from_html(url, response)
                if record is None:
                    rejections.append(
                        ConnectorRejection(
                            index + 1,
                            "No product evidence found",
                            {"url": url},
                        )
                    )
                else:
                    records.append(record)
            except (PublicCatalogConnectorError, httpx.HTTPError) as exc:
                rejections.append(
                    ConnectorRejection(
                        index + 1,
                        str(exc),
                        {"url": url},
                    )
                )
            processed += 1
            delay = max(
                self.config.crawl_delay_seconds,
                self._crawl_delay_for(url),
            )
            if delay > 0 and index < len(urls) - 1:
                await self._sleep(delay)
            if processed >= page_size:
                yield ConnectorPage(
                    records=tuple(records),
                    rejections=tuple(rejections),
                    next_checkpoint={
                        "index": index + 1,
                        "url_set_hash": url_set_hash,
                    },
                )
                records = []
                rejections = []
                processed = 0

        if records or rejections:
            yield ConnectorPage(
                records=tuple(records),
                rejections=tuple(rejections),
                next_checkpoint={
                    "index": len(urls),
                    "url_set_hash": url_set_hash,
                },
            )

    async def _discover_urls(
        self,
        *,
        validation_only: bool,
    ) -> tuple[str, ...]:
        if self.config.source_type == "urls":
            candidates = self.config.product_urls[: self.config.max_products]
            normalized = [
                await self._validated_url(url) for url in candidates
            ]
            return tuple(dict.fromkeys(normalized))

        sitemap_url = await self._validated_url(
            cast(str, self.config.start_url)
        )
        discovered: list[str] = []
        pending = [sitemap_url]
        visited: set[str] = set()
        while pending and len(visited) < self.config.max_sitemaps:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            response = await self._request(current, expected="xml")
            child_sitemaps, product_urls = self._parse_sitemap(
                response.content
            )
            for child in child_sitemaps:
                child_url = await self._validated_url(
                    urljoin(current, child)
                )
                if child_url not in visited:
                    pending.append(child_url)
            for candidate in product_urls:
                product_url = await self._validated_url(
                    urljoin(current, candidate)
                )
                if product_url not in discovered:
                    discovered.append(product_url)
                if len(discovered) >= self.config.max_products:
                    return tuple(discovered)
            if validation_only and discovered:
                return tuple(discovered[:1])
        return tuple(discovered)

    async def _validated_url(self, value: str) -> str:
        normalized = self._normalize_url(value)
        parsed = urlparse(normalized)
        host = cast(str, parsed.hostname)
        if host != self._allowed_host:
            raise PublicCatalogConnectorError(
                "Cross-host catalog URLs are not allowed"
            )
        addresses = await self._resolve_host(host)
        if not addresses:
            raise PublicCatalogConnectorError(
                "Catalog host could not be resolved"
            )
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise PublicCatalogConnectorError(
                    "Catalog host resolution was invalid"
                ) from exc
            if not ip.is_global:
                raise PublicCatalogConnectorError(
                    "Catalog host must resolve to public IP addresses"
                )
        return normalized

    @staticmethod
    def _normalize_url(value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise PublicCatalogConnectorError(
                "Catalog URLs must use HTTPS"
            )
        if parsed.username or parsed.password or parsed.port is not None:
            raise PublicCatalogConnectorError(
                "Catalog URLs cannot contain credentials or ports"
            )
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        path = parsed.path or "/"
        return urlunparse(("https", host, path, "", parsed.query, ""))

    async def _request(
        self,
        url: str,
        *,
        expected: str,
    ) -> httpx.Response:
        current = await self._validated_url(url)
        for _ in range(_MAX_REDIRECTS + 1):
            response = await self._send(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise PublicCatalogConnectorError(
                        "Redirect location was missing"
                    )
                current = await self._validated_url(
                    urljoin(current, location)
                )
                continue
            response.raise_for_status()
            maximum = {
                "xml": _MAX_SITEMAP_BYTES,
                "html": _MAX_HTML_BYTES,
                "robots": _MAX_ROBOTS_BYTES,
            }.get(expected)
            if maximum is None:
                raise ValueError("Unsupported response expectation")
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise PublicCatalogConnectorError(
                        "Catalog response length was invalid"
                    ) from exc
                if declared_length > maximum:
                    raise PublicCatalogConnectorError(
                        "Catalog response exceeded size limit"
                    )
            if len(response.content) > maximum:
                raise PublicCatalogConnectorError(
                    "Catalog response exceeded size limit"
                )
            content_type = response.headers.get(
                "content-type",
                "",
            ).lower()
            if expected == "xml" and not any(
                value in content_type
                for value in ("xml", "text/plain", "octet-stream")
            ):
                raise PublicCatalogConnectorError(
                    "Sitemap response was not XML"
                )
            if expected == "html" and "html" not in content_type:
                raise PublicCatalogConnectorError(
                    "Product response was not HTML"
                )
            if expected == "robots" and not any(
                value in content_type for value in ("text/plain", "text/html")
            ):
                raise PublicCatalogConnectorError(
                    "Robots response was not text"
                )
            return response
        raise PublicCatalogConnectorError("Too many redirects")

    async def _send(self, url: str) -> httpx.Response:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,text/plain;q=0.9",
        }
        if self._client is not None:
            return await self._client.get(
                url,
                headers=headers,
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
            )
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds
        ) as client:
            return await client.get(
                url,
                headers=headers,
                follow_redirects=False,
            )

    async def _can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"https://{parsed.hostname}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            try:
                response = await self._request(
                    robots_url,
                    expected="robots",
                )
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    parser.parse([])
                else:
                    return False
            except (PublicCatalogConnectorError, httpx.HTTPError):
                return False
            self._robots[origin] = parser
            delay = parser.crawl_delay(USER_AGENT)
            if delay is None:
                delay = parser.crawl_delay("*")
            self._robot_delays[origin] = float(delay or 0)
        return parser.can_fetch(USER_AGENT, url)

    def _crawl_delay_for(self, url: str) -> float:
        parsed = urlparse(url)
        return self._robot_delays.get(f"https://{parsed.hostname}", 0.0)

    @staticmethod
    def _parse_sitemap(
        content: bytes,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        lowered = content.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise PublicCatalogConnectorError(
                "Sitemap XML declarations are not allowed"
            )
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise PublicCatalogConnectorError(
                "Sitemap XML was invalid"
            ) from exc
        local_name = root.tag.rsplit("}", 1)[-1].lower()
        locations = tuple(
            element.text.strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].lower() == "loc"
            and element.text
            and element.text.strip()
        )
        if local_name == "sitemapindex":
            return locations, ()
        if local_name == "urlset":
            return (), locations
        raise PublicCatalogConnectorError("Unsupported sitemap document")

    def _record_from_html(
        self,
        source_url: str,
        response: httpx.Response,
    ) -> ConnectorRecord | None:
        parser = _ProductHtmlParser()
        parser.feed(response.text)
        products: list[Mapping[str, Any]] = []
        warnings: list[str] = []
        for block in parser.json_ld_blocks:
            try:
                decoded = json.loads(block)
            except json.JSONDecodeError:
                warnings.append("invalid_json_ld")
                continue
            products.extend(self._find_products(decoded))
        canonical = self._normalize_canonical(
            source_url,
            parser.canonical_url,
        )
        fallback = {
            "title": " ".join(parser.title_parts).strip()
            or parser.meta.get("og:title"),
            "description": parser.meta.get("description")
            or parser.meta.get("og:description"),
            "image": parser.meta.get("og:image"),
            "visible_text": " ".join(parser.visible_parts)[:12_000],
        }
        if not products and not fallback["title"]:
            return None
        payload: dict[str, Any] = {
            "platform": "public_web",
            "source_url": source_url,
            "canonical_url": canonical,
            "extraction_method": (
                "json_ld" if products else "html_fallback"
            ),
            "products": [dict(product) for product in products],
            "html_fallback": fallback,
        }
        stable = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ConnectorRecord(
            external_id=canonical,
            record_type="product",
            payload=payload,
            content_hash=hashlib.sha256(
                stable.encode("utf-8")
            ).hexdigest(),
            source_updated_at=self._last_modified(response),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _normalize_canonical(
        self,
        source_url: str,
        canonical: str | None,
    ) -> str:
        if not canonical:
            return source_url
        try:
            normalized = self._normalize_url(
                urljoin(source_url, canonical)
            )
        except PublicCatalogConnectorError:
            return source_url
        if urlparse(normalized).hostname == self._allowed_host:
            return normalized
        return source_url

    @staticmethod
    def _find_products(value: object) -> list[Mapping[str, Any]]:
        found: list[Mapping[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                found.extend(
                    PublicCatalogConnector._find_products(item)
                )
            return found
        if not isinstance(value, dict):
            return found
        mapping = cast(Mapping[str, Any], value)
        type_value = mapping.get("@type")
        if isinstance(type_value, str):
            types = {type_value}
        elif isinstance(type_value, list):
            types = {
                item for item in type_value if isinstance(item, str)
            }
        else:
            types = set()
        if "Product" in types:
            found.append(mapping)
        for key in ("@graph", "itemListElement", "mainEntity"):
            if key in mapping:
                found.extend(
                    PublicCatalogConnector._find_products(mapping[key])
                )
        return found

    @staticmethod
    def _last_modified(response: httpx.Response) -> datetime | None:
        value = response.headers.get("last-modified")
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo is not None else None
