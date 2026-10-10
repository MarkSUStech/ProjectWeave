"""事件追加与查询：幂等去重、白名单校验、aggregate 序列分配。"""

import uuid as uuid_module
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.events.models import (
    EVENT_TYPES,
    MAX_PAYLOAD_CHARS,
    LearningEvent,
)

VALID_EVENT_TYPES = EVENT_TYPES


class EventError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


def _validate_uuid(value: str) -> uuid_module.UUID:
    try:
        return uuid_module.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise EventError(f"非法 UUID：{value}") from None


def append_event(
    db: Session,
    *,
    event_id: str,
    type: str,
    occurred_at: datetime,
    aggregate_id: str,
    payload: dict,
    project_id=None,
    owner_id: str = "dev-user",
) -> bool:
    """追加一条事件；eventId 已存在则跳过（幂等）。返回是否实际写入。

    sequence 按 (aggregate_id) 单调递增，由服务端分配。
    """
    if type not in VALID_EVENT_TYPES:
        raise EventError(f"不允许的事件类型：{type}")
    if not isinstance(payload, dict):
        raise EventError("payload 必须是对象")
    if len(str(payload)) > MAX_PAYLOAD_CHARS:
        raise EventError(f"payload 过大（上限 {MAX_PAYLOAD_CHARS} 字符）")
    if db.query(LearningEvent).filter(LearningEvent.event_id == event_id).first() is not None:
        return False

    sequence = (
        db.scalar(
            select(func.max(LearningEvent.sequence)).where(
                LearningEvent.aggregate_id == aggregate_id
            )
        )
        or 0
    ) + 1
    db.add(
        LearningEvent(
            event_id=event_id,
            type=type,
            occurred_at=occurred_at,
            owner_id=owner_id,
            project_id=project_id,
            aggregate_id=aggregate_id,
            sequence=sequence,
            payload=payload,
        )
    )
    db.commit()
    return True


def server_event_id(*parts: str) -> str:
    """服务端事件的确定性 id：同参数重复追加会被幂等跳过。"""
    digest = uuid_module.uuid5(uuid_module.NAMESPACE_URL, "/".join(map(str, parts)))
    return str(digest)


def list_events(
    db: Session,
    project_id: str | None = None,
    type: str | None = None,
    limit: int = 50,
) -> list[LearningEvent]:
    stmt = select(LearningEvent).order_by(LearningEvent.occurred_at.desc(), LearningEvent.id.desc())
    if project_id is not None:
        stmt = stmt.where(LearningEvent.project_id == _validate_uuid(project_id))
    if type is not None:
        if type not in VALID_EVENT_TYPES:
            raise EventError(f"未知事件类型：{type}")
        stmt = stmt.where(LearningEvent.type == type)
    stmt = stmt.limit(min(max(limit, 1), 200))
    return list(db.scalars(stmt))
