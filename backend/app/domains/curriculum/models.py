"""Curriculum Engine：项目任务图与学习路线（设计文档 §7、§5.3、附录 B）。

样板课程任务模板是确定性内容；任意目标的自动课程生成属于后续版本。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectTask(Base):
    """项目任务图节点（设计 5.3）：依赖、知识要求、交付物与验收。"""

    __tablename__ = "project_tasks"
    __table_args__ = (
        # 同一项目内 taskId 唯一（联合唯一由服务层保证，见 service）
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(String(100))
    milestone: Mapped[int] = mapped_column()  # 里程碑序号 M1..M6
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default="")
    depends_on: Mapped[list] = mapped_column(JSONType, default=list)  # taskId 列表
    required_concepts: Mapped[list] = mapped_column(JSONType, default=list)  # conceptId 列表
    deliverable: Mapped[str] = mapped_column(String(500), default="")
    effort_band: Mapped[str] = mapped_column(String(10), default="medium")  # small/medium/large
    # P5.1：任务级 AI 提示层级（渐进提示， Tutor 按当前 H 级取用）
    hints: Mapped[list] = mapped_column(JSONType, default=list)  # [{level, text}]
    # P5.1：可视化教学建议（引导使用调试/内存图等真实数据场景）
    viz_suggestion: Mapped[str] = mapped_column(String(1000), default="")
    # 任务绑定的测试文件路径（任务级验收只看这些文件）
    test_files: Mapped[list] = mapped_column(JSONType, default=list)
    # P8.2 任务验收契约：cmake 任务按目标/CTest 名验收（{buildSystem,
    # buildTargets, testNames, verificationProfile}）；空 = 旧 testFiles 语义
    verification: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # 任务初始代码 [{path, content}]，项目创建时种子到 project_files
    starter_files: Mapped[list] = mapped_column(JSONType, default=list)
    # 验收条件（人可读描述，展示给学习者）
    acceptance_criteria: Mapped[list] = mapped_column(JSONType, default=list)
    # pending / in-progress / done / needs-fix
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningPlan(Base):
    """生成的学习路线（设计 7.3）：版本化，保留原因与差异。"""

    __tablename__ = "learning_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_version: Mapped[int] = mapped_column()
    # [{type, order, conceptId?/taskId, reason}]
    activities: Mapped[list] = mapped_column(JSONType, default=list)
    # [{conceptId, reason}]
    skipped: Mapped[list] = mapped_column(JSONType, default=list)
    # 生成依据摘要（如"基于 2 次诊断的证据"）
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
