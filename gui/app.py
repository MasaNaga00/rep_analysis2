"""
gui/app.py - メインアプリケーションウィンドウ

役割:
- ルートウィンドウの生成
- 設定の読み込み(起動時)→ config モジュールに反映
- タブの生成・管理
- メニューバー(セッション保存・読み込み等)
- ステータスバー
- AppState の保持と全タブからの参照提供
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional

from gui.state import AppState, list_sessions, delete_session, SESSIONS_BASE_DIR
from gui.settings_store import AppSettings
from gui.tabs import (
    SettingsTab,
    InquiryTab,
    SchemaEditTab,
    DataLoadTab,
    TaggingTab,
    RankingTab,
    ExportTab,
)


class App:
    """
    アプリケーション全体を統括するクラス。
    
    タブの順番(処理フロー順):
      1. 設定
      2. 問い合わせ
      3. スキーマ編集
      4. データ取得
      5. タグ付け実行
      6. 絞り込み
      7. 出力
    """
    
    WINDOW_TITLE = "カメラ修理データ 類似事例検索"
    WINDOW_SIZE = "1200x800"
    
    # タブ定義(クラス, デフォルトで有効か)
    TAB_CLASSES = [
        SettingsTab,
        InquiryTab,
        SchemaEditTab,
        DataLoadTab,
        TaggingTab,
        RankingTab,
        ExportTab,
    ]
    
    def __init__(self):
        # --- 設定読み込み ---
        self.settings: AppSettings = AppSettings.load()
        try:
            self.settings.apply_to_config_module()
        except ImportError as e:
            # config が無い環境(テスト等)では無視
            print(f"⚠️ config モジュール反映スキップ: {e}")
        
        # --- 状態 ---
        self.state: AppState = AppState()
        
        # --- ルートウィンドウ ---
        self.root = tk.Tk()
        self.root.title(self.WINDOW_TITLE)
        self.root.geometry(self.WINDOW_SIZE)
        
        # macOS で見た目を改善するために ttk テーマを設定
        # (Windows でも同テーマが使えるので統一)
        style = ttk.Style()
        try:
            # 利用可能なテーマから優先順に試す
            available = style.theme_names()
            for theme in ["vista", "winnative", "clam", "default"]:
                if theme in available:
                    style.theme_use(theme)
                    break
        except tk.TclError:
            pass
        
        # --- UI 構築 ---
        self._build_menu()
        self._build_notebook()
        self._build_statusbar()
        
        # --- 終了時の処理 ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------
    
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        
        # ファイルメニュー
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新規セッション", command=self.new_session)
        file_menu.add_command(label="セッションを保存...",
                              command=self.save_session_dialog)
        file_menu.add_command(label="セッションを読み込み...",
                              command=self.load_session_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self._on_close)
        menubar.add_cascade(label="ファイル", menu=file_menu)
        
        # ヘルプメニュー
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="このアプリについて", command=self._show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=5, pady=5)
        
        # タブ生成
        self.tabs: dict[str, object] = {}
        for tab_cls in self.TAB_CLASSES:
            tab = tab_cls(self.notebook, self)
            self.notebook.add(tab, text=tab.TITLE)
            self.tabs[tab_cls.__name__] = tab
        
        # タブ切り替え時のイベント
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._current_tab_idx: Optional[int] = self.notebook.index("current")
    
    def _build_statusbar(self):
        self.statusbar_frame = ttk.Frame(self.root, relief="sunken")
        self.statusbar_frame.pack(side="bottom", fill="x")
        
        self.status_var = tk.StringVar(value="準備完了")
        status_label = ttk.Label(
            self.statusbar_frame,
            textvariable=self.status_var,
            anchor="w",
            padding=(8, 2),
        )
        status_label.pack(side="left", fill="x", expand=True)
        
        self.session_var = tk.StringVar(value="セッション: 未保存")
        session_label = ttk.Label(
            self.statusbar_frame,
            textvariable=self.session_var,
            anchor="e",
            padding=(8, 2),
        )
        session_label.pack(side="right")
    
    # ------------------------------------------------------------------
    # タブ切り替えイベント
    # ------------------------------------------------------------------
    
    def _on_tab_changed(self, event):
        """タブが切り替わった時、前タブの on_hide と新タブの on_show を呼ぶ"""
        new_idx = self.notebook.index("current")
        
        # 前タブの on_hide
        if self._current_tab_idx is not None and self._current_tab_idx != new_idx:
            try:
                prev_tab = self.notebook.nametowidget(
                    self.notebook.tabs()[self._current_tab_idx]
                )
                if hasattr(prev_tab, "on_hide"):
                    prev_tab.on_hide()
            except (tk.TclError, IndexError):
                pass
        
        # 新タブの on_show
        try:
            new_tab = self.notebook.nametowidget(self.notebook.tabs()[new_idx])
            if hasattr(new_tab, "on_show"):
                new_tab.on_show()
        except (tk.TclError, IndexError):
            pass
        
        self._current_tab_idx = new_idx
    
    # ------------------------------------------------------------------
    # ステータス表示ヘルパー(各タブから呼べる)
    # ------------------------------------------------------------------
    
    def set_status(self, text: str):
        self.status_var.set(text)
    
    def _update_session_label(self, name: Optional[str] = None):
        if name:
            self.session_var.set(f"セッション: {name}")
        else:
            self.session_var.set("セッション: 未保存")
    
    # ------------------------------------------------------------------
    # セッション操作
    # ------------------------------------------------------------------
    
    def new_session(self):
        """新規セッション開始(state をリセット)"""
        if not messagebox.askyesno(
            "新規セッション",
            "現在の状態を破棄して新しいセッションを開始しますか?\n"
            "(保存していない作業内容は失われます)"
        ):
            return
        
        self.state.reset()
        self._refresh_all_tabs()
        self._update_session_label(None)
        self.set_status("新規セッションを開始しました")
    
    def save_session_dialog(self):
        """セッション保存ダイアログ"""
        # 全タブの on_hide を呼んで state を最新化
        # (現在表示中のタブだけだと、他タブで未確定の編集が漏れる可能性がある)
        self._sync_all_tabs_to_state()
        
        # セッション名を訊く
        from tkinter.simpledialog import askstring
        name = askstring(
            "セッション保存",
            "セッション名を入力してください(空欄可):",
            parent=self.root,
        )
        if name is None:
            return  # キャンセル
        
        # 保存
        try:
            session_dir = self.state.save_session(session_name=name.strip() or None)
            self._update_session_label(session_dir.name)
            self.set_status(f"セッション保存: {session_dir}")
            messagebox.showinfo(
                "保存完了",
                f"セッションを保存しました:\n{session_dir}"
            )
        except Exception as e:
            messagebox.showerror("保存失敗", f"セッション保存に失敗しました:\n{e}")
    
    def load_session_dialog(self):
        """セッション読み込みダイアログ"""
        sessions = list_sessions()
        if not sessions:
            messagebox.showinfo(
                "セッション読み込み",
                "保存済みのセッションがありません。"
            )
            return
        
        dialog = SessionPickerDialog(self.root, sessions)
        self.root.wait_window(dialog.top)
        
        if dialog.selected_path is None:
            return
        
        try:
            self.state.load_session(dialog.selected_path)
            self._refresh_all_tabs()
            self._update_session_label(dialog.selected_path.name)
            self.set_status(f"セッション読込: {dialog.selected_path}")
        except Exception as e:
            messagebox.showerror("読み込み失敗", f"セッション読み込みに失敗:\n{e}")
    
    def _sync_current_tab_to_state(self):
        """現在表示中のタブの on_hide を呼んで state を最新化する"""
        try:
            current = self.notebook.nametowidget(
                self.notebook.tabs()[self.notebook.index("current")]
            )
            if hasattr(current, "on_hide"):
                current.on_hide()
        except (tk.TclError, IndexError):
            pass
    
    def _sync_all_tabs_to_state(self):
        """全タブの on_hide を呼んで state を最新化する(セッション保存前用)"""
        for tab in self.tabs.values():
            if hasattr(tab, "on_hide"):
                try:
                    tab.on_hide()
                except Exception as e:
                    # 1タブ失敗しても他は処理を続ける
                    print(f"⚠️ {tab.__class__.__name__}.on_hide エラー: {e}")
    
    def _refresh_all_tabs(self):
        """state が外部から変更された時、全タブの UI を再構築"""
        for tab in self.tabs.values():
            if hasattr(tab, "refresh_from_state"):
                try:
                    tab.refresh_from_state()
                except Exception as e:
                    print(f"⚠️ {tab.__class__.__name__}.refresh_from_state エラー: {e}")
    
    # ------------------------------------------------------------------
    # その他
    # ------------------------------------------------------------------
    
    def _show_about(self):
        messagebox.showinfo(
            "このアプリについて",
            "カメラ修理データ 類似事例検索 GUI\n\n"
            "Dify を用いた過去事例の自動絞り込みツール"
        )
    
    def _on_close(self):
        """ウィンドウを閉じる前の処理"""
        # 何か作業が進んでいる場合のみ確認ダイアログを出す
        summary = self.state.get_summary()
        has_work = any([
            summary["inquiry_set"],
            summary["schema_generated"],
            summary["data_loaded"],
            summary["tagged"],
            summary["ranked"],
        ])
        
        if has_work:
            if not messagebox.askyesno(
                "終了確認",
                "アプリを終了しますか?\n"
                "(保存していない作業内容は失われます)"
            ):
                return
        
        self.root.destroy()
    
    # ------------------------------------------------------------------
    # メインループ
    # ------------------------------------------------------------------
    
    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------------
# セッション選択ダイアログ
# ----------------------------------------------------------------------

class SessionPickerDialog:
    """セッション一覧から1つ選ぶダイアログ"""
    
    def __init__(self, parent, sessions: list[dict]):
        self.selected_path: Optional[Path] = None
        self.sessions = sessions
        
        self.top = tk.Toplevel(parent)
        self.top.title("セッションを読み込み")
        self.top.geometry("900x420")
        self.top.transient(parent)
        self.top.grab_set()
        
        # ツリー
        columns = ("saved_at", "session_name", "summary", "preview")
        tree = ttk.Treeview(self.top, columns=columns, show="headings")
        tree.heading("saved_at", text="保存日時")
        tree.heading("session_name", text="名前")
        tree.heading("summary", text="進捗")
        tree.heading("preview", text="問い合わせ(先頭)")
        tree.column("saved_at", width=140)
        tree.column("session_name", width=160)
        tree.column("summary", width=160)
        tree.column("preview", width=360)
        
        for s in sessions:
            # 進捗サマリ: どのフェーズまで終わっているかをチップ風に表示
            chips = []
            if s.get("has_repair_df"):
                chips.append("📥データ")
            if s.get("has_tagged_df"):
                chips.append("🏷️タグ済")
            if s.get("has_ranked_df"):
                chips.append("🎯絞込済")
            summary = " ".join(chips) if chips else "─"
            
            # 日時を見やすく
            saved_at = s["saved_at"][:19].replace("T", " ") if s["saved_at"] else "?"
            
            tree.insert("", "end", iid=str(s["path"]), values=(
                saved_at,
                s["session_name"] or "(無名)",
                summary,
                s["inquiry_preview"] or "(未入力)",
            ))
        tree.pack(expand=True, fill="both", padx=8, pady=8)
        self.tree = tree
        
        # ボタン群
        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))
        
        ttk.Button(btn_frame, text="読み込み",
                   command=self._on_ok).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="キャンセル",
                   command=self._on_cancel).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="削除...",
                   command=self._on_delete).pack(side="left", padx=2)
        
        # フォルダを開くボタン
        ttk.Button(btn_frame, text="保存先フォルダを開く",
                   command=self._open_folder).pack(side="left", padx=2)
        
        tree.bind("<Double-1>", lambda e: self._on_ok())
    
    def _on_ok(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("選択", "セッションを選択してください", parent=self.top)
            return
        self.selected_path = Path(sel[0])
        self.top.destroy()
    
    def _on_cancel(self):
        self.top.destroy()
    
    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = Path(sel[0])
        if not messagebox.askyesno(
            "削除確認",
            f"セッション '{path.name}' を削除しますか?\n(この操作は元に戻せません)",
            parent=self.top,
        ):
            return
        try:
            delete_session(path)
            self.tree.delete(sel[0])
        except Exception as e:
            messagebox.showerror("削除失敗", str(e), parent=self.top)
    
    def _open_folder(self):
        """セッション保存先のベースフォルダを OS のファイラで開く"""
        import os
        import platform
        import subprocess
        from gui.state import SESSIONS_BASE_DIR
        
        path = SESSIONS_BASE_DIR
        if not path.exists():
            messagebox.showinfo(
                "フォルダなし",
                f"セッション保存先がまだ存在しません:\n{path}",
                parent=self.top
            )
            return
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(str(path))
            elif system == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("オープン失敗",
                                 f"フォルダを開けませんでした:\n{e}",
                                 parent=self.top)


# ----------------------------------------------------------------------
# エントリポイント
# ----------------------------------------------------------------------

def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
