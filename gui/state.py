"""
gui/state.py - アプリケーション状態管理 + セッション永続化

タブ間で共有される状態を AppState 1個に集約し、
明示的な「セッション保存」「セッション読み込み」で再開可能にする。

保存形式は混合:
- state.json: スカラー値・dict(JSONシリアライズ可能なもの)
- repair_df.parquet: 取得済みデータ
- tagged_df.parquet: タグ付け結果(フラット化済み)
- ranked_df.parquet: スコア付き絞り込み結果
- batch_results.pkl: バッチ結果(成功・失敗、再実行のため)
- records.pkl: 整形済みレコード(失敗再実行のため必要)
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import pandas as pd


# ------------------------------------------------------------------
# 定数
# ------------------------------------------------------------------

# セッション保存先のベースディレクトリ
# Windows: %APPDATA%/repair-analysis/sessions
# Mac/Linux: ~/.repair-analysis/sessions
def _get_sessions_base_dir() -> Path:
    import os
    import sys
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "repair-analysis"
    else:
        base = Path.home() / ".repair-analysis"
    return base / "sessions"


SESSIONS_BASE_DIR = _get_sessions_base_dir()


# ------------------------------------------------------------------
# AppState
# ------------------------------------------------------------------

@dataclass
class AppState:
    """
    アプリ全体の状態を保持するシングルトン的オブジェクト。
    全タブはこの AppState を共有する。
    
    DataFrame や batch_results は JSON 化できないため、
    保存時は別ファイルとして書き出す。
    """
    # --- 問い合わせ ---
    inquiry_text: str = ""
    
    # --- スキーマ(1回目の結果) ---
    schema: Optional[dict] = None
    
    # --- データソース設定 ---
    data_source: Literal["sql", "csv"] = "csv"
    csv_path: Optional[str] = None
    sql_query: Optional[str] = None
    sql_params: list = field(default_factory=list)  # tuple は JSON 不可なので list
    mapping_name: Optional[str] = None
    
    # --- 絞り込みタグ ---
    query_tags: dict = field(default_factory=dict)
    
    # --- スコアリングパラメータ ---
    min_relevance: float = 0.3
    top_n: int = 50
    
    # --- 出力タグ(ファイル名のサフィックス) ---
    output_tag: str = ""
    
    # --- Copilot用エクスポートのON/OFF ---
    copilot_export: bool = False
    
    # --- DataFrame・batch_results は JSON 外で保持 ---
    # これらは dataclass 化しない(別途プロパティで管理)
    
    def __post_init__(self):
        # 非シリアライズフィールドを初期化
        self.repair_df: Optional[pd.DataFrame] = None
        self.records: Optional[list[dict]] = None
        self.batches: Optional[list[list[dict]]] = None
        self.batch_results: Optional[list[dict]] = None
        self.tagged_df: Optional[pd.DataFrame] = None
        self.ranked_df: Optional[pd.DataFrame] = None
        self._current_session_dir: Optional[Path] = None
    
    # --- セッション保存 ---
    def save_session(self, session_dir: Optional[Path] = None,
                     session_name: Optional[str] = None) -> Path:
        """
        セッションを保存する。
        
        Args:
            session_dir: 保存先ディレクトリ(指定なければ新規タイムスタンプ)
            session_name: セッション名(ディレクトリ名のサフィックス)
        
        Returns:
            保存先ディレクトリ
        """
        if session_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"{timestamp}_{session_name}" if session_name else timestamp
            session_dir = SESSIONS_BASE_DIR / name
        
        session_dir = Path(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # state.json (JSON シリアライズ可能なフィールドのみ)
        state_dict = self._to_serializable_dict()
        state_dict["_saved_at"] = datetime.now().isoformat()
        state_dict["_session_name"] = session_name or ""
        with open(session_dir / "state.json", "w", encoding="utf-8") as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2)
        
        # DataFrame を Parquet で保存
        if self.repair_df is not None:
            self.repair_df.to_parquet(session_dir / "repair_df.parquet", index=False)
        if self.tagged_df is not None:
            self.tagged_df.to_parquet(session_dir / "tagged_df.parquet", index=False)
        if self.ranked_df is not None:
            self.ranked_df.to_parquet(session_dir / "ranked_df.parquet", index=False)
        
        # records/batches/batch_results は pickle で保存
        # (構造が複雑で JSON 不向き、かつタグ付け失敗時の再実行に必要)
        if self.records is not None:
            with open(session_dir / "records.pkl", "wb") as f:
                pickle.dump(self.records, f)
        if self.batches is not None:
            with open(session_dir / "batches.pkl", "wb") as f:
                pickle.dump(self.batches, f)
        if self.batch_results is not None:
            with open(session_dir / "batch_results.pkl", "wb") as f:
                pickle.dump(self.batch_results, f)
        
        self._current_session_dir = session_dir
        return session_dir
    
    # --- セッション読み込み ---
    def load_session(self, session_dir: Path) -> None:
        """
        セッションを読み込んで現在の AppState を上書きする。
        
        ファイルが存在しないフィールドは None のまま。
        """
        session_dir = Path(session_dir)
        if not session_dir.exists():
            raise FileNotFoundError(f"セッションが存在しません: {session_dir}")
        
        # state.json
        state_path = session_dir / "state.json"
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                state_dict = json.load(f)
            self._apply_serializable_dict(state_dict)
        
        # DataFrame
        for attr, fname in [
            ("repair_df", "repair_df.parquet"),
            ("tagged_df", "tagged_df.parquet"),
            ("ranked_df", "ranked_df.parquet"),
        ]:
            p = session_dir / fname
            if p.exists():
                setattr(self, attr, pd.read_parquet(p))
            else:
                setattr(self, attr, None)
        
        # pickle
        for attr, fname in [
            ("records", "records.pkl"),
            ("batches", "batches.pkl"),
            ("batch_results", "batch_results.pkl"),
        ]:
            p = session_dir / fname
            if p.exists():
                with open(p, "rb") as f:
                    setattr(self, attr, pickle.load(f))
            else:
                setattr(self, attr, None)
        
        self._current_session_dir = session_dir
    
    def _to_serializable_dict(self) -> dict:
        """JSON 化可能なフィールドだけ辞書化"""
        d = asdict(self)
        # __post_init__ で追加した非シリアライズ属性は asdict に含まれないが念のため
        for k in ["repair_df", "records", "batches", "batch_results",
                  "tagged_df", "ranked_df", "_current_session_dir"]:
            d.pop(k, None)
        return d
    
    def _apply_serializable_dict(self, d: dict) -> None:
        """JSON 辞書から AppState の値を復元"""
        # メタフィールドは無視
        for meta_key in ["_saved_at", "_session_name"]:
            d.pop(meta_key, None)
        
        for k, v in d.items():
            if hasattr(self, k):
                setattr(self, k, v)
    
    def reset(self) -> None:
        """状態を初期化(新規セッション開始時に呼ぶ)"""
        defaults = AppState()
        for k, v in defaults.__dict__.items():
            setattr(self, k, v)
        self.repair_df = None
        self.records = None
        self.batches = None
        self.batch_results = None
        self.tagged_df = None
        self.ranked_df = None
        self._current_session_dir = None
    
    # --- セッションサマリー(再開UI用) ---
    def get_summary(self) -> dict:
        """現在の状態のサマリー(UI 表示用)"""
        return {
            "inquiry_set": bool(self.inquiry_text.strip()),
            "schema_generated": self.schema is not None,
            "data_loaded": self.repair_df is not None,
            "data_count": len(self.repair_df) if self.repair_df is not None else 0,
            "tagged": self.tagged_df is not None,
            "tagged_count": len(self.tagged_df) if self.tagged_df is not None else 0,
            "ranked": self.ranked_df is not None,
            "ranked_count": len(self.ranked_df) if self.ranked_df is not None else 0,
        }


# ------------------------------------------------------------------
# セッション一覧(再開UI用)
# ------------------------------------------------------------------

def list_sessions(base_dir: Optional[Path] = None) -> list[dict]:
    """
    保存されているセッションの一覧を返す。
    
    Returns:
        [{"path": Path, "name": str, "saved_at": str, "summary": {...}}, ...]
        新しい順にソート済み
    """
    base_dir = base_dir or SESSIONS_BASE_DIR
    if not base_dir.exists():
        return []
    
    sessions = []
    for d in base_dir.iterdir():
        if not d.is_dir():
            continue
        state_path = d / "state.json"
        if not state_path.exists():
            continue
        
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        
        # 簡易サマリー
        info = {
            "path": d,
            "dir_name": d.name,
            "session_name": state.get("_session_name", ""),
            "saved_at": state.get("_saved_at", ""),
            "inquiry_preview": state.get("inquiry_text", "")[:60],
            "data_source": state.get("data_source", ""),
            "has_repair_df": (d / "repair_df.parquet").exists(),
            "has_tagged_df": (d / "tagged_df.parquet").exists(),
            "has_ranked_df": (d / "ranked_df.parquet").exists(),
        }
        sessions.append(info)
    
    # 新しい順
    sessions.sort(key=lambda s: s["saved_at"], reverse=True)
    return sessions


def delete_session(session_dir: Path) -> None:
    """セッションディレクトリを削除"""
    import shutil
    session_dir = Path(session_dir)
    if session_dir.exists() and session_dir.is_dir():
        shutil.rmtree(session_dir)
