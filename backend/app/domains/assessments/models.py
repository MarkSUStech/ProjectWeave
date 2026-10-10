"""初始能力诊断（设计文档 6.4 / FR-02）。

会话按项目技术栈选题，作答由确定性规则判定（无 LLM 参与评分）；
概念级三档估计保存在会话结果中，供 P2.3 的 mastery/evidence 精化。
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


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # in-progress / completed / abandoned
    status: Mapped[str] = mapped_column(String(20), default="in-progress", index=True)
    # 选中题目的快照（itemId 列表 + 题库版本），保证题库升级后历史可追溯。
    selected_items: Mapped[list] = mapped_column(JSONType, default=list)
    # 提交后计算的概念级诊断结果 {concepts, questions}；未提交为 NULL。
    results: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assessment_sessions.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[str] = mapped_column(String(100))
    concept_id: Mapped[str] = mapped_column(String(100))
    selected_option_index: Mapped[int] = mapped_column()
    correct: Mapped[bool] = mapped_column()
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
