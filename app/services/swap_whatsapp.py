"""WhatsApp helpers for shift-swap approval workflow."""

from __future__ import annotations

from typing import Any

from app.services import employees, swaps
from app.services.whatsapp import send_whatsapp, set_conversation
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

APPROVE_WORDS = {"מאשר", "מאשרת", "כן", "approve", "ok", "אישור"}
REJECT_WORDS = {"דוחה", "לא", "reject", "דחייה", "סירוב"}


def notify_proposed_nurse(swap: dict[str, Any]) -> dict[str, Any]:
    proposed = employees.get_employee(swap["proposed_nurse_id"])
    requester = employees.get_employee(swap["requester_nurse_id"])
    if not proposed:
        return {"ok": False, "error": "proposed missing"}

    o = swap["original_shift"]
    r = swap["requested_shift"]
    body = (
        f"שלום {proposed['name']} 🔄\n\n"
        f"{requester['name'] if requester else 'אחות'} מבקש/ת להחליף משמרות:\n"
        f"• הם/ן: יום {o['day']} – {o['shift']}\n"
        f"• את/ה: יום {r['day']} – {r['shift']}\n"
        f"שבוע: {swap['week']}\n\n"
        f"לאישור: השיבו «מאשר»\n"
        f"לדחייה: השיבו «דוחה»\n"
        f"(מזהה: {swap['id'][:8]})"
    )
    set_conversation(
        proposed["phone"],
        "awaiting_swap_proposed",
        {"swapId": swap["id"], "weekId": swap["week"]},
    )
    return send_whatsapp(proposed["phone"], body)


def notify_chief_nurse(swap: dict[str, Any]) -> dict[str, Any]:
    chief = swaps.get_chief_nurse()
    if not chief:
        logger.warning("No chief nurse configured – swap %s waiting without WhatsApp", swap["id"])
        return {"ok": False, "error": "no chief"}

    enriched = swaps.enrich_swap(swap)
    o = swap["original_shift"]
    r = swap["requested_shift"]
    body = (
        f"שלום {chief['name']} (אחראית) 📋\n\n"
        f"בקשת החלפה ממתינה לאישורך:\n"
        f"• {enriched['requester_name']}: יום {o['day']} {o['shift']}\n"
        f"• {enriched['proposed_name']}: יום {r['day']} {r['shift']}\n"
        f"שבוע: {swap['week']}\n\n"
        f"לאישור: «מאשר»\n"
        f"לדחייה: «דוחה»\n"
        f"(מזהה: {swap['id'][:8]})"
    )
    set_conversation(
        chief["phone"],
        "awaiting_swap_chief",
        {"swapId": swap["id"], "weekId": swap["week"]},
    )
    return send_whatsapp(chief["phone"], body)


def notify_swap_outcome(swap: dict[str, Any], approved: bool) -> list[dict[str, Any]]:
    results = []
    enriched = swaps.enrich_swap(swap)
    o = swap["original_shift"]
    r = swap["requested_shift"]
    if approved:
        msg_req = (
            f"ההחלפה אושרה ✅\n"
            f"עכשיו את/ה ביום {r['day']} – {r['shift']}\n"
            f"(במקום יום {o['day']} {o['shift']})"
        )
        msg_prop = (
            f"ההחלפה אושרה ✅\n"
            f"עכשיו את/ה ביום {o['day']} – {o['shift']}\n"
            f"(במקום יום {r['day']} {r['shift']})"
        )
    else:
        msg_req = msg_prop = (
            f"החלפה נדחתה ❌\n{swaps.format_swap_summary(swap)}"
        )

    for nid, body in (
        (swap["requester_nurse_id"], msg_req),
        (swap["proposed_nurse_id"], msg_prop),
    ):
        emp = employees.get_employee(nid)
        if emp:
            set_conversation(emp["phone"], "idle", {"weekId": swap.get("week")})
            results.append(send_whatsapp(emp["phone"], body))

    logger.info(
        "Swap outcome notified approved=%s swap=%s (%s↔%s)",
        approved,
        swap["id"],
        enriched["requester_name"],
        enriched["proposed_name"],
    )
    return results


