"""総合化学メーカー版の追加データを作る（SQLファイル＋テスト用の固定データ）。

Supabase へは何も書き込まない。出力:
  seed_chem/sql/01_departments.sql 〜 06_chat_logs.sql   ← チームが SQL Editor で順に実行する
  seed_chem/seed_fixture.json                              ← エンジンの検証用（DBに入れる前でも試せる）

設計は ../../データ設計_化学メーカー.md。テーブル・列は変えず、行を追加するだけ。
乱数は固定シード。何度実行しても同じ内容になる。
    python seed_chem/make_seed.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQL_DIR = HERE / "sql"
rnd = random.Random(20261009)

JST = timezone(timedelta(hours=9))

# ----------------------------------------------------------------------------
# 1. 部署
# ----------------------------------------------------------------------------
NEW_DEPARTMENTS = [
    "素材研究所", "高分子研究所", "樹脂事業部", "繊維事業部", "フィルム事業部",
    "機能性材料事業部", "生産技術部", "環境・サステナビリティ推進部", "知財・法務部", "海外営業部",
]

# 追加する社員数（既存20名を含めて合計100名になるよう配分）
NEW_EMPLOYEE_COUNT = {
    "素材研究所": 10, "高分子研究所": 10, "樹脂事業部": 9, "繊維事業部": 9, "フィルム事業部": 7,
    "機能性材料事業部": 7, "技術本部": 1, "生産技術部": 6, "営業本部": 4, "海外営業部": 5,
    "品質保証部": 2, "環境・サステナビリティ推進部": 4, "知財・法務部": 3, "DX推進部": 3,
}
EXISTING_HEAD = {"技術本部": "E006", "営業本部": "E011", "品質保証部": "E015"}  # 既存の責任者（新メンバーの上司になる）

# ----------------------------------------------------------------------------
# 2. スキル（既存 S01〜S22 に続けて S23〜）
# ----------------------------------------------------------------------------
NEW_SKILLS = [
    ("再生材配合設計", "技術検討", "再生材;再生PET;リサイクル材;マテリアルリサイクル;強度低下"),
    ("難燃材料開発", "技術検討", "難燃;燃焼;UL94;難燃剤"),
    ("PFAS代替材料開発", "技術検討", "PFAS;フッ素;代替材料;規制対応"),
    ("軽量化設計", "技術検討", "軽量化;軽量;比重;CFRP"),
    ("耐熱樹脂開発", "技術検討", "耐熱;高温;ガラス転移"),
    ("高分子合成", "技術検討", "重合;高分子;ポリマー;分子量"),
    ("繊維加工技術", "技術検討", "繊維;紡糸;不織布;染色"),
    ("フィルム成形", "技術検討", "フィルム;押出;延伸;包装材"),
    ("ケミカルリサイクル", "技術検討", "ケミカルリサイクル;解重合;モノマー回収"),
    ("LCA・CO2算定", "技術検討", "LCA;CO2算定;カーボンフットプリント;排出量"),
    ("材料評価・分析", "技術検討", "物性評価;引張;物性分析;劣化;耐久試験"),
    ("成形加工", "技術検討", "射出成形;成形条件;ひけ;バリ"),
    ("スケールアップ", "技術検討", "スケールアップ;量産化;ラボ;パイロット"),
    ("化学物質規制対応", "他部署連携", "REACH;RoHS;化審法;SDS;規制"),
    ("品質規格・認証", "他部署連携", "規格;認証;ISO;自動車規格;IATF"),
    ("自動車向け技術営業", "事業戦略", "自動車;内装材;OEM;Tier1;車載"),
    ("包装・食品向け提案", "事業戦略", "包装;食品;バリア;ラミネート"),
    ("電子材料向け提案", "事業戦略", "電子材料;半導体;ディスプレイ"),
    ("用途開発", "事業戦略", "新用途;用途開発;顧客課題;用途提案"),
    ("海外顧客対応", "事業戦略", "海外;東南アジア;欧州;現地"),
    ("知財調査・出願", "事業戦略", "特許;先行技術;出願;FTO"),
    ("生産計画・調達", "予算・リソース配分", "原料調達;生産計画;設備投資;稼働率"),
    ("コスト・採算分析", "予算・リソース配分", "原価;採算;コスト;投資対効果"),
    ("研究人材育成", "人材・スキル", "若手研究者;技術継承;OJT;教育"),
    ("技術伝承", "人材・スキル", "ベテラン;暗黙知;ノウハウ;継承"),
    ("組織間調整", "他部署連携", "研究所;事業部;部門間;部門間調整"),
    ("働き方・メンタルケア", "働き方・職場環境", "在宅;残業;メンタル;孤独;両立"),
    ("データ活用（材料開発）", "技術検討", "マテリアルズ・インフォマティクス;実験データ;予測"),
]
NEW_SKILL_ROWS = [
    {"skill_id": f"S{23 + i}", "skill_name": n, "related_category_1": c, "keywords": k}
    for i, (n, c, k) in enumerate(NEW_SKILLS)
]
# 既存スキル（DBにあるもの）のキーワード。実績文の生成に使う（DBの値と同じ）
EXISTING_SKILL_KEYWORDS = {
    "事業提携交渉": "提携;アライアンス;協業;共同事業", "知財戦略": "知財;特許;知的財産;ライセンス",
    "顧客共創(共同開発)": "共創;共同開発;顧客要望", "市場調査": "市場調査;市場分析;競合",
    "海外市場開拓": "海外;アジア;現地;輸出", "語学(英/中)": "英語;中国語;翻訳;通訳",
    "大口顧客折衝": "大口顧客;値引き;価格交渉;顧客折衝", "代理店開拓": "代理店;販売店",
    "IoTセンサー開発": "IoT;センサー;通信規格", "UXデザイン": "UX;ユーザー体験;画面設計;使い勝手",
    "製品開発マネジメント": "製品開発;試作;開発スケジュール;量産", "脱炭素技術": "脱炭素;カーボン;CO2;環境負荷",
    "AI・機械学習": "AI;機械学習;予測モデル;予知保全;精度", "材料工学": "新素材;材料;素材;歩留まり",
    "データ分析": "データ分析;統計;KPI;採算;シミュレーション;集計", "業界標準化交渉": "標準化;規格;認証;業界団体",
    "品質マネジメント": "品質;品証;不良", "組織開発": "組織;部門間;役割分担;ワークショップ",
    "人材育成": "育成;研修;技術継承;若手;教育;キャリア",
}
SKILL_KEYWORDS = {**EXISTING_SKILL_KEYWORDS, **{n: k for n, _, k in NEW_SKILLS}}

# 部署ごとの専門スキル候補
DEPT_POOL = {
    "素材研究所": ["材料評価・分析", "再生材配合設計", "高分子合成", "難燃材料開発", "耐熱樹脂開発", "PFAS代替材料開発", "材料工学", "データ活用（材料開発）", "ケミカルリサイクル"],
    "高分子研究所": ["高分子合成", "耐熱樹脂開発", "PFAS代替材料開発", "ケミカルリサイクル", "難燃材料開発", "材料評価・分析", "スケールアップ", "軽量化設計"],
    "樹脂事業部": ["成形加工", "再生材配合設計", "軽量化設計", "自動車向け技術営業", "難燃材料開発", "用途開発", "品質規格・認証", "顧客共創(共同開発)"],
    "繊維事業部": ["繊維加工技術", "再生材配合設計", "ケミカルリサイクル", "用途開発", "材料評価・分析", "顧客共創(共同開発)"],
    "フィルム事業部": ["フィルム成形", "包装・食品向け提案", "PFAS代替材料開発", "電子材料向け提案", "材料評価・分析", "用途開発"],
    "機能性材料事業部": ["電子材料向け提案", "耐熱樹脂開発", "用途開発", "材料評価・分析", "高分子合成", "顧客共創(共同開発)", "軽量化設計"],
    "技術本部": ["製品開発マネジメント", "スケールアップ", "脱炭素技術", "AI・機械学習", "組織間調整", "データ活用（材料開発）"],
    "生産技術部": ["スケールアップ", "成形加工", "生産計画・調達", "コスト・採算分析", "品質マネジメント", "IoTセンサー開発", "AI・機械学習"],
    "営業本部": ["大口顧客折衝", "自動車向け技術営業", "包装・食品向け提案", "電子材料向け提案", "用途開発", "代理店開拓", "市場調査"],
    "海外営業部": ["海外顧客対応", "海外市場開拓", "語学(英/中)", "大口顧客折衝", "自動車向け技術営業", "化学物質規制対応"],
    "品質保証部": ["品質マネジメント", "品質規格・認証", "化学物質規制対応", "材料評価・分析", "業界標準化交渉"],
    "環境・サステナビリティ推進部": ["LCA・CO2算定", "脱炭素技術", "化学物質規制対応", "ケミカルリサイクル", "組織間調整"],
    "知財・法務部": ["知財調査・出願", "知財戦略", "化学物質規制対応", "事業提携交渉"],
    "DX推進部": ["データ分析", "AI・機械学習", "データ活用（材料開発）", "IoTセンサー開発", "UXデザイン"],
}
SENIOR_EXTRA_SKILLS = ["研究人材育成", "技術伝承", "組織間調整"]  # 課長・部長が持つことがある

# 部署ごとの資格候補（None＝資格なし）
DEPT_CERTS = {
    "素材研究所": ["技術士（化学）", "危険物取扱者（甲種）", None, None],
    "高分子研究所": ["技術士（化学）", "危険物取扱者（甲種）", None, None],
    "樹脂事業部": ["QC検定1級", "危険物取扱者（甲種）", None, None],
    "繊維事業部": ["技術士（繊維）", "QC検定1級", None, None],
    "フィルム事業部": ["QC検定1級", "高圧ガス製造保安責任者", None, None],
    "機能性材料事業部": ["技術士（化学）", "TOEIC900", None, None],
    "技術本部": ["技術士（化学）", "統計検定2級", None, None],
    "生産技術部": ["高圧ガス製造保安責任者", "公害防止管理者", "衛生管理者", None],
    "営業本部": ["TOEIC900", "MBA", None, None],
    "海外営業部": ["TOEIC900", "中国語検定", "MBA", None],
    "品質保証部": ["QC検定1級", "毒物劇物取扱責任者", None, None],
    "環境・サステナビリティ推進部": ["公害防止管理者", "衛生管理者", None, None],
    "知財・法務部": ["弁理士", "知的財産管理技能士", None, None],
    "DX推進部": ["統計検定1級", "統計検定2級", None, None],
}

SURNAME_FULL = [
    "山田", "中村", "小林", "加藤", "吉田", "山口", "松本", "井上", "木村", "林", "斎藤", "清水", "山崎", "森", "池田",
    "橋本", "阿部", "石川", "山下", "中島", "石井", "小川", "前田", "岡田", "長谷川", "藤田", "後藤", "近藤", "村上", "遠藤",
    "青木", "坂本", "福田", "太田", "西村", "藤井", "岡本", "三浦", "中野", "原田", "松田", "竹内", "金子", "和田", "中山",
    "石田", "上田", "森田", "原", "柴田", "酒井", "工藤", "横山", "宮崎", "宮本", "内田", "高木", "安藤", "谷口", "大野",
    "丸山", "今井", "河野", "藤原", "小野", "松井", "平野", "菅原", "古川", "小島", "野口", "杉山", "千葉", "武田", "島田",
]
GIVEN = [
    "太郎", "一郎", "健一", "翔太", "大樹", "拓也", "直人", "雄介", "浩二", "誠", "隆", "悠斗", "蓮", "航", "涼太",
    "美咲", "陽子", "彩", "優子", "麻衣", "恵", "由美", "千尋", "沙織", "真由", "香織", "里奈", "葵", "結衣", "菜々子",
    "和也", "康平", "智也", "修", "亮", "学", "豊", "健太郎", "美穂", "奈々", "愛", "舞", "理恵", "祐子", "裕子",
]

# ----------------------------------------------------------------------------
# 3. 業績の文（key_project / comment）に使う話題
# ----------------------------------------------------------------------------
# 手書きの話題（テーマの中心になるスキル）。それ以外は、スキルのキーワードから定型で作る。
PROJECT_OVERRIDES: dict[str, list[tuple[str, str]]] = {
    "再生材配合設計": [("再生PET繊維の強度改善", "配合見直しで引張強度の低下を抑え量産化に貢献"),
                  ("リサイクル材比率向上プロジェクト", "再生材の相溶化剤を選定し強度低下の原因を特定"),
                  ("再生材グレードの品質安定化", "ロット間のばらつきを抑える配合基準を確立")],
    "難燃材料開発": [("難燃再生樹脂の開発", "UL94 V-0を維持したままリサイクル性を高め高評価"),
                 ("ハロゲンフリー難燃剤の評価", "燃焼試験を主導し顧客認証を取得")],
    "PFAS代替材料開発": [("PFASフリー撥水コーティング開発", "フッ素を使わない代替材料で顧客評価を達成"),
                    ("PFAS規制対応の代替材料選定", "規制対応を前倒しで完了し顧客から高評価")],
    "軽量化設計": [("自動車内装材の軽量化プロジェクト", "比重を下げつつ強度を確保し量産採用"),
                ("CFRP複合材の軽量化検証", "軽量化目標を超過達成")],
    "ケミカルリサイクル": [("ケミカルリサイクル実証プラント立上げ", "解重合条件を最適化しモノマー回収率を向上"),
                    ("使用済みPETの解重合検討", "プロセス条件を確立し事業化検討に貢献")],
    "自動車向け技術営業": [("自動車内装材の新規受注", "Tier1との技術折衝を主導し新規契約を獲得"),
                    ("車載向け樹脂の拡販", "OEMの要求仕様を整理し提案を成功させた")],
    "化学物質規制対応": [("REACH規制対応体制の構築", "SDS整備と欧州顧客への説明を主導"),
                  ("化審法の届出業務の標準化", "規制対応の手順書を整備し対応時間を短縮")],
    "研究人材育成": [("若手研究者のOJT制度設計", "教育計画を整え技術継承を推進し高く評価された"),
                 ("研究人材育成プログラムの運用", "若手研究者の育成で成果を上げた")],
    "技術伝承": [("ベテラン技術者のノウハウ集約", "暗黙知を文書化し継承の仕組みを構築"),
              ("実験ノウハウのデータベース化", "技術継承に貢献し他部署へ展開")],
    "海外顧客対応": [("欧州顧客向けの規制対応支援", "現地の要求に合わせた資料を整備し受注に貢献"),
                 ("東南アジア拠点との技術連携", "現地顧客との折衝を主導し新規契約を獲得")],
    "コスト・採算分析": [("設備投資の採算シミュレーション", "原価と投資対効果を試算し意思決定に貢献"),
                  ("原料調達コストの変動分析", "コスト削減策を提案し目標を達成")],
    "LCA・CO2算定": [("製品別カーボンフットプリント算定", "LCAの算定基盤を構築し顧客報告に貢献"),
                  ("CO2排出量の見える化", "排出量算定の手順を標準化")],
    "組織間調整": [("研究所と事業部の連携会議の運営", "部門間調整を主導しテーマの停滞を解消"),
               ("開発テーマの事業部への引き渡し", "役割分担を明確にし立ち上げを円滑化")],
}
PROJECT_FORMS = [
    "{a}に関する改善プロジェクト", "{a}対応の顧客別検証", "{a}の量産立上げ", "{a}の評価手法の確立", "{a}の社内標準化",
]
COMMENT_FORMS = [
    "{b}の検証を主導し成果を上げた", "{b}の課題に対し粘り強く取り組み達成", "{b}で関係部署と連携し貢献",
    "{b}に関して一部で遅延が出たが改善", "{b}の知見を共有し推進",
]


def project_theme(skill: str) -> tuple[str, str]:
    """スキルに対応する (key_project, comment)。手書きがあればそれを、無ければキーワードから作る。"""
    if skill in PROJECT_OVERRIDES:
        return rnd.choice(PROJECT_OVERRIDES[skill])
    kws = [k for k in SKILL_KEYWORDS.get(skill, skill).split(";") if k]
    a = rnd.choice(kws)
    b = rnd.choice(kws)
    return rnd.choice(PROJECT_FORMS).format(a=a), rnd.choice(COMMENT_FORMS).format(b=b)


# ----------------------------------------------------------------------------
# 4. 相談ログのテーマ
# ----------------------------------------------------------------------------
# (名前, 割合, 既定ジャンル, 週ごとの重み(8週分、古い→新しい), 困りごとの重み, 対象部署, [(要約, ジャンル or None), ...])
# 要約は「辞書の語を含むもの」と「言い換え（辞書の語を含まないもの）」を半々にしてある。
THEMES = [
    ("再生材×強度低下", 0.18, "技術検討", [2, 2, 3, 3, 5, 7, 9, 12],
     {"判断基準が分からない": 3, "エラー・障害": 2.5, "誰に聞くか分からない": 2.5, "情報が見つからない": 2},
     ["素材研究所", "高分子研究所", "樹脂事業部", "繊維事業部", "フィルム事業部", "生産技術部", "品質保証部"],
     [("再生PETを配合すると引張強度が低下する原因と対策を知りたい", None),
      ("再生材の比率を上げると強度低下が出るため、配合設計の見直し方法を知りたい", None),
      ("リサイクル材を混ぜたときの強度低下を抑える相溶化剤の選び方が分からない", None),
      ("再生PET繊維の強度低下について、過去の類似検討を探している", None),
      ("マテリアルリサイクル品でロットごとに強度がばらつく理由を知りたい", None),
      ("リサイクル原料を混ぜるほど製品が割れやすくなる。誰に聞けばよいか", None),
      ("使用済み原料の比率を上げたら引っ張りに弱くなってしまった", None),
      ("回収したペットボトル由来の原料で糸が切れやすくなる原因を知りたい", None),
      ("混ぜる原料のグレードで物性が変わる理由が整理できていない", None),
      ("再利用原料を使った試作品の耐久試験が基準を下回った", None)]),
    ("難燃×リサイクル", 0.12, "技術検討", [3, 3, 3, 3, 3, 3, 3, 3],
     {"判断基準が分からない": 3, "情報が見つからない": 3, "誰に聞くか分からない": 2},
     ["素材研究所", "高分子研究所", "樹脂事業部", "機能性材料事業部", "品質保証部"],
     [("難燃剤を入れた樹脂をリサイクルすると物性が落ちる。UL94を維持する方法は", None),
      ("難燃性とリサイクル性を両立する材料設計の事例を探している", None),
      ("難燃グレードの再生樹脂でUL94 V-0を満たす配合が分からない", None),
      ("燃焼試験の結果が再生樹脂だとばらつく原因を知りたい", None),
      ("ハロゲンを含まない燃えにくい材料を再利用したい", None),
      ("火が燃え広がりにくい樹脂を回収品から作る前例はあるか", None),
      ("安全規格を満たしつつ循環利用できる素材の組み合わせを知りたい", None)]),
    ("PFAS代替", 0.10, "技術検討", [0, 0, 0, 0, 0, 2, 4, 7],
     {"判断基準が分からない": 3, "情報が見つからない": 3, "誰に聞くか分からない": 2},
     ["素材研究所", "高分子研究所", "フィルム事業部", "機能性材料事業部", "環境・サステナビリティ推進部", "知財・法務部", "品質保証部"],
     [("PFAS規制に対応するフッ素フリーの代替材料を探している", None),
      ("PFASフリーのコーティング材の性能評価基準が分からない", None),
      ("フッ素系の撥水剤を使わない代替材料の事例を知りたい", None),
      ("PFAS代替の規制対応について、他部署に詳しい人がいるか知りたい", "他部署連携"),
      ("欧州の新しい有機フッ素化合物の規制に間に合う代替素材の候補を知りたい", None),
      ("撥水撥油をフッ素なしで実現した過去の案件はあるか", None),
      ("顧客から使用禁止物質の切り替え時期を問われて困っている", "他部署連携")]),
    ("自動車内装材の軽量化", 0.08, "技術検討", [3, 3, 3, 3, 3, 3, 3, 3],
     {"判断基準が分からない": 3, "情報が見つからない": 2, "誰に聞くか分からない": 2},
     ["樹脂事業部", "営業本部", "機能性材料事業部", "素材研究所", "生産技術部"],
     [("自動車内装材の軽量化提案で、比重を下げつつ強度を保つ材料を探している", None),
      ("車載向けの軽量化ニーズに対する提案資料を作りたい", "事業戦略"),
      ("内装部品を軽くする要望がTier1からあり、類似案件を知りたい", "事業戦略"),
      ("クルマの内装を軽くしたいという顧客依頼にどう答えるか", "事業戦略"),
      ("乗用車向けの部品を薄肉化して重量を減らす相談先を知りたい", None),
      ("CFRPと樹脂の使い分けの判断基準を知りたい", None)]),
    ("海外顧客・規制対応", 0.08, "事業戦略", [2, 2, 3, 3, 4, 4, 5, 5],
     {"手順がわからない": 3, "誰に聞くか分からない": 3, "情報が見つからない": 2},
     ["海外営業部", "営業本部", "品質保証部", "環境・サステナビリティ推進部", "樹脂事業部"],
     [("欧州向けでREACH規制の対応状況を顧客に説明する必要がある", "他部署連携"),
      ("海外顧客からSDSの提出を求められたが手順が分からない", "他部署連携"),
      ("東南アジアの現地規制と化審法の違いを整理したい", "他部署連携"),
      ("輸出先の化学物質のルールが変わるらしく、確認先が分からない", "他部署連携"),
      ("海外の顧客から取扱い書類の様式を求められた", None),
      ("欧州の顧客との価格交渉で、現地の相場情報が見つからない", None)]),
    ("研究人材育成・技術伝承", 0.07, "人材・スキル", [3, 3, 3, 3, 3, 3, 3, 3],
     {"判断基準が分からない": 3, "悩み・不安": 3, "誰に聞くか分からない": 2},
     ["素材研究所", "高分子研究所", "技術本部", "樹脂事業部", "繊維事業部", "人事部"],
     [("若手研究者のOJTの進め方に悩んでいる", None),
      ("ベテランの技術継承が進まず、暗黙知が失われそうで心配", None),
      ("実験のノウハウを体系的に残す方法を知りたい", None),
      ("定年が近い先輩の知識を後輩にどう引き継ぐか", None),
      ("新人が実験でつまずく原因を教える時間が取れない", None)]),
    ("部門間調整", 0.07, "他部署連携", [2, 2, 2, 3, 3, 4, 5, 6],
     {"誰に聞くか分からない": 3, "判断基準が分からない": 3, "悩み・不安": 2},
     ["素材研究所", "高分子研究所", "樹脂事業部", "繊維事業部", "フィルム事業部", "機能性材料事業部", "営業本部", "技術本部", "生産技術部"],
     [("研究所と事業部で優先順位が合わず、調整が進まない", None),
      ("部門間の役割分担が曖昧で、テーマが停滞している", None),
      ("研究所の成果を事業部に引き渡す手順が分からない", None),
      ("開発側と営業側で納期の認識がずれて困っている", None),
      ("別の部署に同じ検討をしている人がいるのか知りたい", None)]),
    ("予算・設備投資", 0.06, "予算・リソース配分", [3, 3, 3, 3, 3, 3, 3, 3],
     {"手順がわからない": 3, "判断基準が分からない": 3},
     ["生産技術部", "技術本部", "経営企画部", "樹脂事業部", "繊維事業部", "フィルム事業部"],
     [("新規の設備投資について、採算のシミュレーションの作り方が分からない", None),
      ("コスト試算で原料調達の変動をどう織り込むか知りたい", None),
      ("試作費の予算が不足しており、優先順位をつける判断基準が欲しい", None),
      ("来期の計画で人手が足りず、どこを削るか決められない", None)]),
    ("働き方・メンタル", 0.04, "働き方・職場環境", [2, 2, 2, 2, 2, 2, 2, 2],
     {"悩み・不安": 6, "誰に聞くか分からない": 1},
     ["素材研究所", "高分子研究所", "樹脂事業部", "営業本部", "生産技術部", "DX推進部"],
     [("在宅勤務が続いて孤独を感じ、集中力が落ちている", None),
      ("残業が増えて研究と家庭の両立が難しい", None),
      ("メンタル面で不調を感じており、相談先が知りたい", None),
      ("評価面談の前に気持ちが落ち着かない", None)]),
    ("課題ではない", 0.10, None, [2, 2, 2, 2, 2, 2, 2, 2],
     {"課題ではない": 1},
     None,
     [("こんにちは、今日はよろしくお願いします", None), ("ありがとう、助かりました", None),
      ("会議室の予約方法を確認しただけ", None), ("おすすめのランチを聞いただけ", None),
      ("文章の誤字を直してほしいという軽い依頼", None), ("今日の天気を聞いただけ", None)]),
    ("その他の業務", 0.10, None, [2, 2, 2, 2, 2, 2, 2, 2],
     {"手順がわからない": 2, "情報が見つからない": 2, "判断基準が分からない": 2, "作業代行": 1.5, "エラー・障害": 1},
     None,
     [("特許の先行技術調査の進め方を知りたい", "事業戦略"),
      ("実験データの解析にAIを使えるか知りたい", "技術検討"),
      ("品質不良の原因分析の手順が分からない", "他部署連携"),
      ("新しい用途の提案先を探している。電子材料向けの需要を知りたい", "事業戦略"),
      ("包装フィルムのバリア性を上げる方法を知りたい", "技術検討"),
      ("繊維の染色ムラの原因と対策を知りたい", "技術検討"),
      ("射出成形のひけを減らす条件を知りたい", "技術検討"),
      ("ラボからのスケールアップで収率が落ちる原因を知りたい", "技術検討"),
      ("LCAの算定範囲をどう決めるか知りたい", "技術検討"),
      ("議事録の要約を作ってほしい", None)]),
]
# 文末の補足（相談文に自然なばらつきを出す。辞書のキーワードは含めない）
TAILS = [
    "", "", "", "",
    "。来月の顧客との打ち合わせまでに答えが必要", "。社内に過去の事例がないか知りたい", "。手元の評価では再現できている",
    "。他の拠点でも同じ状況か気になる", "。上司には口頭で伝えてある", "。まず何から確認すべきか迷っている",
    "。納期が迫っていて焦っている", "。関連する資料が見つからない", "。担当者が異動してしまい引き継ぎが不十分",
    "。社外の文献も調べたが決め手がない", "。同僚にも聞いたが意見が分かれた",
]
PREFIXES = ["", "", "", "先週から", "新規案件で", "顧客からの要望で", "量産前の検証で", "会議の準備で", "試作の段階で", "最近"]
TOTAL_LOGS = 360
WEEK_STARTS = [datetime(2026, 8, 17, tzinfo=JST) + timedelta(weeks=i) for i in range(8)]  # 月曜。最新週は 10/5〜
NOW_JST = datetime(2026, 10, 9, 11, 30, tzinfo=JST)  # これより未来の時刻は作らない


# ----------------------------------------------------------------------------
# 5. 生成
# ----------------------------------------------------------------------------
def load_existing_names() -> set[str]:
    """既存社員の氏名（重複回避用）。DBに繋がらなくても動く。"""
    try:
        import sys
        sys.path.insert(0, str(HERE.parent))
        import matching_engine as me

        return {r["name"] for r in me._fetch("employees")}
    except Exception:
        return set()


def make_employees() -> list[dict]:
    used_names = load_existing_names()
    rows: list[dict] = []
    next_no = 21
    dept_head: dict[str, str] = dict(EXISTING_HEAD)
    big_depts = {"素材研究所", "高分子研究所", "樹脂事業部", "繊維事業部", "フィルム事業部", "機能性材料事業部", "生産技術部"}

    for dept, count in NEW_EMPLOYEE_COUNT.items():
        # 役職の割り振り: 責任者がいない部署は先頭を部長（大きい部署）か課長にする
        positions: list[str] = []
        if dept not in dept_head:
            positions.append("部長" if dept in big_depts else "課長")
        remaining = count - len(positions)
        n_kacho = max(1 if count >= 5 else 0, round(count * 0.2)) - (1 if positions == ["課長"] else 0)
        positions += ["課長"] * max(0, min(n_kacho, remaining))
        remaining = count - len(positions)
        positions += [rnd.choice(["主任", "主任", "一般社員", "一般社員", "一般社員"]) for _ in range(remaining)]
        rest = positions[1:]  # 先頭（責任者）は固定、残りの並びだけ混ぜる
        rnd.shuffle(rest)
        positions = positions[:1] + rest

        for pos in positions:
            emp_id = f"E{next_no:03d}"
            next_no += 1
            while True:
                name = f"{rnd.choice(SURNAME_FULL)} {rnd.choice(GIVEN)}"
                if name not in used_names:
                    used_names.add(name)
                    break
            age = {"部長": rnd.randint(46, 58), "課長": rnd.randint(38, 48), "主任": rnd.randint(29, 38), "一般社員": rnd.randint(22, 30)}[pos]
            yoe = max(0, age - 22 - rnd.randint(0, 2))
            hire_year = 2026 - yoe

            pool = list(DEPT_POOL[dept])
            if pos in ("部長", "課長") and rnd.random() < 0.4:
                pool += SENIOR_EXTRA_SKILLS
            skill1, skill2 = rnd.sample(pool, 2)

            def skill_stats() -> tuple[int, int]:
                years = rnd.randint(1, max(1, yoe)) if yoe >= 1 else 1
                years = min(years, yoe) if yoe >= 1 else 0
                level = 1 + years // 3 + rnd.choice([0, 0, 0, 0, 0, 0, 1, -1, 1])
                return years, max(1, min(5, level))

            y1, l1 = skill_stats()
            y2, l2 = skill_stats()
            cert = rnd.choice(DEPT_CERTS[dept])
            if cert and rnd.random() < 0.12:
                cert = f"{cert}、{rnd.choice([c for c in DEPT_CERTS[dept] if c and c != cert] or ['TOEIC900'])}"

            rows.append({
                "employee_id": emp_id, "name": name, "department": dept, "position": pos, "manager_id": None,
                "age": age, "years_of_experience": yoe,
                "employment_type": "契約社員" if rnd.random() < 0.05 else "正社員",
                "skill1": skill1, "skill1_year": y1, "skill1_level": l1,
                "skill2": skill2, "skill2_year": y2, "skill2_level": l2,
                "certifications": cert or "なし", "hire_date": f"{hire_year}-04-01",
            })
            if dept not in dept_head and pos in ("部長", "課長"):
                dept_head[dept] = emp_id

    # 上司: 責任者は上司なし（既存部署は既存責任者の下）、他は部署の責任者
    for r in rows:
        head = dept_head.get(r["department"])
        if head and head != r["employee_id"]:
            r["manager_id"] = head
    return rows


def make_performance(employees: list[dict]) -> list[dict]:
    rows: list[dict] = []
    no = 41  # 既存は P001〜P040
    for e in employees:
        own = [e["skill1"], e["skill2"]]
        pool = DEPT_POOL[e["department"]]
        for year in (2024, 2025):
            if year == 2024:
                theme_skill = own[0]
            else:
                theme_skill = own[1] if rnd.random() < 0.6 else own[0]
            # 約12%は、自分のスキル欄に無い隣接分野の経験を持つ（「経験だけ当たる人」の確認用）
            if year == 2025 and rnd.random() < 0.12:
                others = [s for s in pool if s not in own]
                if others:
                    theme_skill = rnd.choice(others)
            project, comment = project_theme(theme_skill)
            rating = rnd.choices(["S", "A", "B", "C", "D"], weights=[5, 35, 40, 15, 5])[0]
            point = {"S": rnd.randint(110, 120), "A": rnd.randint(100, 110), "B": rnd.randint(90, 100),
                     "C": rnd.randint(80, 90), "D": rnd.randint(70, 80)}[rating]
            rows.append({
                "record_id": f"P{no:03d}", "employee_id": e["employee_id"], "fiscal_year": year,
                "performance_rating": rating, "point": float(point), "key_project": project, "comment": comment,
            })
            no += 1
    return rows


PROJECTS = [
    ("PJ06", "再生PET繊維の強度向上プロジェクト", "繊維事業部", "進行中", "再生材配合設計;繊維加工技術;材料評価・分析", "技術特許;顧客基盤", "2026-01-15", "素材研究所と連携"),
    ("PJ07", "PFASフリー包装フィルムの開発", "フィルム事業部", "進行中", "PFAS代替材料開発;フィルム成形;化学物質規制対応", "規制対応ノウハウ;顧客基盤", "2026-03-01", "欧州規制に対応"),
    ("PJ08", "自動車内装材の軽量化プログラム", "樹脂事業部", "進行中", "軽量化設計;自動車向け技術営業;成形加工", "OEM関係;技術特許", "2025-10-01", "Tier1と共同"),
    ("PJ09", "難燃リサイクル樹脂の事業化検討", "素材研究所", "立ち上げ準備", "難燃材料開発;再生材配合設計;品質規格・認証", "知財ポートフォリオ", "2026-11-01", "規格取得が前提"),
    ("PJ10", "海外顧客向け機能性フィルムの展開", "海外営業部", "進行中", "海外顧客対応;電子材料向け提案;語学(英/中)", "現地ネットワーク", "2026-02-01", "東南アジア中心"),
    ("PJ11", "ケミカルリサイクル実証プラント", "高分子研究所", "進行中", "ケミカルリサイクル;スケールアップ;LCA・CO2算定", "プロセス特許", "2025-12-01", "環境推進部と連動"),
    ("PJ12", "LCA・CO2算定基盤の整備", "環境・サステナビリティ推進部", "検討中", "LCA・CO2算定;データ分析;脱炭素技術", "データ基盤", "2027-01-01", "全社展開を想定"),
]
PROJECT_DEPTS = {
    "PJ06": ["繊維事業部", "素材研究所", "高分子研究所"], "PJ07": ["フィルム事業部", "素材研究所", "品質保証部", "環境・サステナビリティ推進部"],
    "PJ08": ["樹脂事業部", "営業本部", "機能性材料事業部", "生産技術部"], "PJ09": ["素材研究所", "樹脂事業部", "品質保証部", "知財・法務部"],
    "PJ10": ["海外営業部", "機能性材料事業部", "営業本部"], "PJ11": ["高分子研究所", "素材研究所", "生産技術部", "環境・サステナビリティ推進部"],
    "PJ12": ["環境・サステナビリティ推進部", "DX推進部", "技術本部"],
}


def make_projects(employees: list[dict]) -> tuple[list[dict], list[dict]]:
    projects = [dict(zip(
        ["project_id", "project_name", "sponsor_department", "status", "required_skills",
         "non_financial_assets_needed", "target_start_date", "notes"], p)) for p in PROJECTS]
    load = {e["employee_id"]: 0 for e in employees}
    members: list[dict] = []
    for p in PROJECTS:
        pid = p[0]
        cands = [e for e in employees if e["department"] in PROJECT_DEPTS[pid]]
        rnd.shuffle(cands)
        size = rnd.randint(7, 10)
        for e in cands:
            if len([m for m in members if m["project_id"] == pid]) >= size:
                break
            if load[e["employee_id"]] >= 3:
                continue
            load[e["employee_id"]] += 1
            start = datetime.strptime(p[6], "%Y-%m-%d") - timedelta(days=rnd.randint(0, 30))
            members.append({"project_id": pid, "employee_id": e["employee_id"], "assigned_date": start.strftime("%Y-%m-%d")})
    return projects, members


def make_chat_logs(employees: list[dict]) -> list[dict]:
    by_dept: dict[str, list[dict]] = {}
    for e in employees:
        by_dept.setdefault(e["department"], []).append(e)
    all_emp = list(employees)

    plan: list[tuple[int, str]] = []  # (テーマindex, 週index)
    for ti, th in enumerate(THEMES):
        n = round(TOTAL_LOGS * th[1])
        weights = th[3]
        wsum = sum(weights)
        counts = [int(n * w / wsum) for w in weights]
        for _ in range(n - sum(counts)):
            counts[rnd.choices(range(8), weights=weights)[0]] += 1
        for wi, c in enumerate(counts):
            plan += [(ti, wi)] * c

    rows: list[dict] = []
    no = 2000
    for ti, wi in plan:
        name, _, default_cat1, _, cat2_w, depts, cores = THEMES[ti]
        core, cat1 = rnd.choice(cores)
        cat1 = cat1 or default_cat1
        pool = [e for d in (depts or []) for e in by_dept.get(d, [])] or all_emp
        emp = rnd.choice(pool)
        cat2 = rnd.choices(list(cat2_w), weights=list(cat2_w.values()))[0]
        if name == "その他の業務" and core == cores[-1][0]:
            cat1 = None
        # 時刻: 平日の9〜18時（JST）。現在時刻より未来は作らない
        for _ in range(20):
            ts = WEEK_STARTS[wi] + timedelta(days=rnd.randint(0, 4), hours=rnd.randint(9, 17), minutes=rnd.randint(0, 59), seconds=rnd.randint(0, 59))
            if ts <= NOW_JST:
                break
        else:
            ts = NOW_JST - timedelta(hours=rnd.randint(1, 20))
        summary = (rnd.choice(PREFIXES) + core + rnd.choice(TAILS)) if cat1 != "働き方・職場環境" else core + rnd.choice(TAILS[:4] + TAILS[8:10])
        rows.append({
            "log_id": f"L{no}", "employee_id": emp["employee_id"], "department": emp["department"],
            "timestamp": ts.astimezone(timezone.utc).isoformat(),
            "category_1": cat1, "category_2": cat2, "issue_summary": summary,
        })
        no += 1
    rows.sort(key=lambda r: r["timestamp"])
    for i, r in enumerate(rows):  # 時系列順にIDを振り直す
        r["log_id"] = f"L{2000 + i}"
    return rows


# ----------------------------------------------------------------------------
# 6. SQL出力
# ----------------------------------------------------------------------------
def lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path: Path, table: str, rows: list[dict], conflict: str, header: str, update: bool = True) -> None:
    cols = list(rows[0])
    lines = [f"-- {header}", "-- Supabase の SQL Editor に貼り付けて Run。何度流しても同じ結果になる（upsert）。", ""]
    lines.append(f"insert into {table} ({', '.join(cols)}) values")
    lines.append(",\n".join("  (" + ", ".join(lit(r[c]) for c in cols) + ")" for r in rows))
    non_key = [c for c in cols if c not in [k.strip() for k in conflict.split(",")]]
    if update and non_key:
        lines.append(f"on conflict ({conflict}) do update set " + ", ".join(f"{c} = excluded.{c}" for c in non_key) + ";")
    else:
        lines.append(f"on conflict ({conflict}) do nothing;")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    SQL_DIR.mkdir(exist_ok=True)
    departments = [{"department_name": d} for d in NEW_DEPARTMENTS]
    employees = make_employees()
    performance = make_performance(employees)
    projects, members = make_projects(employees)
    logs = make_chat_logs(employees)

    write_sql(SQL_DIR / "01_departments.sql", "departments", departments, "department_name", "部署マスタの追加（10件）", update=False)
    write_sql(SQL_DIR / "02_skill_master.sql", "skill_master", NEW_SKILL_ROWS, "skill_id", f"スキルマスタの追加（{len(NEW_SKILL_ROWS)}件, S23〜）")
    write_sql(SQL_DIR / "03_employees.sql", "employees", employees, "employee_id", f"社員の追加（{len(employees)}名, E021〜）。manager_id は同じ文の社員を指す（1文で入るので順序は気にしなくてよい）")
    write_sql(SQL_DIR / "04_performance_records.sql", "performance_records", performance, "record_id", f"業績の追加（{len(performance)}件）")
    write_sql(SQL_DIR / "05a_projects.sql", "projects", projects, "project_id", f"案件の追加（{len(projects)}件）")
    write_sql(SQL_DIR / "05b_project_members.sql", "project_members", members, "project_id, employee_id", f"案件メンバーの追加（{len(members)}件）", update=False)
    write_sql(SQL_DIR / "06_chat_logs.sql", "chat_logs", logs, "log_id", f"相談ログの追加（{len(logs)}件, L2000〜）")

    fixture = {
        "departments": departments, "skill_master": NEW_SKILL_ROWS, "employees": employees,
        "performance_records": performance, "projects": projects, "project_members": members, "chat_logs": logs,
    }
    (HERE / "seed_fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: len(v) for k, v in fixture.items()})


if __name__ == "__main__":
    main()
