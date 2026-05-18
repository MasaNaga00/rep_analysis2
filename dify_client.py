"""
dify_client.py - Dify APIクライアント

- 1回目（スキーマ生成）：同期で1回
- 2回目（タグ付け）：非同期並列でバッチ処理
- リトライ・JSON破損リカバリ付き
- CA証明書を指定したHTTPS接続（社内Dify対応）
"""
import asyncio
import json
import re
import ssl
import sys
from pathlib import Path
from typing import Optional
import aiohttp
import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type
)

import config


class DifyError(Exception):
    """Dify API関連の基底例外"""


class DifyJSONParseError(DifyError):
    """JSON解析失敗"""


class DifyCertificateError(DifyError):
    """CA証明書ファイルが見つからない・読み込めない"""


# ---------- CA証明書の解決 ----------

def _get_app_root() -> Path:
    """
    アプリのルートディレクトリを返す。
    
    - 通常実行: このファイル（dify_client.py）のあるディレクトリ
    - cx_Freeze 等で凍結された exe: 実行ファイルのあるディレクトリ
    """
    if getattr(sys, "frozen", False):
        # cx_Freeze / PyInstaller 等の凍結環境
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def resolve_ca_cert_path(configured_path: Optional[str] = None) -> Path:
    """
    CA証明書ファイルのパスを解決して返す。
    
    探索順:
        1. 絶対パスならそのまま使用
        2. 相対パスなら ①アプリルート → ②カレントディレクトリ の順
    
    Args:
        configured_path: 設定された証明書パス（省略時は config.DIFY_CA_CERT_PATH）
    
    Returns:
        証明書ファイルの絶対パス
    
    Raises:
        DifyCertificateError: ファイルが見つからない
    """
    # 引数指定があれば優先、なければ config を使用
    # 空文字は「未設定」として扱う(GUI でクリアされたケース等)
    path_str = configured_path if configured_path is not None else config.DIFY_CA_CERT_PATH
    if not path_str:
        raise DifyCertificateError(
            "CA証明書パスが設定されていません。"
            "config.DIFY_CA_CERT_PATH または環境変数 DIFY_CA_CERT_PATH を確認してください。"
        )
    
    path = Path(path_str)
    
    if path.is_absolute():
        if not path.exists():
            raise DifyCertificateError(
                f"CA証明書ファイルが存在しません: {path}"
            )
        return path
    
    # 相対パスの場合は探索(重複は除去)
    seen = set()
    candidates = []
    for base in [_get_app_root(), Path.cwd()]:
        candidate = (base / path).resolve()
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    raise DifyCertificateError(
        f"CA証明書ファイル '{path_str}' が見つかりません。\n"
        f"以下を確認してください:\n"
        f"  探索した場所:\n"
        + "\n".join(f"    - {c}" for c in candidates)
        + f"\n  config.DIFY_CA_CERT_PATH = '{path_str}'"
    )


def _build_ssl_context(ca_cert_path: Optional[Path] = None) -> ssl.SSLContext:
    """
    aiohttp 用の SSLContext を構築する。
    
    Args:
        ca_cert_path: CA証明書パス（省略時は resolve_ca_cert_path を使用）
    """
    if ca_cert_path is None:
        ca_cert_path = resolve_ca_cert_path()
    
    try:
        ctx = ssl.create_default_context(cafile=str(ca_cert_path))
    except (ssl.SSLError, OSError) as e:
        raise DifyCertificateError(
            f"CA証明書ファイルの読み込みに失敗しました: {ca_cert_path}\n  エラー: {e}"
        )
    return ctx


# ---------- ユーティリティ ----------

def extract_json(text: str) -> dict | list:
    """
    LLM出力から JSON部分を抽出してパース。
    コードブロック記法・前後の説明文を除去。
    """
    text = text.strip()
    
    # コードブロック記法の除去
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    
    # 最初の { または [ から最後の } または ] まで抽出
    start_obj = text.find("{")
    start_arr = text.find("[")
    
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        start, end_char = start_arr, "]"
    elif start_obj != -1:
        start, end_char = start_obj, "}"
    else:
        raise DifyJSONParseError(f"JSONが見つかりません: {text[:200]}")
    
    end = text.rfind(end_char)
    if end == -1:
        raise DifyJSONParseError(f"JSON終端が見つかりません: {text[:200]}")
    
    json_str = text[start:end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise DifyJSONParseError(f"JSONパース失敗: {e}\n対象: {json_str[:500]}")


# ---------- 1回目：スキーマ生成（同期） ----------

@retry(
    stop=stop_after_attempt(config.MAX_RETRIES),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((requests.RequestException, DifyJSONParseError)),
    reraise=True,
)
def generate_tag_schema(
    inquiry_text: str,
    max_detail_axes: int = 4,
    user_id: str = "repair-analysis",
) -> dict:
    """
    Dify 1回目ワークフローを呼び出し、タグスキーマを生成。
    
    Returns:
        {
            "axes": [...],
            "query_summary": "..."
        }
    """
    url = f"{config.DIFY_API_BASE}/workflows/run"
    headers = {
        "Authorization": f"Bearer {config.DIFY_API_KEY_SCHEMA}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {
            "inquiry_text": inquiry_text,
            "max_detail_axes": max_detail_axes,
        },
        "response_mode": "blocking",
        "user": user_id,
    }
    
    # CA証明書を指定してHTTPS接続
    ca_cert = resolve_ca_cert_path()
    
    resp = requests.post(
        url, headers=headers, json=payload,
        timeout=config.REQUEST_TIMEOUT,
        verify=str(ca_cert),
    )
    resp.raise_for_status()
    data = resp.json()
    
    # Difyワークフロー出力の取り出し
    outputs = data.get("data", {}).get("outputs", {})
    return _unwrap_schema_response(outputs)


