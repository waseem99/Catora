from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent, ShopifyStoreInvitation
from catora_api.shopify.installations import normalize_shop_domain


class ShopifyInvitationError(ValueError):
    pass


class ShopifyInvitationService:
    async def create_or_replace(
        self,
        session: AsyncSession,
        *,
        issuer_workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        shop_domain: str,
        prospect_name: str,
        expires_in_hours: int,
        feature_tier: str = "demo",
    ) -> ShopifyStoreInvitation:
        shop = normalize_shop_domain(shop_domain)
        name = prospect_name.strip()
        if not name:
            raise ShopifyInvitationError("Prospect name is required")
        if expires_in_hours < 1 or expires_in_hours > 720:
            raise ShopifyInvitationError("Invitation lifetime must be between 1 and 720 hours")
        if feature_tier not in {"demo", "plus_demo"}:
            raise ShopifyInvitationError("Unsupported Shopify invitation feature tier")

        now = datetime.now(UTC)
        invitation = await session.scalar(
            select(ShopifyStoreInvitation).where(
                ShopifyStoreInvitation.shop_domain == shop
            )
        )
        event_type = "shopify.public_invitation_created"
        if invitation is None:
            invitation = ShopifyStoreInvitation(
                issuer_workspace_id=issuer_workspace_id,
                activated_workspace_id=None,
                created_by_user_id=actor_user_id,
                shop_domain=shop,
                prospect_name=name,
                feature_tier=feature_tier,
                status="pending",
                expires_at=now + timedelta(hours=expires_in_hours),
                activated_at=None,
                revoked_at=None,
            )
            session.add(invitation)
            await session.flush()
        else:
            if invitation.status == "activated":
                raise ShopifyInvitationError(
                    "An activated Shopify store invitation cannot be replaced"
                )
            invitation.issuer_workspace_id = issuer_workspace_id
            invitation.created_by_user_id = actor_user_id
            invitation.prospect_name = name
            invitation.feature_tier = feature_tier
            invitation.status = "pending"
            invitation.expires_at = now + timedelta(hours=expires_in_hours)
            invitation.activated_workspace_id = None
            invitation.activated_at = None
            invitation.revoked_at = None
            event_type = "shopify.public_invitation_reissued"

        session.add(
            AuditEvent(
                workspace_id=issuer_workspace_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type="shopify_store_invitation",
                entity_id=invitation.id,
                payload={
                    "shop_domain": shop,
                    "prospect_name": name,
                    "feature_tier": feature_tier,
                    "expires_at": invitation.expires_at.isoformat(),
                },
            )
        )
        await session.commit()
        await session.refresh(invitation)
        return invitation

    async def list_for_workspace(
        self,
        session: AsyncSession,
        *,
        issuer_workspace_id: uuid.UUID,
    ) -> tuple[ShopifyStoreInvitation, ...]:
        invitations = await session.scalars(
            select(ShopifyStoreInvitation)
            .where(ShopifyStoreInvitation.issuer_workspace_id == issuer_workspace_id)
            .order_by(ShopifyStoreInvitation.created_at.desc())
        )
        return tuple(invitations.all())

    async def require_activatable(
        self,
        session: AsyncSession,
        *,
        shop_domain: str,
    ) -> ShopifyStoreInvitation:
        shop = normalize_shop_domain(shop_domain)
        invitation = await session.scalar(
            select(ShopifyStoreInvitation).where(
                ShopifyStoreInvitation.shop_domain == shop
            )
        )
        if invitation is None:
            raise ShopifyInvitationError("This Shopify store is not invited to Catora")
        if invitation.status == "activated":
            return invitation
        if invitation.status == "pending" and invitation.expires_at <= datetime.now(UTC):
            invitation.status = "expired"
            await session.commit()
            raise ShopifyInvitationError("This Shopify store invitation has expired")
        if invitation.status != "pending":
            raise ShopifyInvitationError("This Shopify store invitation is not active")
        return invitation

    async def activate(
        self,
        session: AsyncSession,
        *,
        shop_domain: str,
        activated_workspace_id: uuid.UUID,
    ) -> ShopifyStoreInvitation:
        invitation = await self.require_activatable(session, shop_domain=shop_domain)
        if invitation.status == "activated":
            if invitation.activated_workspace_id != activated_workspace_id:
                raise ShopifyInvitationError(
                    "This Shopify store is already attached to another Catora workspace"
                )
            return invitation

        invitation.status = "activated"
        invitation.activated_workspace_id = activated_workspace_id
        invitation.activated_at = datetime.now(UTC)
        invitation.revoked_at = None
        session.add(
            AuditEvent(
                workspace_id=invitation.issuer_workspace_id,
                actor_user_id=None,
                event_type="shopify.public_invitation_activated",
                entity_type="shopify_store_invitation",
                entity_id=invitation.id,
                payload={
                    "shop_domain": invitation.shop_domain,
                    "activated_workspace_id": str(activated_workspace_id),
                    "feature_tier": invitation.feature_tier,
                },
            )
        )
        await session.commit()
        await session.refresh(invitation)
        return invitation

    async def revoke(
        self,
        session: AsyncSession,
        *,
        issuer_workspace_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> ShopifyStoreInvitation:
        invitation = await session.scalar(
            select(ShopifyStoreInvitation).where(
                ShopifyStoreInvitation.id == invitation_id,
                ShopifyStoreInvitation.issuer_workspace_id == issuer_workspace_id,
            )
        )
        if invitation is None:
            raise ShopifyInvitationError("Shopify store invitation not found")
        if invitation.status == "revoked":
            return invitation

        invitation.status = "revoked"
        invitation.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=issuer_workspace_id,
                actor_user_id=actor_user_id,
                event_type="shopify.public_invitation_revoked",
                entity_type="shopify_store_invitation",
                entity_id=invitation.id,
                payload={
                    "shop_domain": invitation.shop_domain,
                    "activated_workspace_id": (
                        str(invitation.activated_workspace_id)
                        if invitation.activated_workspace_id is not None
                        else None
                    ),
                },
            )
        )
        await session.commit()
        await session.refresh(invitation)
        return invitation
