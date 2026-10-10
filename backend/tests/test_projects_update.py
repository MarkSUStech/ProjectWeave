"""项目更新、版本号与删除行为。"""

from tests.conftest import VALID_CREATE_PAYLOAD


def test_update_project_fields(client):
    created = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()
    patch = {"title": "改名后的编辑器", "stack": ["TypeScript", "React"]}
    resp = client.patch(f"/api/v1/projects/{created['id']}", json=patch)
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "改名后的编辑器"
    assert body["stack"] == ["TypeScript", "React"]
    # 规格字段变更后 spec_version 应提升
    assert body["specVersion"] == created["specVersion"] + 1


def test_update_status_does_not_bump_spec_version(client):
    created = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()
    resp = client.patch(f"/api/v1/projects/{created['id']}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["specVersion"] == created["specVersion"]


def test_update_unknown_project_404(client):
    resp = client.patch(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000",
        json={"title": "不存在"},
    )
    assert resp.status_code == 404


def test_delete_project(client):
    created = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()
    resp = client.delete(f"/api/v1/projects/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/projects/{created['id']}").status_code == 404
    listing = client.get("/api/v1/projects").json()
    assert listing["total"] == 0


def test_milestones_roundtrip(client):
    payload = dict(
        VALID_CREATE_PAYLOAD,
        milestones=[
            {"id": "m1", "title": "页面骨架", "description": "搭建编辑器布局"},
            {"id": "m2", "title": "实时预览", "status": "in-progress"},
        ],
    )
    created = client.post("/api/v1/projects", json=payload).json()
    assert created["milestones"][0] == {
        "id": "m1",
        "title": "页面骨架",
        "description": "搭建编辑器布局",
        "status": "pending",
    }
    assert created["milestones"][1]["status"] == "in-progress"

    detail = client.get(f"/api/v1/projects/{created['id']}").json()
    assert detail["milestones"] == created["milestones"]
