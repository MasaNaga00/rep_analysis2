"""
gui/tabs/inquiry_tab.py - 問い合わせタブ

役割:
- 問い合わせ文(複数行)を入力
- max_detail_axes を選択
- 「スキーマ生成」ボタンで Dify 1回目をワーカースレッドで実行
- 完了後、AppState.schema に格納してスキーマ編集タブに進むよう促す
- 進捗・エラーをログ表示
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from gui.tabs.base import BaseTab
from gui.workers import Worker, QueuePoller


class InquiryTab(BaseTab):
    TITLE = "問い合わせ"
    
    PLACEHOLDER = (
        "例: EOS R7 で、冬の屋外撮影時に AF が迷う現象が複数のお客様から\n"
        "報告されている。特定のレンズ装着時に発生するのか、個体差なのか、\n"
        "低温環境に起因するのか切り分けたい。"
    )
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:問い合わせ文 ===
        ttk.Label(main, text="問い合わせ内容(複数行可):",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        
        text_frame = ttk.Frame(main)
        text_frame.pack(fill="both", expand=True)
        
        self.txt_inquiry = tk.Text(text_frame, wrap="word", height=10,
                                   font=("", 11))
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical",
                                  command=self.txt_inquiry.yview)
        self.txt_inquiry.configure(yscrollcommand=scrollbar.set)
        self.txt_inquiry.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # プレースホルダ表示
        self.txt_inquiry.insert("1.0", self.PLACEHOLDER)
        self.txt_inquiry.configure(foreground="gray")
        self._placeholder_active = True
        self.txt_inquiry.bind("<FocusIn>", self._on_text_focus_in)
        self.txt_inquiry.bind("<FocusOut>", self._on_text_focus_out)
        
        # === 中部:パラメータ ===
        param_frame = ttk.Frame(main)
        param_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Label(param_frame, text="detail軸の最大数:").pack(side="left")
        self.var_max_detail = tk.IntVar(value=4)
        ttk.Spinbox(param_frame, from_=0, to=10, textvariable=self.var_max_detail,
                    width=5).pack(side="left", padx=(4, 16))
        
        ttk.Label(param_frame, text="(0〜10、デフォルト4)",
                  foreground="gray").pack(side="left")
        
        # === ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        self.btn_generate = ttk.Button(
            btn_frame, text="スキーマ生成 (Dify 1回目)",
            command=self._on_generate
        )
        self.btn_generate.pack(side="left")
        
        self.btn_clear_log = ttk.Button(
            btn_frame, text="ログクリア", command=self._clear_log
        )
        self.btn_clear_log.pack(side="left", padx=4)
        
        # ステータス
        self.var_status = tk.StringVar(value="準備完了")
        ttk.Label(btn_frame, textvariable=self.var_status,
                  foreground="gray").pack(side="right")
        
        # === 下部:ログ表示 ===
        ttk.Label(main, text="ログ:", font=("", 10, "bold")).pack(
            anchor="w", pady=(10, 2)
        )
        log_frame = ttk.Frame(main)
        log_frame.pack(fill="both")
        
        self.txt_log = tk.Text(log_frame, wrap="word", height=8,
                               font=("Monospace", 9), state="disabled",
                               background="#f5f5f5")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                   command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        
        # ワーカー管理
        self._worker: Optional[Worker] = None
        self._msg_queue: Optional[queue.Queue] = None
        self._poller: Optional[QueuePoller] = None
    
    # ------------------------------------------------------------------
    # プレースホルダ処理
    # ------------------------------------------------------------------
    
    def _on_text_focus_in(self, event):
        if self._placeholder_active:
            self.txt_inquiry.delete("1.0", "end")
            self.txt_inquiry.configure(foreground="black")
            self._placeholder_active = False
    
    def _on_text_focus_out(self, event):
        if not self.txt_inquiry.get("1.0", "end").strip():
            self.txt_inquiry.insert("1.0", self.PLACEHOLDER)
            self.txt_inquiry.configure(foreground="gray")
            self._placeholder_active = True
    
    def _get_inquiry_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self.txt_inquiry.get("1.0", "end").strip()
    
    def _set_inquiry_text(self, text: str):
        self.txt_inquiry.delete("1.0", "end")
        if text:
            self.txt_inquiry.insert("1.0", text)
            self.txt_inquiry.configure(foreground="black")
            self._placeholder_active = False
        else:
            self.txt_inquiry.insert("1.0", self.PLACEHOLDER)
            self.txt_inquiry.configure(foreground="gray")
            self._placeholder_active = True
    
    # ------------------------------------------------------------------
    # ログ
    # ------------------------------------------------------------------
    
    def _log(self, message: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", message + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
    
    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")
    
    # ------------------------------------------------------------------
    # スキーマ生成実行
    # ------------------------------------------------------------------
    
    def _on_generate(self):
        inquiry = self._get_inquiry_text()
        if not inquiry:
            messagebox.showwarning("入力エラー", "問い合わせ内容を入力してください。")
            return
        
        # 設定チェック
        from gui.settings_store import AppSettings  # for type
        if not self.settings.dify_api_key_schema:
            messagebox.showwarning(
                "設定不足",
                "Dify API キー(スキーマ生成)が未設定です。\n"
                "「設定」タブで入力してください。"
            )
            return
        if not self.settings.dify_ca_cert_path:
            messagebox.showwarning(
                "設定不足",
                "CA証明書パスが未設定です。「設定」タブで入力してください。"
            )
            return
        
        # AppState に保存
        self.state.inquiry_text = inquiry
        max_detail = int(self.var_max_detail.get())
        
        # ボタン無効化、ステータス更新
        self.btn_generate.configure(state="disabled", text="生成中…")
        self.var_status.set("Dify にリクエスト中…")
        self.app.set_status("スキーマ生成中…")
        self._log(f"=== スキーマ生成開始 ===")
        self._log(f"問い合わせ: {inquiry[:80]}{'…' if len(inquiry) > 80 else ''}")
        self._log(f"max_detail_axes: {max_detail}")
        
        # ワーカー起動
        self._msg_queue = queue.Queue()
        
        def task():
            # config モジュールの値を最新に
            try:
                self.settings.apply_to_config_module()
            except ImportError:
                pass
            
            import dify_client
            return dify_client.generate_tag_schema(
                inquiry_text=inquiry,
                max_detail_axes=max_detail,
            )
        
        self._worker = Worker(target=task, msg_queue=self._msg_queue)
        self._poller = QueuePoller(
            root=self.app.root,
            msg_queue=self._msg_queue,
            on_done=self._on_generate_done,
            on_error=self._on_generate_error,
            interval_ms=100,
        )
        self._worker.start()
        self._poller.start()
    
    def _on_generate_done(self, schema: dict):
        self.state.schema = schema
        self._log(f"✅ スキーマ生成完了")
        self._log(f"  query_summary: {schema.get('query_summary', '(なし)')}")
        n_core = sum(1 for a in schema.get("axes", []) if a.get("tier") == "core")
        n_detail = sum(1 for a in schema.get("axes", []) if a.get("tier") == "detail")
        self._log(f"  軸構成: core={n_core}, detail={n_detail}")
        for ax in schema.get("axes", []):
            cands = ax.get("candidates", [])
            cands_str = ", ".join(cands[:5])
            if len(cands) > 5:
                cands_str += f", ...(全{len(cands)}個)"
            self._log(f"    [{ax.get('tier')}] {ax.get('name')}: {cands_str}")
        
        self.btn_generate.configure(state="normal",
                                    text="スキーマ生成 (Dify 1回目)")
        self.var_status.set("完了")
        self.app.set_status("スキーマ生成完了")
        
        messagebox.showinfo(
            "スキーマ生成完了",
            f"タグスキーマを生成しました。\n"
            f"軸: core={n_core}, detail={n_detail}\n\n"
            f"「スキーマ編集」タブで内容を確認・編集してください。"
        )
    
    def _on_generate_error(self, err: dict):
        self._log(f"❌ エラー: {err['exc_type']}: {err['message']}")
        # トレースバックの最後の数行だけ表示
        tb_lines = err['traceback'].strip().split("\n")
        for line in tb_lines[-6:]:
            self._log(f"  {line}")
        
        self.btn_generate.configure(state="normal",
                                    text="スキーマ生成 (Dify 1回目)")
        self.var_status.set("エラー")
        self.app.set_status("スキーマ生成エラー")
        
        messagebox.showerror(
            "スキーマ生成エラー",
            f"{err['exc_type']}\n\n{err['message']}\n\n"
            f"詳細はログを確認してください。"
        )
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_hide(self):
        """他タブに切り替わる時、問い合わせ文を state に保存"""
        self.state.inquiry_text = self._get_inquiry_text()
    
    def on_show(self):
        """このタブに切り替わった時、state から問い合わせ文を復元"""
        if self.state.inquiry_text and self.state.inquiry_text != self._get_inquiry_text():
            self._set_inquiry_text(self.state.inquiry_text)
    
    def refresh_from_state(self):
        """セッションロード後、UI を state から再構築"""
        self._set_inquiry_text(self.state.inquiry_text or "")
        self._clear_log()
        self.var_status.set("準備完了")