def _unwrap_schema_response(outputs: dict) -> dict:
    """
    Dify ワークフロー出力からスキーマ本体 ({"axes": [...], "query_summary": ...})
    を取り出す。ワークフロー側の最終ノードの返し方によって、以下のような複数の
    形があり得るので順に解いていく:
    
        パターンA: {"schema": {"axes": [...], "query_summary": ...}}
        パターンB: {"result": "{\"success\": true, \"schema\": {...}}"}  ← 文字列
        パターンC: {"result": {"success": true, "schema": {...}}}        ← dict
        パターンD: {"result": "{\"axes\": [...], ...}"}                  ← 直接schemaの文字列
        パターンE: {"text": "..."} (LLMノード生出力)
    
    success: False のラッパーが付いていれば DifyError を投げる。
    """
    # パターンA: outputs["schema"] にスキーマ本体
    if "schema" in outputs:
        schema = outputs["schema"]
        if isinstance(schema, str):
            schema = extract_json(schema)
        # 中身がさらに {"success": ..., "schema": ...} ラップされているなら剥がす
        return _strip_success_wrapper(schema)
    
    # パターンB〜E: result / text / 他のキー
    raw = outputs.get("result") or outputs.get("text") or \
          next(iter(outputs.values()), "")
    
    if isinstance(raw, str):
        raw = extract_json(raw)
    
    if not isinstance(raw, dict):
        raise DifyJSONParseError(
            f"スキーマの取り出しに失敗しました。outputs の型: {type(raw)}, "
            f"内容: {str(raw)[:200]}"
        )
    
    return _strip_success_wrapper(raw)


def _strip_success_wrapper(obj: dict) -> dict:
    """
    {"success": True, "schema": {...}} のようなラッパーを剥がして、
    スキーマ本体({"axes": [...], "query_summary": ...})を返す。
    
    ラップされていない場合(直接スキーマ本体が来た場合)はそのまま返す。
    success: False の場合は DifyError を投げる。
    """
    # success フラグがあって False なら明示的エラー
    if "success" in obj and obj["success"] is False:
        err = obj.get("error") or obj.get("message") or "ワークフローが success: false を返しました"
        raise DifyError(f"Dify スキーマ生成エラー: {err}")
    
    # ラッパー: {"success": ..., "schema": {...}} を剥がす
    if "schema" in obj and isinstance(obj["schema"], dict):
        inner = obj["schema"]
        # 念のため文字列だった場合も対応
        if isinstance(inner, str):
            inner = extract_json(inner)
        return inner
    
    # 既にスキーマ本体(axes を直接持つ)ならそのまま
    if "axes" in obj:
        return obj
    
    # 形が違うが、せめて中身を返す(呼び出し側でバリデーションして警告)
    raise DifyJSONParseError(
        f"想定外のスキーマ形式です。トップレベルキー: {list(obj.keys())}"
    )


