"""
gui/widgets/dataframe_view.py - pandastable ラッパー

DataFrame を表示するウィジェット。pandastable が利用可能なら使い、
ない場合は ttk.Treeview にフォールバックする。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import pandas as pd


# pandastable が使えるかチェック
try:
    from pandastable import Table
    PANDASTABLE_AVAILABLE = True
except ImportError:
    PANDASTABLE_AVAILABLE = False


class DataFrameView(ttk.Frame):
    """
    DataFrame を表示する汎用ウィジェット。
    
    使い方:
        view = DataFrameView(parent, df=None)
        view.pack(fill="both", expand=True)
        view.update_df(df)
    """
    
    def __init__(self, parent, df: Optional[pd.DataFrame] = None,
                 editable: bool = False, max_rows_display: int = 1000):
        super().__init__(parent)
        self.editable = editable
        self.max_rows_display = max_rows_display
        self._df: Optional[pd.DataFrame] = None
        
        if PANDASTABLE_AVAILABLE:
            self._build_pandastable()
        else:
            self._build_treeview()
        
        if df is not None:
            self.update_df(df)
    
    # ------------------------------------------------------------------
    # pandastable バックエンド
    # ------------------------------------------------------------------
    
    def _build_pandastable(self):
        self.table = Table(
            self,
            dataframe=pd.DataFrame(),
            editable=self.editable,
            showtoolbar=False,
            showstatusbar=True,
        )
        self.table.show()
    
    def _update_pandastable(self, df: pd.DataFrame):
        # 表示行数を制限(巨大DFで固まらないように)
        if len(df) > self.max_rows_display:
            display_df = df.head(self.max_rows_display).copy()
        else:
            display_df = df
        
        self.table.model.df = display_df
        self.table.redraw()
    
    # ------------------------------------------------------------------
    # Treeview フォールバック
    # ------------------------------------------------------------------
    
    def _build_treeview(self):
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        
        self.tree = ttk.Treeview(tree_frame, show="headings")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal",
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.tree.grid(row=0, column=0, sticky="nswe")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="we")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        # ステータスラベル
        self.lbl_status = ttk.Label(self, text="", foreground="gray")
        self.lbl_status.pack(anchor="w", padx=4)
    
    def _update_treeview(self, df: pd.DataFrame):
        # 既存データクリア
        self.tree.delete(*self.tree.get_children())
        
        columns = list(df.columns)
        self.tree["columns"] = columns
        
        for col in columns:
            self.tree.heading(col, text=str(col))
            self.tree.column(col, width=120, minwidth=60)
        
        # 表示行数を制限
        if len(df) > self.max_rows_display:
            display_df = df.head(self.max_rows_display)
            self.lbl_status.configure(
                text=f"{len(df)}行中、先頭{self.max_rows_display}行を表示"
            )
        else:
            display_df = df
            self.lbl_status.configure(text=f"{len(df)}行")
        
        for i, (_, row) in enumerate(display_df.iterrows()):
            values = [str(v) if v is not None else "" for v in row]
            self.tree.insert("", "end", iid=str(i), values=values)
    
    # ------------------------------------------------------------------
    # 公開メソッド
    # ------------------------------------------------------------------
    
    def update_df(self, df: pd.DataFrame):
        """DataFrame を更新して表示"""
        self._df = df
        if df is None or len(df) == 0:
            df = pd.DataFrame()
        
        if PANDASTABLE_AVAILABLE:
            self._update_pandastable(df)
        else:
            self._update_treeview(df)
    
    def get_df(self) -> Optional[pd.DataFrame]:
        return self._df
    
    def clear(self):
        self.update_df(pd.DataFrame())
