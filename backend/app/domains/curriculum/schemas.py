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
    description: str = ""
    required_concepts: list[str] = Field(default_factory=list)
    deliverable: str = ""
    test_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class PlanDetailRead(APIModel):
    plan: PlanRead
    tasks: list[PlanTaskRead]


class EvaluationFileResult(APIModel):
    path: str
    status: str
    passed: int = 0
    failed: int = 0
    totalCases: int = 0


class EvaluationSuiteInput(APIModel):
    """测试套件结果（由前端运行器采集后提交；浏览器或远程沙箱均可）。"""

    files: list[EvaluationFileResult] = Field(default_factory=list)
    traceId: str | None = Field(default=None, max_length=64)
    # 执行来源与远程执行会话（P4.2b：python 经服务端沙箱执行时的溯源）。
    source: str = Field(default="browser", pattern="^(browser|remote)$")
    executionId: str | None = Field(default=None, max_length=64)
    # 兼容 P3.5 旧字段（渐进迁移，任务级评估优先用 files）
    totalFiles: int = Field(default=0, ge=0)
    totalPassed: int = Field(default=0, ge=0)
    totalFailed: int = Field(default=0, ge=0)
    errorFiles: int = Field(default=0, ge=0)


class EvaluationResultRead(APIModel):
    taskId: str
    status: str
    passed: bool
    rubricVersion: str
    evidenceConcepts: list[str]
    warnings: list[str] = Field(default_factory=list)
    # practice = 客户端自报练习（非正式验收）；formal 需服务端可信执行
    trustLevel: str = "practice"
