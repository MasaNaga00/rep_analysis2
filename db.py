"""
db.py - MS SQL Serverからの修理データ取得

pyodbcを使用。大量データはpandas.read_sqlでDataFrame化。
"""
import pyodbc
import pandas as pd
from contextlib import contextmanager
from typing import Optional

import config


def _build_connection_string() -> str:
    """ODBC接続文字列を構築"""
    return (
        f"DRIVER={config.MSSQL_DRIVER};"
        f"SERVER={config.MSSQL_SERVER};"
        f"DATABASE={config.MSSQL_DATABASE};"
        f"UID={config.MSSQL_USER};"
        f"PWD={config.MSSQL_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )


@contextmanager
def get_connection():
    """コンテキストマネージャで接続管理"""
    conn = pyodbc.connect(_build_connection_string())
    try:
        yield conn
    finally:
        conn.close()


def fetch_repair_data(
    sql: str,
    params: Optional[tuple] = None,
) -> pd.DataFrame:
    """
    SQLで修理データを取得してDataFrameで返す。
    
    Args:
        sql: 実行するSQLクエリ（プレースホルダは?）
        params: SQLパラメータ
    
    Returns:
        修理データのDataFrame
        必須カラム: repair_id, user_comment, repair_comment, internal_1, internal_2
    
    Example:
        >>> sql = '''
        ...     SELECT repair_id, user_comment, repair_comment, internal_1, internal_2
        ...     FROM repair_records
        ...     WHERE model = ? AND repair_date >= ?
        ... '''
        >>> df = fetch_repair_data(sql, ('EOS R7', '2024-01-01'))
    """
    with get_connection() as conn:
        df = pd.read_sql(sql, conn, params=params)
    return df


def fetch_by_model_and_period(
    model: str,
    date_from: str,
    date_to: Optional[str] = None,
    symptom_keyword: Optional[str] = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """
    機種・期間・キーワードで修理データを絞り込む便利関数。
    
    実運用ではここをカスタマイズしてください。
    """
    sql = """
        SELECT TOP (?)
            repair_id,
            model,
            repair_date,
            country_code,
            user_comment,
            repair_comment,
            internal_1,
            internal_2
        FROM repair_records
        WHERE model = ?
          AND repair_date >= ?
    """
    params = [limit, model, date_from]
    
    if date_to:
        sql += " AND repair_date <= ?"
        params.append(date_to)
    
    if symptom_keyword:
        # 4カラムのいずれかにキーワードが含まれる
        sql += """
          AND (
            user_comment LIKE ? OR
            repair_comment LIKE ? OR
            internal_1 LIKE ? OR
            internal_2 LIKE ?
          )
        """
        like = f"%{symptom_keyword}%"
        params.extend([like, like, like, like])
    
    sql += " ORDER BY repair_date DESC"
    
    return fetch_repair_data(sql, tuple(params))
