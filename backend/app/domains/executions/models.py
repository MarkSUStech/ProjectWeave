"""执行会话模型（P4.2b，设计 §10 远程执行）。

一次执行 = 一份不可变文件快照 + 在隔离沙箱中的一次运行。
会话行承载全生命周期状态与结果摘要；沙箱本身（容器）用后即毁，
行内的 stdout/stderr/事件为截断后的摘要（上限见 service 层配置）。

状态机：queued → preparing → running → completed | failed | timed-out | cancelled
（queued/preparing/running 任一时刻可被 cancel；终态不可变。）
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

# 允许持久化的状态（DB 检查用；与 schemas.ExecutionStatus 一致）
STATUSES = (
    "queued",
    "preparing",
    "running",
    "completed",
    "failed",
    "timed-out",
    "cancelled",
)
TERMINAL_STATUSES = {"completed", "failed", "timed-out", "cancelled"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionSession(Base):
    __tablename__ = "execution_sessions"
    __table_args__ = (
        Index("ix_execution_sessions_owner_created", "owner_id", "created_at"),
        Index("ix_execution_sessions_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user")
    # 可选的项目关联（学习证据与事件引用）。
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    language: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10))  # run | test
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)

    entry_point: Mapped[str | None] = mapped_column(String(300), nullable=True)
    test_paths: Mapped[list] = mapped_column(JSONType, default=list)
    stdin_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=20000)
    # 客户端执行的代码指纹（与学习事件/画布版本绑定，§14.3）。
    code_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # 请求文件快照（路径 → 内容，经校验与容量上限）。
    files_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)

    # 结果
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 基础设施错误
    stdout_text: Mapped[str] = mapped_column(Text, default="")
    stderr_text: Mapped[str] = mapped_column(Text, default="")
    # 输出事件流（轮询增量读取：[{seq, at, channel, text}]）。
    events: Mapped[list] = mapped_column(JSONType, default=list)
    diagnostics: Mapped[list] = mapped_column(JSONType, default=list)
    test_results: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    # 通用阶段记录（C++ 的 build/run 两阶段复用同一形状）。
    phases: Mapped[list] = mapped_column(JSONType, default=list)

    sandbox_engine: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sandbox_image: Mapped[str | None] = mapped_column(String(120), nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
