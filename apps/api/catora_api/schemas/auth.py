from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RoleName = Literal["owner", "admin", "analyst", "reviewer", "viewer"]


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BootstrapRequest(AuthModel):
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
    workspace_name: str = Field(min_length=2, max_length=200)
    workspace_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("Invalid email address")
        return normalized


class LoginRequest(AuthModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class WorkspaceMembershipView(AuthModel):
    workspace_id: uuid.UUID
    organization_id: uuid.UUID
    workspace_name: str
    organization_name: str
    role: RoleName


class AuthUserView(AuthModel):
    id: uuid.UUID
    email: str
    display_name: str
    memberships: list[WorkspaceMembershipView]


class SessionResponse(AuthModel):
    user: AuthUserView
    csrf_token: str


class InviteRequest(AuthModel):
    email: str = Field(min_length=3, max_length=320)
    role: RoleName

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class InviteResponse(AuthModel):
    id: uuid.UUID
    email: str
    role: RoleName
    expires_at: str


class AcceptInvitationRequest(AuthModel):
    token: str = Field(min_length=32, max_length=512)
    display_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=256)


class PasswordForgotRequest(AuthModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(AuthModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=12, max_length=256)


class MemberRoleUpdate(AuthModel):
    role: RoleName
