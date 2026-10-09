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
from collections import Counter
from datetime import timedelta

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
MATCH_TOP_N = 20         # 表示する候補者の最大人数
MATCH_SAMPLE_LOGS = 10   # 課題文として渡す、似た相談の要約の最大件数（新しい順）
MATCH_DEFAULT_DAYS = 28  # 課題を選ぶ期間の初期値（最新の相談から遡る日数）
GROUP_SIMILARITY = 0.5   # 似た相談を1項目にまとめる類似度（文字N-gramのTF-IDFコサイン。大きいほど厳しい）
ALL_GENRES = "（すべて）"
CANDIDATES: list[dict] = []  # ③で算出する。④のAIアドバイスの根拠にも使う
SELECTED_ISSUE: dict | None = None  # ③でマネージャーが選んだ課題（似た相談をまとめた1項目）。未選択ならNone

# AIアドバイザーに渡す固定プロンプト（ユーザーが質問を入力するのではなく、
# ③で選んだ課題と集計結果そのものを根拠に自動でアドバイスを生成させる）
ADVISOR_PROMPT = (
    "マネージャーが③で選んだ課題について、①②の今週の集計結果（ジャンル別・課題別の件数と前週比、"
    "具体的な課題の例）と、支援候補となる社員を踏まえて、マネージャーが取るべきアクションを"
    "提案してください。この課題への具体的な対応と、誰にどう動いてもらうと良いかを述べてください。"
)

