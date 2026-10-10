"""调试会话服务（P4.5a）：生命周期编排 + DAP 交互 + 快照落库。

线程模型（防死锁关键）：
- DapClient 读线程只做非阻塞回调（入队 + 置位等待者）；
- 每个会话一个**串行线程**，独占全部 DAP 请求（初始化流程 / 事件处理 /
  指令执行共用命令+事件队列），API 线程仅入队并等待回执；
- 因此 on_event 回调内绝不会发起 DAP 请求（否则等待响应的正是自己阻塞的读线程）。

状态机：CREATING → BUILDING → CONFIGURING → RUNNING ⇄ PAUSED → TERMINATED。
快照（位置/线程/栈帧/作用域变量）全部来自真实 DAP 响应并按暂停刷新落库。
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.domains.debugging.dap_client import DapClient, DapError
from app.domains.debugging.debug_sandbox import (
    DEBUG_BUILD_FLAGS,
    DEBUGGER_PROFILE,
    DockerDebugSandbox,
    build_files_archive,
)
from app.domains.debugging.models import DEBUG_STATUSES, DebugSession
from app.domains.debugging.schemas import BreakpointSpec, DebugSessionCreate
from app.domains.events.service import append_event, server_event_id
from app.domains.executions.languages.cpp_driver import select_run_sources
from app.domains.executions.languages.cpp_runner import parse_build_diagnostics
from app.domains.executions.service import validate_file_path
from app.domains.executions.sandbox.base import SandboxUnavailableError

WORKDIR_PREFIX = "/sandbox/work/"
BINARY = "/sandbox/work/__pw_build/app"

MAX_STACK_FRAMES = 50
MAX_VARIABLES_PER_SCOPE = 100
MAX_VALUE_CHARS = 300
MAX_DAP_LOG = 200
STEP_SETTLE_TIMEOUT_S = 20.0


class DebugValidationError(ValueError):
    """请求不合法（422）。"""


class DebugNotFoundError(KeyError):
    """会话不存在（404）。"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 注入点

_provider = DockerDebugSandbox()
_provider_lock = threading.Lock()
_session_factory = SessionLocal


def set_debug_provider(provider) -> None:
    global _provider
    with _provider_lock:
        _provider = provider


def get_debug_provider():
    with _provider_lock:
        return _provider


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


# ---------------------------------------------------------------- 句柄

class _Command:
    def __init__(self, name: str, payload: dict) -> None:
        self.name = name
        self.payload = payload
        self.done = threading.Event()
        self.result: dict = {}
        self.error: str | None = None


class _Handle:
    def __init__(self, container_name: str) -> None:
        self.container_name = container_name
        self.lock = threading.Lock()
        self.command_queue: queue.Queue[_Command | None] = queue.Queue()
        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.stop_requested = threading.Event()
        self.initialized = threading.Event()
        self.stopped_signal = threading.Event()
        self.terminated = threading.Event()
        self.dap: DapClient | None = None
        self.dap_log: list[dict] = []
        self.primary_thread_id: int | None = None
        self.last_activity = time.monotonic()
        self.hard_deadline = time.monotonic() + _hard_timeout_s()
        # 看门狗请求的超时原因（idle/hard），主循环 stop 分支据此区分 end_reason
        self.timeout_reason: str | None = None
        self.watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog.start()

    def _watchdog_loop(self) -> None:
        """独立看门狗：空闲/硬超时判定不依赖主循环节奏（断线回收保障）。"""
        while not self.terminated.wait(timeout=1.0):
            now = time.monotonic()
            reason = None
            if now > self.hard_deadline:
                reason = "调试会话达到硬超时上限"
            elif now - self.last_activity > _idle_timeout_s():
                reason = "调试会话空闲超时（无客户端活动）"
            if reason is not None and not self.stop_requested.is_set():
                self.timeout_reason = reason
                self.stop_requested.set()
                self.command_queue.put(None)
                return

    def log_dap(self, kind: str, detail: str) -> None:
        self.dap_log.append({"at": utcnow().isoformat(), "kind": kind, "detail": detail[:200]})
        if len(self.dap_log) > MAX_DAP_LOG:
            del self.dap_log[: len(self.dap_log) - MAX_DAP_LOG]

    def touch(self) -> None:
        self.last_activity = time.monotonic()


