"""相談ログのSupabase保存と、画面で使うマスタの取得。接続は他の画面と共通の utils/service.py を使う。"""

import streamlit as st

from utils.service import get_supabase_client


@st.cache_data(ttl=300, show_spinner=False)
def load_employees() -> list[dict]:
    """社員の一覧（employee_id / name / department）。相談者の選択肢に使う。"""
    rows = get_supabase_client().table("employees").select("employee_id, name, department").execute().data or []
    return sorted(rows, key=lambda r: r["employee_id"])


@st.cache_data(ttl=300, show_spinner=False)
def load_category_options() -> tuple[list[str], list[str]]:
    """AIが選べるジャンル（category_1）と困りごと（category_2）の一覧。"""
    client = get_supabase_client()
    category_1 = [r["category_1"] for r in client.table("category1_master").select("category_1").execute().data or []]
    category_2 = [r["category_2"] for r in client.table("category2_master").select("category_2").execute().data or []]
    return category_1, category_2


def save_chat_log(
    employee_id: str,
    department: str,
    category_1: str | None,
    category_2: str,
    issue_summary: str,
) -> str:
    # 相談ログを1件保存し、発行されたlog_idを返す
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
