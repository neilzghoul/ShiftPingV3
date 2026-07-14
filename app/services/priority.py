"""Priority history – track preference satisfaction for fair weekly weighting."""

from __future__ import annotations

from typing import Any

from app.services import db, employees, preferences
from app.utils.hebrew import DAYS_HE, PREF_WANT, SHIFTS_HE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

COLLECTION = "priority_history"

# preferences_satisfied → priority_score (higher = scheduler favors their prefs next week)
SCORE_BY_SATISFIED: dict[int, int] = {
    0: 100,
    1: 80,
    2: 60,
    3: 40,
}

DEFAULT_PRIORITY_SCORE = 50  # no history yet


def priority_doc_id(nurse_id: str, week: str) -> str:
    return f"{nurse_id}_{week}"


def score_from_satisfied(count: int) -> int:
    clamped = max(0, min(3, int(count)))
    return SCORE_BY_SATISFIED[clamped]


def count_preferences_satisfied(
    nurse_id: str,
    week: str,
    grid: dict[str, dict[str, list[str]]],
) -> int:
    """Count assigned shifts that match the nurse's WANT preference (0–3)."""
    prefs = preferences.get_preferences(nurse_id, week).get("grid") or {}
    satisfied = 0
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            if nurse_id not in (grid.get(day) or {}).get(shift, []):
                continue
            if (prefs.get(day) or {}).get(shift) == PREF_WANT:
                satisfied += 1
    return min(satisfied, 3)


def record_priority_for_week(
    week: str,
    grid: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """Analyze schedule + prefs and upsert priority_history rows for all active nurses."""
    if grid is None:
        from app.services import scheduler

        sched = scheduler.get_schedule(week)
        if not sched:
            raise LookupError(f"לא נמצא סידור לשבוע {week}")
        grid = sched.get("grid") or {}

    recorded: list[dict[str, Any]] = []
    for emp in employees.list_employees(active_only=True):
        nurse_id = emp["id"]
        satisfied = count_preferences_satisfied(nurse_id, week, grid)
        priority_score = score_from_satisfied(satisfied)
        payload = {
            "nurse_id": nurse_id,
            "week": week,
            "preferences_satisfied": satisfied,
            "priority_score": priority_score,
            "nurse_name": emp.get("name", ""),
        }
        doc = db.upsert_doc(COLLECTION, priority_doc_id(nurse_id, week), payload)
        recorded.append(doc)
        logger.info(
            "Priority recorded nurse=%s week=%s satisfied=%d score=%d",
            emp.get("name") or nurse_id,
            week,
            satisfied,
            priority_score,
        )
    return recorded


def list_priority_history(*, week: str | None = None, nurse_id: str | None = None) -> list[dict[str, Any]]:
    filters: list[tuple[str, str, Any]] = []
    if week:
        filters.append(("week", "==", week))
    if nurse_id:
        filters.append(("nurse_id", "==", nurse_id))
    docs = db.list_docs(COLLECTION, filters=filters or None)
    return sorted(
        docs,
        key=lambda d: (d.get("week") or "", -int(d.get("priority_score") or 0), d.get("nurse_name") or ""),
    )


def get_latest_priority_scores(before_week: str | None = None) -> dict[str, int]:
    """Map nurse_id → most recent priority_score (optionally only weeks before *before_week*)."""
    docs = list_priority_history()
    if before_week:
        docs = [d for d in docs if (d.get("week") or "") < before_week]

    by_nurse: dict[str, dict[str, Any]] = {}
    for d in docs:
        nid = d.get("nurse_id")
        if not nid:
            continue
        prev = by_nurse.get(nid)
        if prev is None or (d.get("week") or "") > (prev.get("week") or ""):
            by_nurse[nid] = d

    return {
        nid: int(d.get("priority_score", DEFAULT_PRIORITY_SCORE))
        for nid, d in by_nurse.items()
    }


def get_priority_scores_for_scheduling(week: str) -> dict[str, int]:
    """Scores to use when generating *week* (from prior weeks' history)."""
    scores = get_latest_priority_scores(before_week=week)
    # Fill defaults for active staff with no history
    for emp in employees.list_employees(active_only=True):
        scores.setdefault(emp["id"], DEFAULT_PRIORITY_SCORE)
    return scores
