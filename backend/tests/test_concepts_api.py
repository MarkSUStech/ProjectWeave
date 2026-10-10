"""知识图 API 与种子测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import Base, get_db
from app.domains.concepts import service
from app.domains.concepts.seed import SEED_CONCEPTS
from app.main import app


@pytest.fixture()
def seeded_client(db_session: Session):
    assert service.ensure_seed_concepts(db_session) == len(SEED_CONCEPTS)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_seed_is_idempotent(db_session: Session):
    assert service.ensure_seed_concepts(db_session) == len(SEED_CONCEPTS)
    # 第二次调用不重复写入、不报错
    assert service.ensure_seed_concepts(db_session) == 0
    assert db_session.query(service.KnowledgeConcept).count() == len(SEED_CONCEPTS)


def test_seed_graph_is_valid_dag():
    # 种子自身必须通过校验（无环、无悬空先修）
    service.validate_graph({c["id"]: c["prerequisites"] for c in SEED_CONCEPTS})


def test_validate_graph_rejects_cycle():
    with pytest.raises(ValueError, match="环"):
        service.validate_graph({"a": ["b"], "b": ["a"]})


def test_validate_graph_rejects_self_reference():
    with pytest.raises(ValueError, match="自身"):
        service.validate_graph({"a": ["a"]})


def test_validate_graph_rejects_dangling_reference():
    with pytest.raises(ValueError, match="悬空"):
        service.validate_graph({"a": ["missing"]})


def test_list_concepts(seeded_client: TestClient):
    resp = seeded_client.get("/api/v1/concepts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(SEED_CONCEPTS)
    assert "javascript" in data["domains"]
    assert "typescript" in data["domains"]
    item = data["items"][0]
    assert set(item.keys()) >= {
        "id", "title", "domain", "prerequisites",
        "objectives", "assessmentMethods", "examples", "version",
    }


def test_list_concepts_filter_by_domain(seeded_client: TestClient):
    data = seeded_client.get("/api/v1/concepts", params={"domain": "typescript"}).json()
    assert data["total"] == 2
    assert all(item["domain"] == "typescript" for item in data["items"])


def test_get_concept_detail(seeded_client: TestClient):
    resp = seeded_client.get("/api/v1/concepts/js.closures")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "闭包与变量捕获"
    assert set(body["prerequisites"]) == {"js.functions", "js.objects"}
    assert "prediction" in body["assessmentMethods"]


def test_get_concept_404(seeded_client: TestClient):
    assert seeded_client.get("/api/v1/concepts/nope").status_code == 404


def test_concepts_endpoint_empty_without_seed(client: TestClient):
    # 未种子时列表为空（不自动播种——种子只发生在启动 lifespan）
    data = client.get("/api/v1/concepts").json()
    assert data == {"items": [], "total": 0, "domains": []}
