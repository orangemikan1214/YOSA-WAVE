import base64
import json
import os

import streamlit as st
from supabase import create_client, Client

from utils.env import load_env

# .env 読み込み（プロジェクト直下の .env。起動した場所に関係なく同じファイルを読む）
load_env()

# =========================
# Secrets/環境変数の取得
# =========================

def _get_supabase_creds():
    """Supabase認証情報を取得"""
    url = None
    key = None
    try:
        url = st.secrets.get("SUPABASE_URL", url)
        key = st.secrets.get("SUPABASE_KEY", key)
    except Exception:
        pass
    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_KEY")
    return url, key

SUPABASE_URL, SUPABASE_KEY = _get_supabase_creds()


def _assert_public_key(key: str) -> None:
    """管理者権限のキー（secret / service_role）は、アプリでは使わせない。"""
    message = (
        "SUPABASE_KEY に管理者権限のキー（secret / service_role）が設定されています。"
        "アプリには publishable（anon）キーだけを設定してください。"
    )
    if key.startswith("sb_secret_"):
        raise ValueError(message)
    if key.startswith("eyJ"):
        try:
            payload = key.split(".")[1]
            role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
        except Exception:
            return
        if role == "service_role":
            raise ValueError(message)

# =========================
# Supabase クライアント
# =========================

def get_supabase_client() -> Client:
    """Supabaseクライアントを取得（認証セッション付き）。ダッシュボード・マッチング・相談AIで共通。"""

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL または SUPABASE_KEY が設定されていません。.env または Secrets を確認してください。")
    _assert_public_key(SUPABASE_KEY.strip())

    # 末尾の余計なスラッシュを除去（PGRST125エラー防止）
    clean_url = SUPABASE_URL.rstrip("/")
    clean_key = SUPABASE_KEY.strip()

    supabase = create_client(clean_url, clean_key)
    
    # セッションステートから認証情報を取得して設定
    if "access_token" in st.session_state and "refresh_token" in st.session_state:
        supabase.auth.set_session(
            st.session_state["access_token"],
            st.session_state["refresh_token"]
        )
    
    return supabase