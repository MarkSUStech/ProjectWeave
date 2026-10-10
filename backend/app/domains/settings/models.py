"""用户 AI 偏好设置（设计 §8.2 三种介入模式 / §3.1 设置与权限）。

MVP 为单用户开发模式（dev-user）；P1.7 接入身份后按 owner 隔离。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

INTERVENTION_MODES = {"quiet", "adaptive", "guided"}
DEFAULT_MODE = "adaptive"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserSettings(Base):
    __tablename__ = "user_settings"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # quiet：仅用户请求时响应；adaptive：明确证据下的非阻塞建议（默认）；
    # guided：允许基于失败证据的主动点拨
    intervention_mode: Mapped[str] = mapped_column(String(20), default=DEFAULT_MODE)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
