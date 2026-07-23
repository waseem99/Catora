from pathlib import Path

path = Path("apps/api/catora_api/api/diagnostics.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "    IngestionJob,\n    ReportJob,\n    Workspace,\n",
    "    IngestionJob,\n    Organization,\n    ReportJob,\n    Workspace,\n",
)
text = text.replace(
    "    await session.execute(\n        delete(Workspace).where(Workspace.id == assessment.workspace_id)\n    )\n    await session.commit()\n",
    "    organization_id = _snapshot_uuid(snapshot, \"organization_id\")\n    if organization_id is None:\n        raise HTTPException(status_code=409, detail=\"Diagnostic organization is unavailable\")\n    await session.execute(\n        delete(Organization).where(Organization.id == organization_id)\n    )\n    await session.commit()\n",
    1,
)
text = text.replace(
    "        await session.execute(\n            delete(Workspace).where(Workspace.id == assessment.workspace_id)\n        )\n        purged += 1\n",
    "        organization_id = _snapshot_uuid(snapshot, \"organization_id\")\n        if organization_id is None:\n            continue\n        await session.execute(\n            delete(Organization).where(Organization.id == organization_id)\n        )\n        purged += 1\n",
    1,
)
if "Diagnostic organization is unavailable" not in text:
    raise SystemExit("Cleanup patch did not apply")
path.write_text(text, encoding="utf-8")
