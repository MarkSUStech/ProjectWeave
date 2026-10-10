"""执行会话 REST API（P4.2b）。

- POST /api/v1/executions           创建（202 排队；沙箱不可用 503；校验失败 422）
- GET  /api/v1/executions/{id}      查询（?afterSeq= 增量读取事件，轮询用；
                                     SSE/WebSocket 预留：同一查询语义可直接换推送）
- POST /api/v1/executions/{id}/cancel 取消（幂等；终态时返回当前状态）
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.executions import service
from app.domains.executions.sandbox.base import SandboxUnavailableError
from app.domains.executions.schemas import (
    ExecutionCancelled,
    ExecutionCreated,
    ExecutionCreate,
    ExecutionRead,
)

router = APIRouter(prefix="/executions", tags=["executions"])


def _parse_exec_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="执行会话不存在") from None


@router.post("", response_model=ExecutionCreated, status_code=202)
def create_execution(
    payload: ExecutionCreate,
    db: Session = Depends(get_db),
) -> ExecutionCreated:
    try:
        row = service.create_execution(db, payload)
    except service.ExecutionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SandboxUnavailableError as exc:
        detail = exc.reason if not exc.hint else f"{exc.reason}（{exc.hint}）"
        raise HTTPException(status_code=503, detail=detail) from None
    return ExecutionCreated(id=row.id, status=row.status)


@router.get("/{exec_id}", response_model=ExecutionRead)
def get_execution(
    exec_id: str,
    afterSeq: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ExecutionRead:
    exec_uuid = _parse_exec_id(exec_id)
    try:
        row = service.get_execution(db, exec_uuid)
    except service.ExecutionNotFoundError:
        raise HTTPException(status_code=404, detail="执行会话不存在") from None
    return ExecutionRead.model_validate(service.to_read_model(row, after_seq=afterSeq))


@router.post("/{exec_id}/cancel", response_model=ExecutionCancelled)
def cancel_execution(
    exec_id: str,
    db: Session = Depends(get_db),
) -> ExecutionCancelled:
    exec_uuid = _parse_exec_id(exec_id)
    try:
        row, already = service.cancel_execution(db, exec_uuid)
    except service.ExecutionNotFoundError:
        raise HTTPException(status_code=404, detail="执行会话不存在") from None
    return ExecutionCancelled(id=row.id, status=row.status, already_finished=already)
