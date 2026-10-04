"""
matching_engine.py
-------------------
FEATURE 02「人材マッチング」の中核ロジック。

蓄積された相談ログから抽出された課題（category_1 / issue_summary）に対して、
人事マスタ・業績データ・プロジェクトの稼働状況と突合し、対応に適した人材を
スコア順に提案する。

データの読み込み元は環境変数 MATCHING_DATA_SOURCE で切り替える。
    supabase（既定） : Supabase の各テーブルを読む（.env の SUPABASE_URL / SUPABASE_KEY が必要）
    csv              : data/dummy_data/*.csv を読む（オフラインで動作確認したいとき用）
「データ取得(_fetch / load_*)」と「スコアリング(_*_score)」は分離してあるので、
読み込み元を変えてもスコアリングには影響しない。

起動方法（動作確認用）:
    python matching_engine.py                                  # Supabase を読む
    MATCHING_DATA_SOURCE=csv python matching_engine.py         # CSV を読む（Windows PowerShell: $env:MATCHING_DATA_SOURCE="csv"）
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------------
# パス設定
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # .env と data/ があるフォルダ
DATA_DIR = PROJECT_ROOT / "data" / "dummy_data"

# ----------------------------------------------------------------------------
# スコアリングの重み・パラメータ（チームで調整しやすいよう定数化）
# ----------------------------------------------------------------------------
#   match_score = W_SKILL * スキル + W_PERFORMANCE * 業績   （合計1.0。稼働状況は含めない）
W_SKILL = 0.6
W_PERFORMANCE = 0.4

# スキルスコアの内訳（合計1.0）。「課題との一致度」に、スキルのレベルと経験年数を掛け合わせる。
#   skill_score = 一致度 × (SKILL_BASE + SKILL_LEVEL_WEIGHT × レベル/5 + SKILL_YEAR_WEIGHT × 年数/SKILL_YEARS_CAP)
# 一致度が同じなら、レベルが高く経験年数が長い人ほど上位になる。
SKILL_BASE = 0.4
SKILL_LEVEL_WEIGHT = 0.4
SKILL_YEAR_WEIGHT = 0.2
SKILL_YEARS_CAP = 10  # このスキル年数以上は満点扱い

# 稼働状況（availability）はスコアには反映せず、画面表示用の参考情報としてのみ算出する。
# 実績（assignment_type="実績"）としてこの件数以上プロジェクトを抱えていたら「稼働に余裕なし」。
# ※ "AI推薦" は過去にこのマッチングエンジンが提案しただけの候補であり、
#    確定した稼働ではないため稼働率には含めない。
MAX_ACTIVE_ASSIGNMENTS = 3

# 業績スコア（0〜1にクリップ）= 直近年度の評価ランク + 評価コメントの論調 + 課題に関連する過去実績
#   1) 評価ランク（S/A/B/C/D）を点数化したもの
RATING_SCORE = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}
#   2) 直近年度の評価コメントに含まれる肯定語/否定語の数の差 × TONE_STEP を加減点（±TONE_CAPまで）
TONE_STEP = 0.05
TONE_CAP = 0.10
POSITIVE_TERMS = ["高評価", "高く評価", "成功", "達成", "貢献", "主導", "リーダーシップ", "超過",
                  "スムーズ", "牽引", "発揮", "向上", "良好", "推進", "発掘", "新規契約"]
NEGATIVE_TERMS = ["課題", "遅延", "苦労", "難航", "やり直し", "不足", "改善余地", "時間を要", "苦戦"]
#   3) 課題文に出てくる語（スキルのキーワード）が、過去の実績（案件名・評価コメント。全年度分）にも
#      出てくる場合、その語1つにつき EVIDENCE_STEP を加点（+EVIDENCE_CAPまで）
EVIDENCE_STEP = 0.05
EVIDENCE_CAP = 0.15

# スキル関連度（_skill_relevance）。
#   カテゴリ一致                 : RELEVANCE_CATEGORY_MATCH
#   カテゴリ一致 + 課題文にキーワード : RELEVANCE_CATEGORY_MATCH + RELEVANCE_TEXT_BONUS（= 1.0）
#   課題文にキーワードのみ         : RELEVANCE_TEXT_ONLY
# 「キーワードのみ」はカテゴリ一致より低くしておく。同じ水準にすると、一般的な語が偶然含まれるだけで
# 全く畑違いの社員が上位に紛れ込んでしまう（例: 技術検討の課題に人事担当者が浮上する）。
RELEVANCE_CATEGORY_MATCH = 0.8
RELEVANCE_TEXT_BONUS = 0.2
RELEVANCE_TEXT_ONLY = 0.6

# skill_master にキーワードが登録されていないスキルのための代替として、スキル名から
# 末尾の「〜開発」「〜設計」等を取り除いた語幹（stem）をキーワードとして使う。
# 長い接尾辞から順に判定する。
_SKILL_SUFFIXES = sorted(
    ["モデル設計", "マネジメント", "開発", "設計", "戦略", "分析", "交渉", "育成", "開拓", "折衝", "調査"],
    key=len,
    reverse=True,
)

# 自由記述の相談文からカテゴリ（category_1）を推定するための簡易キーワード辞書。
# 本来はai_advisor.py側でLLMによる意図解析に置き換わる想定の、暫定ヒューリスティック。
CATEGORY_HINT_KEYWORDS = {
    "技術検討": ["技術", "開発", "設計", "システム", "IoT", "AI", "センサー", "精度", "素材", "検証"],
    "人材・スキル": ["人材", "育成", "スキル", "組織", "キャリア", "教育", "継承"],
    "他部署連携": ["連携", "部署", "部門", "規格", "認証", "品質", "標準化", "会議"],
    "事業戦略": ["市場", "事業", "アライアンス", "提携", "海外", "代理店", "顧客", "戦略", "モデル", "販売", "知財", "非財務資産"],
    "予算・リソース配分": ["予算", "リソース", "人員", "投資", "KPI", "採算", "説明資料"],
}


@dataclass
class Candidate:
    """マッチング結果1件分。UI表示にも、デバッグ確認にもそのまま使える形にしている。"""

    employee_id: str
    name: str
    department: str
    position: str
    manager_name: Optional[str]
    match_score: float
    feature: str  # UIにそのまま出せる説明文（app.pyのCANDIDATES["feature"]相当）
    matched_skill: Optional[str]
    skill_score: float
    performance_score: float
    availability_score: float  # 表示用。match_score には含めない
    availability_note: str  # 例:「稼働に余裕あり」


# ----------------------------------------------------------------------------
# データ取得（_fetch / load_*）— 読み込み元の切り替えはここだけで完結する
# ----------------------------------------------------------------------------

# 同じテーブルを何度も取りに行かないよう、短時間だけ結果を使い回す。
# ログが増えたことを反映したいときは clear_cache() を呼ぶ。
CACHE_TTL_SECONDS = 60
_PAGE_SIZE = 1000  # Supabase(PostgREST) は1回の取得上限が1000行なので、ページ分割して全件取る
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


def _data_source() -> str:
    source = os.getenv("MATCHING_DATA_SOURCE", "supabase").strip().lower()
    if source not in ("supabase", "csv"):
        raise ValueError(f"MATCHING_DATA_SOURCE は 'supabase' か 'csv' を指定してください（現在: '{source}'）")
    return source


def _normalize(row: dict) -> dict:
    """列名を小文字に揃える（CSVの skill1_Level と、DBの skill1_level の差を吸収する）"""
    return {key.lower(): value for key, value in row.items()}


def _read_csv(filename: str) -> list[dict]:
    with open(DATA_DIR / filename, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_supabase(table: str) -> list[dict]:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")  # どのフォルダから起動しても .env を見つけられるようにする
    except ImportError:
        pass

    from utils.service import get_supabase_client  # SUPABASE_URL / SUPABASE_KEY が未設定ならここで ValueError

    client = get_supabase_client()
    rows: list[dict] = []
    start = 0
    while True:
        chunk = client.table(table).select("*").range(start, start + _PAGE_SIZE - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < _PAGE_SIZE:
            return rows
        start += _PAGE_SIZE


def _fetch(table: str, csv_filename: str) -> list[dict]:
    """テーブル（Supabase）またはCSVの全行を、列名を小文字化した辞書のリストで返す。"""
    source = _data_source()
    key = (source, table)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    raw = _read_supabase(table) if source == "supabase" else _read_csv(csv_filename)
    rows = [_normalize(row) for row in raw]
    _cache[key] = (time.monotonic(), rows)
    return rows


def load_employees() -> dict[str, dict]:
    """employee_id -> 社員情報dict"""
    return {row["employee_id"]: row for row in _fetch("employees", "hr_employees.csv")}


def load_skill_master() -> dict[str, str]:
    """skill_name -> related_category_1"""
    return {row["skill_name"]: row["related_category_1"] for row in _fetch("skill_master", "skill_master.csv")}


def load_skill_keywords() -> dict[str, list[str]]:
    """skill_name -> 課題文に出てきたら関連するとみなす語のリスト（skill_master.keywords）"""
    result: dict[str, list[str]] = {}
    for row in _fetch("skill_master", "skill_master.csv"):
        raw = row.get("keywords") or ""
        result[row["skill_name"]] = [kw.strip() for kw in raw.split(";") if kw.strip()]
    return result


def load_performance() -> dict[str, list[dict]]:
    """employee_id -> 業績レコードのリスト（複数年度分）"""
    by_employee: dict[str, list[dict]] = {}
    for row in _fetch("performance_records", "performance_records.csv"):
        by_employee.setdefault(row["employee_id"], []).append(row)
    return by_employee


def load_active_assignment_counts() -> dict[str, int]:
    """employee_id -> 実績（確定）ベースの現在のプロジェクト稼働数"""
    counts: dict[str, int] = {}
    for row in _fetch("project_members", "project_members.csv"):
        if row.get("assignment_type") == "実績":
            counts[row["employee_id"]] = counts.get(row["employee_id"], 0) + 1
    return counts


def load_extracted_issues() -> dict[str, dict]:
    """issue_id -> 課題ログ（extracted_issuesの1行）。issue_id順に並べて返す。"""
    rows = _fetch("extracted_issues", "extracted_issues.csv")
    return {row["issue_id"]: row for row in sorted(rows, key=lambda r: r["issue_id"])}


def load_category1_values() -> set[str]:
    """ジャンル（category_1）マスタに定義されている値の集合"""
    return {row["category_1"] for row in _fetch("category1_master", "category_master.csv") if row.get("category_1")}


# ----------------------------------------------------------------------------
# スコアリング（_*_score）
# ----------------------------------------------------------------------------

def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _core_name(skill_name: str) -> str:
    """「顧客共創(共同開発)」→「顧客共創」のように、注記の括弧を取り除く"""
    return skill_name.split("(")[0].split("（")[0]


def _skill_stem(skill_name: str) -> str:
    """
    スキル名から末尾の接尾辞（開発/設計/戦略...）を1つ取り除いた語幹を返す。
    例: 「IoTセンサー開発」→「IoTセンサー」。相談文との部分一致判定に使う。
    """
    base = _core_name(skill_name)
    for suffix in _SKILL_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


def _skill_terms(skill_name: str, skill_keywords: dict[str, list[str]]) -> list[str]:
    """スキルに対応するキーワード。未登録ならスキル名の語幹で代替する。"""
    terms = skill_keywords.get(skill_name) or []
    if terms:
        return terms
    stem = _skill_stem(skill_name)
    return [stem] if stem else []


def _issue_terms(issue_text: str, skill_keywords: dict[str, list[str]]) -> list[str]:
    """課題文に出てくる、全スキルのキーワード（重複なし）。過去実績との照合に使う。"""
    if not issue_text:
        return []
    found: dict[str, None] = {}
    for skill_name in skill_keywords:
        for term in _skill_terms(skill_name, skill_keywords):
            if term in issue_text:
                found[term] = None
    return list(found)


def _skill_relevance(
    skill_name: str,
    category_1: Optional[str],
    issue_text: str,
    skill_master: dict[str, str],
    skill_keywords: dict[str, list[str]],
) -> float:
    """
    1つのスキルが、指定の課題（カテゴリ・相談文）にどれだけ関連するかを0-1で返す。

      カテゴリ一致 + 課題文にキーワード → RELEVANCE_CATEGORY_MATCH + RELEVANCE_TEXT_BONUS
      カテゴリ一致のみ                  → RELEVANCE_CATEGORY_MATCH
      課題文にキーワードのみ             → RELEVANCE_TEXT_ONLY（カテゴリ不一致/未指定でも拾える補助シグナル）
      どちらも無し                      → 0.0（関連スキルなし）
    """
    category_hit = bool(category_1 and skill_master.get(skill_name) == category_1)
    text_hit = bool(issue_text) and any(term in issue_text for term in _skill_terms(skill_name, skill_keywords))

    if category_hit:
        return RELEVANCE_CATEGORY_MATCH + (RELEVANCE_TEXT_BONUS if text_hit else 0.0)
    if text_hit:
        return RELEVANCE_TEXT_ONLY
    return 0.0


def _skill_score(
    employee: dict,
    category_1: Optional[str],
    issue_text: str,
    skill_master: dict[str, str],
    skill_keywords: dict[str, list[str]],
) -> tuple[float, Optional[str]]:
    """
    社員のskill1/skill2のうち課題に最も関連するものを1つ選び、
    (0-1のスコア, 採用したスキル名) を返す。レベル・経験年数を上乗せ要素として使う。
    """
    best_score = 0.0
    best_skill: Optional[str] = None

    for slot in ("skill1", "skill2"):
        name = (employee.get(slot) or "").strip()
        if not name:
            continue

        relevance = _skill_relevance(name, category_1, issue_text, skill_master, skill_keywords)
        if relevance <= 0.0:
            continue

        level = _to_float(employee.get(f"{slot}_level"), default=1.0)
        years = _to_float(employee.get(f"{slot}_year"), default=0.0)
        level_factor = min(level, 5.0) / 5.0
        year_factor = min(years, SKILL_YEARS_CAP) / SKILL_YEARS_CAP

        # 課題との一致度に、スキルのレベル・経験年数を掛け合わせる（最大1.0）
        slot_score = relevance * (
            SKILL_BASE + SKILL_LEVEL_WEIGHT * level_factor + SKILL_YEAR_WEIGHT * year_factor
        )

        if slot_score > best_score:
            best_score = slot_score
            best_skill = name

    return best_score, best_skill


def _performance(
    employee_id: str, performance_by_employee: dict[str, list[dict]], issue_terms: list[str]
) -> tuple[float, Optional[str]]:
    """
    業績スコア(0-1)と、課題に関連する過去実績の説明文（無ければNone）を返す。
    評価ランクだけでなく、評価コメントの文章も読む（論調・課題に関連する実績）。評価データが無ければ中間値0.5。
    """
    records = performance_by_employee.get(employee_id, [])
    if not records:
        return 0.5, None

    latest = max(records, key=lambda r: int(r["fiscal_year"]))
    score = RATING_SCORE.get(latest.get("performance_rating") or "", 0.5)

    # 2) 直近年度の評価コメントの論調
    comment = latest.get("comment") or ""
    tone = sum(term in comment for term in POSITIVE_TERMS) - sum(term in comment for term in NEGATIVE_TERMS)
    score += max(-TONE_CAP, min(TONE_CAP, TONE_STEP * tone))

    # 3) 課題に関連する過去実績（全年度の案件名・評価コメント）
    hit_terms: set[str] = set()
    latest_hit_record: Optional[dict] = None  # 表示用: 課題に関連する語を含む、最も新しい年度の実績
    for record in sorted(records, key=lambda r: int(r["fiscal_year"]), reverse=True):
        text = f"{record.get('key_project') or ''} {record.get('comment') or ''}"
        hits = [term for term in issue_terms if term in text]
        hit_terms.update(hits)
        if hits and latest_hit_record is None:
            latest_hit_record = record
    score += min(EVIDENCE_CAP, EVIDENCE_STEP * len(hit_terms))

    evidence = None
    if latest_hit_record:
        evidence = f"「{latest_hit_record.get('key_project')}」（{latest_hit_record.get('comment')}）"
    return round(max(0.0, min(1.0, score)), 3), evidence


def _availability_score(employee_id: str, active_counts: dict[str, int]) -> float:
    """実績ベースの現稼働プロジェクト数から、余裕度を0-1で算出（表示用。スコアには含めない）。"""
    count = active_counts.get(employee_id, 0)
    return round(max(0.0, 1.0 - count / MAX_ACTIVE_ASSIGNMENTS), 3)


def _availability_note(availability_score: float) -> str:
    if availability_score >= 0.66:
        return "稼働に余裕あり"
    if availability_score >= 0.34:
        return "稼働はやや逼迫"
    return "稼働はほぼ埋まっている"


def _feature_text(
    employee: dict, matched_skill: Optional[str], performance_score: float, evidence: Optional[str]
) -> str:
    """app.pyの候補カード（feature列）にそのまま表示できる、スキルと業績の説明文を組み立てる。"""
    if matched_skill:
        slot = "skill1" if employee.get("skill1") == matched_skill else "skill2"
        level = employee.get(f"{slot}_level", "-")
        years = employee.get(f"{slot}_year", "-")
        skill_part = f"{matched_skill}（Lv{level}・経験{years}年）を保有"
    else:
        skill_part = "直接一致するスキルは見つからず"

    if performance_score >= 0.75:
        perf_note = "直近の業績評価は良好"
    elif performance_score >= 0.5:
        perf_note = "直近の業績評価は標準的"
    else:
        perf_note = "直近の業績評価はやや苦戦気味"

    text = f"{skill_part}。{perf_note}。"
    if evidence:
        text += f"この課題に関連する実績: {evidence}。"
    return text


# ----------------------------------------------------------------------------
# 公開API
# ----------------------------------------------------------------------------

def match_employees(
    category_1: Optional[str] = None,
    issue_text: str = "",
    department: Optional[str] = None,
    exclude_employee_ids: Optional[list[str]] = None,
    top_n: int = 3,
) -> list[Candidate]:
    """
    課題（ジャンル + 相談文）に対して、対応候補となる社員をスコア順に返す。

    Args:
        category_1: 課題のジャンル（category1_master / category_master.csvのcategory_1に準拠）。
                    Noneの場合はカテゴリ一致を使わず、issue_textとの部分一致のみで判定する。
        issue_text: 相談内容の要約文（issue_summary等）。空文字でもよい。
        department: 指定した場合、その部署の社員のみを候補にする（Noneなら全社対象）。
        exclude_employee_ids: 除外したい社員ID（相談者本人など）。
        top_n: 返す最大件数。

    Returns:
        match_score降順のCandidateリスト（関連スキルが1つも無い社員は候補に含めない）。
    """
    employees = load_employees()
    skill_master = load_skill_master()
    skill_keywords = load_skill_keywords()
    performance_by_employee = load_performance()
    active_counts = load_active_assignment_counts()
    exclude = set(exclude_employee_ids or [])
    issue_terms = _issue_terms(issue_text, skill_keywords)

    candidates: list[Candidate] = []
    for employee_id, employee in employees.items():
        if employee_id in exclude:
            continue
        if department and employee.get("department") != department:
            continue

        skill_score, matched_skill = _skill_score(employee, category_1, issue_text, skill_master, skill_keywords)
        if skill_score <= 0.0:
            continue  # 関連スキルが全く無い社員は候補にしない

        performance_score, evidence = _performance(employee_id, performance_by_employee, issue_terms)
        availability_score = _availability_score(employee_id, active_counts)

        total_score = W_SKILL * skill_score + W_PERFORMANCE * performance_score

        manager = employees.get(employee.get("manager_id") or "")

        candidates.append(
            Candidate(
                employee_id=employee_id,
                name=employee["name"],
                department=employee["department"],
                position=employee.get("position") or "",
                manager_name=manager["name"] if manager else None,
                match_score=round(total_score, 3),
                feature=_feature_text(employee, matched_skill, performance_score, evidence),
                matched_skill=matched_skill,
                skill_score=round(skill_score, 3),
                performance_score=performance_score,
                availability_score=availability_score,
                availability_note=_availability_note(availability_score),
            )
        )

    candidates.sort(key=lambda c: c.match_score, reverse=True)
    return candidates[:top_n]


def match_for_issue_id(issue_id: str, top_n: int = 3, exclude_employee_ids: Optional[list[str]] = None) -> list[Candidate]:
    """extracted_issues の issue_id を指定して、そのままマッチングする（ダッシュボード連携用）。"""
    issue = load_extracted_issues().get(issue_id)
    if issue is None:
        raise ValueError(f"issue_id '{issue_id}' が extracted_issues に見つかりません")

    return match_employees(
        category_1=issue["category_1"],
        issue_text=issue.get("issue_summary") or "",
        exclude_employee_ids=exclude_employee_ids,
        top_n=top_n,
    )


def guess_category_1(query_text: str) -> Optional[str]:
    """
    自由記述の相談文から、最もキーワードが一致したcategory_1を推定する簡易ヒューリスティック。
    将来ai_advisor.pyでLLMによる意図解析に置き換わるまでの暫定ロジック。
    一致するキーワードが無ければ None（カテゴリ指定なしの全文一致マッチングにフォールバック）。
    """
    best_category: Optional[str] = None
    best_hits = 0
    for category, keywords in CATEGORY_HINT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in query_text)
        if hits > best_hits:
            best_hits = hits
            best_category = category
    return best_category


def match_for_query(
    query_text: str,
    department: Optional[str] = None,
    exclude_employee_ids: Optional[list[str]] = None,
    top_n: int = 3,
) -> list[Candidate]:
    """
    マネージャーの自由記述の質問（recommendationsのmanager_query相当）から
    候補人材を提案する。カテゴリはguess_category_1()で簡易推定する。

    ※ 精度はキーワードヒューリスティックの範囲にとどまる。ai_advisor.py実装後は
      LLMにcategory_1・issue_textを整形させてmatch_employees()に渡す形へ置き換え可能。
    """
    category_1 = guess_category_1(query_text)
    return match_employees(
        category_1=category_1,
        issue_text=query_text,
        department=department,
        exclude_employee_ids=exclude_employee_ids,
        top_n=top_n,
    )


def to_ui_dict(candidate: Candidate) -> dict:
    """app.py の CANDIDATES の形（name/feature/manager/match_score）＋稼働状況（availability）に変換する。"""
    return {
        "name": candidate.name,
        "feature": candidate.feature,
        "manager": candidate.manager_name or "（上長未設定）",
        "match_score": candidate.match_score,
        "availability": candidate.availability_note,
    }


def to_ui_list(candidates: list[Candidate]) -> list[dict]:
    return [to_ui_dict(c) for c in candidates]


# ----------------------------------------------------------------------------
# 動作確認用デモ
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"データ読み込み元: {_data_source()}")
    print("=" * 60)
    print("課題ログ(extracted_issues)に対するマッチング")
    print("=" * 60)
    issues = load_extracted_issues()
    for issue_id, issue in issues.items():
        print(f"\n[{issue_id}] {issue['department']} / {issue['category_1']}（urgency={issue['urgency']}）")
        print(f"  相談内容: {issue['issue_summary']}")
        for candidate in match_for_issue_id(issue_id, top_n=3):
            print(f"    -> {candidate.name}（{candidate.department}/{candidate.position}）"
                  f" score={candidate.match_score}  {candidate.feature} [{candidate.availability_note}]")

    print("\n" + "=" * 60)
    print("自由記述クエリ(recommendationsのmanager_query)に対するマッチング")
    print("=" * 60)
    for rec in _fetch("recommendations", "recommendations.csv"):
        query = rec["manager_query"]
        guessed = guess_category_1(query)
        print(f"\nQ. {query}")
        print(f"  推定カテゴリ: {guessed}")
        for candidate in match_for_query(query, exclude_employee_ids=[rec["manager_id"]], top_n=3):
            print(f"    -> {candidate.name}（{candidate.department}/{candidate.position}）"
                  f" score={candidate.match_score}  {candidate.feature} [{candidate.availability_note}]")
