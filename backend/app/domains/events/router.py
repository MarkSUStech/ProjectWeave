"""事件路由：批量上报（客户端事件）与查询。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.events import service
from app.domains.events.schemas import (
    EventBatch,
    EventIngestResult,
    EventList,
    EventRead,
)
from app.domains.events.service import EventError

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventIngestResult, summary="批量上报学习事件（幂等）")
def ingest_events(payload: EventBatch, db: Session = Depends(get_db)) -> EventIngestResult:
    accepted = 0
    duplicated = 0
    try:
        for event in payload.events:
            written = service.append_event(
                db,
                event_id=event.eventId,
                type=event.type,
                occurred_at=event.occurredAt,
                aggregate_id=event.aggregateId,
                payload=event.payload,
                project_id=event.projectId,
            )
            if written:
                accepted += 1
            else:
                duplicated += 1
    except EventError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return EventIngestResult(accepted=accepted, duplicated=duplicated)


@router.get("", response_model=EventList, summary="学习事件查询（按项目/类型过滤）")
def list_events(
    projectId: str | None = Query(default=None),
    type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> EventList:
    try:
        events = service.list_events(db, project_id=projectId, type=type, limit=limit)
    except EventError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return EventList(
        items=[EventRead.model_validate(e) for e in events], total=len(events)
    )
