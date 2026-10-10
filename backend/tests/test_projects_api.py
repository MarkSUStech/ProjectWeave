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


# ---------------------------------------------------------------- C++ 项目脚手架（P4.5b.1 后续）


def test_create_cpp_project_seeds_cpp_starter(client):
    """stack 含 C++ 时种子 C++ 多文件脚手架（可运行/可测试/可调试），不种 TS 文件。"""
    payload = dict(VALID_CREATE_PAYLOAD)
    payload["stack"] = ["C++", "CMake"]
    payload["title"] = "C++ 指针与内存实验"
    resp = client.post("/api/v1/projects", json=payload)
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    files = client.get(f"/api/v1/projects/{pid}/files").json()["items"]
    paths = {f["path"] for f in files}
    assert "src/main.cpp" in paths
    assert "src/math.hpp" in paths
    assert "src/math.cpp" in paths
    assert "tests/test_math.cpp" in paths
    assert "README.md" in paths
    # 不种 TS 脚手架
    assert "src/main.ts" not in paths
    assert "src/main.test.ts" not in paths

    main_cpp = client.get(
        f"/api/v1/projects/{pid}/files/content", params={"path": "src/main.cpp"}
    ).json()["content"]
    assert "int* p = &a;" in main_cpp  # 指针演示（内存图可画已验证边）
    assert "nullptr" in main_cpp
    readme = client.get(
        f"/api/v1/projects/{pid}/files/content", params={"path": "README.md"}
    ).json()["content"]
    assert "调试" in readme  # 起步指引


def test_cpp_project_seeds_cpp_pointer_course(client, db_session):
    """C++ 项目种子《理解 C++ 指针》课程（3 任务 + 初始代码 + 测试），不种 TS 课程。"""
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)  # cpp.* 概念供任务知识要求引用
    payload = dict(VALID_CREATE_PAYLOAD)
    payload["stack"] = ["cpp"]
    resp = client.post("/api/v1/projects", json=payload)
    pid = resp.json()["id"]

    plan_detail = client.get(f"/api/v1/plans/{pid}")
    assert plan_detail.status_code == 200
    tasks = plan_detail.json()["tasks"]
    assert [t["taskId"] for t in tasks] == [
        "cpp-ptr-1-address", "cpp-ptr-2-dereference", "cpp-ptr-3-functions",
    ]
    # 任务携带渐进提示与可视化建议
    assert tasks[0]["hints"] and tasks[0]["hints"][0]["level"] == 1
    assert "调试" in tasks[1]["vizSuggestion"]
    # 文件：任务初始代码与测试已种，且无 TS 文件
    files = {f["path"] for f in client.get(f"/api/v1/projects/{pid}/files").json()["items"]}
    assert "src/tasks/task1_address.cpp" in files
    assert "src/tasks/task2_deref_test.cpp" in files
    assert all(not p.endswith(".ts") for p in files)


def test_python_project_no_course_explicit(client, db_session):
    """Python 项目：Python 脚手架 + 无课程（学习路线如实为空，不展示其他语言课程）。"""
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    payload = dict(VALID_CREATE_PAYLOAD)
    payload["stack"] = ["Python"]
    resp = client.post("/api/v1/projects", json=payload)
    pid = resp.json()["id"]

    files = {f["path"] for f in client.get(f"/api/v1/projects/{pid}/files").json()["items"]}
    assert "src/main.py" in files and "tests/test_main.py" in files
    assert not any(p.endswith((".ts", ".cpp")) for p in files)
    plan_detail = client.get(f"/api/v1/plans/{pid}")
    assert plan_detail.status_code == 200
    assert plan_detail.json()["tasks"] == []


def test_replan_never_overwrites_user_files(client, db_session):
    """重规划不覆盖用户代码：用户改过的种子文件在 replan 后保持原样。"""
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    payload = dict(VALID_CREATE_PAYLOAD)
    payload["stack"] = ["cpp"]
    pid = client.post("/api/v1/projects", json=payload).json()["id"]
    client.get(f"/api/v1/plans/{pid}")  # 首次生成种子课程文件

    # 用户修改任务初始文件
    user_code = "// my own code" + chr(10) + "int main() { return 0; }" + chr(10)
    put = client.put(
        f"/api/v1/projects/{pid}/files",
        json={"path": "src/tasks/task1_address.cpp", "content": user_code},
    )
    assert put.status_code in (200, 201)

    client.post(f"/api/v1/plans/{pid}/replan")  # 重规划
    content = client.get(
        f"/api/v1/projects/{pid}/files/content",
        params={"path": "src/tasks/task1_address.cpp"},
    ).json()["content"]
    assert content == user_code  # 用户代码未被覆盖


def test_ts_project_keeps_existing_starter(client, db_session):
    """非 C++ 项目维持 TS 脚手架与试点课程（零回归）。"""
    # TestClient 不跑 lifespan：先种子知识图谱（试点任务的知识要求校验依赖）
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    resp = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD)
    pid = resp.json()["id"]
    files = {f["path"] for f in client.get(f"/api/v1/projects/{pid}/files").json()["items"]}
    assert "src/main.ts" in files and "src/main.test.ts" in files
    plan_detail = client.get(f"/api/v1/plans/{pid}").json()
    assert len(plan_detail["tasks"]) == 3  # TS 试点课程照常