_handles: dict[uuid.UUID, _Handle] = {}
_handles_lock = threading.Lock()


# ---------------------------------------------------------------- 校验


def _validate_create(payload: DebugSessionCreate) -> list[str]:
    errors: list[str] = []
    if not settings.execution_enabled:
        errors.append("远程执行已禁用（PW_EXECUTION_ENABLED）")
        return errors
    if len(payload.files) > settings.execution_max_files:
        errors.append(f"文件数超上限（{settings.execution_max_files}）：{len(payload.files)}")
    total = sum(len(c.encode("utf-8")) for c in payload.files.values())
    if total > settings.execution_max_total_bytes:
        errors.append("文件总大小超上限")
    for path in payload.files:
        err = validate_file_path(path)
        if err:
            errors.append(err)
    if not payload.entry_point.endswith((".cpp", ".cc", ".cxx")):
        errors.append("调试入口必须是 C++ 源文件（.cpp/.cc/.cxx）")
    elif payload.entry_point not in payload.files:
        errors.append(f"入口文件不在 files 中：{payload.entry_point}")
    for bp in payload.breakpoints:
        if bp.path not in payload.files:
            errors.append(f"断点文件不在 files 中：{bp.path}")
        if any(line < 1 or line > 100_000 for line in bp.lines):
            errors.append(f"断点行号非法：{bp.path}")
    return errors


# ---------------------------------------------------------------- 创建/查询/停止


