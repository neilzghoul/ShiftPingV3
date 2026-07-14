"""Twilio WhatsApp messaging and inbound webhook handling."""

from __future__ import annotations

from typing import Any

from app.config import config
from app.services import db, employees, preferences, scheduler
from app.services.preferences import parse_preference_message
from app.services.preferences import preference_summary_he as pref_summary
from app.utils.dates import format_date_he, next_week_id, week_dates, week_id as current_week_id
from app.utils.hebrew import DAYS_HE, SHIFTS_HE, can_verb, welcome_greeting
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def _twilio_client():
    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        return None
    from twilio.rest import Client

    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def normalize_whatsapp_from(raw: str) -> str:
    """whatsapp:+972... → +972..."""
    phone = raw.strip()
    if phone.lower().startswith("whatsapp:"):
        phone = phone.split(":", 1)[1]
    return employees.normalize_phone(phone)


def send_whatsapp(to_phone: str, body: str) -> dict[str, Any]:
    """Send a WhatsApp message via Twilio. Returns status dict."""
    to = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
    client = _twilio_client()

    if client is None:
        logger.warning("Twilio not configured – mocking send to %s: %s", to, body[:80])
        return {"ok": True, "mocked": True, "to": to, "body": body}

    try:
        msg = client.messages.create(
            from_=config.TWILIO_WHATSAPP_FROM,
            to=to,
            body=body,
        )
        logger.info("WhatsApp sent sid=%s to=%s", msg.sid, to)
        return {"ok": True, "sid": msg.sid, "to": to}
    except Exception as exc:
        logger.exception("WhatsApp send failed to %s", to)
        return {"ok": False, "error": str(exc), "to": to}


def get_conversation(phone: str) -> dict[str, Any]:
    doc = db.get_doc("conversations", phone)
    if doc:
        return doc
    return {"id": phone, "phone": phone, "state": "idle", "context": {}}


def set_conversation(phone: str, state: str, context: dict | None = None) -> dict[str, Any]:
    return db.upsert_doc(
        "conversations",
        phone,
        {"phone": phone, "state": state, "context": context or {}},
    )


def preference_instructions(emp: dict[str, Any], week: str) -> str:
    gender = emp.get("gender")
    can = can_verb(gender)
    dates = week_dates(week)
    date_range = f"{format_date_he(dates[0])}–{format_date_he(dates[-1])}"
    return (
        f"{welcome_greeting(emp['name'], gender)}\n\n"
        f"נא לשלוח העדפות למשמרות לשבוע {week} ({date_range}).\n\n"
        f"פורמט (שורה לכל משמרת):\n"
        f"  יום משמרת העדפה\n\n"
        f"ימים: {', '.join(DAYS_HE)}\n"
        f"משמרות: {', '.join(SHIFTS_HE)}\n"
        f"העדפות: רוצה / {can} / לא\n\n"
        f"דוגמאות:\n"
        f"  ראשון בוקר רוצה\n"
        f"  שני ערב {can}\n"
        f"  שלישי לילה לא\n\n"
        f"שלחו 'סיים' כשתסיימו, או 'סטטוס' לראות מה נרשם.\n"
        f"שלחו 'עזרה' להודעה זו שוב."
    )


def request_preferences(week: str | None = None) -> dict[str, Any]:
    """Broadcast preference-collection message to all active nurses."""
    week = week or next_week_id()
    results = []
    for emp in employees.list_employees(active_only=True):
        body = preference_instructions(emp, week)
        set_conversation(emp["phone"], "collecting_prefs", {"weekId": week})
        results.append(send_whatsapp(emp["phone"], body))
    return {"weekId": week, "results": results}


def format_personal_schedule(emp: dict[str, Any], schedule: dict[str, Any]) -> str:
    shifts = scheduler.personal_shifts(schedule, emp["id"])
    week = schedule.get("weekId", "")
    if not shifts:
        return f"שלום {emp['name']}, אין לך משמרות בסידור לשבוע {week}."
    lines = [f"שלום {emp['name']} 📋", f"הסידור שלך לשבוע {week}:", ""]
    for day, shift in shifts:
        lines.append(f"• יום {day} – {shift}")
    lines.append("")
    lines.append("בהצלחה!")
    return "\n".join(lines)


