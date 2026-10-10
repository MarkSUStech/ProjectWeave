"""数据库引擎与会话管理。

使用同步 SQLAlchemy 2.0；FastAPI 的同步端点会在线程池中执行，
对当前阶段的负载是简单可靠的选择（见 docs/DECISIONS.md D3）。
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def _connect_args() -> dict[str, bool]:
    # SQLite 需要允许多线程访问（FastAPI 线程池 + TestClient）。
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(),
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
