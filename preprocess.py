"""
preprocess.py - 修理コメントの整形・前処理

- NaN/None処理
- 定型句・署名除去
- 言語検出
- カラムラベル付き結合
- トークン節約のための整形
"""
import re
import pandas as pd
from typing import Optional

import config


# 除去する定型句のパターン（必要に応じて追加）
BOILERPLATE_PATTERNS = [
    r"お世話になっております[。、]?",
    r"よろしくお願い(?:いた)?します[。、]?",
    r"以上[、，,]?\s*よろしく",
    r"Best regards[,.]?",
    r"Thank you[,.]?",
    r"敬具",
    r"--+",  # 区切り線
    r"={3,}",
]


def clean_comment(text: Optional[str]) -> str:
    """
    コメントのクリーニング。
    
    - None/NaN → 空文字列
    - 定型句除去
    - 連続空白・改行の正規化
    - 最大長でトリム
    """
    if text is None or pd.isna(text):
        return ""
    
    text = str(text).strip()
    if not text:
        return ""
    
    # 定型句除去
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    
    # 連続空白・改行の正規化
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    
    # 最大長トリム
    if len(text) > config.MAX_COMMENT_LENGTH:
        text = text[:config.MAX_COMMENT_LENGTH] + "..."
    
    return text


def detect_language(text: str) -> str:
    """
    簡易言語検出。文字種から判定（langdetectは不要）。
    
    Returns:
        "ja" | "zh" | "ko" | "en" | "unknown"
    """
    if not text:
        return "unknown"
    
    # ひらがな・カタカナ → 日本語確定
    if re.search(r"[ぁ-んァ-ヶ]", text):
        return "ja"
    
    # ハングル → 韓国語
    if re.search(r"[가-힣]", text):
        return "ko"
    
    # CJK統合漢字のみで、ひらがな・ハングルがない → 中国語
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    
    # ASCII主体 → 英語
    if re.search(r"[a-zA-Z]", text):
        return "en"
    
    return "unknown"


def classify_length_tier(total_length: int) -> str:
    """コメント合計長からtierを判定"""
    if total_length < 50:
        return "minimal"
    elif total_length < 200:
        return "standard"
    else:
        return "detailed"


def format_record_for_dify(row: pd.Series) -> dict:
    """
    1行の修理データをDify入力形式に整形。
    
    Returns:
        {
            "repair_id": str,
            "records": str,   # カラムラベル付き結合済みテキスト
            "meta": {...}      # 参考情報
        }
    """
    # 各コメントをクリーニング
    cols = {
        "U": clean_comment(row.get("user_comment")),
        "R": clean_comment(row.get("repair_comment")),
        "I1": clean_comment(row.get("internal_1")),
        "I2": clean_comment(row.get("internal_2")),
    }
    
    # 全文結合して言語検出（最も情報量の多いテキストから判定）
    combined = " ".join(v for v in cols.values() if v)
    language = detect_language(combined)
    total_length = len(combined)
    length_tier = classify_length_tier(total_length)
    
    # カラムラベル付き整形
    lines = [f"[META] length_tier: {length_tier}, lang: {language}"]
    for label, text in cols.items():
        if text:
            lines.append(f"[{label}] {text}")
    
    records_text = "\n".join(lines)
    
    return {
        "repair_id": str(row["repair_id"]),
        "records": records_text,
        "meta": {
            "language": language,
            "length_tier": length_tier,
            "total_length": total_length,
            "has_user_comment": bool(cols["U"]),
            "has_repair_comment": bool(cols["R"]),
            "has_internal": bool(cols["I1"] or cols["I2"]),
        }
    }


def prepare_records(df: pd.DataFrame) -> list[dict]:
    """
    DataFrame全体をDify投入用のリストに変換。
    """
    return [format_record_for_dify(row) for _, row in df.iterrows()]


def chunk_records(records: list[dict], batch_size: int) -> list[list[dict]]:
    """レコードをバッチサイズで分割"""
    return [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
