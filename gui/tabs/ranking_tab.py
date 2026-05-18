"""
gui/tabs/ranking_tab.py - 絞り込みタブ

役割:
- query_tags の指定 UI(各軸ごとに候補ドロップダウン)
- min_relevance スライダー、top_n スピンボックス
- 「絞り込み実行」ボタン → scoring.rank_results()
- 結果テーブル(DataFrameView)
- 選択レコードの根拠表示
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import pandas as pd

from gui.tabs.base import BaseTab
from gui.widgets.dataframe_view import DataFrameView


class RankingTab(BaseTab):
    TITLE = "絞り込み"
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:query_tags 指定 ===
        tag_frame = ttk.LabelFrame(main, text="問い合わせタグの指定", padding=8)
        tag_frame.pack(fill="x")
        
        self.tags_container = ttk.Frame(tag_frame)
        self.tags_container.pack(fill="x")
        
        self.var_query_tags: dict[str, tk.StringVar] = {}
        self.var_no_status = tk.StringVar(
            value="(スキーマが未生成です。「問い合わせ」タブから生成してください)"
        )
        self.lbl_no_status = ttk.Label(self.tags_container,
                                        textvariable=self.var_no_status,
                                        foreground="gray")
        self.lbl_no_status.pack(anchor="w")
        
        # === スコアリングパラメータ ===
        param_frame = ttk.Frame(main)
        param_frame.pack(fill="x", pady=(8, 0))
        
        ttk.Label(param_frame, text="最低 overall_relevance:").pack(side="left")
        self.var_min_relevance = tk.DoubleVar(value=self.state.min_relevance or 0.3)
        self.lbl_min_relevance_val = ttk.Label(param_frame, text="0.30",
                                                width=5)
        ttk.Scale(param_frame, from_=0.0, to=1.0,
                  variable=self.var_min_relevance,
                  command=self._on_relevance_changed,
                  orient="horizontal", length=200).pack(side="left", padx=4)
        self.lbl_min_relevance_val.pack(side="left", padx=(0, 16))
        
        ttk.Label(param_frame, text="上位 N 件:").pack(side="left")
        self.var_top_n = tk.IntVar(value=self.state.top_n or 50)
        ttk.Spinbox(param_frame, from_=1, to=10000,
                    textvariable=self.var_top_n, width=8).pack(side="left", padx=4)
        
        # === ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        self.btn_rank = ttk.Button(btn_frame, text="絞り込み実行",
                                   command=self._on_rank)
        self.btn_rank.pack(side="left", padx=2)
        
        self.var_status = tk.StringVar(value="準備完了")
        ttk.Label(btn_frame, textvariable=self.var_status,
                  foreground="gray").pack(side="right")
        
        # === 結果プレビュー ===
        ttk.Label(main, text="絞り込み結果:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(12, 4))
        
        # 結果テーブル + 根拠表示の上下分割
        pw = ttk.PanedWindow(main, orient="vertical")
        pw.pack(fill="both", expand=True)
        
        self.df_view = DataFrameView(pw)
        pw.add(self.df_view, weight=2)
        
        # === 根拠表示 ===
        detail_frame = ttk.LabelFrame(pw, text="根拠詳細(行を選択)", padding=4)
        pw.add(detail_frame, weight=1)
        
        detail_inner = ttk.Frame(detail_frame)
        detail_inner.pack(fill="both", expand=True)
        
        self.txt_detail = tk.Text(detail_inner, wrap="word", height=8,
                                  font=("Monospace", 9), state="disabled",
                                  background="#fafafa")
        detail_scroll = ttk.Scrollbar(detail_inner, orient="vertical",
                                      command=self.txt_detail.yview)
        self.txt_detail.configure(yscrollcommand=detail_scroll.set)
        self.txt_detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        
        # 行選択イベント
        self._bind_row_selection()
    
    def _bind_row_selection(self):
        """DataFrameView の行選択時に根拠表示を更新"""
        # pandastable と Treeview で実装が異なる
        from gui.widgets.dataframe_view import PANDASTABLE_AVAILABLE
        if PANDASTABLE_AVAILABLE and hasattr(self.df_view, "table"):
            # pandastable はクリックイベントを直接バインドしにくいので、
            # 一定間隔で選択を見る方式
            self._poll_selection()
        elif hasattr(self.df_view, "tree"):
            self.df_view.tree.bind("<<TreeviewSelect>>",
                                   self._on_treeview_select)
    
    def _poll_selection(self):
        """pandastable の現在選択行を定期的に確認"""
        try:
            if hasattr(self.df_view, "table"):
                t = self.df_view.table
                if hasattr(t, "currentrow") and self.state.ranked_df is not None:
                    row_idx = t.currentrow
                    if row_idx is not None and 0 <= row_idx < len(self.state.ranked_df):
                        if not hasattr(self, "_last_shown_row") or \
                           self._last_shown_row != row_idx:
                            self._last_shown_row = row_idx
                            self._show_detail(row_idx)
        except (AttributeError, IndexError):
            pass
        # 500ms ごとに再ポーリング
        self.after(500, self._poll_selection)
    
    def _on_treeview_select(self, event):
        sel = self.df_view.tree.selection()
        if not sel:
            return
        try:
            row_idx = int(sel[0])
            self._show_detail(row_idx)
        except (ValueError, IndexError):
            pass
    
    def _show_detail(self, row_idx: int):
        """指定行の根拠を詳細表示"""
        if self.state.ranked_df is None or row_idx >= len(self.state.ranked_df):
            return
        
        row = self.state.ranked_df.iloc[row_idx]
        schema = self.state.schema or {}
        
        lines = [
            f"repair_id: {row.get('repair_id', '')}",
            f"match_score: {row.get('match_score', 0):.3f}",
            f"overall_relevance: {row.get('overall_relevance', 0):.3f}",
            f"language_detected: {row.get('language_detected', '')}",
            f"",
            f"relevance_reason:",
            f"  {row.get('relevance_reason', '')}",
            f"",
            f"--- 軸ごとの判定 ---",
        ]
        for ax in schema.get("axes", []):
            name = ax["name"]
            tag = row.get(f"tag__{name}")
            conf = row.get(f"conf__{name}", 0)
            ev = row.get(f"evidence__{name}", "")
            lines.append(f"[{name}] {tag} (conf={conf:.2f})")
            lines.append(f"  根拠: {ev}")
        
        self.txt_detail.configure(state="normal")
        self.txt_detail.delete("1.0", "end")
        self.txt_detail.insert("1.0", "\n".join(lines))
        self.txt_detail.configure(state="disabled")
    
    # ------------------------------------------------------------------
    # query_tags UI 構築
    # ------------------------------------------------------------------
    
    def _rebuild_tag_inputs(self):
        # 既存ウィジェット削除
        for w in self.tags_container.winfo_children():
            w.destroy()
        self.var_query_tags = {}
        
        if not self.state.schema:
            self.lbl_no_status = ttk.Label(
                self.tags_container,
                text="(スキーマが未生成です)",
                foreground="gray"
            )
            self.lbl_no_status.pack(anchor="w")
            self.btn_rank.configure(state="disabled")
            return
        
        self.btn_rank.configure(state="normal")
        
        # 各軸に対してドロップダウン
        for i, ax in enumerate(self.state.schema.get("axes", [])):
            name = ax["name"]
            tier = ax.get("tier", "detail")
            candidates = ax.get("candidates", [])
            
            row_frame = ttk.Frame(self.tags_container)
            row_frame.pack(fill="x", pady=2)
            
            label_text = f"[{tier}] {name}:"
            ttk.Label(row_frame, text=label_text, width=30,
                      anchor="e").pack(side="left", padx=4)
            
            var = tk.StringVar(value=self.state.query_tags.get(name, "")
                               if self.state.query_tags else "")
            self.var_query_tags[name] = var
            
            # detail 軸は「(指定なし)」も選べるように
            values = ["(指定なし)"] + candidates if tier == "detail" \
                     else candidates
            cb = ttk.Combobox(row_frame, textvariable=var,
                              values=values, width=30, state="readonly")
            cb.pack(side="left", padx=4)
            
            if tier == "core" and not var.get() and candidates:
                # core 軸はデフォルト未指定だが、警告
                ttk.Label(row_frame, text="(必須)",
                          foreground="red").pack(side="left", padx=4)
            elif tier == "detail" and not var.get():
                var.set("(指定なし)")
    
    def _on_relevance_changed(self, value):
        try:
            v = float(value)
            self.lbl_min_relevance_val.configure(text=f"{v:.2f}")
        except ValueError:
            pass
    
    # ------------------------------------------------------------------
    # 絞り込み実行
    # ------------------------------------------------------------------
    
    def _collect_query_tags(self) -> Optional[dict]:
        """UI から query_tags を取得。core 軸未指定なら None を返す"""
        if not self.state.schema:
            return None
        
        result = {}
        core_axis_name = None
        for ax in self.state.schema.get("axes", []):
            name = ax["name"]
            val = self.var_query_tags.get(name)
            if not val:
                continue
            v = val.get()
            if ax.get("tier") == "core":
                core_axis_name = name
                if not v:
                    messagebox.showwarning(
                        "core軸未指定",
                        f"core軸 '{name}' は必須です。値を選択してください。"
                    )
                    return None
                result[name] = v
            else:
                # detail
                if v and v != "(指定なし)":
                    result[name] = v
        
        if not core_axis_name:
            messagebox.showwarning("エラー", "core軸が見つかりません。")
            return None
        
        return result
    
    def _on_rank(self):
        if self.state.tagged_df is None or len(self.state.tagged_df) == 0:
            messagebox.showwarning("データなし",
                                   "タグ付け結果がありません。")
            return
        
        query_tags = self._collect_query_tags()
        if query_tags is None:
            return
        
        self.state.query_tags = query_tags
        self.state.min_relevance = float(self.var_min_relevance.get())
        self.state.top_n = int(self.var_top_n.get())
        
        try:
            import scoring
            ranked = scoring.rank_results(
                self.state.tagged_df,
                query_tags=query_tags,
                schema=self.state.schema,
                min_relevance=self.state.min_relevance,
                top_n=self.state.top_n,
            )
            self.state.ranked_df = ranked
            
            # 表示用に列を絞る(評価に必要な列のみ)
            display_cols = ["repair_id", "match_score", "overall_relevance",
                            "language_detected", "relevance_reason"]
            # 軸タグも追加
            for ax in self.state.schema.get("axes", []):
                tag_col = f"tag__{ax['name']}"
                if tag_col in ranked.columns:
                    display_cols.append(tag_col)
            
            display_cols = [c for c in display_cols if c in ranked.columns]
            display_df = ranked[display_cols]
            
            self.df_view.update_df(display_df)
            
            self.var_status.set(f"完了: {len(ranked)}件")
            self.app.set_status(
                f"絞り込み完了: {len(ranked)} / "
                f"{len(self.state.tagged_df)} 件"
            )
        except Exception as e:
            messagebox.showerror("絞り込みエラー", str(e))
            self.var_status.set("エラー")
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_show(self):
        self._rebuild_tag_inputs()
        # 既存の ranked_df があれば表示
        if self.state.ranked_df is not None:
            display_cols = ["repair_id", "match_score", "overall_relevance",
                            "language_detected", "relevance_reason"]
            display_cols = [c for c in display_cols
                            if c in self.state.ranked_df.columns]
            for ax in (self.state.schema or {}).get("axes", []):
                tag_col = f"tag__{ax['name']}"
                if tag_col in self.state.ranked_df.columns:
                    display_cols.append(tag_col)
            self.df_view.update_df(self.state.ranked_df[display_cols])
    
    def on_hide(self):
        # スコアリングパラメータと query_tags を state に書き戻し
        try:
            self.state.min_relevance = float(self.var_min_relevance.get())
            self.state.top_n = int(self.var_top_n.get())
            # query_tags は実行ボタン押下時にのみ書き戻し(中途半端な状態を残さない)
        except (tk.TclError, ValueError):
            pass
    
    def refresh_from_state(self):
        self._rebuild_tag_inputs()
        self.var_min_relevance.set(self.state.min_relevance or 0.3)
        self.var_top_n.set(self.state.top_n or 50)
        self._on_relevance_changed(self.var_min_relevance.get())
        if self.state.ranked_df is not None:
            self.df_view.update_df(self.state.ranked_df)
        else:
            self.df_view.clear()
        self.txt_detail.configure(state="normal")
        self.txt_detail.delete("1.0", "end")
        self.txt_detail.configure(state="disabled")
