"""后端集成测试夹具：每个测试会话使用独立的临时 SQLite 数据库。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base, get_db
from app.main import app

from sqlalchemy import create_engine


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


VALID_CREATE_PAYLOAD = {
    "title": "Markdown 笔记编辑器",
    "description": "类似 Obsidian 的本地 Markdown 编辑器，Web 端实时预览。",
    "mode": "rebuild",
    "complexity": "medium",
    "targetFeatures": ["实时预览", "本地保存", "全文搜索"],
    "nonGoals": ["插件系统", "多端同步"],
    "stack": ["TypeScript", "React", "Vite"],
    "acceptanceCriteria": ["刷新后笔记内容保留"],
}
