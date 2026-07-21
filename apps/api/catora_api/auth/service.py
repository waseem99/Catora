from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auth.mailer import AuthMailer
from catora_api.auth.roles import Role, can_assign
from catora_api.auth.security import PasswordService, TokenService, fingerprint
from catora_api.config import Settings
from catora_api.db.models import AuditEvent, Membership, Organization, User, Workspace
from catora_api.db.models.auth import AuthSession, Invitation, PasswordResetToken
from catora_api.schemas.auth import (
    AcceptInvitationRequest,
    AuthUserView,
    BootstrapRequest,
    InviteRequest,
    LoginRequest,
    PasswordResetRequest,
    SessionResponse,
    WorkspaceMembershipView,
)


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class ConflictError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AuthContext:
    user: User
    auth_session: AuthSession
    via_cookie: bool


@dataclass(frozen=True)
class IssuedSession:
    response: SessionResponse
    raw_session_token: str


class AuthService:
    def __init__(self, settings: Settings, mailer: AuthMailer) -> None:
        self.settings = settings
        self.passwords = PasswordService()
        self.tokens = TokenService(settings.auth_token_pepper)
        self.mailer = mailer

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    async def _audit(
        self,
        session: AsyncSession,
        event_type: str,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload or {},
            )
        )

    async def bootstrap(
        self,
        session: AsyncSession,
        request: BootstrapRequest,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        existing = await session.scalar(select(func.count(User.id)))
        if existing:
            raise ConflictError("Catora has already been initialized")

        organization = Organization(name=request.organization_name, slug=request.organization_slug)
        session.add(organization)
        await session.flush()
        workspace = Workspace(
            organization_id=organization.id,
            name=request.workspace_name,
            slug=request.workspace_slug,
        )
        user = User(
            email=request.email,
            display_name=request.display_name,
            password_hash=self.passwords.hash(request.password),
            is_active=True,
        )
        session.add_all([workspace, user])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            workspace_id=workspace.id,
            user_id=user.id,
            role=Role.OWNER.value,
        )
        session.add(membership)
        await self._audit(
            session,
            "auth.bootstrap",
            workspace_id=workspace.id,
            actor_user_id=user.id,
            entity_type="workspace",
            entity_id=workspace.id,
        )
        response = await self._create_session(session, user, user_agent, ip)
        await session.commit()
        return response

    async def login(
        self, session: AsyncSession, request: LoginRequest, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        user = await session.scalar(select(User).where(User.email == request.email))
        if (
            user is None
            or not user.is_active
            or not self.passwords.verify(user.password_hash, request.password)
        ):
            raise AuthenticationError("Invalid email or password")
        if self.passwords.needs_rehash(user.password_hash):
            user.password_hash = self.passwords.hash(request.password)
        response = await self._create_session(session, user, user_agent, ip)
        await session.commit()
        return response

    async def _create_session(
        self, session: AsyncSession, user: User, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        token = self.tokens.issue()
        csrf = self.tokens.issue(32)
        now = self.now()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=token.digest,
            csrf_hash=csrf.digest,
            expires_at=now + timedelta(hours=self.settings.session_ttl_hours),
            last_seen_at=now,
            user_agent_hash=fingerprint(user_agent),
            ip_prefix_hash=fingerprint(ip),
        )
        session.add(auth_session)
        await session.flush()
        view = await self.user_view(session, user)
        return IssuedSession(
            response=SessionResponse(user=view, csrf_token=csrf.raw),
            raw_session_token=token.raw,
        )

    async def user_view(self, session: AsyncSession, user: User) -> AuthUserView:
        rows = (
            await session.execute(
                select(Membership, Workspace, Organization)
                .join(Workspace, Workspace.id == Membership.workspace_id)
                .join(Organization, Organization.id == Membership.organization_id)
                .where(Membership.user_id == user.id)
                .order_by(Organization.name, Workspace.name)
            )
        ).all()
        memberships = [
            WorkspaceMembershipView(
                workspace_id=membership.workspace_id,
                organization_id=membership.organization_id,
                workspace_name=workspace.name,
                organization_name=organization.name,
                role=membership.role,
            )
            for membership, workspace, organization in rows
        ]
        return AuthUserView(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            memberships=memberships,
        )

    async def authenticate(
        self, session: AsyncSession, raw_token: str, *, via_cookie: bool
    ) -> AuthContext:
        now = self.now()
        auth_session = await session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == self.tokens.digest(raw_token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        if auth_session is None:
            raise AuthenticationError("Authentication required")
        user = await session.get(User, auth_session.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Authentication required")
        auth_session.last_seen_at = now
        return AuthContext(user=user, auth_session=auth_session, via_cookie=via_cookie)

    def verify_csrf(self, context: AuthContext, csrf_token: str | None) -> None:
        if context.via_cookie and (
            csrf_token is None or not self.tokens.verify(csrf_token, context.auth_session.csrf_hash)
        ):
            raise AuthorizationError("CSRF validation failed")

    async def logout(self, session: AsyncSession, context: AuthContext) -> None:
        context.auth_session.revoked_at = self.now()
        await session.commit()

    async def membership(
        self, session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Membership:
        membership = await session.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.workspace_id == workspace_id,
            )
        )
        if membership is None:
            raise AuthorizationError("Workspace access denied")
        return membership

    async def invite(
        self,
        session: AsyncSession,
        actor: User,
        membership: Membership,
        request: InviteRequest,
    ) -> Invitation:
        if not can_assign(membership.role, request.role):
            raise AuthorizationError("Role cannot be assigned by this user")
        token = self.tokens.issue()
        invite = Invitation(
            workspace_id=membership.workspace_id,
            organization_id=membership.organization_id,
            email=request.email,
            role=request.role,
            token_hash=token.digest,
            invited_by_user_id=actor.id,
            expires_at=self.now() + timedelta(hours=self.settings.invitation_ttl_hours),
        )
        session.add(invite)
        await session.flush()
        await self._audit(
            session,
            "membership.invited",
            workspace_id=membership.workspace_id,
            actor_user_id=actor.id,
            entity_type="invitation",
            entity_id=invite.id,
            payload={"email": request.email, "role": request.role},
        )
        await session.commit()
        link = f"{self.settings.frontend_url}/accept-invitation?token={token.raw}"
        await self.mailer.send_invitation(request.email, link)
        return invite

    async def accept_invitation(
        self,
        session: AsyncSession,
        request: AcceptInvitationRequest,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        now = self.now()
        invitation = await session.scalar(
            select(Invitation).where(
                Invitation.token_hash == self.tokens.digest(request.token),
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
        )
        if invitation is None:
            raise InvalidTokenError("Invitation is invalid or expired")
        user = await session.scalar(select(User).where(User.email == invitation.email))
        if user is None:
            if not request.password or not request.display_name:
                raise ConflictError("Display name and password are required for a new account")
            user = User(
                email=invitation.email,
                display_name=request.display_name,
                password_hash=self.passwords.hash(request.password),
                is_active=True,
            )
            session.add(user)
            await session.flush()
        existing = await session.scalar(
            select(Membership).where(
                Membership.workspace_id == invitation.workspace_id,
                Membership.user_id == user.id,
            )
        )
        if existing is None:
            session.add(
                Membership(
                    organization_id=invitation.organization_id,
                    workspace_id=invitation.workspace_id,
                    user_id=user.id,
                    role=invitation.role,
                )
            )
        invitation.accepted_at = now
        await self._audit(
            session,
            "membership.accepted",
            workspace_id=cast(uuid.UUID, invitation.workspace_id),
            actor_user_id=user.id,
            entity_type="invitation",
            entity_id=invitation.id,
        )
        response = await self._create_session(session, user, user_agent, ip)
        await session.commit()
        return response

    async def request_password_reset(self, session: AsyncSession, email: str) -> None:
        user = await session.scalar(
            select(User).where(User.email == email, User.is_active.is_(True))
        )
        if user is None:
            return
        token = self.tokens.issue()
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=token.digest,
            expires_at=self.now() + timedelta(minutes=self.settings.password_reset_ttl_minutes),
        )
        session.add(reset)
        await session.commit()
        link = f"{self.settings.frontend_url}/reset-password?token={token.raw}"
        await self.mailer.send_password_reset(email, link)

    async def reset_password(self, session: AsyncSession, request: PasswordResetRequest) -> None:
        now = self.now()
        reset = await session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == self.tokens.digest(request.token),
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
        if reset is None:
            raise InvalidTokenError("Reset token is invalid or expired")
        user = await session.get(User, reset.user_id)
        if user is None:
            raise InvalidTokenError("Reset token is invalid or expired")
        user.password_hash = self.passwords.hash(request.password)
        reset.used_at = now
        await session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()

    async def update_member_role(
        self,
        session: AsyncSession,
        actor_membership: Membership,
        target: Membership,
        role: str,
    ) -> None:
        if target.workspace_id != actor_membership.workspace_id:
            raise AuthorizationError("Workspace access denied")
        if not can_assign(actor_membership.role, role):
            raise AuthorizationError("Role cannot be assigned by this user")
        if target.role == Role.OWNER and actor_membership.role != Role.OWNER:
            raise AuthorizationError("Only an owner can modify an owner")
        if target.role == Role.OWNER and role != Role.OWNER:
            other_owners = await session.scalar(
                select(func.count(Membership.id)).where(
                    Membership.workspace_id == target.workspace_id,
                    Membership.role == Role.OWNER,
                    Membership.id != target.id,
                )
            )
            if not other_owners:
                raise ConflictError("A workspace must retain at least one owner")
        target.role = role
        await self._audit(
            session,
            "membership.role_changed",
            workspace_id=target.workspace_id,
            actor_user_id=actor_membership.user_id,
            entity_type="membership",
            entity_id=target.id,
            payload={"role": role},
        )
        await session.commit()

    async def remove_member(
        self, session: AsyncSession, actor_membership: Membership, target: Membership
    ) -> None:
        if target.workspace_id != actor_membership.workspace_id:
            raise AuthorizationError("Workspace access denied")
        if target.role == Role.OWNER:
            raise ConflictError("Transfer ownership before removing an owner")
        await self._audit(
            session,
            "membership.removed",
            workspace_id=target.workspace_id,
            actor_user_id=actor_membership.user_id,
            entity_type="membership",
            entity_id=target.id,
        )
        await session.delete(target)
        await session.commit()
