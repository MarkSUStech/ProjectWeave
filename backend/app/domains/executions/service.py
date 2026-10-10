"""执行会话服务（P4.2b）：生命周期编排 + 校验 + 结果落库。

职责边界：
- 本模块只做"会话状态机 + 通用校验 + 资源上限"；
- 语言特有逻辑（命令、文件包、结果解析）全部委托 LanguageRunner；
- 环境隔离全部委托 SandboxManager；
- 一切确定性，无 LLM 参与。

状态语义：completed = 沙箱执行完整跑完（程序退出码/断言失败是业务结果，
不是基础设施失败）；failed = 无法执行（沙箱/协议错误）；timed-out / cancelled
= 被资源策略终止。
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.domains.events.service import append_event, server_event_id
from app.domains.executions.languages import get_runner, list_languages
from app.domains.executions.languages.base import ExecutionSpecInput
from app.domains.executions.models import ExecutionSession, TERMINAL_STATUSES
from app.domains.executions.sandbox.base import SandboxUnavailableError
from app.domains.executions.sandbox.docker_sandbox import DockerSandboxManager
from app.domains.executions.schemas import (
    ExecutionCreate,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PREPARING,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_TIMED_OUT,
)

# 结果信任级：服务端执行 ≠ 正式认证；正式认证需服务端受保护测试与
# 可信快照（P5 计划），本阶段一切执行结果按 practice 呈现（D32）。
TRUST_LEVEL = "practice"

RESERVED_PREFIX = "__pw"
_INVALID_PATH_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}


class ExecutionValidationError(ValueError):
    """请求不合法（422）。"""


class ExecutionNotFoundError(KeyError):
    """会话不存在（404）。"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# 沙箱管理器（可注入；测试用假实现替换）
# --------------------------------------------------------------------------

_sandbox_manager = DockerSandboxManager()
_sandbox_lock = threading.Lock()

# 会话工厂：默认应用全局 SessionLocal；测试注入临时库工厂。
_session_factory = SessionLocal


def set_sandbox_manager(manager) -> None:
    """测试注入用：替换全局沙箱管理器。"""
    global _sandbox_manager
    with _sandbox_lock:
        _sandbox_manager = manager


def get_sandbox_manager():
    with _sandbox_lock:
        return _sandbox_manager


def set_session_factory(factory) -> None:
    """测试注入用：替换 worker 线程的会话工厂。"""
    global _session_factory
    _session_factory = factory


# --------------------------------------------------------------------------
# 活动句柄（取消信号 + 输出流缓冲）
# --------------------------------------------------------------------------

class _Handle:
    """活动执行句柄：取消信号 + 线程安全的输出缓冲。"""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.events_lock = threading.Lock()
        self.events: list[dict] = []
        self.stdout_chunks: list[str] = []
        self.stderr_chunks: list[str] = []
        self.seq = 0

    def append_event(self, channel: str, text: str) -> None:
        with self.events_lock:
            self.seq += 1
            self.events.append(
                {"seq": self.seq, "at": utcnow().isoformat(), "channel": channel, "text": text}
            )
            if channel == "stdout":
                self.stdout_chunks.append(text)
            elif channel == "stderr":
                self.stderr_chunks.append(text)

    def snapshot(self) -> tuple[list[dict], str, str]:
        with self.events_lock:
            return (
                list(self.events),
                "".join(self.stdout_chunks),
                "".join(self.stderr_chunks),
            )


_handles: dict[uuid.UUID, _Handle] = {}
_handles_lock = threading.Lock()

