from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auth.mailer import SmtpAuthMailer
from catora_api.auth.service import AuthContext, AuthenticationError, AuthService
from catora_api.config import Settings, get_settings
from catora_api.database import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_auth_service(settings: SettingsDependency) -> AuthService:
    return AuthService(settings, SmtpAuthMailer(settings))


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


async def get_auth_context(
    request: Request,
    session: SessionDependency,
    service: AuthServiceDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    cookie_token = request.cookies.get(service.settings.session_cookie_name)
    bearer_token: str | None = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            bearer_token = value
    raw_token = cookie_token or bearer_token
    if raw_token is None:
        raise AuthenticationError("Authentication required")
    return await service.authenticate(session, raw_token, via_cookie=cookie_token is not None)


AuthContextDependency = Annotated[AuthContext, Depends(get_auth_context)]


async def require_csrf(
    context: AuthContextDependency,
    service: AuthServiceDependency,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    service.verify_csrf(context, csrf_token)
    return context


CsrfContextDependency = Annotated[AuthContext, Depends(require_csrf)]
