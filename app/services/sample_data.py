"""Sample nurses and preferences for local testing."""

from __future__ import annotations

from app.services import db, employees, preferences
from app.utils.dates import next_week_id
from app.utils.hebrew import DAYS_HE, PREF_CAN, PREF_NO, PREF_WANT, SHIFTS_HE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

SAMPLE_EMPLOYEES = [
    {"name": "נועה כהן", "gender": "female", "phone": "+972501111001", "notes": "ותיקה"},
    {"name": "יעל לוי", "gender": "female", "phone": "+972501111002", "notes": ""},
    {"name": "מיכל אברהם", "gender": "female", "phone": "+972501111003", "notes": ""},
    {"name": "דנה שמש", "gender": "female", "phone": "+972501111004", "notes": "מעדיפה בוקר"},
    {"name": "רונית גולן", "gender": "female", "phone": "+972501111005", "notes": ""},
    {"name": "אבי מזרחי", "gender": "male", "phone": "+972501111006", "notes": ""},
    {"name": "יוסי פרץ", "gender": "male", "phone": "+972501111007", "notes": "מוכן לילות"},
    {"name": "דוד חדד", "gender": "male", "phone": "+972501111008", "notes": ""},
]


def _pattern_for(index: int) -> dict:
    """Deterministic preference pattern per nurse index."""
    grid = {day: {shift: PREF_CAN for shift in SHIFTS_HE} for day in DAYS_HE}
    # Rotate WANT / NO for variety
    want_day = DAYS_HE[index % 7]
    no_day = DAYS_HE[(index + 3) % 7]
    want_shift = SHIFTS_HE[index % 3]
    no_shift = SHIFTS_HE[(index + 1) % 3]
    grid[want_day][want_shift] = PREF_WANT
    grid[no_day][no_shift] = PREF_NO
    # Extra NO on Shabbat night for some
    if index % 2 == 0:
        grid["שבת"]["לילה"] = PREF_NO
    return grid


def seed_sample_data(*, reset: bool = False) -> dict:
    """Load sample employees + preferences. Safe to re-run if reset=False (skips existing phones)."""
    if reset and db.using_mock():
        db.clear_mock_store()

    created = []
    week = next_week_id()

    for i, raw in enumerate(SAMPLE_EMPLOYEES):
        existing = employees.find_by_phone(raw["phone"])
        if existing:
            emp = existing
        else:
            emp = employees.create_employee({**raw, "active": True})
            created.append(emp["id"])

        preferences.set_full_grid(emp["id"], week, _pattern_for(i), submitted=True)

    logger.info("Seeded %d employees for week %s (%d new)", len(SAMPLE_EMPLOYEES), week, len(created))
    return {
        "weekId": week,
        "employees": employees.list_employees(),
        "createdCount": len(created),
    }
