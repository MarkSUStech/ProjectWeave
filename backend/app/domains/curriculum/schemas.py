"""课程规划契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domains.projects.schemas import APIModel


class PlanActivity(APIModel):
    type: str = Field(pattern="^(learn-concept|practice-task)$")
    order: int = Field(ge=1)
    conceptId: str | None = None
    taskId: str | None = None
    title: str | None = None
    reason: str


class PlanSkipped(APIModel):
    conceptId: str
    reason: str


class PlanRead(APIModel):
    id: UUID
    project_id: UUID
    plan_version: int
    activities: list[PlanActivity]
    skipped: list[PlanSkipped]
    reason: str
    created_at: datetime


class PlanTaskRead(APIModel):
    task_id: str
    milestone: int
    title: str
    status: str


class PlanDetailRead(APIModel):
    plan: PlanRead
    tasks: list[PlanTaskRead]
