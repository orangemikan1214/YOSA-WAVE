"""
課題ダッシュボード（マネージャー支援AIプラットフォーム）
------------------------------------------------------
Supabase の chat_logs テーブルを実データソースとして使用する。

起動方法（このファイルがあるフォルダで）:
    pip install -r requirements.txt
    # .env.example を .env にコピーし、SUPABASE_URL / SUPABASE_KEY（公開キーのみ）/ OPENAI_API_KEY を設定する
    # OPENAI_API_KEY が未設定なら、AIアドバイスは今週のデータから作る簡易文にフォールバックする
    streamlit run app.py

社員が使う相談AIは別アプリ: streamlit run consult_app/app.py
"""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from matching_engine import match_employees, to_ui_list
from utils.auth import require_manager_login
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

# デモ用の簡易ログイン。マネージャー以外にはダッシュボードを見せない（Supabase側の保護は別途）
require_manager_login()

st.title("📊 課題ダッシュボード")
st.caption("相談ログ分析（FEATURE 01）｜個人・部署の粒度は表示せず、カテゴリ単位で集計。「課題ではない」と判定された相談は集計に含めない。")

# ----------------------------------------------------------------------------
# 定数
# ----------------------------------------------------------------------------

# ジャンル（category_1）・課題（category_2）の一覧は、Supabase のマスタ
# （category1_master / category2_master）から読む。マスタに分類が増えても、このコードを直さずに集計へ反映される。
UNCLASSIFIED = "未分類"  # category_1 が空のログの表示名
EXCLUDED_ISSUE_TYPE = "課題ではない"  # この困りごとのログは、集計・一覧・AIアドバイスのすべてから除外する

CATEGORIES: list[str] = []   # データ取得後に、マスタ + UNCLASSIFIED で埋める
ISSUE_TYPES: list[str] = []  # データ取得後に、マスタで埋める
CATEGORY_COLORS: dict[str, str] = {}
ISSUE_COLORS: dict[str, str] = {}

TREND_WEEKS = 8  # 傾向表示は8週分で固定

# 色は従来の分類に固定で割り当て、マスタに増えた分類は予備の色を順に割り当てる
KNOWN_CATEGORY_COLORS = {
    "技術検討": "#2b5f8a",
    "人材・スキル": "#3c7a5a",
    "他部署連携": "#a5771f",
    "事業戦略": "#6a5aa8",
    "予算・リソース配分": "#b5432e",
    UNCLASSIFIED: "#8a9ba3",
}
KNOWN_ISSUE_COLORS = {
    "手順がわからない": "#2b5f8a",
    "判断基準が分からない": "#a5771f",
    "エラー・障害": "#b5432e",
    "誰に聞くか分からない": "#3c7a5a",
    "情報が見つからない": "#6a5aa8",
    "作業代行": "#c47eb0",
}
EXTRA_COLORS = ["#0f766e", "#c2410c", "#3d5a80", "#9a3f6b", "#8a6d3b", "#4b7f52"]


def assign_colors(names: list[str], known: dict[str, str]) -> dict[str, str]:
    colors, spare = {}, 0
    for name in names:
        if name in known:
            colors[name] = known[name]
        else:
            colors[name] = EXTRA_COLORS[spare % len(EXTRA_COLORS)]
            spare += 1
    return colors


# 「今週」の基準。
# True : chat_logs 内で最新のログがある週を「今週」とする（サンプルデータが過去日付のため）
# False: 実行日の週を「今週」とする（本番運用向け）
ANCHOR_TO_LATEST_DATA = True

TABLE_NAME = "chat_logs"
PAGE_SIZE = 1000  # Supabaseの1リクエストあたり取得上限

# 人材マッチングの設定。候補者は matching_engine.py が Supabase の社員・スキル・業績データから算出する
MATCH_TOP_N = 3         # 表示する候補者の人数
MATCH_SAMPLE_LOGS = 10  # 課題文として渡す、今週の相談要約の件数（新しい順）
CANDIDATES: list[dict] = []  # ③で算出する。④のAIアドバイスの根拠にも使う

# AIアドバイザーに渡す固定プロンプト（ユーザーが質問を入力するのではなく、
# 集計結果そのものを根拠に自動でアドバイスを生成させる）
ADVISOR_PROMPT = (
    "①②の今週の集計結果（ジャンル別・課題別の件数と前週比、具体的な課題の例、"
    "支援候補となる社員）を踏まえて、マネージャーが今週取るべきアクションを"
    "提案してください。特にどのジャンル・課題への対応を優先すべきか、"
    "誰にどう動いてもらうと良いかを具体的に述べてください。"
)

# APIキー未設定・API呼び出し失敗時のフォールバック回答。固定文ではなく、今週のデータから組み立てる
def fallback_response() -> str:
    names = "、".join(c["name"] for c in CANDIDATES) or "（該当する候補者なし）"
    return (
        f"［フォールバック回答／AIは未使用］ 今週は「{top_category_this_week}」の相談が最多"
        f"（{int(this_week_counts[top_category_this_week])}件）です。"
        f"まず対応できる候補者（{names}）に、暫定的な支援を相談することを検討してください。"
        "「🤖 今週の結果からAIアドバイスを生成」を押すと、AIがより具体的な提案を作ります。"
    )


