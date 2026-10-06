"""相談ログのSQLite保存。既存のTech0 Searchと同じ接続・INSERT方式。"""

import os

from supabase import Client, create_client

def get_client() -> Client:
    #環境変数を使ってSupabaseに接続する。
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError("Supabaseの接続設定がありません")

    return create_client(url, key)


def save_chat_log(
    employee_id: str,
    department: str,
    category_1: str | None,
    category_2: str,
    issue_summary: str,
) -> str:
    #相談ログを1件保存し、発行されたlog_idを返す
    result = (
        get_client()
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