from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import IngestionJob, ReportJob, ShopifyStoreInvitation
from catora_api.schemas.shopify_public import (
    ShopifyPublicOperatorInstallationView,
)
from catora_api.shopify.installations import SHOPIFY_INSTALLATION_TYPE
from catora_api.shopify.invitations import ShopifyInvitationService
from catora_api.shopify.public_installations import ShopifyPublicInstallationService
from catora_api.shopify.recovery import prepare_shopify_operator_recovery
from catora_api.shopify.sync import ACTIVE_JOB_STATUSES, queue_shopify_sync
from catora_api.shopify.webhooks import SHOPIFY_WEBHOOK_DELIVERY_TYPE

router = APIRouter(tags=["shopify public app operations"])


def _require_source_management(role: str) -> None:
    if not can(Role(role), "sources.write"):
        raise AuthorizationError("Catalog source management permission required")


def _text(snapshot: dict[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _integer(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _boolean(snapshot: dict[str, object], key: str) -> bool:
    return snapshot.get(key) is True


def _uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = _text(snapshot, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _datetime(snapshot: dict[str, object], key: str) -> datetime | None:
    value = _text(snapshot, key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _latest_webhook(
    session: SessionDependency,
    *,
    workspace_id: uuid.UUID,
    installation_id: uuid.UUID,
) -> ReportJob | None:
    deliveries = list(
        (
            await session.scalars(
                select(ReportJob)
                .where(
                    ReportJob.workspace_id == workspace_id,
                    ReportJob.report_type == SHOPIFY_WEBHOOK_DELIVERY_TYPE,
                )
                .order_by(ReportJob.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    expected = str(installation_id)
    return next(
        (
            delivery
            for delivery in deliveries
            if delivery.input_snapshot.get("installation_id") == expected
        ),
        None,
    )


def _operator_view(
    invitation: ShopifyStoreInvitation,
    installation: ReportJob,
    latest_webhook: ReportJob | None,
) -> ShopifyPublicOperatorInstallationView:
    snapshot = dict(installation.input_snapshot)
    delivery_snapshot = (
        dict(latest_webhook.input_snapshot) if latest_webhook is not None else {}
    )
    installation_status = installation.status
    if installation_status not in {
        "active",
        "refresh_required",
        "disconnected",
        "failed",
    }:
        installation_status = "failed"
    sync_status = _text(snapshot, "sync_status") or "not_started"
    if sync_status not in {
        "not_started",
        "queued",
        "coalesced",
        "running",
        "completed",
        "failed",
    }:
        sync_status = "failed"
    analysis_status = _text(snapshot, "analysis_status") or "not_started"
    if analysis_status not in {"not_started", "running", "completed", "failed"}:
        analysis_status = "failed"
    bulk_status = _text(snapshot, "last_bulk_operation_status")
    if bulk_status not in {"canceled", "canceling", "completed", "failed"}:
        bulk_status = None
    invitation_status = cast(
        Literal["activated", "revoked"],
        invitation.status if invitation.status in {"activated", "revoked"} else "revoked",
    )
    feature_tier = cast(
        Literal["demo", "plus_demo"],
        invitation.feature_tier,
    )
    report_ready = _uuid(snapshot, "last_verified_analysis_report_job_id") is not None
    return ShopifyPublicOperatorInstallationView(
        invitation_id=invitation.id,
        invitation_status=invitation_status,
        prospect_name=invitation.prospect_name,
        invitation_expires_at=invitation.expires_at,
        activated_at=invitation.activated_at,
        shop_domain=invitation.shop_domain,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        installation_id=installation.id,
        catalog_source_id=_uuid(snapshot, "catalog_source_id"),
        feature_tier=feature_tier,
        installation_status=cast(
            Literal["active", "refresh_required", "disconnected", "failed"],
            installation_status,
        ),
        sync_status=cast(
            Literal[
                "not_started",
                "queued",
                "coalesced",
                "running",
                "completed",
                "failed",
            ],
            sync_status,
        ),
        product_count=_integer(snapshot, "product_count"),
        variant_count=_integer(snapshot, "variant_count"),
        warning_count=_integer(snapshot, "warning_count"),
        assigned_category_count=_integer(snapshot, "assigned_category_count"),
        ambiguous_category_count=_integer(snapshot, "ambiguous_category_count"),
        unclassified_category_count=_integer(snapshot, "unclassified_category_count"),
        last_successful_sync_at=_datetime(snapshot, "last_successful_sync_at"),
        last_sync_job_id=_uuid(snapshot, "last_sync_job_id"),
        last_audit_run_id=_uuid(snapshot, "last_audit_run_id"),
        last_sync_error_type=_text(snapshot, "last_sync_error_type"),
        last_sync_full_reconciliation=_boolean(
            snapshot,
            "last_sync_full_reconciliation",
        ),
        last_completed_full_reconciliation=_boolean(
            snapshot,
            "last_completed_full_reconciliation",
        ),
        sync_attempt_count=_integer(snapshot, "sync_attempt_count"),
        sync_retry_count=_integer(snapshot, "sync_retry_count"),
        sync_next_retry_at=_datetime(snapshot, "sync_next_retry_at"),
        sync_last_failure_at=_datetime(snapshot, "sync_last_failure_at"),
        sync_last_failure_type=_text(snapshot, "sync_last_failure_type"),
        sync_dead_lettered_at=_datetime(snapshot, "sync_dead_lettered_at"),
        sync_recovery_required=_boolean(snapshot, "sync_recovery_required"),
        last_webhook_topic=_text(delivery_snapshot, "topic"),
        last_webhook_received_at=_datetime(delivery_snapshot, "received_at"),
        last_bulk_operation_status=cast(
            Literal["canceled", "canceling", "completed", "failed"] | None,
            bulk_status,
        ),
        last_bulk_operation_completed_at=_datetime(
            snapshot,
            "last_bulk_operation_completed_at",
        ),
        last_bulk_webhook_received_at=_datetime(
            snapshot,
            "last_bulk_webhook_received_at",
        ),
        last_bulk_operation_error_code=_text(
            snapshot,
            "last_bulk_operation_error_code",
        ),
        analysis_status=cast(
            Literal["not_started", "running", "completed", "failed"],
            analysis_status,
        ),
        analysis_stale=_boolean(snapshot, "analysis_stale"),
        analysis_completed_at=_datetime(snapshot, "analysis_completed_at"),
        analysis_error_type=_text(snapshot, "analysis_error_type"),
        finding_count=_integer(snapshot, "analysis_finding_count"),
        intent_run_count=_integer(snapshot, "analysis_intent_run_count"),
        intent_match_count=_integer(snapshot, "analysis_intent_match_count"),
        confident_match_count=_integer(snapshot, "analysis_confident_match_count"),
        possible_match_missing_data_count=_integer(
            snapshot,
            "analysis_possible_match_missing_data_count",
        ),
        report_ready=report_ready,
        report_path="/api/v1/shopify/public/report.pptx" if report_ready else None,
        backlog_path="/api/v1/shopify/public/backlog.csv" if report_ready else None,
        reauthorization_required=installation.status == "refresh_required",
    )


async def _authorized_installation(
    workspace_id: uuid.UUID,
    installation_id: uuid.UUID,
    session: SessionDependency,
) -> tuple[ShopifyStoreInvitation, ReportJob]:
    installation = await session.get(ReportJob, installation_id)
    if (
        installation is None
        or installation.report_type != SHOPIFY_INSTALLATION_TYPE
        or installation.input_snapshot.get("distribution") != "public"
    ):
        raise HTTPException(status_code=404, detail="Shopify installation not found")
    invitation = await session.scalar(
        select(ShopifyStoreInvitation).where(
            ShopifyStoreInvitation.workspace_id == workspace_id,
            ShopifyStoreInvitation.activated_workspace_id == installation.workspace_id,
            ShopifyStoreInvitation.shop_domain
            == installation.input_snapshot.get("shop_domain"),
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Shopify installation not found")
    return invitation, installation


@router.get(
    "/workspaces/{workspace_id}/shopify/public-installations",
    response_model=list[ShopifyPublicOperatorInstallationView],
)
async def list_shopify_public_installations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[ShopifyPublicOperatorInstallationView]:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    invitations = await ShopifyInvitationService().list_for_workspace(
        session,
        issuer_workspace_id=workspace_id,
    )
    views: list[ShopifyPublicOperatorInstallationView] = []
    installation_service = ShopifyPublicInstallationService()
    for invitation in invitations[:250]:
        if invitation.activated_workspace_id is None:
            continue
        installation = await installation_service.find_installation(
            session,
            workspace_id=invitation.activated_workspace_id,
            shop_domain=invitation.shop_domain,
        )
        if installation is None:
            continue
        latest_webhook = await _latest_webhook(
            session,
            workspace_id=invitation.activated_workspace_id,
            installation_id=installation.id,
        )
        views.append(_operator_view(invitation, installation, latest_webhook))
    return views


@router.post(
    "/workspaces/{workspace_id}/shopify/public-installations/"
    "{installation_id}/recover",
    response_model=ShopifyPublicOperatorInstallationView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recover_shopify_public_installation(
    workspace_id: uuid.UUID,
    installation_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> ShopifyPublicOperatorInstallationView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_source_management(membership.role)
    invitation, installation = await _authorized_installation(
        workspace_id,
        installation_id,
        session,
    )
    snapshot = dict(installation.input_snapshot)
    if installation.status != "active" or snapshot.get(
        "scope_reauthorization_required"
    ) is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Shopify installation requires reauthorization",
        )
    recovery_allowed = (
        snapshot.get("sync_recovery_required") is True
        or snapshot.get("sync_status") == "failed"
        or snapshot.get("analysis_status") == "failed"
    )
    if not recovery_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Shopify installation does not require recovery",
        )
    source_id = _uuid(snapshot, "catalog_source_id")
    if source_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Shopify catalog source is unavailable",
        )
    active_job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.workspace_id == installation.workspace_id,
            IngestionJob.catalog_source_id == source_id,
            IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shopify synchronization is already running",
        )
    await prepare_shopify_operator_recovery(
        session,
        installation=installation,
        actor_user_id=context.user.id,
    )
    job = await queue_shopify_sync(
        session,
        installation=installation,
        reason="operator_recovery",
        actor_user_id=context.user.id,
        full_reconciliation=True,
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shopify recovery could not be queued",
        )
    await session.refresh(installation)
    latest_webhook = await _latest_webhook(
        session,
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        installation_id=installation.id,
    )
    return _operator_view(invitation, installation, latest_webhook)
