"""
loader.py - SQL/CSV 共通データロードレイヤー

修理データの取得元(SQL Server / CSV)を抽象化し、
カラム名の違いをマッピングで吸収して、後段の preprocess.py が
期待する論理カラム名のDataFrameを返す。

論理カラム名:
    repair_id, user_comment, repair_comment, internal_1, internal_2

物理カラム名はマッピングで定義(例: "修理番号" → repair_id)。

使い方:
    # CSV から読み込み
    df = load_from_csv("data/repair.csv", mapping_name="sample_japan")
    
    # SQL から読み込み(既存 db.py を経由)
    df = load_from_sql(sql, params=("EOS R7", "2024-01-01"),
                       mapping_name="sample_japan")
"""
import json
from pathlib import Path
from typing import Optional, Union

import pandas as pd

# db モジュールは load_from_sql() 内で遅延 import する。
# CSV しか使わないユーザーは pyodbc をインストールしなくてもよいようにするため。


# ------------------------------------------------------------------
# 定数
# ------------------------------------------------------------------

# preprocess.py が必要とする論理カラム名
REQUIRED_LOGICAL_COLUMNS = ["repair_id"]
COMMENT_LOGICAL_COLUMNS = [
    "user_comment", "repair_comment", "internal_1", "internal_2"
]
ALL_LOGICAL_COLUMNS = REQUIRED_LOGICAL_COLUMNS + COMMENT_LOGICAL_COLUMNS

# マッピングプリセット保存先(プロジェクトルート/mappings)
MAPPINGS_DIR = Path(__file__).parent / "mappings"


# ------------------------------------------------------------------
# マッピング管理
# ------------------------------------------------------------------

def list_mappings() -> list[dict]:
    """
    mappings/ ディレクトリ内のマッピングプリセット一覧を返す。
    
    Returns:
        [{"name": "sample_japan", "display_name": "国内拠点サンプル",
          "description": "...", "path": "..."}, ...]
    """
    if not MAPPINGS_DIR.exists():
        return []
    
    result = []
    for json_path in sorted(MAPPINGS_DIR.glob("*.json")):
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "name": json_path.stem,
                "display_name": data.get("name", json_path.stem),
                "description": data.get("description", ""),
                "path": str(json_path),
            })
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ マッピング読み込み失敗: {json_path.name}: {e}")
    return result


def load_mapping(mapping_name: str) -> dict:
    """
    マッピングプリセットを読み込む。
    
    Args:
        mapping_name: 拡張子なしのファイル名(例: "sample_japan")
                      または .json を含むパス
    
    Returns:
        マッピング定義dict
    
    Raises:
        FileNotFoundError: マッピングファイルが存在しない
        ValueError: マッピング内容が不正
    """
    # パスとして直接指定された場合
    path = Path(mapping_name)
    if not path.suffix:
        path = MAPPINGS_DIR / f"{mapping_name}.json"
    
    if not path.exists():
        available = [m["name"] for m in list_mappings()]
        raise FileNotFoundError(
            f"マッピング '{mapping_name}' が見つかりません。\n"
            f"利用可能: {available}"
        )
    
    with open(path, encoding="utf-8") as f:
        mapping = json.load(f)
    
    _validate_mapping_structure(mapping, path)
    return mapping


def save_mapping(mapping: dict, mapping_name: str) -> Path:
    """
    マッピングプリセットをJSONとして保存する(GUIから呼ばれる想定)。
    
    Args:
        mapping: マッピング定義
        mapping_name: 拡張子なしのファイル名
    
    Returns:
        保存先パス
    """
    _validate_mapping_structure(mapping, None)
    MAPPINGS_DIR.mkdir(exist_ok=True, parents=True)
    
    path = MAPPINGS_DIR / f"{mapping_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    return path


def _validate_mapping_structure(mapping: dict, source: Optional[Path]) -> None:
    """マッピング定義の構造をチェック(値の妥当性はvalidate_mappingで別途)"""
    src = f"({source.name})" if source else ""
    if not isinstance(mapping, dict):
        raise ValueError(f"マッピングはdictである必要があります {src}")
    if "columns" not in mapping or not isinstance(mapping["columns"], dict):
        raise ValueError(f"マッピングに 'columns' (dict) が必要です {src}")
    
    # repair_id は必須
    columns = mapping["columns"]
    if "repair_id" not in columns or not columns["repair_id"]:
        raise ValueError(
            f"マッピングの columns に 'repair_id' のマッピングが必要です {src}"
        )
    
    # 少なくとも1つのコメントカラムがマッピングされている
    has_comment = any(
        columns.get(c) for c in COMMENT_LOGICAL_COLUMNS
    )
    if not has_comment:
        raise ValueError(
            f"マッピングに少なくとも1つのコメントカラム"
            f"(user_comment等)が必要です {src}"
        )


