# ruff: noqa: E501

from __future__ import annotations

import csv
import html
import io
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import (
    AuditFinding,
    AuditRun,
    BuyerIntent,
    IngestionJob,
    IntentProductMatch,
    IntentRun,
    Product,
    ProductVariant,
    ReportJob,
)
from catora_api.demo.pptx import (
    CONTENT_TYPES,
    ROOT_RELS,
    SLIDE_LAYOUT,
    SLIDE_MASTER,
    THEME,
    Slide,
    _slide_xml,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
FIELD_LABELS = {
    "width_mm": "Width",
    "depth_mm": "Depth",
    "height_mm": "Height",
    "materials": "Materials",
    "care_instructions": "Care instructions",
    "assembly_required": "Assembly requirements",
    "warranty_months": "Warranty",
    "usage_environment": "Indoor/outdoor suitability",
    "seating_capacity": "Seating capacity",
    "image_alt_text": "Image alt text",
    "description": "Product description",
}


@dataclass(frozen=True, slots=True)
class IntentReport:
    name: str
    query: str
    confident: int
    possible_missing_data: int
    non_match: int
    insufficient_category: int


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    company_name: str
    market_code: str
    locale: str
    product_count: int
    variant_count: int
    processed_rows: int
    rejected_rows: int
    warning_count: int
    assigned_categories: int
    ambiguous_categories: int
    unclassified_categories: int
    score_basis_points: int
    confidence_basis_points: int
    finding_counts: dict[str, int]
    top_gaps: tuple[tuple[str, int], ...]
    findings: tuple[tuple[AuditFinding, str], ...]
    intents: tuple[IntentReport, ...]


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _snapshot_uuid_list(snapshot: dict[str, object], key: str) -> list[uuid.UUID]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    result: list[uuid.UUID] = []
    for item in value:
        if isinstance(item, str):
            try:
                result.append(uuid.UUID(item))
            except ValueError:
                continue
    return result


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


async def load_report(session: AsyncSession, assessment: ReportJob) -> DiagnosticReport:
    snapshot = dict(assessment.input_snapshot)
    workspace_id = assessment.workspace_id
    audit_run_id = _snapshot_uuid(snapshot, "audit_run_id")
    intent_run_ids = _snapshot_uuid_list(snapshot, "intent_run_ids")
    job_id = _snapshot_uuid(snapshot, "ingestion_job_id")

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
    job = await session.get(IngestionJob, job_id) if job_id is not None else None
    audit_run = await session.get(AuditRun, audit_run_id) if audit_run_id is not None else None

    findings: list[AuditFinding] = []
    product_titles: dict[uuid.UUID, str] = {}
    if audit_run is not None:
        findings = list(
            (
                await session.scalars(
                    select(AuditFinding).where(
                        AuditFinding.workspace_id == workspace_id,
                        AuditFinding.audit_run_id == audit_run.id,
                        AuditFinding.status != "resolved",
                    )
                )
            ).all()
        )
        findings.sort(
            key=lambda item: (
                SEVERITY_ORDER.get(item.severity, 99),
                item.category_key,
                item.product_id,
                item.field_key,
                item.id,
            )
        )
        product_ids = sorted({finding.product_id for finding in findings})
        if product_ids:
            products = (
                await session.scalars(
                    select(Product).where(
                        Product.workspace_id == workspace_id,
                        Product.id.in_(product_ids),
                    )
                )
            ).all()
            product_titles = {product.id: product.title for product in products}

    gap_products: dict[str, set[uuid.UUID]] = defaultdict(set)
    for finding in findings:
        gap_products[finding.field_key].add(finding.product_id)
    top_gaps = tuple(
        sorted(
            (
                (FIELD_LABELS.get(key, key.replace("_", " ").title()), len(product_ids))
                for key, product_ids in gap_products.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )[:8]
    )

    intent_reports: list[IntentReport] = []
    if intent_run_ids:
        rows = (
            await session.execute(
                select(IntentRun, BuyerIntent)
                .join(BuyerIntent, BuyerIntent.id == IntentRun.buyer_intent_id)
                .where(
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.id.in_(intent_run_ids),
                    BuyerIntent.workspace_id == workspace_id,
                )
                .order_by(IntentRun.created_at, IntentRun.id)
            )
        ).all()
        matches = (
            await session.scalars(
                select(IntentProductMatch).where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentProductMatch.intent_run_id.in_(intent_run_ids),
                )
            )
        ).all()
        by_run: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
        for match in matches:
            by_run[match.intent_run_id][match.status] += 1
        for run, intent in rows:
            counts = by_run[run.id]
            intent_reports.append(
                IntentReport(
                    name=intent.name,
                    query=intent.query,
                    confident=counts["confident_match"],
                    possible_missing_data=counts["possible_match_missing_data"],
                    non_match=counts["non_match"],
                    insufficient_category=counts["insufficient_category_data"],
                )
            )

    score_summary = audit_run.score_summary if audit_run is not None else {}
    finding_counts = (
        {key: _integer(value) for key, value in audit_run.finding_counts.items()}
        if audit_run is not None
        else {}
    )
    return DiagnosticReport(
        company_name=str(snapshot.get("company_name") or "Prospect"),
        market_code=str(snapshot.get("market_code") or ""),
        locale=str(snapshot.get("locale") or ""),
        product_count=product_count,
        variant_count=variant_count,
        processed_rows=job.processed_count if job is not None else 0,
        rejected_rows=job.rejection_count if job is not None else 0,
        warning_count=job.warning_count if job is not None else 0,
        assigned_categories=_integer(snapshot.get("assigned_category_count")),
        ambiguous_categories=_integer(snapshot.get("ambiguous_category_count")),
        unclassified_categories=_integer(snapshot.get("unclassified_category_count")),
        score_basis_points=_integer(score_summary.get("overall_score_basis_points")),
        confidence_basis_points=_integer(score_summary.get("confidence_basis_points")),
        finding_counts=finding_counts,
        top_gaps=top_gaps,
        findings=tuple((finding, product_titles.get(finding.product_id, "Unknown product")) for finding in findings),
        intents=tuple(intent_reports),
    )


def build_backlog_csv(report: DiagnosticReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "company",
            "market",
            "product_id",
            "product_title",
            "severity",
            "category",
            "field_key",
            "issue",
            "business_impact",
            "remediation_type",
            "failure_codes",
            "evidence",
        ]
    )
    for finding, title in report.findings:
        evidence = " | ".join(
            str(item.get("excerpt") or item.get("field_path") or "evidence available")
            for item in finding.evidence
        )
        writer.writerow(
            [
                report.company_name,
                report.market_code,
                finding.product_id,
                title,
                finding.severity,
                finding.category_key,
                finding.field_key,
                finding.title,
                finding.business_impact,
                finding.remediation_type,
                ";".join(finding.failure_codes),
                evidence,
            ]
        )
    return output.getvalue()