def create_debug_session(db: Session, payload: DebugSessionCreate, owner_id: str = "dev-user") -> DebugSession:
    errors = _validate_create(payload)
    if errors:
        raise DebugValidationError("；".join(errors[:5]))
    ok, reason = get_debug_provider().available()
    if not ok:
        raise SandboxUnavailableError(reason)

    row = DebugSession(
        owner_id=owner_id,
        project_id=payload.project_id,
        language="cpp",
        status="creating",
        entry_point=payload.entry_point,
        files_snapshot=dict(payload.files),
        breakpoints=[bp.model_dump(by_alias=True) for bp in payload.breakpoints],
        code_fingerprint=payload.code_fingerprint,
        debugger_profile=DEBUGGER_PROFILE,
        sandbox_engine="docker",
        sandbox_image=get_debug_provider().image,
        idle_deadline_ms=_idle_deadline_wallclock_ms(),
        hard_deadline_ms=_hard_deadline_wallclock_ms(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    handle = _Handle(container_name=f"pw-dbg-{str(row.id)[:12]}")
    with _handles_lock:
        _handles[row.id] = handle
    threading.Thread(
        target=_session_main, args=(row.id, handle, payload), daemon=True, name=f"pw-dbg-{row.id.hex[:8]}"
    ).start()
    return row


def _idle_timeout_s() -> float:
    return float(getattr(settings, "debug_idle_timeout_seconds", 600))


def _hard_timeout_s() -> float:
    return float(getattr(settings, "debug_hard_timeout_seconds", 1800))


def get_debug_session(db: Session, session_id: uuid.UUID) -> DebugSession:
    row = db.get(DebugSession, session_id)
    if row is None:
        raise DebugNotFoundError(session_id)
    return row


def get_snapshot(db: Session, session_id: uuid.UUID) -> DebugSession:
    row = get_debug_session(db, session_id)
    with _handles_lock:
        handle = _handles.get(session_id)
    if handle is not None:
        handle.touch()
    return row


def send_command(db: Session, session_id: uuid.UUID, command: str, payload: dict) -> dict:
    with _handles_lock:
        handle = _handles.get(session_id)
    if handle is None:
        row = get_debug_session(db, session_id)
        if row.status == "terminated":
            if command == "stop":
                return {"status": "terminated"}  # 幂等：已结束的会话停止=成功
            raise DebugValidationError("调试会话已结束")
        raise DebugNotFoundError(session_id)
    handle.touch()
    if command == "stop":
        handle.stop_requested.set()
        handle.command_queue.put(None)
        # 等待会话线程收尾（最多硬超时余量的一小段）
        for _ in range(100):
            if handle.terminated.wait(0.1):
                break
        return {"status": "terminated"}

    item = _Command(command, payload)
    handle.command_queue.put(item)
    if not item.done.wait(timeout=STEP_SETTLE_TIMEOUT_S + 15):
        raise DebugValidationError("调试指令超时未完成")
    if item.error:
        raise DebugValidationError(item.error)
    return item.result


def expand_variables(db: Session, session_id: uuid.UUID, variables_reference: int) -> dict:
    """懒加载：按 DAP variablesReference 展开变量（复杂对象）。"""
    with _handles_lock:
        handle = _handles.get(session_id)
    if handle is None:
        raise DebugNotFoundError(session_id)
    handle.touch()
    item = _Command("variables", {"variablesReference": variables_reference})
    handle.command_queue.put(item)
    if not item.done.wait(timeout=15):
        raise DebugValidationError("变量查询超时")
    if item.error:
        raise DebugValidationError(item.error)
    return item.result


def stop_debug_session(db: Session, session_id: uuid.UUID) -> DebugSession:
    try:
        send_command(db, session_id, "stop", {})
    except DebugNotFoundError:
        row = get_debug_session(db, session_id)
        if row.status != "terminated":
            row.status = "terminated"
            row.end_reason = "cancelled"
            row.finished_at = utcnow()
            db.commit()
            db.refresh(row)
        return row
    db.expire_all()
    return get_debug_session(db, session_id)


def cleanup_stale_debug() -> int:
    """启动时清理遗留调试容器 + 把悬挂的未终态会话行标记终止。"""
    removed = 0
    try:
        removed = get_debug_provider().cleanup_stale()
    except Exception:
        removed = 0
    try:
        with _session_factory() as db2:
            for row in db2.query(DebugSession).filter(
                DebugSession.status.in_(["creating", "building", "configuring", "running", "paused"])
            ).all():
                row.status = "terminated"
                row.end_reason = "internal-error"
                row.error = "服务重启：会话未正常收尾（容器已清理）"
                row.finished_at = utcnow()
            db2.commit()
    except Exception:
        pass
    return removed


# ---------------------------------------------------------------- 会话线程


def _session_main(session_id: uuid.UUID, handle: _Handle, payload: DebugSessionCreate) -> None:
    try:
        _session_main_inner(session_id, handle, payload)
    except Exception as exc:  # 任何异常 → 终态，绝不悬挂
        _finalize(handle, session_id, "internal-error", error=f"调试会话内部错误：{exc}")
    finally:
        with _handles_lock:
            _handles.pop(session_id, None)
        handle.terminated.set()


def _persist(session_id: uuid.UUID, **fields) -> None:
    try:
        with _session_factory() as db:
            row = db.get(DebugSession, session_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        pass


def _finalize(handle: _Handle, session_id: uuid.UUID, reason: str, error: str | None = None) -> None:
    if handle.dap is not None:
        try:
            handle.dap.close()
        except Exception:
            pass
        handle.dap = None
    get_debug_provider().destroy(handle.container_name)
    try:
        with _session_factory() as db:
            row = db.get(DebugSession, session_id)
            if row is not None and row.status != "terminated":
                row.status = "terminated"
                row.end_reason = reason
                row.error = error
                row.finished_at = utcnow()
                row.dap_log = list(handle.dap_log)
                db.commit()
                append_event(
                    db,
                    event_id=server_event_id("debug-session-finished", str(session_id)),
                    type="debug-session-finished",
                    occurred_at=utcnow(),
                    aggregate_id=f"debug:{session_id}",
                    payload={
                        "debugSessionId": str(session_id),
                        "endReason": reason,
                        "language": "cpp",
                        "debugger": DEBUGGER_PROFILE,
                        "projectId": str(row.project_id) if row.project_id else None,
                    },
                    project_id=row.project_id,
                    owner_id=row.owner_id,
                )
    except Exception:
        pass


def _dap_call(handle: _Handle, command: str, arguments: dict | None = None, timeout: float = 15.0) -> dict:
    if handle.dap is None:
        raise DapError("DAP 通道未建立")
    return handle.dap.send_request(command, arguments, timeout=timeout)


def _norm_file(path: str | None) -> str | None:
    if path is None:
        return None
    if path.startswith(WORKDIR_PREFIX):
        return path[len(WORKDIR_PREFIX):]
    return path


def _fetch_pause_snapshot(handle: _Handle, stopped_thread_id: int | None = None) -> dict:
    """暂停时抓取完整快照：线程 → 栈帧 → 顶帧作用域与变量（真实 DAP 数据）。

    步进/断点命中的瞬间 stackTrace 可能返回空栈（调试器尚未同步），
    短间隔重试最多 3 次——绝不用空数据冒充快照。
    """
    threads_body = _dap_call(handle, "threads", {}, timeout=10)
    threads = [
        {"id": t.get("id"), "name": t.get("name", ""), "isPrimary": idx == 0}
        for idx, t in enumerate(threads_body.get("threads", [])[:20])
    ]
    if not threads:
        return {}
    thread_ids = {t["id"] for t in threads}
    thread_id = (
        stopped_thread_id if stopped_thread_id in thread_ids
        else handle.primary_thread_id if handle.primary_thread_id in thread_ids
        else threads[0]["id"]
    )
    handle.primary_thread_id = thread_id

    frames: list[dict] = []
    for _attempt in range(3):
        stack_body = _dap_call(handle, "stackTrace", {"threadId": thread_id, "levels": MAX_STACK_FRAMES}, timeout=10)
        raw_frames = stack_body.get("stackFrames", [])[:MAX_STACK_FRAMES]
        if raw_frames:
            frames = [
                {
                    "id": frame.get("id"),
                    "name": frame.get("name", ""),
                    "file": _norm_file((frame.get("source") or {}).get("path")),
                    "line": frame.get("line"),
                    "column": frame.get("column"),
                }
                for frame in raw_frames
            ]
            break
        time.sleep(0.15)

    snapshot: dict = {"threads": threads, "threadId": thread_id, "stackFrames": frames}

    top = frames[0] if frames else None
    if top is not None:
        location = {
            "file": top["file"],
            "line": top["line"],
            "column": top["column"],
            "frameName": top["name"],
        }
        snapshot["location"] = location
        try:
            scopes_body = _dap_call(handle, "scopes", {"frameId": top["id"]}, timeout=10)
            scopes = []
            for scope in scopes_body.get("scopes", []):
                entry = {
                    "name": scope.get("name", ""),
                    "variablesReference": scope.get("variablesReference", 0),
                    "expensive": bool(scope.get("expensive", False)),
                    "variables": [],
                }
                # 顶帧的非昂贵作用域立即取一层变量；复杂对象懒加载（variablesReference>0）
                if not entry["expensive"] and "egisters" not in entry["name"]:
                    try:
                        var_body = _dap_call(handle, "variables", {"variablesReference": entry["variablesReference"]}, timeout=10)
                        entry["variables"] = [
                            {
                                "name": v.get("name", ""),
                                "value": str(v.get("value", ""))[:MAX_VALUE_CHARS],
                                "type": v.get("type"),
                                "variablesReference": v.get("variablesReference", 0),
                            }
                            for v in var_body.get("variables", [])[:MAX_VARIABLES_PER_SCOPE]
                        ]
                    except DapError:
                        pass
                scopes.append(entry)
            snapshot["scopes"] = scopes
        except DapError:
            snapshot["scopes"] = []
    return snapshot


def _persist_snapshot(handle: _Handle, session_id: uuid.UUID, status: str, reason: str | None, snapshot: dict) -> None:
    fields = {
        "status": status,
        "stop_reason": reason,
        "threads": snapshot.get("threads", []),
        "stack_frames": snapshot.get("stackFrames", []),
        "scopes": snapshot.get("scopes", []),
        "current_location": snapshot.get("location"),
        "dap_log": list(handle.dap_log),
    }
    if status == "paused":
        fields["paused_at"] = utcnow()
    try:
        with _session_factory() as db:
            row = db.get(DebugSession, session_id)
            if row is None or row.status == "terminated":
                return
            for key, value in fields.items():
                setattr(row, key, value)
            row.idle_deadline_ms = _idle_deadline_wallclock_ms()
            db.commit()
    except Exception:
        pass


def _session_main_inner(session_id: uuid.UUID, handle: _Handle, payload: DebugSessionCreate) -> None:
    provider = get_debug_provider()
    files = dict(payload.files)

    # ---- BUILDING：容器 + 文件 + 调试构建（复用 CppRunner 源集策略与诊断解析）
    _persist(session_id, status="building")
    provider.start(handle.container_name)
    provider.put_files(handle.container_name, build_files_archive(files))
    sources = select_run_sources(files, payload.entry_point)
    build_cmd = ["clang++", *DEBUG_BUILD_FLAGS, "-o", BINARY, *sources]
    code, stdout, stderr = provider.run_build(handle.container_name, build_cmd, timeout_s=120.0)
    diagnostics = parse_build_diagnostics(stdout or stderr)
    if code != 0:
        _persist(session_id, status="terminated", end_reason="build-failed",
                 build_diagnostics=diagnostics, build_stdout=(stdout or stderr)[:4000],
                 finished_at=utcnow())
        append_finished_event(session_id, "build-failed")
        provider.destroy(handle.container_name)
        return
    _persist(session_id, build_stdout=(stdout or "")[:2000])

    # ---- CONFIGURING：DAP 通道 + launch + 断点
    _persist(session_id, status="configuring", started_at=utcnow())

    def _on_event(message: dict) -> None:
        # 只做非阻塞动作（读线程上下文禁止 DAP 请求）
        handle.log_dap("event", str(message.get("event")))
        name = message.get("event")
        if name == "initialized":
            handle.initialized.set()
        handle.event_queue.put(message)

    handle.dap = DapClient(provider.dap_argv(handle.container_name), _on_event)
    try:
        _dap_call(handle, "initialize", {
            "adapterID": "lldb", "linesStartAt1": True, "columnsStartAt1": True,
            "pathFormat": "path",
        }, timeout=25)
        _dap_call(handle, "launch", {
            "program": BINARY,
            "cwd": "/sandbox/work",
            "stopOnEntry": payload.stop_on_entry,
            "console": "internalConsole",
        }, timeout=30)
        if not handle.initialized.wait(15):
            raise DapError("未收到 initialized 事件")
        verified = _apply_breakpoints(handle, payload.breakpoints)
        _persist(session_id, verified_breakpoints=verified)
        _dap_call(handle, "configurationDone", {}, timeout=15)
    except DapError as exc:
        _finalize(handle, session_id, "debugger-error", error=f"调试器启动失败：{exc}")
        return
    _persist(session_id, status="running")

    # ---- 事件/指令/超时主循环（看门狗负责超时判定；事件即使无指令也及时落库）
    while not handle.terminated.is_set():
        if handle.stop_requested.is_set():
            try:
                _dap_call(handle, "disconnect", {"terminateDebuggee": True}, timeout=10)
            except DapError:
                pass
            if handle.timeout_reason is not None:
                _finalize(handle, session_id, "timeout", error=handle.timeout_reason)
            else:
                _finalize(handle, session_id, "cancelled")
            return

        now = time.monotonic()

        try:
            item = handle.command_queue.get(timeout=0.25)
        except queue.Empty:
            item = None
        if item is None:
            _drain_events(handle, session_id)
            if handle.terminated.is_set():
                return
            # DAP 通道死亡（调试器退出/docker exec 断开）→ 回收
            if handle.dap is not None and not handle.dap.alive:
                _finalize(handle, session_id, "debugger-error", error="DAP 通道意外关闭")
                return
            continue
        try:
            item.result = _execute_command(handle, session_id, item)
        except DapError as exc:
            item.error = f"调试指令失败：{exc}"
        except Exception as exc:
            item.error = f"调试指令异常：{exc}"
        finally:
            item.done.set()


def _hard_deadline_wallclock_ms() -> int:
    return int((utcnow().timestamp() + _hard_timeout_s()) * 1000)


def _idle_deadline_wallclock_ms() -> int:
    return int((utcnow().timestamp() + _idle_timeout_s()) * 1000)


def append_finished_event(session_id: uuid.UUID, reason: str) -> None:
    try:
        with _session_factory() as db:
            row = db.get(DebugSession, session_id)
            append_event(
                db,
                event_id=server_event_id("debug-session-finished", str(session_id), reason),
                type="debug-session-finished",
                occurred_at=utcnow(),
                aggregate_id=f"debug:{session_id}",
                payload={
                    "debugSessionId": str(session_id),
                    "endReason": reason,
                    "language": "cpp",
                    "debugger": DEBUGGER_PROFILE,
                    "projectId": str(row.project_id) if row and row.project_id else None,
                },
                project_id=row.project_id if row else None,
                owner_id=row.owner_id if row else "dev-user",
            )
    except Exception:
        pass


def _apply_breakpoints(handle: _Handle, breakpoints: list[BreakpointSpec]) -> list[dict]:
    """把项目相对路径断点发到 DAP（容器内绝对路径），返回验证结果。"""
    verified: list[dict] = []
    for bp in breakpoints:
        response = _dap_call(handle, "setBreakpoints", {
            "source": {"name": bp.path.rsplit("/", 1)[-1], "path": f"{WORKDIR_PREFIX}{bp.path}"},
            "lines": list(bp.lines),
            "breakpoints": [{"line": line} for line in bp.lines],
        }, timeout=15)
        requested = {line: None for line in bp.lines}
        for entry in response.get("breakpoints", []):
            requested[entry.get("line", 0)] = entry
        for line in bp.lines:
            entry = requested.get(line) or {}
            verified.append({
                "path": bp.path,
                "line": line,
                "verified": bool(entry.get("verified", False)),
                "message": entry.get("message"),
            })
    return verified


def _execute_command(handle: _Handle, session_id: uuid.UUID, item: _Command) -> dict:
    command = item.name
    payload = item.payload

    if command == "setBreakpoints":
        specs = [BreakpointSpec.model_validate(bp) for bp in payload.get("breakpoints", [])]
        verified = _apply_breakpoints(handle, specs)
        _persist(session_id, verified_breakpoints=verified)
        return {"breakpoints": verified}

    if command == "variables":
        body = _dap_call(handle, "variables", {
            "variablesReference": payload.get("variablesReference", 0),
        }, timeout=15)
        return {"variables": [
            {
                "name": v.get("name", ""),
                "value": str(v.get("value", ""))[:MAX_VALUE_CHARS],
                "type": v.get("type"),
                "variablesReference": v.get("variablesReference", 0),
            }
            for v in body.get("variables", [])[:MAX_VARIABLES_PER_SCOPE]
        ]}

    thread_id = payload.get("threadId") or handle.primary_thread_id
    if thread_id is None:
        threads = _dap_call(handle, "threads", {}, timeout=10).get("threads", [])
        thread_id = threads[0]["id"] if threads else None
    if thread_id is None:
        raise DapError("无线程可操作")

    if command == "pause":
        _dap_call(handle, "pause", {"threadId": thread_id}, timeout=10)
        handle.stopped_signal.wait(timeout=STEP_SETTLE_TIMEOUT_S)
        _drain_events(handle, session_id)
        return {}

    if command in ("continue", "next", "stepIn", "stepOut"):
        handle.stopped_signal.clear()
        _dap_call(handle, command, {"threadId": thread_id}, timeout=10)
        if command != "continue":
            # 单步等待新的 stopped（步进很快完成；超时则如实返回当前状态）
            handle.stopped_signal.wait(timeout=STEP_SETTLE_TIMEOUT_S)
        else:
            # continue：若程序很快再次停止（下一断点），等一小段让调用方拿到已结算快照
            handle.stopped_signal.wait(timeout=3.0)
        _drain_events(handle, session_id)
        return {}

    raise DapError(f"未知指令：{command}")


def _drain_events(handle: _Handle, session_id: uuid.UUID) -> None:
    """处理积压 DAP 事件（stopped/continued/terminated 等）。"""
    while True:
        try:
            message = handle.event_queue.get_nowait()
        except queue.Empty:
            break
        name = message.get("event")
        body = message.get("body") or {}
        if name == "stopped":
            snapshot = {}
            try:
                snapshot = _fetch_pause_snapshot(handle, body.get("threadId"))
            except DapError as exc:
                handle.log_dap("error", f"快照抓取失败：{exc}")
            _persist_snapshot(handle, session_id, "paused", body.get("reason", "unknown"), snapshot)
            handle.stopped_signal.set()
        elif name == "continued":
            _persist_snapshot(handle, session_id, "running", None, {})
        elif name in ("terminated", "exited"):
            _finalize(handle, session_id, "completed")
            handle.terminated.set()
            return
        elif name == "thread":
            handle.log_dap("thread", str(body))
