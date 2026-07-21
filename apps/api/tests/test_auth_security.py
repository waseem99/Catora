from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from catora_api.auth.roles import Role, can, can_assign
from catora_api.auth.security import PasswordService, TokenService
from catora_api.auth.service import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    AuthService,
    ConflictError,
)
from catora_api.config import Settings
from catora_api.db.models import AuthSession, Membership, User
from catora_api.main import app
from catora_api.schemas.auth import LoginRequest


class FakeMailer:
    async def send_invitation(self, recipient: str, link: str) -> None:
        return None

    async def send_password_reset(self, recipient: str, link: str) -> None:
        return None


class EmptyRows:
    def all(self) -> list[object]:
        return []


def test_passwords_use_argon2id_and_reject_wrong_password() -> None:
    service = PasswordService()
    password_hash = service.hash("a sufficiently long passphrase")
    assert password_hash.startswith("$argon2id$")
    assert service.verify(password_hash, "a sufficiently long passphrase")
    assert not service.verify(password_hash, "incorrect password")


def test_opaque_tokens_are_hashed_and_constant_time_verified() -> None:
    service = TokenService("a-token-pepper-with-at-least-32-characters")
    token = service.issue()
    assert token.raw not in token.digest
    assert len(token.digest) == 64
    assert service.verify(token.raw, token.digest)
    assert not service.verify(f"{token.raw}x", token.digest)


def test_role_matrix_prevents_privilege_escalation() -> None:
    assert can(Role.REVIEWER, "recommendations.review")
    assert not can(Role.REVIEWER, "members.manage")
    assert can_assign(Role.ADMIN, Role.REVIEWER)
    assert not can_assign(Role.ADMIN, Role.OWNER)
    assert can_assign(Role.OWNER, Role.OWNER)


def test_unauthenticated_me_is_generic_401() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.asyncio
async def test_login_stores_only_hashed_session_token() -> None:
    settings = Settings(auth_token_pepper="a-token-pepper-with-at-least-32-characters")
    auth = AuthService(settings, FakeMailer())
    password = "a sufficiently long passphrase"
    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        display_name="Owner",
        password_hash=auth.passwords.hash(password),
        is_active=True,
    )
    session = Mock()
    session.scalar = AsyncMock(return_value=user)
    session.execute = AsyncMock(return_value=EmptyRows())
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = Mock()

    issued = await auth.login(
        session,
        LoginRequest(email="owner@example.com", password=password),
        "test-agent",
        "127.0.0.1",
    )

    stored_session = next(
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuthSession)
    )
    assert issued.raw_session_token != stored_session.token_hash
    assert auth.tokens.digest(issued.raw_session_token) == stored_session.token_hash
    assert issued.response.user.email == "owner@example.com"


@pytest.mark.asyncio
async def test_login_error_does_not_reveal_account_existence() -> None:
    settings = Settings(auth_token_pepper="a-token-pepper-with-at-least-32-characters")
    auth = AuthService(settings, FakeMailer())
    session = Mock()
    session.scalar = AsyncMock(return_value=None)

    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await auth.login(
            session,
            LoginRequest(email="unknown@example.com", password="anything"),
            None,
            None,
        )


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted() -> None:
    settings = Settings(auth_token_pepper="a-token-pepper-with-at-least-32-characters")
    auth = AuthService(settings, FakeMailer())
    workspace_id = uuid.uuid4()
    owner = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        display_name="Owner",
        password_hash="unused",
        is_active=True,
    )
    membership = Membership(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=workspace_id,
        user_id=owner.id,
        role=Role.OWNER.value,
    )
    session = Mock()
    session.scalar = AsyncMock(return_value=0)

    with pytest.raises(ConflictError, match="at least one owner"):
        await auth.update_member_role(session, membership, membership, Role.VIEWER.value)


def test_cookie_csrf_is_required_but_bearer_csrf_is_not() -> None:
    settings = Settings(auth_token_pepper="a-token-pepper-with-at-least-32-characters")
    auth = AuthService(settings, FakeMailer())
    csrf = auth.tokens.issue()
    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        display_name="Owner",
        password_hash="unused",
        is_active=True,
    )
    stored = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=auth.tokens.issue().digest,
        csrf_hash=csrf.digest,
        expires_at=auth.now(),
        last_seen_at=auth.now(),
    )
    with pytest.raises(AuthorizationError, match="CSRF"):
        auth.verify_csrf(AuthContext(user=user, auth_session=stored, via_cookie=True), None)
    auth.verify_csrf(AuthContext(user=user, auth_session=stored, via_cookie=True), csrf.raw)
    auth.verify_csrf(AuthContext(user=user, auth_session=stored, via_cookie=False), None)
