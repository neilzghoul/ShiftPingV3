"""Weekly preference storage and WhatsApp preference parsing."""

from __future__ import annotations

from typing import Any

from app.services import db
from app.utils.dates import week_id as current_week_id
from app.utils.hebrew import (
    DAYS_HE,
    PREF_CAN,
    PREF_NO,
    PREF_WANT,
    SHIFTS_HE,
    parse_day,
    parse_pref,
    parse_shift,
)
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def empty_grid() -> dict[str, dict[str, str | None]]:
    """day → shift → preference (WANT/CAN/NO/None)."""
    return {day: {shift: None for shift in SHIFTS_HE} for day in DAYS_HE}


def pref_doc_id(employee_id: str, week: str) -> str:
    return f"{employee_id}_{week}"


def get_preferences(employee_id: str, week: str | None = None) -> dict[str, Any]:
    week = week or current_week_id()
    doc = db.get_doc("preferences", pref_doc_id(employee_id, week))
    if doc:
        return doc
    return {
        "id": pref_doc_id(employee_id, week),
        "employeeId": employee_id,
        "weekId": week,
        "grid": empty_grid(),
        "submitted": False,
    }


def set_preference(
    employee_id: str,
    week: str,
    day: str,
    shift: str,
    preference: str | None,
) -> dict[str, Any]:
    if day not in DAYS_HE:
        raise ValueError(f"יום לא חוקי: {day}")
    if shift not in SHIFTS_HE:
        raise ValueError(f"משמרת לא חוקית: {shift}")
    if preference is not None and preference not in (PREF_WANT, PREF_CAN, PREF_NO):
        raise ValueError(f"העדפה לא חוקית: {preference}")

    doc_id = pref_doc_id(employee_id, week)
    existing = get_preferences(employee_id, week)
    grid = existing.get("grid") or empty_grid()
    grid.setdefault(day, {})[shift] = preference

    payload = {
        "employeeId": employee_id,
        "weekId": week,
        "grid": grid,
        "submitted": existing.get("submitted", False),
    }
    return db.upsert_doc("preferences", doc_id, payload)


def set_full_grid(
    employee_id: str,
    week: str,
    grid: dict[str, dict[str, str | None]],
    *,
    submitted: bool = True,
) -> dict[str, Any]:
    # Normalize / validate
    normalized = empty_grid()
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            val = (grid.get(day) or {}).get(shift)
            if val in (PREF_WANT, PREF_CAN, PREF_NO, None):
                normalized[day][shift] = val
            elif val:
                parsed = parse_pref(str(val))
                normalized[day][shift] = parsed

    doc_id = pref_doc_id(employee_id, week)
    payload = {
        "employeeId": employee_id,
        "weekId": week,
        "grid": normalized,
        "submitted": submitted,
    }
    return db.upsert_doc("preferences", doc_id, payload)


def list_preferences_for_week(week: str) -> list[dict[str, Any]]:
    return db.list_docs("preferences", filters=[("weekId", "==", week)])


def mark_submitted(employee_id: str, week: str) -> dict[str, Any]:
    doc = get_preferences(employee_id, week)
    return db.upsert_doc(
        "preferences",
        pref_doc_id(employee_id, week),
        {
            "employeeId": employee_id,
            "weekId": week,
            "grid": doc.get("grid") or empty_grid(),
            "submitted": True,
        },
    )


def parse_preference_message(text: str) -> list[tuple[str, str, str]]:
    """Parse free-text Hebrew preference lines.

    Supported formats (one per line or semicolon-separated):
      ראשון בוקר רוצה
      שני ערב לא
      שלישי לילה יכול
      ראשון בוקר=רוצה
      WANT ראשון בוקר
    """
    results: list[tuple[str, str, str]] = []
    cleaned = text.replace(",", " ").replace("=", " ").replace(":", " ")
    chunks = []
    for part in cleaned.replace(";", "\n").splitlines():
        part = part.strip()
        if part:
            chunks.append(part)

    for chunk in chunks:
        tokens = chunk.split()
        if len(tokens) < 2:
            continue

        day = shift = pref = None
        for tok in tokens:
            if day is None and parse_day(tok):
                day = parse_day(tok)
            elif shift is None and parse_shift(tok):
                shift = parse_shift(tok)
            elif pref is None and parse_pref(tok):
                pref = parse_pref(tok)

        if day and shift and pref:
            results.append((day, shift, pref))

    return results


def preference_summary_he(grid: dict[str, dict[str, str | None]]) -> str:
    lines: list[str] = []
    labels = {PREF_WANT: "רוצה", PREF_CAN: "יכול/ה", PREF_NO: "לא"}
    for day in DAYS_HE:
        day_parts = []
        for shift in SHIFTS_HE:
            val = (grid.get(day) or {}).get(shift)
            if val:
                day_parts.append(f"{shift}:{labels.get(val, val)}")
        if day_parts:
            lines.append(f"יום {day}: " + ", ".join(day_parts))
    return "\n".join(lines) if lines else "(אין העדפות עדיין)"
