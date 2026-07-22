from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from catora_api.db.models.intents import BuyerIntent
from catora_api.intents.types import StructuredBuyerIntent


class BuyerIntentError(RuntimeError):
    pass


class BuyerIntentNotFoundError(BuyerIntentError):
    pass


class BuyerIntentVersionConflictError(BuyerIntentError):
    pass


class BuyerIntentStateError(BuyerIntentError):
    pass


@dataclass(frozen=True, slots=True)
class BuyerIntentPage:
    items: tuple[BuyerIntent, ...]
    total: int


class BuyerIntentService:
    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        name: str,
        source: str,
        structured_intent: StructuredBuyerIntent,
    ) -> BuyerIntent:
        intent = BuyerIntent(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            lineage_id=uuid.uuid4(),
            supersedes_id=None,
            name=name,
            query=structured_intent.query,
            structured_intent=structured_intent.model_dump(mode="json"),
            source=source,
            version=1,
            approval_status="draft",
        )
        session.add(intent)
        await session.flush()
        return intent

    async def latest(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        lineage_id: uuid.UUID,
        for_update: bool = False,
    ) -> BuyerIntent:
        query = select(BuyerIntent).where(
            BuyerIntent.workspace_id == workspace_id,
            BuyerIntent.lineage_id == lineage_id,
        ).order_by(BuyerIntent.version.desc()).limit(1)
        if for_update:
            query = query.with_for_update()
        intent = await session.scalar(query)
        if intent is None:
            raise BuyerIntentNotFoundError("Buyer intent not found")
        return intent

    async def list_latest(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        approval_status: str | None,
        source: str | None,
        offset: int,
        limit: int,
    ) -> BuyerIntentPage:
        query = _latest_query(workspace_id)
        if approval_status is not None:
            query = query.where(BuyerIntent.approval_status == approval_status)
        if source is not None:
            query = query.where(BuyerIntent.source == source)
        total = int(
            (
                await session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
            )
            or 0
        )
        items = (
            await session.scalars(
                query.order_by(BuyerIntent.updated_at.desc(), BuyerIntent.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return BuyerIntentPage(items=tuple(items), total=total)

    async def versions(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        lineage_id: uuid.UUID,
        offset: int,
        limit: int,
    ) -> BuyerIntentPage:
        query = select(BuyerIntent).where(
            BuyerIntent.workspace_id == workspace_id,
            BuyerIntent.lineage_id == lineage_id,
        )
        total = int(
            (
                await session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
            )
            or 0
        )
        if total == 0:
            raise BuyerIntentNotFoundError("Buyer intent not found")
        items = (
            await session.scalars(
                query.order_by(BuyerIntent.version.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return BuyerIntentPage(items=tuple(items), total=total)

    async def revise(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        lineage_id: uuid.UUID,
        expected_version: int,
        name: str,
        structured_intent: StructuredBuyerIntent,
    ) -> BuyerIntent:
        current = await self.latest(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            for_update=True,
        )
        _require_version(current, expected_version)
        if current.approval_status == "draft":
            current.approval_status = "superseded"
        revised = BuyerIntent(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            supersedes_id=current.id,
            name=name,
            query=structured_intent.query,
            structured_intent=structured_intent.model_dump(mode="json"),
            source=current.source,
            version=current.version + 1,
            approval_status="draft",
        )
        session.add(revised)
        await session.flush()
        return revised

    async def approve(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        lineage_id: uuid.UUID,
        expected_version: int,
    ) -> BuyerIntent:
        current = await self.latest(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            for_update=True,
        )
        _require_version(current, expected_version)
        if current.approval_status == "approved":
            raise BuyerIntentStateError("Buyer intent version is already approved")
        if current.approval_status != "draft":
            raise BuyerIntentStateError("Only a draft buyer intent can be approved")
        previous_approved = (
            await session.scalars(
                select(BuyerIntent)
                .where(
                    BuyerIntent.workspace_id == workspace_id,
                    BuyerIntent.lineage_id == lineage_id,
                    BuyerIntent.id != current.id,
                    BuyerIntent.approval_status == "approved",
                )
                .with_for_update()
            )
        ).all()
        for previous in previous_approved:
            previous.approval_status = "superseded"
        current.approval_status = "approved"
        await session.flush()
        return current


def _latest_query(workspace_id: uuid.UUID) -> Select[tuple[BuyerIntent]]:
    newer = aliased(BuyerIntent)
    newest_version = (
        select(func.max(newer.version))
        .where(
            newer.workspace_id == BuyerIntent.workspace_id,
            newer.lineage_id == BuyerIntent.lineage_id,
        )
        .correlate(BuyerIntent)
        .scalar_subquery()
    )
    return select(BuyerIntent).where(
        BuyerIntent.workspace_id == workspace_id,
        BuyerIntent.version == newest_version,
    )


def _require_version(intent: BuyerIntent, expected_version: int) -> None:
    if intent.version != expected_version:
        raise BuyerIntentVersionConflictError(
            f"Buyer intent version changed; expected {expected_version}, found {intent.version}"
        )
