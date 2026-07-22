from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.audit import AuditFinding, AuditRun
from catora_api.db.models.catalog import (
    CatalogSource,
    Category,
    EvidenceReference,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    SourceRecord,
)
from catora_api.db.models.identity import Workspace
from catora_api.db.models.intents import BuyerIntent, IntentProductMatch, IntentRun
from catora_api.db.models.reporting import AuditEvent
from catora_api.db.models.workflow import (
    ChangeSet,
    ChangeSetItem,
    Recommendation,
    RecommendationField,
    ReviewDecision,
)
from catora_api.schemas.demo import (
    DemoAuditSummary,
    DemoCatalogSummary,
    DemoChangeSetView,
    DemoEvidenceView,
    DemoFindingView,
    DemoGapSummary,
    DemoIntentView,
    DemoOverviewResponse,
    DemoProductView,
    DemoRecommendationDecisionRequest,
    DemoRecommendationDecisionResponse,
    DemoRecommendationFieldView,
    DemoRecommendationView,
)

FIELD_LABELS = {
    "width_mm": "Product width",
    "care_instructions": "Care instructions",
    "assembly_required": "Assembly requirements",
    "material": "Material",
    "image_alt_text": "Image alt text",
    "description": "Product description",
    "warranty_months": "Warranty",
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def _integer(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _current_value(field: RecommendationField) -> object | None:
    return field.edited_value if field.edited_value is not None else field.proposed_value


async def product_snapshot_hash(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
) -> str:
    product = await session.scalar(
        select(Product).where(
            Product.workspace_id == workspace_id,
            Product.id == product_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    attributes = (
        await session.scalars(
            select(ProductAttribute)
            .where(
                ProductAttribute.workspace_id == workspace_id,
                ProductAttribute.product_id == product_id,
            )
            .order_by(
                ProductAttribute.variant_id,
                ProductAttribute.key,
                ProductAttribute.id,
            )
        )
    ).all()
    payload = {
        "product": {
            "id": str(product.id),
            "canonical_key": product.canonical_key,
            "title": product.title,
            "category_id": (
                str(product.primary_category_id)
                if product.primary_category_id is not None
                else None
            ),
        },
        "attributes": [
            {
                "id": str(attribute.id),
                "variant_id": (
                    str(attribute.variant_id) if attribute.variant_id is not None else None
                ),
                "key": attribute.key,
                "value": attribute.value,
                "value_type": attribute.value_type,
                "unit": attribute.unit,
                "locale": attribute.locale,
                "value_state": attribute.value_state,
                "confidence": attribute.confidence,
            }
            for attribute in attributes
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class DemoService:
    async def overview(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
    ) -> DemoOverviewResponse:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        audit_run = await session.scalar(
            select(AuditRun)
            .where(
                AuditRun.workspace_id == workspace_id,
                AuditRun.status == "completed",
            )
            .order_by(AuditRun.completed_at.desc(), AuditRun.id.desc())
        )
        if audit_run is None:
            raise HTTPException(
                status_code=409,
                detail="The demo workspace does not have a completed audit",
            )

        recommendation = await session.scalar(
            select(Recommendation)
            .where(Recommendation.workspace_id == workspace_id)
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
        )
        if recommendation is None:
            raise HTTPException(
                status_code=409,
                detail="The demo workspace does not have a recommendation",
            )
        hero_product = await session.scalar(
            select(Product).where(
                Product.workspace_id == workspace_id,
                Product.id == recommendation.product_id,
            )
        )
        if hero_product is None:
            raise HTTPException(status_code=409, detail="Demo recommendation product is missing")
        category = None
        if hero_product.primary_category_id is not None:
            category = await session.scalar(
                select(Category).where(
                    Category.workspace_id == workspace_id,
                    Category.id == hero_product.primary_category_id,
                )
            )

        product_count = int(
            await session.scalar(
                select(func.count(Product.id)).where(
                    Product.workspace_id == workspace_id,
                    Product.deleted_at.is_(None),
                )
            )
            or 0
        )
        variant_count = int(
            await session.scalar(
                select(func.count(ProductVariant.id)).where(
                    ProductVariant.workspace_id == workspace_id,
                    ProductVariant.deleted_at.is_(None),
                )
            )
            or 0
        )
        attribute_count = int(
            await session.scalar(
                select(func.count(ProductAttribute.id)).where(
                    ProductAttribute.workspace_id == workspace_id
                )
            )
            or 0
        )
        image_count = int(
            await session.scalar(
                select(func.count(ProductImage.id)).where(
                    ProductImage.workspace_id == workspace_id
                )
            )
            or 0
        )

        findings = (
            await session.scalars(
                select(AuditFinding).where(
                    AuditFinding.workspace_id == workspace_id,
                    AuditFinding.audit_run_id == audit_run.id,
                    AuditFinding.status != "resolved",
                )
            )
        ).all()
        findings.sort(
            key=lambda item: (
                SEVERITY_ORDER.get(item.severity, 99),
                item.product_id,
                item.field_key,
                item.id,
            )
        )
        product_ids = sorted({finding.product_id for finding in findings})
        products = (
            await session.scalars(
                select(Product).where(
                    Product.workspace_id == workspace_id,
                    Product.id.in_(product_ids),
                )
            )
        ).all() if product_ids else []
        product_titles = {product.id: product.title for product in products}
        field_products: dict[str, set[uuid.UUID]] = {}
        for finding in findings:
            field_products.setdefault(finding.field_key, set()).add(finding.product_id)
        top_gaps = sorted(
            (
                DemoGapSummary(
                    field_key=field_key,
                    label=FIELD_LABELS.get(field_key, field_key.replace("_", " ").title()),
                    affected_products=len(affected),
                )
                for field_key, affected in field_products.items()
            ),
            key=lambda item: (-item.affected_products, item.field_key),
        )[:5]

        evidence_rows = (
            await session.execute(
                select(EvidenceReference, CatalogSource.name)
                .join(SourceRecord, SourceRecord.id == EvidenceReference.source_record_id)
                .join(CatalogSource, CatalogSource.id == SourceRecord.catalog_source_id)
                .where(
                    EvidenceReference.workspace_id == workspace_id,
                    EvidenceReference.product_id == hero_product.id,
                )
                .order_by(EvidenceReference.field_path, EvidenceReference.id)
                .limit(8)
            )
        ).all()
        hero_evidence = [
            DemoEvidenceView(
                field_path=evidence.field_path,
                excerpt=evidence.excerpt,
                source_label=source_name,
            )
            for evidence, source_name in evidence_rows
        ]

        intent_run = await session.scalar(
            select(IntentRun)
            .join(BuyerIntent, BuyerIntent.id == IntentRun.buyer_intent_id)
            .where(
                IntentRun.workspace_id == workspace_id,
                IntentRun.status == "completed",
            )
            .order_by(IntentRun.completed_at.desc(), IntentRun.id.desc())
        )
        if intent_run is None:
            raise HTTPException(
                status_code=409,
                detail="The demo workspace does not have a completed buyer-intent run",
            )
        buyer_intent = await session.scalar(
            select(BuyerIntent).where(
                BuyerIntent.workspace_id == workspace_id,
                BuyerIntent.id == intent_run.buyer_intent_id,
            )
        )
        if buyer_intent is None:
            raise HTTPException(status_code=409, detail="Demo buyer intent is missing")
        matches = (
            await session.scalars(
                select(IntentProductMatch).where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentProductMatch.intent_run_id == intent_run.id,
                )
            )
        ).all()
        match_counts = Counter(match.status for match in matches)
        hero_match = next(
            (match for match in matches if match.product_id == hero_product.id),
            None,
        )
        if hero_match is None:
            raise HTTPException(status_code=409, detail="Demo hero product intent match is missing")
        raw_missing = hero_match.explanation.get("missing_fields", [])
        missing_fields = (
            [item for item in raw_missing if isinstance(item, str)]
            if isinstance(raw_missing, list)
            else []
        )

        fields = (
            await session.scalars(
                select(RecommendationField)
                .where(
                    RecommendationField.workspace_id == workspace_id,
                    RecommendationField.recommendation_id == recommendation.id,
                )
                .order_by(RecommendationField.field_key, RecommendationField.id)
            )
        ).all()
        field_ids = [field.id for field in fields]
        decisions = (
            await session.scalars(
                select(ReviewDecision)
                .where(
                    ReviewDecision.workspace_id == workspace_id,
                    ReviewDecision.recommendation_field_id.in_(field_ids),
                )
                .order_by(
                    ReviewDecision.recommendation_field_id,
                    ReviewDecision.created_at.desc(),
                    ReviewDecision.id.desc(),
                )
            )
        ).all() if field_ids else []
        latest_decisions: dict[uuid.UUID, ReviewDecision] = {}
        for decision in decisions:
            latest_decisions.setdefault(decision.recommendation_field_id, decision)

        approved_items = (
            await session.scalars(
                select(ChangeSetItem)
                .join(ChangeSet, ChangeSet.id == ChangeSetItem.change_set_id)
                .where(
                    ChangeSet.workspace_id == workspace_id,
                    ChangeSetItem.workspace_id == workspace_id,
                    ChangeSetItem.recommendation_field_id.in_(field_ids),
                    ChangeSet.status == "approved",
                )
                .order_by(ChangeSet.created_at.desc(), ChangeSetItem.id.desc())
            )
        ).all() if field_ids else []
        approved_field_ids = {item.recommendation_field_id for item in approved_items}
        width_field_ids = {field.id for field in fields if field.field_key == "width_mm"}
        projected_status = (
            "confident_match"
            if approved_field_ids.intersection(width_field_ids)
            else hero_match.status
        )

        change_set = await session.scalar(
            select(ChangeSet)
            .join(ChangeSetItem, ChangeSetItem.change_set_id == ChangeSet.id)
            .where(
                ChangeSet.workspace_id == workspace_id,
                ChangeSetItem.recommendation_field_id.in_(field_ids),
            )
            .order_by(ChangeSet.created_at.desc(), ChangeSet.id.desc())
        ) if field_ids else None
        approved_count = sum(
            1 for decision in latest_decisions.values() if decision.decision == "approved"
        )
        rejected_count = sum(
            1 for decision in latest_decisions.values() if decision.decision == "rejected"
        )

        score_summary = audit_run.score_summary
        finding_counts = audit_run.finding_counts
        demo_findings = [
            DemoFindingView(
                id=finding.id,
                product_id=finding.product_id,
                product_title=product_titles.get(finding.product_id, "Unknown product"),
                severity=cast(
                    Literal["critical", "high", "medium", "low", "informational"],
                    finding.severity,
                ),
                title=finding.title,
                explanation=finding.explanation,
                category_key=finding.category_key,
                field_key=finding.field_key,
                business_impact=finding.business_impact,
                remediation_type=finding.remediation_type,
                evidence=finding.evidence,
            )
            for finding in findings[:8]
        ]
        recommendation_fields = [
            DemoRecommendationFieldView(
                id=field.id,
                field_key=field.field_key,
                label=FIELD_LABELS.get(
                    field.field_key,
                    field.field_key.replace("_", " ").title(),
                ),
                original_value=field.original_value,
                proposed_value=field.proposed_value,
                edited_value=field.edited_value,
                confidence=field.confidence,
                requires_verification=field.requires_verification,
                evidence=field.evidence,
                decision=(
                    cast(
                        Literal["approved", "rejected"],
                        latest_decisions[field.id].decision,
                    )
                    if field.id in latest_decisions
                    else None
                ),
                decision_comment=(
                    latest_decisions[field.id].comment if field.id in latest_decisions else None
                ),
            )
            for field in fields
        ]
        base_path = f"/api/v1/workspaces/{workspace_id}/demo"
        return DemoOverviewResponse(
            workspace_id=workspace_id,
            workspace_name=workspace.name,
            generated_at=datetime.now(UTC),
            catalog=DemoCatalogSummary(
                product_count=product_count,
                variant_count=variant_count,
                attribute_count=attribute_count,
                image_count=image_count,
            ),
            audit=DemoAuditSummary(
                run_id=audit_run.id,
                score_basis_points=_integer(score_summary.get("overall_score_basis_points")),
                confidence_basis_points=_integer(score_summary.get("confidence_basis_points")),
                critical_count=_integer(finding_counts.get("critical")),
                high_count=_integer(finding_counts.get("high")),
                medium_count=_integer(finding_counts.get("medium")),
            ),
            top_gaps=top_gaps,
            hero_product=DemoProductView(
                id=hero_product.id,
                title=hero_product.title,
                canonical_key=hero_product.canonical_key,
                category_key=category.key if category is not None else "unclassified",
                source_evidence=hero_evidence,
            ),
            findings=demo_findings,
            intent=DemoIntentView(
                id=buyer_intent.id,
                name=buyer_intent.name,
                query=buyer_intent.query,
                confident_match_count=match_counts["confident_match"],
                possible_match_count=match_counts["possible_match_missing_data"],
                non_match_count=match_counts["non_match"],
                insufficient_category_count=match_counts["insufficient_category_data"],
                hero_product_before_status=hero_match.status,
                hero_product_after_status=projected_status,
                missing_fields=missing_fields,
                explanation=(
                    "The product is relevant, but the catalog cannot prove its width. "
                    "The approved change is shown as a projection and is not "
                    "published automatically."
                ),
            ),
            recommendation=DemoRecommendationView(
                id=recommendation.id,
                product_id=hero_product.id,
                product_title=hero_product.title,
                status=recommendation.status,
                source_snapshot_hash=recommendation.source_snapshot_hash,
                fields=recommendation_fields,
            ),
            change_set=DemoChangeSetView(
                id=change_set.id if change_set is not None else None,
                name=change_set.name if change_set is not None else None,
                status=change_set.status if change_set is not None else "not_created",
                approved_field_count=approved_count,
                rejected_field_count=rejected_count,
                export_ready=change_set is not None and change_set.status == "approved",
            ),
            report_pptx_path=f"{base_path}/report.pptx",
            operational_csv_path=f"{base_path}/backlog.csv",
        )

    async def decide(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        reviewer_user_id: uuid.UUID,
        payload: DemoRecommendationDecisionRequest,
    ) -> DemoRecommendationDecisionResponse:
        recommendation = await session.scalar(
            select(Recommendation).where(
                Recommendation.workspace_id == workspace_id,
                Recommendation.id == recommendation_id,
            )
        )
        if recommendation is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if recommendation.source_snapshot_hash != payload.expected_source_snapshot_hash:
            raise HTTPException(
                status_code=409,
                detail="The recommendation snapshot is stale; reload before reviewing",
            )
        current_hash = await product_snapshot_hash(
            session,
            workspace_id=workspace_id,
            product_id=recommendation.product_id,
        )
        if current_hash != recommendation.source_snapshot_hash:
            raise HTTPException(
                status_code=409,
                detail="The source product changed after recommendation generation",
            )
        requested_ids = [item.field_id for item in payload.decisions]
        if len(requested_ids) != len(set(requested_ids)):
            raise HTTPException(
                status_code=422,
                detail="Each recommendation field may be decided once",
            )
        fields = (
            await session.scalars(
                select(RecommendationField).where(
                    RecommendationField.workspace_id == workspace_id,
                    RecommendationField.recommendation_id == recommendation_id,
                    RecommendationField.id.in_(requested_ids),
                )
            )
        ).all()
        fields_by_id = {field.id: field for field in fields}
        if set(fields_by_id) != set(requested_ids):
            raise HTTPException(status_code=404, detail="Recommendation field not found")

        approved_fields: list[RecommendationField] = []
        rejected_count = 0
        for requested in payload.decisions:
            field = fields_by_id[requested.field_id]
            if (
                requested.decision == "approved"
                and field.requires_verification
                and not requested.verified
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field.field_key} requires explicit verification before approval",
                )
            if requested.edited_value is not None:
                field.edited_value = requested.edited_value
            session.add(
                ReviewDecision(
                    workspace_id=workspace_id,
                    recommendation_field_id=field.id,
                    reviewer_user_id=reviewer_user_id,
                    decision=requested.decision,
                    comment=requested.comment,
                )
            )
            if requested.decision == "approved":
                approved_fields.append(field)
            else:
                rejected_count += 1

        change_set: ChangeSet | None = None
        if approved_fields:
            now = datetime.now(UTC)
            change_set = ChangeSet(
                workspace_id=workspace_id,
                name=f"Approved demo improvements — {now.date().isoformat()}",
                status="approved",
                source_snapshot_hash=recommendation.source_snapshot_hash,
                approved_by_user_id=reviewer_user_id,
                approved_at=now,
            )
            session.add(change_set)
            await session.flush()
            for field in approved_fields:
                session.add(
                    ChangeSetItem(
                        workspace_id=workspace_id,
                        change_set_id=change_set.id,
                        recommendation_field_id=field.id,
                        approved_value=_current_value(field),
                    )
                )
        recommendation.status = "approved" if approved_fields else "rejected"
        projected_status = (
            "confident_match"
            if any(field.field_key == "width_mm" for field in approved_fields)
            else "possible_match_missing_data"
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=reviewer_user_id,
                event_type="demo.recommendation_decided",
                entity_type="recommendation",
                entity_id=recommendation.id,
                payload={
                    "approved_field_count": len(approved_fields),
                    "rejected_field_count": rejected_count,
                    "change_set_id": str(change_set.id) if change_set is not None else None,
                    "projected_intent_status": projected_status,
                },
            )
        )
        await session.commit()
        return DemoRecommendationDecisionResponse(
            recommendation_id=recommendation.id,
            recommendation_status=recommendation.status,
            change_set_id=change_set.id if change_set is not None else None,
            approved_field_count=len(approved_fields),
            rejected_field_count=rejected_count,
            projected_intent_status=projected_status,
        )