# APIキー未設定・API呼び出し失敗時のフォールバック回答。固定文ではなく、選んだ課題と候補者から組み立てる
def fallback_response() -> str:
    if SELECTED_ISSUE is None:
        return "［AIは未使用］③で課題を選ぶと、その課題に対するアドバイスを生成できます。"
    names = "、".join(c["name"] for c in CANDIDATES[:3]) or "（該当する候補者なし）"
    return (
        f"［フォールバック回答／AIは未使用］ 選んだ課題「{SELECTED_ISSUE['rep']}」"
        f"（類似{SELECTED_ISSUE['count']}件）について、まず対応できる候補者（{names}）に、"
        "暫定的な支援を相談することを検討してください。"
        "「🤖 選んだ課題についてAIアドバイスを生成」を押すと、AIがより具体的な提案を作ります。"
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
            .select("log_id, employee_id, timestamp, category_1, category_2, issue_summary")
            .order("timestamp")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    df = pd.DataFrame(rows, columns=["log_id", "employee_id", "timestamp", "category_1", "category_2", "issue_summary"])
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


def group_similar_issues(df: pd.DataFrame) -> list[dict]:
    """
    似た相談（issue_summary）を1項目にまとめる。文字N-gramのTF-IDFコサイン類似度が GROUP_SIMILARITY 以上なら同じ項目。
    各項目: id(最新ログのlog_id) / rep(代表=最新の要約) / summaries(新しい順) / count / category_1(最多のジャンル。未分類のみならNone)
            / employee_ids(相談者。候補から外すだけで画面には出さない) / label(選択肢の表示)
    """
    rows = df.dropna(subset=["issue_summary"]).sort_values("timestamp", ascending=False).reset_index(drop=True)
    if rows.empty:
        return []
    texts = rows["issue_summary"].tolist()
    assigned = [-1] * len(texts)
    members: list[list[int]] = []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        sim = cosine_similarity(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True).fit_transform(texts))
    except Exception:  # scikit-learn が使えないときは、まとめずに1件ずつ
        sim = None
    for i in range(len(texts)):
        if assigned[i] >= 0:
            continue
        group = [i]
        assigned[i] = len(members)
        if sim is not None:
            for j in range(i + 1, len(texts)):
                if assigned[j] < 0 and sim[i, j] >= GROUP_SIMILARITY:
                    group.append(j)
                    assigned[j] = len(members)
        members.append(group)

    groups = []
    for idxs in members:
        part = rows.iloc[idxs]
        genres = [g for g in part["category_1"] if g != UNCLASSIFIED]
        rep = texts[idxs[0]]
        count = len(idxs)
        short = rep if len(rep) <= 60 else rep[:60] + "…"
        groups.append({
            "id": part.iloc[0]["log_id"], "rep": rep, "summaries": [texts[i] for i in idxs], "count": count,
            "category_1": Counter(genres).most_common(1)[0][0] if genres else None,
            "employee_ids": [e for e in part["employee_id"].dropna().unique()],
            "label": f"{short}（類似{count}件）" if count > 1 else short,
            "latest": part["timestamp"].max(),
        })
    groups.sort(key=lambda g: (-g["count"], -g["latest"].value))
    return groups


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
        f"- {c['name']}（{c['match_type']}／{'・'.join(c['tags'])}）: 課題文との一致語 {'・'.join(c['matched_terms']) or 'なし'}"
        for c in CANDIDATES[:5]
    ) or "- （該当する候補者なし）"

    if SELECTED_ISSUE is not None:
        shown = "\n".join(f"- {t}" for t in SELECTED_ISSUE["summaries"][:5])
        selected_block = (
            f"■ マネージャーが選んだ課題（類似の相談 {SELECTED_ISSUE['count']}件を1項目にまとめたもの）\n"
            f"代表: {SELECTED_ISSUE['rep']}\n{shown}\n\n"
        )
    else:
        selected_block = ""

    return (
        f"{selected_block}"
        "■ 今週のジャンル別相談件数\n"
        f"{genre_lines}\n\n"
        "■ 今週の課題別件数（ジャンルとは別分類）\n"
        f"{issue_lines}\n\n"
        "■ 相談ログからの具体的な課題例（抜粋）\n"
        f"{concrete_lines}\n\n"
        "■ 支援候補となる社員（スキル・資格・過去の実績が課題に一致した人。上位5名）\n"
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
# セクション3: 人材マッチング（課題を選ぶと、その課題に詳しそうな人を探す）
# ----------------------------------------------------------------------------

st.subheader("③ 人材マッチング")
st.caption(
    "調べたい課題を選ぶと、その課題に詳しそうな人を探して並べます。課題を変えると結果も変わります。"
    "最終的に誰に相談するかは、タグを見て人が選びます。"
)

period_min = logs_df["timestamp"].min().date()
period_max = logs_df["timestamp"].max().date()
default_start = max(period_min, period_max - timedelta(days=MATCH_DEFAULT_DAYS - 1))

sel1, sel2 = st.columns(2)
period = sel1.date_input(
    "期間", value=(default_start, period_max), min_value=period_min, max_value=period_max, key="match_period"
)
if isinstance(period, (tuple, list)) and len(period) == 2:
    period_start, period_end = period
    period_df = logs_df[(logs_df["timestamp"].dt.date >= period_start) & (logs_df["timestamp"].dt.date <= period_end)]
else:
    st.info("期間の終わりの日も選んでください。")
    period_start = period_end = period_max
    period_df = logs_df.iloc[0:0]

genre_options = [ALL_GENRES] + [g for g in CATEGORIES if g in set(period_df["category_1"])]
genre = sel2.selectbox("ジャンルで絞り込み", genre_options, key="match_genre")
scope_df = period_df if genre == ALL_GENRES else period_df[period_df["category_1"] == genre]

issue_groups = group_similar_issues(scope_df)
issue_by_id = {g["id"]: g for g in issue_groups}
selected_id = st.selectbox(
    f"課題（{len(scope_df)}件の相談を、似たものをまとめて{len(issue_groups)}項目にしています）",
    options=list(issue_by_id),
    index=None,
    placeholder="課題を選んでください",
    format_func=lambda i: issue_by_id[i]["label"],
    key=f"match_issue_{period_start}_{period_end}_{genre}",  # 絞り込みを変えたら選び直し
)

if selected_id is None:
    st.info("課題を選ぶと、候補者が表示されます。")
else:
    SELECTED_ISSUE = issue_by_id[selected_id]
    if SELECTED_ISSUE["count"] > 1:
        with st.expander(f"まとめた{SELECTED_ISSUE['count']}件の相談を見る"):
            for text in SELECTED_ISSUE["summaries"]:
                st.write(f"- {text}")
    issue_text = "。".join(SELECTED_ISSUE["summaries"][:MATCH_SAMPLE_LOGS])
    try:
        # 相談した本人は候補から外す（誰の相談かは画面に出さない）
        CANDIDATES = to_ui_list(match_employees(
            category_1=SELECTED_ISSUE["category_1"], issue_text=issue_text,
            exclude_employee_ids=SELECTED_ISSUE["employee_ids"], top_n=MATCH_TOP_N,
        ))
    except Exception as e:
        st.error(f"人材マッチングの実行に失敗しました: {e}")

    with st.expander("このマッチングの仕組み"):
        st.markdown(
            "- **スコア = スキル一致 × 0.8 ＋ 経験一致 × 0.2**（表示用）\n"
            "- **スキル一致**: その人の skill1・skill2・資格が、課題の文の語（辞書）に当たるか。語が多く当たるほど強い。"
            "ジャンルが同じなら少しだけ加点（ジャンルだけでは候補になりません）\n"
            "- **経験一致**: 過去の業績（案件名・コメント）が課題に関連するか。語の一致と、文の類似度の両方で見ます\n"
            "- **評価ランク（S・A・B…）はマッチングにも並び順にも使っていません**\n"
            "- **並び順**: ①スキルが一致した人（一致した語の種類が多い→スキルのレベルが高い→年数が長い順）"
            "②資格だけ一致した人 ③経験だけ一致した人。スコアの高さではなく、このルールで並べています\n"
            "- 相談した本人は候補から外しています。タグは、探している人が自分で選ぶための目印です"
        )

    if not CANDIDATES:
        st.info("該当する候補者が見つかりませんでした。")
    else:
        # タグ（種類ごと）で絞り込み。種類の中はどれか一致、種類をまたぐときは全部一致
        tag_kinds = ["部署", "年代", "役職", "資格", "参加案件"]
        tag_cols = st.columns(len(tag_kinds))
        chosen: dict[str, list[str]] = {}
        for col, kind in zip(tag_cols, tag_kinds):
            values: list[str] = []
            for person in CANDIDATES:
                v = person["tag_groups"].get(kind)
                for item in (v if isinstance(v, list) else [v]):
                    if item and item not in values:
                        values.append(item)
            chosen[kind] = col.multiselect(kind, sorted(values), key=f"match_tag_{kind}_{selected_id}")

        def matches_tags(person: dict) -> bool:
            for kind, picked in chosen.items():
                if not picked:
                    continue
                v = person["tag_groups"].get(kind)
                have = v if isinstance(v, list) else [v]
                if not any(item in picked for item in have):
                    return False
            return True

        shown_candidates = [p for p in CANDIDATES if matches_tags(p)]
        st.caption(f"候補 {len(shown_candidates)}名（条件に当てはまった {len(CANDIDATES)}名のうち）")

        TAG_COLORS = {"年代": "blue", "部署": "green", "役職": "orange", "経験": "gray", "参加案件": "violet", "資格": "red"}
        for person in shown_candidates:
            with st.container(border=True):
                c1, c2 = st.columns([1, 3])
                with c1:
                    st.markdown(f"**{person['name']}**")
                    st.caption(f"{person['match_type']}｜マッチ度 {person['match_score']:.2f}")
                    st.caption(f"上司: {person['manager']}")
                with c2:
                    badges = []
                    for kind, v in person["tag_groups"].items():
                        for item in (v if isinstance(v, list) else [v]):
                            badges.append(f":{TAG_COLORS.get(kind, 'gray')}-badge[{item}]")
                    st.markdown(" ".join(badges))
                    with st.expander("なぜこの人が出たか（判断根拠）"):
                        for line in person["explanation"]:
                            st.write(f"- {line}")

st.divider()

# ----------------------------------------------------------------------------
# セクション4: AIアドバイザーの回答（③で選んだ課題に対する助言）
# ----------------------------------------------------------------------------

st.subheader("④ AIアドバイザーの回答")
st.caption(
    "③で選んだ課題と、①②の相談ログ集計データ（ジャンル別・課題別件数、具体例）、支援候補を根拠に、"
    "OpenAI API が取るべきアクションを提案します。課題を選び直すと、回答は消えます。"
    "OPENAI_API_KEY が未設定の場合はフォールバックの回答を表示します。"
)

advisor_key = SELECTED_ISSUE["id"] if SELECTED_ISSUE else None
if "advisor_response" not in st.session_state or st.session_state.get("advisor_for") != advisor_key:
    st.session_state["advisor_response"] = fallback_response()
    st.session_state["advisor_for"] = advisor_key

if st.button("🤖 選んだ課題についてAIアドバイスを生成", disabled=SELECTED_ISSUE is None):
    with st.spinner("AIアドバイザーが課題を分析しています..."):
        context = build_advisor_context(this_week_logs)
        st.session_state["advisor_response"] = generate_advisor_response(context)

with st.chat_message("assistant"):
    st.write(st.session_state["advisor_response"])

st.caption(
    "※ ジャンル・課題の集計は Supabase `chat_logs` テーブルの実データです。"
    "人材マッチング候補は matching_engine.py が社員・スキル・業績データから算出しています。"
)