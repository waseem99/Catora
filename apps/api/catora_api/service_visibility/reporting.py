# ruff: noqa: E501

from __future__ import annotations

import csv
import html
import io
import zipfile

from catora_api.demo.pptx import (
    CONTENT_TYPES,
    ROOT_RELS,
    SLIDE_LAYOUT,
    SLIDE_MASTER,
    THEME,
    Slide,
    _slide_xml,
)
from catora_api.service_visibility.models import ServiceFinding, ServiceVisibilityReport


def build_findings_csv(report: ServiceVisibilityReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "company",
            "site",
            "family",
            "severity",
            "lifecycle",
            "code",
            "page_url",
            "title",
            "detail",
            "recommendation",
            "evidence_excerpt",
        ]
    )
    for finding in report.findings:
        writer.writerow(
            [
                report.site.company_name,
                report.site.site_url,
                finding.family,
                finding.severity,
                finding.lifecycle,
                finding.code,
                finding.page_url or "",
                finding.title,
                finding.detail,
                finding.recommendation,
                " | ".join(item.get("excerpt", "") for item in finding.evidence),
            ]
        )
    return output.getvalue()


def build_questions_csv(report: ServiceVisibilityReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["key", "question", "status", "rationale", "evidence_urls", "evidence_excerpts"])
    for result in report.buyer_questions:
        writer.writerow(
            [
                result.key,
                result.question,
                result.status,
                result.rationale,
                " | ".join(item.get("url", "") for item in result.evidence),
                " | ".join(item.get("excerpt", "") for item in result.evidence),
            ]
        )
    return output.getvalue()


def build_content_brief_markdown(report: ServiceVisibilityReport) -> str:
    lines = [
        f"# {report.site.company_name} service visibility remediation brief",
        "",
        f"Site: {report.site.site_url}",
        f"Generated: {report.generated_at.isoformat()}",
        "",
        "## Scorecard",
        "",
        f"- Overall: {report.scorecard.overall}/100",
        f"- Technical SEO: {report.scorecard.technical_seo}/100",
        f"- Answer readiness: {report.scorecard.aeo}/100",
        f"- AI discovery readiness: {report.scorecard.ai_discovery}/100",
        f"- Site architecture: {report.scorecard.architecture}/100",
        f"- Evidence confidence: {report.scorecard.confidence}/100",
        "",
        "## Executive summary",
        "",
    ]
    lines.extend(f"- {item}" for item in report.executive_summary)
    lines.extend(["", "## Priority page briefs", ""])
    priority = [finding for finding in report.findings if finding.severity in {"critical", "high"}]
    grouped: dict[str, list[ServiceFinding]] = {}
    for finding in priority:
        grouped.setdefault(finding.page_url or "Site-wide", []).append(finding)
    for page_url, findings in list(grouped.items())[:20]:
        lines.extend([f"### {page_url}", ""])
        for finding in findings:
            lines.extend(
                [
                    f"**{finding.title}** ({finding.severity})",
                    "",
                    finding.detail,
                    "",
                    f"Recommended change: {finding.recommendation}",
                    "",
                ]
            )
    lines.extend(["## Buyer questions without sufficient support", ""])
    for result in report.buyer_questions:
        if result.status in {"unsupported", "partially_supported", "conflicting"}:
            lines.extend([f"- **{result.question}** — {result.status}: {result.rationale}"])
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- {item}" for item in report.disclaimers)
    lines.append("")
    return "\n".join(lines)


def _slides(report: ServiceVisibilityReport) -> tuple[Slide, ...]:
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in report.findings:
        if finding.severity in counts:
            counts[finding.severity] += 1
    unsupported = sum(item.status == "unsupported" for item in report.buyer_questions)
    top_findings = sorted(
        report.findings,
        key=lambda finding: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}[finding.severity],
            finding.title,
        ),
    )[:5]
    finding_lines = tuple(
        f"{finding.severity.upper()}: {finding.title}"
        for finding in top_findings
    ) or ("No priority findings were produced.",)
    return (
        Slide(
            "Catora service visibility assessment",
            (
                report.site.company_name,
                report.site.site_url,
                f"{len(report.site.pages)} authorized public pages analyzed",
                "SEO, answer readiness, and AI discovery evidence — without ranking guarantees",
            ),
        ),
        Slide(
            "Executive scorecard",
            (
                f"Overall visibility readiness: {report.scorecard.overall}/100",
                f"Technical SEO: {report.scorecard.technical_seo}/100",
                f"Answer readiness: {report.scorecard.aeo}/100",
                f"AI discovery readiness: {report.scorecard.ai_discovery}/100",
                f"Site architecture: {report.scorecard.architecture}/100",
            ),
        ),
        Slide(
            "Finding profile",
            (
                f"Critical: {counts['critical']}; high: {counts['high']}; medium: {counts['medium']}; low: {counts['low']}",
                f"New: {report.continuity.new_findings}; persisting: {report.continuity.persisting_findings}; resolved: {report.continuity.resolved_findings}",
                *finding_lines[:4],
            ),
        ),
        Slide(
            "Service and evidence coverage",
            (
                f"Services identified: {len(report.site.service_names)}",
                f"Industries identified: {len(report.site.industry_names)}",
                f"Locations identified: {len(report.site.location_names)}",
                f"Evidence pages: {report.site.evidence_page_count}",
            ),
        ),
        Slide(
            "Buyer-question coverage",
            (
                f"Questions evaluated: {len(report.buyer_questions)}",
                f"Unsupported questions: {unsupported}",
                "Every result is linked to public-page evidence or explicitly marked unsupported.",
                "FAQ rich results, AI citations, traffic, leads, and rankings are not promised.",
            ),
        ),
        Slide(
            "Controlled remediation",
            (
                "Prioritize critical technical and architecture blockers first.",
                "Strengthen service definitions, process, evidence, and named expertise.",
                "Create WordPress drafts only after explicit approval; never publish automatically.",
                "Re-scan after approved changes and preserve before-and-after evidence.",
            ),
        ),
    )


def build_report_pptx(report: ServiceVisibilityReport) -> bytes:
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
            f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>{presentation_ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>''',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>{presentation_rels}</Relationships>''',
        )
        archive.writestr("ppt/slideMasters/slideMaster1.xml", SLIDE_MASTER)
        archive.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>''',
        )
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", SLIDE_LAYOUT)
        archive.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>''',
        )
        archive.writestr("ppt/theme/theme1.xml", THEME)
        archive.writestr(
            "docProps/core.xml",
            f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{html.escape(report.site.company_name)} service visibility assessment</dc:title><dc:creator>Catora</dc:creator></cp:coreProperties>''',
        )
        archive.writestr(
            "docProps/app.xml",
            f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Catora</Application><Slides>{len(slides)}</Slides></Properties>''',
        )
        for index, slide in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(slide))
            archive.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels",
                '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>''',
            )
    return output.getvalue()
