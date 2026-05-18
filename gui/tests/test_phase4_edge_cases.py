"""
test_phase4_edge_cases.py - フェーズ4 セッションのエッジケース

- 編集中タブの未確定値が保存に含まれるか
- セッション読み込み後に失敗バッチ再実行できる準備が整っているか
- ファイルが部分的に欠けたセッション
- pickle で渡された DataFrame と Parquet で渡された DataFrame の等価性
"""
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import test_phase3_integration as t3


class TempSessionDir:
    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="repair_edge_")
        self.tmpdir_path = Path(self.tmpdir)
        import gui.state as gs
        self._original = gs.SESSIONS_BASE_DIR
        gs.SESSIONS_BASE_DIR = self.tmpdir_path
        return self.tmpdir_path
    
    def __exit__(self, *args):
        import gui.state as gs
        gs.SESSIONS_BASE_DIR = self._original
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def test_save_captures_unconfirmed_inquiry_edit():
    """
    問い合わせタブで文字入力中(プレースホルダから抜けた状態)に
    save_session_dialog を呼ぶと、UI入力値が state に反映されてから保存される。
    """
    print("\n=== test_save_captures_unconfirmed_inquiry_edit ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    with TempSessionDir() as base:
        from gui.app import App
        app = App()
        
        # 問い合わせタブをアクティブに
        inquiry_idx = list(app.tabs.keys()).index("InquiryTab")
        app.notebook.select(inquiry_idx)
        app.root.update()
        
        # 入力(プレースホルダを抜けて編集)
        inquiry_tab = app.tabs["InquiryTab"]
        inquiry_tab._set_inquiry_text("途中まで入力した文章")
        # この時点で state.inquiry_text は更新されていない
        # (on_hide / 明示的同期で初めて反映される設計)
        
        # 直接 _sync_current_tab_to_state を呼ぶ(save_session_dialog の最初にやる処理)
        app._sync_current_tab_to_state()
        
        assert app.state.inquiry_text == "途中まで入力した文章", \
            f"同期失敗: {app.state.inquiry_text!r}"
        
        # 保存
        saved_dir = app.state.save_session(session_name="edit_capture")
        app.root.destroy()
        
        # 読み込みで戻るか
        from gui.state import AppState
        restored = AppState()
        restored.load_session(saved_dir)
        assert restored.inquiry_text == "途中まで入力した文章"
        print("  ✅ 編集中の値がちゃんと保存・復元された")


def test_save_captures_current_tab_settings_edit():
    """
    設定タブで API キーを編集中に保存ボタンを押した場合、
    apply_to_config_module も呼ばれているか(他タブで dify を呼べる状態か)。
    
    GUI 側でセッションには設定は含まれないが、現在のセッション内では
    config モジュールに反映されている必要がある。
    """
    print("\n=== test_save_captures_current_tab_settings_edit ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    from gui.app import App
    import config
    original = config.DIFY_API_KEY_TAGGING
    
    try:
        app = App()
        settings_tab = app.tabs["SettingsTab"]
        settings_tab.var_dify_key_tagging.set("app-test12345")
        
        # 別タブに切り替える(on_hide が呼ばれる)
        app.notebook.select(1)  # 問い合わせタブ
        app.root.update()
        
        # config モジュールに反映されたか
        assert config.DIFY_API_KEY_TAGGING == "app-test12345", \
            f"反映されてない: {config.DIFY_API_KEY_TAGGING}"
        
        app.root.destroy()
        print("  ✅ タブ切り替えで config モジュールに反映された")
    finally:
        config.DIFY_API_KEY_TAGGING = original


def test_load_session_with_failed_batches_enables_retry():
    """
    失敗バッチを含むセッションを読み込んだ後、
    タグ付けタブで「失敗バッチを再実行」ボタンが有効になる。
    """
    print("\n=== test_load_session_with_failed_batches_enables_retry ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    with TempSessionDir() as base:
        from gui.state import AppState
        
        # 失敗バッチありの state を保存
        s = AppState()
        s.schema = t3.make_dummy_schema()
        s.records = t3.make_dummy_records()
        s.batches = [s.records]
        s.batch_results = [
            {"batch_idx": 0, "success": True, "results": [], "input_ids": ["R001"]},
            {"batch_idx": 1, "success": False, "error": "timeout", "input_ids": ["R002", "R003"]},
        ]
        saved = s.save_session(session_name="with_failure")
        
        # 新規アプリで読み込み
        from gui.app import App
        app = App()
        app.state.load_session(saved)
        app._refresh_all_tabs()
        app.root.update()
        
        # タグ付けタブに切替
        tagging_idx = list(app.tabs.keys()).index("TaggingTab")
        app.notebook.select(tagging_idx)
        app.root.update()
        
        tagging_tab = app.tabs["TaggingTab"]
        # 失敗バッチTreeviewに1件入っている
        failed_items = tagging_tab.tree_failed.get_children()
        assert len(failed_items) == 1, \
            f"失敗バッチ件数: {len(failed_items)}"
        
        # 「失敗バッチを再実行」ボタンが有効
        retry_state = str(tagging_tab.btn_retry["state"])
        assert retry_state == "normal", f"retry ボタン状態: {retry_state}"
        
        app.root.destroy()
        print("  ✅ 失敗バッチ含む復元: 再実行ボタン有効、Treeview表示OK")


def test_dataframe_dtype_preservation():
    """Parquet 経由でも DataFrame の dtype が崩れないか"""
    print("\n=== test_dataframe_dtype_preservation ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState
        
        s = AppState()
        s.repair_df = pd.DataFrame({
            "repair_id": ["R001", "R002"],
            "score": [0.85, 0.42],
            "count": [3, 7],
            "is_active": [True, False],
        })
        saved = s.save_session(session_name="dtype_test")
        
        restored = AppState()
        restored.load_session(saved)
        
        # dtype 比較
        for col in s.repair_df.columns:
            orig_dtype = s.repair_df[col].dtype
            new_dtype = restored.repair_df[col].dtype
            # bool/int/float の互換性は緩めに見る
            assert orig_dtype.kind == new_dtype.kind, \
                f"{col}: {orig_dtype} → {new_dtype}"
        print("  ✅ dtype保持: object/float/int/bool")


def test_session_with_unicode_data():
    """日本語データを含むセッション"""
    print("\n=== test_session_with_unicode_data ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState
        
        s = AppState()
        s.inquiry_text = "EOS R7 の AF 性能 🎯 寒冷地で迷走"
        s.schema = {
            "axes": [
                {
                    "name": "発生箇所",
                    "tier": "core",
                    "candidates": ["AF系", "電源系", "シャッター系", "その他", "不明"],
                }
            ],
            "query_summary": "AF系の不具合 (低温時)",
        }
        s.query_tags = {"発生箇所": "AF系"}
        s.repair_df = pd.DataFrame([
            {"repair_id": "R001", "user_comment": "冬の山中でAFが効かなくなった😱"},
            {"repair_id": "R002", "user_comment": "ピント外れる"},
        ])
        
        saved = s.save_session(session_name="日本語セッション_絵文字付き")
        
        restored = AppState()
        restored.load_session(saved)
        
        assert restored.inquiry_text == s.inquiry_text
        assert restored.schema == s.schema
        assert restored.query_tags == s.query_tags
        pd.testing.assert_frame_equal(
            restored.repair_df.reset_index(drop=True),
            s.repair_df.reset_index(drop=True)
        )
        print("  ✅ Unicode・絵文字含むデータ往復OK")


def test_session_with_only_state_json():
    """DataFrame ファイルが無い古いセッション(state.json のみ)"""
    print("\n=== test_session_with_only_state_json ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState
        
        s = AppState()
        s.inquiry_text = "古い形式"
        s.schema = {"axes": [{"name": "X", "tier": "core", "candidates": ["a"]}]}
        # DataFrame系は意図的に入れない
        saved = s.save_session(session_name="state_only")
        
        # parquet/pkl が存在しないことを確認
        assert not (saved / "repair_df.parquet").exists()
        
        restored = AppState()
        # まず何か入れておく
        restored.repair_df = pd.DataFrame({"a": [1]})
        
        restored.load_session(saved)
        
        # スカラーは復元
        assert restored.inquiry_text == "古い形式"
        # DataFrame は None
        assert restored.repair_df is None
        assert restored.records is None
        print("  ✅ DF欠落セッションでも例外なくロード")


def test_back_to_back_save_load():
    """連続して保存・読み込みを繰り返してもメモリリーク等で壊れない"""
    print("\n=== test_back_to_back_save_load ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState, list_sessions
        
        s = AppState()
        for i in range(5):
            s.inquiry_text = f"問い合わせ#{i}"
            s.schema = {"axes": [{"name": f"axis_{i}", "tier": "core",
                                  "candidates": ["a", "b"]}]}
            s.save_session(session_name=f"iter_{i}")
        
        sessions = list_sessions()
        assert len(sessions) == 5
        
        # 全部読み込めるか
        for sess in sessions:
            r = AppState()
            r.load_session(sess["path"])
            # session_name は state には入らない(メタ情報)
            assert r.inquiry_text.startswith("問い合わせ#")
        print("  ✅ 連続保存・読み込み5回OK")


def test_concurrent_session_dirs_isolated():
    """同じ秒に複数のセッションを保存しても衝突しない"""
    print("\n=== test_concurrent_session_dirs_isolated ===")
    
    # 厳密に同一秒で衝突するかは時刻依存だが、
    # 別名を渡せば必ず分離されることを確認
    with TempSessionDir() as base:
        from gui.state import AppState, list_sessions
        
        # 1秒以内に2回保存(同タイムスタンプの可能性)
        s1 = AppState()
        s1.inquiry_text = "A"
        d1 = s1.save_session(session_name="A_session")
        
        s2 = AppState()
        s2.inquiry_text = "B"
        d2 = s2.save_session(session_name="B_session")
        
        # 異なるディレクトリに保存される(名前が違うので)
        assert d1 != d2
        assert d1.exists() and d2.exists()
        
        sessions = list_sessions()
        assert len(sessions) == 2
        print(f"  ✅ 同タイムスタンプでも別名なら分離: {d1.name}, {d2.name}")


if __name__ == "__main__":
    test_save_captures_unconfirmed_inquiry_edit()
    test_save_captures_current_tab_settings_edit()
    test_load_session_with_failed_batches_enables_retry()
    test_dataframe_dtype_preservation()
    test_session_with_unicode_data()
    test_session_with_only_state_json()
    test_back_to_back_save_load()
    test_concurrent_session_dirs_isolated()
    
    print("\n" + "=" * 50)
    print("✅ フェーズ4 エッジケース全テスト通過")
