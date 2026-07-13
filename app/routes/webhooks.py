"""Twilio WhatsApp webhook + seed/health endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from app.services import db, sample_data, whatsapp
from app.utils.auth import require_admin
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
bp = Blueprint("webhooks", __name__)


@bp.post("/webhook/whatsapp")
def twilio_whatsapp_webhook():
    """Inbound WhatsApp messages from Twilio."""
    form = request.form.to_dict()
    signature = request.headers.get("X-Twilio-Signature", "")
    # Reconstruct URL – prefer APP_BASE_URL for proxy correctness
    from app.config import config

    url = request.url
    if config.APP_BASE_URL and not config.APP_BASE_URL.startswith("http://localhost"):
        url = config.APP_BASE_URL.rstrip("/") + "/webhook/whatsapp"

    if not whatsapp.validate_twilio_request(url, form, signature):
        logger.warning("Invalid Twilio signature")
        return Response("Forbidden", status=403)

    from_number = form.get("From", "")
    body = form.get("Body", "")
    logger.info("Inbound WhatsApp from=%s body=%r", from_number, body[:120])

    try:
        reply = whatsapp.handle_inbound(from_number, body)
    except Exception:
        logger.exception("Error handling inbound WhatsApp")
        reply = "אירעה שגיאה זמנית. נסו שוב מאוחר יותר."

    # TwiML response
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{_xml_escape(reply)}</Message></Response>"
    )
    return Response(twiml, mimetype="application/xml")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@bp.post("/api/seed")
@require_admin
def api_seed():
    data = request.get_json(silent=True) or {}
    result = sample_data.seed_sample_data(reset=bool(data.get("reset")))
    return jsonify(result)


@bp.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "mockDb": db.using_mock(),
        "service": "ShiftPing",
    })
