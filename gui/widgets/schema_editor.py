"""
gui/widgets/schema_editor.py - 軸編集ダイアログ

スキーマの単一軸(name, tier, description, candidates, priority)を
モーダルダイアログで編集する。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional


class AxisEditorDialog:
    """
    1つの軸を編集するダイアログ。
    
    使い方:
        dlg = AxisEditorDialog(parent, axis_dict=existing_axis_or_None,
                                allow_core=True)
        parent.wait_window(dlg.top)
        if dlg.result is not None:
            # 編集後の dict が dlg.result に入る
    """
    
    def __init__(
        self,
        parent,
        axis_dict: Optional[dict] = None,
        allow_core: bool = True,
        title: str = "軸を編集",
    ):
        self.result: Optional[dict] = None
        self.allow_core = allow_core
        
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("500x520")
        self.top.transient(parent)
        self.top.grab_set()
        
        # 初期値
        is_new = axis_dict is None
        a = axis_dict or {}
        self.var_name = tk.StringVar(value=a.get("name", ""))
        self.var_tier = tk.StringVar(value=a.get("tier", "detail"))
        self.var_priority = tk.StringVar(value=a.get("priority", "medium"))
        
        self._build_ui(a)
    
    def _build_ui(self, axis_dict: dict):
        main = ttk.Frame(self.top, padding=10)
        main.pack(expand=True, fill="both")
        
        # name
        ttk.Label(main, text="軸の名前:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.var_name, width=40).grid(
            row=0, column=1, sticky="we", padx=4, pady=4
        )
        
        # tier
        ttk.Label(main, text="tier:").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        tier_frame = ttk.Frame(main)
        tier_frame.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        if self.allow_core:
            ttk.Radiobutton(tier_frame, text="core", variable=self.var_tier,
                            value="core").pack(side="left")
        ttk.Radiobutton(tier_frame, text="detail", variable=self.var_tier,
                        value="detail").pack(side="left")
        
        # priority
        ttk.Label(main, text="priority:").grid(row=2, column=0, sticky="e", padx=4, pady=4)
        ttk.Combobox(main, textvariable=self.var_priority,
                     values=["high", "medium", "low"],
                     state="readonly", width=10).grid(
            row=2, column=1, sticky="w", padx=4, pady=4
        )
        
        # description
        ttk.Label(main, text="description:").grid(row=3, column=0, sticky="ne", padx=4, pady=4)
        self.txt_desc = tk.Text(main, height=3, width=40, wrap="word")
        self.txt_desc.grid(row=3, column=1, sticky="we", padx=4, pady=4)
        if axis_dict.get("description"):
            self.txt_desc.insert("1.0", axis_dict["description"])
        
        # candidates
        ttk.Label(main, text="候補 (candidates):").grid(
            row=4, column=0, sticky="ne", padx=4, pady=(12, 4)
        )
        cands_frame = ttk.Frame(main)
        cands_frame.grid(row=4, column=1, sticky="nswe", padx=4, pady=(12, 4))
        
        list_frame = ttk.Frame(cands_frame)
        list_frame.pack(fill="both", expand=True)
        
        self.lst_candidates = tk.Listbox(list_frame, height=8, width=35)
        lst_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                   command=self.lst_candidates.yview)
        self.lst_candidates.configure(yscrollcommand=lst_scroll.set)
        self.lst_candidates.pack(side="left", fill="both", expand=True)
        lst_scroll.pack(side="right", fill="y")
        
        for c in axis_dict.get("candidates", []):
            self.lst_candidates.insert("end", c)
        
        cand_btn_frame = ttk.Frame(cands_frame)
        cand_btn_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(cand_btn_frame, text="追加",
                   command=self._add_candidate).pack(side="left", padx=2)
        ttk.Button(cand_btn_frame, text="編集",
                   command=self._edit_candidate).pack(side="left", padx=2)
        ttk.Button(cand_btn_frame, text="削除",
                   command=self._delete_candidate).pack(side="left", padx=2)
        ttk.Button(cand_btn_frame, text="↑",
                   command=lambda: self._move_candidate(-1), width=3).pack(side="left", padx=2)
        ttk.Button(cand_btn_frame, text="↓",
                   command=lambda: self._move_candidate(1), width=3).pack(side="left", padx=2)
        
        ttk.Label(
            main,
            text="※ candidatesは MECE で、必ず「不明」または「該当なし」を含めること",
            foreground="gray", font=("", 9)
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 8))
        
        # === OK/キャンセル ===
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="キャンセル",
                   command=self._on_cancel).pack(side="right", padx=2)
        
        main.columnconfigure(1, weight=1)
        main.rowconfigure(4, weight=1)
    
    def _add_candidate(self):
        val = self._prompt_string("候補追加", "候補名を入力:")
        if val:
            self.lst_candidates.insert("end", val)
    
    def _edit_candidate(self):
        sel = self.lst_candidates.curselection()
        if not sel:
            return
        idx = sel[0]
        current = self.lst_candidates.get(idx)
        val = self._prompt_string("候補編集", "候補名:", initial=current)
        if val:
            self.lst_candidates.delete(idx)
            self.lst_candidates.insert(idx, val)
            self.lst_candidates.selection_set(idx)
    
    def _delete_candidate(self):
        sel = self.lst_candidates.curselection()
        if not sel:
            return
        self.lst_candidates.delete(sel[0])
    
    def _move_candidate(self, delta: int):
        sel = self.lst_candidates.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= self.lst_candidates.size():
            return
        val = self.lst_candidates.get(idx)
        self.lst_candidates.delete(idx)
        self.lst_candidates.insert(new_idx, val)
        self.lst_candidates.selection_set(new_idx)
    
    def _prompt_string(self, title, prompt, initial=""):
        """シンプルな文字列入力ダイアログ"""
        dlg = tk.Toplevel(self.top)
        dlg.title(title)
        dlg.geometry("400x120")
        dlg.transient(self.top)
        dlg.grab_set()
        
        ttk.Label(dlg, text=prompt).pack(padx=10, pady=(10, 4), anchor="w")
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(dlg, textvariable=var, width=40)
        entry.pack(padx=10, pady=4, fill="x")
        entry.focus_set()
        entry.select_range(0, "end")
        
        result = []
        
        def ok():
            v = var.get().strip()
            if v:
                result.append(v)
            dlg.destroy()
        
        def cancel():
            dlg.destroy()
        
        btn = ttk.Frame(dlg)
        btn.pack(pady=8)
        ttk.Button(btn, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btn, text="キャンセル", command=cancel).pack(side="left", padx=4)
        
        entry.bind("<Return>", lambda e: ok())
        entry.bind("<Escape>", lambda e: cancel())
        
        self.top.wait_window(dlg)
        return result[0] if result else None
    
    def _on_ok(self):
        # バリデーション
        name = self.var_name.get().strip()
        if not name:
            messagebox.showwarning("入力エラー", "軸の名前は必須です。", parent=self.top)
            return
        
        candidates = list(self.lst_candidates.get(0, "end"))
        if not candidates:
            messagebox.showwarning(
                "入力エラー", "候補(candidates)は1つ以上必要です。",
                parent=self.top
            )
            return
        
        # 重複チェック
        if len(candidates) != len(set(candidates)):
            messagebox.showwarning(
                "入力エラー", "候補に重複があります。",
                parent=self.top
            )
            return
        
        # 「不明」「該当なし」のいずれかが含まれているか(警告のみ)
        if not any(c in candidates for c in ("不明", "該当なし")):
            if not messagebox.askyesno(
                "確認",
                "候補に「不明」または「該当なし」が含まれていません。"
                "これらが無いと判定不能なレコードを表現できません。"
                "このまま保存しますか?",
                parent=self.top
            ):
                return
        
        self.result = {
            "name": name,
            "tier": self.var_tier.get(),
            "description": self.txt_desc.get("1.0", "end").strip(),
            "candidates": candidates,
            "priority": self.var_priority.get(),
        }
        self.top.destroy()
    
    def _on_cancel(self):
        self.top.destroy()
