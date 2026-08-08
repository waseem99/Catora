from __future__ import annotations

from typing import Any

import pytest

from catora_api.measurement.google import (
    GoogleAnalyticsProvider,
    GoogleSearchConsoleProvider,
)
from catora_api.measurement.provider import MeasurementCapabilityUnavailable


@pytest.mark.asyncio
async def test_search_console_is_exactly_allowlisted_and_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_json(
        self: GoogleSearchConsoleProvider,
        method: str,
        url: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        del self
        if method == "GET":
            assert url.endswith("/webmasters/v3/sites")
            return {
                "siteEntry": [
                    {
                        "siteUrl": "sc-domain:hilariousai.io",
                        "permissionLevel": "siteFullUser",
                    },
                    {
                        "siteUrl": "sc-domain:unrelated.example",
                        "permissionLevel": "siteOwner",
                    },
                ]
            }
        assert payload is not None
        assert "sc-domain%3Ahilariousai.io" in url
        assert payload["dimensions"] == ["date", "page", "query"]
        assert payload["dataState"] == "final"
        return {
            "rows": [
                {
                    "keys": [
                        "2026-08-01",
                        "https://hilariousai.io/service/ai-development/",
                        "ai development company",
                    ],
                    "clicks": 3,
                    "impressions": 120,
                    "ctr": 0.025,
                    "position": 8.4,
                }
            ]
        }

    monkeypatch.setattr(GoogleSearchConsoleProvider, "_json", fake_json)
    provider = GoogleSearchConsoleProvider(
        access_token="test-token",
        property_allowlist=("sc-domain:hilariousai.io",),
    )
    properties = await provider.discover_properties()
    assert [item.external_property_id for item in properties] == ["sc-domain:hilariousai.io"]
    assert properties[0].canonical_origin == "https://hilariousai.io"

    observations = [item async for item in provider.observations(properties[0])]
    assert {item.metric_key for item in observations} == {
        "clicks",
        "impressions",
        "ctr",
        "position",
    }
    assert all(item.provider == "google_search_console" for item in observations)
    assert all(
        set(item.dimensions) == {"date", "page", "query"} for item in observations
    )
    clicks = next(item for item in observations if item.metric_key == "clicks")
    assert clicks.value_microunits == 3_000_000


@pytest.mark.asyncio
async def test_search_console_rejects_unverified_allowlisted_property(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_json(
        self: GoogleSearchConsoleProvider,
        method: str,
        url: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        del self, method, url, payload
        return {
            "siteEntry": [
                {
                    "siteUrl": "sc-domain:hilariousai.io",
                    "permissionLevel": "siteUnverifiedUser",
                }
            ]
        }

    monkeypatch.setattr(GoogleSearchConsoleProvider, "_json", fake_json)
    provider = GoogleSearchConsoleProvider(
        access_token="test-token",
        property_allowlist=("sc-domain:hilariousai.io",),
    )
    with pytest.raises(MeasurementCapabilityUnavailable):
        await provider.discover_properties()


@pytest.mark.asyncio
async def test_ga4_discovers_only_allowlisted_property_and_emits_aggregate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_json(
        self: GoogleAnalyticsProvider,
        method: str,
        url: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        del self, params
        if method == "GET" and url.endswith("/accountSummaries"):
            return {
                "accountSummaries": [
                    {
                        "account": "accounts/1",
                        "displayName": "Hilarious",
                        "propertySummaries": [
                            {
                                "property": "properties/123456789",
                                "displayName": "Hilarious AI",
                                "propertyType": "PROPERTY_TYPE_ORDINARY",
                            },
                            {
                                "property": "properties/999999999",
                                "displayName": "Unrelated",
                                "propertyType": "PROPERTY_TYPE_ORDINARY",
                            },
                        ],
                    }
                ]
            }
        if method == "GET" and url.endswith("/properties/123456789"):
            return {
                "name": "properties/123456789",
                "displayName": "Hilarious AI",
                "timeZone": "Asia/Karachi",
                "currencyCode": "USD",
            }
        assert method == "POST"
        assert url.endswith("/v1beta/properties/123456789:runReport")
        assert payload is not None
        assert payload["dimensions"] == [
            {"name": "date"},
            {"name": "landingPagePlusQueryString"},
            {"name": "sessionSource"},
            {"name": "sessionMedium"},
        ]
        return {
            "dimensionHeaders": [
                {"name": "date"},
                {"name": "landingPagePlusQueryString"},
                {"name": "sessionSource"},
                {"name": "sessionMedium"},
            ],
            "metricHeaders": [
                {"name": "sessions", "type": "TYPE_INTEGER"},
                {"name": "activeUsers", "type": "TYPE_INTEGER"},
                {"name": "screenPageViews", "type": "TYPE_INTEGER"},
            ],
            "rows": [
                {
                    "dimensionValues": [
                        {"value": "20260801"},
                        {"value": "/service/ai-development/"},
                        {"value": "google"},
                        {"value": "organic"},
                    ],
                    "metricValues": [
                        {"value": "12"},
                        {"value": "9"},
                        {"value": "18"},
                    ],
                }
            ],
            "metadata": {"dataLossFromOtherRow": False},
        }

    monkeypatch.setattr(GoogleAnalyticsProvider, "_json", fake_json)
    provider = GoogleAnalyticsProvider(
        access_token="test-token",
        property_allowlist=("123456789",),
    )
    properties = await provider.discover_properties()
    assert [item.external_property_id for item in properties] == ["123456789"]
    assert properties[0].timezone == "Asia/Karachi"

    observations = [item async for item in provider.observations(properties[0])]
    assert {item.metric_key for item in observations} == {
        "sessions",
        "activeUsers",
        "screenPageViews",
    }
    assert all(item.provider == "ga4" for item in observations)
    assert all(
        set(item.dimensions)
        == {"date", "landing_page", "session_source", "session_medium"}
        for item in observations
    )
    sessions = next(item for item in observations if item.metric_key == "sessions")
    assert sessions.value_microunits == 12_000_000
    assert sessions.dimensions["session_medium"] == "organic"
