"""相談ログのSQLite保存。既存のTech0 Searchと同じ接続・INSERT方式。"""

import os
from supabase import Client, create_client
from utils.service import get_supabase_client

def save_chat_log(
    employee_id: str,
    department: str,
    category_1: str | None,
    category_2: str,
    issue_summary: str,
) -> str:
    #相談ログを1件保存し、発行されたlog_idを返す
    result = (
        get_supabase_client()
        .table("chat_logs")
        .insert({
            "employee_id": employee_id,
            "department": department,
            "category_1": category_1,
            "category_2": category_2,
            "issue_summary": issue_summary,
        })
        .select("log_id")
        .execute()
    )

    return result.data[0]["log_id"]