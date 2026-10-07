"""
課題ダッシュボード（マネージャー支援AIプラットフォーム）
------------------------------------------------------
Supabase の chat_logs テーブルを実データソースとして使用する。

起動方法:
    pip install streamlit pandas plotly openai supabase
    # OpenAI APIを使う場合は下記のいずれかでキーを設定（未設定ならフォールバック固定回答）
    #   export OPENAI_API_KEY="sk-..."
    #   または .streamlit/secrets.toml に OPENAI_API_KEY = "sk-..." を記載
    streamlit run app.py
"""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.service import get_supabase_client

try:
    from openai import OpenAI  # openai>=1.0 系のクライアント
except ImportError:  # ライブラリ未インストールでも画面自体は落とさない
    OpenAI = None

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ----------------------------------------------------------------------------
# ページ設定（Streamlitコマンドの中で一番最初に呼ぶ必要がある）
# ----------------------------------------------------------------------------

st.set_page_config(page_title="課題ダッシュボード", page_icon="📊", layout="wide")

st.title("📊 課題ダッシュボード")
st.caption("相談ログ分析（FEATURE 01）｜個人・部署の粒度は表示せず、カテゴリ単位で集計。")

# サイドバーの自動ページ一覧（ナビゲーション）を隠すCSS
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    if st.button("せーせーAI-分からん事相談してミーナに戻る", use_container_width=True):
        st.switch_page("app_aichat.py")

# ----------------------------------------------------------------------------
# 定数
# ----------------------------------------------------------------------------

# ジャンル（大分類）= chat_logs.category_1
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

# 課題（別分類）= chat_logs.category_2
ISSUE_TYPES = [
    "手順がわからない",
    "判断基準が分からない",
    "エラー・障害",
    "誰に聞くか分からない",
    "情報が見つからない",
    "作業代行",
    "課題ではない",
]

ISSUE_COLORS = {
    "手順がわからない": "#2b5f8a",
    "判断基準が分からない": "#a5771f",
    "エラー・障害": "#b5432e",
    "誰に聞くか分からない": "#3c7a5a",
    "情報が見つからない": "#6a5aa8",
    "作業代行": "#c47eb0",
    "課題ではない": "#57666d",
}

# 「今週」の基準。
# True : chat_logs 内で最新のログがある週を「今週」とする（サンプルデータが過去日付のため）
# False: 実行日の週を「今週」とする（本番運用向け）
ANCHOR_TO_LATEST_DATA = True

TABLE_NAME = "chat_logs"
PAGE_SIZE = 1000  # Supabaseの1リクエストあたり取得上限

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

# AIアドバイザーに渡す固定プロンプト（ユーザーが質問を入力するのではなく、
# 集計結果そのものを根拠に自動でアドバイスを生成させる）
ADVISOR_PROMPT = (
    "①②の今週の集計結果（ジャンル別・課題別の件数と前週比、具体的な課題の例、"
    "支援候補となる社員）を踏まえて、マネージャーが今週取るべきアクションを"
    "提案してください。特にどのジャンル・課題への対応を優先すべきか、"
    "誰にどう動いてもらうと良いかを具体的に述べてください。"
)

# APIキー未設定時のフォールバック回答（固定値）
AI_ADVISOR = {
    "response": (
        "［フォールバック回答／OpenAI APIキー未設定］ "
        "直近1週間で「技術検討」カテゴリの相談が最多となっています。"
        "手順が分からない・作業を代行してほしいという相談が中心とみられるため、"
        "まずは技術検討に知見のある候補者を暫定支援に充てることを提案します。"
        "中村さんはAI・機械学習側からの技術サポートが可能、吉田さんは外部との"
        "折衝が絡む論点の整理に貢献できます。"
    ),
}


