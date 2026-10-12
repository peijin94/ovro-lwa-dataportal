"""
Visitor logging for the OVRO LWA data portal.

This module keeps a small SQLite database of page visits so we can
track basic usage (timestamp, path, IP, user agent).

The implementation is adapted from the StreamReceiver visitor logging
in SunSpecStreamSys (record_visit / _init_visitor_db).

Design notes (2026-10-12, issue #8):
* The tables are created once, at import time -- not on every request.
* Writes happen off the event loop (the caller awaits
  ``run_in_threadpool(record_visit, request)``); this module stays
  synchronous and serialises access with a module-level lock.
* Retention: raw rows older than ``VISITORS_RETAIN_DAYS`` (default 365)
  are folded into a cumulative archive counter at startup, so the file
  stays bounded while ``/portal/visitors/count`` keeps returning the
  cumulative number of visits.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi import Request


DB_PATH = os.environ.get(
    "VISITORS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "visitors.db"),
)
RETAIN_DAYS = int(os.environ.get("VISITORS_RETAIN_DAYS", "365"))

_lock = threading.Lock()


def _now_iso() -> str:
    """UTC timestamp in the same shape as the historical rows (...Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """Serialised short-lived connection; commits on success, closes always."""
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def _init_visitor_db() -> None:
    """Create the visitor tables once (idempotent)."""
    try:
        with _db() as conn:
            conn.execute(
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visits_time ON visits(visited_at_utc)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visits_archive (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    archived_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO visits_archive (id, archived_count) VALUES (1, 0)"
            )
    except Exception as exc:  # pragma: no cover - best-effort logging
        # If visitor DB fails, log and continue; core functionality should not break.
        print(f"[VISITORS_ERROR] Failed to initialize visitor DB: {exc}")


def _prune_old_rows() -> None:
    """Fold raw rows older than RETAIN_DAYS into the archive counter."""
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)
        ).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        with _db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM visits WHERE visited_at_utc < ?", (cutoff,)
            ).fetchone()
            n = int(row[0]) if row else 0
            if n:
                conn.execute("DELETE FROM visits WHERE visited_at_utc < ?", (cutoff,))
                conn.execute(
                    "UPDATE visits_archive SET archived_count = archived_count + ? WHERE id = 1",
                    (n,),
                )
                print(f"[VISITORS] Pruned {n} rows older than {cutoff}")
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[VISITORS_ERROR] Failed to prune visitor DB: {exc}")


def record_visit(req: Request) -> None:
    """Record a single page visit.

    Blocking (SQLite); callers on async routes must run it via
    ``run_in_threadpool`` so the event loop is never blocked.
    """
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

    visited_at = _now_iso()

    for attempt in (1, 2):
        try:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO visits (visited_at_utc, path, ip, user_agent) VALUES (?, ?, ?, ?)",
                    (visited_at, path, ip, user_agent[:512]),
                )
            return
        except Exception as exc:  # pragma: no cover - best-effort logging
            if attempt == 1:
                # The table may have been dropped at runtime (e.g. manual DB
                # surgery); rebuild it once and retry.
                _init_visitor_db()
                continue
            print(f"[VISITORS_ERROR] Failed to record visit: {exc}")


def get_visitor_count() -> int:
    """Return the cumulative number of recorded visits (archive + live rows)."""
    try:
        with _db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM visits").fetchone()
            live = int(row[0]) if row and row[0] is not None else 0
            row = conn.execute(
                "SELECT archived_count FROM visits_archive WHERE id = 1"
            ).fetchone()
            archived = int(row[0]) if row else 0
        return archived + live
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[VISITORS_ERROR] Failed to read visitor count: {exc}")
        return 0


# Create the tables once when the app is imported (i.e. at startup), and
# apply the retention window once per process start.
_init_visitor_db()
_prune_old_rows()
