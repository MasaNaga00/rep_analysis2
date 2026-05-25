"""
gui/settings_store.py - アプリ設定の永続化(平文 settings.json)

API キー・DB 接続情報・出力先ディレクトリ等を保存する。
keyring は使用せず、settings.json に平文で保存(ユーザー判断)。

保存先:
- Windows: %APPDATA%/repair-analysis/settings.json
- Mac/Linux: ~/.repair-analysis/settings.json

GUI の設定タブから読み書きする。アプリ起動時に読み込み、
保存時に書き込み、起動中は AppSettings オブジェクトを参照する。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ------------------------------------------------------------------
# 保存先
# ------------------------------------------------------------------

def _get_settings_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "repair-analysis"
    else:
        base = Path.home() / ".repair-analysis"
    return base


SETTINGS_DIR = _get_settings_dir()
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


# ------------------------------------------------------------------
# 設定オブジェクト
# ------------------------------------------------------------------

@dataclass
class AppSettings:
    """アプリ全体の設定"""
    # Dify API
    dify_api_base: str = "https://api.dify.ai/v1"
    dify_api_key_schema: str = ""
    dify_api_key_tagging: str = ""
    dify_ca_cert_path: str = "certs/dify_ca.pem"  # CA証明書(必須)
    
    # MS SQL Server
    mssql_server: str = ""
    mssql_database: str = ""
    mssql_user: str = ""
    mssql_password: str = ""
    mssql_driver: str = "{ODBC Driver 18 for SQL Server}"
    
    # 処理パラメータ
    batch_size: int = 10
    max_concurrent: int = 5
    max_retries: int = 3
    request_timeout: int = 120
    max_comment_length: int = 2000
    
    # タグ付け件数の警告しきい値(この件数超でポップアップ警告)
    tagging_warn_threshold: int = 500
    
    # 出力
    output_dir: str = ""  # 空なら ./output を使う
    
    # 最後に使ったマッピング・CSVパス(便利のため)
    last_mapping_name: str = ""
    last_csv_path: str = ""
    
    def save(self, path: Optional[Path] = None) -> Path:
        """JSON ファイルに保存"""
        path = path or SETTINGS_FILE
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        return path
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppSettings":
        """JSON ファイルから読み込む。存在しなければデフォルト値で返す"""
        path = path or SETTINGS_FILE
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # 未知のキーは無視
            valid_keys = set(cls.__dataclass_fields__.keys())
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**filtered)
        except (json.JSONDecodeError, OSError, TypeError) as e:
            print(f"⚠️ 設定ファイル読み込みエラー: {e}。デフォルト値を使用します。")
            return cls()
    
    def apply_to_config_module(self) -> None:
        """
        config.py モジュールの値を AppSettings の値で上書きする。
        既存の db.py / dify_client.py は config.* を参照しているため、
        起動時にこの関数を呼んで設定を反映する。
        """
        import config
        from pathlib import Path
        
        config.DIFY_API_BASE = self.dify_api_base
        config.DIFY_API_KEY_SCHEMA = self.dify_api_key_schema
        config.DIFY_API_KEY_TAGGING = self.dify_api_key_tagging
        config.DIFY_CA_CERT_PATH = self.dify_ca_cert_path
        
        config.MSSQL_SERVER = self.mssql_server
        config.MSSQL_DATABASE = self.mssql_database
        config.MSSQL_USER = self.mssql_user
        config.MSSQL_PASSWORD = self.mssql_password
        config.MSSQL_DRIVER = self.mssql_driver
        
        config.BATCH_SIZE = self.batch_size
        config.MAX_CONCURRENT = self.max_concurrent
        config.MAX_RETRIES = self.max_retries
        config.REQUEST_TIMEOUT = self.request_timeout
        config.MAX_COMMENT_LENGTH = self.max_comment_length
        
        # タグ付け警告しきい値:
        # settings.json で既定値(500)から変更されている場合のみ config を上書きする。
        # 変更されていなければ config.py が .env から読んだ値を尊重する
        # (=「デフォルト500・.envで変更可能」を保ちつつ、GUIでの明示変更も効かせる)。
        if self.tagging_warn_threshold != 500:
            config.TAGGING_WARN_THRESHOLD = self.tagging_warn_threshold
        
        if self.output_dir:
            config.OUTPUT_DIR = Path(self.output_dir)
            config.OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
