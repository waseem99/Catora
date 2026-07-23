from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, func, select

from catora_api.database import SessionFactory
from catora_api.db.models import Membership, Organization, ReportJob, User, Workspace
from catora_api.diagnostics.service import DiagnosticService
from catora_api.schemas.diagnostics import DiagnosticCreateRequest


async def validate() -> None:
    async with SessionFactory() as session:
        operator_workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == "sales-demo")
        )
        operator = await session.scalar(
            select(User).where(User.email == "demo@catora.local")
        )
        if operator_workspace is None or operator is None:
            raise RuntimeError("Run the enterprise demo seed before this validation")

        assessment = await DiagnosticService().create(
            session,
            actor_user_id=operator.id,
            actor_role="owner",
            operator_workspace_id=operator_workspace.id,
            payload=DiagnosticCreateRequest(
                company_name="CI Prospect Furniture",
                market_code="AE",
                locale="en-AE",
                currency="AED",
                retention_days=14,
                authorization_confirmed=True,
                storefront_domain="ci-prospect.myshopify.com",
            ),
        )
        snapshot = dict(assessment.input_snapshot)
        if snapshot.get("operator_workspace_id") != str(operator_workspace.id):
            raise RuntimeError("Diagnostic did not retain its operator workspace identity")
        if snapshot.get("authorization_confirmed") is not True:
            raise RuntimeError("Diagnostic authorization confirmation was not persisted")

        diagnostic_workspace = await session.get(Workspace, assessment.workspace_id)
        if diagnostic_workspace is None or "CI Prospect Furniture" not in diagnostic_workspace.name:
            raise RuntimeError("Prospect workspace was not created correctly")
        membership_count = int(
            await session.scalar(
                select(func.count(Membership.id)).where(
                    Membership.workspace_id == diagnostic_workspace.id,
                    Membership.user_id == operator.id,
                    Membership.role == "owner",
                )
            )
            or 0
        )
        if membership_count != 1:
            raise RuntimeError("Operator was not granted one scoped prospect membership")
        persisted = await session.scalar(
            select(ReportJob).where(
                ReportJob.id == assessment.id,
                ReportJob.workspace_id == diagnostic_workspace.id,
                ReportJob.report_type == "prospect_diagnostic",
                ReportJob.status == "awaiting_upload",
            )
        )
        if persisted is None:
            raise RuntimeError("Prospect diagnostic state was not persisted")

        organization_id = diagnostic_workspace.organization_id
        await session.execute(
            delete(Organization).where(Organization.id == organization_id)
        )
        await session.commit()

        if await session.get(Workspace, diagnostic_workspace.id) is not None:
            raise RuntimeError("Prospect workspace was not removed by organization cleanup")
        if await session.get(ReportJob, assessment.id) is not None:
            raise RuntimeError("Prospect diagnostic did not cascade during cleanup")
        if await session.get(Workspace, operator_workspace.id) is None:
            raise RuntimeError("Prospect cleanup affected the operator workspace")

    print("Prospect diagnostic PostgreSQL acceptance check passed.")


if __name__ == "__main__":
    asyncio.run(validate())
