"""Employee (nurse) service."""

from __future__ import annotations

import re
from typing import Any

from app.services import db
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", phone.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("0") and not cleaned.startswith("00"):
        # Assume Israel local → E.164
        cleaned = "+972" + cleaned[1:]
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def validate_employee_payload(data: dict[str, Any], *, partial: bool = False) -> list[str]:
    errors: list[str] = []
    if not partial or "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            errors.append("שם הוא שדה חובה")
    if not partial or "gender" in data:
        gender = data.get("gender")
        if gender not in ("male", "female"):
            errors.append("מגדר חייב להיות male או female")
    if not partial or "phone" in data:
        phone = data.get("phone", "")
        try:
            normalized = normalize_phone(str(phone))
            if not PHONE_RE.match(normalized):
                errors.append("מספר טלפון לא תקין")
        except Exception:
            errors.append("מספר טלפון לא תקין")
    if "active" in data and not isinstance(data["active"], bool):
        errors.append("active חייב להיות בוליאני")
    return errors


def create_employee(data: dict[str, Any]) -> dict[str, Any]:
    errors = validate_employee_payload(data)
    if errors:
        raise ValueError("; ".join(errors))

    phone = normalize_phone(data["phone"])
    existing = find_by_phone(phone)
    if existing:
        raise ValueError("עובד עם מספר טלפון זה כבר קיים")

    payload = {
        "name": data["name"].strip(),
        "gender": data["gender"],
        "phone": phone,
        "active": data.get("active", True),
        "notes": (data.get("notes") or "").strip(),
    }
    emp = db.create_doc("employees", payload)
    logger.info("Created employee %s (%s)", emp["id"], emp["name"])
    return emp


def update_employee(emp_id: str, data: dict[str, Any]) -> dict[str, Any]:
    existing = db.get_doc("employees", emp_id)
    if not existing:
        raise LookupError("עובד לא נמצא")

    errors = validate_employee_payload(data, partial=True)
    if errors:
        raise ValueError("; ".join(errors))

    updates: dict[str, Any] = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "gender" in data:
        updates["gender"] = data["gender"]
    if "phone" in data:
        phone = normalize_phone(data["phone"])
        other = find_by_phone(phone)
        if other and other["id"] != emp_id:
            raise ValueError("עובד עם מספר טלפון זה כבר קיים")
        updates["phone"] = phone
    if "active" in data:
        updates["active"] = bool(data["active"])
    if "notes" in data:
        updates["notes"] = (data.get("notes") or "").strip()

    updated = db.update_doc("employees", emp_id, updates)
    assert updated is not None
    logger.info("Updated employee %s", emp_id)
    return updated


def delete_employee(emp_id: str) -> bool:
    ok = db.delete_doc("employees", emp_id)
    if ok:
        logger.info("Deleted employee %s", emp_id)
    return ok


def get_employee(emp_id: str) -> dict[str, Any] | None:
    return db.get_doc("employees", emp_id)


def list_employees(*, active_only: bool = False) -> list[dict[str, Any]]:
    docs = db.list_docs("employees")
    if active_only:
        docs = [d for d in docs if d.get("active", True)]
    return sorted(docs, key=lambda d: d.get("name", ""))


def find_by_phone(phone: str) -> dict[str, Any] | None:
    normalized = normalize_phone(phone)
    # Also try without whatsapp: prefix
    candidates = {normalized, normalized.replace("whatsapp:", "")}
    for emp in list_employees():
        if emp.get("phone") in candidates:
            return emp
    return None