# ----------------------------------------------------------------------------
# Supabaseからのデータ取得・集計
# ----------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def load_masters() -> tuple[list[str], list[str]]:
    """ジャンル（category_1）と課題（category_2）の一覧をマスタテーブルから取得する。"""
    client = get_supabase_client()
    category_1 = [r["category_1"] for r in client.table("category1_master").select("category_1").execute().data or []]
    category_2 = [r["category_2"] for r in client.table("category2_master").select("category_2").execute().data or []]
    return category_1, category_2


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

    df = df[df["category_2"] != EXCLUDED_ISSUE_TYPE].copy()
    df["category_1"] = df["category_1"].fillna(UNCLASSIFIED)

    # timestamptz は「秒まで」と「小数秒つき」が混在する（ダミーデータと、相談画面から保存した分）。
    # pandas は最初の行の形式で全体を読むため、format="ISO8601" を指定して両方を読めるようにする。
    ts = pd.to_datetime(df["timestamp"], errors="coerce", format="ISO8601", utc=True)
    ts = ts.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    df["timestamp"] = ts
    df.attrs["unparsed_rows"] = int(ts.isna().sum())  # 日時を読めずに除外した件数（画面に警告を出す）
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
        f"- {c['name']}（上司: {c['manager']}）: {c['feature']}（{c['availability']}）" for c in CANDIDATES
    ) or "- （該当する候補者なし）"

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
        return fallback_response()

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
        return fallback_response()


# ----------------------------------------------------------------------------
# データ取得
# ----------------------------------------------------------------------------

try:
    master_category_1, master_category_2 = load_masters()
    CATEGORIES = master_category_1 + [UNCLASSIFIED]
    ISSUE_TYPES = [t for t in master_category_2 if t != EXCLUDED_ISSUE_TYPE]
    CATEGORY_COLORS = assign_colors(CATEGORIES, KNOWN_CATEGORY_COLORS)
    ISSUE_COLORS = assign_colors(ISSUE_TYPES, KNOWN_ISSUE_COLORS)
    logs_df = load_chat_logs()
except Exception as e:
    st.error(f"Supabaseからのデータ取得に失敗しました: {e}")
    st.stop()

if logs_df.empty:
    st.warning("chat_logs にデータがありません。")
    st.stop()

if logs_df.attrs.get("unparsed_rows"):
    st.warning(f"日時を読み取れない相談ログが {logs_df.attrs['unparsed_rows']} 件あり、集計から除外しています。")

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

top_category_this_week = this_week_counts.drop(labels=[UNCLASSIFIED], errors="ignore").idxmax()

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
        st.plotly_chart(fig_bar, width="stretch")

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
        st.plotly_chart(fig_issue, width="stretch")

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
    st.plotly_chart(fig_heatmap, width="stretch")

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
    st.plotly_chart(fig_trend, width="stretch")

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
    st.plotly_chart(fig_trend_issue, width="stretch")

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
            width="stretch",
            hide_index=True,
            column_config={"日時": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
        )

st.divider()

# ----------------------------------------------------------------------------
# セクション3: 人材マッチング
# ----------------------------------------------------------------------------

st.subheader("③ 人材マッチング")

# 今週の最多ジャンルの相談要約（新しい順）を課題文として渡し、対応できる社員を探す
top_logs = this_week_logs[this_week_logs["category_1"] == top_category_this_week]
issue_text = "。".join(
    top_logs.sort_values("timestamp", ascending=False)["issue_summary"].dropna().head(MATCH_SAMPLE_LOGS)
)
try:
    CANDIDATES = to_ui_list(match_employees(category_1=top_category_this_week, issue_text=issue_text, top_n=MATCH_TOP_N))
except Exception as e:
    st.error(f"人材マッチングの実行に失敗しました: {e}")

st.caption(
    f"今週最多カテゴリ「{top_category_this_week}」の相談（{len(top_logs)}件）に対する支援候補。"
    "スキル・業績から算出し、稼働状況は点数に含めず参考として表示します。"
)

if not CANDIDATES:
    st.info("該当する候補者が見つかりませんでした。")

for person in CANDIDATES:
    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown(f"**{person['name']}**")
            st.caption(f"上司: {person['manager']}")
            st.caption(f"マッチ度 {person['match_score']:.2f}")
            st.caption(f"稼働: {person['availability']}")
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
    st.session_state["advisor_response"] = fallback_response()

if st.button("🤖 今週の結果からAIアドバイスを生成"):
    with st.spinner("AIアドバイザーが今週の結果を分析しています..."):
        context = build_advisor_context(this_week_logs)
        st.session_state["advisor_response"] = generate_advisor_response(context)

with st.chat_message("assistant"):
    st.write(st.session_state["advisor_response"])

st.caption(
    "※ ジャンル・課題の集計は Supabase `chat_logs` テーブルの実データです。"
    "人材マッチング候補は matching_engine.py が社員・スキル・業績データから算出しています。"
)