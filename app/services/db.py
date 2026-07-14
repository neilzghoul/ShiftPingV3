"""Firestore / in-memory database layer for ShiftPing.

Collections:
  employees/{id}     – nurse profiles
  preferences/{id}   – weekly preference docs (employeeId_weekId)
  schedules/{weekId} – generated/edited weekly schedules
  conversations/{phone} – WhatsApp conversation state
  priority_history/{nurseId_week} – preference satisfaction scores
  shift_swaps/{id} – swap requests
  swap_audit/{id} – swap audit trail events
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import config
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

_lock = threading.RLock()
_mock_store: dict[str, dict[str, dict[str, Any]]] = {
    "employees": {},
    "preferences": {},
    "schedules": {},
    "conversations": {},
    "priority_history": {},
    "shift_swaps": {},
    "swap_audit": {},
}

_firestore_client = None
_initialized = False
_force_mock = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def using_mock() -> bool:
    init_db()
    return _force_mock or config.USE_MOCK_DB


def init_db() -> None:
    """Initialize Firebase Admin or fall back to mock store."""
    global _firestore_client, _initialized, _force_mock
    if _initialized:
        return

    if config.USE_MOCK_DB:
        logger.info("Using in-memory mock database (USE_MOCK_DB=true)")
        _force_mock = True
        _initialized = True
        return

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            if config.FIREBASE_CREDENTIALS_JSON:
                cred_dict = json.loads(config.FIREBASE_CREDENTIALS_JSON)
                cred = credentials.Certificate(cred_dict)
            elif config.FIREBASE_CREDENTIALS_PATH:
                cred = credentials.Certificate(config.FIREBASE_CREDENTIALS_PATH)
            else:
                cred = credentials.ApplicationDefault()
            options = {}
            if config.FIREBASE_PROJECT_ID:
                options["projectId"] = config.FIREBASE_PROJECT_ID
            firebase_admin.initialize_app(cred, options or None)

        _firestore_client = firestore.client()
        logger.info("Firebase Firestore initialized")
        _initialized = True
    except Exception:
        logger.exception("Firebase init failed – falling back to mock DB")
        _force_mock = True
        _initialized = True


def _col(name: str):
    init_db()
    if using_mock():
        return None
    return _firestore_client.collection(name)


def create_doc(collection: str, data: dict[str, Any], doc_id: str | None = None) -> dict[str, Any]:
    doc_id = doc_id or str(uuid.uuid4())
    payload = {**data, "id": doc_id, "createdAt": _utc_now_iso(), "updatedAt": _utc_now_iso()}

    if using_mock():
        with _lock:
            _mock_store.setdefault(collection, {})[doc_id] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    _col(collection).document(doc_id).set(payload)
    return payload


def get_doc(collection: str, doc_id: str) -> dict[str, Any] | None:
    init_db()
    if using_mock():
        with _lock:
            doc = _mock_store.get(collection, {}).get(doc_id)
            return copy.deepcopy(doc) if doc else None

    snap = _col(collection).document(doc_id).get()
    return snap.to_dict() if snap.exists else None


def update_doc(collection: str, doc_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    init_db()
    payload = {**data, "updatedAt": _utc_now_iso()}

    if using_mock():
        with _lock:
            existing = _mock_store.get(collection, {}).get(doc_id)
            if not existing:
                return None
            existing.update(payload)
            return copy.deepcopy(existing)

    ref = _col(collection).document(doc_id)
    if not ref.get().exists:
        return None
    ref.update(payload)
    return get_doc(collection, doc_id)


def delete_doc(collection: str, doc_id: str) -> bool:
    init_db()
    if using_mock():
        with _lock:
            return _mock_store.get(collection, {}).pop(doc_id, None) is not None

    ref = _col(collection).document(doc_id)
    if not ref.get().exists:
        return False
    ref.delete()
    return True


def list_docs(
    collection: str,
    filters: list[tuple[str, str, Any]] | None = None,
) -> list[dict[str, Any]]:
    init_db()
    if using_mock():
        with _lock:
            docs = list(_mock_store.get(collection, {}).values())
        if filters:
            for field, op, value in filters:
                if op == "==":
                    docs = [d for d in docs if d.get(field) == value]
                elif op == "!=":
                    docs = [d for d in docs if d.get(field) != value]
                elif op == "in":
                    docs = [d for d in docs if d.get(field) in value]
        return copy.deepcopy(docs)

    query = _col(collection)
    if filters:
        for field, op, value in filters:
            query = query.where(field, op, value)
    return [doc.to_dict() for doc in query.stream()]


def upsert_doc(collection: str, doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    existing = get_doc(collection, doc_id)
    if existing:
        updated = update_doc(collection, doc_id, data)
        assert updated is not None
        return updated
    return create_doc(collection, data, doc_id=doc_id)


def clear_mock_store() -> None:
    with _lock:
        for key in _mock_store:
            _mock_store[key] = {}


def dump_mock_store() -> dict[str, Any]:
    with _lock:
        return copy.deepcopy(_mock_store)
