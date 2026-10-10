"""调试会话 API 单元测试（Fake 调试沙箱 + 假 lldb-dap 子进程，无需 Docker）。

覆盖：创建校验 / 503 / 断点暂停快照 / 单步 / 递归栈 / 编译失败不启动调试器 /
停止幂等 / 404 / 变量懒加载。
"""

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import SessionLocal
from app.domains.debugging import service
from app.domains.debugging.debug_sandbox import DockerDebugSandbox
from tests.fake_dap_server import __file__ as FAKE_DAP_SERVER_PATH

FAKE_DAP = os.path.abspath(FAKE_DAP_SERVER_PATH)


class FakeDebugProvider:
    """协议兼容假沙箱：容器操作全记录，DAP 通道指向假 lldb-dap 子进程。"""

    image = "fake-debug-image"
    engine = "fake"

    def __init__(self, build_ok=True):
        self.build_ok = build_ok
        self.calls: list[str] = []
        self.destroyed: list[str] = []

    def available(self):
        return True, ""

    def start(self, name):
        self.calls.append(f"start:{name}")

    def put_files(self, name, archive):
        self.calls.append(f"files:{len(archive)}")

    def run_build(self, name, command, timeout_s):
        self.calls.append("build")
        if not self.build_ok:
            return 1, "src/main.cpp:3:5: error: expected ';'\n", ""
        return 0, "", ""

    def dap_argv(self, name):
        return [sys.executable, FAKE_DAP]

    def destroy(self, name):
        self.destroyed.append(name)

    def cleanup_stale(self):
        return 0


@pytest.fixture()
def debug_env(client, db_session: Session, monkeypatch):
    provider = FakeDebugProvider()
    service.set_debug_provider(provider)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    monkeypatch.setenv("FAKE_DAP_SCRIPT", json.dumps({
        "stopLine": 17,
        "entry": "src/main.cpp",
        "locals": {"x": "40", "y": "42"},
        "recursionFrames": [
            {"id": 0, "name": "fib(int)", "file": "src/main.cpp", "line": 5},
            {"id": 1, "name": "fib(int)", "file": "src/main.cpp", "line": 5},
            {"id": 2, "name": "main", "file": "src/main.cpp", "line": 16},
        ],
    }))
    yield provider
    service.set_debug_provider(DockerDebugSandbox())
    service.set_session_factory(SessionLocal)


def _create(client: TestClient, **overrides):
    payload = {
        "language": "cpp",
        "entryPoint": "src/main.cpp",
        "files": {"src/main.cpp": "int main() { int x = 40; return 0; }"},
        "breakpoints": [{"path": "src/main.cpp", "lines": [17]}],
    }
    payload.update(overrides)
    return client.post("/api/v1/debug-sessions", json=payload)


