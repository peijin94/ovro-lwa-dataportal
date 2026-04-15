"""AI summary SQLite helpers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from backend.config import AI_SUMMARY_DB_PATH


def _ensure_db() -> None:
    """Create DB/table and seed placeholder summaries for recent days."""
    AI_SUMMARY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AI_SUMMARY_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_summary (
                date TEXT PRIMARY KEY,
                summary TEXT NOT NULL
            )
            """
        )
        # Seed placeholder data for the past few days.
        today = datetime.now(timezone.utc).date()
        for delta in range(0, 7):
            d = today - timedelta(days=delta)
            date_str = d.strftime("%Y-%m-%d")
            cur.execute(
                "INSERT OR IGNORE INTO ai_summary (date, summary) VALUES (?, ?)",
                (date_str, "template text"),
            )
        conn.commit()
    finally:
        conn.close()


def get_ai_summary_for_date(date: str) -> str:
    """Return AI summary for date (YYYY-MM-DD), fallback to placeholder text."""
    _ensure_db()
    conn = sqlite3.connect(str(AI_SUMMARY_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT summary FROM ai_summary WHERE date = ?", (date,))
        row = cur.fetchone()
        return row[0] if row else "template text"
    finally:
        conn.close()

