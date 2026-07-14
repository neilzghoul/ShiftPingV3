"""Schedule generation, editing, publish, and priority finalization API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import priority, scheduler, whatsapp
from app.utils.auth import require_admin
from app.utils.dates import next_week_id
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("schedules", __name__)


def _finalize_priority(week_id: str, grid: dict | None = None) -> list[dict]:
    """Calculate and store priority_history after a schedule is ready."""
    try:
        rows = priority.record_priority_for_week(week_id, grid=grid)
        logger.info("Recorded %d priority_history rows for week %s", len(rows), week_id)
        return rows
    except Exception:
        logger.exception("Failed to record priority for week %s", week_id)
        raise


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
        priority_rows = _finalize_priority(week, grid=result.get("grid"))
        enriched = scheduler.enrich_schedule(result)
        return jsonify({
            "schedule": enriched,
            "priorityHistory": priority_rows,
        })
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
        priority_rows = None
        if saved.get("published") or data.get("finalizePriority"):
            priority_rows = _finalize_priority(week_id, grid=grid)
        return jsonify({
            "schedule": scheduler.enrich_schedule(saved),
            "warnings": scheduler.validate_schedule(grid),
            "priorityHistory": priority_rows,
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
        sched = scheduler.get_schedule(week_id)
        priority_rows = _finalize_priority(week_id, grid=(sched or {}).get("grid"))
        result["priorityHistory"] = priority_rows
        return jsonify(result)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        logger.exception("Publish failed")
        return jsonify({"error": "שגיאה בפרסום הסידור"}), 500


@bp.post("/api/schedules/<week_id>/priority")
@require_admin
def api_record_priority(week_id: str):
    """Manually (re)calculate priority_history for a week."""
    try:
        rows = _finalize_priority(week_id)
        return jsonify({"week": week_id, "priorityHistory": rows})
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        logger.exception("Priority finalize failed")
        return jsonify({"error": "שגיאה בחישוב עדיפות"}), 500


@bp.get("/api/priority-history")
@require_admin
def api_priority_history():
    week = request.args.get("week")
    nurse_id = request.args.get("nurse_id")
    rows = priority.list_priority_history(week=week or None, nurse_id=nurse_id or None)
    return jsonify({"priorityHistory": rows, "week": week, "nurse_id": nurse_id})
