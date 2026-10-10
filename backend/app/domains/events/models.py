"""学习事件信封（设计文档 §11.3/§12.2/§12.3）。

事件日志与当前状态表并存（非 Event Sourcing）：业务状态照常写各自表，
重要变更追加事件行。eventId 全局唯一——重复投递按幂等跳过（至少一次投递）。
payload 只存摘要与引用（路径/id/计数），不存代码全文与任何密钥。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

SCHEMA_VERSION = 1

# 允许持久化的类型白名单（服务端写入 + 客户端上报分开声明）
SERVER_EVENT_TYPES = {
    "file-saved",            # 文件保存（来源：文件写入）
    "assessment-submitted",  # 诊断提交
    "plan-generated",        # 学习路线首次生成
    "plan-replanned",        # 学习路线重新规划
    "task-evaluated",        # 阶段任务验收（来源：evaluate 端点）
}
CLIENT_EVENT_TYPES = {
    "code-run",            # 浏览器运行（来源：前端上报）
    "tests-run",           # 浏览器测试运行（来源：前端上报）
    "tutor-turn",          # AI 教学回合（来源：后端 tutor）
}
EVENT_TYPES = SERVER_EVENT_TYPES | CLIENT_EVENT_TYPES

MAX_PAYLOAD_ITEMS = 20
MAX_PAYLOAD_CHARS = 4000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        Index("ix_learning_events_aggregate", "aggregate_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 幂等去重键：客户端生成的 UUID v4；重复直接跳过。
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    schema_version: Mapped[int] = mapped_column(default=SCHEMA_VERSION)
    type: Mapped[str] = mapped_column(String(40), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user", index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(100), index=True)
    sequence: Mapped[int] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
