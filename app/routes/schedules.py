"""Schedule generation, editing, and publish API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import scheduler, whatsapp
from app.utils.auth import require_admin
from app.utils.dates import next_week_id
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("schedules", __name__)


@bp.get("/api/schedules/<week_id>")
@require_admin
def api_get_schedule(week_id: str):
    sched = scheduler.get_schedule(week_id)
    if not sched:
        return jsonify({"error": "סידור לא נמצא", "weekId": week_id}), 404
    return jsonify({"schedule": scheduler.enrich_schedule(sched)})


@bp.get("/api/schedules")
@require_admin
def api_get_current_schedule():
    week = request.args.get("week") or next_week_id()
    sched = scheduler.get_schedule(week)
    if not sched:
        return jsonify({"schedule": None, "weekId": week})
    return jsonify({"schedule": scheduler.enrich_schedule(sched), "weekId": week})


@bp.post("/api/schedules/generate")
@require_admin
def api_generate_schedule():
    data = request.get_json(silent=True) or {}
    week = data.get("weekId") or next_week_id()
    nps = data.get("nursesPerShift")
    try:
        result = scheduler.generate_schedule(
            week,
            nurses_per_shift=int(nps) if nps else None,
            save=True,
        )
        return jsonify({"schedule": scheduler.enrich_schedule(result)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Schedule generation failed")
        return jsonify({"error": "שגיאה ביצירת סידור"}), 500


@bp.put("/api/schedules/<week_id>")
@require_admin
def api_update_schedule(week_id: str):
    data = request.get_json(silent=True) or {}
    grid = data.get("grid")
    if not isinstance(grid, dict):
        return jsonify({"error": "נדרש grid"}), 400
    try:
        saved = scheduler.save_schedule(
            week_id,
            grid,
            status=data.get("status", "draft"),
            published=bool(data.get("published", False)),
            notes=data.get("notes", ""),
            generationLog=data.get("generationLog", []),
        )
        return jsonify({
            "schedule": scheduler.enrich_schedule(saved),
            "warnings": scheduler.validate_schedule(grid),
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.patch("/api/schedules/<week_id>/assignment")
@require_admin
def api_patch_assignment(week_id: str):
    data = request.get_json(silent=True) or {}
    day = data.get("day")
    shift = data.get("shift")
    employee_ids = data.get("employeeIds")
    if not day or not shift or not isinstance(employee_ids, list):
        return jsonify({"error": "נדרשים day, shift, employeeIds"}), 400
    try:
        saved = scheduler.update_assignment(week_id, day, shift, employee_ids)
        return jsonify({
            "schedule": scheduler.enrich_schedule(saved),
            "warnings": scheduler.validate_schedule(saved["grid"]),
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/schedules/<week_id>/publish")
@require_admin
def api_publish_schedule(week_id: str):
    try:
        result = whatsapp.publish_schedule(week_id)
        return jsonify(result)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        logger.exception("Publish failed")
        return jsonify({"error": "שגיאה בפרסום הסידור"}), 500
