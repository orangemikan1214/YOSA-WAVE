"""OpenAI Responses API との通信。"""

import os

from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

class AIResult(BaseModel):
    category: Literal[
         "未分類", "予算・人員", "技術", "品質", "部署間連携"
    ]
    issue: str
    issue_summary: str
    answer: str

def ask_ai(messages: list[dict[str, str]]) -> AIResult:
    """マスキング済み会話を渡し、回答文を返す。"""
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # 毎回履歴を渡すのでサーバー側の会話保存には依存しない。
    response = OpenAI(timeout=30.0, max_retries=1).responses.parse(
        model=model,
        #プロンプト部分
        instructions=(
            "あなたは新規事業に関する相談の補助役です。日本語で簡潔に答え、"
            "不確かなことは断定せず、必要なら確認事項を示してください。"
            "最新のユーザーの相談を中心に分析し、"
            "categoryは指定された選択肢から最も近いものを選んでください。"
            "issueは具体的な課題を短い題名にしてください。"
            "issue_summaryは課題を1～2文で要約してください。"
            "相談から課題を判断できない場合はcategoryを未分類、"
            "issueを『課題未特定』とし、推測で課題を作らないでください。"
        ),
        input=messages,
        text_format = AIResult,
        store=False,
    )

    result = response.output_parsed
    if result is None:
        raise ValueError("AIの回答が得られませんでした")
    return result
