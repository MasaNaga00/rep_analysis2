"""
scoring.py - タグ付け結果のマッチングスコア計算・保存

- core軸一致で強くフィルタ
- detail軸一致でボーナス
- overall_relevanceで最終調整
- DataFrameへのフラット化・Parquet保存
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

import config


# ---------- 型正規化ヘルパー ----------
#
# 【重要・削除禁止】このセクションの正規化は実際のバグ対策です。
# Dify は insufficient_info を bool / 文字列 "true" / キー欠落(None) で混在して返し、
# overall_relevance や conf__* も文字列や None で返すことがある。
# そのまま DataFrame に入れると列が object 型になり、Parquet/Excel 書き込みが
# 「Conversion failed for column ... with type object」で失敗する。
# 「冗長」に見えても削除しないこと。詳細は AI_HANDOFF.md §2-3,4。

def _to_bool(v) -> bool:
    """
    Difyの戻り値に混在しうる bool/str/None を bool に正規化する。
    "false"/"0"/"no"/"" 等は False、"true"/"1"/"yes"/"はい" 等は True。
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "はい")
    return bool(v)


def _to_float(v, default: float = 0.0) -> float:
    """
    数値列(overall_relevance, conf__*)を float に正規化する。
    None・空文字・パース不能値は default にフォールバック。
    """
    if isinstance(v, bool):
        # bool は数値扱いしない(True/False が 1.0/0.0 になるのを防ぐ)
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return default
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    保存前に列の dtype を確定させ、object 型混在による
    Parquet/Excel 書き込みエラーを防ぐ。
    
    - insufficient_info: bool
    - overall_relevance / conf__* / match_score: float
    - tag__* / evidence__* / 文字列系: object のまま(NaN は空文字へ)
    """
    df = df.copy()
    
    if "insufficient_info" in df.columns:
        df["insufficient_info"] = df["insufficient_info"].apply(_to_bool).astype(bool)
    
    float_cols = ["overall_relevance", "match_score"]
    float_cols += [c for c in df.columns if c.startswith("conf__")]
    for c in float_cols:
        if c in df.columns:
            df[c] = df[c].apply(_to_float).astype(float)
    
    # 文字列系の列は NaN/None を空文字に揃える(Excel/Parquet で型がブレないように)
    str_cols = [c for c in df.columns
                if c.startswith(("tag__", "evidence__"))
                or c in ("repair_id", "language_detected",
                         "relevance_reason", "insufficient_reason")]
    for c in str_cols:
        if c in df.columns:
            df[c] = df[c].where(df[c].notna(), "").astype(object)
    
    return df


def flatten_tagging_results(
    batch_results: list[dict],
    schema: dict,
) -> pd.DataFrame:
    """
    バッチ結果をDataFrameにフラット化。
    各軸のtag/confidence/evidenceが列になる。
    
    Args:
        batch_results: tag_records_batchの戻り値
        schema: 1回目のスキーマ
    
    Returns:
        1行=1修理レコードのDataFrame
    """
    axes_names = [ax["name"] for ax in schema["axes"]]
    
    rows = []
    errors = []
    
    for batch in batch_results:
        if not batch["success"]:
            errors.append({
                "batch_idx": batch["batch_idx"],
                "input_ids": batch["input_ids"],
                "error": batch["error"],
            })
            continue
        
        for item in batch["results"]:
            row = {
                "repair_id": item.get("repair_id"),
                "language_detected": item.get("language_detected"),
                "overall_relevance": _to_float(item.get("overall_relevance", 0.0)),
                "relevance_reason": item.get("relevance_reason", ""),
                "insufficient_info": _to_bool(item.get("insufficient_info", False)),
                "insufficient_reason": item.get("insufficient_reason", ""),
            }
            
            tags = item.get("tags", {})
            confidence = item.get("confidence", {})
            evidence = item.get("evidence", {})
            
            for ax in axes_names:
                row[f"tag__{ax}"] = tags.get(ax)
                row[f"conf__{ax}"] = _to_float(confidence.get(ax, 0.0))
                row[f"evidence__{ax}"] = evidence.get(ax, "")
            
            rows.append(row)
    
    df = pd.DataFrame(rows)
    
    if errors:
        print(f"⚠️  {len(errors)}件のバッチでエラー発生")
        for e in errors[:5]:
            print(f"  - batch {e['batch_idx']}: {e['error'][:100]}")
    
    return df


def score_record(
    row: pd.Series,
    query_tags: dict,
    schema: dict,
    core_match_weight: float = 5.0,
    detail_match_weight: float = 1.0,
) -> float:
    """
    1レコードのマッチングスコア計算。
    
    Args:
        row: flatten後のDataFrameの1行
        query_tags: 問い合わせ側のタグ（コア軸は必須）
        schema: タグスキーマ
    
    Returns:
        スコア（0.0 〜）。0.0はcore軸不一致。
    """
    score = 0.0
    
    # 【不変条件】core軸は「ちょうど1個」前提。0個だと StopIteration、
    # 複数あると先頭1個のみ使用。スキーマ生成プロンプト(Dify側)でも1個に制約している。
    # tier は "core"/"detail" の2値のみ。詳細は AI_HANDOFF.md §2-1,2。
    core_axis = next(ax for ax in schema["axes"] if ax["tier"] == "core")
    detail_axes = [ax for ax in schema["axes"] if ax["tier"] == "detail"]
    
    # core軸：不一致なら即0
    core_name = core_axis["name"]
    rec_core = row.get(f"tag__{core_name}")
    query_core = query_tags.get(core_name)
    
    if rec_core != query_core:
        return 0.0
    
    score += core_match_weight * row.get(f"conf__{core_name}", 0.0)
    
    # detail軸：一致ごとにボーナス（「不明」同士は加点しない）
    for ax in detail_axes:
        name = ax["name"]
        rec_val = row.get(f"tag__{name}")
        query_val = query_tags.get(name)
        
        if rec_val == query_val and rec_val not in ("不明", "該当なし", None):
            score += detail_match_weight * row.get(f"conf__{name}", 0.0)
    
    # LLMのoverall_relevanceで最終調整
    score *= (0.5 + row.get("overall_relevance", 0.0))
    
    return score


def rank_results(
    df: pd.DataFrame,
    query_tags: dict,
    schema: dict,
    min_relevance: float = 0.3,
    top_n: Optional[int] = None,
) -> pd.DataFrame:
    """
    スコアを計算して並び替え。
    
    Args:
        df: flatten_tagging_resultsの出力
        query_tags: 問い合わせ側のタグ
        schema: タグスキーマ
        min_relevance: overall_relevanceの最低閾値
        top_n: 上位N件のみ返す
    
    Returns:
        match_score列を追加してソートしたDataFrame
    """
    df = df.copy()
    df["match_score"] = df.apply(
        lambda row: score_record(row, query_tags, schema),
        axis=1,
    )
    
    # フィルタとソート
    filtered = df[
        (df["match_score"] > 0) &
        (df["overall_relevance"] >= min_relevance)
    ].sort_values("match_score", ascending=False)
    
    if top_n:
        filtered = filtered.head(top_n)
    
    return filtered.reset_index(drop=True)


def save_results(
    tagged_df: pd.DataFrame,
    ranked_df: pd.DataFrame,
    schema: dict,
    inquiry_text: str,
    output_dir: Optional[Path] = None,
    tag: str = "",
) -> dict:
    """
    結果一式を保存。
    
    - tagged: 全タグ付け結果（Parquet）
    - ranked: スコア付き絞り込み結果（Parquet + CSV）
    - schema: 使用したスキーマ（JSON）
    - meta: 実行メタ情報（JSON）
    
    Returns:
        保存パス辞書
    """
    output_dir = output_dir or config.OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    # 保存前に dtype を確定(object 型混在による書き込みエラーを防ぐ)
    tagged_df = _coerce_dtypes(tagged_df)
    ranked_df = _coerce_dtypes(ranked_df)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{timestamp}_{tag}" if tag else timestamp
    
    paths = {
        "results_xlsx": output_dir / f"{prefix}_results.xlsx",
        "tagged_parquet": output_dir / f"{prefix}_tagged.parquet",
        "ranked_parquet": output_dir / f"{prefix}_ranked.parquet",
        "schema_json": output_dir / f"{prefix}_schema.json",
        "meta_json": output_dir / f"{prefix}_meta.json",
    }
    
    tagged_df.to_parquet(paths["tagged_parquet"], index=False)
    ranked_df.to_parquet(paths["ranked_parquet"], index=False)
    # Excel: 1ファイルに「全件(tagged)」「絞り込み(ranked)」を別シートで出力。
    # Excel で確認したいユーザ向け。Tableau もこの xlsx を直接読める。
    with pd.ExcelWriter(paths["results_xlsx"], engine="openpyxl") as writer:
        tagged_df.to_excel(writer, index=False, sheet_name="tagged")
        ranked_df.to_excel(writer, index=False, sheet_name="ranked")
    
    with open(paths["schema_json"], "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    
    meta = {
        "timestamp": timestamp,
        "inquiry_text": inquiry_text,
        "query_summary": schema.get("query_summary", ""),
        "total_tagged": len(tagged_df),
        "total_ranked": len(ranked_df),
        "top_score": float(ranked_df["match_score"].max()) if len(ranked_df) else 0.0,
    }
    with open(paths["meta_json"], "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    return {k: str(v) for k, v in paths.items()}
