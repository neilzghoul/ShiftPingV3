"""Unit tests for preference parsing and schedule generation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("USE_MOCK_DB", "true")
os.environ.setdefault("ADMIN_TOKEN", "test-token")

from app.services import db, employees, preferences, sample_data, scheduler
from app.services.preferences import parse_preference_message
from app.utils.hebrew import parse_day, parse_pref, parse_shift


def setup_module():
    db.clear_mock_store()


def test_hebrew_parsers():
    assert parse_day("ראשון") == "ראשון"
    assert parse_day("יום שני") == "שני"
    assert parse_shift("בוקר") == "בוקר"
    assert parse_shift("night") == "לילה"
    assert parse_pref("רוצה") == "WANT"
    assert parse_pref("יכולה") == "CAN"
    assert parse_pref("לא") == "NO"


def test_parse_preference_message():
    text = "ראשון בוקר רוצה\nשני ערב לא\nשלישי לילה יכול"
    parsed = parse_preference_message(text)
    assert ("ראשון", "בוקר", "WANT") in parsed
    assert ("שני", "ערב", "NO") in parsed
    assert ("שלישי", "לילה", "CAN") in parsed


def test_generate_respects_no_and_no_double():
    db.clear_mock_store()
    seeded = sample_data.seed_sample_data(reset=True)
    week = seeded["weekId"]
    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    grid = result["grid"]
    warnings = scheduler.validate_schedule(grid)

    # Hard constraint: no PREF_NO assignments
    prefs = {p["employeeId"]: p for p in preferences.list_preferences_for_week(week)}
    for day, shifts in grid.items():
        for shift, ids in shifts.items():
            for eid in ids:
                val = (prefs.get(eid, {}).get("grid") or {}).get(day, {}).get(shift)
                assert val != "NO", f"{eid} assigned to NO slot {day} {shift}"

    # Soft warnings may exist from second-pass fills, but double shifts should be rare
    # Generation itself avoids double shifts – validate should be clean for doubles from generator
    double_warns = [w for w in warnings if "משובצ" in w]
    assert double_warns == [], double_warns


def test_employee_crud():
    db.clear_mock_store()
    emp = employees.create_employee({
        "name": "בדיקה כהן",
        "gender": "female",
        "phone": "0509998887",
    })
    assert emp["phone"].startswith("+972")
    updated = employees.update_employee(emp["id"], {"notes": "ok"})
    assert updated["notes"] == "ok"
    assert employees.delete_employee(emp["id"]) is True


def test_whatsapp_handler_unknown():
    from app.services import whatsapp

    reply = whatsapp.handle_inbound("whatsapp:+19999999999", "שלום")
    assert "לא רשום" in reply


def test_whatsapp_pref_flow():
    db.clear_mock_store()
    sample_data.seed_sample_data(reset=True)
    from app.services import whatsapp
    from app.utils.dates import next_week_id

    emp = employees.list_employees()[0]
    week = next_week_id()
    whatsapp.set_conversation(emp["phone"], "collecting_prefs", {"weekId": week})
    reply = whatsapp.handle_inbound(emp["phone"], "ראשון בוקר רוצה")
    assert "נשמרו" in reply
    prefs = preferences.get_preferences(emp["id"], week)
    assert prefs["grid"]["ראשון"]["בוקר"] == "WANT"


if __name__ == "__main__":
    test_hebrew_parsers()
    test_parse_preference_message()
    test_generate_respects_no_and_no_double()
    test_employee_crud()
    test_whatsapp_handler_unknown()
    test_whatsapp_pref_flow()
    print("All tests passed.")
