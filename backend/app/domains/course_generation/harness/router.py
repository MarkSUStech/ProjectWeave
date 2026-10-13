"""Course Development Session REST API（P8.2.3，D48）。"""

from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.course_generation.harness import service
from app.domains.course_generation.lessons.lesson_publisher import ReleaseError

router = APIRouter(prefix="/course-dev-sessions", tags=["course-harness"])


def _parse_id(value: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="会话不存在") from None


@router.post("", status_code=201)
def create_session(generationId: str, releaseId: str | None = None,
                   db: Session = Depends(get_db)) -> dict:
    try:
        row = service.start_session(db, generationId, releaseId)
    except service.HarnessSessionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return {"sessionId": str(row.id), "state": row.state}


@router.get("/{session_id}")
def get_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return service.session_status(db, session_id)
    except service.HarnessSessionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.post("/{session_id}/run")
def run_slice(session_id: str, db: Session = Depends(get_db)) -> dict:
    """执行一个开发 slice（当前任务直到完成/预算/暂停；409=已有 worker）。"""
    _parse_id(session_id)
    try:
        return service.run_slice(_parse_id(session_id))
    except service.HarnessSessionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.post("/{session_id}/pause")
def pause(session_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return service.pause_session(db, session_id)
    except service.HarnessSessionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.post("/{session_id}/cancel")
def cancel(session_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return service.cancel_session(db, session_id)
    except service.HarnessSessionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
