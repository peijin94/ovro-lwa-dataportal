"""
Visitor logging for the OVRO LWA data portal.

This module keeps a small SQLite database of page visits so we can
track basic usage (timestamp, path, IP, user agent).

The implementation is adapted from the StreamReceiver visitor logging
in SunSpecStreamSys (record_visit / _init_visitor_db).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import Request


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visitors.db")


def _init_visitor_db() -> None:
    """Initialize local SQLite database for visitor logging."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visited_at_utc TEXT NOT NULL,
                path TEXT NOT NULL,
                ip TEXT,
                user_agent TEXT
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # pragma: no cover - best-effort logging
        # If visitor DB fails, log and continue; core functionality should not break.
        print(f"[VISITORS_ERROR] Failed to initialize visitor DB: {exc}")


def record_visit(req: Request) -> None:
    """Record a single page visit in the visitor database."""
    _init_visitor_db()
    try:
        headers: Any = req.headers or {}

        # Normalize header keys to lowercase for safety
        xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")

        if xff:
            ip = xff.split(",", 1)[0].strip()
        else:
            # FastAPI/Starlette style: request.client.host
            client = req.client
            ip = client.host if client else ""

        path = getattr(req.url, "path", "/")
        user_agent = headers.get("user-agent", "") or ""

        # Skip noisy internal probes (e.g. python-requests health checks)
        # and local 127.0.0.1 traffic, which are not real visitors.
        if "python-requests" in user_agent.lower():
            return
        if ip in ("127.0.0.1", "::1", ""):
            return

        visited_at = datetime.utcnow().isoformat() + "Z"

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO visits (visited_at_utc, path, ip, user_agent) VALUES (?, ?, ?, ?)",
            (visited_at, path, ip, user_agent[:512]),
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[VISITORS_ERROR] Failed to record visit: {exc}")


def get_visitor_count() -> int:
    """Return total number of recorded visits."""
    _init_visitor_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM visits")
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[VISITORS_ERROR] Failed to read visitor count: {exc}")
        return 0


