"""Course Development Session 持久化（P8.2.3，D48）。

课程开发 = 长期多轮 Agent 会话（不同于一次 LLM 请求）：状态机服务端权威、
Workspace 版本化、预算可控、可暂停/恢复/取消/回滚。复用 P8.2.2 GenerationJob
租约语义（同一 session 同时至多一个 worker）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domains.course_generation.models import JSONType  # noqa: F401 复用类型别名

# 状态机（服务端权威转移；模型不可自报状态）
SESSION_STATES = (
    "pending",       # 已创建未开始
    "developing",    # Agent 工具循环执行中
    "paused",        # 用户/预算暂停（可恢复）
    "awaiting-eval", # 候选待独立评估（瞬时）
    "completed",     # 课程全部任务验证通过并发布 ready
    "failed",        # 预算耗尽/不可恢复错误（保留诊断，可 resume 重试）
    "cancelled",     # 用户取消
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CourseDevSession(Base):
    """一次课程开发会话（D48）。"""

    __tablename__ = "course_dev_sessions"
    __table_args__ = (
        Index("ix_course_dev_sessions_gen", "generation_id"),
        Index("ix_course_dev_sessions_release", "release_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    release_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user")
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    agent_model: Mapped[str] = mapped_column(String(80), default="")
    blueprint_revision: Mapped[int] = mapped_column(Integer, default=0)

    # 当前任务与工作区
    current_task_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    current_task_seq: Mapped[int] = mapped_column(Integer, default=0)
    workspace_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # 版本化工作区（CourseWorkspace JSON：reference/starter/manifest/…）
    workspace: Mapped[dict] = mapped_column(JSONType, default=dict)
    # 已验证累积（从 Checkpoint 恢复的基线快照 + 测试注册表）
    verified_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)

    # 用量与预算（真实计量，不估算）
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_count: Mapped[int] = mapped_column(Integer, default=0)
    token_usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    sandbox_usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    budget: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_feedback: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Agent 活动时间线（[{seq, at, kind, tool, args, ok, summary, error}]）
    timeline: Mapped[list] = mapped_column(JSONType, default=list)

    # 租约（复用 D47 语义）
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
