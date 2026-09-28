"""相談ログのSQLite保存。既存のTech0 Searchと同じ接続・INSERT方式。"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "manager_ai.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8"))


def save_chat_log(
    employee_id, department, category, issue,
    issue_summary, response_masked
):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO chat_logs
               (employee_id, department, category, issue,
                issue_summary, response_masked, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                employee_id, department, category, issue,
                issue_summary, response_masked,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cursor.lastrowid
