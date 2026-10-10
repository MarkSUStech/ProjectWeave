"""Learner Engine：学习者掌握模型与学习证据（设计文档 6.2/6.3/6.5）。

四维能力（understanding/application/debugging/independence）各自独立估计；
没有证据的维度保持 null——估计值是系统推断，绝不编造客观分数。
MVP 证据来源为诊断预测题（understanding 维），其余维度由后续任务编码、
测试运行等证据类型接入。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

MASTERY_MODEL_VERSION = "rule-v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LearnerMastery(Base):
    __tablename__ = "learner_mastery"
    __table_args__ = (
        UniqueConstraint("owner_id", "concept_id", name="uq_mastery_owner_concept"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user", index=True)
    concept_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("knowledge_concepts.id"), index=True
    )
    # {dimension: {estimate, confidence, evidenceCount, lastObservedAt} | null}
    dimensions: Mapped[dict] = mapped_column(JSONType, default=dict)
    model_version: Mapped[str] = mapped_column(String(20), default=MASTERY_MODEL_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LearningEvidence(Base):
    __tablename__ = "learning_evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user", index=True)
    concept_id: Mapped[str] = mapped_column(String(100), index=True)
    # prediction / explanation / coding / debugging / transfer（设计 6.3 词表）
    evidence_type: Mapped[str] = mapped_column(String(20))
    # passed / failed
    outcome: Mapped[str] = mapped_column(String(10))
    # 证据来源（当前为诊断会话；后续为任务/运行）
    source_kind: Mapped[str] = mapped_column(String(20), default="assessment")
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
