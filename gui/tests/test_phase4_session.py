"""
test_phase4_session.py - セッション保存・読み込みのエンドツーエンド検証

検証項目:
1. 全フィールドが入った state を保存 → 別 AppState インスタンスで読み込み → 等価性確認
2. 部分的に埋まった state(よくあるケース)で保存 → 読み込み → 欠落フィールドが None
3. list_sessions() が新しい順に返す
4. delete_session() で実際に消える
5. 不正なセッションディレクトリでの読み込みエラー
6. UI 経由: App 起動 → state 構築 → 保存 → App 再起動 → load_session → 全タブ refresh
7. セッション保存先のディレクトリが存在しない場合の自動作成
"""
import sys
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

import test_phase3_integration as t3  # ダミーデータ生成関数を再利用


# 一時的にセッションベースディレクトリを差し替えるためのコンテキストマネージャ
class TempSessionDir:
    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="repair_test_sessions_")
        self.tmpdir_path = Path(self.tmpdir)
        # gui.state.SESSIONS_BASE_DIR を一時的に差し替え
        import gui.state as gs
        self._original = gs.SESSIONS_BASE_DIR
        gs.SESSIONS_BASE_DIR = self.tmpdir_path
        return self.tmpdir_path
    
    def __exit__(self, *args):
        import gui.state as gs
        gs.SESSIONS_BASE_DIR = self._original
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _make_full_state() -> "AppState":
    """全フィールドが埋まったAppState"""
    from gui.state import AppState
    s = AppState()
    s.inquiry_text = "EOS R7 で寒い屋外で AF が迷う現象の切り分け"
    s.schema = t3.make_dummy_schema()
    s.data_source = "csv"
    s.csv_path = "/some/path/data.csv"
    s.sql_query = "SELECT * FROM repair_records WHERE model = ?"
    s.sql_params = ["EOS R7"]
    s.mapping_name = "sample_japan"
    s.query_tags = {"machine_part": "AF系", "environment": "低温下"}
    s.min_relevance = 0.45
    s.top_n = 100
    s.output_tag = "EOS_R7_AF_lowtemp"
    
    # DF / pickle系
    s.repair_df = pd.DataFrame([
        {"repair_id": "R001", "user_comment": "AFが合わない", "model": "EOS R7"},
        {"repair_id": "R002", "user_comment": "シャッター", "model": "EOS R6"},
        {"repair_id": "R003", "user_comment": "AF迷い", "model": "EOS R7"},
    ])
    s.records = t3.make_dummy_records()
    s.batches = [s.records[:2], s.records[2:]]
    s.batch_results = [
        {
            "batch_idx": 0, "success": True,
            "results": [{"repair_id": "R001"}, {"repair_id": "R002"}],
            "input_ids": ["R001", "R002"],
        },
        {
            "batch_idx": 1, "success": False,
            "error": "DifyTimeoutError: 120s",
            "input_ids": ["R003"],
        },
    ]
    s.tagged_df = t3.make_dummy_tagged_df()
    s.ranked_df = t3.make_dummy_tagged_df().iloc[[0, 2]].copy()  # AF系のみ
    return s


def _assert_state_equal(a, b, ctx=""):
    """2つのAppStateが等価か検証"""
    # スカラー
    assert a.inquiry_text == b.inquiry_text, f"{ctx} inquiry_text 不一致"
    assert a.data_source == b.data_source, f"{ctx} data_source 不一致"
    assert a.csv_path == b.csv_path, f"{ctx} csv_path 不一致"
    assert a.sql_query == b.sql_query, f"{ctx} sql_query 不一致"
    assert a.sql_params == b.sql_params, f"{ctx} sql_params 不一致"
    assert a.mapping_name == b.mapping_name, f"{ctx} mapping_name 不一致"
    assert a.query_tags == b.query_tags, f"{ctx} query_tags 不一致"
    assert abs(a.min_relevance - b.min_relevance) < 1e-9, \
        f"{ctx} min_relevance 不一致"
    assert a.top_n == b.top_n, f"{ctx} top_n 不一致"
    assert a.output_tag == b.output_tag, f"{ctx} output_tag 不一致"
    
    # schema (dict)
    assert a.schema == b.schema, f"{ctx} schema 不一致"
    
    # DataFrame
    def _df_equal(x, y, name):
        if x is None and y is None:
            return
        assert x is not None and y is not None, \
            f"{ctx} {name} 片方だけNone"
        pd.testing.assert_frame_equal(
            x.reset_index(drop=True), y.reset_index(drop=True),
            check_dtype=False, obj=name
        )
    _df_equal(a.repair_df, b.repair_df, "repair_df")
    _df_equal(a.tagged_df, b.tagged_df, "tagged_df")
    _df_equal(a.ranked_df, b.ranked_df, "ranked_df")
    
    # pickle
    assert a.records == b.records, f"{ctx} records 不一致"
    assert a.batches == b.batches, f"{ctx} batches 不一致"
    assert a.batch_results == b.batch_results, f"{ctx} batch_results 不一致"