# ----------------------------------------------------------------------------
# Supabaseからのデータ取得・集計
# ----------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="Supabaseからデータを取得中...")
def load_chat_logs() -> pd.DataFrame:
    """chat_logs を全件取得（1000件超でも取りこぼさないようページングする）。"""
    client = get_supabase_client()
    rows, start = [], 0
    while True:
        res = (
            client.table(TABLE_NAME)
            .select("log_id, timestamp, category_1, category_2, issue_summary")
            .order("timestamp")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    df = pd.DataFrame(rows, columns=["log_id", "timestamp", "category_1", "category_2", "issue_summary"])
    if df.empty:
        return df

    # text型（"2025/7/3 9:15"）でも timestamptz でも読めるようにする
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    df["timestamp"] = ts
    df = df.dropna(subset=["timestamp"])

    # 週開始日（月曜）
    df["week_start"] = df["timestamp"].dt.normalize() - pd.to_timedelta(
        df["timestamp"].dt.weekday, unit="D"
    )
    return df


def build_weekly_dataset(df: pd.DataFrame):
    """
    ログから週次のピボット（行=週開始日、列=ジャンル/課題）を作る。
    ログが0件の週も 0 で埋めて、直近 TREND_WEEKS 週ぶんを返す。
    """
    if ANCHOR_TO_LATEST_DATA:
        this_week_start = df["week_start"].max()
    else:
        today = pd.Timestamp.today().normalize()
        this_week_start = today - pd.Timedelta(days=today.weekday())

    week_starts = [
        this_week_start - pd.Timedelta(weeks=(TREND_WEEKS - 1 - i))
        for i in range(TREND_WEEKS)
    ]

    def pivot(col, order):
        p = (
            df.groupby(["week_start", col]).size().unstack(fill_value=0)
            .reindex(index=week_starts, columns=order, fill_value=0)
        )
        p.index.name = None
        return p

    weekly_pivot = pivot("category_1", CATEGORIES)
    weekly_issue_pivot = pivot("category_2", ISSUE_TYPES)

    # 今週のジャンル × 課題 クロス集計（ヒートマップ用）
    this_week_df = df[df["week_start"] == this_week_start]
    cross_tab = (
        pd.crosstab(this_week_df["category_1"], this_week_df["category_2"])
        .reindex(index=CATEGORIES, columns=ISSUE_TYPES, fill_value=0)
    )
    return weekly_pivot, weekly_issue_pivot, cross_tab, this_week_start


def week_bounds(start: pd.Timestamp):
    return start, start + pd.Timedelta(days=6)


def build_advisor_context(this_week_logs: pd.DataFrame) -> str:
    """
    「相談ログ（chat_logs）データ」から AI アドバイザーに渡す文脈をテキスト化する。
    件数集計に加え、今週の生ログから具体例を抜粋して根拠として渡す。
    """
    genre_lines = "\n".join(
        f"- {cat}: {int(this_week_counts[cat])}件（前週比 {int(this_week_counts[cat] - last_week_counts[cat]):+d}）"
        for cat in CATEGORIES
    )
    issue_lines = "\n".join(
        f"- {issue}: {int(this_week_issue_counts[issue])}件" for issue in ISSUE_TYPES
    )

    sample_logs = this_week_logs.dropna(subset=["issue_summary"]).head(15)
    concrete_lines = "\n".join(
        f"- [{row['category_1']} / {row['category_2']}] {row['issue_summary']}"
        for _, row in sample_logs.iterrows()
    ) or "- （該当ログなし）"

    candidate_lines = "\n".join(
        f"- {c['name']}（上司: {c['manager']}）: {c['feature']}" for c in CANDIDATES
    )

    return (
        "■ 今週のジャンル別相談件数\n"
        f"{genre_lines}\n\n"
        "■ 今週の課題別件数（ジャンルとは別分類）\n"
        f"{issue_lines}\n\n"
        "■ 相談ログからの具体的な課題例（抜粋）\n"
        f"{concrete_lines}\n\n"
        "■ 支援候補となる社員\n"
        f"{candidate_lines}"
    )


def generate_advisor_response(context: str) -> str:
    """
    相談ログの集計データ（context）だけを根拠に、OpenAI API に
    マネージャー向けアドバイスを自動生成させる。ユーザーからの質問入力は受け付けず、
    集計結果に基づく提案をそのまま生成する。APIキー未設定・呼び出し失敗時は
    固定のフォールバック回答を返す。
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("OPENAI_API_KEY")
        except Exception:
            api_key = None

    if not OpenAI or not api_key:
        return AI_ADVISOR["response"]

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたは社内のマネージャー支援AIアドバイザーです。"
                        "以下の相談ログの集計データ・具体例・候補者情報だけを根拠に、"
                        "簡潔で実行可能な助言を日本語で200字程度で回答してください。"
                        "データにない人名や数値を創作しないでください。\n\n"
                        f"{context}"
                    ),
                },
                {"role": "user", "content": ADVISOR_PROMPT},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:  # APIエラー時も画面を落とさずフォールバック
        st.error(f"OpenAI APIの呼び出しに失敗しました（{e}）。フォールバック回答を表示します。")
        return AI_ADVISOR["response"]


# ----------------------------------------------------------------------------
# データ取得
# ----------------------------------------------------------------------------

try:
    logs_df = load_chat_logs()
except Exception as e:
    st.error(f"Supabaseからのデータ取得に失敗しました: {e}")
    st.stop()

if logs_df.empty:
    st.warning("chat_logs にデータがありません。")
    st.stop()

weekly_pivot, weekly_issue_pivot, cross_tab, this_week_start = build_weekly_dataset(logs_df)
this_week_end = week_bounds(this_week_start)[1]
last_week_start = this_week_start - pd.Timedelta(weeks=1)
last_week_end = week_bounds(last_week_start)[1]

this_week_counts = weekly_pivot.loc[this_week_start]
last_week_counts = weekly_pivot.loc[last_week_start]
this_week_issue_counts = weekly_issue_pivot.loc[this_week_start]
this_week_logs = logs_df[logs_df["week_start"] == this_week_start]

# ----------------------------------------------------------------------------
# KPIサマリー
# ----------------------------------------------------------------------------

total_this_week = int(this_week_counts.sum())
total_last_week = int(last_week_counts.sum())
delta_total = total_this_week - total_last_week

top_category_this_week = this_week_counts.idxmax()

col1, col2 = st.columns(2)
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
# 具体的な課題の一覧（折りたたみ）。個人・部署の情報は出さない
# ----------------------------------------------------------------------------

with st.expander(f"具体的な課題を見る（今週 {len(this_week_logs)} 件）"):
    f1, f2 = st.columns(2)
    sel_genres = f1.multiselect("ジャンルで絞り込み", CATEGORIES, key="issue_list_genre")
    sel_issues = f2.multiselect("課題で絞り込み", ISSUE_TYPES, key="issue_list_issue")

    view_df = this_week_logs
    if sel_genres:
        view_df = view_df[view_df["category_1"].isin(sel_genres)]
    if sel_issues:
        view_df = view_df[view_df["category_2"].isin(sel_issues)]

    if view_df.empty:
        st.info("該当する課題はありません。")
    else:
        st.dataframe(
            view_df.sort_values("timestamp", ascending=False)[
                ["timestamp", "category_1", "category_2", "issue_summary"]
            ].rename(columns={
                "timestamp": "日時",
                "category_1": "ジャンル",
                "category_2": "課題",
                "issue_summary": "内容",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={"日時": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
        )

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
st.caption(
    "①②の相談ログ集計データ（ジャンル別・課題別件数、具体例、候補者情報）を根拠に、"
    "OpenAI API が今週取るべきアクションを自動で提案します。"
    "OPENAI_API_KEY が未設定の場合はフォールバックの固定回答を表示します。"
)

if "advisor_response" not in st.session_state:
    st.session_state["advisor_response"] = AI_ADVISOR["response"]

if st.button("🤖 今週の結果からAIアドバイスを生成"):
    with st.spinner("AIアドバイザーが今週の結果を分析しています..."):
        context = build_advisor_context(this_week_logs)
        st.session_state["advisor_response"] = generate_advisor_response(context)

with st.chat_message("assistant"):
    st.write(st.session_state["advisor_response"])

st.caption(
    "※ ジャンル・課題の集計は Supabase `chat_logs` テーブルの実データです。"
    "人材マッチング候補のみ固定サンプルです。"
)