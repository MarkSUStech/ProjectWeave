"""项目文件 API 测试：CRUD、路径安全、脚手架种子、项目删除级联。"""

import pytest

from tests.conftest import VALID_CREATE_PAYLOAD

FILES = "/api/v1/projects/{id}/files"


@pytest.fixture()
def project(client):
    return client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()


def test_new_project_seeded_with_starter_files(client, project):
    resp = client.get(FILES.format(id=project["id"]))
    assert resp.status_code == 200
    data = resp.json()
    paths = [item["path"] for item in data["items"]]
    assert "README.md" in paths
    assert "src/main.ts" in paths
    assert "src/main.test.ts" in paths
    assert data["total"] == 3
    readme = next(item for item in data["items"] if item["path"] == "README.md")
    assert readme["size"] > 0
    assert readme["updatedAt"]


def test_read_file_returns_content(client, project):
    resp = client.get(
        FILES.format(id=project["id"]) + "/content", params={"path": "README.md"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "README.md"
    assert project["title"] in body["content"]


def test_write_then_read_roundtrip_persists(client, project):
    put = client.put(
        FILES.format(id=project["id"]),
        json={"path": "src/utils/math.ts", "content": "export const one = 1;\n"},
    )
    assert put.status_code == 201
    assert put.json()["path"] == "src/utils/math.ts"

    got = client.get(
        FILES.format(id=project["id"]) + "/content",
        params={"path": "src/utils/math.ts"},
    )
    assert got.status_code == 200
    assert got.json()["content"] == "export const one = 1;\n"

    # 覆盖更新：仍是 201 语义（upsert），内容被替换
    put2 = client.put(
        FILES.format(id=project["id"]),
        json={"path": "src/utils/math.ts", "content": "export const two = 2;\n"},
    )
    assert put2.status_code == 201
    got2 = client.get(
        FILES.format(id=project["id"]) + "/content",
        params={"path": "src/utils/math.ts"},
    )
    assert got2.json()["content"] == "export const two = 2;\n"


def test_rename_file(client, project):
    client.put(
        FILES.format(id=project["id"]),
        json={"path": "notes/draft.md", "content": "draft"},
    )
    resp = client.patch(
        FILES.format(id=project["id"]),
        json={"path": "notes/draft.md", "newPath": "notes/final.md"},
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "notes/final.md"
    assert (
        client.get(
            FILES.format(id=project["id"]) + "/content", params={"path": "notes/draft.md"}
        ).status_code
        == 404
    )
    renamed = client.get(
        FILES.format(id=project["id"]) + "/content", params={"path": "notes/final.md"}
    )
    assert renamed.json()["content"] == "draft"


def test_rename_to_existing_path_conflict(client, project):
    client.put(FILES.format(id=project["id"]), json={"path": "a.md", "content": "a"})
    client.put(FILES.format(id=project["id"]), json={"path": "b.md", "content": "b"})
    resp = client.patch(
        FILES.format(id=project["id"]), json={"path": "a.md", "newPath": "b.md"}
    )
    assert resp.status_code == 409


def test_delete_file(client, project):
    client.put(FILES.format(id=project["id"]), json={"path": "tmp.txt", "content": "x"})
    assert (
        client.delete(FILES.format(id=project["id"]), params={"path": "tmp.txt"}).status_code
        == 204
    )
    assert (
        client.get(
            FILES.format(id=project["id"]) + "/content", params={"path": "tmp.txt"}
        ).status_code
        == 404
    )


def test_missing_file_returns_404(client, project):
    assert (
        client.get(
            FILES.format(id=project["id"]) + "/content", params={"path": "nope.md"}
        ).status_code
        == 404
    )
    assert (
        client.delete(FILES.format(id=project["id"]), params={"path": "nope.md"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path",
    [
        "../escape.txt",          # 父目录穿越
        "a/../../b.txt",          # 嵌套穿越
        "/absolute.txt",          # 绝对路径
        "back\\slash.txt",        # 反斜杠
        "a//b.txt",               # 空段
        "a/./b.txt",              # 当前目录段
        "trailing ",              # 首尾空格
        'illegal<>.txt',          # 非法字符
        "CON",                    # Windows 保留名
        "",                       # 空路径
    ],
)
def test_unsafe_paths_rejected(client, project, path):
    resp = client.put(FILES.format(id=project["id"]), json={"path": path, "content": "x"})
    assert resp.status_code == 422
    # 确认没有文件被创建
    listing = client.get(FILES.format(id=project["id"])).json()
    assert all(item["path"] != path.strip() for item in listing["items"])


def test_files_of_unknown_project_404(client):
    unknown = "00000000-0000-0000-0000-000000000000"
    assert client.get(FILES.format(id=unknown)).status_code == 404


def test_deleting_project_removes_its_files(client, project):
    client.put(FILES.format(id=project["id"]), json={"path": "x.txt", "content": "x"})
    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    assert client.get(FILES.format(id=project["id"])).status_code == 404