def initiate_swap_from_whatsapp(requester: dict[str, Any], text: str, week: str) -> str:
    """Create swap from Hebrew WhatsApp text and notify proposed nurse."""
    parsed = swaps.parse_swap_message(text)
    if not parsed:
        return (
            "לא הצלחתי לפרסר בקשת החלפה.\n"
            "דוגמה:\n"
            "אני רוצה להחליף בוקר בתאריך ראשון עם יעל לוי\n"
            "או עם משמרת יעד:\n"
            "אני רוצה להחליף בוקר בתאריך ראשון עם יעל לוי בשני ערב"
        )

    proposed = swaps.find_nurse_by_name(parsed["name"])
    if not proposed:
        return f"לא מצאתי עובד/ת בשם «{parsed['name']}»."

    original = {"day": parsed["day"], "shift": parsed["shift"]}
    requested = None
    if "their_day" in parsed:
        requested = {"day": parsed["their_day"], "shift": parsed["their_shift"]}

    try:
        swap = swaps.create_swap_request(
            requester["id"],
            proposed["id"],
            original,
            requested_shift=requested,
            week=week,
        )
    except ValueError as exc:
        return f"לא ניתן ליצור החלפה: {exc}"

    notify_proposed_nurse(swap)
    o = swap["original_shift"]
    r = swap["requested_shift"]
    return (
        f"בקשת החלפה נשלחה ל-{proposed['name']} ✅\n"
        f"את/ה: יום {o['day']} {o['shift']}\n"
        f"הם/ן: יום {r['day']} {r['shift']}\n"
        f"ממתינים לאישורם/ן, ואז לאישור האחראית."
    )


def handle_swap_reply(emp: dict[str, Any], text: str, state: str, ctx: dict) -> str | None:
    """Handle מאשר/דוחה while awaiting swap approval. Returns reply or None."""
    lower = text.strip().lower()
    first = lower.split()[0] if lower else ""
    swap_id = (ctx or {}).get("swapId")
    if not swap_id:
        return None

    from app.services import swaps as swaps_svc

    swap = swaps_svc.get_swap(swap_id)
    if not swap:
        return "בקשת ההחלפה כבר לא קיימת."

    if first in REJECT_WORDS or lower in REJECT_WORDS:
        try:
            swaps_svc.reject_swap(swap_id, emp["id"], reason="נדחה ב-WhatsApp")
        except (ValueError, LookupError) as exc:
            return str(exc)
        notify_swap_outcome(swaps_svc.get_swap(swap_id) or swap, approved=False)
        set_conversation(emp["phone"], "idle", {"weekId": swap.get("week")})
        return "ההחלפה נדחתה. תודה."

    if first not in APPROVE_WORDS and lower not in APPROVE_WORDS:
        return None  # not a swap reply

    try:
        if state == "awaiting_swap_proposed":
            updated = swaps_svc.approve_by_proposed(swap_id, emp["id"])
            notify_chief_nurse(updated)
            set_conversation(emp["phone"], "idle", {"weekId": swap.get("week")})
            return (
                "אישרת את ההחלפה. נשלחה בקשה לאחות האחראית לאישור סופי."
            )
        if state == "awaiting_swap_chief":
            updated = swaps_svc.approve_by_chief(swap_id, emp["id"])
            notify_swap_outcome(updated, approved=True)
            set_conversation(emp["phone"], "idle", {"weekId": swap.get("week")})
            return "ההחלפה אושרה והסידור עודכן. שני הצדדים קיבלו הודעה."
    except (ValueError, LookupError) as exc:
        return f"לא ניתן לאשר: {exc}"

    return None


def looks_like_swap_request(text: str) -> bool:
    t = text.strip()
    return bool(
        swaps.parse_swap_message(t)
        or ("להחליף" in t and "עם" in t)
        or ("החלפה" in t and "עם" in t)
    )
