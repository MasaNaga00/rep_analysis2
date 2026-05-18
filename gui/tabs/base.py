"""
gui/tabs/base.py - タブの基底クラス

全タブは BaseTab を継承し、AppState と AppSettings を参照できる。
タブ切り替え時のフックも提供する。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gui.state import AppState
    from gui.settings_store import AppSettings


class BaseTab(ttk.Frame):
    """
    全タブの基底。
    
    サブクラスは __init__ で UI を組み立て、必要なら on_show / on_hide を
    オーバーライドして「タブが表示された時」「他のタブに切り替わった時」の
    処理を書く。
    
    タブ間の状態共有は state(AppState)経由で行う。
    タブからアプリ全体に通知する場合は self.app に直接アクセスできる。
    """
    
    # タブのタイトル(タブヘッダーに表示される)
    TITLE = "Untitled"
    
    def __init__(self, parent, app: "App", **kwargs):
        super().__init__(parent, **kwargs)
        self.app: "App" = app
        # 便宜的にstate/settingsへのショートカット
        self.state: "AppState" = app.state
        self.settings: "AppSettings" = app.settings
        
        self.build_ui()
    
    def build_ui(self):
        """UI 構築。サブクラスがオーバーライド"""
        raise NotImplementedError
    
    def on_show(self):
        """このタブが表示された時に呼ばれる(state からの再表示等に使う)"""
        pass
    
    def on_hide(self):
        """他のタブに切り替わる時に呼ばれる(編集中の値を state に書き戻す等)"""
        pass
    
    def refresh_from_state(self):
        """state から UI を再構築(セッションロード後等に呼ばれる)"""
        pass
