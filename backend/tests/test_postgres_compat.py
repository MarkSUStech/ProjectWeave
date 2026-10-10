"""PostgreSQL 兼容验证套件（P1.8）。

默认跳过；设置环境变量后启用，例如（Git Bash）：

    PW_TEST_DATABASE_URL=postgresql+psycopg2://projectweave:projectweave@localhost:5433/projectweave_test \
      .venv/Scripts/python.exe -m pytest tests/test_postgres_compat.py -v

覆盖内容：
1. Alembic 迁移在 PG 上 upgrade → downgrade → upgrade（可回滚、可重放）；
2. 列类型断言（JSONB / 原生 uuid / timestamptz）；
3. 项目/文件/快照端到端冒烟（UUID 主键往返、JSONB 数组、中文内容、codeVersion）。

测试库会被反复 DROP/CREATE，切勿指向生产数据。
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import Base, get_db
from app.core.migrate import BACKEND_DIR
from app.main import app

PG_TEST_URL = os.environ.get("PW_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    PG_TEST_URL is None,
    reason="未设置 PW_TEST_DATABASE_URL，跳过 PostgreSQL 兼容验证（详见文件头说明）",
)

TEST_DB_NAME = "projectweave_pytest"


def _admin_engine():
    from sqlalchemy.pool import NullPool

    return create_engine(
        PG_TEST_URL.rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )


@pytest.fixture(scope="module")
def pg_url(monkeypatch_module):
    """创建干净的测试数据库，并把应用 settings 指向它。"""
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    test_url = PG_TEST_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"
    monkeypatch_module.setattr(settings, "database_url", test_url, raising=True)
    yield test_url

    # 恢复 settings 并清理测试库
    monkeypatch_module.setattr(
        settings, "database_url", os.environ.get("PW_DATABASE_URL", "sqlite:///./projectweave.db")
    )
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="module")
def monkeypatch_module(request):
    """模块级 monkeypatch（pytest 内建 monkeypatch 为函数级）。"""
    from _pytest.monkeypatch import MonkeyPatch

    patcher = MonkeyPatch()
    yield patcher
    patcher.undo()


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="module")
def pg_migrated(pg_url):
    """在 PG 上执行 upgrade head，返回 (engine_factory, alembic config)。"""
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(pg_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(pg_migrated):
    factory = sessionmaker(bind=pg_migrated, autoflush=False, expire_on_commit=False)
    session = factory()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        # 每个用例清空数据，保持独立性
        Base.metadata.drop_all(pg_migrated)
        Base.metadata.create_all(pg_migrated)


def test_upgrade_creates_expected_column_types(pg_migrated):
    with pg_migrated.connect() as conn:
        columns = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'projects'"
                )
            )
        }
    assert columns["id"] == "uuid", "PG 上主键应为原生 uuid 类型"
    assert columns["target_features"] == "jsonb", "spec 数组字段应为 JSONB"
    assert columns["milestones"] == "jsonb"
    assert columns["created_at"] == "timestamp with time zone"
    assert columns["description"] == "text"

    with pg_migrated.connect() as conn:
        snapshot_columns = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'code_snapshots'"
                )
            )
        }
    assert snapshot_columns["content_sha256"] == "character varying"


def test_crud_roundtrip_on_postgres(client):
    created = client.post(
        "/api/v1/projects",
        json={
            "title": "PostgreSQL 联调项目",
            "description": "中文描述 with JSONB arrays",
            "stack": ["TypeScript", "React"],
            "targetFeatures": ["实时预览", "本地保存"],
        },
    )
    assert created.status_code == 201
    project = created.json()
    assert project["stack"] == ["TypeScript", "React"]
    assert project["targetFeatures"] == ["实时预览", "本地保存"]
    # PG 返回 aware datetime → ISO 字符串带时区偏移
    assert project["createdAt"].endswith(("Z", "+00:00"))

    pid = project["id"]
    files = client.get(f"/api/v1/projects/{pid}/files").json()
    assert files["total"] == 3

    put = client.put(
        f"/api/v1/projects/{pid}/files",
        json={"path": "notes/联调.md", "content": "v1 内容"},
    )
    assert put.status_code == 201
    put2 = client.put(
        f"/api/v1/projects/{pid}/files",
        json={"path": "notes/联调.md", "content": "v2 内容"},
    )
    assert put2.status_code == 201

    history = client.get(
        f"/api/v1/projects/{pid}/files/history", params={"path": "notes/联调.md"}
    ).json()
    assert history["total"] == 1

    snapshot_id = history["items"][0]["id"]
    restored = client.post(
        f"/api/v1/projects/{pid}/files/history/{snapshot_id}/restore"
    )
    assert restored.status_code == 200
    current = client.get(
        f"/api/v1/projects/{pid}/files/content", params={"path": "notes/联调.md"}
    ).json()
    assert current["content"] == "v1 内容"

    version = client.get(f"/api/v1/projects/{pid}/code-version").json()
    assert version["codeVersion"].startswith("sha256:")
    assert version["fileCount"] == 4


def test_path_validation_still_enforced_on_postgres(client):
    created = client.post("/api/v1/projects", json={"title": "校验"}).json()
    pid = created["id"]
    resp = client.put(
        f"/api/v1/projects/{pid}/files", json={"path": "../escape", "content": "x"}
    )
    assert resp.status_code == 422


def test_downgrade_then_upgrade_replayable(pg_migrated, pg_url):
    def public_tables():
        with pg_migrated.connect() as conn:
            return {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            }

    # 先有数据，随后完整回滚并重放
    command.downgrade(_alembic_config(), "base")
    assert "projects" not in public_tables()

    command.upgrade(_alembic_config(), "head")
    assert {"projects", "project_files", "code_snapshots"} <= public_tables()
