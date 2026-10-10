"""快照历史、恢复与 codeVersion 测试。"""

import pytest

from tests.conftest import VALID_CREATE_PAYLOAD

FILES = "/api/v1/projects/{id}/files"
HISTORY = FILES + "/history"


@pytest.fixture()
def project(client):
    return client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()


def save(client, project_id, path, content):
    resp = client.put(FILES.format(id=project_id), json={"path": path, "content": content})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_code_version_shape_and_change(client, project):
    pid = project["id"]
    base = client.get(f"/api/v1/projects/{pid}/code-version").json()
    assert base["codeVersion"].startswith("sha256:")
    assert len(base["codeVersion"]) == len("sha256:") + 64
    assert base["fileCount"] == 3  # 种子文件

    save(client, pid, "src/main.ts", "export const changed = true;\n")
    after = client.get(f"/api/v1/projects/{pid}/code-version").json()
    assert after["codeVersion"] != base["codeVersion"]
    assert after["fileCount"] == 3


def test_save_snapshots_old_content_only_on_change(client, project):
    pid = project["id"]
    # 新建文件：无历史
    save(client, pid, "notes/a.md", "v1")
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/a.md"}).json()["total"] == 0

    # 内容变化：旧内容 v1 入快照
    save(client, pid, "notes/a.md", "v2")
    history = client.get(HISTORY.format(id=pid), params={"path": "notes/a.md"}).json()
    assert history["total"] == 1
    item = history["items"][0]
    assert item["path"] == "notes/a.md"
    assert item["size"] == 2
    assert len(item["sha256"]) == 12  # 展示用缩写
    assert item["createdAt"]

    # 相同内容重复保存：不产生新快照
    save(client, pid, "notes/a.md", "v2")
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/a.md"}).json()["total"] == 1


def test_history_listed_newest_first_and_content_readable(client, project):
    pid = project["id"]
    save(client, pid, "notes/b.md", "old-1")
    save(client, pid, "notes/b.md", "old-2")
    save(client, pid, "notes/b.md", "current")

    history = client.get(HISTORY.format(id=pid), params={"path": "notes/b.md"}).json()
    assert history["total"] == 2
    snapshots = [client.get(f"{HISTORY.format(id=pid)}/{item['id']}").json() for item in history["items"]]
    # 倒序：最近被覆盖的 old-2 在前
    assert snapshots[0]["content"] == "old-2"
    assert snapshots[1]["content"] == "old-1"
    for snapshot in snapshots:
        assert len(snapshot["sha256"]) == 64


def test_restore_puts_current_content_into_history_first(client, project):
    pid = project["id"]
    save(client, pid, "notes/c.md", "v1")
    save(client, pid, "notes/c.md", "v2")

    history = client.get(HISTORY.format(id=pid), params={"path": "notes/c.md"}).json()
    v1_snapshot = history["items"][0]

    restored = client.post(f"{HISTORY.format(id=pid)}/{v1_snapshot['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["path"] == "notes/c.md"

    current = client.get(
        FILES.format(id=pid) + "/content", params={"path": "notes/c.md"}
    ).json()
    assert current["content"] == "v1"

    # 恢复前的 v2 也进入了历史，不丢数据
    history_after = client.get(HISTORY.format(id=pid), params={"path": "notes/c.md"}).json()
    assert history_after["total"] == 2
    contents = [
        client.get(f"{HISTORY.format(id=pid)}/{i['id']}").json()["content"]
        for i in history_after["items"]
    ]
    assert "v2" in contents


def test_restore_identical_content_no_extra_snapshot(client, project):
    pid = project["id"]
    save(client, pid, "notes/d.md", "v1")
    save(client, pid, "notes/d.md", "v2")
    history = client.get(HISTORY.format(id=pid), params={"path": "notes/d.md"}).json()
    v1_snapshot = history["items"][0]

    # 第一次恢复：v2 入历史，current 变回 v1
    assert client.post(f"{HISTORY.format(id=pid)}/{v1_snapshot['id']}/restore").status_code == 200
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/d.md"}).json()["total"] == 2

    # 再次恢复同一快照：内容已一致，不再产生新快照
    assert client.post(f"{HISTORY.format(id=pid)}/{v1_snapshot['id']}/restore").status_code == 200
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/d.md"}).json()["total"] == 2


def test_snapshot_of_unknown_project_or_id_404(client, project):
    unknown = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/projects/{unknown}/code-version").status_code == 404
    assert (
        client.get(f"{HISTORY.format(id=unknown)}/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )
    pid = project["id"]
    assert (
        client.get(f"{HISTORY.format(id=pid)}/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )


def test_history_requires_valid_path(client, project):
    pid = project["id"]
    resp = client.get(HISTORY.format(id=pid), params={"path": "../escape"})
    assert resp.status_code == 422


def test_rename_carries_history(client, project):
    pid = project["id"]
    save(client, pid, "notes/e.md", "v1")
    save(client, pid, "notes/e.md", "v2")
    client.patch(FILES.format(id=pid), json={"path": "notes/e.md", "newPath": "notes/f.md"})

    assert client.get(HISTORY.format(id=pid), params={"path": "notes/e.md"}).json()["total"] == 0
    history = client.get(HISTORY.format(id=pid), params={"path": "notes/f.md"}).json()
    assert history["total"] == 1
    assert history["items"][0]["path"] == "notes/f.md"


def test_delete_file_removes_its_history(client, project):
    pid = project["id"]
    save(client, pid, "notes/g.md", "v1")
    save(client, pid, "notes/g.md", "v2")
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/g.md"}).json()["total"] == 1
    client.delete(FILES.format(id=pid), params={"path": "notes/g.md"})
    assert client.get(HISTORY.format(id=pid), params={"path": "notes/g.md"}).json()["total"] == 0


def test_snapshot_retention_limit(client, project):
    pid = project["id"]
    save(client, pid, "loop.txt", "seed")
    for index in range(60):
        save(client, pid, "loop.txt", f"content-{index}")
    history = client.get(HISTORY.format(id=pid), params={"path": "loop.txt"}).json()
    assert history["total"] == 50
    newest = client.get(f"{HISTORY.format(id=pid)}/{history['items'][0]['id']}").json()
    oldest = client.get(f"{HISTORY.format(id=pid)}/{history['items'][-1]['id']}").json()
    assert newest["content"] == "content-58"  # 最新被覆盖的是 content-58（当前为 59）
    assert oldest["content"] == "content-9"
