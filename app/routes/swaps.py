"""Admin API for shift swaps."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import swap_whatsapp, swaps
from app.utils.auth import require_admin
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("swaps", __name__)


@bp.get("/api/swaps")
@require_admin
def api_list_swaps():
    week = request.args.get("week")
    status = request.args.get("status")
    pending = request.args.get("pending") == "1"
    rows = [
        swaps.enrich_swap(s)
        for s in swaps.list_swaps(week=week or None, status=status or None, pending_only=pending)
    ]
    return jsonify({"swaps": rows})


@bp.get("/api/swap-audit")
@require_admin
def api_swap_audit():
    swap_id = request.args.get("swap_id")
    return jsonify({"audit": swaps.list_swap_audit(swap_id or None)})


@bp.get("/api/swaps/<swap_id>")
@require_admin
def api_get_swap(swap_id: str):
    swap = swaps.get_swap(swap_id)
    if not swap:
        return jsonify({"error": "לא נמצא"}), 404
    return jsonify({"swap": swaps.enrich_swap(swap)})


@bp.post("/api/swaps")
@require_admin
def api_create_swap():
    data = request.get_json(silent=True) or {}
    try:
        swap = swaps.create_swap_request(
            data["requester_nurse_id"],
            data["proposed_nurse_id"],
            data["original_shift"],
            requested_shift=data.get("requested_shift"),
            week=data.get("week"),
        )
        swap_whatsapp.notify_proposed_nurse(swap)
        return jsonify({"swap": swaps.enrich_swap(swap)}), 201
    except KeyError as exc:
        return jsonify({"error": f"חסר שדה: {exc}"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/swaps/<swap_id>/approve")
@require_admin
def api_approve_swap(swap_id: str):
    """Manual admin approve (backup for WhatsApp)."""
    try:
        swap = swaps.get_swap(swap_id)
        if not swap:
            return jsonify({"error": "לא נמצא"}), 404
        status = swap.get("status")
        if status == swaps.STATUS_PENDING_PROPOSED:
            swap = swaps.admin_approve(swap_id)
            swap_whatsapp.notify_swap_outcome(swap, approved=True)
        elif status == swaps.STATUS_PENDING_CHIEF:
            swap = swaps.approve_by_chief(swap_id, force_admin=True)
            swap_whatsapp.notify_swap_outcome(swap, approved=True)
        else:
            return jsonify({"error": "הבקשה אינה במצב לאישור"}), 400
        return jsonify({"swap": swaps.enrich_swap(swap)})
    except (ValueError, LookupError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/swaps/<swap_id>/reject")
@require_admin
def api_reject_swap(swap_id: str):
    data = request.get_json(silent=True) or {}
    try:
        swap = swaps.reject_swap(swap_id, actor_id=None, reason=data.get("reason") or "נדחה ע״י מנהל")
        swap_whatsapp.notify_swap_outcome(swap, approved=False)
        return jsonify({"swap": swaps.enrich_swap(swap)})
    except (ValueError, LookupError) as exc:
        return jsonify({"error": str(exc)}), 400
