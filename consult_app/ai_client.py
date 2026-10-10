"""OpenAI Responses API との通信。"""

import os

from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, create_model


def build_result_model(category_1_values: list[str], category_2_values: list[str]) -> type[BaseModel]:
    """AIが返す形式を作る。ジャンル・困りごとの選択肢は、DBのマスタから渡された値だけにする。"""
    return create_model(
        "AIResult",
        category_1=(Optional[Literal[tuple(category_1_values)]], ...),
        category_2=(Literal[tuple(category_2_values)], ...),
        issue_summary=(str, ...),
        answer=(str, ...),
    )


def ask_ai(
    messages: list[dict[str, str]], category_1_values: list[str], category_2_values: list[str]
) -> BaseModel:
    """マスキング済み会話を渡し、回答文を返す。"""
    AIResult = build_result_model(category_1_values, category_2_values)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # 毎回履歴を渡すのでサーバー側の会話保存には依存しない。
    response = OpenAI(timeout=30.0, max_retries=1).responses.parse(
        model=model,
        #プロンプト部分
         instructions="""
            あなたは総合化学メーカーの社員向け相談AIです。
            社員の業務・学習・職場に関する相談に、日本語で簡潔に回答してください。
            分類結果は、相談ログから組織の課題傾向を把握し、
            関連する社内知識や詳しい人を探すために使います。

            【分類の基本】
            最新のユーザー発言を中心に分類してください。
            短い続きの発言なら、過去の会話を使って意味を補ってください。
            category_1は「相談の主なテーマ」、
            category_2は「今、何に困り、どのような支援を求めているか」です。
            部署名や「会議の準備」「納期が近い」などの付随情報だけで分類しないでください。
            複数の要素がある場合は、ユーザーが最も解決したいことを選んでください。

            【category_1：相談の主なテーマ】
            ・技術検討：樹脂、フィルム、繊維、材料の配合・物性・加工・評価、
            品質上の現象、代替材料や技術的な規制対応。
            ・人材・スキル：教育、OJT、専門知識の習得、技術継承、育成。
            ・他部署連携：部門間の役割分担・引き継ぎ・情報共有、
            他部署の担当者や専門家を探すこと自体が主な目的の場合。
            ・事業戦略：顧客提案、市場参入、新用途、新商品、販売方針。
            ・予算・リソース配分：費用、設備、人員の確保・配分・優先順位。
            ・働き方・職場環境：働き方、職場の人間関係、孤独感や心理的負担。
            テーマを判断する情報が足りない場合はnullにしてください。
            単に別部署が話に登場しただけなら「他部署連携」にはしません。

            【category_2：求めている支援】
            ・手順がわからない：方法、使い方、進め方を知りたい。
            ・判断基準が分からない：複数案の選択、評価基準、優先順位に迷う。
            ・エラー・障害：システムのエラーや、試験・製造で実際に起きた
            不具合、物性低下、ばらつきの原因と対策を知りたい。
            部門間の調整遅れだけを「エラー・障害」にしない。
            ・誰に聞くか分からない：適切な担当部署・担当者・専門家を探したい。
            ・情報が見つからない：既存の資料、過去案件、事例、データ、
            材料候補などを探したい。
            ・作業代行：文書の作成、要約、集計など、具体的な成果物を作ってほしい。
            ・悩み・不安：本人の不安、孤独感、心理的負担が相談の中心にある。
            納期への焦りが添えられているだけなら、主な依頼に沿って分類する。
            ・課題ではない：挨拶、雑談、業務上の支援を伴わない一般的な事実確認。
            仕事上の方法・判断・情報・人探し・不具合・作業依頼、
            または本人の不安があれば「課題ではない」にしないでください。

            【分類例】
            「再生PETを混ぜると強度が落ちる。原因を知りたい」
            → 技術検討／エラー・障害
            「難燃性とリサイクル性を両立した過去案件が見つからない」
            → 技術検討／情報が見つからない
            「PFAS代替に詳しい他部署の人を知りたい」
            → 他部署連携／誰に聞くか分からない
            「在宅勤務が続き、孤独感がつらい」
            → 働き方・職場環境／悩み・不安
            「この議事録を要約して」
            → テーマが不明ならcategory_1はnull／category_2は作業代行

            issue_summaryには、対象となる材料・用途・現象や、
            何を解決したいかを1～2文で具体的に書いてください。
            相談にない事実を補わないでください。
            answerには相談への回答を書き、不確かなことは断定しないでください。
            社内資料や社員情報が与えられていなければ、
            実在する過去案件や担当者を知っているかのように答えないでください。
            """,
        input=messages,
        text_format = AIResult,
        store=False,
    )

    result = response.output_parsed
    if result is None:
        raise ValueError("AIの回答が得られませんでした")
    return result

