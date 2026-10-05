"""OpenAI Responses API との通信。"""

import os

from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

class AIResult(BaseModel):
    category_1: Literal[
        "技術検討", "人材・スキル", "他部署連携",
        "事業戦略", "予算・リソース配分","働き方・職場環境"
    ] | None
    category_2: Literal[
        "手順がわからない", "判断基準が分からない",
        "エラー・障害", "誰に聞くか分からない",
        "情報が見つからない", "作業代行", "課題ではない","悩み・不安", "その他の業務課題"
    ]
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
            "あなたは社員の仕事・職場・学習に関する相談の補助役です。"
            "日本語で簡潔に答え、不確かなことは断定しないでください。"
            "最新のユーザーの相談を中心に、次の項目を作成してください。"

            "category_1とcategory_2は、AIResultで指定された選択肢から選んでください。"

            "ここでいう『課題』には、明示的な問題だけでなく、"
            "困りごと、理解不足、疑問、不安、懸念、違和感、エラー、"
            "改善したいこと、解決方法を求めていることも含みます。"
            "『在宅勤務で孤独感や落ち込みを感じている』は職場での悩みです。"
            "category_1を『働き方・職場環境』、category_2を『悩み・不安』にしてください。"

            "質問形式でも、相談文に本人の理解不足、困りごと、不安、"
            "解決したい事柄が表れていれば『課題』として扱ってください。"

            "例えば、"
            "『正規表現の意味が分からない』は理解不足という課題です。"
            "『生成AIを使うことで自分の思考との境界が曖昧になる』は"
            "生成AI利用に対する懸念という課題です。"
            "『エラーが出て動かない』は技術的な課題です。"

            "一方、単なる雑談、挨拶、困りごとを伴わない単純な事実確認は"
            "課題ではありません。"

            "本人が困りごとや不安を述べている場合、"
            "category_2に『課題ではない』を選ばないでください。"

            "課題が含まれない相談では、category_2を『課題ではない』、"
            "category_1をnullにしてください。"

            "issue_summaryは、課題がある場合は"
            "『何に困っているのか・何を解決したいのか』が分かるように"
            "1～2文で要約してください。"
            "課題がない場合は相談内容の要点を簡潔に要約してください。"

            "answerには相談への回答を入れてください。"
            "相談にない情報を推測で補わないでください。"
        ),
        input=messages,
        text_format = AIResult,
        store=False,
    )

    result = response.output_parsed
    if result is None:
        raise ValueError("AIの回答が得られませんでした")
    return result

