"""Streamlit 相談画面。起動: streamlit run app.py"""

import os

import streamlit as st
from dotenv import load_dotenv

from ai_client import ask_ai
from anonymizer import mask_text
from database import init_db, save_chat_log

load_dotenv()
st.set_page_config(page_title="マネージャー支援AI", page_icon="💬")
init_db()

st.title("せーせーAI-分からん事相談してミーナ")

# ★変更：DBには質問全文ではなく、入力した課題の要約を保存する
st.caption("相談内容をAIに送り、課題情報とマスキング済みの回答をSQLiteに保存")

# ★変更：employee_idはDBに保存されることを明示
st.info(
    "メールアドレスとハイフン付き電話番号を自動置換します。"
    "氏名・会社名などは自動で除去できません。"
    "社員IDはデータベースにそのまま保存されます。"
)

# chatGPT風にサイドバーを作成
with st.sidebar:
    st.header("ユーザ情報")

    # ★変更：画面上の表示もemployee_idに合わせる
    employee_id = st.text_input(
        "社員ID", placeholder="例: E001", max_chars=40
    )

    department = st.selectbox(
        "部署",
        ["経営企画本部", "新規事業開発部", "技術本部",
         "品質保証部", "営業本部", "DX推進部", "その他"],
    )

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
        st.error("先に社員IDを入力してください。")

    # 追加部分：課題名と要約が空ならAPIを呼ばない


    elif not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY が未設定です。.env の設定を確認してください。")

    else:
        masked_prompt = mask_text(raw_prompt.strip())

        # 過去の会話もマスキング済みの文字列だけをAPIに渡す。
        messages_for_ai = [
            {"role": m["role"], "content": mask_text(m["content"])}
            for m in st.session_state.messages
        ] + [
            {"role": "user", "content": masked_prompt}
        ]

        failed_step = "AI API"

        try:
            with st.spinner("回答を作成中..."):
                ai_result = ask_ai(messages_for_ai)

                db_answer = mask_text(ai_result.answer)
                db_issue = mask_text(ai_result.issue)
                db_summary = mask_text(ai_result.issue_summary)

                # 保存に失敗した場合、画面にも履歴にも回答を追加しない。
                failed_step = "SQLiteへの保存"

                # 変更部分：database.pyの新しい引数に合わせて6項目渡す
                save_chat_log(
                    employee_id.strip(),
                    department,
                    ai_result.category,
                    db_issue,
                    db_summary,
                    db_answer,
                )

        except Exception as exc:
            # 例外の詳細には送信内容などが含まれる場合があるため画面へ出さない。
            status = getattr(exc, "status_code", None)
            http_code = f" / HTTP {status}" if status is not None else ""
            st.error(
                f"{failed_step}で失敗しました："
                f"{type(exc).__name__}{http_code}"
            )

        else:
            st.session_state.messages.extend([
                {"role": "user", "content": masked_prompt},
                # 画面には元の回答を出力
                {"role": "assistant", "content": ai_result.answer},  
            ])
            st.rerun()