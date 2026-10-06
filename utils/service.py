import os
import uuid
from datetime import datetime, timedelta, date, timezone
from typing import Optional, Dict, Any, List

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client 

# .env 読み込み
load_dotenv(dotenv_path=".env")

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

# =========================
# Supabase クライアント
# =========================

def get_supabase_client() -> Client:
    """Supabaseクライアントを取得（認証セッション付き）"""
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL または SUPABASE_KEY が設定されていません。.env または Secrets を確認してください。")

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