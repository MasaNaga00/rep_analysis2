"""
test_phase3_integration.py - フェーズ3の通しシミュレーション

実 Dify を叩かずに、state を手動で組み立てて
各タブの on_show / refresh_from_state / 表示更新を検証する。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd


def make_dummy_schema():
    return {
        "query_summary": "EOS R7 で寒い屋外で AF が迷う現象の切り分け",
        "axes": [
            {
                "name": "machine_part",
                "tier": "core",
                "description": "発生箇所",
                "candidates": ["AF系", "電源系", "シャッター系", "不明"],
                "priority": "high",
            },
            {
                "name": "environment",
                "tier": "detail",
                "description": "発生環境",
                "candidates": ["低温下", "高湿度下", "通常環境", "該当なし"],
                "priority": "medium",
            },
            {
                "name": "lens_dep",
                "tier": "detail",
                "description": "レンズ依存性",
                "candidates": ["特定レンズで再現", "複数レンズで再現", "該当なし"],
                "priority": "medium",
            },
        ],
    }


def make_dummy_tagged_df():
    """flatten_tagging_results 相当のDFを手で作る"""
    data = [
        {
            "repair_id": "R001",
            "user_comment": "冬の山で AF が合わない",
            "language_detected": "ja",
            "tag__machine_part": "AF系",
            "conf__machine_part": 0.9,
            "evidence__machine_part": "冬の山でAFが合わない",
            "tag__environment": "低温下",
            "conf__environment": 0.85,
            "evidence__environment": "冬の山",
            "tag__lens_dep": "該当なし",
            "conf__lens_dep": 0.5,
            "evidence__lens_dep": "",
            "overall_relevance": 0.92,
            "relevance_reason": "AF系+低温下で問い合わせと完全一致",
        },
        {
            "repair_id": "R002",
            "user_comment": "シャッターが切れない",
            "language_detected": "ja",
            "tag__machine_part": "シャッター系",
            "conf__machine_part": 0.95,
            "evidence__machine_part": "シャッター切れない",
            "tag__environment": "通常環境",
            "conf__environment": 0.7,
            "evidence__environment": "",
            "tag__lens_dep": "該当なし",
            "conf__lens_dep": 0.4,
            "evidence__lens_dep": "",
            "overall_relevance": 0.15,
            "relevance_reason": "問い合わせと無関係",
        },
        {
            "repair_id": "R003",
            "user_comment": "RF24-105 装着時にAFが迷う",
            "language_detected": "ja",
            "tag__machine_part": "AF系",
            "conf__machine_part": 0.88,
            "evidence__machine_part": "AFが迷う",
            "tag__environment": "通常環境",
            "conf__environment": 0.6,
            "evidence__environment": "",
            "tag__lens_dep": "特定レンズで再現",
            "conf__lens_dep": 0.9,
            "evidence__lens_dep": "RF24-105 装着時",
            "overall_relevance": 0.78,
            "relevance_reason": "AF系で部分一致、レンズ依存も検出",
        },
    ]
    return pd.DataFrame(data)


def make_dummy_records():
    """preprocess の出力相当"""
    return [
        {
            "repair_id": "R001",
            "comments_combined": "[U] 冬の山で AF が合わない",
            "meta": {
                "language": "ja",
                "length_tier": "short",
                "total_length": 25,
            },
        },
        {
            "repair_id": "R002",
            "comments_combined": "[U] シャッターが切れない",
            "meta": {
                "language": "ja",
                "length_tier": "short",
                "total_length": 18,
            },
        },
        {
            "repair_id": "R003",
            "comments_combined": "[U] RF24-105 装着時にAFが迷う",
            "meta": {
                "language": "ja",
                "length_tier": "short",
                "total_length": 22,
            },
        },
    ]


def test_each_tab_refresh_from_state():
    """各タブの refresh_from_state が完全な state でエラーなく動くか"""
    print("\n=== test_each_tab_refresh_from_state ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    from gui.app import App
    
    app = App()
    
    # state を組み立て
    app.state.inquiry_text = "EOS R7 で寒い屋外で AF が迷う"
    app.state.schema = make_dummy_schema()
    app.state.records = make_dummy_records()
    app.state.batches = [app.state.records]  # 1バッチ
    app.state.tagged_df = make_dummy_tagged_df()
    app.state.batch_results = [
        {"batch_idx": 0, "success": True,
         "results": [{"repair_id": r["repair_id"]} for r in app.state.records],
         "input_ids": [r["repair_id"] for r in app.state.records]},
    ]
    app.state.repair_df = make_dummy_tagged_df()[["repair_id", "user_comment"]]
    app.state.query_tags = {"machine_part": "AF系"}
    app.state.min_relevance = 0.3
    app.state.top_n = 50
    
    # 各タブの refresh_from_state を呼ぶ
    for tab in app.tabs.values():
        try:
            tab.refresh_from_state()
            print(f"  ✅ {tab.TITLE}.refresh_from_state OK")
        except Exception as e:
            print(f"  ❌ {tab.TITLE}.refresh_from_state: {e}")
            raise
    
    app.root.update()
    app.root.destroy()
    print("  ✅ 全タブ refresh_from_state 成功")


def test_tab_navigation_keeps_state():
    """タブを順に切り替えて on_show/on_hide が呼ばれても state が壊れない"""
    print("\n=== test_tab_navigation_keeps_state ===")
    
    import os
    if not os.environ.get("DISPLAY"):
        print("  ⏭️ DISPLAY なし、スキップ")
        return
    
    from gui.app import App
    
    app = App()
    app.state.schema = make_dummy_schema()
    app.state.inquiry_text = "test inquiry"
    app.state.tagged_df = make_dummy_tagged_df()
    
    # 全タブを順に開く
    for i in range(len(app.tabs)):
        app.notebook.select(i)
        app.root.update()
    
    # state が初期と変わっていないか
    assert app.state.schema is not None
    assert app.state.inquiry_text == "test inquiry"
    assert app.state.tagged_df is not None
    assert len(app.state.schema["axes"]) == 3
    
    app.root.destroy()
    print("  ✅ タブ切り替えで state が保持された")


def test_ranking_logic_with_dummy_data():
    """絞り込みタブの内部ロジック: scoring.rank_results が動くか"""
    print("\n=== test_ranking_logic_with_dummy_data ===")
    
    try:
        import scoring
    except ImportError:
        print("  ⏭️ scoring モジュールがないのでスキップ")
        return
    
    schema = make_dummy_schema()
    tagged_df = make_dummy_tagged_df()
    query_tags = {"machine_part": "AF系"}
    
    ranked = scoring.rank_results(
        tagged_df,
        query_tags=query_tags,
        schema=schema,
        min_relevance=0.3,
        top_n=10,
    )
    
    # AF系のレコードだけ残るはず (R001, R003)
    assert len(ranked) == 2, f"期待:2件, 実際:{len(ranked)}件"
    repair_ids = set(ranked["repair_id"].tolist())
    assert "R001" in repair_ids
    assert "R003" in repair_ids
    assert "R002" not in repair_ids  # シャッター系で R002 は弾かれる
    print(f"  ✅ rank_results: R001, R003 が残った ({len(ranked)}件)")


def test_save_results_with_dummy_data():
    """出力タブの内部ロジック: save_results がファイルを生成する"""
    print("\n=== test_save_results_with_dummy_data ===")
    
    try:
        import scoring
    except ImportError:
        print("  ⏭️ scoring モジュールがないのでスキップ")
        return
    
    schema = make_dummy_schema()
    tagged_df = make_dummy_tagged_df()
    ranked = scoring.rank_results(
        tagged_df,
        query_tags={"machine_part": "AF系"},
        schema=schema,
        min_relevance=0.3,
        top_n=10,
    )
    
    # 一時的に config.OUTPUT_DIR を変更
    import config
    with tempfile.TemporaryDirectory() as td:
        original = config.OUTPUT_DIR
        config.OUTPUT_DIR = td
        try:
            paths = scoring.save_results(
                tagged_df=tagged_df,
                ranked_df=ranked,
                schema=schema,
                inquiry_text="test inquiry",
                tag="test_tag",
            )
        finally:
            config.OUTPUT_DIR = original
        
        # 期待されるキー
        assert "ranked_csv" in paths
        assert "ranked_parquet" in paths
        assert "tagged_parquet" in paths
        assert "schema_json" in paths
        assert "meta_json" in paths
        
        # ファイルが実在するか
        for key, path in paths.items():
            assert Path(path).exists(), f"{key} が無い: {path}"
        
        print(f"  ✅ {len(paths)} ファイル生成: {list(paths.keys())}")


def test_mapping_listing():
    """マッピング選択 UI が認識する登録済みマッピング"""
    print("\n=== test_mapping_listing ===")
    
    import loader
    mappings = loader.list_mappings()
    names = [m["name"] for m in mappings]
    print(f"  検出されたマッピング: {names}")
    assert "sample_japan" in names
    assert "sample_overseas" in names
    print("  ✅ サンプルマッピング検出 OK")


def test_pandastable_availability():
    """pandastable が使えるか確認"""
    print("\n=== test_pandastable_availability ===")
    from gui.widgets.dataframe_view import PANDASTABLE_AVAILABLE
    print(f"  PANDASTABLE_AVAILABLE = {PANDASTABLE_AVAILABLE}")
    # Mac/Windows 環境では使えるはず、なくてもフォールバックでOK


if __name__ == "__main__":
    test_pandastable_availability()
    test_mapping_listing()
    test_each_tab_refresh_from_state()
    test_tab_navigation_keeps_state()
    test_ranking_logic_with_dummy_data()
    test_save_results_with_dummy_data()
    
    print("\n" + "=" * 50)
    print("✅ フェーズ3 統合テスト 全通過")
