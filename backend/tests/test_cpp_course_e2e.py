"""P5.1 C++ 指针课程端到端（选入 PW_SANDBOX_E2E=1；真实服务 + Docker 沙箱）。

创建 C++ 项目 → cpp 域诊断 → 3 任务课程 → Task1 真实测试验收 →
Task2 LLDB 暂停（p→x 已验证边 + 单步 x 变化）→ Task3 迁移练习 → cpp 掌握证据。

前置：后端已在 127.0.0.1:8001 运行（uvicorn app.main:app --port 8001）。
"""

import json
import os
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1、已构建镜像与 8001 端口运行的后端",
)

BASE = "http://127.0.0.1:8001/api/v1"
NL = chr(10)


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode())


def wait_exec(eid, timeout=60):
    for _ in range(timeout * 2):
        s = req("GET", f"/executions/{eid}")
        if s["status"] in ("completed", "failed", "timed-out"):
            return s
        time.sleep(0.5)
    pytest.fail("执行超时")


def wait_paused(did, prev_seq=0, timeout=120):
    for _ in range(timeout * 2):
        d = req("GET", f"/debug-sessions/{did}")
        if d["status"] == "paused" and d.get("pauseSeq", 0) > prev_seq:
            return d
        if d["status"] == "terminated":
            pytest.fail(f"会话提前终止：{d.get('endReason')}")
        time.sleep(0.5)
    pytest.fail("调试等待超时")


