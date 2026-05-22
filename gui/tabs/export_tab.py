"""
gui/tabs/export_tab.py - 出力タブ

役割:
- output_tag(ファイル名サフィックス)の指定
- 出力先ディレクトリの確認(設定タブで指定したものを表示)
- 「保存実行」ボタンで scoring.save_results()
- 出力ファイル一覧表示
- 各ファイルを Explorer/Finder で開くボタン
"""
from __future__ import annotations

import os
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from gui.tabs.base import BaseTab


class ExportTab(BaseTab):
    TITLE = "出力"
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:状態確認 ===
        status_frame = ttk.LabelFrame(main, text="保存対象", padding=8)
        status_frame.pack(fill="x")
        
        self.var_status = tk.StringVar(value="(タグ付けと絞り込みを先に実行してください)")
        ttk.Label(status_frame, textvariable=self.var_status,
                  font=("Monospace", 10)).pack(anchor="w")
        
        # === 出力設定 ===
        setting_frame = ttk.LabelFrame(main, text="出力設定", padding=8)
        setting_frame.pack(fill="x", pady=(8, 0))
        
        # ファイル名サフィックス
        ttk.Label(setting_frame, text="ファイル名タグ:").grid(
            row=0, column=0, sticky="e", padx=4, pady=4
        )
        self.var_tag = tk.StringVar(value=self.state.output_tag or "")
        ttk.Entry(setting_frame, textvariable=self.var_tag, width=40).grid(
            row=0, column=1, sticky="we", padx=4, pady=4
        )
        ttk.Label(setting_frame, text="(例: EOS_R7_AF_lowtemp)",
                  foreground="gray").grid(row=0, column=2, sticky="w", padx=4)
        
        # 出力先
        ttk.Label(setting_frame, text="出力先ディレクトリ:").grid(
            row=1, column=0, sticky="e", padx=4, pady=4
        )
        self.var_output_dir = tk.StringVar(
            value=self.settings.output_dir or "./output"
        )
        ttk.Entry(setting_frame, textvariable=self.var_output_dir,
                  state="readonly", width=40).grid(
            row=1, column=1, sticky="we", padx=4, pady=4
        )
        ttk.Label(setting_frame, text="(設定タブで変更)",
                  foreground="gray").grid(row=1, column=2, sticky="w", padx=4)
        
        setting_frame.columnconfigure(1, weight=1)
        
        # === 操作ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        self.btn_save = ttk.Button(btn_frame, text="保存実行",
                                   command=self._on_save)
        self.btn_save.pack(side="left", padx=2)
        
        self.var_progress = tk.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self.var_progress,
                  foreground="green").pack(side="left", padx=8)
        
        # === 出力ファイル一覧 ===
        ttk.Label(main, text="出力ファイル:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(16, 4))
        
        list_frame = ttk.Frame(main)
        list_frame.pack(fill="both", expand=True)
        
        columns = ("name", "path")
        self.tree_files = ttk.Treeview(list_frame, columns=columns,
                                        show="headings")
        self.tree_files.heading("name", text="種別")
        self.tree_files.heading("path", text="パス")
        self.tree_files.column("name", width=200)
        self.tree_files.column("path", width=600)
        
        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                    command=self.tree_files.yview)
        self.tree_files.configure(yscrollcommand=tree_scroll.set)
        self.tree_files.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        
        self.tree_files.bind("<Double-1>", lambda e: self._open_selected())
        
        # === 個別操作 ===
        file_btn_frame = ttk.Frame(main)
        file_btn_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(file_btn_frame, text="選択ファイルを開く",
                   command=self._open_selected).pack(side="left", padx=2)
        ttk.Button(file_btn_frame, text="フォルダを開く",
                   command=self._open_folder).pack(side="left", padx=2)
        
        ttk.Label(
            main, foreground="gray",
            text="ヒント: results.xlsx に tagged(全件)/ranked(絞り込み) の2シートが入ります。Tableau Desktop でも直接開けます"
        ).pack(anchor="w", pady=(8, 0))
    
    # ------------------------------------------------------------------
    # 状態表示
    # ------------------------------------------------------------------
    
    def _update_status(self):
        lines = []
        if self.state.tagged_df is not None:
            lines.append(f"✅ tagged_df: {len(self.state.tagged_df)} 件")
        else:
            lines.append("❌ tagged_df: なし (タグ付けタブで実行)")
        
        if self.state.ranked_df is not None:
            lines.append(f"✅ ranked_df: {len(self.state.ranked_df)} 件")
        else:
            lines.append("❌ ranked_df: なし (絞り込みタブで実行)")
        
        if self.state.schema:
            lines.append(f"✅ schema: {len(self.state.schema.get('axes', []))} 軸")
        else:
            lines.append("❌ schema: なし")
        
        self.var_status.set("\n".join(lines))
        
        # 保存可能か判定
        can_save = (self.state.tagged_df is not None
                    and self.state.ranked_df is not None
                    and self.state.schema is not None)
        self.btn_save.configure(state="normal" if can_save else "disabled")
    
    # ------------------------------------------------------------------
    # 保存実行
    # ------------------------------------------------------------------
    
    def _on_save(self):
        if self.state.tagged_df is None or self.state.ranked_df is None:
            messagebox.showwarning("エラー", "保存対象が揃っていません。")
            return
        
        try:
            self.settings.apply_to_config_module()
        except ImportError:
            pass
        
        tag = self.var_tag.get().strip()
        
        try:
            import scoring
            paths = scoring.save_results(
                tagged_df=self.state.tagged_df,
                ranked_df=self.state.ranked_df,
                schema=self.state.schema,
                inquiry_text=self.state.inquiry_text,
                tag=tag,
            )
            self.state.output_tag = tag
            
            # ファイル一覧を表示
            self._populate_files(paths)
            
            self.var_progress.set(f"✅ {len(paths)} ファイルを保存しました")
            self.app.set_status("出力完了")
            
            messagebox.showinfo(
                "保存完了",
                f"{len(paths)} ファイルを保存しました。\n\n"
                "results.xlsx に tagged/ranked の2シートが入っています。"
            )
        except Exception as e:
            self.var_progress.set(f"❌ 失敗: {e}")
            messagebox.showerror("保存失敗", str(e))
    
    def _populate_files(self, paths: dict):
        self.tree_files.delete(*self.tree_files.get_children())
        
        # 表示順を制御(重要なものから)
        display_order = [
            ("results_xlsx", "結果 (Excel: tagged/ranked 2シート)"),
            ("ranked_parquet", "絞り込み結果 (Parquet)"),
            ("tagged_parquet", "タグ付け結果 全件 (Parquet)"),
            ("schema_json", "使用スキーマ (JSON)"),
            ("meta_json", "実行メタ情報 (JSON)"),
        ]
        for key, label in display_order:
            if key in paths:
                self.tree_files.insert("", "end", iid=key, values=(label, paths[key]))
        # 上記以外
        for key, path in paths.items():
            if key not in dict(display_order):
                self.tree_files.insert("", "end", iid=key, values=(key, path))
    
    # ------------------------------------------------------------------
    # ファイル操作
    # ------------------------------------------------------------------
    
    def _open_selected(self):
        sel = self.tree_files.selection()
        if not sel:
            messagebox.showinfo("選択", "開くファイルを選んでください。")
            return
        item = self.tree_files.item(sel[0])
        path_str = item["values"][1]
        self._open_path(path_str)
    
    def _open_folder(self):
        # 設定の output_dir(なければ ./output)
        out_dir = self.settings.output_dir or "./output"
        path = Path(out_dir).resolve()
        if not path.exists():
            messagebox.showwarning("エラー",
                                   f"フォルダが存在しません: {path}")
            return
        self._open_path(str(path))
    
    def _open_path(self, path_str: str):
        """OS 標準のファイラ/エディタで開く"""
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path_str)
            elif system == "Darwin":
                subprocess.Popen(["open", path_str])
            else:
                subprocess.Popen(["xdg-open", path_str])
        except Exception as e:
            messagebox.showerror("オープン失敗",
                                 f"ファイルを開けませんでした:\n{e}")
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_show(self):
        self._update_status()
        # 出力ディレクトリの最新値
        self.var_output_dir.set(self.settings.output_dir or "./output")
    
    def on_hide(self):
        self.state.output_tag = self.var_tag.get().strip()
    
    def refresh_from_state(self):
        self.var_tag.set(self.state.output_tag or "")
        self.var_output_dir.set(self.settings.output_dir or "./output")
        self._update_status()
        self.tree_files.delete(*self.tree_files.get_children())
        self.var_progress.set("")
