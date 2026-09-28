"""
課題ダッシュボード（マネージャー支援AIプラットフォーム）
------------------------------------------------------
FEATURE 01「相談ログ分析」の画面①相当。
DB未接続のため、本ファイル単体で固定のサンプル数値を保持してUIを確認できるようにしている。
実装フェーズでは build_weekly_dataset() を database.py（chat_logs / extracted_issues）
からの読み込みに置き換えるだけで良い構成。

起動方法:
    pip install streamlit pandas plotly
    streamlit run dashboard_app.py
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils.service import get_supabase_client

# ----------------------------------------------------------------------------
# 定数・固定サンプルデータ
# ----------------------------------------------------------------------------

# ジャンル（大分類）。ユーザー提供のカテゴリマスタに準拠
CATEGORIES = [
    "技術検討",
    "人材・スキル",
    "他部署連携",
    "事業戦略",
    "予算・リソース配分",
]

CATEGORY_COLORS = {
    "技術検討": "#2b5f8a",
    "人材・スキル": "#3c7a5a",
    "他部署連携": "#a5771f",
    "事業戦略": "#6a5aa8",
    "予算・リソース配分": "#b5432e",
}

TREND_WEEKS = 8  # 傾向表示は8週分で固定

# ジャンル別の週次件数（固定値・古い週→新しい週の順、末尾が「今週」）
WEEKLY_COUNTS = {
    "技術検討":       [10, 11, 10, 12, 13, 12, 14, 15],
    "人材・スキル":    [9, 8, 8, 7, 7, 6, 6, 5],
    "他部署連携":     [9, 11, 10, 12, 11, 13, 12, 14],
    "事業戦略":       [5, 6, 5, 6, 7, 6, 7, 8],
    "予算・リソース配分": [9, 8, 10, 9, 9, 10, 10, 11],
}

# 課題（ジャンルとは独立した「別分類」。ユーザー提供のカテゴリマスタに準拠）
ISSUE_TYPES = [
    "手順がわからない",
    "判断基準が分からない",
    "エラー・障害",
    "誰に聞くか分からない",
    "情報が見つからない",
    "作業代行",
    "課題ではない",
]

# 課題別の週次件数（固定値・古い週→新しい週の順、末尾が「今週」）
WEEKLY_ISSUE_COUNTS = {
    "手順がわからない":       [7, 8, 8, 9, 10, 10, 11, 12],
    "判断基準が分からない":    [4, 4, 5, 5, 5, 6, 6, 6],
    "エラー・障害":          [5, 6, 6, 7, 7, 8, 8, 9],
    "誰に聞くか分からない":    [3, 3, 4, 4, 4, 5, 5, 5],
    "情報が見つからない":     [4, 5, 5, 6, 6, 6, 7, 7],
    "作業代行":             [2, 2, 3, 3, 3, 4, 4, 4],
    "課題ではない":          [2, 2, 2, 3, 3, 3, 3, 3],
}

ISSUE_COLORS = {
    "手順がわからない": "#2b5f8a",
    "判断基準が分からない": "#a5771f",
    "エラー・障害": "#b5432e",
    "誰に聞くか分からない": "#3c7a5a",
    "情報が見つからない": "#6a5aa8",
    "作業代行": "#c47eb0",
    "課題ではない": "#57666d",
}

# ジャンル × 課題 のクロス集計（固定値。ヒートマップ表示用）
CROSS_TAB_COUNTS = {
    "技術検討":       [6, 1, 0, 1, 1, 4, 1],
    "人材・スキル":    [1, 4, 0, 1, 0, 0, 2],
    "他部署連携":     [1, 0, 6, 1, 1, 0, 0],
    "事業戦略":       [1, 1, 0, 3, 1, 0, 0],
    "予算・リソース配分": [1, 0, 1, 0, 4, 0, 0],
}

# 折りたたみで見せる「具体的な課題」の例（固定サンプル。ジャンル×課題タグ付き）
CONCRETE_ISSUES = [
    {"genre": "技術検討", "issue_type": "手順がわからない", "detail": "新しい検証ツールの操作手順が分からず作業が止まっている"},
    {"genre": "技術検討", "issue_type": "作業代行", "detail": "負荷試験用スクリプトの作成を代わりにやってほしいという依頼"},
    {"genre": "人材・スキル", "issue_type": "判断基準が分からない", "detail": "評価面談での評点基準が人によって解釈が分かれている"},
    {"genre": "他部署連携", "issue_type": "エラー・障害", "detail": "他部署管理のシステムでエラーが頻発しているが問い合わせ窓口が分からない"},
    {"genre": "事業戦略", "issue_type": "誰に聞くか分からない", "detail": "新規事業の方針転換について誰に確認すればよいか分からない"},
    {"genre": "予算・リソース配分", "issue_type": "情報が見つからない", "detail": "予算申請に必要な過去実績データがどこにあるか分からない"},
]

# 今週トップの相談カテゴリに対する人材マッチング結果（固定値）
# 本番では matching_engine.py が hr_employees / performance_records と突合して算出する想定
CANDIDATES = [
    {
        "name": "中村 拓也",
        "feature": "AI・機械学習／データ分析が専門。関連プロジェクトへの相談対応実績が豊富で稼働にも余裕あり。",
        "manager": "佐藤 健一",
        "match_score": 0.91,
    },
    {
        "name": "吉田 真理",
        "feature": "大口顧客折衝・業界標準化交渉に強み。外部規格対応や部門間の渉外調整の経験が豊富。",
        "manager": "高橋 直子",
        "match_score": 0.84,
    },
    {
        "name": "鈴木 美咲",
        "feature": "サブスクリプションモデル設計・顧客共創のリード経験あり。新規事業側の事情にも明るい。",
        "manager": "山本 修",
        "match_score": 0.78,
    },
]

# AIアドバイザーからの回答例（固定値）
AI_ADVISOR = {
    "query": "技術検討まわりの相談が今週最多です。対応を加速するための増員候補は？",
    "response": (
        "直近1週間で「技術検討」カテゴリの相談が最多となっています。"
        "手順が分からない・作業を代行してほしいという相談が中心とみられるため、"
        "まずは技術検討に知見のある候補者を暫定支援に充てることを提案します。"
        "中村さんはAI・機械学習側からの技術サポートが可能、吉田さんは外部との"
        "折衝が絡む論点の整理に貢献できます。"
    ),
}


@st.cache_data
def build_weekly_dataset():
    """
    固定のサンプル数値から、週開始日つきの集計テーブルを組み立てる。
    本番では database.py 経由で extracted_issues
    （year_month / topic_category / mention_count）を集計してこの形にする想定。
    """
    today = pd.Timestamp.today().normalize()
    this_week_start = today - pd.Timedelta(days=today.weekday())
    week_starts = [this_week_start - pd.Timedelta(weeks=(TREND_WEEKS - 1 - i)) for i in range(TREND_WEEKS)]

    weekly_pivot = pd.DataFrame(WEEKLY_COUNTS, index=week_starts).reindex(columns=CATEGORIES, fill_value=0)
    weekly_issue_pivot = pd.DataFrame(WEEKLY_ISSUE_COUNTS, index=week_starts).reindex(columns=ISSUE_TYPES, fill_value=0)
    return weekly_pivot, weekly_issue_pivot, this_week_start


def week_bounds(start: pd.Timestamp):
    return start, start + pd.Timedelta(days=6)

# ----------------------------------------------------------------------------
# Supabase接続
# ----------------------------------------------------------------------------

supabase = get_supabase_client()

# ----------------------------------------------------------------------------
# ページ設定
# ----------------------------------------------------------------------------

st.set_page_config(page_title="課題ダッシュボード", page_icon="📊", layout="wide")

st.title("📊 課題ダッシュボード")
st.caption(
    "相談ログ分析（FEATURE 01）｜個人・部署の粒度は表示せず、カテゴリ単位で集計。"
    "現在は **固定のサンプル数値** で表示中（DB未接続 / フロント確認用）。"
)

weekly_pivot, weekly_issue_pivot, this_week_start = build_weekly_dataset()
this_week_end = week_bounds(this_week_start)[1]
last_week_start = this_week_start - pd.Timedelta(weeks=1)
last_week_end = week_bounds(last_week_start)[1]

this_week_counts = weekly_pivot.loc[this_week_start]
last_week_counts = weekly_pivot.loc[last_week_start]
this_week_issue_counts = weekly_issue_pivot.loc[this_week_start]

# ----------------------------------------------------------------------------
# KPIサマリー
# ----------------------------------------------------------------------------

total_this_week = int(this_week_counts.sum())
total_last_week = int(last_week_counts.sum())
delta_total = total_this_week - total_last_week

top_category_this_week = this_week_counts.idxmax()

col1, col2= st.columns(2)
col1.metric("今週の相談件数", f"{total_this_week} 件", delta=f"{delta_total:+d} 件（前週比）")
col2.metric("最多カテゴリ", top_category_this_week)

st.caption(
    f"対象週: {this_week_start.strftime('%Y-%m-%d')} 〜 {this_week_end.strftime('%Y-%m-%d')}"
    f"（前週: {last_week_start.strftime('%Y-%m-%d')} 〜 {last_week_end.strftime('%Y-%m-%d')}）"
)

st.divider()

# ----------------------------------------------------------------------------
# セクション1・2: 今週のカテゴリまとめ / これまでのトレンド（横並び）
# ----------------------------------------------------------------------------

sec1, sec2 = st.columns(2)

with sec1:
    st.subheader("① 今週のカテゴリまとめ")

    bar_left, bar_right = st.columns(2)

    with bar_left:
        st.caption("ジャンル別")
        week_counts = this_week_counts.reset_index()
        week_counts.columns = ["category", "count"]

        fig_bar = px.bar(
            week_counts.sort_values("count", ascending=True),
            x="count",
            y="category",
            orientation="h",
            color="category",
            color_discrete_map=CATEGORY_COLORS,
            text="count",
        )
        fig_bar.update_layout(
            showlegend=False,
            xaxis_title="件数",
            yaxis_title="",
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True)

    with bar_right:
        st.caption("課題別（別分類）")
        issue_counts_df = (
            pd.DataFrame({"count": this_week_issue_counts})
            .reindex(ISSUE_TYPES)
            .reset_index()
        )
        issue_counts_df.columns = ["issue", "count"]

        fig_issue = px.bar(
            issue_counts_df.sort_values("count", ascending=True),
            x="count",
            y="issue",
            orientation="h",
            text="count",
        )
        fig_issue.update_traces(marker_color="#57666d", textposition="outside")
        fig_issue.update_layout(
            xaxis_title="件数",
            yaxis_title="",
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_issue, use_container_width=True)

    st.caption("ジャンル × 課題（件数が多いマスほど濃い色）")
    cross_tab = pd.DataFrame(CROSS_TAB_COUNTS, index=ISSUE_TYPES).T.reindex(CATEGORIES)

    fig_heatmap = px.imshow(
        cross_tab,
        labels=dict(x="課題", y="ジャンル", color="件数"),
        x=ISSUE_TYPES,
        y=CATEGORIES,
        color_continuous_scale="Blues",
        text_auto=True,
        aspect="auto",
    )
    fig_heatmap.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)

with sec2:
    st.subheader(f"② これまでのトレンド（直近{TREND_WEEKS}週）")

    st.caption("ジャンル別")
    fig_trend = go.Figure()
    for cat in CATEGORIES:
        fig_trend.add_trace(
            go.Scatter(
                x=weekly_pivot.index,
                y=weekly_pivot[cat],
                mode="lines+markers",
                name=cat,
                line=dict(color=CATEGORY_COLORS[cat], width=2),
            )
        )
    fig_trend.update_layout(
        xaxis_title="週（開始日）",
        yaxis_title="件数",
        height=280,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    st.caption("課題別（別分類）")
    fig_trend_issue = go.Figure()
    for issue in ISSUE_TYPES:
        fig_trend_issue.add_trace(
            go.Scatter(
                x=weekly_issue_pivot.index,
                y=weekly_issue_pivot[issue],
                mode="lines+markers",
                name=issue,
                line=dict(color=ISSUE_COLORS[issue], width=2),
            )
        )
    fig_trend_issue.update_layout(
        xaxis_title="週（開始日）",
        yaxis_title="件数",
        height=280,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_trend_issue, use_container_width=True)

st.divider()

# ----------------------------------------------------------------------------
# 今週上がっている課題の詳細（折りたたみ）
# ----------------------------------------------------------------------------

with st.expander("📂 具体的な課題を見る"):
    st.caption("相談ログから抽出された、ジャンル・課題タグ付きの具体例（固定サンプル）")
    for item in CONCRETE_ISSUES:
        st.markdown(f"- **[{item['genre']} / {item['issue_type']}]** {item['detail']}")

st.divider()

# ----------------------------------------------------------------------------
# セクション3: 人材マッチング
# ----------------------------------------------------------------------------

st.subheader("③ 人材マッチング")
st.caption(f"今週最多カテゴリ「{top_category_this_week}」の課題に対する暫定支援候補（固定サンプル）")

for person in CANDIDATES:
    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown(f"**{person['name']}**")
            st.caption(f"上司: {person['manager']}")
            st.caption(f"マッチ度 {person['match_score']:.2f}")
        with c2:
            st.write(person["feature"])

st.divider()

# ----------------------------------------------------------------------------
# セクション4: AIアドバイザーの回答
# ----------------------------------------------------------------------------

st.subheader("④ AIアドバイザーの回答")

with st.chat_message("assistant"):
    st.caption(f"Q. {AI_ADVISOR['query']}")
    st.write(AI_ADVISOR["response"])

st.caption(
    "※ 表示データはすべて固定のサンプル数値です。DB接続後は extracted_issues /"
    " hr_employees / recommendations テーブルからの集計・生成AI応答に差し替えます。"
)

# ----------------------------------------------------------------------------
# chat_logs テーブル接続・データ取得テスト
# ----------------------------------------------------------------------------
st.divider()
st.subheader("💬 Supabase: `chat_logs` データ取得テスト")

if st.button("`chat_logs` の最新データを取得"):
    try:
        # chat_logs から最新 10 件を取得
        response = (
            supabase.table("chat_logs")
            .select("*")
            .order("log_id", desc=True)  # ※日時カラム名が created_at の場合
            .limit(10)
            .execute()
        )
        
        data = response.data
        if data:
            st.success(f"✅ `chat_logs` から {len(data)} 件のログを取得しました！")
            
            # DataFrame化してテーブル表示
            df_chat = pd.DataFrame(data)
            st.dataframe(df_chat, use_container_width=True)
        else:
            st.info("ℹ️ テーブルは存在しますが、データが 0 件です。")

    except Exception as e:
        st.error(f"❌ データ取得エラー: {e}")
        st.caption("※ テーブル名が異なる場合や、RLS (Row Level Security) のアクセス制限がかかっている可能性があります。")