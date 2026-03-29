"""Lightweight JSON-file store for skill improvement records.

Tracks improvement requests (pending, completed, failed) with source/trigger
info, so the Web Portal can show a queue and history view.

File: {data_dir}/skill_improvements.json
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from agenticops.config import settings

logger = logging.getLogger(__name__)


def _store_path() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / "skill_improvements.json"


def _load() -> list[dict[str, Any]]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read skill improvements store, returning empty")
        return []


def _save(records: list[dict[str, Any]]) -> None:
    p = _store_path()
    p.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")


def add_improvement(
    skill_name: str,
    improvement: str,
    source: str = "web",
    trigger: str = "manual",
    status: str = "pending",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add an improvement record and return it."""
    record = {
        "id": uuid.uuid4().hex[:12],
        "skill_name": skill_name,
        "improvement": improvement,
        "source": source,
        "trigger": trigger,
        "status": status,
        "result": result,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "completed_at": None,
    }
    records = _load()
    records.append(record)
    _save(records)
    return record


def update_improvement(record_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Update an existing record by id. Returns updated record or None."""
    records = _load()
    for rec in records:
        if rec["id"] == record_id:
            rec["status"] = status
            if result is not None:
                rec["result"] = result
            if status in ("completed", "failed"):
                rec["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _save(records)
            return rec
    return None


def list_pending() -> list[dict[str, Any]]:
    """Return improvement records with status 'pending'."""
    return [r for r in _load() if r["status"] == "pending"]


def list_history(limit: int = 50) -> list[dict[str, Any]]:
    """Return completed/failed records, newest first."""
    done = [r for r in _load() if r["status"] in ("completed", "failed")]
    done.sort(key=lambda r: r.get("completed_at") or r.get("created_at", ""), reverse=True)
    return done[:limit]


def list_all(limit: int = 100) -> list[dict[str, Any]]:
    """Return all records, newest first."""
    records = _load()
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records[:limit]
