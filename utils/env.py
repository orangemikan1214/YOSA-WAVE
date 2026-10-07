"""共通の .env 読み込み。どのフォルダから起動しても、プロジェクト直下の .env を読む。"""

from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> None:
    load_dotenv(ENV_PATH)
