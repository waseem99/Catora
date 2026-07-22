from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def next_finding_status(previous_status: str | None) -> str:
    if previous_status is None:
        return "new"
    if previous_status == "resolved":
        return "regressed"
    return "ongoing"


def finding_count_summary(
    current_statuses: Iterable[str],
    *,
    resolved_count: int,
) -> dict[str, object]:
    counts = Counter(current_statuses)
    return {
        "new": counts["new"],
        "ongoing": counts["ongoing"],
        "regressed": counts["regressed"],
        "resolved": resolved_count,
        "open_total": counts["new"] + counts["ongoing"] + counts["regressed"],
    }
