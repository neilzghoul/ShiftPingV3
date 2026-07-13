"""Employee CRUD API + pages."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import employees
from app.utils.auth import require_admin
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("employees", __name__)


@bp.get("/api/employees")
@require_admin
def api_list_employees():
    active_only = request.args.get("active") == "1"
    return jsonify({"employees": employees.list_employees(active_only=active_only)})


@bp.post("/api/employees")
@require_admin
def api_create_employee():
    data = request.get_json(silent=True) or {}
    try:
        emp = employees.create_employee(data)
        return jsonify({"employee": emp}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.get("/api/employees/<emp_id>")
@require_admin
def api_get_employee(emp_id: str):
    emp = employees.get_employee(emp_id)
    if not emp:
        return jsonify({"error": "עובד לא נמצא"}), 404
    return jsonify({"employee": emp})


@bp.put("/api/employees/<emp_id>")
@bp.patch("/api/employees/<emp_id>")
@require_admin
def api_update_employee(emp_id: str):
    data = request.get_json(silent=True) or {}
    try:
        emp = employees.update_employee(emp_id, data)
        return jsonify({"employee": emp})
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/api/employees/<emp_id>")
@require_admin
def api_delete_employee(emp_id: str):
    if not employees.delete_employee(emp_id):
        return jsonify({"error": "עובד לא נמצא"}), 404
    return jsonify({"ok": True})
