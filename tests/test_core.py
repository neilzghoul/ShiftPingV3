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
from app.utils.hebrew import DAYS_HE, SHIFTS_HE, parse_day, parse_pref, parse_shift


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


def test_valid_transitions_allowed():
    """Morning→evening and evening→night on same/next day are legal."""
    grid = scheduler.empty_schedule_grid()
    eid = "emp1"
    grid["ראשון"]["בוקר"] = [eid]
    assert scheduler.can_assign(eid, "ראשון", "ערב", grid) is True
    grid["ראשון"]["ערב"] = [eid]
    assert scheduler.can_assign(eid, "ראשון", "לילה", grid) is True

    grid2 = scheduler.empty_schedule_grid()
    grid2["ראשון"]["בוקר"] = [eid]
    assert scheduler.can_assign(eid, "שני", "ערב", grid2) is True  # next day


def test_night_then_morning_illegal():
    grid = scheduler.empty_schedule_grid()
    eid = "emp1"
    grid["ראשון"]["לילה"] = [eid]
    assert scheduler.can_assign(eid, "שני", "בוקר", grid) is False
    assert scheduler.can_assign(eid, "שני", "ערב", grid) is False
    assert scheduler.can_assign(eid, "שני", "לילה", grid) is False
    # After a full rest day, may start a new unused type
    assert scheduler.can_assign(eid, "שלישי", "בוקר", grid) is True


def test_same_shift_type_twice_illegal():
    grid = scheduler.empty_schedule_grid()
    eid = "emp1"
    grid["ראשון"]["בוקר"] = [eid]
    # Must follow with evening before anything else; but even later morning blocked by type
    grid["ראשון"]["ערב"] = [eid]
    grid["ראשון"]["לילה"] = [eid]
    # rest Monday, try Tuesday morning — already used בוקר
    assert scheduler.can_assign(eid, "שלישי", "בוקר", grid) is False


def test_validate_flags_night_morning():
    grid = scheduler.empty_schedule_grid()
    grid["ראשון"]["לילה"] = ["e1"]
    grid["שני"]["בוקר"] = ["e1"]
    warnings = scheduler.validate_schedule(grid)
    assert any("לילה" in w and "שני" in w for w in warnings)


def test_generate_covers_full_week_including_weekend():
    """Schedule must include שישי and שבת, not only Sun–Thu."""
    db.clear_mock_store()
    seeded = sample_data.seed_sample_data(reset=True)
    week = seeded["weekId"]
    # Prefs include all 7 days for every nurse
    for emp in employees.list_employees(active_only=True):
        grid = preferences.get_preferences(emp["id"], week).get("grid") or {}
        assert set(grid.keys()) == set(DAYS_HE), emp["name"]
        assert "שישי" in grid and "שבת" in grid

    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    g = result["grid"]
    assert set(g.keys()) == set(DAYS_HE)
    for day in DAYS_HE:
        day_total = sum(len(g[day][s]) for s in SHIFTS_HE)
        assert day_total > 0, f"day {day} has no assignments"
    # Weekend specifically staffed
    fri = sum(len(g["שישי"][s]) for s in SHIFTS_HE)
    sat = sum(len(g["שבת"][s]) for s in SHIFTS_HE)
    assert fri >= 2, f"Friday underfilled: {g['שישי']}"
    assert sat >= 2, f"Saturday underfilled: {g['שבת']}"
    assert scheduler.validate_schedule(g) == []


def test_generate_respects_no_and_constraints():
    db.clear_mock_store()
    seeded = sample_data.seed_sample_data(reset=True)
    week = seeded["weekId"]
    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    grid = result["grid"]
    warnings = scheduler.validate_schedule(grid)

    prefs = {p["employeeId"]: p for p in preferences.list_preferences_for_week(week)}
    for day, shifts in grid.items():
        for shift, ids in shifts.items():
            for eid in ids:
                val = (prefs.get(eid, {}).get("grid") or {}).get(day, {}).get(shift)
                assert val != "NO", f"{eid} assigned to NO slot {day} {shift}"

    assert warnings == [], warnings
    assert result.get("constraintViolations", []) == []

    for emp in employees.list_employees(active_only=True):
        assigns = scheduler.assignments_for_employee(grid, emp["id"])
        types = [s for _, s in assigns]
        assert len(types) == len(set(types)), f"duplicate shift type for {emp['name']}: {assigns}"
        for i in range(1, len(assigns)):
            pd, ps = assigns[i - 1]
            cd, cs = assigns[i]
            if ps == "לילה":
                assert DAYS_HE.index(cd) >= DAYS_HE.index(pd) + 2, (
                    f"night→next-day for {emp['name']}: {assigns}"
                )


