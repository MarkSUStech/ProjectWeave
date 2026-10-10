"""Project Engine 领域的 ORM 模型（第一阶段：仅 projects 表）。

说明：
- spec 中数组类字段（target_features、milestones 等）暂以 JSON 列存储，
  待 Curriculum Engine 阶段再拆分为独立表（见 docs/DECISIONS.md D4）。
- owner_id 是为未来身份体系预留的字段，当前开发模式下使用固定占位值。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user", index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # rebuild = 从零重建；contribution = 开源贡献（设计文档 5.1）
    mode: Mapped[str] = mapped_column(String(20), default="rebuild")
    # draft / analyzing / active / completed / archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # small / medium / large
    complexity: Mapped[str] = mapped_column(String(10), default="small")

    target_features: Mapped[list] = mapped_column(JSONType, default=list)
    non_goals: Mapped[list] = mapped_column(JSONType, default=list)
    stack: Mapped[list] = mapped_column(JSONType, default=list)
    milestones: Mapped[list] = mapped_column(JSONType, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSONType, default=list)

    spec_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectFile(Base):
    """项目工作区文件。

    P1 阶段内容以 TEXT 内联存储（上限见 file_service，快照与对象存储
    属于后续 codeVersion 任务）；path 由服务层严格校验，防止穿越。
    """

    __tablename__ = "project_files"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_project_files_path"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CodeSnapshot(Base):
    """文件历史快照：覆盖保存前一刻的旧内容。

    快照在 write_file 覆盖旧内容时产生（同内容跳过）；restore 会先把
    当前内容再存快照，任何路径都不丢数据。每文件保留最近
    SNAPSHOTS_PER_FILE_LIMIT 份（file_service 维护）。
    """

    __tablename__ = "code_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(500), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