# ------------------------------------------------------------------
# DataFrame へのマッピング適用
# ------------------------------------------------------------------

def apply_column_mapping(
    df: pd.DataFrame,
    mapping: dict,
    strict: bool = False,
) -> pd.DataFrame:
    """
    物理カラム名のDataFrameを論理カラム名にリネームする。
    
    - マッピングに定義された物理カラム → 論理カラムにリネーム
    - passthrough_columns に指定された物理カラムはそのまま保持
    - 上記以外の物理カラムは破棄
    - マッピングで指定されたが実カラムにないコメントカラムは空列を作成
    
    Args:
        df: 物理カラム名のDataFrame
        mapping: マッピング定義
        strict: Trueなら必須カラム不足時にエラー、Falseなら警告のみ
    
    Returns:
        論理カラム名 + passthrough_columns のDataFrame
    """
    columns_map = mapping["columns"]
    passthrough = mapping.get("passthrough_columns", [])
    
    # 物理 → 論理のリネーム辞書を作成(値が None/空文字のものは除外)
    rename_dict = {
        physical: logical
        for logical, physical in columns_map.items()
        if physical and physical in df.columns
    }
    
    df_renamed = df.rename(columns=rename_dict)
    
    # 残すカラムを決定
    logical_present = [c for c in ALL_LOGICAL_COLUMNS if c in df_renamed.columns]
    passthrough_present = [c for c in passthrough if c in df_renamed.columns]
    kept_columns = logical_present + passthrough_present
    
    df_result = df_renamed[kept_columns].copy()
    
    # 欠落しているコメントカラムは空列で補う
    # (preprocess.py が row.get() するので存在自体は必須ではないが、
    #  明示的に空列を作っておく方が一貫性がある)
    for logical in COMMENT_LOGICAL_COLUMNS:
        if logical not in df_result.columns:
            df_result[logical] = ""
    
    # repair_id 不在は致命的
    if "repair_id" not in df_result.columns:
        msg = (
            f"必須カラム 'repair_id' (物理名: '{columns_map['repair_id']}') "
            f"が読み込み元データに存在しません。"
            f"\n読み込み元の実カラム: {list(df.columns)}"
        )
        if strict:
            raise ValueError(msg)
        else:
            print(f"❌ {msg}")
    
    return df_result


def validate_mapping(df: pd.DataFrame, mapping: dict) -> list[str]:
    """
    マッピングと実データの整合性をチェックし、警告メッセージのリストを返す。
    
    Args:
        df: 読み込んだ生のDataFrame(リネーム前)
        mapping: マッピング定義
    
    Returns:
        警告メッセージのリスト(空ならOK)
    """
    warnings = []
    columns_map = mapping["columns"]
    actual_columns = set(df.columns)
    
    # 必須カラムのチェック
    for logical in REQUIRED_LOGICAL_COLUMNS:
        physical = columns_map.get(logical)
        if not physical:
            warnings.append(f"必須論理カラム '{logical}' がマッピング未定義")
        elif physical not in actual_columns:
            warnings.append(
                f"必須カラム '{logical}' に対応する物理カラム "
                f"'{physical}' がCSV/SQL結果に存在しません"
            )
    
    # コメントカラムのチェック(欠落は警告のみ)
    missing_comments = []
    for logical in COMMENT_LOGICAL_COLUMNS:
        physical = columns_map.get(logical)
        if physical and physical not in actual_columns:
            missing_comments.append(f"{logical}→'{physical}'")
    if missing_comments:
        warnings.append(
            f"コメントカラム欠落(空列で補完): {', '.join(missing_comments)}"
        )
    
    # passthrough カラムのチェック
    passthrough = mapping.get("passthrough_columns", [])
    missing_pt = [c for c in passthrough if c not in actual_columns]
    if missing_pt:
        warnings.append(
            f"passthrough_columns に指定されたが存在しないカラム: {missing_pt}"
        )
    
    return warnings


# ------------------------------------------------------------------
# CSV ローダー
# ------------------------------------------------------------------

