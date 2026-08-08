from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from celery import shared_task
from sqlalchemy import select

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models.measurement import MeasurementProviderAccount
from catora_api.measurement.google import google_provider_from_reference
from catora_api.measurement.service import MeasurementService

_GOOGLE_PROVIDERS = {"google_search_console", "ga4"}


def _property_allowlist(account: MeasurementProviderAccount) -> tuple[str, ...]:
    configuration = account.sync_checkpoint.get("configuration")
    if not isinstance(configuration, dict):
        return ()
    values = configuration.get("property_allowlist")
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if isinstance(value, str) and value)


@shared_task(name="catora.measurement.sync_google", ignore_result=True)  # type: ignore[misc]
def sync_google_measurements() -> None:
    asyncio.run(_sync_google_measurements())


async def _sync_google_measurements() -> None:
    if not get_settings().measurement_connectors_enabled:
        return
    async with SessionFactory() as session:
        account_ids = list(
            (
                await session.scalars(
                    select(MeasurementProviderAccount.id).where(
                        MeasurementProviderAccount.status == "ready",
                        MeasurementProviderAccount.provider.in_(_GOOGLE_PROVIDERS),
                    )
                )
            ).all()
        )
    for account_id in account_ids:
        await _sync_one(account_id)


async def _sync_one(account_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        account = await session.get(MeasurementProviderAccount, account_id)
        if (
            account is None
            or account.status != "ready"
            or account.provider not in _GOOGLE_PROVIDERS
        ):
            return
        allowlist = _property_allowlist(account)
        if not allowlist:
            return
        try:
            provider_name = cast(
                Literal["google_search_console", "ga4"],
                account.provider,
            )
            provider, external_account_id = await google_provider_from_reference(
                provider=provider_name,
                credential_reference=account.credential_reference,
                property_allowlist=allowlist,
            )
            if external_account_id != account.external_account_id:
                raise ValueError("Managed Google credential no longer matches the account")
            await MeasurementService().sync_account(
                session,
                workspace_id=account.workspace_id,
                actor_user_id=None,
                account_id=account.id,
                provider=provider,
            )
        except Exception as exc:
            await session.rollback()
            failed = await session.get(MeasurementProviderAccount, account_id)
            if failed is None:
                return
            configuration = failed.sync_checkpoint.get("configuration")
            failed.sync_checkpoint = {
                **(
                    {"configuration": configuration}
                    if isinstance(configuration, dict)
                    else {}
                ),
                "last_failed_at": datetime.now(UTC).isoformat(),
                "last_error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
            await session.commit()
