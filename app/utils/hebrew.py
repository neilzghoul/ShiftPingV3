"""Hebrew constants, day/shift names, and gender-aware messaging helpers."""

from __future__ import annotations

from typing import Literal

Gender = Literal["male", "female"]

# Israeli work week starts on Sunday
DAYS_HE = [
    "ראשון",
    "שני",
    "שלישי",
    "רביעי",
    "חמישי",
    "שישי",
    "שבת",
]

DAY_ALIASES: dict[str, str] = {
    "ראשון": "ראשון",
    "יום ראשון": "ראשון",
    "א": "ראשון",
    "א'": "ראשון",
    "sunday": "ראשון",
    "sun": "ראשון",
    "שני": "שני",
    "יום שני": "שני",
    "ב": "שני",
    "ב'": "שני",
    "monday": "שני",
    "mon": "שני",
    "שלישי": "שלישי",
    "יום שלישי": "שלישי",
    "ג": "שלישי",
    "ג'": "שלישי",
    "tuesday": "שלישי",
    "tue": "שלישי",
    "רביעי": "רביעי",
    "יום רביעי": "רביעי",
    "ד": "רביעי",
    "ד'": "רביעי",
    "wednesday": "רביעי",
    "wed": "רביעי",
    "חמישי": "חמישי",
    "יום חמישי": "חמישי",
    "ה": "חמישי",
    "ה'": "חמישי",
    "thursday": "חמישי",
    "thu": "חמישי",
    "שישי": "שישי",
    "יום שישי": "שישי",
    "ו": "שישי",
    "ו'": "שישי",
    "friday": "שישי",
    "fri": "שישי",
    "שבת": "שבת",
    "יום שבת": "שבת",
    "ש": "שבת",
    "saturday": "שבת",
    "sat": "שבת",
}

SHIFTS_HE = ["בוקר", "ערב", "לילה"]

SHIFT_ALIASES: dict[str, str] = {
    "בוקר": "בוקר",
    "בקר": "בוקר",
    "morning": "בוקר",
    "am": "בוקר",
    "מ": "בוקר",
    "ערב": "ערב",
    "evening": "ערב",
    "pm": "ערב",
    "ע": "ערב",
    "לילה": "לילה",
    "ליל": "לילה",
    "night": "לילה",
    "ל": "לילה",
}

# Preference codes: WANT / CAN / NO
PREF_WANT = "WANT"
PREF_CAN = "CAN"
PREF_NO = "NO"

PREF_ALIASES: dict[str, str] = {
    "want": PREF_WANT,
    "רוצה": PREF_WANT,
    "ר": PREF_WANT,
    "1": PREF_WANT,
    "can": PREF_CAN,
    "יכול": PREF_CAN,
    "יכולה": PREF_CAN,
    "י": PREF_CAN,
    "2": PREF_CAN,
    "no": PREF_NO,
    "לא": PREF_NO,
    "ל": PREF_NO,
    "3": PREF_NO,
}

PREF_LABELS_HE = {
    PREF_WANT: "רוצה",
    PREF_CAN: "יכול/ה",
    PREF_NO: "לא",
}

# Preference priority for scheduling (higher = better)
PREF_PRIORITY = {
    PREF_WANT: 3,
    PREF_CAN: 2,
    PREF_NO: 0,
    None: 1,  # no response treated as soft available
}


def can_verb(gender: Gender | str | None) -> str:
    """Return gender-aware Hebrew for 'can'."""
    if gender == "female":
        return "יכולה"
    return "יכול"


def want_verb(gender: Gender | str | None) -> str:  # noqa: ARG001
    """Hebrew 'want' is gender-neutral in this context."""
    return "רוצה"


def welcome_greeting(name: str, gender: Gender | str | None) -> str:
    if gender == "female":
        return f"שלום {name}! ברוכה הבאה ל-ShiftPing 👋"
    return f"שלום {name}! ברוך הבא ל-ShiftPing 👋"


def parse_day(token: str) -> str | None:
    key = token.strip().lower()
    return DAY_ALIASES.get(key) or DAY_ALIASES.get(token.strip())


def parse_shift(token: str) -> str | None:
    key = token.strip().lower()
    return SHIFT_ALIASES.get(key) or SHIFT_ALIASES.get(token.strip())


def parse_pref(token: str) -> str | None:
    key = token.strip().lower()
    return PREF_ALIASES.get(key) or PREF_ALIASES.get(token.strip())


def day_header(day: str) -> str:
    return f"יום {day}"
