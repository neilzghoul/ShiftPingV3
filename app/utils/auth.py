"""Simple admin token auth for API mutating endpoints."""

from __future__ import annotations

from functools import wraps

from flask import jsonify, request

from app.config import config


def _extract_token() -> str | None:
    token = request.headers.get("X-Admin-Token") or request.args.get("token")
    if token:
        return token
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if body.get("token"):
            return body["token"]
    token = request.form.get("token") or request.cookies.get("admin_token")
    return token


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token or token != config.ADMIN_TOKEN:
            return jsonify({"error": "אין הרשאה – נדרש אסימון מנהל"}), 401
        return fn(*args, **kwargs)

    return wrapper
