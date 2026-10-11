"""调试会话 REST API（P4.5a）。

- POST   /api/v1/debug-sessions                 创建（201；编译失败→terminated/build-failed）
- GET    /api/v1/debug-sessions/{id}            快照（状态/位置/线程/栈帧/作用域变量）
- POST   /api/v1/debug-sessions/{id}/commands   结构化调试指令（白名单，非任意 LLDB 命令）
- GET    /api/v1/debug-sessions/{id}/variables  懒加载变量（按 variablesReference）
- DELETE /api/v1/debug-sessions/{id}            停止并回收容器
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.debugging import service
from app.domains.debugging.schemas import (
    DebugCommandInput,
    FrameVariablesRead,
    DebugSessionCreated,
    DebugSessionCreate,
    DebugSnapshotRead,
    DebugVariablesQuery,
)
from app.domains.executions.sandbox.base import SandboxUnavailableError

router = APIRouter(prefix="/debug-sessions", tags=["debugging"])


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None


@router.post("", response_model=DebugSessionCreated, status_code=201)
def create_session(
    payload: DebugSessionCreate,
    db: Session = Depends(get_db),
) -> DebugSessionCreated:
    try:
        row = service.create_debug_session(db, payload)
    except service.DebugValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SandboxUnavailableError as exc:
        detail = exc.reason if not exc.hint else f"{exc.reason}（{exc.hint}）"
        raise HTTPException(status_code=503, detail=detail) from None
    return DebugSessionCreated(id=row.id, status=row.status)


@router.get("/{session_id}", response_model=DebugSnapshotRead)
def get_snapshot(
    session_id: str,
    db: Session = Depends(get_db),
) -> DebugSnapshotRead:
    try:
        row = service.get_snapshot(db, _parse_id(session_id))
    except service.DebugNotFoundError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None
    return _to_read(row)


@router.post("/{session_id}/commands", response_model=DebugSnapshotRead)
def send_command(
    session_id: str,
    payload: DebugCommandInput,
    db: Session = Depends(get_db),
) -> DebugSnapshotRead:
    session_uuid = _parse_id(session_id)
    try:
        service.send_command(db, session_uuid, payload.command, payload.model_dump(by_alias=True))
    except service.DebugValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except service.DebugNotFoundError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None
    db.expire_all()
    row = service.get_debug_session(db, session_uuid)
    return _to_read(row)


@router.get("/{session_id}/variables")
def expand_variables(
    session_id: str,
    variablesReference: int = Query(ge=0),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return service.expand_variables(db, _parse_id(session_id), variablesReference)
    except service.DebugValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except service.DebugNotFoundError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None


@router.get("/{session_id}/frames/{frame_id}/variables", response_model=FrameVariablesRead)
def frame_variables(
    session_id: str,
    frame_id: int,
    db: Session = Depends(get_db),
) -> FrameVariablesRead:
    """按栈帧取作用域变量（白名单；携带 pauseSeq——旧代次缓存不得复用）。"""
    session_uuid = _parse_id(session_id)
    try:
        result = service.send_command(
            db, session_uuid, "frameVariables", {"frameId": frame_id}
        )
    except service.DebugValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except service.DebugNotFoundError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None
    return FrameVariablesRead.model_validate(result)


@router.delete("/{session_id}", status_code=200, response_model=DebugSnapshotRead)
def stop_session(session_id: str, db: Session = Depends(get_db)) -> DebugSnapshotRead:
    session_uuid = _parse_id(session_id)
    try:
        row = service.stop_debug_session(db, session_uuid)
    except service.DebugNotFoundError:
        raise HTTPException(status_code=404, detail="调试会话不存在") from None
    return _to_read(row)


def _to_read(row) -> DebugSnapshotRead:
    return DebugSnapshotRead(
        id=row.id,
        language=row.language,
        status=row.status,
        endReason=row.end_reason,
        entryPoint=row.entry_point,
        projectId=row.project_id,
        codeFingerprint=row.code_fingerprint,
        debuggerProfile=row.debugger_profile,
        location=row.current_location or None,
        stopReason=row.stop_reason,
        pauseSeq=row.pause_seq or 0,
        threadId=row.snapshot_thread_id,
        pointerGraph=row.pointer_graph,
        threads=row.threads or [],
        stackFrames=row.stack_frames or [],
        scopes=row.scopes or [],
        breakpoints=row.verified_breakpoints or [],
        buildDiagnostics=row.build_diagnostics or [],
        buildStdout=row.build_stdout or "",
        error=row.error,
        programOutput=row.program_output or [],
        dapLog=row.dap_log or [],
        sandbox={"engine": row.sandbox_engine, "image": row.sandbox_image},
        createdAt=row.created_at,
        startedAt=row.started_at,
        pausedAt=row.paused_at,
        finishedAt=row.finished_at,
    )
