"""Debug Adapter Protocol 客户端（P4.5a）。

- 基于 DAP 基础协议（Content-Length 帧 + JSON 消息），与 LSP 同构；
- 通过子进程 stdin/stdout 与 lldb-dap 通信（后端以 `docker exec -i` 把
  通道延伸进调试沙箱——DAP 服务器与被调试程序同容器）；
- 线程模型：构造后启动读线程；response 按 request_seq 唤醒等待者，
  event 进入回调（服务层据此推进状态机）；
- 只发协议白名单命令（由服务层约束），本客户端不提供任意命令透传。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable


class DapError(RuntimeError):
    """DAP 通信/协议错误。"""


class DapTimeout(DapError):
    """等待响应/事件超时。"""


def encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


class _Buffer:
    """字节流 → DAP 帧（Content-Length 头 + JSON 体）。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[dict]:
        self._buf.extend(chunk)
        messages: list[dict] = []
        while True:
            sep = self._buf.find(b"\r\n\r\n")
            if sep < 0:
                break
            header = bytes(self._buf[:sep]).decode("ascii", errors="replace")
            length: int | None = None
            for line in header.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        length = None
                    break
            if length is None:
                # 帧损坏：丢弃头部重试（健壮性优先，不崩溃）
                del self._buf[: sep + 4]
                continue
            if len(self._buf) < sep + 4 + length:
                break
            body = bytes(self._buf[sep + 4 : sep + 4 + length])
            del self._buf[: sep + 4 + length]
            try:
                messages.append(json.loads(body.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return messages


class DapClient:
    """一个 lldb-dap 会话的双向通道。"""

    def __init__(
        self,
        argv: list[str],
        on_event: Callable[[dict], None],
        stderr_sink: Callable[[str], None] | None = None,
    ) -> None:
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._on_event = on_event
        self._stderr_sink = stderr_sink
        self._closed = threading.Event()

        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

    # ---------------------------------------------------------------- 底层

    def _read_stdout(self) -> None:
        buffer = _Buffer()
        try:
            assert self._proc.stdout is not None
            while not self._closed.is_set():
                chunk = self._proc.stdout.read1(8192)
                if not chunk:
                    break
                for message in buffer.feed(chunk):
                    self._dispatch(message)
        except (OSError, ValueError):
            pass
        finally:
            # 通道关闭：唤醒全部等待者
            with self._lock:
                for event in self._pending.values():
                    event.set()

    def _read_stderr(self) -> None:
        try:
            assert self._proc.stderr is not None
            while not self._closed.is_set():
                chunk = self._proc.stderr.read1(4096)
                if not chunk:
                    break
                if self._stderr_sink:
                    self._stderr_sink(chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass

    def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "response":
            request_seq = message.get("request_seq")
            with self._lock:
                waiter = self._pending.pop(request_seq, None)
                if waiter is not None:
                    self._responses[request_seq] = message
                    waiter.set()
        elif kind == "event":
            try:
                self._on_event(message)
            except Exception:  # 事件回调失败不终止读线程
                pass

    # ---------------------------------------------------------------- API

    def send_request(self, command: str, arguments: dict | None = None, timeout: float = 15.0) -> dict:
        """发送请求并等待对应响应，返回响应体（失败抛 DapError）。"""
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        message = {"seq": seq, "type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        waiter = threading.Event()
        with self._lock:
            self._pending[seq] = waiter
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(encode_message(message))
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._lock:
                self._pending.pop(seq, None)
            raise DapError(f"DAP 通道已关闭：{exc}") from exc

        if not waiter.wait(timeout):
            with self._lock:
                self._pending.pop(seq, None)
            raise DapTimeout(f"DAP 请求超时：{command}")
        with self._lock:
            response = self._responses.pop(seq, {})
        if response.get("success") is not True:
            message_text = response.get("message") or "未知错误"
            raise DapError(f"DAP 请求失败：{command}（{message_text}）")
        return response.get("body") or {}

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None and not self._closed.is_set()

    def close(self, timeout: float = 5.0) -> None:
        """关闭通道并终止子进程。"""
        self._closed.set()
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=timeout)
