"""
gui/tabs/tagging_tab.py - タグ付け実行タブ

役割:
- 実行前情報表示(レコード数、バッチ数、想定時間)
- 「タグ付け開始」ボタンで Worker 起動
- 進捗バー、ログ表示、失敗バッチ一覧
- 失敗バッチ再実行(BATCH_SIZE を半分にして再試行)
- 完了後 tagged_df を state に格納
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from gui.tabs.base import BaseTab
from gui.workers import Worker, QueuePoller


class TaggingTab(BaseTab):
    TITLE = "タグ付け実行"
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:実行前情報 ===
        info_frame = ttk.LabelFrame(main, text="実行前の確認", padding=8)
        info_frame.pack(fill="x")
        
        self.var_info = tk.StringVar(value="(前のタブで前処理を完了してください)")
        ttk.Label(info_frame, textvariable=self.var_info,
                  font=("Monospace", 10)).pack(anchor="w")
        
        # === 操作ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        self.btn_start = ttk.Button(btn_frame, text="タグ付け開始",
                                    command=self._on_start)
        self.btn_start.pack(side="left", padx=2)
        
        self.btn_retry = ttk.Button(
            btn_frame, text="失敗バッチを再実行",
            command=self._on_retry, state="disabled"
        )
        self.btn_retry.pack(side="left", padx=2)
        
        self.btn_clear = ttk.Button(btn_frame, text="ログクリア",
                                    command=self._clear_log)
        self.btn_clear.pack(side="left", padx=2)
        
        self.var_status = tk.StringVar(value="準備完了")
        ttk.Label(btn_frame, textvariable=self.var_status,
                  foreground="gray").pack(side="right")
        
        # === 進捗バー ===
        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill="x", pady=(12, 0))
        
        ttk.Label(progress_frame, text="進捗:").pack(side="left")
        self.var_progress_text = tk.StringVar(value="0 / 0")
        ttk.Label(progress_frame, textvariable=self.var_progress_text,
                  width=20).pack(side="right")
        
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", pady=(2, 0))
        
        # === 失敗バッチ表示 ===
        ttk.Label(main, text="失敗バッチ:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(12, 2))
        fail_frame = ttk.Frame(main)
        fail_frame.pack(fill="x")
        
        columns = ("batch_idx", "ids", "error")
        self.tree_failed = ttk.Treeview(fail_frame, columns=columns,
                                        show="headings", height=4)
        self.tree_failed.heading("batch_idx", text="バッチ#")
        self.tree_failed.heading("ids", text="repair_id")
        self.tree_failed.heading("error", text="エラー")
        self.tree_failed.column("batch_idx", width=80, anchor="center")
        self.tree_failed.column("ids", width=200)
        self.tree_failed.column("error", width=600)
        
        fail_scroll = ttk.Scrollbar(fail_frame, orient="vertical",
                                    command=self.tree_failed.yview)
        self.tree_failed.configure(yscrollcommand=fail_scroll.set)
        self.tree_failed.pack(side="left", fill="x", expand=True)
        fail_scroll.pack(side="right", fill="y")
        
        # === ログ ===
        ttk.Label(main, text="ログ:", font=("", 10, "bold")).pack(
            anchor="w", pady=(12, 2)
        )
        log_frame = ttk.Frame(main)
        log_frame.pack(fill="both", expand=True)
        
        self.txt_log = tk.Text(log_frame, wrap="word", height=8,
                               font=("Monospace", 9), state="disabled",
                               background="#f5f5f5")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                   command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        
        # ワーカー管理
        self._msg_queue: Optional[queue.Queue] = None
        self._worker: Optional[Worker] = None
        self._poller: Optional[QueuePoller] = None
        self._is_retry = False
    
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
    # 実行前情報更新
    # ------------------------------------------------------------------
    
    def _update_info(self):
        if not self.state.schema:
            self.var_info.set("❌ スキーマが未生成です(問い合わせタブ)")
            self.btn_start.configure(state="disabled")
            return
        if not self.state.records or not self.state.batches:
            self.var_info.set(
                "❌ 前処理が未実行です(データ取得タブで「前処理実行」)"
            )
            self.btn_start.configure(state="disabled")
            return
        
        n_records = len(self.state.records)
        n_batches = len(self.state.batches)
        batch_size = self.settings.batch_size
        max_concurrent = self.settings.max_concurrent
        
        # 想定時間の試算(1バッチ ≈ 30秒、並列数で割る)
        est_sec = n_batches * 30 / max_concurrent
        if est_sec < 60:
            est_str = f"{int(est_sec)}秒"
        elif est_sec < 3600:
            est_str = f"{int(est_sec / 60)}分"
        else:
            est_str = f"{est_sec / 3600:.1f}時間"
        
        lines = [
            f"レコード数:   {n_records}件",
            f"バッチ数:     {n_batches} (1バッチ {batch_size}件)",
            f"並列数:       {max_concurrent}",
            f"想定実行時間: {est_str} 程度(目安)",
            f"軸構成:       core×{sum(1 for a in self.state.schema['axes'] if a.get('tier') == 'core')} "
            f"+ detail×{sum(1 for a in self.state.schema['axes'] if a.get('tier') == 'detail')}",
        ]
        self.var_info.set("\n".join(lines))
        self.btn_start.configure(state="normal")
    
    # ------------------------------------------------------------------
    # 実行
    # ------------------------------------------------------------------
    
    def _on_start(self):
        if not self._can_run():
            return
        
        if not self.settings.dify_api_key_tagging:
            messagebox.showwarning(
                "設定不足",
                "Dify API キー(タグ付け)が未設定です。"
                "「設定」タブで入力してください。"
            )
            return
        
        # 件数がしきい値を超える場合、トークン消費の警告を出す
        try:
            import config
            threshold = getattr(config, "TAGGING_WARN_THRESHOLD", 500)
        except ImportError:
            threshold = 500
        
        n_records = len(self.state.records) if self.state.records else 0
        if n_records > threshold:
            if not messagebox.askyesno(
                "件数確認",
                f"{n_records} 件をタグ付けしようとしています"
                f"(警告しきい値: {threshold} 件)。\n\n"
                "件数が多いとトークンを多く消費します。続行しますか?",
                icon="warning",
            ):
                return
        
        # 既存の結果がある場合は確認
        if self.state.batch_results:
            if not messagebox.askyesno(
                "確認",
                "既にタグ付け結果があります。再実行すると上書きされます。続行しますか?"
            ):
                return
        
        self._is_retry = False
        self._run_tagging(self.state.batches, label="本実行")
    
    def _on_retry(self):
        """失敗バッチだけ再実行(BATCH_SIZE を半分にする)"""
        if not self.state.batch_results:
            return
        
        failed = [b for b in self.state.batch_results if not b["success"]]
        if not failed:
            messagebox.showinfo("再実行", "失敗バッチはありません。")
            return
        
        # 失敗バッチの records を再構築
        failed_ids = set()
        for b in failed:
            failed_ids.update(b["input_ids"])
        
        retry_records = [r for r in self.state.records
                         if r["repair_id"] in failed_ids]
        if not retry_records:
            messagebox.showwarning("エラー", "再実行対象のレコードが見つかりません。")
            return
        
        # バッチサイズを半分にして再バッチ化
        try:
            import preprocess
        except ImportError:
            messagebox.showerror("エラー", "preprocess モジュールが見つかりません。")
            return
        
        new_batch_size = max(1, self.settings.batch_size // 2)
        retry_batches = preprocess.chunk_records(retry_records,
                                                  batch_size=new_batch_size)
        
        self._log(
            f"\n=== 失敗バッチ再実行 ({len(failed)}件 → "
            f"{len(retry_batches)}バッチ, batch_size={new_batch_size}) ==="
        )
        
        self._is_retry = True
        self._retry_batches = retry_batches
        self._run_tagging(retry_batches, label="再実行")
    
    def _can_run(self) -> bool:
        if not self.state.schema:
            messagebox.showwarning("エラー", "スキーマが未生成です。")
            return False
        if not self.state.records or not self.state.batches:
            messagebox.showwarning("エラー", "前処理が未実行です。")
            return False
        return True
    
    def _run_tagging(self, batches: list, label: str):
        self.btn_start.configure(state="disabled")
        self.btn_retry.configure(state="disabled")
        self.var_status.set(f"{label}中…")
        self.app.set_status(f"タグ付け{label}中…")
        
        self.progress.configure(maximum=len(batches), value=0)
        self.var_progress_text.set(f"0 / {len(batches)}")
        
        self._log(f"\n=== {label}開始 ===")
        self._log(f"バッチ数: {len(batches)}")
        
        schema = self.state.schema
        summary = schema.get("query_summary", "")
        
        # 確実に config モジュールに settings を反映
        try:
            self.settings.apply_to_config_module()
        except ImportError:
            pass
        
        def task(progress_callback=None):
            import dify_client
            return dify_client.run_tagging_sync(
                tag_schema=schema,
                inquiry_summary=summary,
                batches=batches,
                progress_callback=progress_callback,
            )
        
        self._msg_queue = queue.Queue()
        self._worker = Worker(
            target=task,
            msg_queue=self._msg_queue,
            pass_progress_callback=True,
        )
        self._poller = QueuePoller(
            root=self.app.root,
            msg_queue=self._msg_queue,
            on_progress=self._on_progress,
            on_done=self._on_done,
            on_error=self._on_error,
            interval_ms=100,
        )
        self._worker.start()
        self._poller.start()
    
    # ------------------------------------------------------------------
    # 進捗・完了ハンドラ
    # ------------------------------------------------------------------
    
    def _on_progress(self, payload: dict):
        done = payload["done"]
        total = payload["total"]
        self.progress.configure(value=done)
        self.var_progress_text.set(f"{done} / {total}")
        
        if payload.get("info"):
            self._log(payload["info"])
    
    def _on_done(self, batch_results: list):
        if self._is_retry:
            # 再実行の場合、既存の失敗バッチを成功分で置き換える
            existing_success = [b for b in self.state.batch_results if b["success"]]
            existing_failed_ids = set()
            for b in self.state.batch_results:
                if not b["success"]:
                    existing_failed_ids.update(b["input_ids"])
            
            # 再実行結果: 成功と失敗を分ける
            new_success = [b for b in batch_results if b["success"]]
            new_failed = [b for b in batch_results if not b["success"]]
            
            # 統合: 既存成功 + 新規成功 + 新規失敗
            self.state.batch_results = existing_success + new_success + new_failed
        else:
            self.state.batch_results = batch_results
        
        # 統計
        n_total = len(batch_results)
        n_success = sum(1 for b in batch_results if b["success"])
        n_failed = n_total - n_success
        
        self._log(f"✅ 完了: 成功 {n_success} / 失敗 {n_failed} (/ 合計 {n_total} バッチ)")
        
        # フラット化 → tagged_df へ
        try:
            import scoring
            tagged_df = scoring.flatten_tagging_results(
                self.state.batch_results, self.state.schema
            )
            self.state.tagged_df = tagged_df
            self._log(f"タグ付け結果フラット化: {len(tagged_df)}件")
        except Exception as e:
            # 詳細を吐いて原因究明を助ける
            self._log(f"⚠️ フラット化エラー: {type(e).__name__}: {e}")
            
            # batch_results の構造をダンプ
            try:
                br = self.state.batch_results
                if br:
                    self._log(f"  batch_results 件数: {len(br)}")
                    first = br[0]
                    self._log(f"  [0] success: {first.get('success')}")
                    self._log(f"  [0] type(results): {type(first.get('results'))}")
                    
                    results = first.get("results")
                    if isinstance(results, list) and len(results) > 0:
                        self._log(f"  [0] len(results): {len(results)}")
                        item = results[0]
                        self._log(f"  [0] type(results[0]): {type(item).__name__}")
                        if isinstance(item, str):
                            self._log(f"  [0] results[0] が文字列(先頭200字): {item[:200]}")
                        elif isinstance(item, dict):
                            self._log(f"  [0] results[0] keys: {list(item.keys())}")
                        else:
                            self._log(f"  [0] results[0] 内容: {repr(item)[:200]}")
                    elif isinstance(results, str):
                        self._log(f"  [0] results が文字列(先頭300字): {results[:300]}")
                    else:
                        self._log(f"  [0] results 内容: {repr(results)[:300]}")
            except Exception as dump_err:
                self._log(f"  ダンプ自体に失敗: {dump_err}")
            
            messagebox.showerror(
                "フラット化エラー",
                f"{type(e).__name__}: {e}\n\n"
                f"詳細はログ欄を確認してください。\n"
                f"よくある原因: Dify からの返り値が想定形式と違う(配列の中身が文字列等)"
            )
        
        # 失敗バッチ表示
        self._refresh_failed_tree()
        
        self.btn_start.configure(state="normal")
        if n_failed > 0:
            self.btn_retry.configure(state="normal")
        
        self.var_status.set(f"完了 (失敗 {n_failed})")
        self.app.set_status(f"タグ付け完了 (成功 {n_success} / 失敗 {n_failed})")
        
        if n_failed == 0:
            messagebox.showinfo(
                "完了",
                f"タグ付けが完了しました。\n"
                f"成功: {n_success} バッチ\n\n"
                f"「絞り込み」タブに進めます。"
            )
        else:
            messagebox.showwarning(
                "完了(一部失敗)",
                f"タグ付けが完了しましたが {n_failed} バッチで失敗があります。\n"
                f"「失敗バッチを再実行」ボタンで再試行できます。"
            )
    
    def _on_error(self, err: dict):
        self._log(f"❌ {err['exc_type']}: {err['message']}")
        tb_lines = err['traceback'].strip().split("\n")
        for line in tb_lines[-6:]:
            self._log(f"  {line}")
        
        self.btn_start.configure(state="normal")
        self.var_status.set("エラー")
        self.app.set_status("タグ付けエラー")
        
        messagebox.showerror(
            "タグ付けエラー",
            f"{err['exc_type']}\n\n{err['message']}"
        )
    
    def _refresh_failed_tree(self):
        self.tree_failed.delete(*self.tree_failed.get_children())
        if not self.state.batch_results:
            return
        for b in self.state.batch_results:
            if not b["success"]:
                self.tree_failed.insert("", "end", values=(
                    b["batch_idx"],
                    ", ".join(b["input_ids"][:3])
                    + ("..." if len(b["input_ids"]) > 3 else ""),
                    b.get("error", "")[:120],
                ))
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_show(self):
        self._update_info()
        self._refresh_failed_tree()
        if self.state.batch_results:
            n_failed = sum(1 for b in self.state.batch_results if not b["success"])
            if n_failed > 0:
                self.btn_retry.configure(state="normal")
    
    def refresh_from_state(self):
        self._update_info()
        self._refresh_failed_tree()
        self.progress.configure(value=0, maximum=1)
        self.var_progress_text.set("0 / 0")
        self._clear_log()
        if self.state.batch_results:
            n_success = sum(1 for b in self.state.batch_results if b["success"])
            n_failed = sum(1 for b in self.state.batch_results if not b["success"])
            self._log(f"過去のセッション: 成功 {n_success} / 失敗 {n_failed}")
            self.var_status.set(f"過去結果あり (失敗 {n_failed})")
            if n_failed > 0:
                self.btn_retry.configure(state="normal")
