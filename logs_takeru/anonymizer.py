"""PoC用の限定的なパターン置換。氏名や企業名は検出できない。"""
#re 正規表現を扱うためのモジュール
import re

#正規表現
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 正規表現→0から始まり、数字-数字-数字 の形になっている電話番号を探す
PHONE = re.compile(r"(?<!\d)0\d{1,4}-\d{1,4}-\d{3,4}(?!\d)")

#電話番号は[phone]にメールアドレスは[EMAIL]に変換する
def mask_text(text: str) -> str:
    """既知のメールアドレス・ハイフン付き電話番号を置換する。"""
    return PHONE.sub("[PHONE]", EMAIL.sub("[EMAIL]", text))
