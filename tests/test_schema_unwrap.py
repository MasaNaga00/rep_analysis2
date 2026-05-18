"""
test_schema_unwrap.py - Dify スキーマレスポンスの解凍ロジックテスト

Dify ワークフローの出力は色々な形でラップされて返ってくるので、
それを全部正しく解凍できるかチェックする。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dify_client import (
    _unwrap_schema_response,
    _strip_success_wrapper,
    DifyError,
    DifyJSONParseError,
)


# 期待されるスキーマ本体
EXPECTED_SCHEMA = {
    "axes": [
        {
            "name": "症状カテゴリ",
            "tier": "core",
            "description": "発生症状の大分類",
            "candidates": ["AF系", "電源系", "シャッター系", "不明"],
            "priority": "high",
        },
        {
            "name": "発生環境温度",
            "tier": "detail",
            "description": "発生時の環境温度",
            "candidates": ["低温", "常温", "高温", "不明"],
            "priority": "medium",
        },
    ],
    "query_summary": "EOS R7 で寒い屋外でAFが迷う事象の切り分け",
}


def test_pattern_a_direct_schema_key():
    """パターンA: outputs に schema キーで直接スキーマ本体"""
    print("\n=== test_pattern_a_direct_schema_key ===")
    outputs = {"schema": EXPECTED_SCHEMA}
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    assert "query_summary" in result
    assert len(result["axes"]) == 2
    print("  ✅ OK: 直接 schema キーを取り出した")


def test_pattern_b_result_str_with_success_schema():
    """パターンB: outputs["result"] が文字列で {success, schema} ラップ"""
    print("\n=== test_pattern_b_result_str_with_success_schema ===")
    import json
    wrapper = {"success": True, "schema": EXPECTED_SCHEMA}
    outputs = {"result": json.dumps(wrapper, ensure_ascii=False)}
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    assert "query_summary" in result
    print("  ✅ OK: 文字列ラップから schema を取り出した")


def test_pattern_c_result_dict_with_success_schema():
    """パターンC: outputs["result"] が dict で {success, schema} ラップ"""
    print("\n=== test_pattern_c_result_dict_with_success_schema ===")
    outputs = {"result": {"success": True, "schema": EXPECTED_SCHEMA}}
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    print("  ✅ OK: dictラップから schema を取り出した")


def test_pattern_d_result_str_with_direct_schema():
    """パターンD: outputs["result"] が文字列で、中身が直接スキーマ"""
    print("\n=== test_pattern_d_result_str_with_direct_schema ===")
    import json
    outputs = {"result": json.dumps(EXPECTED_SCHEMA, ensure_ascii=False)}
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    print("  ✅ OK: 文字列で直接スキーマを取り出した")


def test_pattern_e_text_key_str():
    """パターンE: outputs["text"] にコードブロック付きJSON"""
    print("\n=== test_pattern_e_text_key_str ===")
    import json
    schema_json = json.dumps(EXPECTED_SCHEMA, ensure_ascii=False)
    # LLM が ```json ... ``` でくるんだケース
    outputs = {"text": f"```json\n{schema_json}\n```"}
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    print("  ✅ OK: ```json コードブロックから抽出")


def test_success_false_raises():
    """success: False が来たら DifyError を投げる"""
    print("\n=== test_success_false_raises ===")
    outputs = {"result": {"success": False, "error": "LLM出力がJSON配列でない"}}
    try:
        _unwrap_schema_response(outputs)
        assert False, "DifyError が出るべき"
    except DifyError as e:
        assert "LLM出力" in str(e)
        print(f"  ✅ OK: 期待通りエラー: {e}")


def test_success_false_with_message():
    """success: False で message キーの場合"""
    print("\n=== test_success_false_with_message ===")
    outputs = {"schema": {"success": False, "message": "タイムアウト"}}
    try:
        _unwrap_schema_response(outputs)
        assert False, "DifyError が出るべき"
    except DifyError as e:
        assert "タイムアウト" in str(e)
        print(f"  ✅ OK: 期待通りエラー: {e}")


def test_strip_wrapper_unwrapped():
    """{success, schema} ラップなし(直接スキーマ本体)はそのまま返る"""
    print("\n=== test_strip_wrapper_unwrapped ===")
    result = _strip_success_wrapper(EXPECTED_SCHEMA)
    assert result == EXPECTED_SCHEMA
    print("  ✅ OK: ラップなしはそのまま")


def test_strip_wrapper_with_wrap():
    """{success: true, schema: ...} はちゃんと剥がす"""
    print("\n=== test_strip_wrapper_with_wrap ===")
    wrapped = {"success": True, "schema": EXPECTED_SCHEMA}
    result = _strip_success_wrapper(wrapped)
    assert result == EXPECTED_SCHEMA
    print("  ✅ OK: ラップを剥がして本体を返した")


def test_unknown_format_raises():
    """まったく想定外のキー構成は DifyJSONParseError"""
    print("\n=== test_unknown_format_raises ===")
    outputs = {"result": {"data": "no axes, no schema, no nothing"}}
    try:
        _unwrap_schema_response(outputs)
        assert False, "DifyJSONParseError が出るべき"
    except DifyJSONParseError as e:
        print(f"  ✅ OK: 期待通りエラー: {e}")


def test_real_world_dify_response():
    """実際の Dify から返ってきそうな全体構造で end-to-end"""
    print("\n=== test_real_world_dify_response ===")
    import json
    
    # まさしさんが見ている形 (success/schema ラップが文字列で result に入る)
    raw_data = {
        "task_id": "abc-123",
        "workflow_run_id": "wfr-456",
        "data": {
            "id": "wfr-456",
            "workflow_id": "wf-789",
            "status": "succeeded",
            "outputs": {
                "result": json.dumps({
                    "success": True,
                    "schema": EXPECTED_SCHEMA,
                }, ensure_ascii=False),
            },
            "elapsed_time": 12.3,
        },
    }
    
    outputs = raw_data["data"]["outputs"]
    result = _unwrap_schema_response(outputs)
    assert result == EXPECTED_SCHEMA
    assert "query_summary" in result
    assert result["query_summary"] == "EOS R7 で寒い屋外でAFが迷う事象の切り分け"
    assert result["axes"][0]["name"] == "症状カテゴリ"
    print(f"  ✅ OK: Dify からの実レスポンス相当を正しく解凍")
    print(f"     query_summary: {result['query_summary']}")
    print(f"     axes 数: {len(result['axes'])}")


# ============================================================
# タグ付け(2回目)レスポンスの解凍テスト
# ============================================================

from dify_client import _unwrap_tagging_response


EXPECTED_TAGGING = [
    {
        "repair_id": "R001",
        "tags": {"症状カテゴリ": "AF系"},
        "overall_relevance": 0.9,
    },
    {
        "repair_id": "R002",
        "tags": {"症状カテゴリ": "電源系"},
        "overall_relevance": 0.2,
    },
]


def test_tagging_pattern_a_results_key():
    """outputs["results"] に直接配列"""
    print("\n=== test_tagging_pattern_a_results_key ===")
    outputs = {"results": EXPECTED_TAGGING}
    result = _unwrap_tagging_response(outputs)
    assert result == EXPECTED_TAGGING
    print("  ✅ OK: results キー直接")


def test_tagging_pattern_b_result_str_array():
    """outputs["result"] が配列文字列"""
    print("\n=== test_tagging_pattern_b_result_str_array ===")
    import json
    outputs = {"result": json.dumps(EXPECTED_TAGGING, ensure_ascii=False)}
    result = _unwrap_tagging_response(outputs)
    assert result == EXPECTED_TAGGING
    print("  ✅ OK: 文字列配列")


def test_tagging_pattern_c_result_wrapped():
    """outputs["result"] が {success, results} ラッパー(文字列)"""
    print("\n=== test_tagging_pattern_c_result_wrapped ===")
    import json
    outputs = {
        "result": json.dumps({
            "success": True,
            "results": EXPECTED_TAGGING,
        }, ensure_ascii=False)
    }
    result = _unwrap_tagging_response(outputs)
    assert result == EXPECTED_TAGGING
    print("  ✅ OK: success/results ラップ(文字列)")


def test_tagging_pattern_c2_result_wrapped_dict():
    """outputs["result"] が {success, results} ラッパー(dict)"""
    print("\n=== test_tagging_pattern_c2_result_wrapped_dict ===")
    outputs = {"result": {"success": True, "results": EXPECTED_TAGGING}}
    result = _unwrap_tagging_response(outputs)
    assert result == EXPECTED_TAGGING
    print("  ✅ OK: success/results ラップ(dict)")


def test_tagging_pattern_d_result_direct_array():
    """outputs["result"] が直接配列(dict ではない)"""
    print("\n=== test_tagging_pattern_d_result_direct_array ===")
    outputs = {"result": EXPECTED_TAGGING}
    result = _unwrap_tagging_response(outputs)
    assert result == EXPECTED_TAGGING
    print("  ✅ OK: result が直接配列")


def test_tagging_success_false():
    """タグ付けで success: False"""
    print("\n=== test_tagging_success_false ===")
    outputs = {"result": {"success": False, "error": "バッチ全件失敗"}}
    try:
        _unwrap_tagging_response(outputs)
        assert False, "DifyError が出るべき"
    except DifyError as e:
        assert "バッチ全件失敗" in str(e)
        print(f"  ✅ OK: 期待通りエラー: {e}")


def test_tagging_unknown_format():
    """想定外の形式"""
    print("\n=== test_tagging_unknown_format ===")
    outputs = {"result": {"something_else": "no results"}}
    try:
        _unwrap_tagging_response(outputs)
        assert False, "DifyJSONParseError が出るべき"
    except DifyJSONParseError as e:
        print(f"  ✅ OK: {e}")


if __name__ == "__main__":
    test_pattern_a_direct_schema_key()
    test_pattern_b_result_str_with_success_schema()
    test_pattern_c_result_dict_with_success_schema()
    test_pattern_d_result_str_with_direct_schema()
    test_pattern_e_text_key_str()
    test_success_false_raises()
    test_success_false_with_message()
    test_strip_wrapper_unwrapped()
    test_strip_wrapper_with_wrap()
    test_unknown_format_raises()
    test_real_world_dify_response()
    
    # タグ付け側
    test_tagging_pattern_a_results_key()
    test_tagging_pattern_b_result_str_array()
    test_tagging_pattern_c_result_wrapped()
    test_tagging_pattern_c2_result_wrapped_dict()
    test_tagging_pattern_d_result_direct_array()
    test_tagging_success_false()
    test_tagging_unknown_format()
    
    print("\n" + "=" * 50)
    print("✅ スキーマ・タグ付け解凍 全テスト通過")
