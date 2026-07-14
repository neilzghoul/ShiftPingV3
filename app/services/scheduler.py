"""Automatic weekly schedule generation with constraints and fairness.

Hard constraints:
  1. No nurse works the same shift type twice in one week
  2. Night may not be followed by any shift the next day (rest required)
  3. Morning may only be followed by evening (same day or next day)
  4. Evening may only be followed by night (same day or next day)
  5. NEVER assign PREF_NO

Soft goals:
  - Prefer WANT over CAN over unanswered
  - Fairness: balance total shifts across nurses
  - Priority history: higher priority_score → try harder to hit WANT prefs
  - Fill nurses_per_shift slots when possible
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.config import config
from app.services import db, employees, preferences, priority
from app.utils.dates import next_week_id, week_id as current_week_id
from app.utils.hebrew import DAYS_HE, PREF_NO, PREF_PRIORITY, PREF_WANT, SHIFTS_HE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

SHIFT_ORDER = {s: i for i, s in enumerate(SHIFTS_HE)}  # בוקר=0, ערב=1, לילה=2

# After shift A, the only allowed next shift type (before a rest gap after night)
ALLOWED_NEXT: dict[str, str | None] = {
    "בוקר": "ערב",
    "ערב": "לילה",
    "לילה": None,  # must rest next calendar day; new sequence only after that
}


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


def _slot_key(day: str, shift: str) -> tuple[int, int]:
    return (DAYS_HE.index(day), SHIFT_ORDER[shift])


def assignments_for_employee(
    grid: dict[str, dict[str, list[str]]],
    employee_id: str,
) -> list[tuple[str, str]]:
    """Chronological list of (day, shift) for one employee."""
    result: list[tuple[str, str]] = []
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            if employee_id in (grid.get(day) or {}).get(shift, []):
                result.append((day, shift))
    return result


def why_ineligible(
    employee_id: str,
    day: str,
    shift: str,
    grid: dict[str, dict[str, list[str]]],
    prefs_grid: dict | None = None,
) -> str | None:
    """Return Hebrew reason if assignment is illegal, else None."""
    if _pref_score(prefs_grid, day, shift) < 0:
        return "העדפת לא (NO)"

    existing = assignments_for_employee(grid, employee_id)
    used_types = {s for _, s in existing}
    if shift in used_types:
        return f"כבר משובצ/ת למשמרת {shift} השבוע"

    if not existing:
        return None

    last_day, last_shift = existing[-1]
    last_i = DAYS_HE.index(last_day)
    day_i = DAYS_HE.index(day)
    last_key = _slot_key(last_day, last_shift)
    new_key = _slot_key(day, shift)

    if new_key <= last_key:
        return "משמרת אינה אחרי ההשמה הקודמת כרונולוגית"

    # Night → must rest the entire next calendar day
    if last_shift == "לילה":
        if day_i == last_i + 1:
            return f"לילה ביום {last_day} מחייב מנוחה ביום {day}"
        # After rest day (or later), may start a new unused shift type
        return None

    allowed = ALLOWED_NEXT.get(last_shift)
    if allowed is None:
        return f"אחרי {last_shift} אין המשך חוקי"

    if shift != allowed:
        return f"אחרי {last_shift} מותר רק {allowed} (לא {shift})"

    # Morning→evening and evening→night: same day or next day only
    if day_i not in (last_i, last_i + 1):
        return (
            f"מעבר {last_shift}→{shift} חייב באותו יום או למחרת "
            f"({last_day}→{day})"
        )

    return None


def can_assign(
    employee_id: str,
    day: str,
    shift: str,
    grid: dict[str, dict[str, list[str]]],
    prefs_grid: dict | None = None,
) -> bool:
    return why_ineligible(employee_id, day, shift, grid, prefs_grid) is None


def validate_schedule(grid: dict[str, dict[str, list[str]]]) -> list[str]:
    """Return Hebrew warning messages for all constraint violations."""
    warnings: list[str] = []
    emp_ids: set[str] = set()
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            emp_ids.update((grid.get(day) or {}).get(shift, []))

    for eid in sorted(emp_ids):
        emp = employees.get_employee(eid)
        name = emp["name"] if emp else eid
        assigns = assignments_for_employee(grid, eid)

        # 1. Same shift type twice
        by_type: dict[str, list[str]] = defaultdict(list)
        for day, shift in assigns:
            by_type[shift].append(day)
        for shift, days in by_type.items():
            if len(days) > 1:
                msg = f"{name}: משמרת {shift} יותר מפעם אחת ({', '.join(days)})"
                warnings.append(msg)
                logger.warning("Constraint: %s", msg)

        # Sequence / rest rules along chronological assignments
        for i in range(1, len(assigns)):
            prev_day, prev_shift = assigns[i - 1]
            cur_day, cur_shift = assigns[i]
            prev_i = DAYS_HE.index(prev_day)
            cur_i = DAYS_HE.index(cur_day)

            if prev_shift == "לילה":
                if cur_i == prev_i + 1:
                    tag = "לילה→בוקר" if cur_shift == "בוקר" else "לילה→משמרת ללא מנוחה"
                    msg = f"{tag}: {name} ({prev_day} לילה → {cur_day} {cur_shift})"
                    warnings.append(msg)
                    logger.warning("Constraint: %s", msg)
                # After a rest gap, sequence restarts — no further check
                continue

            allowed = ALLOWED_NEXT.get(prev_shift)
            if cur_shift != allowed:
                msg = (
                    f"מעבר לא חוקי {prev_shift}→{cur_shift}: {name} "
                    f"({prev_day}→{cur_day})"
                )
                warnings.append(msg)
                logger.warning("Constraint: %s", msg)
                continue

            if cur_i not in (prev_i, prev_i + 1):
                msg = (
                    f"מעבר {prev_shift}→{cur_shift} רחוק מדי: {name} "
                    f"({prev_day}→{cur_day}; מותר אותו יום או למחרת)"
                )
                warnings.append(msg)
                logger.warning("Constraint: %s", msg)

    if warnings:
        logger.info("validate_schedule: %d violation(s)", len(warnings))
    else:
        logger.debug("validate_schedule: no violations")

    return warnings


def generate_schedule(
    week: str | None = None,
    *,
    nurses_per_shift: int | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Generate a weekly schedule respecting preferences, sequences, and fairness."""
    week = week or next_week_id()
    nps = nurses_per_shift or config.NURSES_PER_SHIFT
    active = employees.list_employees(active_only=True)
    if not active:
        raise ValueError("אין עובדים פעילים ליצירת סידור")

    prefs_by_emp: dict[str, dict] = {}
    for emp in active:
        prefs_by_emp[emp["id"]] = preferences.get_preferences(emp["id"], week).get("grid") or {}

    priority_scores = priority.get_priority_scores_for_scheduling(week)
    for emp in active:
        eid = emp["id"]
        ps = priority_scores.get(eid, priority.DEFAULT_PRIORITY_SCORE)
        logger.info(
            "Priority applied nurse=%s week=%s priority_score=%d",
            emp.get("name") or eid,
            week,
            ps,
        )

    grid = empty_schedule_grid()
    shift_counts: dict[str, int] = {e["id"]: 0 for e in active}
    log: list[str] = []
    skip_log_count = 0
    priority_boost_log = 0

    def try_place(day: str, shift: str, *, pass_name: str) -> None:
        nonlocal skip_log_count, priority_boost_log
        while len(grid[day][shift]) < nps:
            candidates: list[tuple[float, str]] = []
            for emp in active:
                eid = emp["id"]
                if eid in grid[day][shift]:
                    continue
                reason = why_ineligible(eid, day, shift, grid, prefs_by_emp.get(eid))
                if reason:
                    skip_log_count += 1
                    if skip_log_count <= 40:
                        logger.debug(
                            "Skip %s for %s %s (%s): %s",
                            eid,
                            day,
                            shift,
                            pass_name,
                            reason,
                        )
                    continue
                score = _pref_score(prefs_by_emp.get(eid), day, shift)
                fairness = -shift_counts[eid] * 10
                weight = 100 if pass_name == "primary" else 50
                p_score = priority_scores.get(eid, priority.DEFAULT_PRIORITY_SCORE)
                # Higher historical priority → stronger pull onto WANT slots
                pref_val = (prefs_by_emp.get(eid) or {}).get(day, {}).get(shift)
                if pref_val == PREF_WANT:
                    priority_boost = p_score * 2.0
                else:
                    priority_boost = p_score * 0.15
                total = score * weight + fairness + priority_boost
                if priority_boost and priority_boost_log < 25:
                    logger.debug(
                        "Priority boost nurse=%s day=%s shift=%s want=%s boost=%.1f score=%.1f",
                        eid,
                        day,
                        shift,
                        pref_val == PREF_WANT,
                        priority_boost,
                        total,
                    )
                    priority_boost_log += 1
                candidates.append((total, eid))

            if not candidates:
                break
            candidates.sort(key=lambda x: (-x[0], x[1]))
            eid = candidates[0][1]
            grid[day][shift].append(eid)
            shift_counts[eid] += 1
            logger.debug("Assign %s → %s %s (%s)", eid, day, shift, pass_name)
            if pass_name == "fill":
                log.append(f"מילוי נוסף: יום {day} {shift} ← {eid}")

    # Primary pass: fill by shift type across ALL 7 days first
    # (avoids burning capacity on Sun–Thu before Fri/Sat are considered).
    for shift in SHIFTS_HE:
        for day in DAYS_HE:
            before = len(grid[day][shift])
            try_place(day, shift, pass_name="primary")
            after = len(grid[day][shift])
            if after < nps:
                msg = f"יום {day} {shift}: מולאו {after}/{nps} מקומות"
                log.append(msg)
                logger.warning("Understaffed: %s", msg)
            elif after > before:
                logger.info("Filled %s %s: %d nurse(s)", day, shift, after)

    # Second pass: fill remaining gaps day-by-day (incl. שישי/שבת)
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            if len(grid[day][shift]) < nps:
                try_place(day, shift, pass_name="fill")

    # Coverage summary for all 7 days
    for day in DAYS_HE:
        filled = sum(len(grid[day][s]) for s in SHIFTS_HE)
        target = nps * len(SHIFTS_HE)
        log.append(f"כיסוי יום {day}: {filled}/{target}")
        logger.info("Day coverage %s: %d/%d", day, filled, target)

    violations = validate_schedule(grid)
    for v in violations:
        log.append(f"אזהרת אילוץ: {v}")

    name_of = {e["id"]: e["name"] for e in active}
    counts_summary = ", ".join(
        f"{name_of[eid]}:{cnt}"
        for eid, cnt in sorted(shift_counts.items(), key=lambda x: -x[1])
    )
    prio_summary = ", ".join(
        f"{name_of[eid]}:{priority_scores.get(eid, priority.DEFAULT_PRIORITY_SCORE)}"
        for eid in sorted(name_of, key=lambda i: -priority_scores.get(i, 0))
    )
    log.append(f"סיכום משמרות: {counts_summary}")
    log.append(f"ציוני עדיפות בשימוש: {prio_summary}")
    log.append(f"דילוגי אילוץ (סריקות): {skip_log_count}")
    logger.info(
        "Generated schedule for %s – %s (violations=%d, skips=%d, priorities=%s)",
        week,
        counts_summary,
        len(violations),
        skip_log_count,
        prio_summary,
    )

    result = {
        "weekId": week,
        "grid": grid,
        "status": "draft",
        "published": False,
        "generationLog": log,
        "shiftCounts": shift_counts,
        "constraintViolations": violations,
        "priorityScoresUsed": priority_scores,
    }
    if save:
        saved = save_schedule(week, grid, status="draft", published=False, generationLog=log)
        result.update(saved)
        result["constraintViolations"] = violations
        result["shiftCounts"] = shift_counts
        result["priorityScoresUsed"] = priority_scores
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
    violations = validate_schedule(grid)
    for v in violations:
        logger.warning("Manual edit violation on %s: %s", week, v)

    return save_schedule(
        week,
        grid,
        status=schedule.get("status", "draft"),
        published=schedule.get("published", False),
        notes=schedule.get("notes", ""),
        generationLog=schedule.get("generationLog", []),
    )


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
    return assignments_for_employee(schedule.get("grid") or {}, employee_id)
