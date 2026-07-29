from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from catora_api.config import Settings
from catora_api.connectors.public_catalog import PublicCatalogConnector, PublicCatalogConnectorConfig
from catora_api.connectors.wordpress import WordPressSnapshotConnector
from catora_api.db.models.catalog import CatalogSource
from catora_api.schemas.service_visibility import WordPressSnapshotBatch
from catora_api.service_visibility.analysis import QUESTION_TEMPLATES, analyze_service_site
from catora_api.service_visibility.security import ServiceVisibilityAuthenticator

PUBLIC_IP = "93.184.216.34"


async def public_resolver(_: str) -> Sequence[str]:
    return (PUBLIC_IP,)


def _service_html() -> str:
    organization = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Example Technology",
    }
    return f"""
    <html>
      <head>
        <title>Cloud Migration Services | Example Technology</title>
        <meta name="description" content="Cloud migration for regulated technology teams">
        <meta name="generator" content="WordPress 6.8">
        <link rel="canonical" href="/services/cloud-migration">
        <script type="application/ld+json">{json.dumps(organization)}</script>
      </head>
      <body class="page page-id-42 elementor-page">
        <h1>Cloud Migration Services</h1>
        <h2>Our process</h2>
        <p>We help technology companies migrate to AWS and Azure. Our process includes discovery,
        implementation, security review, and support. A client project reduced infrastructure cost
        by 25 percent in twelve weeks.</p>
        <a href="/case-studies/fintech-cloud">Read the case study</a>
        <a href="/contact">Book a consultation</a>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_wordpress_public_connector_retains_service_page_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        if request.url.path == "/wp-sitemap.xml":
            return httpx.Response(
                200,
                text=(
                    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/services/cloud-migration</loc></url></urlset>"
                ),
                headers={"content-type": "application/xml"},
            )
        return httpx.Response(
            200,
            text=_service_html(),
            headers={"content-type": "text/html", "last-modified": "Wed, 29 Jul 2026 05:00:00 GMT"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = PublicCatalogConnector(
            PublicCatalogConnectorConfig(
                source_type="wordpress",
                start_url="https://example.com/wp-sitemap.xml",
                authorized_domain_confirmed=True,
                crawl_delay_seconds=0,
            ),
            client=client,
            resolve_host=public_resolver,
        )
        pages = [page async for page in connector.pages()]

    record = pages[0].records[0]
    assert record.record_type == "service_page"
    assert record.payload["title"].startswith("Cloud Migration")
    assert record.payload["headings"][0] == {"level": "h1", "text": "Cloud Migration Services"}
    assert record.payload["wordpress"]["is_wordpress"] is True
    assert record.payload["wordpress"]["builder"] == "elementor"
    assert "https://example.com/contact" in record.payload["links"]


def test_service_visibility_analysis_is_deterministic_and_evidence_backed() -> None:
    payload = {
        "source_url": "https://example.com/services/cloud-migration",
        "canonical_url": "https://example.com/services/cloud-migration",
        "title": "Cloud Migration Services | Example Technology",
        "meta_description": "Cloud migration for regulated technology teams",
        "robots": "",
        "headings": [
            {"level": "h1", "text": "Cloud Migration Services"},
            {"level": "h2", "text": "Our process"},
        ],
        "links": ["https://example.com/contact"],
        "visible_text": (
            "We help technology companies with cloud migration. Our process includes discovery, "
            "implementation, security review, and managed support. A client case study reduced "
            "infrastructure cost by 25 percent in twelve weeks. Contact us to book a consultation."
        ),
        "json_ld": [{"@type": "Organization", "name": "Example Technology"}],
        "wordpress": {"post_id": 42, "revision": "2026-07-29 05:00:00"},
    }
    first = analyze_service_site(
        source_id=str(uuid.uuid4()),
        ingestion_job_id=str(uuid.uuid4()),
        site_url="https://example.com",
        records=[(payload, "a" * 64, datetime.now(UTC))],
    )
    second = analyze_service_site(
        source_id=first.source_id,
        ingestion_job_id=first.ingestion_job_id,
        site_url="https://example.com",
        records=[(payload, "a" * 64, datetime.now(UTC))],
        prior_report_id="prior",
        prior_fingerprints={finding.fingerprint for finding in first.findings},
    )

    assert len(QUESTION_TEMPLATES) == 25
    assert len(first.buyer_questions) == 25
    assert first.site.company_name == "Example Technology"
    assert first.site.service_names == ["Cloud Migration Services"]
    assert first.scorecard.model_dump() == second.scorecard.model_dump()
    assert second.continuity.persisting_findings == len(first.findings)
    assert all(finding.evidence or finding.page_url is None for finding in first.findings)
    assert all("guarantee" not in item.casefold() for item in first.executive_summary)


class _MemoryStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def get_bytes(self, _: str) -> bytes:
        return self.content


@pytest.mark.asyncio
async def test_wordpress_snapshot_connector_emits_immutable_page_records() -> None:
    snapshot_id = uuid.uuid4()
    payload = {
        "snapshot_id": str(snapshot_id),
        "sequence": 0,
        "records": [
            {
                "url": "https://example.com/services/cloud",
                "title": "Cloud service",
                "visible_text": "We help teams migrate cloud systems.",
                "wordpress": {"post_id": 7, "revision": "2026-07-29 05:00:00"},
            }
        ],
    }
    content = json.dumps(payload, separators=(",", ":")).encode()
    connector = WordPressSnapshotConnector(
        config={
            "service_visibility_snapshot": {
                "status": "complete",
                "batches": [
                    {
                        "object_key": "snapshot/0.json",
                        "checksum": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        },
        storage=_MemoryStorage(content),  # type: ignore[arg-type]
    )

    pages = [page async for page in connector.pages()]

    assert pages[0].records[0].external_id == "https://example.com/services/cloud"
    assert pages[0].records[0].record_type == "service_page"
    assert pages[0].next_checkpoint == {"batch_sequence": 1}


def _settings() -> Settings:
    key = base64.urlsafe_b64encode(b"s" * 32).decode()
    return Settings(
        service_visibility_enabled=True,
        service_visibility_credential_encryption_key=key,
    )


def _signed_request(*, path: str, body: bytes, token: str) -> Request:
    timestamp = str(int(datetime.now(UTC).timestamp()))
    content_hash = hashlib.sha256(body).hexdigest()
    key = "snapshot:test:00000000"
    canonical = "\n".join(("POST", path, timestamp, content_hash, key))
    signature = base64.urlsafe_b64encode(
        hmac.new(token.encode(), canonical.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (b"x-catora-timestamp", timestamp.encode()),
                (b"x-catora-content-sha256", content_hash.encode()),
                (b"x-catora-idempotency-key", key.encode()),
                (b"x-catora-signature", signature.encode()),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("api.example.com", 443),
        }
    )


@pytest.mark.asyncio
async def test_service_visibility_bridge_authentication_fails_closed() -> None:
    settings = _settings()
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="WordPress service site",
        source_type="wordpress",
        status="ready",
        config={"connection_mode": "wordpress_bridge"},
    )
    authenticator = ServiceVisibilityAuthenticator(settings)
    credential = authenticator.rotate(source)
    body = b'{"snapshot_id":"00000000-0000-0000-0000-000000000000"}'
    path = f"/api/v1/service-visibility/sources/{source.id}/snapshots"

    await authenticator.authenticate(
        _signed_request(path=path, body=body, token=credential.token),
        source=source,
        body=body,
    )
    with pytest.raises(Exception, match="signature is invalid"):
        await authenticator.authenticate(
            _signed_request(path=path, body=body, token="wrong-token"),
            source=source,
            body=body,
        )


def test_wordpress_plugin_is_draft_only_and_excludes_private_data() -> None:
    plugin = (
        Path(__file__).parents[2]
        / "wordpress-service-visibility"
        / "includes"
        / "class-catora-service-visibility.php"
    ).read_text()
    assert "'post_status'  => 'draft'" in plugin
    assert "wp_update_post" not in plugin
    assert "post_status'    => 'publish'" in plugin
    assert "has_password'   => false" in plugin
    assert "get_users" not in plugin
    assert "wc_get_orders" not in plugin
    assert "get_option( 'woocommerce" not in plugin
