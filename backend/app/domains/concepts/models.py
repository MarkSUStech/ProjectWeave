"""Learner Engine 领域一：知识图谱（KnowledgeConcept）。

概念是"可测量的最小能力单元"（设计文档 6.1），不把"会 React"当作
不可分解的整体。先修关系构成 DAG，由服务端校验（无环、无悬空引用）。
掌握度估计（learner_mastery）属于后续 P2.3，不在本模块。
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeConcept(Base):
    __tablename__ = "knowledge_concepts"

    # 人类可读的稳定标识，如 "js.closures"，作为对外 API 的主键。
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    prerequisites: Mapped[list] = mapped_column(JSONType, default=list)
    objectives: Mapped[list] = mapped_column(JSONType, default=list)
    assessment_methods: Mapped[list] = mapped_column(JSONType, default=list)
    examples: Mapped[list] = mapped_column(JSONType, default=list)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
