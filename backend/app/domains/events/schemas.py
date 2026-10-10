"""事件契约（信封 v1 的字段子集，设计 §12.3）。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domains.projects.schemas import APIModel


class EventInput(APIModel):
    eventId: str = Field(min_length=8, max_length=64)
    type: str = Field(min_length=1, max_length=40)
    occurredAt: datetime
    aggregateId: str = Field(min_length=1, max_length=100)
    projectId: UUID | None = None
    payload: dict = Field(default_factory=dict)


class EventBatch(APIModel):
    events: list[EventInput] = Field(min_length=1, max_length=20)


class EventRead(APIModel):
    event_id: str
    schema_version: int
    type: str
    occurred_at: datetime
    aggregate_id: str
    sequence: int
    project_id: UUID | None
    payload: dict


class EventIngestResult(APIModel):
    accepted: int
    duplicated: int


class EventList(APIModel):
    items: list[EventRead]
    total: int
