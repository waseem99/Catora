from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from catora_api.measurement.models import (
    MeasurementObservation,
    MeasurementProperty,
    MeasurementProvider,
    MeasurementProviderCapability,
)
from catora_api.measurement.provider import (
    MeasurementCapabilityUnavailable,
    MeasurementProviderError,
    MeasurementSourceProvider,
)

SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_SEARCH_CONSOLE_TZ = ZoneInfo("America/Los_Angeles")
_MAX_ROWS = 100_000


@dataclass(frozen=True, slots=True)
class GoogleResolvedCredential:
    account_id: str
    access_token: str


def _environment_secret(credential_reference: str) -> dict[str, Any]:
    if not credential_reference.startswith("env:"):
        raise MeasurementCapabilityUnavailable(
            "Google measurement credentials currently require a managed env: reference"
        )
    variable = credential_reference.removeprefix("env:").strip()
    if not variable or not variable.replace("_", "").isalnum() or variable.upper() != variable:
        raise MeasurementCapabilityUnavailable("Google measurement env reference is invalid")
    raw = os.environ.get(variable)
    if not raw:
        raise MeasurementCapabilityUnavailable(
            f"Google measurement credential secret {variable} is unavailable"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeasurementCapabilityUnavailable(
            "Google measurement service-account secret is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise MeasurementCapabilityUnavailable(
            "Google measurement service-account secret must be a JSON object"
        )
    required = {"client_email", "private_key", "token_uri"}
    if not required.issubset(value):
        raise MeasurementCapabilityUnavailable(
            "Google measurement service-account secret is incomplete"
        )
    return cast(dict[str, Any], value)


async def resolve_google_service_account(
    credential_reference: str,
    *,
    scopes: Iterable[str],
) -> GoogleResolvedCredential:
    info = _environment_secret(credential_reference)

    def refresh() -> GoogleResolvedCredential:
        try:
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=tuple(scopes),
            )
            credentials.refresh(GoogleAuthRequest())
        except (GoogleAuthError, ValueError) as exc:
            raise MeasurementCapabilityUnavailable(
                "Google service-account authentication failed"
            ) from exc
        if not credentials.token:
            raise MeasurementCapabilityUnavailable(
                "Google service account did not return an access token"
            )
        return GoogleResolvedCredential(
            account_id=str(info["client_email"]),
            access_token=str(credentials.token),
        )

    return await asyncio.to_thread(refresh)


def _observed_hash(
    *,
    provider: MeasurementProvider,
    property_id: str,
    metric_key: str,
    value_microunits: int,
    dimensions: dict[str, str],
    window_start: datetime,
    window_end: datetime,
) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "property": property_id,
            "metric": metric_key,
            "value": value_microunits,
            "dimensions": dimensions,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _microunits(value: object) -> int:
    try:
        return round(float(str(value)) * 1_000_000)
    except (TypeError, ValueError) as exc:
        raise MeasurementProviderError("Google returned a non-numeric metric") from exc


def _sync_dates(
    checkpoint: dict[str, str] | None,
    *,
    tz: ZoneInfo,
) -> tuple[date, date]:
    today = datetime.now(tz).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=27)
    if checkpoint:
        last = checkpoint.get("last_synced_at")
        if last:
            try:
                parsed = datetime.fromisoformat(last)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                overlap = parsed.astimezone(tz).date() - timedelta(days=3)
                start = max(start, overlap)
            except ValueError:
                pass
    if start > end:
        start = end
    return start, end


