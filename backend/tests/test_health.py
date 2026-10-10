"""健康检查与服务基本信息测试。"""


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/v1/projects" in paths
    assert "/api/v1/projects/{project_id}" in paths
