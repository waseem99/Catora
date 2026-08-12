from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import delete, select

from catora_api.auth.security import PasswordService
from catora_api.database import SessionFactory
from catora_api.db.models.identity import Membership, User, Workspace

QA_WORKSPACE_SLUG = "sales-demo"
DENIED_WORKSPACE_SLUG = "staging-certification-denied"
EMAIL_SUFFIX = "@staging.catora.local"
CONFIRMATION = "I_UNDERSTAND_THIS_IS_STAGING_ONLY"
ROLE_ENV = {
    "owner": ("CATORA_STAGING_OWNER_EMAIL", "CATORA_STAGING_OWNER_PASSWORD"),
    "admin": ("CATORA_STAGING_ADMIN_EMAIL", "CATORA_STAGING_ADMIN_PASSWORD"),
    "analyst": ("CATORA_STAGING_ANALYST_EMAIL", "CATORA_STAGING_ANALYST_PASSWORD"),
    "reviewer": ("CATORA_STAGING_REVIEWER_EMAIL", "CATORA_STAGING_REVIEWER_PASSWORD"),
    "viewer": ("CATORA_STAGING_VIEWER_EMAIL", "CATORA_STAGING_VIEWER_PASSWORD"),
}
NO_MEMBERSHIP_ENV = (
    "CATORA_STAGING_NO_MEMBERSHIP_EMAIL",
    "CATORA_STAGING_NO_MEMBERSHIP_PASSWORD",
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _staging_email(name: str) -> str:
    email = _required(name).lower()
    if not email.endswith(EMAIL_SUFFIX):
        raise RuntimeError(f"{name} must use the dedicated {EMAIL_SUFFIX} suffix")
    return email


async def _upsert_user(
    *,
    session,  # type: ignore[no-untyped-def]
    email: str,
    password: str,
    display_name: str,
    password_service: PasswordService,
) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    password_hash = password_service.hash(password)
    if user is None:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            is_active=True,
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = password_hash
        user.display_name = display_name
        user.is_active = True
    return user


async def seed() -> dict[str, object]:
    if _required("CATORA_STAGING_CERTIFICATION_SEED_CONFIRM") != CONFIRMATION:
        raise RuntimeError("Staging certification seed confirmation did not match")

    credentials = {
        role: (
            _staging_email(email_name),
            _required(password_name),
        )
        for role, (email_name, password_name) in ROLE_ENV.items()
    }
    no_membership_email = _staging_email(NO_MEMBERSHIP_ENV[0])
    no_membership_password = _required(NO_MEMBERSHIP_ENV[1])
    all_emails = [email for email, _ in credentials.values()] + [no_membership_email]
    if len(set(all_emails)) != len(all_emails):
        raise RuntimeError("Every staging certification identity must use a distinct email")

    password_service = PasswordService()
    async with SessionFactory() as session:
        qa_workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == QA_WORKSPACE_SLUG)
        )
        if qa_workspace is None:
            raise RuntimeError(
                "The enterprise demo workspace does not exist; run seed_enterprise_demo.py first"
            )

        denied_workspace = await session.scalar(
            select(Workspace).where(
                Workspace.organization_id == qa_workspace.organization_id,
                Workspace.slug == DENIED_WORKSPACE_SLUG,
            )
        )
        if denied_workspace is None:
            denied_workspace = Workspace(
                organization_id=qa_workspace.organization_id,
                name="Staging Certification Denied Workspace",
                slug=DENIED_WORKSPACE_SLUG,
            )
            session.add(denied_workspace)
            await session.flush()

        role_users: dict[str, User] = {}
        for role, (email, password) in credentials.items():
            user = await _upsert_user(
                session=session,
                email=email,
                password=password,
                display_name=f"Staging QA {role.title()}",
                password_service=password_service,
            )
            role_users[role] = user
            membership = await session.scalar(
                select(Membership).where(
                    Membership.workspace_id == qa_workspace.id,
                    Membership.user_id == user.id,
                )
            )
            if membership is None:
                session.add(
                    Membership(
                        organization_id=qa_workspace.organization_id,
                        workspace_id=qa_workspace.id,
                        user_id=user.id,
                        role=role,
                    )
                )
            else:
                membership.organization_id = qa_workspace.organization_id
                membership.role = role
            await session.execute(
                delete(Membership).where(
                    Membership.workspace_id == denied_workspace.id,
                    Membership.user_id == user.id,
                )
            )

        no_membership_user = await _upsert_user(
            session=session,
            email=no_membership_email,
            password=no_membership_password,
            display_name="Staging QA No Membership",
            password_service=password_service,
        )
        await session.execute(
            delete(Membership).where(Membership.user_id == no_membership_user.id)
        )
        await session.commit()

        return {
            "qa_workspace_id": str(qa_workspace.id),
            "denied_workspace_id": str(denied_workspace.id),
            "roles": sorted(role_users),
            "no_membership_identity": True,
        }


if __name__ == "__main__":
    try:
        result = asyncio.run(seed())
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as exc:
        raise SystemExit(f"Staging certification fixture seed failed: {exc}") from exc
