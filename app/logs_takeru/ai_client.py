"""OpenAI Responses API との通信。"""

import os

from openai import OpenAI


def ask_ai(messages: list[dict[str, str]]) -> str:
    """マスキング済み会話を渡し、回答文を返す。"""
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    # 毎回履歴を渡すのでサーバー側の会話保存には依存しない。
    response = OpenAI(timeout=30.0, max_retries=1).responses.create(
        model=model,
        instructions=(
            "あなたは新規事業に関する相談の補助役です。日本語で簡潔に答え、"
            "不確かなことは断定せず、必要なら確認事項を示してください。"
        ),
        input=messages,
        store=False,
    )
    answer = response.output_text
    if not answer:
        raise ValueError("AIの回答が空でした")
    return answer
