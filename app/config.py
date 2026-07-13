"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Runtime configuration for ShiftPing."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "admin-dev-token")

    # Firebase
    FIREBASE_CREDENTIALS_JSON: str = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
    FIREBASE_CREDENTIALS_PATH: str = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "")
    USE_MOCK_DB: bool = os.getenv("USE_MOCK_DB", "true").lower() in ("1", "true", "yes")

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    TWILIO_WEBHOOK_VALIDATE: bool = os.getenv("TWILIO_WEBHOOK_VALIDATE", "false").lower() in (
        "1",
        "true",
        "yes",
    )

    # App
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:5000")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jerusalem")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Scheduling defaults
    SHIFTS_PER_DAY: int = int(os.getenv("SHIFTS_PER_DAY", "3"))
    NURSES_PER_SHIFT: int = int(os.getenv("NURSES_PER_SHIFT", "2"))


config = Config()