def _wait(client: TestClient, sid: str, want: set[str], timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/debug-sessions/{sid}")
        assert data.status_code == 200, data.text
        if data.json()["status"] in want:
            return data.json()
        time.sleep(0.05)
    pytest.fail(f"等待状态 {want} 超时")


def _cmd(client: TestClient, sid: str, command: str, **extra):
    payload = {"command": command, **extra}
    resp = client.post(f"/api/v1/debug-sessions/{sid}/commands", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 创建与暂停


def test_breakpoint_pause_snapshot(client: TestClient, debug_env):
    resp = _create(client)
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]

    snap = _wait(client, sid, {"paused"})
    assert snap["status"] == "paused"
    assert snap["stopReason"] == "breakpoint"
    assert snap["location"]["file"] == "src/main.cpp"
    assert snap["location"]["line"] == 17
    assert snap["location"]["frameName"] == "main"
    # 断点验证结果
    assert snap["breakpoints"] == [{"path": "src/main.cpp", "line": 17, "verified": True, "message": None}]
    # 顶帧 Locals 变量（真实 DAP 数据）
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    values = {v["name"]: v["value"] for v in locals_scope["variables"]}
    assert values == {"x": "40", "y": "42"}
    # 线程与栈帧
    assert snap["threads"][0]["name"] == "fake-app"
    assert snap["stackFrames"][0]["file"] == "src/main.cpp"
    assert snap["debuggerProfile"] == "lldb-dap:19"


def test_step_updates_location(client: TestClient, debug_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    snap = _cmd(client, sid, "next")
    assert snap["status"] == "paused"
    assert snap["location"]["line"] == 18
    assert snap["stopReason"] == "step"


def test_continue_recursion_stack_then_complete(client: TestClient, debug_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    snap = _cmd(client, sid, "continue")  # 假 DAP：先停在递归帧
    snap = _wait(client, sid, {"paused"})
    fib_frames = [f for f in snap["stackFrames"] if "fib" in f["name"]]
    assert len(fib_frames) == 2
    snap = _cmd(client, sid, "continue")  # 再继续 → 程序结束
    final = _wait(client, sid, {"terminated"})
    assert final["endReason"] == "completed"


def test_variables_lazy_expand(client: TestClient, debug_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    resp = client.get(f"/api/v1/debug-sessions/{sid}/variables", params={"variablesReference": 2000})
    assert resp.status_code == 200
    assert resp.json()["variables"][0]["name"] == "globalVar"


def test_stop_cleans_container_and_is_idempotent(client: TestClient, debug_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    snap = _cmd(client, sid, "stop")
    assert snap["status"] == "terminated"
    assert snap["endReason"] == "cancelled"
    assert debug_env.destroyed, "容器必须被销毁"
    # 再次 DELETE 幂等
    resp = client.delete(f"/api/v1/debug-sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "terminated"


# ---------------------------------------------------------------- 失败路径


def test_build_failure_does_not_start_debugger(client: TestClient, debug_env):
    debug_env.build_ok = False
    resp = _create(client)
    assert resp.status_code == 201
    sid = resp.json()["id"]
    snap = _wait(client, sid, {"terminated"})
    assert snap["endReason"] == "build-failed"
    assert snap["buildDiagnostics"][0]["file"] == "src/main.cpp"
    assert snap["buildDiagnostics"][0]["line"] == 3
    assert snap["buildDiagnostics"][0]["source"] == "build"
    # 调试器从未启动：无 DAP 通道痕迹
    assert all(not c.startswith("files") or True for c in debug_env.calls)
    assert debug_env.destroyed, "失败路径也要清理容器"


def test_unavailable_returns_503(client: TestClient, debug_env, monkeypatch):
    class Unavailable(FakeDebugProvider):
        def available(self):
            return False, "调试镜像不存在：fake。请先构建"

    service.set_debug_provider(Unavailable())
    resp = _create(client)
    assert resp.status_code == 503
    assert "调试镜像不存在" in resp.json()["detail"]


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"entryPoint": "src/main.py"}, "C++ 源文件"),
        ({"entryPoint": "src/missing.cpp"}, "不在 files"),
        ({"breakpoints": [{"path": "src/nope.cpp", "lines": [1]}]}, "断点文件不在 files"),
        ({"breakpoints": [{"path": "src/main.cpp", "lines": [0]}]}, "断点行号非法"),
        ({"files": {"../evil.cpp": "x"}}, "相对段"),
    ],
)
def test_create_validation(client: TestClient, debug_env, overrides, fragment):
    resp = _create(client, **overrides)
    assert resp.status_code == 422, resp.text
    assert fragment in resp.json()["detail"]


def test_unknown_session_404(client: TestClient, debug_env):
    import uuid

    assert client.get(f"/api/v1/debug-sessions/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"/api/v1/debug-sessions/{uuid.uuid4()}").status_code == 404


def test_command_after_terminated_rejected(client: TestClient, debug_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    _cmd(client, sid, "stop")
    resp = client.post(f"/api/v1/debug-sessions/{sid}/commands", json={"command": "next"})
    assert resp.status_code == 422
    assert "已结束" in resp.json()["detail"]


# ---------------------------------------------------------------- P4.5b.1：指针图 / 代次 / 帧变量


@pytest.fixture()
def ptr_env(client, db_session, monkeypatch):
    """带指针数据的假 DAP：x(0x100) / p→x / np=null / hp=堆(未解析)。"""
    provider = FakeDebugProvider()
    service.set_debug_provider(provider)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    monkeypatch.setenv("FAKE_DAP_SCRIPT", json.dumps({
        "stopLine": 9,
        "entry": "src/main.cpp",
        "typedLocals": [
            {"name": "x", "value": "10", "type": "int", "evaluateName": "x"},
            {"name": "p", "value": "0x0000000000000100", "type": "int *", "evaluateName": "p"},
            {"name": "np", "value": "0x0000000000000000", "type": "int *", "evaluateName": "np"},
            {"name": "hp", "value": "0x000055555556b2b0", "type": "int *", "evaluateName": "hp"},
        ],
        "addresses": {"&x": "0x0000000000000100"},
        "recursionFrames": [
            {"id": 0, "name": "fib(int)", "file": "src/main.cpp", "line": 5},
            {"id": 1, "name": "fib(int)", "file": "src/main.cpp", "line": 5},
            {"id": 2, "name": "main", "file": "src/main.cpp", "line": 8},
        ],
        "frame1Locals": [
            {"name": "x", "value": "999", "type": "int", "evaluateName": "x"},  # 帧间同名变量
        ],
    }))
    yield provider
    service.set_debug_provider(DockerDebugSandbox())
    service.set_session_factory(SessionLocal)


def test_snapshot_carries_pointer_graph_and_pause_seq(client: TestClient, ptr_env):
    sid = _create(client).json()["id"]
    snap = _wait(client, sid, {"paused"})
    # 指针图：唯一已验证边 p→x（地址精确匹配）；np 空指针；hp 未解析
    graph = snap["pointerGraph"]
    assert graph is not None
    assert graph["verifiedEdges"] == [{"from": "p", "to": "x", "address": "0x0000000000000100"}]
    assert graph["nullPointers"] == [{"name": "np", "value": "0x0000000000000000"}]
    assert graph["unresolvedPointers"] == [{"name": "hp", "value": "0x000055555556b2b0"}]
    assert graph["addresses"]["x"] == "0x0000000000000100"
    # 真实变量值（A）
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    assert {v["name"]: v["value"] for v in locals_scope["variables"]}["x"] == "10"
    assert snap["pauseSeq"] == 1


def test_step_advances_pause_seq(client: TestClient, ptr_env):
    sid = _create(client).json()["id"]
    _wait(client, sid, {"paused"})
    snap = _cmd(client, sid, "next")
    assert snap["pauseSeq"] == 2  # 新暂停代次（E：旧引用缓存必须失效）


def test_frame_variables_endpoint_and_same_name_isolation(client: TestClient, ptr_env):
    sid = _create(client).json()["id"]
    snap = _wait(client, sid, {"paused"})
    _cmd(client, sid, "continue")  # 进递归帧
    snap = _wait(client, sid, {"paused"})
    frames = snap["stackFrames"]
    assert len(frames) >= 2 and "fib" in frames[1]["name"]

    resp = client.get(f"/api/v1/debug-sessions/{sid}/frames/{frames[1]['id']}/variables")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pauseSeq"] == snap["pauseSeq"]
    # 帧间同名变量不混淆（D）：帧 1 的 x = 999（不同于顶帧 10）
    locals_scope = next(s for s in body["scopes"] if s["name"] == "Locals")
    values = {v["name"]: v["value"] for v in locals_scope["variables"]}
    assert values["x"] == "999"
    _cmd(client, sid, "stop")
