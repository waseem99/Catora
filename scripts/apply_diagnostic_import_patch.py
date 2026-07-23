from pathlib import Path

path = Path("apps/api/catora_api/diagnostics/tasks.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from collections import defaultdict\nfrom celery import shared_task\n",
    "from collections import defaultdict\n\nfrom celery import shared_task\n",
    1,
)
if "from collections import defaultdict\n\nfrom celery" not in text:
    raise SystemExit("Task import patch did not apply")
path.write_text(text, encoding="utf-8")
