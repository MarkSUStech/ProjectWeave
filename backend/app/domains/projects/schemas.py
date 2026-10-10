"""projects 领域的 API 契约（Pydantic）。

对外 JSON 使用 camelCase（与前端约定），内部字段保持 Python 风格，
通过 alias_generator 转换。日期时间一律 ISO 8601 UTC。
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class APIModel(BaseModel):
    """所有对外契约的基类：camelCase 别名 + ORM 读取。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ProjectMode(str, Enum):
    rebuild = "rebuild"
    contribution = "contribution"


class ProjectStatus(str, Enum):
    draft = "draft"
    analyzing = "analyzing"
    active = "active"
    completed = "completed"
    archived = "archived"


class ProjectComplexity(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"


class MilestoneStatus(str, Enum):
    pending = "pending"
    in_progress = "in-progress"
    done = "done"


class Milestone(APIModel):
    id: str
    title: str
    description: str = ""
    status: MilestoneStatus = MilestoneStatus.pending


class ProjectCreate(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=8000)
    mode: ProjectMode = ProjectMode.rebuild
    complexity: ProjectComplexity = ProjectComplexity.small
    target_features: list[str] = Field(default_factory=list, max_length=50)
    non_goals: list[str] = Field(default_factory=list, max_length=50)
    stack: list[str] = Field(default_factory=list, max_length=30)
    milestones: list[Milestone] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)


class ProjectUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    mode: ProjectMode | None = None
    status: ProjectStatus | None = None
    complexity: ProjectComplexity | None = None
    target_features: list[str] | None = Field(default=None, max_length=50)
    non_goals: list[str] | None = Field(default=None, max_length=50)
    stack: list[str] | None = Field(default=None, max_length=30)
    milestones: list[Milestone] | None = Field(default=None, max_length=50)
    acceptance_criteria: list[str] | None = Field(default=None, max_length=50)


class ProjectRead(APIModel):
    id: UUID
    owner_id: str
    title: str
    description: str
    mode: ProjectMode
    status: ProjectStatus
    complexity: ProjectComplexity
    target_features: list[str]
    non_goals: list[str]
    stack: list[str]
    milestones: list[Milestone]
    acceptance_criteria: list[str]
    spec_version: int
    template_id: str | None = None  # 项目模板（P5.1，D39）
    created_at: datetime
    updated_at: datetime


class ProjectList(APIModel):
    items: list[ProjectRead]
    total: int
