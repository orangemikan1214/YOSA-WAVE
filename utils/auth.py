"""ダッシュボードの簡易ログイン（デモ用）。

マネージャー用の共通パスワード（.env の DASHBOARD_PASSWORD）を知っている人だけが画面を開ける。
これは「画面を開けるか」だけを守る。Supabase のデータ自体は守らない（RLS は別途）。
パスワード未設定のときは、誰も入れない（鍵のかけ忘れで素通りしない）。
"""

import hmac
import os

import streamlit as st

from utils.env import load_env


def require_manager_login() -> None:
    """ログイン済みでなければ入力欄を出して st.stop() する。set_page_config の直後に呼ぶ。"""
    if st.session_state.get("manager_authenticated"):
        return

    load_env()
    expected = os.environ.get("DASHBOARD_PASSWORD", "")

    st.title("🔒 マネージャー用ダッシュボード")
    if not expected:
        st.error("DASHBOARD_PASSWORD が .env に設定されていないため、開けません。管理者に連絡してください。")
        st.stop()

    with st.form("manager_login"):
        entered = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン")

    if submitted:
        if hmac.compare_digest(entered.encode(), expected.encode()):
            st.session_state["manager_authenticated"] = True
            st.rerun()
        st.error("パスワードが違います。")
    st.stop()