def test_generate_fairness_roughly_balanced():
    db.clear_mock_store()
    seeded = sample_data.seed_sample_data(reset=True)
    week = seeded["weekId"]
    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    counts = list(result["shiftCounts"].values())
    assert counts, "expected shift counts"
    assert max(counts) - min(counts) <= 2, f"unfair spread: {result['shiftCounts']}"


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


def test_priority_history_after_schedule():
    from app.services import priority as priority_svc

    db.clear_mock_store()
    seeded = sample_data.seed_sample_data(reset=True)
    week = seeded["weekId"]
    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    rows = priority_svc.record_priority_for_week(week, grid=result["grid"])
    assert len(rows) == len(employees.list_employees(active_only=True))
    for r in rows:
        assert r["preferences_satisfied"] in (0, 1, 2, 3)
        assert r["priority_score"] == priority_svc.SCORE_BY_SATISFIED[r["preferences_satisfied"]]
        assert r["week"] == week
        assert r["nurse_id"]


def test_zero_satisfied_gets_higher_priority_next_week():
    """Nurses with 0 WANT hits get score 100 and beat score-40 peers on WANT slots."""
    from app.services import priority as priority_svc
    from app.utils.hebrew import PREF_CAN, PREF_WANT

    db.clear_mock_store()
    low = employees.create_employee({
        "name": "עדיפות גבוהה",
        "gender": "female",
        "phone": "+972501222001",
    })
    high_sat = employees.create_employee({
        "name": "עדיפות נמוכה",
        "gender": "male",
        "phone": "+972501222002",
    })
    # Fill other slots so generation can staff
    extras = []
    for i in range(6):
        extras.append(employees.create_employee({
            "name": f"מילוי {i}",
            "gender": "female" if i % 2 == 0 else "male",
            "phone": f"+97250122201{i}",
        }))

    prior_week = "2026-W29"
    next_week = "2026-W30"

    # Prior week outcomes: low got 0 satisfied → 100; high_sat got 3 → 40
    db.upsert_doc("priority_history", f"{low['id']}_{prior_week}", {
        "nurse_id": low["id"],
        "week": prior_week,
        "preferences_satisfied": 0,
        "priority_score": 100,
        "nurse_name": low["name"],
    })
    db.upsert_doc("priority_history", f"{high_sat['id']}_{prior_week}", {
        "nurse_id": high_sat["id"],
        "week": prior_week,
        "preferences_satisfied": 3,
        "priority_score": 40,
        "nurse_name": high_sat["name"],
    })

    scores = priority_svc.get_priority_scores_for_scheduling(next_week)
    assert scores[low["id"]] == 100
    assert scores[high_sat["id"]] == 40

    # Both WANT Sunday morning; others CAN everything
    empty = preferences.empty_grid()
    for emp in [low, high_sat, *extras]:
        grid = {d: {s: PREF_CAN for s in ["בוקר", "ערב", "לילה"]} for d in empty}
        if emp["id"] in (low["id"], high_sat["id"]):
            grid["ראשון"]["בוקר"] = PREF_WANT
        preferences.set_full_grid(emp["id"], next_week, grid, submitted=True)

    result = scheduler.generate_schedule(next_week, nurses_per_shift=1, save=True)
    morning = result["grid"]["ראשון"]["בוקר"]
    assert low["id"] in morning, (
        f"expected high-priority nurse on Sunday morning WANT, got {morning}; "
        f"scores used={result.get('priorityScoresUsed')}"
    )
    assert high_sat["id"] not in morning