def _unwrap_tagging_response(outputs: dict) -> list:
    """
    Dify ワークフロー出力からタグ付け結果のリスト([{repair_id, tags, ...}, ...])を
    取り出す。1回目の _unwrap_schema_response と同じく、複数のラップパターンに対応:
    
        パターンA: outputs["results"] が配列
        パターンB: outputs["result"] が "[...]" 文字列(配列のJSON)
        パターンC: outputs["result"] が dict で {"success": true, "results": [...]} ラップ
        パターンD: outputs["result"] が直接配列
        パターンE: outputs["text"] にコードブロック付きJSON
    
    success: False のラッパーが付いていれば DifyError を投げる。
    """
    # パターンA: outputs["results"] に直接配列
    if "results" in outputs:
        val = outputs["results"]
        if isinstance(val, str):
            val = extract_json(val)
        if isinstance(val, list):
            return val
    
    # その他: result / text / 最初のキー
    raw = outputs.get("result") or outputs.get("text") or \
          next(iter(outputs.values()), None)
    
    # 既にリストならそのまま
    if isinstance(raw, list):
        return raw
    
    # 文字列ならパース
    if isinstance(raw, str):
        raw = extract_json(raw)
    
    if isinstance(raw, list):
        return raw
    
    # dict なら {success, results} ラッパーを剥がす
    if isinstance(raw, dict):
        if "success" in raw and raw["success"] is False:
            err = raw.get("error") or raw.get("message") or "ワークフローが success: false を返しました"
            raise DifyError(f"Dify タグ付けエラー: {err}")
        if "results" in raw and isinstance(raw["results"], list):
            return raw["results"]
        # 1件だけ返ってきたケース? (リストに包んで返す)
        if "repair_id" in raw:
            return [raw]
    
    raise DifyJSONParseError(
        f"タグ付け結果(配列)の取り出しに失敗しました。型: {type(raw)}, "
        f"内容: {str(raw)[:200]}"
    )


# ---------- 2回目：タグ付け（非同期バッチ） ----------

async def _call_dify_tagging(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    tag_schema: dict,
    inquiry_summary: str,
    batch: list[dict],
    batch_idx: int,
    user_id: str,
) -> dict:
    """1バッチ分のタグ付けを実行"""
    url = f"{config.DIFY_API_BASE}/workflows/run"
    headers = {
        "Authorization": f"Bearer {config.DIFY_API_KEY_TAGGING}",
        "Content-Type": "application/json",
    }
    
    # Difyに投入するrecords_json形式
    records_json = json.dumps([
        {"repair_id": r["repair_id"], "records": r["records"]}
        for r in batch
    ], ensure_ascii=False, indent=2)
    
    payload = {
        "inputs": {
            "tag_schema": json.dumps(tag_schema, ensure_ascii=False),
            "inquiry_summary": inquiry_summary,
            "records_json": records_json,
        },
        "response_mode": "blocking",
        "user": user_id,
    }
    
    async with semaphore:
        for attempt in range(config.MAX_RETRIES):
            try:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                
                outputs = data.get("data", {}).get("outputs", {})
                results = _unwrap_tagging_response(outputs)
                
                return {
                    "batch_idx": batch_idx,
                    "success": True,
                    "results": results,
                    "input_ids": [r["repair_id"] for r in batch],
                }
            
            except (aiohttp.ClientError, asyncio.TimeoutError, DifyJSONParseError) as e:
                if attempt == config.MAX_RETRIES - 1:
                    return {
                        "batch_idx": batch_idx,
                        "success": False,
                        "error": f"{type(e).__name__}: {e}",
                        "input_ids": [r["repair_id"] for r in batch],
                    }
                await asyncio.sleep(2 ** attempt)


async def tag_records_batch(
    tag_schema: dict,
    inquiry_summary: str,
    batches: list[list[dict]],
    user_id: str = "repair-analysis",
    progress_callback=None,
) -> list[dict]:
    """
    複数バッチを並列実行してタグ付け結果を返す。
    
    Args:
        tag_schema: 1回目で生成したスキーマ
        inquiry_summary: 問い合わせ要約
        batches: chunk_recordsで分割済みのバッチリスト
        progress_callback: 進捗通知用の関数 callback(done, total, last_result)
    
    Returns:
        各バッチの結果リスト
    """
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
    
    # CA証明書を指定したSSLコンテキストでaiohttpを初期化
    ssl_ctx = _build_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _call_dify_tagging(
                session, semaphore, tag_schema, inquiry_summary,
                batch, idx, user_id
            )
            for idx, batch in enumerate(batches)
        ]
        
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            if progress_callback:
                progress_callback(len(results), len(tasks), result)
    
    # バッチ順にソート
    results.sort(key=lambda x: x["batch_idx"])
    return results


def run_tagging_sync(
    tag_schema: dict,
    inquiry_summary: str,
    batches: list[list[dict]],
    user_id: str = "repair-analysis",
    progress_callback=None,
) -> list[dict]:
    """
    Jupyter等から同期的に呼べるラッパー。
    既存のevent loopがあるかチェックして適切に処理。
    """
    try:
        loop = asyncio.get_running_loop()
        # Jupyterの既存ループ上で実行
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(
            tag_records_batch(tag_schema, inquiry_summary, batches, user_id, progress_callback)
        )
    except RuntimeError:
        # ループ未起動ならasyncio.run
        return asyncio.run(
            tag_records_batch(tag_schema, inquiry_summary, batches, user_id, progress_callback)
        )
