"""
gui/widgets/mapping_editor.py - カラムマッピング編集ダイアログ

CSV の物理カラム名と loader の論理カラム名を対応付ける UI。
CSV のヘッダから候補を取って、各論理カラムにドロップダウンで選択する形にする。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional


# loader.py の論理カラム名と表示名
LOGICAL_COLUMNS = [
    ("repair_id", "修理ID", True),          # (論理名, 表示名, 必須)
    ("user_comment", "ユーザコメント [U]", False),
    ("repair_comment", "修理者コメント [R]", False),
    ("internal_1", "内部コメント1 [I1]", False),
    ("internal_2", "内部コメント2 [I2]", False),
]


class MappingEditorDialog:
    """
    マッピング新規作成/編集ダイアログ。
    
    使い方:
        dlg = MappingEditorDialog(
            parent,
            csv_columns=["修理番号", "お客様コメント", ...],  # CSVヘッダ
            existing_mapping=None or dict,
            existing_name=None or str,
        )
        parent.wait_window(dlg.top)
        if dlg.result is not None:
            mapping_dict, save_name = dlg.result
    """
    
    def __init__(
        self,
        parent,
        csv_columns: list[str],
        existing_mapping: Optional[dict] = None,
        existing_name: Optional[str] = None,
    ):
        self.result: Optional[tuple[dict, str]] = None
        self.csv_columns = csv_columns
        
        self.top = tk.Toplevel(parent)
        self.top.title("マッピング編集" if existing_mapping else "マッピング新規作成")
        self.top.geometry("700x600")
        self.top.transient(parent)
        self.top.grab_set()
        
        m = existing_mapping or {}
        self.var_display_name = tk.StringVar(value=m.get("name", ""))
        self.var_description = tk.StringVar(value=m.get("description", ""))
        self.var_save_name = tk.StringVar(value=existing_name or "")
        
        # 各論理カラムに対応する物理カラム
        cols = m.get("columns", {})
        self.var_columns = {}
        for logical, _, _ in LOGICAL_COLUMNS:
            self.var_columns[logical] = tk.StringVar(value=cols.get(logical) or "")
        
        # passthrough_columns
        self.passthrough: list[str] = list(m.get("passthrough_columns", []))
        
        self._build_ui()
    
    def _build_ui(self):
        main = ttk.Frame(self.top, padding=10)
        main.pack(expand=True, fill="both")
        
        # === メタ情報 ===
        ttk.Label(main, text="マッピング情報", font=("", 11, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        meta = ttk.Frame(main)
        meta.pack(fill="x")
        
        ttk.Label(meta, text="保存名(ファイル名):").grid(
            row=0, column=0, sticky="e", padx=4, pady=2
        )
        ttk.Entry(meta, textvariable=self.var_save_name, width=30).grid(
            row=0, column=1, sticky="we", padx=4, pady=2
        )
        ttk.Label(meta, text="(例: japan_format)", foreground="gray").grid(
            row=0, column=2, sticky="w", padx=4
        )
        
        ttk.Label(meta, text="表示名:").grid(
            row=1, column=0, sticky="e", padx=4, pady=2
        )
        ttk.Entry(meta, textvariable=self.var_display_name, width=30).grid(
            row=1, column=1, sticky="we", padx=4, pady=2
        )
        
        ttk.Label(meta, text="説明:").grid(
            row=2, column=0, sticky="e", padx=4, pady=2
        )
        ttk.Entry(meta, textvariable=self.var_description, width=50).grid(
            row=2, column=1, columnspan=2, sticky="we", padx=4, pady=2
        )
        meta.columnconfigure(1, weight=1)
        
        # === カラムマッピング ===
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(main, text="カラムマッピング", font=("", 11, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            main, foreground="gray",
            text="各論理カラムに対応するCSVカラム名を選択。"
                 "存在しないなら '(なし)' を選択。"
        ).pack(anchor="w")
        
        cmap = ttk.Frame(main)
        cmap.pack(fill="x", pady=4)
        
        # CSVカラム選択肢(先頭に "(なし)" を入れる)
        cb_values = ["(なし)"] + list(self.csv_columns)
        
        for i, (logical, display, required) in enumerate(LOGICAL_COLUMNS):
            label_text = f"{display} ({logical})"
            if required:
                label_text += " *"
            ttk.Label(cmap, text=label_text).grid(
                row=i, column=0, sticky="e", padx=4, pady=2
            )
            cb = ttk.Combobox(
                cmap, textvariable=self.var_columns[logical],
                values=cb_values, width=40, state="readonly"
            )
            cb.grid(row=i, column=1, sticky="we", padx=4, pady=2)
            
            # 現在値が空なら "(なし)" を選択
            if not self.var_columns[logical].get():
                self.var_columns[logical].set("(なし)")
        cmap.columnconfigure(1, weight=1)
        
        ttk.Label(main, text="* = 必須", foreground="gray").pack(anchor="w")
        
        # === passthrough_columns ===
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(main, text="Passthrough カラム(Tableau出力に残すカラム)",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        
        pt = ttk.Frame(main)
        pt.pack(fill="both", expand=True)
        
        list_frame = ttk.Frame(pt)
        list_frame.pack(side="left", fill="both", expand=True)
        
        self.lst_passthrough = tk.Listbox(list_frame, height=5)
        lst_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                   command=self.lst_passthrough.yview)
        self.lst_passthrough.configure(yscrollcommand=lst_scroll.set)
        self.lst_passthrough.pack(side="left", fill="both", expand=True)
        lst_scroll.pack(side="right", fill="y")
        
        for c in self.passthrough:
            self.lst_passthrough.insert("end", c)
        
        pt_btn_frame = ttk.Frame(pt)
        pt_btn_frame.pack(side="left", fill="y", padx=(8, 0))
        
        self.var_passthrough_add = tk.StringVar()
        ttk.Label(pt_btn_frame, text="追加するカラム:").pack(anchor="w")
        ttk.Combobox(
            pt_btn_frame, textvariable=self.var_passthrough_add,
            values=list(self.csv_columns), width=25, state="readonly"
        ).pack(anchor="w")
        ttk.Button(pt_btn_frame, text="追加 →",
                   command=self._add_passthrough).pack(anchor="w", pady=2)
        ttk.Button(pt_btn_frame, text="選択削除",
                   command=self._remove_passthrough).pack(anchor="w", pady=2)
        
        # === OK / キャンセル ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_frame, text="保存",
                   command=self._on_ok).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="キャンセル",
                   command=self._on_cancel).pack(side="right", padx=2)
    
    def _add_passthrough(self):
        col = self.var_passthrough_add.get()
        if not col or col == "(なし)":
            return
        # 既に追加済みならスキップ
        existing = list(self.lst_passthrough.get(0, "end"))
        if col in existing:
            return
        self.lst_passthrough.insert("end", col)
    
    def _remove_passthrough(self):
        sel = self.lst_passthrough.curselection()
        if sel:
            self.lst_passthrough.delete(sel[0])
    
    def _on_ok(self):
        # 保存名チェック
        save_name = self.var_save_name.get().strip()
        if not save_name:
            messagebox.showwarning("入力エラー", "保存名を入力してください。",
                                   parent=self.top)
            return
        
        # ファイル名として有効な文字のみ
        invalid_chars = set('/\\:*?"<>|')
        if any(c in invalid_chars for c in save_name):
            messagebox.showwarning(
                "入力エラー",
                f"保存名に使えない文字が含まれています: {invalid_chars}",
                parent=self.top
            )
            return
        
        # repair_id 必須
        if self.var_columns["repair_id"].get() in ("", "(なし)"):
            messagebox.showwarning("入力エラー", "repair_id は必須です。",
                                   parent=self.top)
            return
        
        # 少なくとも1つのコメントカラム
        comment_cols = ["user_comment", "repair_comment", "internal_1", "internal_2"]
        has_comment = any(
            self.var_columns[c].get() not in ("", "(なし)")
            for c in comment_cols
        )
        if not has_comment:
            messagebox.showwarning(
                "入力エラー",
                "少なくとも1つのコメントカラムをマッピングしてください。",
                parent=self.top
            )
            return
        
        # マッピング dict を構築
        columns = {}
        for logical, _, _ in LOGICAL_COLUMNS:
            val = self.var_columns[logical].get()
            columns[logical] = None if val in ("", "(なし)") else val
        
        passthrough = list(self.lst_passthrough.get(0, "end"))
        
        mapping = {
            "name": self.var_display_name.get().strip() or save_name,
            "description": self.var_description.get().strip(),
            "columns": columns,
            "passthrough_columns": passthrough,
        }
        
        self.result = (mapping, save_name)
        self.top.destroy()
    
    def _on_cancel(self):
        self.top.destroy()