_pool = ThreadPoolExecutor(
    max_workers=settings.execution_max_concurrent, thread_name_prefix="pw-exec"
)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def validate_file_path(path: str) -> str | None:
    """通用路径校验（语言无关）：返回错误消息或 None。

    防目录穿越 / 绝对路径 / 反斜杠 / 保留名 / 保留前缀（__pw 为驱动命名空间）。
    """
    if not path or len(path) > 300:
        return f"非法路径（空或超长）：{path!r}"
    if "\\" in path:
        return f"路径必须使用正斜杠：{path}"
    if path.startswith("/"):
        return f"不允许绝对路径：{path}"
    if re.match(r"^[A-Za-z]:", path):
        return f"不允许盘符路径：{path}"
    segments = path.split("/")
    for segment in segments:
        if not segment:
            return f"路径含空段：{path}"
        if segment in (".", ".."):
            return f"路径含相对段（. / ..）：{path}"
        if _INVALID_PATH_CHARS.search(segment):
            return f"路径含非法字符：{path}"
        if segment != segment.strip() or segment.endswith("."):
            return f"段首尾空白或以点结尾：{path}"
        if segment.split(".")[0].upper() in _WINDOWS_RESERVED:
            return f"Windows 保留名：{path}"
    if segments[0] == RESERVED_PREFIX:
        return f"保留命名空间 __pw：{path}"
    return None


