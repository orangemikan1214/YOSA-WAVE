"""Streamlit 相談画面（社員が使う相談AI）。起動: プロジェクト直下で streamlit run consult_app/app.py"""

import os
import re
import sys
from pathlib import Path

import streamlit as st

# 共通設定（utils/）をプロジェクト直下から読めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.env import load_env  # noqa: E402
from ai_client import ask_ai  # noqa: E402
from anonymizer import mask_text  # noqa: E402
from database import load_category_options, load_employees, save_chat_log  # noqa: E402

load_env()
st.set_page_config(page_title="マネージャー支援AI", page_icon="💬")

st.title("せーせーAI-分からん事相談してミーナ")

# ★変更：DBには質問全文ではなく、入力した課題の要約を保存する
st.caption("相談内容をAIに送り、課題情報とマスキング済みの回答をSupabaseに保存")

# ★変更：employee_idはDBに保存されることを明示
st.info(
    "相談内容はマスキングせずAIに送信するで。"
    "データベースには、AIが作成した課題の要約をマスキングして保存するから安心してや。"
    "メールアドレスとハイフン付き電話番号を自動置換するけど"
    "氏名・会社名などは自動で除去できんからな"
    "社員IDはデータベースにそのまま保存されるで"
)

# 社員の一覧と、AIが選べる分類（ジャンル・困りごと）は、Supabaseのマスタから取得する
try:
    employees = load_employees()
    category_1_values, category_2_values = load_category_options()
except Exception as exc:
    st.error(f"Supabaseからマスタを取得できませんでした：{type(exc).__name__}")
    st.stop()

# chatGPT風にサイドバーを作成
with st.sidebar:
    st.header("ユーザ情報")

    # 社員はマスタ（employees）から選ぶ。部署は、選んだ社員の所属が自動で入る
    employee_options = {f"{e['employee_id']}　{e['name']}": e for e in employees}
    selected_label = st.selectbox("社員", ["（選択してください）"] + list(employee_options))
    selected_employee = employee_options.get(selected_label)
    employee_id = selected_employee["employee_id"] if selected_employee else ""
    department = selected_employee["department"] if selected_employee else ""
    if selected_employee:
        st.caption(f"部署：{department}")

    if st.button("画面の会話を消去"):
        st.session_state.messages = []
        st.rerun()


# 追加①：DBへ保存する課題情報の入力欄
st.subheader("課題情報")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 社員IDや部署を切り替えた後、前の人の会話を次のAPI呼び出しへ渡さない。
identity = (employee_id.strip(), department)
if st.session_state.get("active_identity") != identity:
    st.session_state.messages = []
    st.session_state.active_identity = identity

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

raw_prompt = st.chat_input("相談内容を入力してください")

if raw_prompt:
    if not employee_id.strip():
        st.error("先にサイドバーで社員を選択してください。")

    # 追加部分：課題名と要約が空ならAPIを呼ばない


    elif not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY が未設定です。.env の設定を確認してください。")

    elif not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        st.error("Supabaseの接続設定が未設定です。.env を確認してください。")

    else:
        masked_prompt = mask_text(raw_prompt.strip())

        # 過去の会話もマスキングせずに文字列だけをAPIに渡す。
        messages_for_ai = st.session_state.messages + [
            {"role": "user", "content": raw_prompt.strip()}
        ]

        failed_step = "AI API"

        try:
            with st.spinner("回答を作成中..."):
                ai_result = ask_ai(messages_for_ai, category_1_values, category_2_values)

                db_summary = mask_text(ai_result.issue_summary)

                # 保存に失敗した場合、画面にも履歴にも回答を追加しない。
                failed_step = "Supabaseへの保存"

                # 変更部分：database.pyの新しい引数に合わせて6項目渡す
                save_chat_log(
                    employee_id.strip(),
                    department,
                    ai_result.category_1,
                    ai_result.category_2,
                    db_summary,
                )

        except Exception as exc:
            # 相談内容が含まれる可能性のある詳細は表示しない。
            code = getattr(exc, "code", None)
            status = getattr(exc, "status_code", None)
            match = re.search(r'constraint "([^"]+)"', str(exc))
            constraint = match.group(1) if match else "不明"
            st.error(
                f"{failed_step}で失敗しました：{type(exc).__name__}"
                f" / code={code} / HTTP={status} / constraint={constraint}"
            )

        else:
            st.session_state.messages.extend([
                {"role": "user", "content": masked_prompt},
                # 画面には元の回答を出力
                {"role": "assistant", "content": ai_result.answer},  
            ])
            st.rerun()