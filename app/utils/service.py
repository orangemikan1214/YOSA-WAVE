import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client 

# アプリ起動時に1回だけ.envをロード
load_dotenv(dotenv_path=".env", override=True)

def _get_supabase_creds():
    """Supabase認証情報を取得"""
    url = st.secrets.get("SUPABASE_URL") if "SUPABASE_URL" in st.secrets else os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") if "SUPABASE_KEY" in st.secrets else os.getenv("SUPABASE_KEY")
    return url, key

# クライアント作成をキャッシュ化して高速化
@st.cache_resource
def _create_cached_supabase_client(url: str, key: str) -> Client:
    """Supabaseクライアント本体の生成（キャッシュ対象）"""
    clean_url = str(url).strip().rstrip("/")
    clean_key = str(key).strip()
    return create_client(clean_url, clean_key)


def get_supabase_client() -> Client:
    """高速かつ安全にSupabaseクライアントを取得"""
    url, key = _get_supabase_creds()

    if not url or not key:
        raise ValueError("SUPABASE_URL または SUPABASE_KEY が取得できていません。")

    # キャッシュされたクライアントを取得（爆速化）
    supabase = _create_cached_supabase_client(url, key)

    # ユーザー認証セッションがある場合のみ反映
    if "access_token" in st.session_state and "refresh_token" in st.session_state:
        try:
            supabase.auth.set_session(
                st.session_state["access_token"],
                st.session_state["refresh_token"]
            )
        except Exception:
            pass

    return supabase