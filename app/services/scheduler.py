"""Automatic weekly schedule generation with constraints and fairness.

Constraints:
  - No double shifts on the same day for one nurse
  - No night → morning (insufficient rest)
  - NEVER assign PREF_NO
  - Prefer WANT over CAN over unanswered
  - Fairness: balance total shifts across nurses
  - Fill nurses_per_shift slots when possible
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.config import config
from app.services import db, employees, preferences
from app.utils.dates import next_week_id, week_id as current_week_id
from app.utils.hebrew import DAYS_HE, PREF_NO, PREF_PRIORITY, SHIFTS_HE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def empty_schedule_grid() -> dict[str, dict[str, list[str]]]:
    """day → shift → list of employee ids."""
    return {day: {shift: [] for shift in SHIFTS_HE} for day in DAYS_HE}


def get_schedule(week: str | None = None) -> dict[str, Any] | None:
    week = week or current_week_id()
    return db.get_doc("schedules", week)


def save_schedule(week: str, grid: dict, **meta: Any) -> dict[str, Any]:
    payload = {
        "weekId": week,
        "grid": grid,
        "status": meta.get("status", "draft"),
        "published": meta.get("published", False),
        "notes": meta.get("notes", ""),
        "generationLog": meta.get("generationLog", []),
    }
    return db.upsert_doc("schedules", week, payload)


def _pref_score(grid: dict | None, day: str, shift: str) -> int:
    if not grid:
        return PREF_PRIORITY[None]
    val = (grid.get(day) or {}).get(shift)
    if val == PREF_NO:
        return -1
    return PREF_PRIORITY.get(val, PREF_PRIORITY[None])


def generate_schedule(
    week: str | None = None,
    *,
    nurses_per_shift: int | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Generate a weekly schedule respecting preferences and fairness."""
    week = week or next_week_id()
    nps = nurses_per_shift or config.NURSES_PER_SHIFT
    active = employees.list_employees(active_only=True)
    if not active:
        raise ValueError("אין עובדים פעילים ליצירת סידור")

    prefs_by_emp: dict[str, dict] = {}
    for emp in active:
        prefs_by_emp[emp["id"]] = preferences.get_preferences(emp["id"], week).get("grid") or {}

    # assignments: day → shift → [emp_ids]
    grid = empty_schedule_grid()
    # Track which shifts each emp got that day (for double-shift ban)
    day_shifts: dict[str, dict[str, set[str]]] = {d: defaultdict(set) for d in DAYS_HE}
    # Track night workers for rest rule
    night_workers: dict[str, set[str]] = {d: set() for d in DAYS_HE}
    shift_counts: dict[str, int] = {e["id"]: 0 for e in active}
    log: list[str] = []

    # Process days in order; within day: morning → evening → night
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            candidates: list[tuple[float, str]] = []
            for emp in active:
                eid = emp["id"]
                score = _pref_score(prefs_by_emp.get(eid), day, shift)
                if score < 0:
                    continue  # NO
                # Already assigned today?
                if day_shifts[day][eid]:
                    continue
                # Night → morning rest
                day_idx = DAYS_HE.index(day)
                if shift == "בוקר" and day_idx > 0:
                    prev = DAYS_HE[day_idx - 1]
                    if eid in night_workers[prev]:
                        continue

                # Fairness: prefer fewer shifts; WANT boost
                fairness = -shift_counts[eid] * 10
                total = score * 100 + fairness
                candidates.append((total, eid))

            candidates.sort(key=lambda x: (-x[0], x[1]))
            chosen = [eid for _, eid in candidates[:nps]]

            if len(chosen) < nps:
                log.append(
                    f"יום {day} {shift}: מולאו {len(chosen)}/{nps} מקומות"
                )

            for eid in chosen:
                grid[day][shift].append(eid)
                day_shifts[day][eid].add(shift)
                shift_counts[eid] += 1
                if shift == "לילה":
                    night_workers[day].add(eid)

    # Second pass: try to fill understaffed slots with remaining eligible (still respect NO)
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            while len(grid[day][shift]) < nps:
                best: tuple[float, str] | None = None
                assigned_set = set(grid[day][shift])
                for emp in active:
                    eid = emp["id"]
                    if eid in assigned_set:
                        continue
                    score = _pref_score(prefs_by_emp.get(eid), day, shift)
                    if score < 0:
                        continue
                    if day_shifts[day][eid]:
                        continue
                    day_idx = DAYS_HE.index(day)
                    if shift == "בוקר" and day_idx > 0:
                        prev = DAYS_HE[day_idx - 1]
                        if eid in night_workers[prev]:
                            continue
                    fairness = -shift_counts[eid] * 10
                    total = score * 50 + fairness
                    if best is None or total > best[0]:
                        best = (total, eid)
                if best is None:
                    break
                eid = best[1]
                grid[day][shift].append(eid)
                day_shifts[day][eid].add(shift)
                shift_counts[eid] += 1
                if shift == "לילה":
                    night_workers[day].add(eid)
                log.append(f"מילוי נוסף: יום {day} {shift} ← {eid}")

    counts_summary = ", ".join(
        f"{next(e['name'] for e in active if e['id'] == eid)}:{cnt}"
        for eid, cnt in sorted(shift_counts.items(), key=lambda x: -x[1])
    )
    log.append(f"סיכום משמרות: {counts_summary}")
    logger.info("Generated schedule for %s – %s", week, counts_summary)

    result = {
        "weekId": week,
        "grid": grid,
        "status": "draft",
        "published": False,
        "generationLog": log,
        "shiftCounts": shift_counts,
    }
    if save:
        saved = save_schedule(week, grid, status="draft", published=False, generationLog=log)
        result.update(saved)
    return result


