from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.rate_limit import RateLimitExceeded, RedisRateLimiter
from catora_api.auth.roles import Role, can
from catora_api.auth.security import fingerprint
from catora_api.auth.service import AuthorizationError, ConflictError, IssuedSession
from catora_api.db.models import Membership, User
from catora_api.schemas.auth import (
    AcceptInvitationRequest,
    AuthUserView,
    BootstrapRequest,
    InviteRequest,
    InviteResponse,
    LoginRequest,
    MemberRoleUpdate,
    PasswordForgotRequest,
    PasswordResetRequest,
    SessionResponse,
)

router = APIRouter(prefix="/api/v1", tags=["authentication"])


def _client_ip(request: Request, service: AuthServiceDependency) -> str | None:
    if service.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _set_session_cookies(
    response: Response, issued: IssuedSession, service: AuthServiceDependency
) -> None:
    secure = service.settings.environment == "production"
    max_age = service.settings.session_ttl_hours * 3600
    response.set_cookie(
        service.settings.session_cookie_name,
        issued.raw_session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        service.settings.csrf_cookie_name,
        issued.response.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


async def _rate_limit(
    service: AuthServiceDependency, key: str, limit: int, window_seconds: int
) -> None:
    limiter = RedisRateLimiter(service.settings.redis_url)
    try:
        await limiter.check(key, limit, window_seconds)
    except RateLimitExceeded as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="Too many requests") from exc


@router.post("/auth/bootstrap", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap(
    payload: BootstrapRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> SessionResponse:
    await _rate_limit(
        service, f"auth:bootstrap:{fingerprint(_client_ip(request, service))}", 5, 3600
    )
    issued = await service.bootstrap(
        session, payload, request.headers.get("user-agent"), _client_ip(request, service)
    )
    _set_session_cookies(response, issued, service)
    return issued.response


@router.post("/auth/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> SessionResponse:
    key = f"auth:login:{fingerprint(_client_ip(request, service))}:{fingerprint(payload.email)}"
    await _rate_limit(service, key, 10, 300)
    issued = await service.login(
        session, payload, request.headers.get("user-agent"), _client_ip(request, service)
    )
    _set_session_cookies(response, issued, service)
    return issued.response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDependency,
    service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> None:
    await service.logout(session, context)
    response.delete_cookie(service.settings.session_cookie_name, path="/")
    response.delete_cookie(service.settings.csrf_cookie_name, path="/")


@router.get("/auth/me", response_model=AuthUserView)
async def me(
    session: SessionDependency,
    service: AuthServiceDependency,
    context: AuthContextDependency,
) -> AuthUserView:
    return await service.user_view(session, context.user)


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: PasswordForgotRequest,
    request: Request,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> dict[str, str]:
    key = f"auth:forgot:{fingerprint(_client_ip(request, service))}:{fingerprint(payload.email)}"
    await _rate_limit(service, key, 5, 3600)
    await service.request_password_reset(session, payload.email)
    return {"status": "accepted"}


@router.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: PasswordResetRequest,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> None:
    await service.reset_password(session, payload)


@router.post("/invitations/accept", response_model=SessionResponse)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> SessionResponse:
    issued = await service.accept_invitation(
        session, payload, request.headers.get("user-agent"), _client_ip(request, service)
    )
    _set_session_cookies(response, issued, service)
    return issued.response


@router.get("/workspaces/{workspace_id}/members")
async def list_members(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    await service.membership(session, context.user.id, workspace_id)
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(User.display_name)
        )
    ).all()
    return [
        {
            "membership_id": membership.id,
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": membership.role,
        }
        for membership, user in rows
    ]


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    workspace_id: uuid.UUID,
    payload: InviteRequest,
    session: SessionDependency,
    service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> InviteResponse:
    membership = await service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "members.manage"):
        raise AuthorizationError("Member management permission required")
    invitation = await service.invite(session, context.user, membership, payload)
    return InviteResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,  # type: ignore[arg-type]
        expires_at=invitation.expires_at.isoformat(),
    )


@router.patch("/workspaces/{workspace_id}/members/{membership_id}", status_code=204)
async def update_member(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberRoleUpdate,
    session: SessionDependency,
    service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> None:
    actor = await service.membership(session, context.user.id, workspace_id)
    if not can(Role(actor.role), "members.manage"):
        raise AuthorizationError("Member management permission required")
    target = await session.get(Membership, membership_id)
    if target is None:
        raise ConflictError("Membership does not exist")
    await service.update_member_role(session, actor, target, payload.role)


@router.delete("/workspaces/{workspace_id}/members/{membership_id}", status_code=204)
async def delete_member(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: SessionDependency,
    service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> None:
    actor = await service.membership(session, context.user.id, workspace_id)
    if not can(Role(actor.role), "members.manage"):
        raise AuthorizationError("Member management permission required")
    target = await session.get(Membership, membership_id)
    if target is None:
        return
    await service.remove_member(session, actor, target)
