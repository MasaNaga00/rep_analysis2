# -*- coding: utf-8 -*-
"""copilot_export.py — Microsoft 365 Copilot エージェント向けエクスポート

scoring.save_results() の出力（results.xlsx 等）とは独立に、
Copilot のナレッジソースとして検索しやすいファイル群を生成する。

出力（out_dir 直下）:
  {session}_00_overview.txt        … 概要（問い合わせ・スキーマ・分布・ランキング・用語）
  {session}_10_{core値}_{NN}.txt   … レコードカード（core軸値ごとに分割、各30,000字以内）
  {session}_90_ranked_flat.xlsx    … ranked を単一シート・日本語列名で出力（集計質問用）

設計メモ:
- tagged_df / ranked_df は scoring.flatten_tagging_results / rank_results の出力を想定
  （型は _coerce_dtypes 済みである前提。ここでは再正規化しない）
- 原文コメント（user_comment / repair_comment）が tagged_df に無い場合は
  source_df（loader の読み込み結果）を repair_id で結合して補う
- 書き込み先 out_dir は呼び出し側が決める（frozen 環境で __file__ 基準のパスを渡さないこと）
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 調整可能な定数 ────────────────────────────────────────────
MAX_FILE_CHARS = 30_000      # 1ファイルの上限（Copilot推奨36,000字に対する安全マージン）
COMMENT_MAX_CHARS = 600      # コメント原文の切り詰め長
TOP_N_OVERVIEW = 10          # 概要に載せるランキング件数
LOW_CONF = 0.5               # 「参考程度」とみなす確信度のしきい値（用語説明に使用）
SKIP_DETAIL_VALUES = {"不明", "該当なし", "", None}  # detail軸で根拠を省略する値

CARD_SEP = "─" * 40

# 指示プロンプトと文言を揃えること（二重化が目的）
GLOSSARY = f"""【用語の説明】
- core軸: 最重要の分類軸（このセッションでは1つ）。集計・傾向分析はこの軸を基準にする。
- detail軸: 補助的な分類軸（0〜4個）。
- 確信度: 0〜1。AIによる分類の確からしさ。{LOW_CONF}未満は参考程度として扱うこと。
- 関連度（overall_relevance）: 0〜1。問い合わせ内容との近さ。
- ランク: 関連度等に基づく絞り込み結果での順位。ランク表記が無いレコードは絞り込み対象外。
- 情報不足（insufficient_info）: 原文の情報が少なく、分類の信頼性が低いレコード。
- 「不明」: 原文から判断できなかったことを示す。「該当なし」: その軸が当てはまらないことを示す。"""


# ── 内部ユーティリティ ────────────────────────────────────────
def _sanitize_filename(name: str, max_len: int = 24) -> str:
    """core軸の値などをファイル名に使える形に整える。"""
    s = str(name).strip()
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", s)
    s = s.strip("._") or "値なし"
    return s[:max_len]


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def _fmt_conf(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "－"


def _trunc(text, limit: int = COMMENT_MAX_CHARS) -> str:
    if _is_blank(text):
        return "（記載なし）"
    s = str(text).strip()
    if len(s) <= limit:
        return s
    return s[:limit] + f"…（以下省略・全文は results.xlsx を参照）"


def _core_axis(schema: dict) -> dict:
    return next(a for a in schema["axes"] if a.get("tier") == "core")


def _detail_axes(schema: dict) -> list[dict]:
    return [a for a in schema["axes"] if a.get("tier") == "detail"]


def _ensure_comments(tagged_df: pd.DataFrame, source_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """user_comment / repair_comment が無ければ source_df から repair_id で補う。"""
    df = tagged_df.copy()
    missing = [c for c in ("user_comment", "repair_comment") if c not in df.columns]
    if missing and source_df is not None:
        cols = ["repair_id"] + [c for c in missing if c in source_df.columns]
        if len(cols) > 1:
            # dtype不一致（SQL由来のint vs Dify由来のstr等）でmergeが空振りしないよう
            # 結合キーは両側とも文字列に正規化する
            src = source_df[cols].drop_duplicates("repair_id").copy()
            src["repair_id"] = src["repair_id"].astype(str).str.strip()
            df["_join_key"] = df["repair_id"].astype(str).str.strip()
            df = df.merge(
                src.rename(columns={"repair_id": "_join_key"}),
                on="_join_key", how="left",
            ).drop(columns="_join_key")
    for c in ("user_comment", "repair_comment"):
        if c not in df.columns:
            df[c] = None
    return df


def _rank_map(ranked_df: Optional[pd.DataFrame]) -> dict:
    """repair_id -> 1始まりの順位（ranked_df の並び順を信頼する）。"""
    if ranked_df is None or ranked_df.empty or "repair_id" not in ranked_df.columns:
        return {}
    return {rid: i + 1 for i, rid in enumerate(ranked_df["repair_id"].tolist())}


# ── カード生成 ────────────────────────────────────────────────
def build_card(row: pd.Series, schema: dict, rank: Optional[int] = None) -> str:
    core = _core_axis(schema)
    lines = [CARD_SEP]

    # ヘッダ行
    head = f"■ 修理ID: {row.get('repair_id', '不明')}"
    rel = row.get("overall_relevance")
    if not _is_blank(rel):
        head += f" ｜ 関連度: {_fmt_conf(rel)}"
    if rank is not None:
        head += f" ｜ ランク: {rank}位"
    lines.append(head)

    # 情報不足はヘッダ直下に置く（エージェントの注記ルール適用を助ける）
    if bool(row.get("insufficient_info", False)):
        reason = row.get("insufficient_reason")
        lines.append(f"情報不足: あり（理由: {reason if not _is_blank(reason) else '記載なし'}）")

    # core軸（常に根拠付き）
    val = row.get(f"tag__{core['name']}")
    conf = row.get(f"conf__{core['name']}")
    ev = row.get(f"evidence__{core['name']}")
    lines.append(f"{core['name']}（core軸）: {val if not _is_blank(val) else '不明'} ［確信度 {_fmt_conf(conf)}］")
    if not _is_blank(ev):
        lines.append(f"  根拠: {ev}")

    # detail軸（不明・該当なしは1行に圧縮）
    for ax in _detail_axes(schema):
        v = row.get(f"tag__{ax['name']}")
        v_disp = "不明" if _is_blank(v) else str(v)
        if v_disp in SKIP_DETAIL_VALUES or _is_blank(v):
            lines.append(f"{ax['name']}: {v_disp}")
            continue
        conf_d = _fmt_conf(row.get("conf__" + ax["name"]))
        lines.append(f"{ax['name']}: {v_disp} ［確信度 {conf_d}］")
        ev = row.get("evidence__" + ax["name"])
        if not _is_blank(ev):
            lines.append(f"  根拠: {ev}")

    # 関連度の理由・言語
    rr = row.get("relevance_reason")
    if not _is_blank(rr):
        lines.append(f"関連度の理由: {rr}")
    lang = row.get("language_detected")
    if not _is_blank(lang):
        lines.append(f"検出言語: {lang}")

    # 原文コメント
    lines.append("ユーザーコメント:")
    lines.append(f"  {_trunc(row.get('user_comment'))}")
    lines.append("修理コメント:")
    lines.append(f"  {_trunc(row.get('repair_comment'))}")

    return "\n".join(lines)


# ── 概要生成 ──────────────────────────────────────────────────
def build_overview(
    tagged_df: pd.DataFrame,
    ranked_df: Optional[pd.DataFrame],
    schema: dict,
    inquiry_text: str,
    session_id: str,
    manifest: list[tuple[str, int]],
    top_n: int = TOP_N_OVERVIEW,
) -> str:
    core = _core_axis(schema)
    total = len(tagged_df)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = [
        "=" * 42,
        f"分類結果 概要 ｜ セッション: {session_id}",
        f"作成日時: {now} ｜ 総レコード数: {total}件",
        "=" * 42,
        "",
        "【問い合わせ内容】",
        str(inquiry_text).strip() or "（記載なし）",
        "",
        "【問い合わせの要約】",
        str(schema.get("query_summary", "")).strip() or "（なし）",
        "",
        "【分類軸（スキーマ）】",
    ]
    for i, ax in enumerate([core] + _detail_axes(schema), start=1):
        tier = "core軸・最重要の分類軸" if ax.get("tier") == "core" else "detail軸"
        parts.append(f"{i}. {ax['name']}（{tier}）")
        if ax.get("description"):
            parts.append(f"   説明: {ax['description']}")
        if ax.get("candidates"):
            parts.append(f"   候補値: {' / '.join(map(str, ax['candidates']))}")

    # core軸の件数分布
    parts += ["", f"【core軸「{core['name']}」の件数分布】"]
    col = f"tag__{core['name']}"
    if col in tagged_df.columns and total > 0:
        vc = tagged_df[col].fillna("不明").astype(str).value_counts()
        for v, n in vc.items():
            parts.append(f"- {v}: {n}件 ({n / total * 100:.1f}%)")
    else:
        parts.append("（分布を集計できませんでした）")

    # 情報不足
    if "insufficient_info" in tagged_df.columns:
        k = int(tagged_df["insufficient_info"].fillna(False).astype(bool).sum())
        parts += ["", f"【情報不足レコード】 {k}件（タグの信頼性が低い）"]

    # ランキング上位
    parts += ["", f"【関連度ランキング 上位{top_n}件】"]
    if ranked_df is not None and not ranked_df.empty:
        core_col = f"tag__{core['name']}"
        for i, (_, r) in enumerate(ranked_df.head(top_n).iterrows(), start=1):
            line = f"{i}. {r.get('repair_id', '不明')} ｜ 関連度{_fmt_conf(r.get('overall_relevance'))}"
            if core_col in ranked_df.columns and not _is_blank(r.get(core_col)):
                line += f" ｜ {r.get(core_col)}"
            rr = r.get("relevance_reason")
            if not _is_blank(rr):
                line += f" ｜ 理由: {_trunc(rr, 80)}"
            parts.append(line)
    else:
        parts.append("（絞り込み結果なし）")

    parts += ["", GLOSSARY, "", "【レコードファイル一覧】"]
    for fname, n in manifest:
        parts.append(f"- {fname}: {n}件")

    parts += [
        "",
        "※ 本ファイル群はAIタグ付けシステムの出力です。タグ・確信度・関連度はAIによる推定値であり、",
        "  個別事例の正確な内容は修理ID（repair_id）で原本システムを確認してください。",
    ]
    return "\n".join(parts)


# ── ranked 単一シートxlsx ─────────────────────────────────────
def _japanese_rename_map(columns, schema: dict) -> dict:
    m = {
        "repair_id": "修理ID",
        "overall_relevance": "関連度",
        "relevance_reason": "関連度の理由",
        "match_score": "一致スコア",
        "insufficient_info": "情報不足",
        "insufficient_reason": "情報不足の理由",
        "language_detected": "検出言語",
        "user_comment": "ユーザーコメント",
        "repair_comment": "修理コメント",
    }
    rename = {}
    for c in columns:
        if c in m:
            rename[c] = m[c]
        elif c.startswith("tag__"):
            rename[c] = c[len("tag__"):]
        elif c.startswith("conf__"):
            rename[c] = c[len("conf__"):] + "_確信度"
        elif c.startswith("evidence__"):
            rename[c] = c[len("evidence__"):] + "_根拠"
    return rename


# ── エントリポイント ──────────────────────────────────────────
def export_for_copilot(
    tagged_df: pd.DataFrame,
    ranked_df: Optional[pd.DataFrame],
    schema: dict,
    inquiry_text: str,
    out_dir: Path,
    session_id: Optional[str] = None,
    source_df: Optional[pd.DataFrame] = None,
    max_file_chars: int = MAX_FILE_CHARS,
) -> dict[str, Path]:
    """Copilot向けファイル群を out_dir に出力し、{名前: パス} を返す。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not session_id:
        session_id = "S" + datetime.now().strftime("%Y%m%d-%H%M")
    sid = _sanitize_filename(session_id, max_len=40)

    core = _core_axis(schema)
    df = _ensure_comments(tagged_df, source_df)
    ranks = _rank_map(ranked_df)
    outputs: dict[str, Path] = {}
    manifest: list[tuple[str, int]] = []

    # ── レコードカード（core軸値ごと → 文字数で分割） ──
    core_col = f"tag__{core['name']}"
    group_key = df[core_col].fillna("不明").astype(str) if core_col in df.columns else pd.Series(["不明"] * len(df))

    for core_val, g in df.groupby(group_key, sort=False):
        if "overall_relevance" in g.columns:
            g = g.sort_values("overall_relevance", ascending=False)
        slug = _sanitize_filename(core_val)

        chunk_lines: list[str] = []
        chunk_count = 0
        chunk_chars = 0
        file_idx = 1

        def _flush():
            nonlocal chunk_lines, chunk_count, chunk_chars, file_idx
            if not chunk_lines:
                return
            fname = f"{sid}_10_{slug}_{file_idx:02d}.txt"
            header = (
                f"レコードカード ｜ セッション: {session_id} ｜ "
                f"{core['name']}: {core_val} ｜ 本ファイル {chunk_count}件\n"
            )
            path = out_dir / fname
            path.write_text(header + "\n".join(chunk_lines) + "\n", encoding="utf-8")
            outputs[fname] = path
            manifest.append((fname, chunk_count))
            file_idx += 1
            chunk_lines, chunk_count, chunk_chars = [], 0, 0

        for _, row in g.iterrows():
            card = build_card(row, schema, rank=ranks.get(row.get("repair_id")))
            if chunk_chars + len(card) > max_file_chars and chunk_lines:
                _flush()
            chunk_lines.append(card)
            chunk_count += 1
            chunk_chars += len(card)
        _flush()

    # ── 概要（manifest が揃ってから） ──
    overview_name = f"{sid}_00_overview.txt"
    overview_path = out_dir / overview_name
    overview_path.write_text(
        build_overview(df, ranked_df, schema, inquiry_text, session_id, manifest) + "\n",
        encoding="utf-8",
    )
    outputs[overview_name] = overview_path

    # ── ranked 単一シートxlsx（日本語列名） ──
    if ranked_df is not None and not ranked_df.empty:
        flat_name = f"{sid}_90_ranked_flat.xlsx"
        flat = ranked_df.rename(columns=_japanese_rename_map(ranked_df.columns, schema))
        flat.to_excel(out_dir / flat_name, sheet_name="ranked", index=False)
        outputs[flat_name] = out_dir / flat_name

    return outputs
