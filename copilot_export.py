# -*- coding: utf-8 -*-
"""copilot_export.py — Microsoft 365 Copilot エージェント向けエクスポート

scoring.save_results() の出力（results.xlsx 等）とは独立に、
Copilot のナレッジソースとして検索しやすいファイル群を生成する。

出力（out_dir 直下、常用の3ファイル）:
  {session}_00_overview.txt        … 概要（問い合わせ・スキーマ・分布・関連度上位・同梱ファイル説明・用語）
  {session}_10_representative.txt  … 代表カード（core軸値ごとに関連度上位 REPRESENTATIVE_PER_CORE 件）
  {session}_90_tagged_flat.xlsx    … tagged全件・コメント原文入り・日本語列名（集計と原文確認はこれ）

設計方針:
- Copilot に常用で渡すのは上記3ファイルのみ。多数のカードtxtを渡す運用は廃止。
- 全件の詳細（コメント原文含む）は tagged_flat.xlsx に集約。件数集計・原文確認はxlsxで完結する
  （Copilot側で Code Interpreter を有効にすること）。
- txt の代表カードは「自然文で読ませて要約・類似把握させる」ための補助。

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
REPRESENTATIVE_PER_CORE = 3  # 代表カード: core軸の値ごとに何件ずつ載せるか（関連度降順）
MAX_FILE_CHARS = 35_000      # 代表カードファイルの上限（Copilot推奨36,000字に対する安全マージン）
                             # 代表件数が多くこれを超える場合は超過分を割愛し、その旨を末尾に明記する
COMMENT_MAX_CHARS = 600      # コメント原文の切り詰め長（カード用。xlsxは原文を切り詰めない）
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
    schema: dict,
    inquiry_text: str,
    session_id: str,
    rep_info: dict,
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

    # 関連度上位（tagged全件を関連度降順で並べた上位N件）
    parts += ["", f"【関連度 上位{top_n}件（全{total}件中）】"]
    core_col = f"tag__{core['name']}"
    if "overall_relevance" in tagged_df.columns and total > 0:
        top = tagged_df.sort_values("overall_relevance", ascending=False).head(top_n)
        for i, (_, r) in enumerate(top.iterrows(), start=1):
            line = f"{i}. {r.get('repair_id', '不明')} ｜ 関連度{_fmt_conf(r.get('overall_relevance'))}"
            if core_col in tagged_df.columns and not _is_blank(r.get(core_col)):
                line += f" ｜ {r.get(core_col)}"
            rr = r.get("relevance_reason")
            if not _is_blank(rr):
                line += f" ｜ 理由: {_trunc(rr, 80)}"
            parts.append(line)
    else:
        parts.append("（関連度の情報がありません）")

    parts += ["", GLOSSARY, "", "【このセッションの同梱ファイル】"]
    parts.append(f"- {session_id}_00_overview.txt: 本ファイル（概要）")
    parts.append(
        f"- {session_id}_10_representative.txt: 代表レコードカード"
        f"（各core軸値ごとに関連度上位{rep_info.get('per_core', REPRESENTATIVE_PER_CORE)}件、"
        f"計{rep_info.get('selected', 0)}件）"
    )
    parts.append(
        f"- {session_id}_90_tagged_flat.xlsx: 全{total}件の一覧"
        "（コメント原文・全タグ・確信度・関連度を含む。件数集計や個別事例の原文確認はこれを使う）"
    )
    parts += ["", "【代表カードの内訳】（残りは tagged_flat.xlsx を参照）"]
    for cval, d in rep_info.get("core_breakdown", {}).items():
        parts.append(f"- {cval}: 代表{d['selected']}件 / 全{d['total']}件")

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

    # ── 代表カード（1ファイル） ──
    # 方針: core軸の値ごとに関連度上位 REPRESENTATIVE_PER_CORE 件を選び、1ファイルにまとめる。
    #   全件は _90_tagged_flat.xlsx（コメント原文入り）にあるため、txtは「代表のみ」に絞り、
    #   常用で渡すファイルを 概要 + 代表カード + 全件xlsx の3つに収める。
    core_col = f"tag__{core['name']}"
    rep_name = f"{sid}_10_representative.txt"
    rep_info = {"per_core": REPRESENTATIVE_PER_CORE, "selected": 0, "omitted": 0, "core_breakdown": {}}

    if core_col in df.columns:
        group_key = df[core_col].fillna("不明").astype(str)
    else:
        group_key = pd.Series(["不明"] * len(df), index=df.index)

    sections: list[str] = []
    for core_val, g in group_key.groupby(group_key, sort=False):
        sub = df.loc[g.index]
        if "overall_relevance" in sub.columns:
            sub = sub.sort_values("overall_relevance", ascending=False)
        n_total = len(sub)
        picked = sub.head(REPRESENTATIVE_PER_CORE)
        rep_info["selected"] += len(picked)
        rep_info["omitted"] += max(0, n_total - len(picked))
        rep_info["core_breakdown"][core_val] = {"selected": len(picked), "total": n_total}

        sections.append(
            f"\n【{core['name']}: {core_val}】 代表 {len(picked)}件 / 全{n_total}件"
            + ("（残りは tagged_flat.xlsx を参照）" if n_total > len(picked) else "")
        )
        for _, row in picked.iterrows():
            sections.append(build_card(row, schema, rank=ranks.get(row.get("repair_id"))))

    rep_header = (
        f"代表レコードカード ｜ セッション: {session_id}\n"
        f"各「{core['name']}」（core軸）の値ごとに関連度の高い順で最大{REPRESENTATIVE_PER_CORE}件を掲載。\n"
        f"掲載 {rep_info['selected']}件 / 全{len(df)}件。"
        f"全件の詳細（コメント原文含む）は同梱の tagged_flat.xlsx を参照してください。\n"
    )
    rep_body = rep_header + "\n".join(sections) + "\n"

    # 念のための文字数ガード（超過時は末尾の代表から削る方針で割愛を明記）
    if len(rep_body) > MAX_FILE_CHARS:
        rep_body = (
            rep_body[:MAX_FILE_CHARS]
            + "\n\n※ 文字数上限のため一部の代表カードを割愛しました。"
              "全件は tagged_flat.xlsx を参照してください。\n"
        )

    rep_path = out_dir / rep_name
    rep_path.write_text(rep_body, encoding="utf-8")
    outputs[rep_name] = rep_path

    # ── 概要 ──
    overview_name = f"{sid}_00_overview.txt"
    overview_path = out_dir / overview_name
    overview_path.write_text(
        build_overview(df, schema, inquiry_text, session_id, rep_info) + "\n",
        encoding="utf-8",
    )
    outputs[overview_name] = overview_path

    # ── tagged 全件の単一シートxlsx（日本語列名・関連度降順・コメント原文入り） ──
    flat_name = f"{sid}_90_tagged_flat.xlsx"
    flat = df
    if "overall_relevance" in flat.columns:
        flat = flat.sort_values("overall_relevance", ascending=False)
    flat = flat.rename(columns=_japanese_rename_map(flat.columns, schema))
    flat.to_excel(out_dir / flat_name, sheet_name="tagged", index=False)
    outputs[flat_name] = out_dir / flat_name

    return outputs
