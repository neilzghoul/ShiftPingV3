"""Shift swap requests with WhatsApp multi-party approval."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import config
from app.services import db, employees, preferences, scheduler
from app.utils.dates import next_week_id
from app.utils.hebrew import DAYS_HE, SHIFTS_HE, parse_day, parse_shift
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

COLLECTION = "shift_swaps"
AUDIT_COLLECTION = "swap_audit"

STATUS_PENDING_PROPOSED = "pending_requester_approval"  # waiting on proposed nurse (schema name)
STATUS_PENDING_CHIEF = "pending_chief_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

PENDING_STATUSES = {STATUS_PENDING_PROPOSED, STATUS_PENDING_CHIEF}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_chief(emp: dict[str, Any] | None) -> bool:
    if not emp:
        return False
    if emp.get("role") == "chief":
        return True
    chief_phone = (config.CHIEF_NURSE_PHONE or "").strip()
    if chief_phone and employees.normalize_phone(emp.get("phone", "")) == employees.normalize_phone(
        chief_phone
    ):
        return True
    return False


def get_chief_nurse() -> dict[str, Any] | None:
    for emp in employees.list_employees(active_only=True):
        if is_chief(emp):
            return emp
    # Fallback: env phone lookup
    if config.CHIEF_NURSE_PHONE:
        return employees.find_by_phone(config.CHIEF_NURSE_PHONE)
    return None


def find_nurse_by_name(name: str) -> dict[str, Any] | None:
    needle = re.sub(r"\s+", " ", name.strip())
    if not needle:
        return None
    matches = []
    for emp in employees.list_employees(active_only=True):
        full = emp.get("name", "")
        if full == needle or needle in full or full.startswith(needle):
            matches.append(emp)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Prefer exact match
        exact = [m for m in matches if m.get("name") == needle]
        return exact[0] if len(exact) == 1 else matches[0]
    return None


def parse_swap_message(text: str) -> dict[str, str] | None:
    """Parse: אני רוצה להחליף [shift] בתאריך [day] עם [name] [optional: ביום X משמרת Y]."""
    cleaned = text.strip()
    # Primary pattern
    m = re.search(
        r"להחליף\s+(\S+)\s+בתאריך\s+(\S+)\s+עם\s+(.+?)(?:\s+ב(?:יום\s*)?(\S+)\s+(\S+)\s*)?$",
        cleaned,
        re.UNICODE,
    )
    if not m:
        # Alternate: החלפה / מחליף
        m = re.search(
            r"(?:החלפה|מחליף|החלף)\s+(\S+)\s+(?:ב)?(?:תאריך\s+)?(\S+)\s+עם\s+(.+?)(?:\s+ב(?:יום\s*)?(\S+)\s+(\S+)\s*)?$",
            cleaned,
            re.UNICODE,
        )
    if not m:
        return None

    shift = parse_shift(m.group(1))
    day = parse_day(m.group(2))
    name = m.group(3).strip()
    # Strip trailing approval junk
    name = re.sub(r"\s+", " ", name)
    if not shift or not day or not name:
        return None

    result: dict[str, str] = {"day": day, "shift": shift, "name": name}
    if m.group(4) and m.group(5):
        day2 = parse_day(m.group(4))
        shift2 = parse_shift(m.group(5))
        if day2 and shift2:
            result["their_day"] = day2
            result["their_shift"] = shift2
    return result


def _shift_dict(day: str, shift: str) -> dict[str, str]:
    return {"day": day, "shift": shift}


def _grid_has(grid: dict, day: str, shift: str, nurse_id: str) -> bool:
    return nurse_id in (grid.get(day) or {}).get(shift, [])


def _remove_from_cell(grid: dict, day: str, shift: str, nurse_id: str) -> None:
    cell = list((grid.get(day) or {}).get(shift, []))
    grid.setdefault(day, {})[shift] = [x for x in cell if x != nurse_id]


def _add_to_cell(grid: dict, day: str, shift: str, nurse_id: str) -> None:
    cell = list((grid.get(day) or {}).get(shift, []))
    if nurse_id not in cell:
        cell.append(nurse_id)
    grid.setdefault(day, {})[shift] = cell


def simulate_swap_grid(
    grid: dict[str, dict[str, list[str]]],
    requester_id: str,
    proposed_id: str,
    original: dict[str, str],
    requested: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    """Return a copy of grid after swapping the two assignments."""
    new_grid = copy.deepcopy(grid)
    od, os_ = original["day"], original["shift"]
    rd, rs = requested["day"], requested["shift"]

    _remove_from_cell(new_grid, od, os_, requester_id)
    _remove_from_cell(new_grid, rd, rs, proposed_id)
    _add_to_cell(new_grid, od, os_, proposed_id)
    _add_to_cell(new_grid, rd, rs, requester_id)
    return new_grid


def validate_swap_constraints(
    week: str,
    requester_id: str,
    proposed_id: str,
    original: dict[str, str],
    requested: dict[str, str],
    *,
    require_submitted_prefs: bool = True,
) -> list[str]:
    """Return Hebrew error messages; empty list means OK."""
    errors: list[str] = []
    if requester_id == proposed_id:
        errors.append("לא ניתן להחליף עם עצמך")
        return errors

    requester = employees.get_employee(requester_id)
    proposed = employees.get_employee(proposed_id)
    if not requester or not proposed:
        errors.append("עובד לא נמצא")
        return errors

    if is_chief(requester):
        errors.append("אחות אחראית לא יכולה לבקש החלפה")
    if is_chief(proposed):
        errors.append("לא ניתן להחליף עם האחות האחראית")

    if require_submitted_prefs:
        for emp, label in ((requester, "המבקש/ת"), (proposed, "המוצע/ת")):
            prefs = preferences.get_preferences(emp["id"], week)
            if not prefs.get("submitted"):
                errors.append(f"{label} ({emp['name']}) טרם הגיש/ה העדפות לשבוע {week}")

    sched = scheduler.get_schedule(week)
    if not sched:
        errors.append(f"אין סידור לשבוע {week}")
        return errors

    grid = sched.get("grid") or {}
    od, os_ = original["day"], original["shift"]
    rd, rs = requested["day"], requested["shift"]

    if od not in DAYS_HE or os_ not in SHIFTS_HE:
        errors.append("משמרת מקור לא חוקית")
    if rd not in DAYS_HE or rs not in SHIFTS_HE:
        errors.append("משמרת יעד לא חוקית")

    if not _grid_has(grid, od, os_, requester_id):
        errors.append(f"{requester['name']} אינ/ה משובצ/ת ביום {od} {os_}")
    if not _grid_has(grid, rd, rs, proposed_id):
        errors.append(f"{proposed['name']} אינ/ה משובצ/ת ביום {rd} {rs}")

    if errors:
        return errors

    # Sequence constraints after swap
    new_grid = simulate_swap_grid(grid, requester_id, proposed_id, original, requested)
    warnings = scheduler.validate_schedule(new_grid)
    # Filter to only those involving the two nurses
    names = {requester["name"], proposed["name"], requester_id, proposed_id}
    relevant = [w for w in warnings if any(n in w for n in names)]
    if relevant:
        errors.extend([f"אילוץ רצף: {w}" for w in relevant])
    elif warnings:
        # Still block if any hard violations introduced (safer)
        before = set(scheduler.validate_schedule(grid))
        introduced = [w for w in warnings if w not in before]
        if introduced:
            errors.extend([f"אילוץ רצף: {w}" for w in introduced])

    return errors


def append_swap_audit(swap_id: str, action: str, actor_id: str | None, detail: str = "") -> dict:
    payload = {
        "swap_id": swap_id,
        "action": action,
        "actor_id": actor_id,
        "detail": detail,
        "at": _utc_now(),
    }
    doc = db.create_doc(AUDIT_COLLECTION, payload)
    logger.info("Swap audit swap=%s action=%s actor=%s %s", swap_id, action, actor_id, detail)
    return doc


def list_swap_audit(swap_id: str | None = None) -> list[dict[str, Any]]:
    filters = [("swap_id", "==", swap_id)] if swap_id else None
    docs = db.list_docs(AUDIT_COLLECTION, filters=filters)
    return sorted(docs, key=lambda d: d.get("at") or "", reverse=True)


def list_swaps(
    *,
    week: str | None = None,
    status: str | None = None,
    pending_only: bool = False,
) -> list[dict[str, Any]]:
    filters: list[tuple[str, str, Any]] = []
    if week:
        filters.append(("week", "==", week))
    if status:
        filters.append(("status", "==", status))
    docs = db.list_docs(COLLECTION, filters=filters or None)
    if pending_only:
        docs = [d for d in docs if d.get("status") in PENDING_STATUSES]
    return sorted(docs, key=lambda d: d.get("created_at") or d.get("createdAt") or "", reverse=True)


def get_swap(swap_id: str) -> dict[str, Any] | None:
    return db.get_doc(COLLECTION, swap_id)


def enrich_swap(swap: dict[str, Any]) -> dict[str, Any]:
    out = dict(swap)
    req = employees.get_employee(swap.get("requester_nurse_id", ""))
    prop = employees.get_employee(swap.get("proposed_nurse_id", ""))
    out["requester_name"] = req["name"] if req else swap.get("requester_nurse_id")
    out["proposed_name"] = prop["name"] if prop else swap.get("proposed_nurse_id")
    out["audit"] = list_swap_audit(swap.get("id"))
    return out


def _pick_proposed_shift(
    grid: dict,
    proposed_id: str,
    *,
    exclude: tuple[str, str] | None = None,
) -> dict[str, str] | None:
    assigns = scheduler.assignments_for_employee(grid, proposed_id)
    for day, shift in assigns:
        if exclude and (day, shift) == exclude:
            continue
        return _shift_dict(day, shift)
    return None


def create_swap_request(
    requester_id: str,
    proposed_id: str,
    original_shift: dict[str, str],
    requested_shift: dict[str, str] | None = None,
    week: str | None = None,
) -> dict[str, Any]:
    week = week or next_week_id()
    sched = scheduler.get_schedule(week)
    if not sched:
        # try published current naming
        raise ValueError(f"אין סידור לשבוע {week}")

    grid = sched.get("grid") or {}
    if requested_shift is None:
        requested_shift = _pick_proposed_shift(
            grid,
            proposed_id,
            exclude=(original_shift["day"], original_shift["shift"]),
        )
        if not requested_shift:
            raise ValueError("למוצע/ת אין משמרת להחלפה השבוע")

    errors = validate_swap_constraints(
        week, requester_id, proposed_id, original_shift, requested_shift
    )
    if errors:
        raise ValueError("; ".join(errors))

    # Block duplicate pending swaps for same pair/slot
    for existing in list_swaps(week=week, pending_only=True):
        if (
            existing.get("requester_nurse_id") == requester_id
            and existing.get("original_shift") == original_shift
        ):
            raise ValueError("כבר קיימת בקשת החלפה ממתינה למשמרת זו")

    swap_id = str(uuid.uuid4())
    payload = {
        "id": swap_id,
        "week": week,
        "requester_nurse_id": requester_id,
        "proposed_nurse_id": proposed_id,
        "original_shift": original_shift,
        "requested_shift": requested_shift,
        "status": STATUS_PENDING_PROPOSED,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "history": [
            {"at": _utc_now(), "action": "created", "by": requester_id},
        ],
    }
    doc = db.create_doc(COLLECTION, payload, doc_id=swap_id)
    append_swap_audit(swap_id, "created", requester_id, "בקשת החלפה נוצרה")
    logger.info(
        "Swap created %s week=%s %s↔%s",
        swap_id,
        week,
        requester_id,
        proposed_id,
    )
    return doc


def _update_status(swap: dict[str, Any], status: str, actor_id: str | None, note: str) -> dict:
    history = list(swap.get("history") or [])
    history.append({"at": _utc_now(), "action": status, "by": actor_id, "note": note})
    updated = db.update_doc(
        COLLECTION,
        swap["id"],
        {
            "status": status,
            "updated_at": _utc_now(),
            "history": history,
        },
    )
    assert updated is not None
    append_swap_audit(swap["id"], status, actor_id, note)
    return updated


def reject_swap(swap_id: str, actor_id: str | None, reason: str = "") -> dict[str, Any]:
    swap = get_swap(swap_id)
    if not swap:
        raise LookupError("בקשת החלפה לא נמצאה")
    if swap.get("status") not in PENDING_STATUSES:
        raise ValueError("הבקשה כבר סגורה")
    return _update_status(swap, STATUS_REJECTED, actor_id, reason or "נדחה")


def approve_by_proposed(swap_id: str, actor_id: str) -> dict[str, Any]:
    swap = get_swap(swap_id)
    if not swap:
        raise LookupError("בקשת החלפה לא נמצאה")
    if swap.get("status") != STATUS_PENDING_PROPOSED:
        raise ValueError("הבקשה אינה ממתינה לאישור המוצע/ת")
    if actor_id != swap.get("proposed_nurse_id"):
        raise ValueError("רק האחות המוצעת יכולה לאשר בשלב זה")

    errors = validate_swap_constraints(
        swap["week"],
        swap["requester_nurse_id"],
        swap["proposed_nurse_id"],
        swap["original_shift"],
        swap["requested_shift"],
    )
    if errors:
        raise ValueError("; ".join(errors))

    return _update_status(swap, STATUS_PENDING_CHIEF, actor_id, "אושר על ידי המוצע/ת")


def apply_swap_to_schedule(swap: dict[str, Any]) -> dict[str, Any]:
    week = swap["week"]
    sched = scheduler.get_schedule(week)
    if not sched:
        raise LookupError(f"אין סידור לשבוע {week}")
    grid = simulate_swap_grid(
        sched.get("grid") or {},
        swap["requester_nurse_id"],
        swap["proposed_nurse_id"],
        swap["original_shift"],
        swap["requested_shift"],
    )
    violations = scheduler.validate_schedule(grid)
    if violations:
        # Re-check only newly introduced
        before = set(scheduler.validate_schedule(sched.get("grid") or {}))
        introduced = [v for v in violations if v not in before]
        if introduced:
            raise ValueError("ההחלפה מפרה אילוצי רצף: " + "; ".join(introduced))

    saved = scheduler.save_schedule(
        week,
        grid,
        status=sched.get("status", "draft"),
        published=sched.get("published", False),
        notes=sched.get("notes", ""),
        generationLog=list(sched.get("generationLog") or [])
        + [f"החלפה {swap['id']}: עודכן סידור"],
    )
    logger.info("Schedule updated after swap %s week=%s", swap["id"], week)
    return saved


def approve_by_chief(swap_id: str, actor_id: str | None = None, *, force_admin: bool = False) -> dict[str, Any]:
    swap = get_swap(swap_id)
    if not swap:
        raise LookupError("בקשת החלפה לא נמצאה")
    if swap.get("status") != STATUS_PENDING_CHIEF:
        raise ValueError("הבקשה אינה ממתינה לאישור האחראית")

    if not force_admin:
        actor = employees.get_employee(actor_id) if actor_id else None
        if not is_chief(actor):
            raise ValueError("רק האחות האחראית יכולה לאשר")

    errors = validate_swap_constraints(
        swap["week"],
        swap["requester_nurse_id"],
        swap["proposed_nurse_id"],
        swap["original_shift"],
        swap["requested_shift"],
    )
    if errors:
        raise ValueError("; ".join(errors))

    apply_swap_to_schedule(swap)
    return _update_status(swap, STATUS_APPROVED, actor_id, "אושר סופית – הסידור עודכן")


def admin_approve(swap_id: str, admin_note: str = "אישור ידני מממשק ניהול") -> dict[str, Any]:
    """Admin backup: advance proposed→chief→approved as needed."""
    swap = get_swap(swap_id)
    if not swap:
        raise LookupError("בקשת החלפה לא נמצאה")

    if swap.get("status") == STATUS_PENDING_PROPOSED:
        swap = _update_status(swap, STATUS_PENDING_CHIEF, None, "דילוג אישור מוצע (מנהל)")
    if swap.get("status") == STATUS_PENDING_CHIEF:
        return approve_by_chief(swap["id"], actor_id=None, force_admin=True)

    raise ValueError("הבקשה אינה במצב שניתן לאשר")


def format_swap_summary(swap: dict[str, Any]) -> str:
    enriched = enrich_swap(swap)
    o = swap.get("original_shift") or {}
    r = swap.get("requested_shift") or {}
    return (
        f"החלפה {swap.get('id', '')[:8]}…\n"
        f"שבוע: {swap.get('week')}\n"
        f"{enriched['requester_name']}: יום {o.get('day')} {o.get('shift')}\n"
        f"↔ {enriched['proposed_name']}: יום {r.get('day')} {r.get('shift')}\n"
        f"סטטוס: {swap.get('status')}"
    )
