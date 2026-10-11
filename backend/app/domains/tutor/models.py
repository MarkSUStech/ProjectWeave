"""Tutor Engine（设计 §8）：教学回合 = 确定性上下文组装 + LLM 提案 + Policy Gate。

AI 只产生教学意图提案；权限、校验与落库由确定性代码完成（Policy Gate，
设计 §8.4/§13.3 的 MVP 形态）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

POLICY_VERSION = "gate-v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TeachingDecision(Base):
    """教学决策（设计 §12.2：可解释、带政策版本）。"""

    __tablename__ = "teaching_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String(2000))
    # user：用户主动提问；auto：基于失败证据的主动建议（受介入模式与冷却约束）
    trigger: Mapped[str] = mapped_column(String(10), default="user")
    # LLM 原始提案（通过 schema 校验后）
    intent: Mapped[str] = mapped_column(String(20))
    hint_level: Mapped[int] = mapped_column()
    message: Mapped[str] = mapped_column(String(4000))
    target_concepts: Mapped[list] = mapped_column(JSONType, default=list)
    explanation: Mapped[str] = mapped_column(String(1000), default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
    # Policy Gate 结果：accepted / degraded / rejected
    outcome: Mapped[str] = mapped_column(String(20), default="accepted")
    outcome_reason: Mapped[str] = mapped_column(String(500), default="")
    # Policy Gate 分级后的工作台动作提案（§10.2：A0/A1/A2）
    workspace_actions: Mapped[list] = mapped_column(JSONType, default=list)
    policy_version: Mapped[str] = mapped_column(String(20), default=POLICY_VERSION)
    # P6 Agent 轨迹：[{tool, args, ok, round, durationMs, summary|error}]
    tool_calls: Mapped[list] = mapped_column(JSONType, default=list)
    agent_rounds: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    model: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
