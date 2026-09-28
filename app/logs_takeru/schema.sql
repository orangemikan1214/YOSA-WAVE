CREATE TABLE IF NOT EXISTS chat_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    department TEXT NOT NULL,
    category TEXT,
    issue TEXT,
    issue_summary TEXT NOT NULL,
    response_masked TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_logs_department_date
ON chat_logs(department, created_at);