def validate_create(payload: ExecutionCreate, runner) -> list[str]:
    """完整请求校验，返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    if not settings.execution_enabled:
        errors.append("远程执行已禁用（PW_EXECUTION_ENABLED）")
        return errors

    if payload.timeout_ms > settings.execution_max_timeout_ms:
        errors.append(
            f"超时上限 {settings.execution_max_timeout_ms}ms，请求 {payload.timeout_ms}ms"
        )

    file_count = len(payload.files)
    if file_count > settings.execution_max_files:
        errors.append(f"文件数超上限（{settings.execution_max_files}）：{file_count}")
    total_bytes = sum(len(content.encode("utf-8")) for content in payload.files.values())
    if total_bytes > settings.execution_max_total_bytes:
        errors.append(
            f"文件总大小超上限（{settings.execution_max_total_bytes // 1024}KB）：{total_bytes // 1024}KB"
        )
    if payload.stdin and len(payload.stdin) > settings.execution_max_stdin_chars:
        errors.append(f"stdin 超上限（{settings.execution_max_stdin_chars} 字符）")

    for path in payload.files:
        err = validate_file_path(path)
        if err:
            errors.append(err)

    if payload.mode == "run":
        if not payload.entry_point:
            errors.append("run 模式必须提供 entryPoint")
        elif payload.entry_point not in payload.files:
            errors.append(f"入口文件不在 files 中：{payload.entry_point}")
    else:
        if not payload.test_paths:
            errors.append("test 模式必须提供 testPaths")
        for path in payload.test_paths:
            if path not in payload.files:
                errors.append(f"测试文件不在 files 中：{path}")

    errors.extend(
        runner.validate_files(
            ExecutionSpecInput(
                exec_id="",
                mode=payload.mode,
                entry_point=payload.entry_point,
                test_paths=list(payload.test_paths),
                files=dict(payload.files),
                stdin=payload.stdin or "",
                timeout_s=payload.timeout_ms / 1000,
            )
        )
    )
    return errors


# --------------------------------------------------------------------------
# 会话生命周期
# --------------------------------------------------------------------------

def create_execution(db: Session, payload: ExecutionCreate, owner_id: str = "dev-user") -> ExecutionSession:
    runner = get_runner(payload.language)
    if runner is None:
        raise ExecutionValidationError(
            f"不支持的语言：{payload.language}（当前支持：{', '.join(list_languages())}）"
        )
    errors = validate_create(payload, runner)
    if errors:
        raise ExecutionValidationError("；".join(errors[:5]))

    # 同步探测沙箱可用性：不可用时创建即失败（明确 503，不排队假成功）。
    ok, reason = get_sandbox_manager().available()
    if not ok:
        raise SandboxUnavailableError(reason)

    row = ExecutionSession(
        owner_id=owner_id,
        project_id=payload.project_id,
        language=payload.language,
        mode=payload.mode,
        status=STATUS_QUEUED,
        entry_point=payload.entry_point,
        test_paths=list(payload.test_paths),
        stdin_text=payload.stdin,
        timeout_ms=payload.timeout_ms,
        code_fingerprint=payload.code_fingerprint,
        files_snapshot=dict(payload.files),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    handle = _Handle()
    with _handles_lock:
        _handles[row.id] = handle
    _pool.submit(_run_worker, row.id, handle)
    return row


def get_execution(db: Session, exec_id: uuid.UUID) -> ExecutionSession:
    row = db.get(ExecutionSession, exec_id)
    if row is None:
        raise ExecutionNotFoundError(exec_id)
    return row


def cancel_execution(db: Session, exec_id: uuid.UUID) -> tuple[ExecutionSession, bool]:
    """请求取消。返回 (会话, 是否已是终态)。运行中的由 worker 收尾。"""
    row = get_execution(db, exec_id)
    already = row.status in TERMINAL_STATUSES
    if not already:
        with _handles_lock:
            handle = _handles.get(exec_id)
        if handle is not None:
            handle.cancel.set()
            # 给 worker 一小段收尾时间（kill 容器 + 落库）。
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                db.refresh(row)
                if row.status in TERMINAL_STATUSES:
                    break
                time.sleep(0.1)
        else:
            # worker 已不在：仅当仍非终态时直接落 cancelled（避免覆盖刚完成的结果）。
            db.refresh(row)
            if row.status not in TERMINAL_STATUSES:
                row.status = STATUS_CANCELLED
                row.cancelled = True
                row.finished_at = utcnow()
                db.commit()
                db.refresh(row)
    db.refresh(row)
    return row, already


def _cap_text(text: str) -> str:
    limit = settings.execution_output_max_chars
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（输出超上限，已截断）"


def _run_worker(exec_id: uuid.UUID, handle: _Handle) -> None:
    """工作线程：状态机推进 + 沙箱运行 + 结果落库 + 事件。"""
    with _session_factory() as db:
        row = db.get(ExecutionSession, exec_id)
        if row is None:
            return
        try:
            _run_worker_inner(db, row, handle)
        except SandboxUnavailableError as exc:
            row.status = STATUS_FAILED
            row.error = f"沙箱不可用：{exc.reason}"
            row.finished_at = utcnow()
            db.commit()
        except Exception as exc:  # 基础设施异常 → failed，绝不伪装成功
            row.status = STATUS_FAILED
            row.error = f"执行服务内部错误：{exc}"
            row.finished_at = utcnow()
            db.commit()
        finally:
            with _handles_lock:
                _handles.pop(exec_id, None)


def _flush_outputs(exec_id: uuid.UUID, handle: _Handle) -> None:
    """周期性把运行中输出写入 DB（轮询可见；SSE 时同一语义换推送）。"""
    last_len = 0
    while not handle.done.is_set():
        time.sleep(0.3)
        events, stdout_text, stderr_text = handle.snapshot()
        if len(events) == last_len:
            continue
        last_len = len(events)
        try:
            with _session_factory() as db:
                row = db.get(ExecutionSession, exec_id)
                if row is None or row.status in TERMINAL_STATUSES:
                    return
                row.events = events
                row.stdout_text = stdout_text
                row.stderr_text = stderr_text
                db.commit()
        except Exception:
            # 刷新失败不影响执行；终态写入会补齐
            continue


def _run_worker_inner(db: Session, row: ExecutionSession, handle: _Handle) -> None:
    runner = get_runner(row.language)
    assert runner is not None  # 创建时已校验

    if handle.cancel.is_set():
        row.status = STATUS_CANCELLED
        row.cancelled = True
        row.finished_at = utcnow()
        db.commit()
        return

    row.status = STATUS_PREPARING
    db.commit()

    spec_input = ExecutionSpecInput(
        exec_id=str(row.id),
        mode=row.mode,
        entry_point=row.entry_point,
        test_paths=list(row.test_paths or []),
        files=dict(row.files_snapshot or {}),
        stdin=row.stdin_text or "",
        timeout_s=row.timeout_ms / 1000,
    )
    sandbox_spec = runner.build_spec(spec_input, spec_input.timeout_s)

    row.status = STATUS_RUNNING
    row.started_at = utcnow()
    row.sandbox_engine = get_sandbox_manager().engine
    row.sandbox_image = sandbox_spec.image
    sandbox_spec.memory_mb = settings.execution_memory_mb
    sandbox_spec.cpus = settings.execution_cpus
    sandbox_spec.pids_limit = settings.execution_pids_limit
    db.commit()

    def _on_output(channel: str, text: str) -> None:
        handle.append_event(channel, text)

    flusher = threading.Thread(target=_flush_outputs, args=(row.id, handle), daemon=True)
    flusher.start()
    try:
        result = get_sandbox_manager().run(sandbox_spec, handle.cancel, on_output=_on_output)
    finally:
        handle.done.set()
        flusher.join(timeout=3)

    # 终态判定（优先级：取消 > 超时 > 基础设施失败 > 协议失败 > 完成）
    outcome = runner.parse_result(result, spec_input)
    if handle.cancel.is_set():
        row.status = STATUS_CANCELLED
        row.cancelled = True
    elif result.timed_out or outcome.timed_out:
        row.status = STATUS_TIMED_OUT
        row.timed_out = True
    elif not result.started:
        row.status = STATUS_FAILED
        row.error = result.stderr.strip()[-600:] or "沙箱启动失败"
    elif outcome.protocol_error:
        row.status = STATUS_FAILED
        row.error = outcome.protocol_error
    else:
        row.status = STATUS_COMPLETED

    row.exit_code = outcome.exit_code
    row.stdout_text = _cap_text(result.stdout)
    row.stderr_text = _cap_text(result.stderr)
    row.diagnostics = outcome.diagnostics
    row.test_results = outcome.test_results
    row.phases = outcome.phases
    row.finished_at = utcnow()
    # 输出事件：流式收集的 + 补齐（假沙箱无回调时从最终输出构造）
    events, _stdout_buf, _stderr_buf = handle.snapshot()
    if not events and (result.stdout or result.stderr):
        if result.stdout:
            handle.append_event("stdout", result.stdout)
        if result.stderr:
            handle.append_event("stderr", result.stderr)
        events, _stdout_buf, _stderr_buf = handle.snapshot()
    row.events = [
        {**event, "text": event["text"][: settings.execution_output_max_chars]}
        for event in events
    ]
    db.commit()

    append_event(
        db,
        event_id=server_event_id("execution-finished", str(row.id)),
        type="execution-finished",
        occurred_at=row.finished_at or utcnow(),
        aggregate_id=f"execution:{row.id}",
        payload={
            "language": row.language,
            "mode": row.mode,
            "status": row.status,
            "exitCode": row.exit_code,
            "timedOut": row.timed_out,
            "cancelled": row.cancelled,
            "sandbox": row.sandbox_engine,
            "trustLevel": TRUST_LEVEL,
            "executionId": str(row.id),
        },
        project_id=row.project_id,
        owner_id=row.owner_id,
    )


# --------------------------------------------------------------------------
# 读取映射
# --------------------------------------------------------------------------

def _aware(dt: datetime) -> datetime:
    """SQLite 不保留时区信息，读回的 naive 时间统一补 UTC。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def to_read_model(row: ExecutionSession, after_seq: int = 0) -> dict:
    started = _aware(row.started_at) if row.started_at else None
    finished = _aware(row.finished_at) if row.finished_at else None
    if started and finished:
        run_ms = int((finished - started).total_seconds() * 1000)
    elif started:
        run_ms = int((utcnow() - started).total_seconds() * 1000)
    else:
        run_ms = 0
    events = [event for event in (row.events or []) if event.get("seq", 0) > after_seq]
    return {
        "id": row.id,
        "language": row.language,
        "mode": row.mode,
        "status": row.status,
        "entry_point": row.entry_point,
        "test_paths": list(row.test_paths or []),
        "timeout_ms": row.timeout_ms,
        "code_fingerprint": row.code_fingerprint,
        "project_id": row.project_id,
        "exit_code": row.exit_code,
        "timed_out": row.timed_out,
        "cancelled": row.cancelled,
        "error": row.error,
        "stdout": row.stdout_text or "",
        "stderr": row.stderr_text or "",
        "events": events,
        "diagnostics": row.diagnostics or [],
        "test_results": row.test_results,
        "phases": row.phases or [],
        "sandbox": {
            "engine": row.sandbox_engine,
            "image": row.sandbox_image,
            "trustLevel": TRUST_LEVEL,
        },
        "queued_at": row.queued_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "run_time_ms": run_ms,
    }


def cleanup_stale_sandboxes() -> int:
    """服务启动时清理遗留沙箱（尽力而为，不阻塞启动）。"""
    try:
        return get_sandbox_manager().cleanup_stale()
    except Exception:
        return 0
