"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify

from app.config import config
from app.services import db
from app.utils.logging_setup import get_logger, setup_logging

ROOT = Path(__file__).resolve().parent.parent

_app: Flask | None = None


def create_app() -> Flask:
    setup_logging()
    logger = get_logger(__name__)

    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["JSON_AS_ASCII"] = False

    db.init_db()

    from app.routes.employees import bp as employees_bp
    from app.routes.pages import bp as pages_bp
    from app.routes.preferences import bp as preferences_bp
    from app.routes.schedules import bp as schedules_bp
    from app.routes.swaps import bp as swaps_bp
    from app.routes.webhooks import bp as webhooks_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(swaps_bp)
    app.register_blueprint(webhooks_bp)

    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify({"error": "לא נמצא"}), 404
        return e

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error: %s", e)
        return jsonify({"error": "שגיאת שרת פנימית"}), 500

    logger.info("ShiftPing app created (mock_db=%s)", db.using_mock())
    return app


def get_app() -> Flask:
    global _app
    if _app is None:
        _app = create_app()
    return _app


def _wants_json() -> bool:
    from flask import request

    return "application/json" in (request.accept_mimetypes.best or "") or request.path.startswith("/api/")


# Lazy WSGI callable for servers that expect `app`
class _AppProxy:
    def __getattr__(self, name):
        return getattr(get_app(), name)

    def __call__(self, environ, start_response):
        return get_app()(environ, start_response)


app = _AppProxy()