def test_swap_whatsapp_full_flow():
    """Request → proposed approve → chief approve → schedule updated."""
    from app.services import swap_whatsapp, swaps, whatsapp
    from app.utils.hebrew import DAYS_HE, SHIFTS_HE

    db.clear_mock_store()
    sample_data.seed_sample_data(reset=True)
    week = sample_data.seed_sample_data()["weekId"]
    # regenerate schedule after seed (seed doesn't generate)
    result = scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    grid = result["grid"]

    # Pick two non-chief nurses with distinct assignments
    chief = swaps.get_chief_nurse()
    assert chief is not None
    candidates = []
    for day in DAYS_HE:
        for shift in SHIFTS_HE:
            for eid in grid[day][shift]:
                if eid == chief["id"]:
                    continue
                candidates.append((eid, day, shift))
    assert len(candidates) >= 2

    # Find two different nurses on different slots where swap won't violate sequence
    requester_id = proposed_id = None
    original = requested = None
    for i, (eid1, d1, s1) in enumerate(candidates):
        for eid2, d2, s2 in candidates[i + 1 :]:
            if eid1 == eid2 or (d1, s1) == (d2, s2):
                continue
            errs = swaps.validate_swap_constraints(
                week, eid1, eid2, {"day": d1, "shift": s1}, {"day": d2, "shift": s2}
            )
            if not errs:
                requester_id, proposed_id = eid1, eid2
                original, requested = {"day": d1, "shift": s1}, {"day": d2, "shift": s2}
                break
        if requester_id:
            break

    assert requester_id and proposed_id, "could not find legal swap pair in sample schedule"

    requester = employees.get_employee(requester_id)
    proposed = employees.get_employee(proposed_id)

    # WhatsApp initiate
    msg = f"אני רוצה להחליף {original['shift']} בתאריך {original['day']} עם {proposed['name']} ב{requested['day']} {requested['shift']}"
    reply = whatsapp.handle_inbound(requester["phone"], msg)
    assert "נשלחה" in reply or "בקשת" in reply, reply

    pending = swaps.list_swaps(week=week, pending_only=True)
    assert len(pending) == 1
    swap = pending[0]
    assert swap["status"] == swaps.STATUS_PENDING_PROPOSED

    # Proposed approves
    whatsapp.set_conversation(proposed["phone"], "awaiting_swap_proposed", {"swapId": swap["id"], "weekId": week})
    reply2 = whatsapp.handle_inbound(proposed["phone"], "מאשר")
    assert "אחראית" in reply2 or "אישרת" in reply2, reply2
    swap = swaps.get_swap(swap["id"])
    assert swap["status"] == swaps.STATUS_PENDING_CHIEF

    # Chief approves
    whatsapp.set_conversation(chief["phone"], "awaiting_swap_chief", {"swapId": swap["id"], "weekId": week})
    reply3 = whatsapp.handle_inbound(chief["phone"], "מאשר")
    assert "אושרה" in reply3 or "עודכן" in reply3, reply3
    swap = swaps.get_swap(swap["id"])
    assert swap["status"] == swaps.STATUS_APPROVED

    new_grid = scheduler.get_schedule(week)["grid"]
    assert proposed_id in new_grid[original["day"]][original["shift"]]
    assert requester_id in new_grid[requested["day"]][requested["shift"]]
    assert requester_id not in new_grid[original["day"]][original["shift"]]
    assert proposed_id not in new_grid[requested["day"]][requested["shift"]]

    audit = swaps.list_swap_audit(swap["id"])
    assert any(a["action"] == "approved" for a in audit)
    assert any(a["action"] == "created" for a in audit)


def test_cannot_swap_with_chief_or_self():
    from app.services import swaps

    db.clear_mock_store()
    sample_data.seed_sample_data(reset=True)
    week = sample_data.seed_sample_data()["weekId"]
    scheduler.generate_schedule(week, nurses_per_shift=2, save=True)
    chief = swaps.get_chief_nurse()
    other = next(e for e in employees.list_employees(active_only=True) if e["id"] != chief["id"])
    assigns = scheduler.assignments_for_employee(scheduler.get_schedule(week)["grid"], other["id"])
    if not assigns:
        return  # skip if unlucky understaffing
    day, shift = assigns[0]
    errs = swaps.validate_swap_constraints(
        week, other["id"], chief["id"],
        {"day": day, "shift": shift},
        {"day": day, "shift": shift},
    )
    assert any("אחראית" in e for e in errs)
    errs2 = swaps.validate_swap_constraints(
        week, other["id"], other["id"],
        {"day": day, "shift": shift},
        {"day": day, "shift": shift},
    )
    assert any("עצמך" in e for e in errs2)


if __name__ == "__main__":
    test_hebrew_parsers()
    test_parse_preference_message()
    test_valid_transitions_allowed()
    test_night_then_morning_illegal()
    test_same_shift_type_twice_illegal()
    test_validate_flags_night_morning()
    test_generate_covers_full_week_including_weekend()
    test_generate_respects_no_and_constraints()
    test_generate_fairness_roughly_balanced()
    test_employee_crud()
    test_whatsapp_handler_unknown()
    test_whatsapp_pref_flow()
    test_priority_history_after_schedule()
    test_zero_satisfied_gets_higher_priority_next_week()
    test_swap_whatsapp_full_flow()
    test_cannot_swap_with_chief_or_self()
    print("All tests passed.")
