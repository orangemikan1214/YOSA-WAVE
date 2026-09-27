"""
matching_engine.py
-------------------
FEATURE 02「人材マッチング」の中核ロジック。

蓄積された相談ログから抽出された課題（category_1 / issue_summary）に対して、
人事マスタ・業績データ・プロジェクトの稼働状況と突合し、対応に適した人材を
スコア順に提案する。

DB未接続のため、現時点では data/dummy_data/ 配下のCSVを直接読み込む。
将来databaseレイヤー（Supabase等）に置き換える場合は、load_* 関数の中身だけ
差し替えれば良いように、「データ取得(load_*)」と「スコアリング(_*_score)」を
分離している。

起動方法（動作確認用）:
    python matching_engine.py
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------------
# パス設定
# ----------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "dummy_data"

# ----------------------------------------------------------------------------
# スコアリングの重み・パラメータ（チームで調整しやすいよう定数化）
# ----------------------------------------------------------------------------
W_SKILL = 0.5
W_PERFORMANCE = 0.3
W_AVAILABILITY = 0.2

# 実績（assignment_type="実績"）としてこの件数以上プロジェクトを抱えていたら
# 稼働に余裕なし（availability_score = 0）とみなす。
# ※ "AI推薦" は過去にこのマッチングエンジンが提案しただけの候補であり、
#    確定した稼働ではないため稼働率には含めない。
MAX_ACTIVE_ASSIGNMENTS = 3

# 人事評価（S/A/B/C/D）を0-1のスコアに変換するための対応表
RATING_SCORE = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}

# スキル関連度（_skill_relevance）の基礎点。
# カテゴリ一致は最有力のシグナルなので1.0、相談文との語幹一致のみ（カテゴリ不一致 or
# カテゴリ未指定）はあくまで補助的なシグナルなので控えめな値にする。
# ここを同じ水準にすると、「人材」のような一般的な語が偶然含まれるだけで、
# 全く畑違いの社員が上位に紛れ込んでしまう（例: 技術検討の課題に人事担当者が浮上する）。
RELEVANCE_CATEGORY_MATCH = 1.0
RELEVANCE_TEXT_MATCH = 0.6

# スキル名から末尾の「〜開発」「〜設計」等を取り除き、相談文との部分一致に使う
# 語幹（stem）を作るための接尾辞リスト。長い接尾辞から順に判定する。
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
    availability_score: float


# ----------------------------------------------------------------------------
# データ取得（load_*）— 将来DB接続に差し替える際はここだけ変更すればよい
# ----------------------------------------------------------------------------

def _read_csv(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_employees() -> dict[str, dict]:
    """employee_id -> 社員情報dict"""
    return {row["employee_id"]: row for row in _read_csv("hr_employees.csv")}


def load_skill_master() -> dict[str, str]:
    """skill_name -> related_category_1"""
    return {row["skill_name"]: row["related_category_1"] for row in _read_csv("skill_master.csv")}


def load_performance() -> dict[str, list[dict]]:
    """employee_id -> 業績レコードのリスト（複数年度分）"""
    by_employee: dict[str, list[dict]] = {}
    for row in _read_csv("performance_records.csv"):
        by_employee.setdefault(row["employee_id"], []).append(row)
    return by_employee


def load_active_assignment_counts() -> dict[str, int]:
    """employee_id -> 実績（確定）ベースの現在のプロジェクト稼働数"""
    counts: dict[str, int] = {}
    for row in _read_csv("project_members.csv"):
        if row.get("assignment_type") == "実績":
            counts[row["employee_id"]] = counts.get(row["employee_id"], 0) + 1
    return counts


def load_extracted_issues() -> dict[str, dict]:
    """issue_id -> 課題ログ（extracted_issues.csvの1行）"""
    return {row["issue_id"]: row for row in _read_csv("extracted_issues.csv")}


def load_category1_values() -> set[str]:
    """category_master.csv に定義されているジャンル（category_1）の集合"""
    return {row["category_1"] for row in _read_csv("category_master.csv") if row.get("category_1")}


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


def _skill_relevance(skill_name: str, category_1: Optional[str], issue_text: str, skill_master: dict[str, str]) -> float:
    """
    1つのスキルが、指定の課題（カテゴリ・相談文）にどれだけ関連するかを0-1で返す。

      1) skill_masterのカテゴリがcategory_1と一致 → RELEVANCE_CATEGORY_MATCH（最有力の関連度）
      2) 相談文にスキルの語幹が含まれる → RELEVANCE_TEXT_MATCH（カテゴリ不一致でも拾える補助シグナル）
      3) どちらも無ければ 0.0（関連スキルなし）
    """
    relevance = 0.0
    if category_1 and skill_master.get(skill_name) == category_1:
        relevance = RELEVANCE_CATEGORY_MATCH

    if issue_text:
        stem = _skill_stem(skill_name)
        if stem and stem in issue_text:
            relevance = max(relevance, RELEVANCE_TEXT_MATCH)

    return relevance


def _skill_score(
    employee: dict, category_1: Optional[str], issue_text: str, skill_master: dict[str, str]
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

        relevance = _skill_relevance(name, category_1, issue_text, skill_master)
        if relevance <= 0.0:
            continue

        level = _to_float(employee.get(f"{slot}_Level"), default=1.0)
        years = _to_float(employee.get(f"{slot}_year"), default=0.0)
        level_factor = min(level, 5.0) / 5.0
        year_factor = min(years, 10.0) / 10.0

        # 関連度(relevance)を土台に、レベルと経験年数でわずかに上乗せする（最大1.0）
        slot_score = min(relevance * (0.7 + 0.2 * level_factor + 0.1 * year_factor), 1.0)

        if slot_score > best_score:
            best_score = slot_score
            best_skill = name

    return best_score, best_skill


def _performance_score(employee_id: str, performance_by_employee: dict[str, list[dict]]) -> float:
    """直近年度の評価(S〜D)とポイントから0-1のスコアを算出。実績データが無ければ中間値0.5。"""
    records = performance_by_employee.get(employee_id, [])
    if not records:
        return 0.5

    latest = max(records, key=lambda r: int(r["fiscal_year"]))
    rating_score = RATING_SCORE.get(latest.get("performance_rating", ""), 0.5)
    point_score = min(_to_float(latest.get("point"), default=100.0) / 120.0, 1.0)
    return round(0.7 * rating_score + 0.3 * point_score, 3)


def _availability_score(employee_id: str, active_counts: dict[str, int]) -> float:
    """実績ベースの現稼働プロジェクト数から、余裕度を0-1で算出。"""
    count = active_counts.get(employee_id, 0)
    return round(max(0.0, 1.0 - count / MAX_ACTIVE_ASSIGNMENTS), 3)


def _feature_text(employee: dict, matched_skill: Optional[str], performance_score: float, availability_score: float) -> str:
    """app.pyの候補カード（feature列）にそのまま表示できる説明文を組み立てる。"""
    if matched_skill:
        slot = "skill1" if employee.get("skill1") == matched_skill else "skill2"
        level = employee.get(f"{slot}_Level", "-")
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

    if availability_score >= 0.66:
        avail_note = "稼働に余裕あり"
    elif availability_score >= 0.34:
        avail_note = "稼働はやや逼迫"
    else:
        avail_note = "稼働はほぼ埋まっている"

    return f"{skill_part}。{perf_note}、{avail_note}。"


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
        category_1: 課題のジャンル（category_master.csvのcategory_1に準拠）。
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
    performance_by_employee = load_performance()
    active_counts = load_active_assignment_counts()
    exclude = set(exclude_employee_ids or [])

    candidates: list[Candidate] = []
    for employee_id, employee in employees.items():
        if employee_id in exclude:
            continue
        if department and employee.get("department") != department:
            continue

        skill_score, matched_skill = _skill_score(employee, category_1, issue_text, skill_master)
        if skill_score <= 0.0:
            continue  # 関連スキルが全く無い社員は候補にしない

        performance_score = _performance_score(employee_id, performance_by_employee)
        availability_score = _availability_score(employee_id, active_counts)

        total_score = (
            W_SKILL * skill_score
            + W_PERFORMANCE * performance_score
            + W_AVAILABILITY * availability_score
        )

        manager = employees.get(employee.get("manager_id") or "")

        candidates.append(
            Candidate(
                employee_id=employee_id,
                name=employee["name"],
                department=employee["department"],
                position=employee.get("position", ""),
                manager_name=manager["name"] if manager else None,
                match_score=round(total_score, 3),
                feature=_feature_text(employee, matched_skill, performance_score, availability_score),
                matched_skill=matched_skill,
                skill_score=round(skill_score, 3),
                performance_score=performance_score,
                availability_score=availability_score,
            )
        )

    candidates.sort(key=lambda c: c.match_score, reverse=True)
    return candidates[:top_n]


def match_for_issue_id(issue_id: str, top_n: int = 3, exclude_employee_ids: Optional[list[str]] = None) -> list[Candidate]:
    """extracted_issues.csv の issue_id を指定して、そのままマッチングする（ダッシュボード連携用）。"""
    issue = load_extracted_issues().get(issue_id)
    if issue is None:
        raise ValueError(f"issue_id '{issue_id}' が extracted_issues.csv に見つかりません")

    return match_employees(
        category_1=issue["category_1"],
        issue_text=issue.get("issue_summary", ""),
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
    マネージャーの自由記述の質問（recommendations.csvのmanager_query相当）から
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
    """app.py の CANDIDATES と同じ形（name/feature/manager/match_score）に変換する。"""
    return {
        "name": candidate.name,
        "feature": candidate.feature,
        "manager": candidate.manager_name or "（上長未設定）",
        "match_score": candidate.match_score,
    }


def to_ui_list(candidates: list[Candidate]) -> list[dict]:
    return [to_ui_dict(c) for c in candidates]


# ----------------------------------------------------------------------------
# 動作確認用デモ
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("課題ログ(extracted_issues.csv)に対するマッチング")
    print("=" * 60)
    issues = load_extracted_issues()
    for issue_id, issue in issues.items():
        print(f"\n[{issue_id}] {issue['department']} / {issue['category_1']}（urgency={issue['urgency']}）")
        print(f"  相談内容: {issue['issue_summary']}")
        for candidate in match_for_issue_id(issue_id, top_n=3):
            print(f"    -> {candidate.name}（{candidate.department}/{candidate.position}）"
                  f" score={candidate.match_score}  {candidate.feature}")

    print("\n" + "=" * 60)
    print("自由記述クエリ(recommendations.csvのmanager_query)に対するマッチング")
    print("=" * 60)
    for rec in _read_csv("recommendations.csv"):
        query = rec["manager_query"]
        guessed = guess_category_1(query)
        print(f"\nQ. {query}")
        print(f"  推定カテゴリ: {guessed}")
        for candidate in match_for_query(query, exclude_employee_ids=[rec["manager_id"]], top_n=3):
            print(f"    -> {candidate.name}（{candidate.department}/{candidate.position}）"
                  f" score={candidate.match_score}  {candidate.feature}")