def test_round_trip_full_state():
    """全フィールド埋まった状態で保存→読込→等価"""
    print("\n=== test_round_trip_full_state ===")
    
    with TempSessionDir() as base:
        original = _make_full_state()
        
        # 保存
        saved_dir = original.save_session(session_name="phase4_full_test")
        print(f"  保存先: {saved_dir}")
        
        # 別インスタンスで読み込み
        from gui.state import AppState
        restored = AppState()
        restored.load_session(saved_dir)
        
        _assert_state_equal(original, restored, ctx="full")
        print("  ✅ 全フィールド一致")


def test_round_trip_partial_state():
    """部分的な state(問い合わせ + スキーマだけ)で保存→読込"""
    print("\n=== test_round_trip_partial_state ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState
        original = AppState()
        original.inquiry_text = "部分保存テスト"
        original.schema = t3.make_dummy_schema()
        # 他は全部 None / デフォルト
        
        saved_dir = original.save_session(session_name="partial")
        
        restored = AppState()
        # 先に何か入れて、読み込みで上書きされることを確認
        restored.inquiry_text = "上書きされるはず"
        restored.repair_df = pd.DataFrame([{"x": 1}])
        
        restored.load_session(saved_dir)
        
        assert restored.inquiry_text == "部分保存テスト"
        assert restored.schema == original.schema
        # 保存されてないフィールドは None / デフォルトに戻る
        assert restored.repair_df is None, "保存されてないDFはNoneになるべき"
        assert restored.tagged_df is None
        assert restored.records is None
        print("  ✅ 部分state: 上書き挙動も正しい")


def test_list_sessions_sorted():
    """list_sessions が新しい順"""
    print("\n=== test_list_sessions_sorted ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState, list_sessions
        import time
        
        # 3つ保存(微妙に時間差をつける)
        for i, name in enumerate(["first", "second", "third"]):
            s = AppState()
            s.inquiry_text = f"問い合わせ#{i}"
            s.save_session(session_name=name)
            time.sleep(0.05)  # タイムスタンプ差をつける
        
        sessions = list_sessions()
        assert len(sessions) == 3, f"期待:3, 実際:{len(sessions)}"
        # 新しい順 → third, second, first
        names = [s["session_name"] for s in sessions]
        assert names == ["third", "second", "first"], \
            f"新しい順でない: {names}"
        print(f"  ✅ 新しい順に並んでいる: {names}")


def test_delete_session():
    """delete_session でディレクトリごと消える"""
    print("\n=== test_delete_session ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState, list_sessions, delete_session
        
        s = AppState()
        s.inquiry_text = "削除予定"
        saved_dir = s.save_session(session_name="to_delete")
        
        assert saved_dir.exists()
        assert len(list_sessions()) == 1
        
        delete_session(saved_dir)
        
        assert not saved_dir.exists()
        assert len(list_sessions()) == 0
        print("  ✅ セッション削除OK")


def test_load_nonexistent_raises():
    """存在しないセッションディレクトリを読み込もうとするとエラー"""
    print("\n=== test_load_nonexistent_raises ===")
    
    from gui.state import AppState
    s = AppState()
    try:
        s.load_session(Path("/tmp/this_does_not_exist_xyz"))
        assert False, "FileNotFoundError が出るべき"
    except FileNotFoundError as e:
        print(f"  ✅ 期待通りエラー: {e}")


def test_corrupted_state_json_handled_in_list():
    """state.json が壊れているセッションは list_sessions でスキップされる"""
    print("\n=== test_corrupted_state_json_handled_in_list ===")
    
    with TempSessionDir() as base:
        # 正常なセッション
        from gui.state import AppState, list_sessions
        good = AppState()
        good.inquiry_text = "正常"
        good.save_session(session_name="good")
        
        # 壊れた state.json を持つディレクトリ
        bad_dir = base / "bad_session"
        bad_dir.mkdir()
        (bad_dir / "state.json").write_text("これはJSONではない{{{")
        
        sessions = list_sessions()
        # 正常な1件だけ拾えるはず
        assert len(sessions) == 1, f"期待:1, 実際:{len(sessions)}"
        assert sessions[0]["session_name"] == "good"
        print("  ✅ 壊れたセッションは無視された")


def test_session_subdir_creation():
    """SESSIONS_BASE_DIR が存在しない状態でも save_session が動く"""
    print("\n=== test_session_subdir_creation ===")
    
    with tempfile.TemporaryDirectory() as parent:
        # 存在しないサブディレクトリを指定
        non_existent = Path(parent) / "deep" / "nested" / "path"
        assert not non_existent.exists()
        
        import gui.state as gs
        original = gs.SESSIONS_BASE_DIR
        gs.SESSIONS_BASE_DIR = non_existent
        try:
            from gui.state import AppState
            s = AppState()
            s.inquiry_text = "深いパス"
            saved_dir = s.save_session(session_name="nested")
            
            assert saved_dir.exists()
            assert non_existent.exists()
            print(f"  ✅ 自動作成OK: {saved_dir}")
        finally:
            gs.SESSIONS_BASE_DIR = original


def test_special_chars_in_session_name():
    """セッション名に日本語・スペースが入っても OK"""
    print("\n=== test_special_chars_in_session_name ===")
    
    with TempSessionDir() as base:
        from gui.state import AppState
        s = AppState()
        s.inquiry_text = "日本語名"
        s.save_session(session_name="2026春_EOS_R7調査")
        
        from gui.state import list_sessions
        sessions = list_sessions()
        assert len(sessions) == 1
        assert "2026春_EOS_R7調査" in sessions[0]["session_name"]
        print(f"  ✅ 日本語OK: {sessions[0]['dir_name']}")


def test_reset_method():
    """reset() で全フィールドが初期値に戻る"""
    print("\n=== test_reset_method ===")
    
    from gui.state import AppState
    s = _make_full_state()
    assert s.inquiry_text != ""
    assert s.schema is not None
    assert s.repair_df is not None
    
    s.reset()
    assert s.inquiry_text == ""
    assert s.schema is None
    assert s.data_source == "csv"
    assert s.repair_df is None
    assert s.tagged_df is None
    assert s.records is None
    assert s.batches is None
    assert s.batch_results is None
    assert s.ranked_df is None
    assert s.query_tags == {}
    print("  ✅ reset OK")


def test_summary_method():
    """get_summary() が正しい状態を返す"""
    print("\n=== test_summary_method ===")
    
    from gui.state import AppState
    s = AppState()
    summary = s.get_summary()
    assert summary["inquiry_set"] is False
    assert summary["schema_generated"] is False
    assert summary["data_loaded"] is False
    assert summary["tagged"] is False
    assert summary["data_count"] == 0
    
    # 部分的に埋める
    s.inquiry_text = "Q"
    s.schema = {"axes": []}
    s.repair_df = pd.DataFrame({"a": [1, 2, 3]})
    
    summary = s.get_summary()
    assert summary["inquiry_set"] is True
    assert summary["schema_generated"] is True
    assert summary["data_loaded"] is True
    assert summary["data_count"] == 3
    print("  ✅ summary OK")


# --------------------------------------------------------------
# UI 連携テスト
# --------------------------------------------------------------

def test_ui_save_and_reload_via_app():
    """
    App を起動 → state 設定 → save → 新しい App インスタンス → load → 全タブ確認

    Tkinter は同一プロセスで複数 root を扱うのが難しいので、
    1つの App で state.save → state を消す → state.load → refresh_from_state を確認。
    """
    print("\n=== test_ui_save_and_reload_via_app ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    with TempSessionDir() as base:
        from gui.app import App
        
        # === セッションA: フル状態で起動 → 保存 ===
        app = App()
        # state を埋める
        s = app.state
        s.inquiry_text = "UIから保存するセッション"
        s.schema = t3.make_dummy_schema()
        s.data_source = "csv"
        s.csv_path = "/some/test.csv"
        s.mapping_name = "sample_japan"
        s.repair_df = pd.DataFrame([
            {"repair_id": "R001", "user_comment": "テスト", "model": "EOS R7"},
        ])
        s.records = t3.make_dummy_records()
        s.batches = [s.records]
        s.batch_results = [
            {"batch_idx": 0, "success": True,
             "results": [{"repair_id": r["repair_id"]} for r in s.records],
             "input_ids": [r["repair_id"] for r in s.records]}
        ]
        s.tagged_df = t3.make_dummy_tagged_df()
        s.ranked_df = t3.make_dummy_tagged_df().iloc[[0, 2]].copy()
        s.query_tags = {"machine_part": "AF系"}
        s.min_relevance = 0.5
        s.top_n = 75
        s.output_tag = "ui_test"
        
        # 全タブを refresh して UI に反映
        for tab in app.tabs.values():
            tab.refresh_from_state()
        app.root.update()
        
        # 保存
        saved_dir = s.save_session(session_name="ui_test")
        print(f"  保存先: {saved_dir}")
        
        app.root.destroy()
        
        # === セッションB: 新規 App を起動 → セッション読込 ===
        app2 = App()
        # 何も state がない状態
        assert app2.state.inquiry_text == ""
        assert app2.state.schema is None
        assert app2.state.tagged_df is None
        
        # 読み込み
        app2.state.load_session(saved_dir)
        # _refresh_all_tabs を直接呼ぶ
        app2._refresh_all_tabs()
        app2.root.update()
        
        # 値が正しく復元されているか
        assert app2.state.inquiry_text == "UIから保存するセッション"
        assert app2.state.schema is not None
        assert len(app2.state.schema["axes"]) == 3
        assert app2.state.csv_path == "/some/test.csv"
        assert app2.state.min_relevance == 0.5
        assert app2.state.top_n == 75
        assert len(app2.state.tagged_df) == 3
        assert len(app2.state.ranked_df) == 2
        assert app2.state.batch_results[0]["success"] is True
        
        # 各タブの UI 状態を確認(代表的なもの)
        # 設定タブの値はセッションには含まれない(設定は別管理)
        # 問い合わせタブ
        inquiry_tab = app2.tabs["InquiryTab"]
        text_in_ui = inquiry_tab._get_inquiry_text()
        assert text_in_ui == "UIから保存するセッション", \
            f"InquiryTab UI: {text_in_ui!r}"
        
        # スキーマ編集タブ
        schema_tab = app2.tabs["SchemaEditTab"]
        # Treeview に3軸入っているか
        tree_items = schema_tab.tree.get_children()
        assert len(tree_items) == 3, f"スキーマTreeview: {len(tree_items)}件"
        
        # データ取得タブ
        data_tab = app2.tabs["DataLoadTab"]
        assert data_tab.var_csv_path.get() == "/some/test.csv"
        assert data_tab.var_mapping.get() == "sample_japan"
        assert data_tab.var_source.get() == "csv"
        
        # 絞り込みタブ
        ranking_tab = app2.tabs["RankingTab"]
        assert abs(ranking_tab.var_min_relevance.get() - 0.5) < 1e-6
        assert int(ranking_tab.var_top_n.get()) == 75
        
        # 出力タブ
        export_tab = app2.tabs["ExportTab"]
        assert export_tab.var_tag.get() == "ui_test"
        
        app2.root.destroy()
        print("  ✅ UI往復OK: 全タブの状態が正しく復元された")


def test_new_session_clears_state():
    """新規セッションでstate.reset → 全タブ refresh"""
    print("\n=== test_new_session_clears_state ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    from gui.app import App
    
    app = App()
    # 何かしら state を入れる
    app.state.inquiry_text = "消えるはず"
    app.state.schema = t3.make_dummy_schema()
    app.state.tagged_df = t3.make_dummy_tagged_df()
    for tab in app.tabs.values():
        tab.refresh_from_state()
    app.root.update()
    
    # state.reset を直接呼ぶ(new_session はダイアログがあるので)
    app.state.reset()
    app._refresh_all_tabs()
    app._update_session_label(None)
    app.root.update()
    
    # 状態が消えているか
    assert app.state.inquiry_text == ""
    assert app.state.schema is None
    assert app.state.tagged_df is None
    
    # UI も連動して消えているか
    inquiry_tab = app.tabs["InquiryTab"]
    assert inquiry_tab._get_inquiry_text() == ""
    
    schema_tab = app.tabs["SchemaEditTab"]
    assert len(schema_tab.tree.get_children()) == 0
    
    app.root.destroy()
    print("  ✅ 新規セッションで全UI クリアOK")


if __name__ == "__main__":
    test_round_trip_full_state()
    test_round_trip_partial_state()
    test_list_sessions_sorted()
    test_delete_session()
    test_load_nonexistent_raises()
    test_corrupted_state_json_handled_in_list()
    test_session_subdir_creation()
    test_special_chars_in_session_name()
    test_reset_method()
    test_summary_method()
    test_ui_save_and_reload_via_app()
    test_new_session_clears_state()
    
    print("\n" + "=" * 50)
    print("✅ フェーズ4 セッション全テスト通過")
