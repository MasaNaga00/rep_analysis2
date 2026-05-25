"""
config.py - 環境設定

Jupyterから呼ぶ前提。APIキーは.envファイルで管理推奨。
"""
import os
from pathlib import Path

# .envから読み込む場合（python-dotenv使用）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# === Dify API ===
DIFY_API_BASE = os.getenv("DIFY_API_BASE", "https://api.dify.ai/v1")
DIFY_API_KEY_SCHEMA = os.getenv("DIFY_API_KEY_SCHEMA", "")  # 1回目ワークフロー用
DIFY_API_KEY_TAGGING = os.getenv("DIFY_API_KEY_TAGGING", "")  # 2回目ワークフロー用

# Dify接続に使用するCA証明書ファイル(必須)
# 社内Difyへの接続時、社内CAで署名された証明書を検証するために必要。
# 相対パスは ①実行ファイル/プロジェクトルート → ②カレントディレクトリ の順で探索。
DIFY_CA_CERT_PATH = os.getenv("DIFY_CA_CERT_PATH", "certs/dify_ca.pem")


# === MS SQL Server ===
# ODBC Driverを事前にインストールしておく
# Macなら `brew install msodbcsql18`
MSSQL_SERVER = os.getenv("MSSQL_SERVER", "your-server.database.windows.net")
MSSQL_DATABASE = os.getenv("MSSQL_DATABASE", "RepairDB")
MSSQL_USER = os.getenv("MSSQL_USER", "")
MSSQL_PASSWORD = os.getenv("MSSQL_PASSWORD", "")
MSSQL_DRIVER = os.getenv("MSSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")


# === 処理パラメータ ===
BATCH_SIZE = 10           # Dify 2回目の1バッチあたりのレコード数
MAX_CONCURRENT = 5        # 並列リクエスト数
MAX_RETRIES = 3           # エラー時のリトライ回数
REQUEST_TIMEOUT = 120     # Difyリクエストタイムアウト（秒）

# コメント前処理
MAX_COMMENT_LENGTH = 2000  # 1カラムあたりの最大文字数（超過時は切り詰め）

# タグ付け件数の警告しきい値
# この件数を超えてタグ付けしようとすると、GUIで確認ポップアップを出す
# (トークン消費が大きくなるため)。.env の TAGGING_WARN_THRESHOLD で変更可能。
TAGGING_WARN_THRESHOLD = int(os.getenv("TAGGING_WARN_THRESHOLD", "500"))


# === 出力 ===
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)