def update_assignment(
    week: str,
    day: str,
    shift: str,
    employee_ids: list[str],
) -> dict[str, Any]:
    if day not in DAYS_HE:
        raise ValueError(f"יום לא חוקי: {day}")
    if shift not in SHIFTS_HE:
        raise ValueError(f"משמרת לא חוקית: {shift}")

    schedule = get_schedule(week)
    if not schedule:
        schedule = save_schedule(week, empty_schedule_grid(), status="draft")

    grid = schedule.get("grid") or empty_schedule_grid()
    grid.setdefault(day, {})[shift] = list(employee_ids)
    return save_schedule(
        week,
        grid,
        status=schedule.get("status", "draft"),
        published=schedule.get("published", False),
        notes=schedule.get("notes", ""),
        generationLog=schedule.get("generationLog", []),
    )


def validate_schedule(grid: dict[str, dict[str, list[str]]]) -> list[str]:
    """Return list of Hebrew warning messages for soft constraint violations."""
    warnings: list[str] = []
    # Double shift same day
    for day in DAYS_HE:
        emp_shifts: dict[str, list[str]] = defaultdict(list)
        for shift in SHIFTS_HE:
            for eid in grid.get(day, {}).get(shift, []):
                emp_shifts[eid].append(shift)
        for eid, shifts in emp_shifts.items():
            if len(shifts) > 1:
                emp = employees.get_employee(eid)
                name = emp["name"] if emp else eid
                warnings.append(f"יום {day}: {name} משובצ/ת ב-{', '.join(shifts)}")

    # Night → morning
    for i, day in enumerate(DAYS_HE):
        if i == 0:
            continue
        prev = DAYS_HE[i - 1]
        night = set(grid.get(prev, {}).get("לילה", []))
        morning = set(grid.get(day, {}).get("בוקר", []))
        for eid in night & morning:
            emp = employees.get_employee(eid)
            name = emp["name"] if emp else eid
            warnings.append(f"לילה→בוקר: {name} ({prev}→{day})")

    return warnings


def enrich_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Attach employee names for UI rendering."""
    emp_map = {e["id"]: e for e in employees.list_employees()}
    grid = schedule.get("grid") or {}
    enriched: dict[str, dict[str, list[dict]]] = {}
    for day in DAYS_HE:
        enriched[day] = {}
        for shift in SHIFTS_HE:
            ids = (grid.get(day) or {}).get(shift, [])
            enriched[day][shift] = [
                {
                    "id": eid,
                    "name": emp_map.get(eid, {}).get("name", eid),
                    "gender": emp_map.get(eid, {}).get("gender"),
                }
                for eid in ids
            ]
    out = dict(schedule)
    out["enriched"] = enriched
    out["warnings"] = validate_schedule(grid)
    return out


def personal_shifts(schedule: dict[str, Any], employee_id: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    grid = schedule.get("grid") or {}
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            if employee_id in (grid.get(day) or {}).get(shift, []):
                result.append((day, shift))
    return result
