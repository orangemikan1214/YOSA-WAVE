"""
matching_engine.py
-------------------
FEATURE 02「人材マッチング」の中核ロジック。

マネージャーが選んだ課題（相談ログの issue_summary）に対して、課題に詳しそうな社員を探して提示する。

【仕様（2026-10 会議で決定）】
  match_score = 0.8 × スキル一致 + 0.2 × 経験一致
    スキル一致 : 社員の skill1 / skill2 / 資格（certifications）のどれかが、課題文の語（辞書）に一致するか
    経験一致   : 過去の業績（key_project・comment）が、課題に関連するか
  ・評価ランク（S/A/B…）や評価コメントの論調は、マッチングにも並び順にも使わない。
  ・並び順はマッチングのスコアではなく「ソート」で決める:
      ①スキル（skill1/2）に一致した人 … 課題文と一致した語の種類数（最大3）→ スキルのレベル → 経験年数の高い順
      ②資格だけ一致した人            … 一致した語の種類数 → 社会人経験年数の長い順
      ③経験だけ一致した人            … 経験一致の高い順
    （「引張」の1語だけ当たった高レベルの人が、語がよく当たる専門家より上に来ないよう、語の種類数を先に見る）
  ・年代・部署・役職・経験年数・参加案件数・資格を「タグ」として付け、最終的に選ぶのは人間（マネージャー）。
  ・なぜその人が出たのかを、explanation（判断根拠）として返す。

【一致の判定】
  辞書方式（skill_master.keywords と資格の辞書 CERT_KEYWORDS）で、「課題文にこの語が含まれるか」を調べる。
  経験は自由文なので、辞書の語に加えて、文字N-gram の TF-IDF 類似度（streamlit_4 の方式）でも拾う。

データは Supabase の各テーブルから読む（.env の SUPABASE_URL / SUPABASE_KEY が必要）。
「データ取得(_fetch / load_*)」と「スコアリング」は分離してある。

動作確認用（DBに繋ぐ）:
    python matching_engine.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------
# パラメータ（チームで調整しやすいよう定数化）
# ----------------------------------------------------------------------------
W_SKILL = 0.8
W_EXPERIENCE = 0.2

# 一致の強さ: 課題文に含まれる「一致した語」の種類数で決める（1種類 0.7 / 2種類 0.85 / 3種類以上 1.0）
STRENGTH_BY_HITS = {1: 0.7, 2: 0.85}
STRENGTH_MAX = 1.0
# ジャンル（category_1）が、そのスキルの関連ジャンルと同じなら少しだけ加点（語が一致したスキルのみ。ジャンルだけでは候補にならない）
GENRE_BONUS = 0.1

# 経験の類似度（TF-IDF・文字N-gram）。この値未満は「無関係」とみなし、満点はFULL_SIM
EXPERIENCE_MIN_SIM = 0.15
EXPERIENCE_FULL_SIM = 0.40

# 並び順で「一致した語の種類数」を比べるときの上限（これ以上は同じ扱い）
SORT_HIT_CAP = 3

# 参加案件として数えない案件の状態
EXCLUDED_PROJECT_STATUSES = {"完了", "中止", "終了"}

# 資格 → 課題文でその資格が関連するとみなす語
CERT_KEYWORDS: dict[str, list[str]] = {
    "技術士（化学）": ["化学プロセス", "プラント", "高分子", "反応"],
    "技術士（繊維）": ["繊維", "紡糸", "高分子"],
    "技術士": ["技術士", "化学プロセス", "プラント"],
    "公害防止管理者": ["排水", "排ガス", "環境規制", "環境対応"],
    "危険物取扱者（甲種）": ["危険物", "溶剤", "火災"],
    "高圧ガス製造保安責任者": ["高圧ガス", "設備保安"],
    "毒物劇物取扱責任者": ["毒物", "劇物", "化学物質管理"],
    "衛生管理者": ["労働衛生", "職場環境", "メンタル"],
    "QC検定1級": ["品質管理", "不良", "工程能力"],
    "弁理士": ["特許", "知財", "出願"],
    "知的財産管理技能士": ["特許", "知財", "出願"],
    "TOEIC900": ["海外", "英語"],
    "中国語検定": ["中国語", "海外"],
    "統計検定1級": ["統計", "データ分析"],
    "統計検定2級": ["統計", "データ分析"],
    "MBA": ["事業戦略", "経営", "新規事業"],
    "中小企業診断士": ["事業戦略", "経営", "新規事業"],
    "電気主任技術者": ["電気", "受変電"],
}

# skill_master にキーワードが登録されていないスキルのための代替: スキル名から末尾の「〜開発」等を除いた語幹
_SKILL_SUFFIXES = sorted(
    ["モデル設計", "マネジメント", "開発", "設計", "戦略", "分析", "交渉", "育成", "開拓", "折衝", "調査"],
    key=len,
    reverse=True,
)

# 自由記述の相談文からカテゴリ（category_1）を推定するための簡易キーワード辞書（match_for_query 用）
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
    match_score: float  # 0.8×skill_score + 0.2×experience_score（表示用。並び順には使わない）
    skill_score: float
    experience_score: float
    match_type: str  # "スキル一致" / "資格のみ" / "経験のみ"
    matched_skill: Optional[str]  # 一致したskill（無ければNone）
    matched_skill_level: Optional[int]
    matched_skill_years: Optional[int]
    matched_skill_terms: list[str]  # 上のスキルが一致した語（並び順で種類数を見る）
    matched_terms: list[str]  # 課題文に出ていて、一致の根拠になった語
    tags: list[str]  # 年代・部署・役職・経験年数・参加案件数・資格
    tag_groups: dict  # タグを種類別にしたもの（画面の絞り込み用）。{"年代": "40代", "部署": …, "資格": [..]}
    active_projects: int
    availability_note: str
    explanation: list[str]  # 「なぜこの人が出たか」の判断根拠（1行ずつ）
    feature: str = ""  # explanation を1つの文にしたもの（従来のUI向け）
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# データ取得（_fetch / load_*）
# ----------------------------------------------------------------------------

# 同じテーブルを何度も取りに行かないよう、短時間だけ結果を使い回す。
CACHE_TTL_SECONDS = 60
_PAGE_SIZE = 1000  # Supabase(PostgREST) は1回の取得上限が1000行なので、ページ分割して全件取る
_cache: dict[str, tuple[float, list[dict]]] = {}
_tfidf_cache: dict[str, object] = {}


def clear_cache() -> None:
    _cache.clear()
    _tfidf_cache.clear()


def _read_supabase(table: str) -> list[dict]:
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


def _fetch(table: str) -> list[dict]:
    """Supabase のテーブルの全行を辞書のリストで返す（短時間キャッシュ付き）。"""
    cached = _cache.get(table)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    rows = _read_supabase(table)
    _cache[table] = (time.monotonic(), rows)
    return rows


def load_employees() -> dict[str, dict]:
    """employee_id -> 社員情報dict"""
    return {row["employee_id"]: row for row in _fetch("employees")}


def load_skill_master() -> dict[str, str]:
    """skill_name -> related_category_1"""
    return {row["skill_name"]: row["related_category_1"] for row in _fetch("skill_master")}


def load_skill_keywords() -> dict[str, list[str]]:
    """skill_name -> 課題文に出てきたら関連するとみなす語のリスト（skill_master.keywords）"""
    result: dict[str, list[str]] = {}
    for row in _fetch("skill_master"):
        raw = row.get("keywords") or ""
        result[row["skill_name"]] = [kw.strip() for kw in raw.split(";") if kw.strip()]
    return result


def load_performance() -> dict[str, list[dict]]:
    """employee_id -> 業績レコードのリスト（複数年度分）"""
    by_employee: dict[str, list[dict]] = {}
    for row in _fetch("performance_records"):
        by_employee.setdefault(row["employee_id"], []).append(row)
    return by_employee


def load_active_project_counts() -> dict[str, int]:
    """employee_id -> 今参加している案件の数（完了・中止の案件は数えない）。"""
    status_by_project = {row["project_id"]: row.get("status") for row in _fetch("projects")}
    counts: dict[str, int] = {}
    for row in _fetch("project_members"):
        if status_by_project.get(row["project_id"]) in EXCLUDED_PROJECT_STATUSES:
            continue
        counts[row["employee_id"]] = counts.get(row["employee_id"], 0) + 1
    return counts


def load_extracted_issues() -> dict[str, dict]:
    """issue_id -> 課題ログ（extracted_issuesの1行）。"""
    rows = _fetch("extracted_issues")
    return {row["issue_id"]: row for row in sorted(rows, key=lambda r: r["issue_id"])}


# ----------------------------------------------------------------------------
# 一致の判定
# ----------------------------------------------------------------------------

def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _core_name(skill_name: str) -> str:
    """「顧客共創(共同開発)」→「顧客共創」のように、注記の括弧を取り除く"""
    return skill_name.split("(")[0].split("（")[0]


def _skill_stem(skill_name: str) -> str:
    """スキル名から末尾の接尾辞（開発/設計/戦略...）を1つ取り除いた語幹。例: 「IoTセンサー開発」→「IoTセンサー」"""
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


def _cert_names(certifications: Optional[str]) -> list[str]:
    """資格欄（「MBA、TOEIC900」など）を1つずつの資格名に分ける。「なし」は空。"""
    if not certifications or certifications.strip() in ("なし", "無し", "-"):
        return []
    for sep in ("、", "／", "/", ",", "，", ";", "；"):
        certifications = certifications.replace(sep, "、")
    return [c.strip() for c in certifications.split("、") if c.strip()]


def _cert_terms(cert_name: str) -> list[str]:
    """資格名に対応する語。辞書に完全一致が無ければ、名前が互いに含まれる辞書項目を使う。"""
    if cert_name in CERT_KEYWORDS:
        return CERT_KEYWORDS[cert_name]
    for key, terms in CERT_KEYWORDS.items():
        if key in cert_name or cert_name in key:
            return terms
    return []


def _hits(terms: list[str], issue_text: str) -> list[str]:
    """課題文に含まれている語（重複なし、辞書の順）"""
    seen: dict[str, None] = {}
    lowered = issue_text.casefold()
    for term in terms:
        if term and term.casefold() in lowered:
            seen[term] = None
    return list(seen)


def _strength(hit_count: int) -> float:
    """一致した語の種類数 → 一致の強さ（0〜1）"""
    if hit_count <= 0:
        return 0.0
    return STRENGTH_BY_HITS.get(hit_count, STRENGTH_MAX)


def _issue_dictionary_terms(issue_text: str, skill_keywords: dict[str, list[str]]) -> list[str]:
    """課題文に出てくる、辞書（全スキルのキーワード＋資格の語）の語。経験の一致判定に使う。"""
    all_terms: dict[str, None] = {}
    for skill_name in skill_keywords:
        for term in _skill_terms(skill_name, skill_keywords):
            all_terms[term] = None
    for terms in CERT_KEYWORDS.values():
        for term in terms:
            all_terms[term] = None
    return _hits(list(all_terms), issue_text)


def _skill_match(
    employee: dict, category_1: Optional[str], issue_text: str,
    skill_master: dict[str, str], skill_keywords: dict[str, list[str]],
) -> tuple[float, list[dict], list[dict]]:
    """
    スキルと資格の一致を調べる。
    戻り値: (skill_score, 一致したスキルのリスト, 一致した資格のリスト)
      skill_score = 一致したもののうち最大の「強さ」（スキルはジャンル一致で+GENRE_BONUS、上限1.0）
    """
    skill_hits: list[dict] = []
    for slot in ("skill1", "skill2"):
        name = (employee.get(slot) or "").strip()
        if not name:
            continue
        terms = _hits(_skill_terms(name, skill_keywords), issue_text)
        if not terms:
            continue  # 語が一致しないスキルは、ジャンルが同じでも一致とみなさない
        strength = _strength(len(terms))
        genre = bool(category_1 and skill_master.get(name) == category_1)
        if genre:
            strength = min(STRENGTH_MAX, strength + GENRE_BONUS)
        skill_hits.append({
            "name": name, "level": _to_int(employee.get(f"{slot}_level"), 1),
            "years": _to_int(employee.get(f"{slot}_year"), 0),
            "terms": terms, "strength": strength, "genre": genre,
        })

    cert_hits: list[dict] = []
    for cert in _cert_names(employee.get("certifications")):
        terms = _hits(_cert_terms(cert), issue_text)
        if terms:
            cert_hits.append({"name": cert, "terms": terms, "strength": _strength(len(terms))})

    score = max([h["strength"] for h in skill_hits] + [h["strength"] for h in cert_hits] + [0.0])
    return score, skill_hits, cert_hits


def _experience_vectorizer(performance_rows: list[dict]):
    """業績の文（key_project＋comment）全体から作る TF-IDF（文字N-gram）。同じデータの間は使い回す。"""
    key = (id(performance_rows), len(performance_rows))
    cached = _tfidf_cache.get("exp")
    if cached and cached[0] == key:
        return cached[1]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        _tfidf_cache["exp"] = (key, None)
        return None
    texts = [_record_text(r) for r in performance_rows]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True)
    matrix = vectorizer.fit_transform(texts)
    pack = (vectorizer, matrix, {id(r): i for i, r in enumerate(performance_rows)})
    _tfidf_cache["exp"] = (key, pack)
    return pack


def _record_text(record: dict) -> str:
    return f"{record.get('key_project') or ''} {record.get('comment') or ''}".strip()


def _experience_match(
    employee_id: str, performance_by_employee: dict[str, list[dict]], performance_rows: list[dict],
    issue_text: str, dictionary_terms: list[str],
) -> tuple[float, Optional[dict]]:
    """
    経験の一致（0〜1）と、その根拠になった業績1件を返す。
      語の一致   : 課題文の辞書語が、その人の業績の文に出てくるか（種類数で強さを決める）
      文の類似度 : 文字N-gram の TF-IDF コサイン類似度（辞書に無い言い換えを拾う）
    二つのうち高い方を採用する。
    """
    records = performance_by_employee.get(employee_id, [])
    if not records or not issue_text:
        return 0.0, None

    # 語の一致（全年度分の業績を合算して、種類数で強さを決める）
    all_hit_terms: dict[str, None] = {}
    best_record_by_terms: Optional[dict] = None
    best_term_count = 0
    for record in records:
        hit = _hits(dictionary_terms, _record_text(record))
        for term in hit:
            all_hit_terms[term] = None
        if len(hit) > best_term_count:
            best_term_count = len(hit)
            best_record_by_terms = {"record": record, "terms": hit}
    term_score = _strength(len(all_hit_terms))

    # 文の類似度
    sim_score = 0.0
    best_sim = 0.0
    best_record_by_sim: Optional[dict] = None
    pack = _experience_vectorizer(performance_rows)
    if pack:
        vectorizer, matrix, index_of = pack
        from sklearn.metrics.pairwise import cosine_similarity

        issue_vec = vectorizer.transform([issue_text])
        for record in records:
            i = index_of.get(id(record))
            if i is None:
                continue
            sim = float(cosine_similarity(issue_vec, matrix[i])[0][0])
            if sim > best_sim:
                best_sim = sim
                best_record_by_sim = {"record": record, "sim": sim}
        if best_sim >= EXPERIENCE_MIN_SIM:
            sim_score = min(1.0, (best_sim - EXPERIENCE_MIN_SIM) / (EXPERIENCE_FULL_SIM - EXPERIENCE_MIN_SIM))

    if term_score >= sim_score and term_score > 0:
        evidence = dict(best_record_by_terms or {})
        evidence["terms"] = list(all_hit_terms)
        return term_score, evidence
    if sim_score > 0 and best_record_by_sim:
        return sim_score, best_record_by_sim
    return 0.0, None


# ----------------------------------------------------------------------------
# 表示用（タグ・稼働・判断根拠）
# ----------------------------------------------------------------------------

def _age_band(age) -> Optional[str]:
    a = _to_int(age, -1)
    return f"{a // 10 * 10}代" if a >= 0 else None


def _availability_note(active_projects: int) -> str:
    if active_projects <= 1:
        return "稼働に余裕あり"
    if active_projects == 2:
        return "稼働はやや逼迫"
    return "稼働はほぼ埋まっている"


def _tag_groups(employee: dict, active_projects: int) -> dict:
    """候補者に付けるタグを、種類別にまとめる（画面では種類ごとに絞り込める）。"""
    groups: dict = {}
    band = _age_band(employee.get("age"))
    if band:
        groups["年代"] = band
    groups["部署"] = employee["department"]
    if employee.get("position"):
        groups["役職"] = employee["position"]
    if employee.get("years_of_experience") is not None:
        groups["経験"] = f"経験{employee['years_of_experience']}年"
    groups["参加案件"] = f"参加案件{active_projects}件"
    certs = _cert_names(employee.get("certifications"))
    if certs:
        groups["資格"] = certs
    return groups


def _tags(groups: dict) -> list[str]:
    tags: list[str] = []
    for value in groups.values():
        tags.extend(value if isinstance(value, list) else [value])
    return tags


def _terms_text(terms: list[str]) -> str:
    return "・".join(f"『{t}』" for t in terms)


def _explain(
    match_type: str, skill_hits: list[dict], cert_hits: list[dict], experience: Optional[dict],
    skill_score: float, experience_score: float, match_score: float,
) -> list[str]:
    lines: list[str] = []
    for h in sorted(skill_hits, key=lambda h: (-h["level"], -h["years"])):
        genre = "（ジャンルも一致して加点）" if h["genre"] else ""
        lines.append(f"スキル『{h['name']}』（Lv{h['level']}・{h['years']}年）: 課題文の語 {_terms_text(h['terms'])} に一致{genre}")
    for h in cert_hits:
        lines.append(f"資格『{h['name']}』: 課題文の語 {_terms_text(h['terms'])} に関連")
    if experience:
        rec = experience["record"]
        what = f"{rec.get('fiscal_year')}年度『{rec.get('key_project')}』（{rec.get('comment')}）"
        if experience.get("terms"):
            lines.append(f"過去の実績 {what}: 課題文の語 {_terms_text(experience['terms'])} に一致")
        else:
            lines.append(f"過去の実績 {what}: 課題文との文の類似度 {experience['sim']:.0%}")
    lines.append(
        f"スコア {match_score:.2f} = スキル一致 {skill_score:.2f}×{W_SKILL} + 経験一致 {experience_score:.2f}×{W_EXPERIENCE}"
        f"（{match_type}。評価ランクは使っていません）"
    )
    return lines


# ----------------------------------------------------------------------------
# 公開API
# ----------------------------------------------------------------------------

_TIER = {"スキル一致": 0, "資格のみ": 1, "経験のみ": 2}


def match_employees(
    category_1: Optional[str] = None,
    issue_text: str = "",
    department: Optional[str] = None,
    exclude_employee_ids: Optional[list[str]] = None,
    top_n: int = 20,
) -> list[Candidate]:
    """
    課題（issue_summary）に対して、対応候補となる社員を並び順どおりに返す。

    Args:
        category_1: 課題のジャンル。指定すると、ジャンルが一致するスキルに少しだけ加点する（語が一致していることが前提）。
        issue_text: 課題の文（issue_summary。似た相談をまとめた場合はそれらをつなげた文）。
        department: 指定した場合、その部署の社員のみを候補にする（Noneなら全社対象）。
        exclude_employee_ids: 除外したい社員ID（相談者本人など）。
        top_n: 返す最大件数（既定20）。

    並び順: ①スキル一致（一致した語の種類数→レベル→年数の高い順）②資格のみ（語の種類数→社会人経験の長い順）③経験のみ（経験一致の高い順）
    スキル・資格・経験のいずれにも一致しない社員は、候補に含めない。
    """
    if not (issue_text or "").strip():
        return []

    employees = load_employees()
    skill_master = load_skill_master()
    skill_keywords = load_skill_keywords()
    performance_by_employee = load_performance()
    performance_rows = _fetch("performance_records")
    active_counts = load_active_project_counts()
    exclude = set(exclude_employee_ids or [])
    dictionary_terms = _issue_dictionary_terms(issue_text, skill_keywords)

    scored: list[tuple[tuple, Candidate]] = []
    for employee_id, employee in employees.items():
        if employee_id in exclude:
            continue
        if department and employee.get("department") != department:
            continue

        skill_score, skill_hits, cert_hits = _skill_match(employee, category_1, issue_text, skill_master, skill_keywords)
        experience_score, experience = _experience_match(
            employee_id, performance_by_employee, performance_rows, issue_text, dictionary_terms
        )
        if skill_score <= 0.0 and experience_score <= 0.0:
            continue

        match_type = "スキル一致" if skill_hits else ("資格のみ" if cert_hits else "経験のみ")
        match_score = round(W_SKILL * skill_score + W_EXPERIENCE * experience_score, 3)

        # 表示・並び順に使うスキル: 語が最もよく当たったもの → レベル → 年数
        best_skill = max(skill_hits, key=lambda h: (min(len(h["terms"]), SORT_HIT_CAP), h["level"], h["years"])) if skill_hits else None
        matched_terms: list[str] = []
        for h in skill_hits + cert_hits:
            matched_terms += [t for t in h["terms"] if t not in matched_terms]
        if experience:
            matched_terms += [t for t in experience.get("terms", []) if t not in matched_terms]

        active_projects = active_counts.get(employee_id, 0)
        manager = employees.get(employee.get("manager_id") or "")
        tag_groups = _tag_groups(employee, active_projects)
        explanation = _explain(match_type, skill_hits, cert_hits, experience, skill_score, experience_score, match_score)

        candidate = Candidate(
            employee_id=employee_id, name=employee["name"], department=employee["department"],
            position=employee.get("position") or "", manager_name=manager["name"] if manager else None,
            match_score=match_score, skill_score=round(skill_score, 3), experience_score=round(experience_score, 3),
            match_type=match_type,
            matched_skill=best_skill["name"] if best_skill else None,
            matched_skill_level=best_skill["level"] if best_skill else None,
            matched_skill_years=best_skill["years"] if best_skill else None,
            matched_skill_terms=list(best_skill["terms"]) if best_skill else [],
            matched_terms=matched_terms, tags=_tags(tag_groups), tag_groups=tag_groups,
            active_projects=active_projects, availability_note=_availability_note(active_projects),
            explanation=explanation, feature="。".join(explanation),
        )

        tier = _TIER[match_type]
        years_of_experience = _to_int(employee.get("years_of_experience"), 0)
        if tier == 0:
            hit_count = min(len(best_skill["terms"]), SORT_HIT_CAP)
            sort_key = (0, -hit_count, -best_skill["level"], -best_skill["years"], -match_score, employee_id)
        elif tier == 1:
            hit_count = min(max(len(h["terms"]) for h in cert_hits), SORT_HIT_CAP)
            sort_key = (1, -hit_count, -years_of_experience, -match_score, employee_id)
        else:
            sort_key = (2, -experience_score, -years_of_experience, employee_id)
        scored.append((sort_key, candidate))

    scored.sort(key=lambda pair: pair[0])
    return [c for _, c in scored[:top_n]]


def match_for_issue_id(issue_id: str, top_n: int = 20, exclude_employee_ids: Optional[list[str]] = None) -> list[Candidate]:
    """extracted_issues の issue_id を指定して、そのままマッチングする。"""
    issue = load_extracted_issues().get(issue_id)
    if issue is None:
        raise ValueError(f"issue_id '{issue_id}' が extracted_issues に見つかりません")

    return match_employees(
        category_1=issue["category_1"], issue_text=issue.get("issue_summary") or "",
        exclude_employee_ids=exclude_employee_ids, top_n=top_n,
    )


def guess_category_1(query_text: str) -> Optional[str]:
    """自由記述の相談文から、最もキーワードが一致したcategory_1を推定する簡易ヒューリスティック。"""
    best_category: Optional[str] = None
    best_hits = 0
    for category, keywords in CATEGORY_HINT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in query_text)
        if hits > best_hits:
            best_hits = hits
            best_category = category
    return best_category


def match_for_query(
    query_text: str, department: Optional[str] = None,
    exclude_employee_ids: Optional[list[str]] = None, top_n: int = 20,
) -> list[Candidate]:
    """マネージャーの自由記述の質問から候補人材を提案する。カテゴリは guess_category_1() で簡易推定する。"""
    return match_employees(
        category_1=guess_category_1(query_text), issue_text=query_text, department=department,
        exclude_employee_ids=exclude_employee_ids, top_n=top_n,
    )


def to_ui_dict(candidate: Candidate) -> dict:
    """画面用の辞書。従来のキー（name/feature/manager/match_score/availability）に、新しい項目を足している。"""
    return {
        "employee_id": candidate.employee_id,
        "name": candidate.name,
        "feature": candidate.feature,
        "manager": candidate.manager_name or "（上長未設定）",
        "match_score": candidate.match_score,
        "availability": candidate.availability_note,
        "match_type": candidate.match_type,
        "skill_score": candidate.skill_score,
        "experience_score": candidate.experience_score,
        "tags": candidate.tags,
        "tag_groups": candidate.tag_groups,
        "position": candidate.position,
        "department": candidate.department,
        "explanation": candidate.explanation,
        "matched_terms": candidate.matched_terms,
    }


def to_ui_list(candidates: list[Candidate]) -> list[dict]:
    return [to_ui_dict(c) for c in candidates]


# ----------------------------------------------------------------------------
# 動作確認用デモ
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    samples = [
        ("技術検討", "再生PET繊維で強度が低下する原因と対策を知りたい"),
        ("技術検討", "難燃性とリサイクル性を両立する材料設計の事例を探している"),
        ("他部署連携", "海外顧客からSDSの提出を求められたが手順が分からない"),
    ]
    for category_1, text in samples:
        print("=" * 60)
        print(f"[{category_1}] {text}")
        for rank, c in enumerate(match_employees(category_1, text, top_n=5), 1):
            print(f"  {rank}. {c.name}（{c.department}/{c.position}）{c.match_type} score={c.match_score}  tags={c.tags}")
