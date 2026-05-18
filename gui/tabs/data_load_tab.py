"""
gui/tabs/data_load_tab.py - データ取得タブ

役割:
- データソース切り替え(SQL / CSV のラジオボタン)
- CSV モード: ファイル選択、マッピングプリセット選択、マッピング編集
- SQL モード: SQL クエリ入力
- 読み込みボタンで Worker で loader 実行
- データプレビュー(DataFrameView)
- 言語分布・コメント長分布の集計表示
- 前処理(preprocess.prepare_records)も実行して records/batches を state に格納
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd

from gui.tabs.base import BaseTab
from gui.widgets.dataframe_view import DataFrameView
from gui.widgets.mapping_editor import MappingEditorDialog
from gui.workers import Worker, QueuePoller


class DataLoadTab(BaseTab):
    TITLE = "データ取得"
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:データソース選択 ===
        src_frame = ttk.LabelFrame(main, text="データソース", padding=8)
        src_frame.pack(fill="x")
        
        self.var_source = tk.StringVar(value=self.state.data_source or "csv")
        ttk.Radiobutton(src_frame, text="CSV", variable=self.var_source,
                        value="csv",
                        command=self._on_source_changed).pack(side="left", padx=8)
        ttk.Radiobutton(src_frame, text="SQL", variable=self.var_source,
                        value="sql",
                        command=self._on_source_changed).pack(side="left", padx=8)
        
        # === CSV / SQL 設定エリア ===
        self.config_frame = ttk.Frame(main)
        self.config_frame.pack(fill="x", pady=(8, 0))
        
        # CSV フレーム
        self.csv_frame = ttk.Frame(self.config_frame)
        self._build_csv_frame(self.csv_frame)
        
        # SQL フレーム
        self.sql_frame = ttk.Frame(self.config_frame)
        self._build_sql_frame(self.sql_frame)
        
        self._on_source_changed()  # 初期状態に合わせて表示切替
        
        # === 操作ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        self.btn_load = ttk.Button(btn_frame, text="読み込み",
                                   command=self._on_load)
        self.btn_load.pack(side="left", padx=2)
        
        self.btn_preprocess = ttk.Button(
            btn_frame, text="前処理実行 (バッチ分割)",
            command=self._on_preprocess, state="disabled"
        )
        self.btn_preprocess.pack(side="left", padx=2)
        
        # ステータス
        self.var_status = tk.StringVar(value="準備完了")
        ttk.Label(btn_frame, textvariable=self.var_status,
                  foreground="gray").pack(side="right")
        
        # === 統計情報 ===
        self.var_stats = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.var_stats,
                  font=("Monospace", 9), foreground="darkblue").pack(
            anchor="w", pady=(8, 0)
        )
        
        # === プレビュー ===
        ttk.Label(main, text="データプレビュー:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(8, 4))
        
        self.df_view = DataFrameView(main)
        self.df_view.pack(fill="both", expand=True)
        
        # ワーカー管理
        self._msg_queue: Optional[queue.Queue] = None
        self._worker: Optional[Worker] = None
        self._poller: Optional[QueuePoller] = None
    
    def _build_csv_frame(self, parent):
        row = 0
        pad = {"padx": 4, "pady": 4}
        
        ttk.Label(parent, text="CSVファイル:").grid(
            row=row, column=0, sticky="e", **pad
        )
        self.var_csv_path = tk.StringVar(value=self.state.csv_path or "")
        ttk.Entry(parent, textvariable=self.var_csv_path, width=50).grid(
            row=row, column=1, sticky="we", **pad
        )
        ttk.Button(parent, text="参照...",
                   command=self._browse_csv).grid(row=row, column=2, **pad)
        row += 1
        
        ttk.Label(parent, text="マッピング:").grid(
            row=row, column=0, sticky="e", **pad
        )
        self.var_mapping = tk.StringVar(value=self.state.mapping_name or "")
        self.cb_mapping = ttk.Combobox(
            parent, textvariable=self.var_mapping, width=40, state="readonly"
        )
        self.cb_mapping.grid(row=row, column=1, sticky="we", **pad)
        
        map_btn_frame = ttk.Frame(parent)
        map_btn_frame.grid(row=row, column=2, sticky="w", **pad)
        ttk.Button(map_btn_frame, text="新規作成",
                   command=self._new_mapping).pack(side="left", padx=2)
        ttk.Button(map_btn_frame, text="編集",
                   command=self._edit_mapping).pack(side="left", padx=2)
        ttk.Button(map_btn_frame, text="↻",
                   command=self._refresh_mappings, width=3).pack(side="left", padx=2)
        row += 1
        
        # マッピング説明
        self.var_mapping_desc = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.var_mapping_desc,
                  foreground="gray", wraplength=600).grid(
            row=row, column=1, columnspan=2, sticky="w", **pad
        )
        self.cb_mapping.bind("<<ComboboxSelected>>", self._on_mapping_changed)
        
        parent.columnconfigure(1, weight=1)
        
        self._refresh_mappings()
    
    def _build_sql_frame(self, parent):
        ttk.Label(parent, text="SQL クエリ:").pack(anchor="w")
        
        sql_text_frame = ttk.Frame(parent)
        sql_text_frame.pack(fill="x")
        
        self.txt_sql = tk.Text(sql_text_frame, wrap="word", height=6,
                               font=("Monospace", 10))
        sql_scroll = ttk.Scrollbar(sql_text_frame, orient="vertical",
                                   command=self.txt_sql.yview)
        self.txt_sql.configure(yscrollcommand=sql_scroll.set)
        self.txt_sql.pack(side="left", fill="x", expand=True)
        sql_scroll.pack(side="right", fill="y")
        
        if self.state.sql_query:
            self.txt_sql.insert("1.0", self.state.sql_query)
        else:
            self.txt_sql.insert("1.0",
                "-- 例:\n"
                "SELECT TOP 500\n"
                "    repair_id, user_comment, repair_comment,\n"
                "    internal_1, internal_2,\n"
                "    model, repair_date\n"
                "FROM repair_records\n"
                "WHERE model = ? AND repair_date >= ?\n"
                "ORDER BY repair_date DESC"
            )
        
        ttk.Label(parent, text="パラメータ(?順、カンマ区切り):",
                  foreground="gray").pack(anchor="w", pady=(4, 0))
        self.var_sql_params = tk.StringVar(
            value=", ".join(self.state.sql_params) if self.state.sql_params else ""
        )
        ttk.Entry(parent, textvariable=self.var_sql_params).pack(
            fill="x"
        )
        
        ttk.Label(
            parent, foreground="gray",
            text="(SELECT 句のカラム名が論理名と異なる場合は、マッピングは "
                 "CSV と同じ要領で別途指定する必要があります。"
                 "通常は SELECT 句で論理名にエイリアスを付けるのが簡単です。)"
        ).pack(anchor="w", pady=(4, 0))
    
    # ------------------------------------------------------------------
    # ソース切替
    # ------------------------------------------------------------------
    
    def _on_source_changed(self):
        src = self.var_source.get()
        if src == "csv":
            self.sql_frame.pack_forget()
            self.csv_frame.pack(fill="x")
        else:
            self.csv_frame.pack_forget()
            self.sql_frame.pack(fill="x")
        self.state.data_source = src
    
    # ------------------------------------------------------------------
    # マッピング関連
    # ------------------------------------------------------------------
    
    def _refresh_mappings(self):
        import loader
        mappings = loader.list_mappings()
        names = [m["name"] for m in mappings]
        self._mappings_info = {m["name"]: m for m in mappings}
        self.cb_mapping["values"] = names
        if self.var_mapping.get() not in names and names:
            self.var_mapping.set(names[0])
        self._on_mapping_changed()
    
    def _on_mapping_changed(self, event=None):
        name = self.var_mapping.get()
        info = self._mappings_info.get(name)
        if info:
            self.var_mapping_desc.set(
                f"{info['display_name']}: {info['description']}"
            )
        else:
            self.var_mapping_desc.set("")
        self.state.mapping_name = name
    
    def _new_mapping(self):
        """CSVファイルからカラムを読み取って新規マッピング作成"""
        csv_path = self.var_csv_path.get().strip()
        if not csv_path:
            messagebox.showwarning(
                "CSV未選択",
                "先にCSVファイルを選択してください。"
                "(マッピング作成にはCSVのヘッダ情報が必要です)"
            )
            return
        
        try:
            import loader
            csv_columns, _ = loader.preview_csv_columns(csv_path)
        except Exception as e:
            messagebox.showerror("読み込みエラー",
                                 f"CSVのヘッダ取得に失敗:\n{e}")
            return
        
        dlg = MappingEditorDialog(self.app.root, csv_columns=csv_columns)
        self.app.root.wait_window(dlg.top)
        if dlg.result is None:
            return
        
        mapping, save_name = dlg.result
        try:
            import loader
            loader.save_mapping(mapping, save_name)
        except Exception as e:
            messagebox.showerror("保存失敗",
                                 f"マッピング保存に失敗:\n{e}")
            return
        
        self._refresh_mappings()
        self.var_mapping.set(save_name)
        self._on_mapping_changed()
        messagebox.showinfo("保存完了",
                            f"マッピング '{save_name}' を保存しました。")
    
    def _edit_mapping(self):
        """既存マッピングを編集"""
        name = self.var_mapping.get()
        if not name:
            return
        
        csv_path = self.var_csv_path.get().strip()
        if not csv_path:
            messagebox.showwarning(
                "CSV未選択",
                "編集にはCSVのヘッダ情報が必要です。先にCSVファイルを選択してください。"
            )
            return
        
        try:
            import loader
            csv_columns, _ = loader.preview_csv_columns(csv_path)
            existing = loader.load_mapping(name)
        except Exception as e:
            messagebox.showerror("読み込みエラー", str(e))
            return
        
        dlg = MappingEditorDialog(
            self.app.root,
            csv_columns=csv_columns,
            existing_mapping=existing,
            existing_name=name,
        )
        self.app.root.wait_window(dlg.top)
        if dlg.result is None:
            return
        
        mapping, save_name = dlg.result
        try:
            import loader
            loader.save_mapping(mapping, save_name)
        except Exception as e:
            messagebox.showerror("保存失敗", str(e))
            return
        
        self._refresh_mappings()
        self.var_mapping.set(save_name)
        self._on_mapping_changed()
        messagebox.showinfo("保存完了", "マッピングを更新しました。")
    
    # ------------------------------------------------------------------
    # データ読み込み
    # ------------------------------------------------------------------
    
    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="CSVファイルを選択",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
        )
        if path:
            self.var_csv_path.set(path)
    
    def _on_load(self):
        src = self.var_source.get()
        
        if src == "csv":
            csv_path = self.var_csv_path.get().strip()
            if not csv_path:
                messagebox.showwarning("入力エラー", "CSVファイルを選択してください。")
                return
            mapping_name = self.var_mapping.get()
            if not mapping_name:
                messagebox.showwarning("入力エラー", "マッピングを選択してください。")
                return
            
            self.state.csv_path = csv_path
            self.state.mapping_name = mapping_name
            
            def task():
                import loader
                return loader.load_from_csv(csv_path, mapping_name=mapping_name,
                                            verbose=False)
        
        else:  # sql
            sql = self.txt_sql.get("1.0", "end").strip()
            if not sql:
                messagebox.showwarning("入力エラー", "SQLを入力してください。")
                return
            params_str = self.var_sql_params.get().strip()
            params = tuple(p.strip() for p in params_str.split(",")) \
                     if params_str else None
            
            self.state.sql_query = sql
            self.state.sql_params = list(params) if params else []
            
            # SQL 接続情報チェック
            if not self.settings.mssql_server:
                messagebox.showwarning(
                    "設定不足",
                    "MS SQL Server の接続情報が未設定です。"
                    "「設定」タブで入力してください。"
                )
                return
            
            def task():
                try:
                    self.settings.apply_to_config_module()
                except ImportError:
                    pass
                import loader
                return loader.load_from_sql(sql, params=params, verbose=False)
        
        # 実行
        self.btn_load.configure(state="disabled", text="読み込み中…")
        self.btn_preprocess.configure(state="disabled")
        self.var_status.set("読み込み中…")
        self.app.set_status("データ読み込み中…")
        
        self._msg_queue = queue.Queue()
        self._worker = Worker(target=task, msg_queue=self._msg_queue)
        self._poller = QueuePoller(
            root=self.app.root,
            msg_queue=self._msg_queue,
            on_done=self._on_load_done,
            on_error=self._on_load_error,
            interval_ms=100,
        )
        self._worker.start()
        self._poller.start()
    
    def _on_load_done(self, df: pd.DataFrame):
        self.state.repair_df = df
        # 前処理結果はクリア(再前処理が必要)
        self.state.records = None
        self.state.batches = None
        
        self.df_view.update_df(df)
        self._update_stats(df)
        
        self.btn_load.configure(state="normal", text="読み込み")
        self.btn_preprocess.configure(state="normal")
        self.var_status.set(f"読み込み完了: {len(df)}件")
        self.app.set_status(f"読み込み完了: {len(df)}件")
    
    def _on_load_error(self, err: dict):
        self.btn_load.configure(state="normal", text="読み込み")
        self.var_status.set("エラー")
        self.app.set_status("読み込みエラー")
        messagebox.showerror(
            "読み込みエラー",
            f"{err['exc_type']}\n\n{err['message']}"
        )
    
    def _update_stats(self, df: pd.DataFrame):
        """言語・コメント長などの簡易統計"""
        if df is None or len(df) == 0:
            self.var_stats.set("")
            return
        
        lines = [f"件数: {len(df)}件"]
        # カラム情報
        lines.append(f"カラム: {len(df.columns)}個 ({', '.join(df.columns[:8])}"
                     + ("..." if len(df.columns) > 8 else "") + ")")
        self.var_stats.set("\n".join(lines))
    
    # ------------------------------------------------------------------
    # 前処理実行
    # ------------------------------------------------------------------
    
    def _on_preprocess(self):
        if self.state.repair_df is None or len(self.state.repair_df) == 0:
            messagebox.showwarning("データなし", "まずデータを読み込んでください。")
            return
        
        try:
            self.settings.apply_to_config_module()
        except ImportError:
            pass
        
        try:
            import preprocess
            records = preprocess.prepare_records(self.state.repair_df)
            batches = preprocess.chunk_records(records,
                                                batch_size=self.settings.batch_size)
            self.state.records = records
            self.state.batches = batches
            
            # 統計表示
            lang_counter = Counter(r["meta"]["language"] for r in records)
            tier_counter = Counter(r["meta"]["length_tier"] for r in records)
            
            lines = [
                f"レコード数: {len(records)}",
                f"バッチ数: {len(batches)} (1バッチ {self.settings.batch_size}件)",
                f"言語分布: {dict(lang_counter)}",
                f"コメント長分布: {dict(tier_counter)}",
            ]
            self.var_stats.set("\n".join(lines))
            self.app.set_status(f"前処理完了: {len(records)}件 / {len(batches)}バッチ")
            messagebox.showinfo(
                "前処理完了",
                f"レコード数: {len(records)}\n"
                f"バッチ数: {len(batches)}\n\n"
                f"「タグ付け実行」タブに進めます。"
            )
        except Exception as e:
            messagebox.showerror("前処理エラー", str(e))
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_hide(self):
        # SQL のテキストを state に書き戻し
        if hasattr(self, "txt_sql"):
            self.state.sql_query = self.txt_sql.get("1.0", "end").strip()
        if hasattr(self, "var_sql_params"):
            params_str = self.var_sql_params.get().strip()
            self.state.sql_params = [p.strip() for p in params_str.split(",")] \
                                    if params_str else []
        self.state.csv_path = self.var_csv_path.get().strip()
        self.state.mapping_name = self.var_mapping.get()
        self.state.data_source = self.var_source.get()
    
    def on_show(self):
        # state から最新値を反映
        if self.state.repair_df is not None:
            self.df_view.update_df(self.state.repair_df)
            if self.state.records:
                self.btn_preprocess.configure(state="normal")
                # 前処理済みなら統計再表示
                lang_counter = Counter(r["meta"]["language"]
                                       for r in self.state.records)
                tier_counter = Counter(r["meta"]["length_tier"]
                                       for r in self.state.records)
                self.var_stats.set("\n".join([
                    f"レコード数: {len(self.state.records)}",
                    f"バッチ数: {len(self.state.batches)} "
                    f"(1バッチ {self.settings.batch_size}件)",
                    f"言語分布: {dict(lang_counter)}",
                    f"コメント長分布: {dict(tier_counter)}",
                ]))
            else:
                self.btn_preprocess.configure(state="normal")
                self._update_stats(self.state.repair_df)
    
    def refresh_from_state(self):
        """セッションロード後"""
        self.var_source.set(self.state.data_source or "csv")
        self.var_csv_path.set(self.state.csv_path or "")
        self.var_mapping.set(self.state.mapping_name or "")
        if hasattr(self, "txt_sql"):
            self.txt_sql.delete("1.0", "end")
            if self.state.sql_query:
                self.txt_sql.insert("1.0", self.state.sql_query)
        if hasattr(self, "var_sql_params"):
            params_str = ", ".join(self.state.sql_params or [])
            self.var_sql_params.set(params_str)
        self._on_source_changed()
        self._on_mapping_changed()
        if self.state.repair_df is not None:
            self.df_view.update_df(self.state.repair_df)
            self.btn_preprocess.configure(state="normal")
            self._update_stats(self.state.repair_df)
        else:
            self.df_view.clear()
            self.btn_preprocess.configure(state="disabled")
            self.var_stats.set("")
