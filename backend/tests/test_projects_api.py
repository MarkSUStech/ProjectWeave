"""项目创建与读取（第一阶段纵向切片的核心验收）。

验证行为：
- 创建后返回 201，camelCase 字段正确回显；
- 数据真实持久化（通过列表与详情接口重新读取）；
- 校验失败返回 422，错误不被静默吞掉；
- 不存在的项目返回 404。
"""

from tests.conftest import VALID_CREATE_PAYLOAD


def test_create_project_returns_201_and_camel_case_fields(client):
    resp = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == VALID_CREATE_PAYLOAD["title"]
    assert body["targetFeatures"] == VALID_CREATE_PAYLOAD["targetFeatures"]
    assert body["nonGoals"] == VALID_CREATE_PAYLOAD["nonGoals"]
    assert body["stack"] == VALID_CREATE_PAYLOAD["stack"]
    assert body["acceptanceCriteria"] == VALID_CREATE_PAYLOAD["acceptanceCriteria"]
    assert body["mode"] == "rebuild"
    assert body["status"] == "draft"
    assert body["specVersion"] == 1
    assert body["createdAt"]
    assert body["updatedAt"]


def test_created_project_is_persisted_and_readable(client):
    created = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()

    detail = client.get(f"/api/v1/projects/{created['id']}")
    assert detail.status_code == 200
    assert detail.json() == created

    listing = client.get("/api/v1/projects")
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == created["id"]


def test_create_project_applies_defaults(client):
    resp = client.post("/api/v1/projects", json={"title": "最小项目"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["mode"] == "rebuild"
    assert body["complexity"] == "small"
    assert body["targetFeatures"] == []
    assert body["milestones"] == []
    assert body["ownerId"] == "dev-user"


def test_create_project_rejects_missing_title(client):
    resp = client.post("/api/v1/projects", json={"description": "没有标题"})
    assert resp.status_code == 422
    assert resp.json()["detail"]


def test_create_project_rejects_invalid_mode(client):
    payload = dict(VALID_CREATE_PAYLOAD, mode="unknown-mode")
    resp = client.post("/api/v1/projects", json=payload)
    assert resp.status_code == 422


def test_get_project_404_for_unknown_id(client):
    resp = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "project not found"


def test_list_projects_ordered_by_created_at_desc(client):
    first = client.post("/api/v1/projects", json={"title": "第一个"}).json()
    second = client.post("/api/v1/projects", json={"title": "第二个"}).json()
    listing = client.get("/api/v1/projects").json()
    ids = [item["id"] for item in listing["items"]]
    assert ids == [second["id"], first["id"]]
