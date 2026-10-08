"""相談AI（社員用）をダッシュボードのページとして開くための入口。

中身は consult_app/app.py にある。ここでは実行するだけで、ロジックは持たない。
単独起動（streamlit run consult_app/app.py）も従来どおり使える。
"""

import runpy
import sys
from pathlib import Path

CONSULT_DIR = Path(__file__).resolve().parent.parent / "consult_app"

# consult_app/app.py は `from ai_client import ...` のように同じフォルダのファイルを読む
if str(CONSULT_DIR) not in sys.path:
    sys.path.insert(0, str(CONSULT_DIR))

runpy.run_path(str(CONSULT_DIR / "app.py"), run_name="__main__")
