from pathlib import Path

replacements = {
    Path("apps/api/catora_api/api/diagnostics.py"): [
        ("    ReportJob,\n    Workspace,\n", "    ReportJob,\n"),
    ],
    Path("apps/api/catora_api/diagnostics/tasks.py"): [
        ("from typing import Any\n\n", ""),
        (
            "def _prepared_intents(*, locale: str, market_id: uuid.UUID | None) -> tuple[tuple[str, StructuredBuyerIntent], ...]:\n",
            "def _prepared_intents(\n    *,\n    locale: str,\n    market_id: uuid.UUID | None,\n) -> tuple[tuple[str, StructuredBuyerIntent], ...]:\n",
        ),
        (
            '                "query": "Which outdoor furniture is clearly suitable for outdoor use and easy care?",\n',
            '                "query": (\n                    "Which outdoor furniture is clearly suitable for outdoor use "\n                    "and easy care?"\n                ),\n',
        ),
    ],
    Path("apps/api/catora_api/schemas/diagnostics.py"): [
        (
            '    locale: str = Field(min_length=2, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")\n',
            '    locale: str = Field(\n        min_length=2,\n        max_length=35,\n        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",\n    )\n',
        ),
    ],
    Path("apps/api/scripts/validate_prospect_diagnostic.py"): [
        ("import uuid\n\n", ""),
    ],
}

for path, changes in replacements.items():
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in changes:
        text = text.replace(old, new, 1)
    if text == original:
        raise SystemExit(f"No Ruff patch applied to {path}")
    path.write_text(text, encoding="utf-8")
