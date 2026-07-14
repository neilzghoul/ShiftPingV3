"""Sample nurses and preferences for local testing (full Sun–Sat week)."""

from __future__ import annotations

from app.services import db, employees, preferences
from app.utils.dates import next_week_id
from app.utils.hebrew import DAYS_HE, PREF_CAN, PREF_NO, PREF_WANT, SHIFTS_HE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 14 nurses → enough capacity for 7 days × 3 shifts × 2 nurses/slot
# under "one of each shift type per week" constraints.
SAMPLE_EMPLOYEES = [
    {"name": "נועה כהן", "gender": "female", "phone": "+972501111001", "notes": "אחות אחראית", "role": "chief"},
    {"name": "יעל לוי", "gender": "female", "phone": "+972501111002", "notes": ""},
    {"name": "מיכל אברהם", "gender": "female", "phone": "+972501111003", "notes": ""},
    {"name": "דנה שמש", "gender": "female", "phone": "+972501111004", "notes": "מעדיפה בוקר"},
    {"name": "רונית גולן", "gender": "female", "phone": "+972501111005", "notes": ""},
    {"name": "שירי בן דוד", "gender": "female", "phone": "+972501111009", "notes": "סופי שבוע"},
    {"name": "תמר אלון", "gender": "female", "phone": "+972501111010", "notes": ""},
    {"name": "הילה רוזן", "gender": "female", "phone": "+972501111011", "notes": ""},
    {"name": "אבי מזרחי", "gender": "male", "phone": "+972501111006", "notes": ""},
    {"name": "יוסי פרץ", "gender": "male", "phone": "+972501111007", "notes": "מוכן לילות"},
    {"name": "דוד חדד", "gender": "male", "phone": "+972501111008", "notes": ""},
    {"name": "עידו שמעון", "gender": "male", "phone": "+972501111012", "notes": ""},
    {"name": "אורי נחמיאס", "gender": "male", "phone": "+972501111013", "notes": "שישי-שבת"},
    {"name": "אמיר קליין", "gender": "male", "phone": "+972501111014", "notes": ""},
]


def _pattern_for(index: int) -> dict:
    """Full 7-day preference grid (ראשון…שבת) with mixed WANT/CAN/NO."""
    grid = {day: {shift: PREF_CAN for shift in SHIFTS_HE} for day in DAYS_HE}

    # One WANT slot rotated across the full week (incl. שישי/שבת)
    want_day = DAYS_HE[index % 7]
    want_shift = SHIFTS_HE[index % 3]
    grid[want_day][want_shift] = PREF_WANT

    # One mid-week NO (avoid blanking the whole weekend)
    no_day = DAYS_HE[(index + 2) % 5]  # ראשון…חמישי only
    no_shift = SHIFTS_HE[(index + 1) % 3]
    if no_day != want_day or no_shift != want_shift:
        grid[no_day][no_shift] = PREF_NO

    # Weekend coverage: every nurse is available Fri/Sat by default (CAN).
    # A few nurses explicitly WANT weekend shifts so the scheduler prefers them there.
    if index % 3 == 0:
        grid["שישי"][SHIFTS_HE[index % 3]] = PREF_WANT
    if index % 3 == 1:
        grid["שבת"][SHIFTS_HE[(index + 1) % 3]] = PREF_WANT

    # Sparse Shabbat-night refusals only (not a blanket weekend block)
    if index % 7 == 0:
        if grid["שבת"]["לילה"] != PREF_WANT:
            grid["שבת"]["לילה"] = PREF_NO

    return grid


def seed_sample_data(*, reset: bool = False) -> dict:
    """Load sample employees + full-week preferences. Safe to re-run if reset=False."""
    if reset and db.using_mock():
        db.clear_mock_store()

    created = []
    week = next_week_id()

    for i, raw in enumerate(SAMPLE_EMPLOYEES):
        existing = employees.find_by_phone(raw["phone"])
        if existing:
            if raw.get("role") and existing.get("role") != raw.get("role"):
                employees.update_employee(existing["id"], {"role": raw["role"]})
                emp = employees.get_employee(existing["id"]) or existing
            else:
                emp = existing
        else:
            emp = employees.create_employee({**raw, "active": True})
            created.append(emp["id"])

        preferences.set_full_grid(emp["id"], week, _pattern_for(i), submitted=True)

    # Sanity: every preference grid covers all 7 days
    for emp in employees.list_employees(active_only=True):
        prefs = preferences.get_preferences(emp["id"], week).get("grid") or {}
        missing = [d for d in DAYS_HE if d not in prefs]
        if missing:
            logger.warning("Employee %s missing preference days: %s", emp["name"], missing)

    logger.info(
        "Seeded %d employees for week %s (%d new) – prefs cover %s",
        len(SAMPLE_EMPLOYEES),
        week,
        len(created),
        ", ".join(DAYS_HE),
    )
    return {
        "weekId": week,
        "employees": employees.list_employees(),
        "createdCount": len(created),
        "days": list(DAYS_HE),
    }
