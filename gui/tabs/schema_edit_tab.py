"""
gui/tabs/schema_edit_tab.py - スキーマ編集タブ

役割:
- AppState.schema の軸一覧を Treeview で表示
- 軸の追加(detail のみ。core は1つだけのため通常追加しない)
- 軸の編集(AxisEditorDialog)
- 軸の削除
- 軸の並び替え
- query_summary の編集
- 「再生成結果に戻す」(問い合わせタブで生成された値に戻すのは不可、
  この機能は次回スキーマ生成時に上書きされる前提なので省略)
- JSON プレビュー
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox

from gui.tabs.base import BaseTab
from gui.widgets.schema_editor import AxisEditorDialog


class SchemaEditTab(BaseTab):
    TITLE = "スキーマ編集"
    
    def build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(expand=True, fill="both")
        
        # === 上部:query_summary ===
        top = ttk.Frame(main)
        top.pack(fill="x", pady=(0, 8))
        
        ttk.Label(top, text="クエリ要約:", font=("", 10, "bold")).pack(
            anchor="w"
        )
        self.var_summary = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_summary, width=80).pack(
            fill="x", pady=2
        )
        
        # === 中部:軸一覧 ===
        ttk.Label(main, text="軸一覧:", font=("", 10, "bold")).pack(
            anchor="w", pady=(8, 2)
        )
        
        tree_frame = ttk.Frame(main)
        tree_frame.pack(fill="both", expand=True)
        
        columns = ("tier", "name", "priority", "candidates")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                 height=10)
        self.tree.heading("tier", text="tier")
        self.tree.heading("name", text="軸の名前")
        self.tree.heading("priority", text="priority")
        self.tree.heading("candidates", text="候補(先頭抜粋)")
        self.tree.column("tier", width=60, anchor="center")
        self.tree.column("name", width=180)
        self.tree.column("priority", width=80, anchor="center")
        self.tree.column("candidates", width=400)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        
        self.tree.bind("<Double-1>", lambda e: self._on_edit())
        
        # === 操作ボタン ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        ttk.Button(btn_frame, text="detail軸を追加",
                   command=self._on_add).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="編集 (ダブルクリック可)",
                   command=self._on_edit).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="削除",
                   command=self._on_delete).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="↑",
                   command=lambda: self._on_move(-1), width=3).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="↓",
                   command=lambda: self._on_move(1), width=3).pack(side="left", padx=2)
        
        ttk.Button(btn_frame, text="JSON プレビュー",
                   command=self._show_json).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="変更を適用",
                   command=self._apply_changes).pack(side="right", padx=2)
        
        # === ステータス ===
        self.var_status = tk.StringVar(
            value="(「問い合わせ」タブでスキーマを生成してから表示されます)"
        )
        ttk.Label(main, textvariable=self.var_status,
                  foreground="gray").pack(anchor="w", pady=(8, 0))
    
    # ------------------------------------------------------------------
    # state ⇔ UI
    # ------------------------------------------------------------------
    
    def _refresh_tree(self):
        """state.schema から Treeview を再構築"""
        self.tree.delete(*self.tree.get_children())
        if not self.state.schema:
            return
        
        for i, ax in enumerate(self.state.schema.get("axes", [])):
            cands = ax.get("candidates", [])
            cands_str = ", ".join(cands[:4])
            if len(cands) > 4:
                cands_str += f", ...(全{len(cands)}個)"
            self.tree.insert("", "end", iid=str(i), values=(
                ax.get("tier", ""),
                ax.get("name", ""),
                ax.get("priority", ""),
                cands_str,
            ))
        
        self.var_summary.set(self.state.schema.get("query_summary", ""))
        
        n_core = sum(1 for a in self.state.schema.get("axes", [])
                     if a.get("tier") == "core")
        n_detail = sum(1 for a in self.state.schema.get("axes", [])
                       if a.get("tier") == "detail")
        self.var_status.set(
            f"スキーマ: core軸={n_core}, detail軸={n_detail}"
        )
    
    def _apply_changes(self):
        """summary の編集を state に反映"""
        if not self.state.schema:
            return
        self.state.schema["query_summary"] = self.var_summary.get().strip()
        messagebox.showinfo("適用完了", "スキーマの変更を適用しました。")
        self.app.set_status("スキーマを更新しました")
    
    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    
    def _on_add(self):
        if not self.state.schema:
            messagebox.showwarning(
                "スキーマなし",
                "まず「問い合わせ」タブでスキーマを生成してください。"
            )
            return
        
        # core 軸は既に存在するので detail のみ追加可
        n_detail = sum(1 for a in self.state.schema["axes"]
                       if a.get("tier") == "detail")
        if n_detail >= 4:
            if not messagebox.askyesno(
                "確認",
                f"detail軸が既に {n_detail} 個あります。"
                "実データで情報欠落しやすい場合、多すぎると絞り込み精度が下がる可能性があります。"
                "それでも追加しますか?"
            ):
                return
        
        # core 軸の存在チェック
        has_core = any(a.get("tier") == "core"
                       for a in self.state.schema["axes"])
        dlg = AxisEditorDialog(
            self.app.root,
            axis_dict=None,
            allow_core=not has_core,
            title="軸を追加",
        )
        self.app.root.wait_window(dlg.top)
        if dlg.result is None:
            return
        
        self.state.schema["axes"].append(dlg.result)
        self._refresh_tree()
    
    def _on_edit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("選択", "編集する軸を選択してください。")
            return
        
        idx = int(sel[0])
        current = self.state.schema["axes"][idx]
        
        # 他に core 軸があれば、この軸を core にできない
        has_other_core = any(
            i != idx and a.get("tier") == "core"
            for i, a in enumerate(self.state.schema["axes"])
        )
        allow_core = (current.get("tier") == "core") or not has_other_core
        
        dlg = AxisEditorDialog(
            self.app.root,
            axis_dict=current,
            allow_core=allow_core,
            title=f"軸を編集: {current.get('name', '')}",
        )
        self.app.root.wait_window(dlg.top)
        if dlg.result is None:
            return
        
        # core 軸の重複チェック
        if dlg.result["tier"] == "core" and has_other_core:
            messagebox.showerror("エラー", "core軸は1つだけです。")
            return
        
        self.state.schema["axes"][idx] = dlg.result
        self._refresh_tree()
        # 選択状態を維持
        self.tree.selection_set(str(idx))
    
    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        axis = self.state.schema["axes"][idx]
        
        if not messagebox.askyesno(
            "削除確認",
            f"軸 '{axis.get('name', '')}' を削除しますか?"
        ):
            return
        
        # core 軸を削除しようとしているなら確認
        if axis.get("tier") == "core":
            if not messagebox.askyesno(
                "core軸の削除",
                "core軸を削除しようとしています。\n"
                "core軸が無いとスコアリングできません。\n"
                "本当に削除しますか?"
            ):
                return
        
        del self.state.schema["axes"][idx]
        self._refresh_tree()
    
    def _on_move(self, delta: int):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        new_idx = idx + delta
        axes = self.state.schema["axes"]
        if new_idx < 0 or new_idx >= len(axes):
            return
        axes[idx], axes[new_idx] = axes[new_idx], axes[idx]
        self._refresh_tree()
        self.tree.selection_set(str(new_idx))
    
    def _show_json(self):
        """スキーマ全体を JSON 表示"""
        if not self.state.schema:
            messagebox.showinfo("JSON", "スキーマが未生成です。")
            return
        
        # 適用前の summary も反映してプレビュー
        preview_schema = dict(self.state.schema)
        preview_schema["query_summary"] = self.var_summary.get().strip()
        
        dlg = tk.Toplevel(self.app.root)
        dlg.title("スキーマ JSON プレビュー")
        dlg.geometry("700x500")
        dlg.transient(self.app.root)
        
        text_frame = ttk.Frame(dlg)
        text_frame.pack(fill="both", expand=True, padx=8, pady=8)
        
        txt = tk.Text(text_frame, wrap="word", font=("Monospace", 10))
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        
        json_str = json.dumps(preview_schema, ensure_ascii=False, indent=2)
        txt.insert("1.0", json_str)
        txt.configure(state="disabled")
        
        ttk.Button(dlg, text="閉じる", command=dlg.destroy).pack(pady=8)
    
    # ------------------------------------------------------------------
    # 基底クラスフック
    # ------------------------------------------------------------------
    
    def on_show(self):
        """このタブに切り替わった時、state からスキーマを表示"""
        self._refresh_tree()
    
    def on_hide(self):
        """summary の編集を state に書き戻し"""
        if self.state.schema:
            self.state.schema["query_summary"] = self.var_summary.get().strip()
    
    def refresh_from_state(self):
        self._refresh_tree()
