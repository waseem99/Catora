from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from catora_api.db.models import ReportJob
from catora_api.shopify.sync import _installation_actor


class ScalarSession:
    def __init__(self, values: list[uuid.UUID | None]) -> None:
        self.values = values
        self.calls = 0

    async def scalar(self, _statement: object) -> uuid.UUID | None:
        self.calls += 1
        return self.values.pop(0)


def _installation(*, distribution: str | None) -> ReportJob:
    snapshot: dict[str, object] = {
        "shop_domain": "prospect-store.myshopify.com",
    }
    if distribution is not None:
        snapshot["distribution"] = distribution
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status="active",
        input_snapshot=snapshot,
        template_version="shopify-installation-v1",
    )


@pytest.mark.asyncio
async def test_public_installation_uses_invitation_issuer_as_sync_actor() -> None:
    invitation_issuer = uuid.uuid4()
    installation = _installation(distribution="public")
    session = ScalarSession([None, invitation_issuer])

    actor = await _installation_actor(
        cast(Any, session),
        installation=installation,
        snapshot=dict(installation.input_snapshot),
        actor_user_id=None,
    )

    assert actor == invitation_issuer
    assert session.calls == 2


@pytest.mark.asyncio
async def test_custom_installation_does_not_query_public_invitation() -> None:
    installation = _installation(distribution=None)
    session = ScalarSession([None])

    actor = await _installation_actor(
        cast(Any, session),
        installation=installation,
        snapshot=dict(installation.input_snapshot),
        actor_user_id=None,
    )

    assert actor is None
    assert session.calls == 1
