from pathlib import Path

api_path = Path("apps/api/catora_api/api/diagnostics.py")
api_text = api_path.read_text(encoding="utf-8")
api_text = api_text.replace(
    "from typing import Annotated\n",
    "from typing import Annotated, cast\n",
    1,
)
api_text = api_text.replace(
    "        assessment.workspace_id,\n    )\n",
    "        cast(uuid.UUID, assessment.workspace_id),\n    )\n",
    1,
)
if "cast(uuid.UUID, assessment.workspace_id)" not in api_text:
    raise SystemExit("API MyPy patch did not apply")
api_path.write_text(api_text, encoding="utf-8")

task_path = Path("apps/api/catora_api/diagnostics/tasks.py")
task_text = task_path.read_text(encoding="utf-8")
task_text = task_text.replace(
    "from collections import defaultdict\n\nfrom celery",
    "from collections import defaultdict\nfrom typing import cast\n\nfrom celery",
    1,
)
task_text = task_text.replace(
    "        workspace_id = assessment.workspace_id\n",
    "        workspace_id = cast(uuid.UUID, assessment.workspace_id)\n",
    1,
)
task_text = task_text.replace(
    '            locale = snapshot.get("locale") if isinstance(snapshot.get("locale"), str) else "en-US"\n',
    '            locale_value = snapshot.get("locale")\n            locale = locale_value if isinstance(locale_value, str) else "en-US"\n',
    1,
)
task_text = task_text.replace(
    "                persisted = await intent_service.execute(\n",
    "                intent_result = await intent_service.execute(\n",
    1,
)
for old, new in (
    ("intent_run_ids.append(str(persisted.run.id))", "intent_run_ids.append(str(intent_result.run.id))"),
    ("entity_id=persisted.run.id", "entity_id=intent_result.run.id"),
    ("persisted.summary.target_count", "intent_result.summary.target_count"),
    ("persisted.summary.confident_match_count", "intent_result.summary.confident_match_count"),
    ("persisted.summary.possible_match_missing_data_count", "intent_result.summary.possible_match_missing_data_count"),
    ("persisted.summary.non_match_count", "intent_result.summary.non_match_count"),
    ("persisted.summary.insufficient_category_data_count", "intent_result.summary.insufficient_category_data_count"),
):
    task_text = task_text.replace(old, new, 1)
task_text = task_text.replace(
    "            persisted = await session.get(ReportJob, assessment_id)\n            if persisted is None:\n",
    "            failed_assessment = await session.get(ReportJob, assessment_id)\n            if failed_assessment is None:\n",
    1,
)
task_text = task_text.replace(
    '            stage = persisted.status.replace("_", " ")\n',
    '            stage = failed_assessment.status.replace("_", " ")\n',
    1,
)
task_text = task_text.replace(
    "                persisted,\n                \"failed\",\n",
    "                failed_assessment,\n                \"failed\",\n",
    1,
)
task_text = task_text.replace(
    "                    workspace_id=persisted.workspace_id,\n",
    "                    workspace_id=failed_assessment.workspace_id,\n",
    1,
)
task_text = task_text.replace(
    "                    entity_id=persisted.id,\n",
    "                    entity_id=failed_assessment.id,\n",
    1,
)
if "failed_assessment" not in task_text or "intent_result" not in task_text:
    raise SystemExit("Task MyPy patch did not apply")
task_path.write_text(task_text, encoding="utf-8")