def load_from_csv(
    file_path: Union[str, Path],
    mapping_name: Optional[str] = None,
    mapping: Optional[dict] = None,
    encoding: str = "utf-8",
    verbose: bool = True,
) -> pd.DataFrame:
    """
    CSVから修理データを読み込み、論理カラム名のDataFrameを返す。
    
    Args:
        file_path: CSVファイルパス
        mapping_name: マッピングプリセット名(mapping_nameかmappingのどちらか)
        mapping: マッピング定義dict(直接指定)
        encoding: 文字コード(デフォルトUTF-8)
        verbose: True なら読み込み内容を表示
    
    Returns:
        論理カラム名のDataFrame
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSVファイルが存在しません: {file_path}")
    
    # マッピングを解決
    if mapping is None:
        if mapping_name is None:
            raise ValueError("mapping_name または mapping を指定してください")
        mapping = load_mapping(mapping_name)
    
    # CSV 読み込み(全カラムを文字列として読む。空セル → NaN は後段で処理)
    # dtype=str にすることで repair_id などの数値カラムが intになるのを防ぐ
    df_raw = pd.read_csv(file_path, encoding=encoding, dtype=str, keep_default_na=False)
    
    if verbose:
        print(f"CSV読み込み: {file_path.name}")
        print(f"  行数: {len(df_raw)}")
        print(f"  カラム: {list(df_raw.columns)}")
    
    # マッピング整合性チェック
    warnings = validate_mapping(df_raw, mapping)
    if warnings and verbose:
        print("マッピング警告:")
        for w in warnings:
            print(f"  ⚠️ {w}")
    
    # 論理カラム名にリネーム
    df = apply_column_mapping(df_raw, mapping)
    
    if verbose:
        print(f"  最終カラム: {list(df.columns)}")
    
    return df


# ------------------------------------------------------------------
# SQL ローダー(既存 db.py のラッパー)
# ------------------------------------------------------------------

def load_from_sql(
    sql: str,
    params: Optional[tuple] = None,
    mapping_name: Optional[str] = None,
    mapping: Optional[dict] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    SQL Serverから修理データを取得し、論理カラム名のDataFrameを返す。
    
    db.fetch_repair_data() のラッパー。SQL結果のカラム名は通常
    そのまま論理名に揃っている想定だが、違う場合のためにマッピングを受け取る。
    マッピング省略時は SQL 結果のカラム名をそのまま使用する。
    
    Args:
        sql: SQLクエリ
        params: SQLパラメータ
        mapping_name: マッピングプリセット名(SQL結果のカラム名が
                      論理名と違う場合に指定)
        mapping: マッピング定義dict(直接指定)
        verbose: True なら読み込み内容を表示
    
    Returns:
        論理カラム名のDataFrame
    """
    # 遅延 import: CSV しか使わないユーザーには pyodbc を要求しない
    import db
    
    df_raw = db.fetch_repair_data(sql, params)
    
    if verbose:
        print(f"SQL取得: {len(df_raw)}行")
        print(f"  カラム: {list(df_raw.columns)}")
    
    # マッピング未指定なら、SQL結果のカラム名がすでに論理名と仮定
    if mapping is None and mapping_name is None:
        # 必須カラムだけチェック
        if "repair_id" not in df_raw.columns:
            print("⚠️ 'repair_id' カラムが見つかりません。"
                  "SQL のSELECT句を確認するか、マッピングを指定してください。")
        # コメントカラムが欠落していれば空列を補う
        for logical in COMMENT_LOGICAL_COLUMNS:
            if logical not in df_raw.columns:
                df_raw[logical] = ""
        return df_raw
    
    # マッピング指定あり
    if mapping is None:
        mapping = load_mapping(mapping_name)
    
    warnings = validate_mapping(df_raw, mapping)
    if warnings and verbose:
        print("マッピング警告:")
        for w in warnings:
            print(f"  ⚠️ {w}")
    
    return apply_column_mapping(df_raw, mapping)


# ------------------------------------------------------------------
# 簡易プレビュー(GUI/Notebook共通で使う想定)
# ------------------------------------------------------------------

def preview_csv_columns(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    n_rows: int = 5,
) -> tuple[list[str], pd.DataFrame]:
    """
    CSVのカラム名と先頭数行を取得(マッピング作成のサポート用)。
    GUIで「新規マッピング作成」時に、ユーザーに実カラム名を見せるために使用。
    
    Returns:
        (カラム名のリスト, 先頭n_rows行のDataFrame)
    """
    df = pd.read_csv(file_path, encoding=encoding, nrows=n_rows, dtype=str,
                     keep_default_na=False)
    return list(df.columns), df
