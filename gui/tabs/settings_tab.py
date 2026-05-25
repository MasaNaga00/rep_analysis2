"""
gui/tabs/settings_tab.py - 設定タブ

役割:
- Dify API キー、ベースURL、CA証明書パスの設定
- MS SQL Server 接続情報(CSV しか使わないなら空欄でOK)
- 処理パラメータ(バッチサイズ、並列数、タイムアウト等)
- 出力ディレクトリ
- 「保存」ボタンで settings.json に書き込み + config モジュールに反映
- 「証明書テスト」ボタンで証明書ファイルの存在確認
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from gui.tabs.base import BaseTab


class SettingsTab(BaseTab):
    TITLE = "設定"
    
    def build_ui(self):
        # スクロール可能なフレーム(項目が多いため)
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable = ttk.Frame(canvas)
        
        self.scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # マウスホイールでスクロール
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"
        ))
        # Linux 用
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        
        self._build_form(self.scrollable)
    
    def _build_form(self, parent):
        # Tkinter 変数
        s = self.settings
        self.var_dify_api_base = tk.StringVar(value=s.dify_api_base)
        self.var_dify_key_schema = tk.StringVar(value=s.dify_api_key_schema)
        self.var_dify_key_tagging = tk.StringVar(value=s.dify_api_key_tagging)
        self.var_ca_cert_path = tk.StringVar(value=s.dify_ca_cert_path)
        
        self.var_mssql_server = tk.StringVar(value=s.mssql_server)
        self.var_mssql_database = tk.StringVar(value=s.mssql_database)
        self.var_mssql_user = tk.StringVar(value=s.mssql_user)
        self.var_mssql_password = tk.StringVar(value=s.mssql_password)
        self.var_mssql_driver = tk.StringVar(value=s.mssql_driver)
        
        self.var_batch_size = tk.IntVar(value=s.batch_size)
        self.var_max_concurrent = tk.IntVar(value=s.max_concurrent)
        self.var_max_retries = tk.IntVar(value=s.max_retries)
        self.var_request_timeout = tk.IntVar(value=s.request_timeout)
        self.var_max_comment_length = tk.IntVar(value=s.max_comment_length)
        self.var_tagging_warn_threshold = tk.IntVar(value=s.tagging_warn_threshold)
        
        self.var_output_dir = tk.StringVar(value=s.output_dir)
        
        row = 0
        pad = {"padx": 8, "pady": 4}
        
        # === Dify API セクション ===
        self._section_header(parent, "Dify API", row); row += 1
        
        ttk.Label(parent, text="ベースURL:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(parent, textvariable=self.var_dify_api_base, width=50).grid(
            row=row, column=1, sticky="we", **pad
        ); row += 1
        
        ttk.Label(parent, text="APIキー(スキーマ生成):").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(parent, textvariable=self.var_dify_key_schema, width=50, show="•").grid(
            row=row, column=1, sticky="we", **pad
        ); row += 1
        
        ttk.Label(parent, text="APIキー(タグ付け):").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(parent, textvariable=self.var_dify_key_tagging, width=50, show="•").grid(
            row=row, column=1, sticky="we", **pad
        ); row += 1
        
        # CA 証明書パス
        ttk.Label(parent, text="CA証明書パス:").grid(row=row, column=0, sticky="e", **pad)
        cert_frame = ttk.Frame(parent)
        cert_frame.grid(row=row, column=1, sticky="we", **pad)
        ttk.Entry(cert_frame, textvariable=self.var_ca_cert_path, width=42).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(cert_frame, text="参照...", command=self._browse_cert).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(cert_frame, text="テスト", command=self._test_cert).pack(
            side="left", padx=(4, 0)
        )
        row += 1
        
        # === SQL Server セクション ===
        self._section_header(parent, "MS SQL Server (CSV しか使わない場合は空欄可)", row); row += 1
        
        for label, var in [
            ("Server:", self.var_mssql_server),
            ("Database:", self.var_mssql_database),
            ("User:", self.var_mssql_user),
            ("Password:", self.var_mssql_password),
            ("Driver:", self.var_mssql_driver),
        ]:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", **pad)
            show = "•" if "Password" in label else None
            entry = ttk.Entry(parent, textvariable=var, width=50,
                              show=show) if show else \
                    ttk.Entry(parent, textvariable=var, width=50)
            entry.grid(row=row, column=1, sticky="we", **pad)
            row += 1
        
        # === 処理パラメータ ===
        self._section_header(parent, "処理パラメータ", row); row += 1
        
        for label, var, hint in [
            ("バッチサイズ:", self.var_batch_size, "10〜20推奨"),
            ("並列数:", self.var_max_concurrent, "3〜10推奨"),
            ("リトライ回数:", self.var_max_retries, "通常3"),
            ("タイムアウト(秒):", self.var_request_timeout, "120推奨"),
            ("最大コメント長:", self.var_max_comment_length, "1カラム超過分は切詰め"),
            ("タグ付け警告件数:", self.var_tagging_warn_threshold, "この件数超で確認(既定500)"),
        ]:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", **pad)
            spin = ttk.Spinbox(parent, from_=1, to=999999, textvariable=var, width=10)
            spin.grid(row=row, column=1, sticky="w", **pad)
            ttk.Label(parent, text=hint, foreground="gray").grid(
                row=row, column=1, sticky="w", padx=(120, 8)
            )
            row += 1
        
        # === 出力 ===
        self._section_header(parent, "出力", row); row += 1
        
        ttk.Label(parent, text="出力先ディレクトリ:").grid(row=row, column=0, sticky="e", **pad)
        out_frame = ttk.Frame(parent)
        out_frame.grid(row=row, column=1, sticky="we", **pad)
        ttk.Entry(out_frame, textvariable=self.var_output_dir, width=42).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(out_frame, text="参照...", command=self._browse_output).pack(
            side="left", padx=(4, 0)
        )
        row += 1
        ttk.Label(parent, text="(空欄なら ./output)", foreground="gray").grid(
            row=row, column=1, sticky="w", padx=(12, 0)
        )
        row += 1
        
        # === ボタン ===
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="e", pady=(20, 10), padx=8)
        ttk.Button(btn_frame, text="設定を保存",
                   command=self._on_save).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="変更を破棄",
                   command=self._on_revert).pack(side="right", padx=2)
        
        # ステータス表示
        self.var_status = tk.StringVar(value="")
        self.lbl_status = ttk.Label(parent, textvariable=self.var_status,
                                    foreground="green")
        self.lbl_status.grid(row=row + 1, column=0, columnspan=2, padx=8, pady=(0, 10))
        
        parent.columnconfigure(1, weight=1)
    
    def _section_header(self, parent, text, row):
        # ヘッダラベル(セパレータとセットで表示)
        sep = ttk.Separator(parent, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=2, sticky="we", pady=(16, 4))
        lbl = ttk.Label(parent, text=text, font=("", 11, "bold"))
        lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
    
    # ------------------------------------------------------------------
    # アクション
    # ------------------------------------------------------------------
    
    def _browse_cert(self):
        path = filedialog.askopenfilename(
            title="CA証明書ファイルを選択",
            filetypes=[
                ("証明書ファイル", "*.pem *.crt *.cer"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if path:
            self.var_ca_cert_path.set(path)
    
    def _browse_output(self):
        path = filedialog.askdirectory(title="出力先ディレクトリを選択")
        if path:
            self.var_output_dir.set(path)
    
    def _test_cert(self):
        """証明書ファイルが見つかるかテスト"""
        path = self.var_ca_cert_path.get().strip()
        if not path:
            messagebox.showwarning("証明書テスト", "CA証明書パスが空です。")
            return
        
        try:
            # 一時的に config に反映してから resolve を試す
            import config
            original = config.DIFY_CA_CERT_PATH
            config.DIFY_CA_CERT_PATH = path
            try:
                from dify_client import resolve_ca_cert_path, _build_ssl_context
                resolved = resolve_ca_cert_path()
                _build_ssl_context(resolved)
                messagebox.showinfo(
                    "証明書テスト",
                    f"✅ 証明書ファイルが正しく読み込めました。\n\n"
                    f"解決後のパス:\n{resolved}"
                )
            finally:
                config.DIFY_CA_CERT_PATH = original
        except Exception as e:
            messagebox.showerror(
                "証明書テスト失敗",
                f"❌ 証明書ファイルの読み込みに失敗しました。\n\n{e}"
            )
    
    def _on_save(self):
        """設定を AppSettings に書き戻し、ファイル保存、config に反映"""
        try:
            self._sync_ui_to_settings()
            saved_path = self.settings.save()
            try:
                self.settings.apply_to_config_module()
            except ImportError:
                pass  # config モジュールが無い環境
            
            self.var_status.set(f"✅ 保存しました: {saved_path}")
            self.lbl_status.configure(foreground="green")
            self.app.set_status("設定を保存しました")
        except Exception as e:
            messagebox.showerror("保存失敗", f"設定の保存に失敗しました:\n{e}")
            self.var_status.set(f"❌ 保存失敗: {e}")
            self.lbl_status.configure(foreground="red")
    
    def _on_revert(self):
        """UI の変更を破棄して AppSettings の値に戻す"""
        if not messagebox.askyesno(
            "変更を破棄", "UI上の編集を破棄して保存済みの設定に戻しますか?"
        ):
            return
        self.refresh_from_state()
        self.var_status.set("変更を破棄しました")
        self.lbl_status.configure(foreground="gray")
    
    def _sync_ui_to_settings(self):
        """Tk 変数 → AppSettings に書き戻し"""
        s = self.settings
        s.dify_api_base = self.var_dify_api_base.get().strip()
        s.dify_api_key_schema = self.var_dify_key_schema.get().strip()
        s.dify_api_key_tagging = self.var_dify_key_tagging.get().strip()
        s.dify_ca_cert_path = self.var_ca_cert_path.get().strip()
        
        s.mssql_server = self.var_mssql_server.get().strip()
        s.mssql_database = self.var_mssql_database.get().strip()
        s.mssql_user = self.var_mssql_user.get().strip()
        s.mssql_password = self.var_mssql_password.get()  # PW 前後空白はそのまま
        s.mssql_driver = self.var_mssql_driver.get().strip()
        
        s.batch_size = int(self.var_batch_size.get())
        s.max_concurrent = int(self.var_max_concurrent.get())
        s.max_retries = int(self.var_max_retries.get())
        s.request_timeout = int(self.var_request_timeout.get())
        s.max_comment_length = int(self.var_max_comment_length.get())
        s.tagging_warn_threshold = int(self.var_tagging_warn_threshold.get())
        
        s.output_dir = self.var_output_dir.get().strip()
    
    # ------------------------------------------------------------------
    # 基底クラスのフック
    # ------------------------------------------------------------------
    
    def on_hide(self):
        """他のタブに切り替わる時、UI 入力を AppSettings に反映(保存はしない)"""
        try:
            self._sync_ui_to_settings()
            # config モジュールにも即反映(他タブで dify を呼ぶときのため)
            try:
                self.settings.apply_to_config_module()
            except ImportError:
                pass
        except (tk.TclError, ValueError):
            # 不正な値が入っていれば無視(保存時に弾く)
            pass
    
    def refresh_from_state(self):
        """settings の値で UI を上書き(セッションロード後等)"""
        s = self.settings
        self.var_dify_api_base.set(s.dify_api_base)
        self.var_dify_key_schema.set(s.dify_api_key_schema)
        self.var_dify_key_tagging.set(s.dify_api_key_tagging)
        self.var_ca_cert_path.set(s.dify_ca_cert_path)
        
        self.var_mssql_server.set(s.mssql_server)
        self.var_mssql_database.set(s.mssql_database)
        self.var_mssql_user.set(s.mssql_user)
        self.var_mssql_password.set(s.mssql_password)
        self.var_mssql_driver.set(s.mssql_driver)
        
        self.var_batch_size.set(s.batch_size)
        self.var_max_concurrent.set(s.max_concurrent)
        self.var_max_retries.set(s.max_retries)
        self.var_request_timeout.set(s.request_timeout)
        self.var_max_comment_length.set(s.max_comment_length)
        self.var_tagging_warn_threshold.set(s.tagging_warn_threshold)
        
        self.var_output_dir.set(s.output_dir)