def test_cpp_course_full_flow():
    # 1. C++ 项目（cpp-pointers-v1 模板）
    project = req("POST", "/projects", {
        "title": "指针课程 E2E", "description": "d", "mode": "rebuild",
        "complexity": "medium", "targetFeatures": ["指针"], "nonGoals": [],
        "stack": ["C++"], "acceptanceCriteria": [],
    })
    pid = project["id"]
    assert project["templateId"] == "cpp-pointers-v1"

    # 2. 诊断（全部 cpp 域概念）
    assess = req("POST", "/assessments/start", {"projectId": pid})
    assert len(assess["items"]) >= 5
    assert all(i["conceptId"].startswith("cpp.") for i in assess["items"])
    submit = req("POST", f"/assessments/{assess['id']}/submit", {
        "answers": [{"itemId": i["itemId"], "selectedOptionIndex": 1} for i in assess["items"]]
    })
    assert submit["status"] == "completed"
    concepts = {c["conceptId"] for c in submit["results"]["concepts"]}
    assert concepts and all(c.startswith("cpp.") for c in concepts)

    # 3. 学习路线（3 任务 + hints/viz）
    plan = req("GET", f"/plans/{pid}")
    tasks = {t["taskId"]: t for t in plan["tasks"]}
    assert list(tasks) == ["cpp-ptr-1-address", "cpp-ptr-2-dereference", "cpp-ptr-3-functions"]
    assert tasks["cpp-ptr-1-address"]["hints"]
    assert "调试" in tasks["cpp-ptr-2-dereference"]["vizSuggestion"]

    def read(path):
        return req("GET", f"/projects/{pid}/files/content?path={path}")["content"]

    def write(path, content):
        req("PUT", f"/projects/{pid}/files", {"path": path, "content": content})

    def all_files():
        items = req("GET", f"/projects/{pid}/files")["items"]
        return {f["path"]: read(f["path"]) for f in items if f["path"] != "README.md"}

    def evaluate(task_id, test_path, exec_id):
        return req("POST", f"/projects/{pid}/tasks/{task_id}/evaluate", {
            "files": [{"path": test_path, "status": "passed", "passed": 1, "failed": 0, "totalCases": 1}],
            "source": "remote", "executionId": exec_id,
        })

    # 4. Task1：学生完成 TODO → 真实测试 + 运行 + 验收
    t1 = read("src/tasks/task1_address.cpp")
    student1 = t1.replace(
        "    // TODO(任务1)：打印 y 的地址（模仿上一行，把 x 换成 y）",
        '    std::printf("y 的地址是 %p' + chr(92) + 'n", (void*)&y);',
    )
    assert student1 != t1, "TODO 替换必须生效"
    write("src/tasks/task1_address.cpp", student1)
    files = all_files()
    e1 = wait_exec(req("POST", "/executions", {
        "language": "cpp", "mode": "test", "entryPoint": None,
        "testPaths": ["src/tasks/task1_address_test.cpp"], "files": files, "timeoutMs": 30000,
    })["id"])
    assert e1["status"] == "completed"
    assert all(r["status"] == "passed" for r in e1["testResults"])
    r1 = wait_exec(req("POST", "/executions", {
        "language": "cpp", "mode": "run", "entryPoint": "src/tasks/task1_address.cpp",
        "files": files, "timeoutMs": 30000,
    })["id"])
    out = r1["stdout"]
    assert "42" in out and out.count("0x") >= 2  # 值 + 两个真实地址
    ev1 = evaluate("cpp-ptr-1-address", "src/tasks/task1_address_test.cpp", e1["id"])
    assert ev1["passed"] is True

    # 5. Task2：真实 LLDB（p→x 已验证边 + 单步 x 变化）+ 测试 + 验收
    t2 = read("src/tasks/task2_deref.cpp")
    student2 = t2.replace("    // TODO(任务2a)：通过 *p 把 x 改成 20", "    *p = 20;")
    assert student2 != t2
    write("src/tasks/task2_deref.cpp", student2)
    files = all_files()
    dbg = req("POST", "/debug-sessions", {
        "language": "cpp", "entryPoint": "src/tasks/task2_deref.cpp", "files": files,
        "breakpoints": [{"path": "src/tasks/task2_deref.cpp", "lines": [14]}],  # *p = 20; 行
    })["id"]
    d1 = wait_paused(dbg)
    edge = d1["pointerGraph"]["verifiedEdges"][0]
    assert (edge["from"], edge["to"]) == ("p", "x")
    locals1 = {v["name"]: v["value"] for s in d1["scopes"] if s["name"] == "Locals" for v in s["variables"]}
    assert locals1["x"] == "10"
    req("POST", f"/debug-sessions/{dbg}/commands", {"command": "next"})
    d2 = wait_paused(dbg, prev_seq=d1["pauseSeq"])
    locals2 = {v["name"]: v["value"] for s in d2["scopes"] if s["name"] == "Locals" for v in s["variables"]}
    assert locals2["x"] == "20" and d2["pauseSeq"] > d1["pauseSeq"]
    req("DELETE", f"/debug-sessions/{dbg}")

    e2 = wait_exec(req("POST", "/executions", {
        "language": "cpp", "mode": "test", "entryPoint": None,
        "testPaths": ["src/tasks/task2_deref_test.cpp"], "files": files, "timeoutMs": 30000,
    })["id"])
    assert all(r["status"] == "passed" for r in e2["testResults"])
    ev2 = evaluate("cpp-ptr-2-dereference", "src/tasks/task2_deref_test.cpp", e2["id"])
    assert ev2["passed"] is True  # 依赖闸门：Task1 已完成

    # 6. Task3：迁移练习（my_swap 独立检验，不提供完整解答）
    t3 = read("src/tasks/task3_swap_test.cpp")
    student3 = t3.replace(
        "    // TODO(任务3c)：用临时变量 + 解引用完成交换",
        "    int tmp = *a; *a = *b; *b = tmp;",
    )
    assert student3 != t3
    write("src/tasks/task3_swap_test.cpp", student3)
    e3 = wait_exec(req("POST", "/executions", {
        "language": "cpp", "mode": "test", "entryPoint": None,
        "testPaths": ["src/tasks/task3_swap_test.cpp"], "files": all_files(), "timeoutMs": 30000,
    })["id"])
    assert all(r["status"] == "passed" for r in e3["testResults"])
    ev3 = evaluate("cpp-ptr-3-functions", "src/tasks/task3_swap_test.cpp", e3["id"])
    assert ev3["passed"] is True

    # 7. 学习证据关联 cpp 概念 + 事件
    mastery = req("GET", "/mastery")["items"]
    cpp = [m for m in mastery if m["conceptId"].startswith("cpp.")]
    assert cpp, "验收必须写入 cpp.* 概念掌握记录"
    events = req("GET", f"/events?projectId={pid}&type=task-evaluated&limit=10")["items"]
    assert len(events) == 3
    assert all(e["payload"]["trustLevel"] == "practice" for e in events)