def publish_schedule(week: str | None = None) -> dict[str, Any]:
    """Mark schedule published and WhatsApp each nurse their shifts."""
    week = week or current_week_id()
    schedule = scheduler.get_schedule(week)
    if not schedule:
        raise LookupError(f"לא נמצא סידור לשבוע {week}")

    scheduler.save_schedule(
        week,
        schedule["grid"],
        status="published",
        published=True,
        notes=schedule.get("notes", ""),
        generationLog=schedule.get("generationLog", []),
    )

    results = []
    for emp in employees.list_employees(active_only=True):
        body = format_personal_schedule(emp, schedule)
        results.append(send_whatsapp(emp["phone"], body))

    # Also send a compact full-board summary to admins? skip – keep simple
    return {"weekId": week, "results": results, "published": True}


def handle_inbound(from_raw: str, body: str) -> str:
    """Process inbound WhatsApp message; return reply text."""
    phone = normalize_whatsapp_from(from_raw)
    text = (body or "").strip()
    emp = employees.find_by_phone(phone)

    if not emp:
        logger.info("Unknown sender %s", phone)
        return (
            "שלום! המספר שלך לא רשום במערכת ShiftPing. "
            "פנה/י למנהל/ת למשמרות לרישום."
        )

    conv = get_conversation(phone)
    state = conv.get("state", "idle")
    ctx = conv.get("context") or {}
    week = ctx.get("weekId") or next_week_id()
    lower = text.lower()

    # Swap approval replies (proposed / chief)
    if state in ("awaiting_swap_proposed", "awaiting_swap_chief"):
        from app.services import swap_whatsapp

        reply = swap_whatsapp.handle_swap_reply(emp, text, state, ctx)
        if reply is not None:
            return reply

    # Global commands
    if lower in ("עזרה", "help", "?", "הוראות"):
        set_conversation(phone, "collecting_prefs", {"weekId": week})
        return preference_instructions(emp, week) + (
            "\n\nלהחלפת משמרת:\n"
            "אני רוצה להחליף בוקר בתאריך ראשון עם יעל לוי"
        )

    if lower in ("סטטוס", "status", "מצב"):
        prefs = preferences.get_preferences(emp["id"], week)
        summary = pref_summary(prefs.get("grid") or {})
        submitted = "כן" if prefs.get("submitted") else "לא"
        return f"ההעדפות שלך לשבוע {week} (הוגש: {submitted}):\n{summary}"

    if lower in ("סיים", "סיום", "done", "finish", "תודה"):
        preferences.mark_submitted(emp["id"], week)
        set_conversation(phone, "idle", {"weekId": week})
        prefs = preferences.get_preferences(emp["id"], week)
        summary = pref_summary(prefs.get("grid") or {})
        return f"תודה {emp['name']}! ההעדפות נשמרו.\n{summary}"

    if lower in ("סידור", "schedule", "המשמרות שלי"):
        sched = scheduler.get_schedule(week)
        if not sched or not sched.get("published"):
            sched = scheduler.get_schedule(current_week_id())
        if not sched:
            # fall back to any saved week schedule
            from app.utils.dates import next_week_id as _nw

            sched = scheduler.get_schedule(_nw()) or sched
        if not sched:
            return "עדיין אין סידור מפורסם."
        return format_personal_schedule(emp, sched)

    # Swap request
    from app.services import swap_whatsapp

    if swap_whatsapp.looks_like_swap_request(text):
        # Prefer published/current schedule week
        sched = scheduler.get_schedule(week) or scheduler.get_schedule(current_week_id())
        if sched:
            week = sched.get("weekId") or week
        return swap_whatsapp.initiate_swap_from_whatsapp(emp, text, week)

    # Preference lines
    parsed = parse_preference_message(text)
    if parsed:
        set_conversation(phone, "collecting_prefs", {"weekId": week})
        for day, shift, pref in parsed:
            preferences.set_preference(emp["id"], week, day, shift, pref)
        prefs = preferences.get_preferences(emp["id"], week)
        summary = pref_summary(prefs.get("grid") or {})
        count = len(parsed)
        return (
            f"נשמרו {count} העדפות.\n{summary}\n\n"
            f"המשיכו לשלוח, או כתבו 'סיים' לסיום."
        )

    if state == "collecting_prefs":
        return (
            "לא הצלחתי לפרסר את ההודעה.\n"
            "נסו: ראשון בוקר רוצה\n"
            "או שלחו 'עזרה'."
        )

    # Default: start collection
    set_conversation(phone, "collecting_prefs", {"weekId": week})
    return preference_instructions(emp, week)


def validate_twilio_request(url: str, params: dict, signature: str) -> bool:
    if not config.TWILIO_WEBHOOK_VALIDATE:
        return True
    if not config.TWILIO_AUTH_TOKEN:
        return False
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)
