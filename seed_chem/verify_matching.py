"""新しいマッチング仕様の確認。

Supabase の既存データ（読み取りのみ）に、seed_fixture.json の追加分を重ねた状態を作って、
matching_engine を動かす。DBには何も書かない。追加データを投入する前でも、投入後と同じ動きを確認できる。

    python seed_chem/verify_matching.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import matching_engine as me  # noqa: E402

KEYS = {
    "departments": "department_name", "skill_master": "skill_id", "employees": "employee_id",
    "performance_records": "record_id", "projects": "project_id",
}


def load_combined_tables() -> None:
    fixture = json.loads((HERE / "seed_fixture.json").read_text(encoding="utf-8"))
    for table in ["departments", "skill_master", "employees", "performance_records", "projects", "project_members", "chat_logs"]:
        existing = me._read_supabase(table)  # 読み取りのみ
        extra = fixture[table]
        if table in KEYS:
            ids = {r[KEYS[table]] for r in extra}
            existing = [r for r in existing if r[KEYS[table]] not in ids]
        # 既存の行は列が少ない場合がある（project_members等）ので、列を揃えず、そのまま足す
        me._cache[table] = (time.monotonic() + 10**9, existing + extra)  # 有効期限を十分先にして固定


CASES = [
    ("技術検討", "再生PETを配合すると繊維の引張強度が低下する原因と対策を知りたい"),
    ("技術検討", "難燃性とリサイクル性を両立する材料設計の事例を探している"),
    ("技術検討", "PFAS規制に対応するフッ素フリーの代替材料を探している"),
    ("事業戦略", "車載向けの軽量化ニーズに対する提案資料を作りたい"),
    ("他部署連携", "海外顧客からSDSの提出を求められたが手順が分からない"),
    ("人材・スキル", "若手研究者のOJTの進め方に悩んでいる"),
    ("技術検討", "リサイクル原料を混ぜるほど製品が割れやすくなる。誰に聞けばよいか"),  # 言い換え（辞書の語なし）
    ("技術検討", "新しい方法を知りたい"),  # ジャンルだけ一致。誰も出てはいけない
]


def check_order(cands: list[me.Candidate]) -> list[str]:
    problems = []
    tiers = [me._TIER[c.match_type] for c in cands]
    if tiers != sorted(tiers):
        problems.append("種別の順序（スキル→資格のみ→経験のみ）が崩れている")
    skill_part = [c for c in cands if c.match_type == "スキル一致"]
    keys = [(-min(len(c.matched_skill_terms), me.SORT_HIT_CAP), -c.matched_skill_level, -c.matched_skill_years) for c in skill_part]
    if keys != sorted(keys):
        problems.append("スキル一致の中が 語の種類数→レベル→年数 の降順になっていない")
    return problems


def main() -> None:
    load_combined_tables()
    employees = me.load_employees()
    print(f"社員 {len(employees)}名 / 業績 {len(me._fetch('performance_records'))}件 / スキル {len(me._fetch('skill_master'))}件")
    for category_1, text in CASES:
        print("=" * 78)
        print(f"[{category_1}] {text}")
        cands = me.match_employees(category_1, text, top_n=20)
        types: dict[str, int] = {}
        for c in cands:
            types[c.match_type] = types.get(c.match_type, 0) + 1
        print(f"  候補 {len(cands)}名 {types}")
        for rank, c in enumerate(cands[:8], 1):
            skill = f"{c.matched_skill}(Lv{c.matched_skill_level}/{c.matched_skill_years}年)" if c.matched_skill else "-"
            print(f"  {rank:>2}. {c.name:<8}{c.department:<10}{c.match_type:<6} score={c.match_score:.2f} "
                  f"(skill{c.skill_score:.2f}/exp{c.experience_score:.2f}) {skill} 案件{c.active_projects}")
        problems = check_order(cands)
        print("  並び順チェック:", "OK" if not problems else problems)
    # 説明の例
    print("=" * 78)
    sample = me.match_employees("技術検討", CASES[0][1], top_n=1)[0]
    print(f"説明の例: {sample.name}  タグ={sample.tags}")
    for line in sample.explanation:
        print("   -", line)


if __name__ == "__main__":
    main()
