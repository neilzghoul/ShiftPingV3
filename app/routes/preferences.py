"""Preferences API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import employees, preferences
from app.utils.auth import require_admin
from app.utils.dates import next_week_id
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("preferences", __name__)


@bp.get("/api/preferences")
@require_admin
def api_list_preferences():
    week = request.args.get("week") or next_week_id()
    prefs = preferences.list_preferences_for_week(week)
    emp_map = {e["id"]: e for e in employees.list_employees()}
    enriched = []
    for p in prefs:
        item = dict(p)
        emp = emp_map.get(p.get("employeeId"))
        item["employeeName"] = emp["name"] if emp else p.get("employeeId")
        enriched.append(item)
    return jsonify({"weekId": week, "preferences": enriched})


@bp.get("/api/preferences/<emp_id>")
@require_admin
def api_get_preferences(emp_id: str):
    week = request.args.get("week") or next_week_id()
    if not employees.get_employee(emp_id):
        return jsonify({"error": "עובד לא נמצא"}), 404
    return jsonify({"preferences": preferences.get_preferences(emp_id, week)})


@bp.put("/api/preferences/<emp_id>")
@require_admin
def api_put_preferences(emp_id: str):
    data = request.get_json(silent=True) or {}
    week = data.get("weekId") or request.args.get("week") or next_week_id()
    if not employees.get_employee(emp_id):
        return jsonify({"error": "עובד לא נמצא"}), 404
    grid = data.get("grid")
    if not isinstance(grid, dict):
        return jsonify({"error": "נדרש grid"}), 400
    try:
        doc = preferences.set_full_grid(emp_id, week, grid, submitted=bool(data.get("submitted", True)))
        return jsonify({"preferences": doc})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/preferences/request")
@require_admin
def api_request_preferences():
    from app.services import whatsapp

    week = (request.get_json(silent=True) or {}).get("weekId") or next_week_id()
    result = whatsapp.request_preferences(week)
    return jsonify(result)
