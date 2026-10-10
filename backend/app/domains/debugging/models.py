"""DebugSession 模型（P4.5a）。

与一次性 ExecutionSession 不同：调试会话是长生命周期交互式会话——
容器常驻（sleep infinity + docker exec 通道），DAP 客户端在服务端持有，
快照（位置/线程/栈帧/作用域变量）在每次暂停时刷新落库，供轮询读取。

状态机：CREATING → BUILDING → CONFIGURING → RUNNING ⇄ PAUSED → TERMINATED
（TERMINATED 终态；end_reason 区分 completed / build-failed / debugger-error /
timeout / cancelled / internal-error。）
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

DEBUG_STATUSES = ("creating", "building", "configuring", "running", "paused", "terminated")
TERMINAL_STATUSES = {"terminated"}

END_REASONS = (
    "completed",       # 程序正常结束
    "build-failed",    # 编译/链接失败（调试器未启动）
    "debugger-error",  # DAP/调试器故障
    "timeout",         # 会话超时回收
    "cancelled",       # 用户停止
    "internal-error",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DebugSession(Base):
    __tablename__ = "debug_sessions"
    __table_args__ = (
        Index("ix_debug_sessions_owner_created", "owner_id", "created_at"),
        Index("ix_debug_sessions_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    language: Mapped[str] = mapped_column(String(20), default="cpp")
    status: Mapped[str] = mapped_column(String(14), default="creating", index=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    entry_point: Mapped[str] = mapped_column(String(300))
    files_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    breakpoints: Mapped[list] = mapped_column(JSONType, default=list)  # [{path, lines:[..]}]
    code_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 调试器 Profile：如 "lldb-dap:19"，记录实际使用的调试器
    debugger_profile: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # 最近一次暂停/停止时的快照（真实 DAP 数据，非推测）
    current_location: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    threads: Mapped[list] = mapped_column(JSONType, default=list)
    stack_frames: Mapped[list] = mapped_column(JSONType, default=list)
    scopes: Mapped[list] = mapped_column(JSONType, default=list)
    verified_breakpoints: Mapped[list] = mapped_column(JSONType, default=list)

    build_diagnostics: Mapped[list] = mapped_column(JSONType, default=list)
    build_stdout: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # DAP 事件日志（有界）
    dap_log: Mapped[list] = mapped_column(JSONType, default=list)

    sandbox_engine: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sandbox_image: Mapped[str | None] = mapped_column(String(120), nullable=True)
    container_name: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # 资源回收：空闲超时与硬超时（时间戳，毫秒 epoch）；活动时刷新 idle_deadline
    idle_deadline_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_deadline_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
