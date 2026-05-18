"""
gui/workers.py - 重い処理をワーカースレッドで実行するためのユーティリティ

Tkinter のメインスレッドをブロックせずに以下を実行する:
- Dify 1回目(スキーマ生成、数秒)
- Dify 2回目(タグ付け、数分)
- SQL/CSV 読み込み(大きいファイルだと数秒〜十数秒)

スレッドとメインスレッドの間は queue.Queue で進捗・結果をやり取りする。
メインスレッド側は root.after() で定期的にキューをポーリングする。
"""
from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional


# ------------------------------------------------------------------
# メッセージ型
# ------------------------------------------------------------------

@dataclass
class WorkerMessage:
    """ワーカースレッドからメインスレッドへのメッセージ"""
    kind: str           # "progress" | "log" | "done" | "error"
    payload: Any = None # 内容はkindによる
    
    # progress: {"done": int, "total": int, "info": str}
    # log:      "メッセージ文字列"
    # done:     ワーカーが返した結果(関数の戻り値)
    # error:    {"exc_type": str, "message": str, "traceback": str}


# ------------------------------------------------------------------
# 汎用ワーカー
# ------------------------------------------------------------------

class Worker(threading.Thread):
    """
    任意の関数をワーカースレッドで実行する汎用クラス。
    
    使い方:
        q = queue.Queue()
        worker = Worker(target=some_long_function, args=(...), msg_queue=q)
        worker.start()
        # メインスレッド側で root.after() でキューをポーリング
    
    target 関数が `progress_callback` 引数を受け付ける場合は、
    キャンセル通知や進捗送信用のコールバックを自動で渡す。
    """
    
    def __init__(
        self,
        target: Callable,
        msg_queue: queue.Queue,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        pass_progress_callback: bool = False,
        name: Optional[str] = None,
    ):
        super().__init__(daemon=True, name=name or target.__name__)
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.msg_queue = msg_queue
        self.pass_progress_callback = pass_progress_callback
        self._cancel_event = threading.Event()
        self._result: Any = None
    
    def cancel(self):
        """キャンセル要求(target 側がチェックすれば停止できる)"""
        self._cancel_event.set()
    
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()
    
    def _progress_callback(self, done: int, total: int, last_result: Any = None):
        """target に渡される進捗コールバック"""
        info = ""
        if isinstance(last_result, dict):
            if not last_result.get("success", True):
                err = last_result.get("error", "")[:80]
                info = f"⚠️ batch {last_result.get('batch_idx', '?')}: {err}"
        
        self.msg_queue.put(WorkerMessage(
            kind="progress",
            payload={"done": done, "total": total, "info": info,
                     "last_result": last_result}
        ))
    
    def log(self, message: str):
        """ワーカー内からログメッセージを送る用"""
        self.msg_queue.put(WorkerMessage(kind="log", payload=message))
    
    def run(self):
        try:
            kwargs = dict(self.kwargs)
            if self.pass_progress_callback:
                kwargs["progress_callback"] = self._progress_callback
            
            result = self.target(*self.args, **kwargs)
            self._result = result
            
            self.msg_queue.put(WorkerMessage(kind="done", payload=result))
        
        except Exception as e:
            self.msg_queue.put(WorkerMessage(
                kind="error",
                payload={
                    "exc_type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            ))


# ------------------------------------------------------------------
# キューポーリング用ヘルパー
# ------------------------------------------------------------------

class QueuePoller:
    """
    Tkinter の root.after() で定期実行し、キューからメッセージを取り出して
    コールバックに渡すヘルパー。
    
    使い方:
        poller = QueuePoller(
            root=root,
            msg_queue=q,
            on_progress=lambda p: progress_bar.set(p["done"] / p["total"]),
            on_log=lambda msg: log_text.insert("end", msg),
            on_done=lambda result: handle_completion(result),
            on_error=lambda err: show_error_dialog(err),
            interval_ms=100,
        )
        poller.start()
    """
    
    def __init__(
        self,
        root,  # tk.Tk or tk.Toplevel
        msg_queue: queue.Queue,
        on_progress: Optional[Callable[[dict], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[dict], None]] = None,
        interval_ms: int = 100,
    ):
        self.root = root
        self.msg_queue = msg_queue
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_done = on_done
        self.on_error = on_error
        self.interval_ms = interval_ms
        self._stopped = False
        self._finished = False
    
    def start(self):
        """ポーリング開始"""
        self._stopped = False
        self._finished = False
        self._poll()
    
    def stop(self):
        """ポーリング停止"""
        self._stopped = True
    
    def _poll(self):
        if self._stopped:
            return
        
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self._dispatch(msg)
                if self._finished:
                    return  # done/error を受けたら停止
        except queue.Empty:
            pass
        
        if not self._stopped:
            self.root.after(self.interval_ms, self._poll)
    
    def _dispatch(self, msg: WorkerMessage):
        if msg.kind == "progress" and self.on_progress:
            self.on_progress(msg.payload)
        elif msg.kind == "log" and self.on_log:
            self.on_log(msg.payload)
        elif msg.kind == "done":
            self._finished = True
            if self.on_done:
                self.on_done(msg.payload)
        elif msg.kind == "error":
            self._finished = True
            if self.on_error:
                self.on_error(msg.payload)