def _slides(report: DiagnosticReport) -> tuple[Slide, ...]:
    score = report.score_basis_points / 100
    confidence = report.confidence_basis_points / 100
    total_findings = sum(report.finding_counts.values())
    top_gaps = ", ".join(f"{label} ({count})" for label, count in report.top_gaps[:4]) or "No material gaps"
    intent_lines = tuple(
        f"{item.name}: {item.confident} confident; {item.possible_missing_data} blocked by missing data"
        for item in report.intents[:4]
    ) or ("No prepared intent results available",)
    representative = report.findings[0] if report.findings else None
    representative_lines = (
        (
            representative[1],
            representative[0].title,
            representative[0].explanation,
        )
        if representative is not None
        else ("No evidence-backed finding was produced",)
    )
    return (
        Slide(
            f"{report.company_name} — Catora catalog assessment",
            (
                f"Market {report.market_code} · locale {report.locale}",
                f"{report.product_count} products and {report.variant_count} variants analysed",
                "Prepared from persisted source evidence and deterministic Catora metrics",
            ),
        ),
        Slide(
            "Executive summary",
            (
                f"Catalog health: {score:.1f}% with {confidence:.1f}% source confidence",
                f"Evidence-backed findings: {total_findings}",
                f"Rejected source rows: {report.rejected_rows}; import warnings: {report.warning_count}",
                f"Top data opportunities: {top_gaps}",
            ),
        ),
        Slide("Representative evidence-backed issue", representative_lines),
        Slide("Buyer-intent coverage", intent_lines),
        Slide(
            "Catalog classification and readiness",
            (
                f"Assigned to taxonomy: {report.assigned_categories}",
                f"Ambiguous classifications: {report.ambiguous_categories}",
                f"Unclassified products: {report.unclassified_categories}",
                "Ambiguous products remain visible for review; Catora does not silently force a category.",
            ),
        ),
        Slide(
            "Recommended 90-day paid pilot",
            (
                "Weeks 1–2: connect the live catalog and confirm evidence requirements",
                "Weeks 3–6: resolve high-value structured-data and content gaps",
                "Weeks 7–10: rerun buyer intents and validate improved eligibility",
                "Weeks 11–13: deliver executive results, operating backlog and scale-up plan",
            ),
        ),
    )


def build_report_pptx(report: DiagnosticReport) -> bytes:
    slides = _slides(report)
    slide_overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for index in range(1, len(slides) + 1)
    )
    presentation_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{index + 1}"/>'
        for index in range(1, len(slides) + 1)
    )
    presentation_rels = "\n".join(
        f'<Relationship Id="rId{index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{index}.xml"/>'
        for index in range(1, len(slides) + 1)
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES.format(slides=slide_overrides))
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr(
            "ppt/presentation.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>{presentation_ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>""",
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>{presentation_rels}</Relationships>""",
        )
        archive.writestr("ppt/slideMasters/slideMaster1.xml", SLIDE_MASTER)
        archive.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>""",
        )
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", SLIDE_LAYOUT)
        archive.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>""",
        )
        archive.writestr("ppt/theme/theme1.xml", THEME)
        archive.writestr(
            "docProps/core.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{html.escape(report.company_name)} Catora catalog assessment</dc:title><dc:creator>Catora</dc:creator></cp:coreProperties>""",
        )
        archive.writestr(
            "docProps/app.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Catora</Application><Slides>{len(slides)}</Slides></Properties>""",
        )
        for index, slide in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(slide))
            archive.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>""",
            )
    return output.getvalue()