def _day_window(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _canonical_origin(site_url: str) -> str | None:
    if site_url.startswith("sc-domain:"):
        domain = site_url.removeprefix("sc-domain:").strip().strip("/")
        return f"https://{domain}" if domain else None
    parsed = urlsplit(site_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _json_object(response: httpx.Response, *, provider_name: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise MeasurementProviderError(
            f"{provider_name} returned a non-JSON response"
        ) from exc
    if not isinstance(value, dict):
        raise MeasurementProviderError(f"{provider_name} returned an invalid response")
    return cast(dict[str, Any], value)


@dataclass(frozen=True, slots=True)
class GoogleSearchConsoleProvider(MeasurementSourceProvider):
    access_token: str
    property_allowlist: tuple[str, ...]

    async def _json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise MeasurementProviderError(
                f"Search Console request failed with HTTP {response.status_code}"
            )
        return _json_object(response, provider_name="Search Console")

    async def discover_capabilities(self) -> tuple[MeasurementProviderCapability, ...]:
        await self.discover_properties()
        now = datetime.now(UTC)
        return (
            MeasurementProviderCapability(
                operation="properties.read",
                state="tested",
                scope="exact allowlisted Search Console properties",
                tested_at=now,
            ),
            MeasurementProviderCapability(
                operation="observations.read",
                state="tested",
                scope="aggregate Search Analytics rows; read-only",
                tested_at=now,
            ),
        )

    async def discover_properties(self) -> tuple[MeasurementProperty, ...]:
        value = await self._json("GET", "https://www.googleapis.com/webmasters/v3/sites")
        entries = value.get("siteEntry")
        rows = entries if isinstance(entries, list) else []
        accessible = {
            str(item.get("siteUrl")): str(item.get("permissionLevel"))
            for item in rows
            if isinstance(item, dict) and item.get("siteUrl")
        }
        unavailable = [
            item
            for item in self.property_allowlist
            if item not in accessible or accessible.get(item) == "siteUnverifiedUser"
        ]
        if unavailable:
            raise MeasurementCapabilityUnavailable(
                "Search Console service account lacks verified access to one or more allowlisted properties"
            )
        return tuple(
            MeasurementProperty(
                provider="google_search_console",
                external_property_id=site_url,
                property_type="site",
                display_name=site_url,
                canonical_origin=_canonical_origin(site_url),
                timezone="America/Los_Angeles",
            )
            for site_url in self.property_allowlist
        )

    async def observations(
        self,
        property: MeasurementProperty,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[MeasurementObservation]:
        if property.external_property_id not in self.property_allowlist:
            raise MeasurementCapabilityUnavailable("Search Console property is outside the allowlist")
        start_date, end_date = _sync_dates(checkpoint, tz=_SEARCH_CONSOLE_TZ)
        row_limit = 25_000
        start_row = 0
        observed_at = datetime.now(UTC)
        total = 0
        while total < _MAX_ROWS:
            encoded_site = quote(property.external_property_id, safe="")
            value = await self._json(
                "POST",
                f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query",
                payload={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "dimensions": ["date", "page", "query"],
                    "dataState": "final",
                    "rowLimit": row_limit,
                    "startRow": start_row,
                },
            )
            rows_value = value.get("rows")
            rows = rows_value if isinstance(rows_value, list) else []
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                keys_value = row.get("keys")
                keys = keys_value if isinstance(keys_value, list) else []
                if len(keys) < 3:
                    continue
                try:
                    day = datetime.strptime(str(keys[0]), "%Y-%m-%d").date()
                except ValueError as exc:
                    raise MeasurementProviderError(
                        "Search Console returned an invalid date dimension"
                    ) from exc
                window_start, window_end = _day_window(day, _SEARCH_CONSOLE_TZ)
                dimensions = {
                    "date": day.isoformat(),
                    "page": str(keys[1]),
                    "query": str(keys[2]),
                }
                for metric_key in ("clicks", "impressions", "ctr", "position"):
                    value_microunits = _microunits(row.get(metric_key, 0))
                    yield MeasurementObservation(
                        provider="google_search_console",
                        external_property_id=property.external_property_id,
                        metric_key=metric_key,
                        metric_version="search-console/v1",
                        value_microunits=value_microunits,
                        dimensions=dimensions,
                        window_start=window_start,
                        window_end=window_end,
                        timezone=property.timezone,
                        sample_state="partial",
                        freshness_state="current",
                        source_definition={
                            "api": "searchAnalytics.query",
                            "data_state": "final",
                            "aggregation": "date,page,query",
                            "bounded_top_rows": True,
                        },
                        observed_at=observed_at,
                        observation_hash=_observed_hash(
                            provider="google_search_console",
                            property_id=property.external_property_id,
                            metric_key=metric_key,
                            value_microunits=value_microunits,
                            dimensions=dimensions,
                            window_start=window_start,
                            window_end=window_end,
                        ),
                    )
            count = len(rows)
            total += count
            if count < row_limit:
                break
            start_row += count


@dataclass(frozen=True, slots=True)
class GoogleAnalyticsProvider(MeasurementSourceProvider):
    access_token: str
    property_allowlist: tuple[str, ...]

    def _normalized_allowlist(self) -> tuple[str, ...]:
        return tuple(
            value if value.startswith("properties/") else f"properties/{value}"
            for value in self.property_allowlist
        )

    async def _json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                json=payload,
                params=params,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise MeasurementProviderError(
                f"Google Analytics request failed with HTTP {response.status_code}"
            )
        return _json_object(response, provider_name="Google Analytics")

    async def discover_capabilities(self) -> tuple[MeasurementProviderCapability, ...]:
        await self.discover_properties()
        now = datetime.now(UTC)
        return (
            MeasurementProviderCapability(
                operation="properties.read",
                state="tested",
                scope="exact allowlisted GA4 properties",
                tested_at=now,
            ),
            MeasurementProviderCapability(
                operation="observations.read",
                state="tested",
                scope="aggregate GA4 reporting rows; read-only",
                tested_at=now,
            ),
        )

    async def discover_properties(self) -> tuple[MeasurementProperty, ...]:
        allowed = set(self._normalized_allowlist())
        summaries: dict[str, dict[str, Any]] = {}
        page_token = ""
        while True:
            params: dict[str, str | int] = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token
            value = await self._json(
                "GET",
                "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                params=params,
            )
            accounts_value = value.get("accountSummaries")
            accounts = accounts_value if isinstance(accounts_value, list) else []
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                properties_value = account.get("propertySummaries")
                property_summaries = (
                    properties_value if isinstance(properties_value, list) else []
                )
                for summary in property_summaries:
                    if not isinstance(summary, dict):
                        continue
                    property_name = str(summary.get("property") or "")
                    if property_name in allowed:
                        summaries[property_name] = cast(dict[str, Any], summary)
            page_token = str(value.get("nextPageToken") or "")
            if not page_token:
                break
        missing = sorted(allowed - summaries.keys())
        if missing:
            raise MeasurementCapabilityUnavailable(
                "Google Analytics service account lacks access to one or more allowlisted properties"
            )
        result: list[MeasurementProperty] = []
        for property_name in self._normalized_allowlist():
            summary = summaries[property_name]
            metadata = await self._json(
                "GET",
                f"https://analyticsadmin.googleapis.com/v1beta/{property_name}",
            )
            result.append(
                MeasurementProperty(
                    provider="ga4",
                    external_property_id=property_name.removeprefix("properties/"),
                    property_type="web_stream",
                    display_name=str(summary.get("displayName") or property_name),
                    timezone=str(metadata.get("timeZone") or "UTC"),
                    currency=str(metadata.get("currencyCode") or "USD")[:3],
                )
            )
        return tuple(result)

    async def observations(
        self,
        property: MeasurementProperty,
        *,
        checkpoint: dict[str, str] | None = None,
    ) -> AsyncIterator[MeasurementObservation]:
        resource = f"properties/{property.external_property_id}"
        if resource not in set(self._normalized_allowlist()):
            raise MeasurementCapabilityUnavailable("GA4 property is outside the allowlist")
        try:
            tz = ZoneInfo(property.timezone)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        start_date, end_date = _sync_dates(checkpoint, tz=tz)
        limit = 10_000
        offset = 0
        observed_at = datetime.now(UTC)
        total = 0
        while total < _MAX_ROWS:
            response = await self._json(
                "POST",
                f"https://analyticsdata.googleapis.com/v1beta/{resource}:runReport",
                payload={
                    "dateRanges": [
                        {
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                        }
                    ],
                    "dimensions": [
                        {"name": "date"},
                        {"name": "landingPagePlusQueryString"},
                        {"name": "sessionSource"},
                        {"name": "sessionMedium"},
                    ],
                    "metrics": [
                        {"name": "sessions"},
                        {"name": "activeUsers"},
                        {"name": "screenPageViews"},
                    ],
                    "limit": str(limit),
                    "offset": str(offset),
                    "keepEmptyRows": False,
                },
            )
            rows_value = response.get("rows")
            rows = rows_value if isinstance(rows_value, list) else []
            dimension_headers_value = response.get("dimensionHeaders")
            metric_headers_value = response.get("metricHeaders")
            dimension_headers = (
                dimension_headers_value if isinstance(dimension_headers_value, list) else []
            )
            metric_headers = metric_headers_value if isinstance(metric_headers_value, list) else []
            dimension_names = [
                str(item.get("name")) for item in dimension_headers if isinstance(item, dict)
            ]
            metric_names = [
                str(item.get("name")) for item in metric_headers if isinstance(item, dict)
            ]
            metadata_value = response.get("metadata")
            data_loss = bool(
                isinstance(metadata_value, dict)
                and metadata_value.get("dataLossFromOtherRow")
            )
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                dimension_values_value = row.get("dimensionValues")
                metric_values_value = row.get("metricValues")
                dimension_values = (
                    dimension_values_value if isinstance(dimension_values_value, list) else []
                )
                metric_values = metric_values_value if isinstance(metric_values_value, list) else []
                raw_dimensions = {
                    name: str(value.get("value") or "")
                    for name, value in zip(dimension_names, dimension_values, strict=False)
                    if isinstance(value, dict)
                }
                raw_date = raw_dimensions.get("date", "")
                if len(raw_date) != 8 or not raw_date.isdigit():
                    raise MeasurementProviderError(
                        "Google Analytics returned an invalid date dimension"
                    )
                day = datetime.strptime(raw_date, "%Y%m%d").date()
                window_start, window_end = _day_window(day, tz)
                dimensions = {
                    "date": day.isoformat(),
                    "landing_page": raw_dimensions.get("landingPagePlusQueryString", ""),
                    "session_source": raw_dimensions.get("sessionSource", ""),
                    "session_medium": raw_dimensions.get("sessionMedium", ""),
                }
                for metric_name, metric_value in zip(
                    metric_names,
                    metric_values,
                    strict=False,
                ):
                    if not isinstance(metric_value, dict):
                        continue
                    value_microunits = _microunits(metric_value.get("value", 0))
                    yield MeasurementObservation(
                        provider="ga4",
                        external_property_id=property.external_property_id,
                        metric_key=metric_name,
                        metric_version="ga4-data/v1beta",
                        value_microunits=value_microunits,
                        dimensions=dimensions,
                        window_start=window_start,
                        window_end=window_end,
                        timezone=property.timezone,
                        sample_state="partial" if data_loss else "complete",
                        freshness_state="current",
                        source_definition={
                            "api": "properties.runReport",
                            "dimensions": "date,landingPagePlusQueryString,sessionSource,sessionMedium",
                            "aggregate_only": True,
                        },
                        observed_at=observed_at,
                        observation_hash=_observed_hash(
                            provider="ga4",
                            property_id=property.external_property_id,
                            metric_key=metric_name,
                            value_microunits=value_microunits,
                            dimensions=dimensions,
                            window_start=window_start,
                            window_end=window_end,
                        ),
                    )
            count = len(rows)
            total += count
            if count < limit:
                break
            offset += count


async def google_provider_from_reference(
    *,
    provider: Literal["google_search_console", "ga4"],
    credential_reference: str,
    property_allowlist: tuple[str, ...],
) -> tuple[MeasurementSourceProvider, str]:
    if not property_allowlist:
        raise MeasurementCapabilityUnavailable("Google measurement property allowlist is required")
    scopes = (
        (SEARCH_CONSOLE_SCOPE,)
        if provider == "google_search_console"
        else (ANALYTICS_SCOPE,)
    )
    credential = await resolve_google_service_account(
        credential_reference,
        scopes=scopes,
    )
    if provider == "google_search_console":
        return (
            GoogleSearchConsoleProvider(
                access_token=credential.access_token,
                property_allowlist=property_allowlist,
            ),
            credential.account_id,
        )
    return (
        GoogleAnalyticsProvider(
            access_token=credential.access_token,
            property_allowlist=property_allowlist,
        ),
        credential.account_id,
    )
