"""调试沙箱真实端到端验收（选入：PW_SANDBOX_E2E=1）。

覆盖任务验收 A-H（真实 LLDB DAP，非模拟）：
A 指定源码行暂停 / B 单步更新 / C 局部变量真实值 / D 递归多栈帧 /
E 多文件断点（跨 .cpp）/ F 编译失败不启动调试器 / G 停止后容器清理 /
H 空闲超时回收。
前置：docker build -t projectweave-sandbox-cpp-debug:clang19-trixie backend/sandbox/cpp-debug
"""

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import SessionLocal
from app.domains.debugging import service
from app.domains.debugging.debug_sandbox import DockerDebugSandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="调试 E2E 需 PW_SANDBOX_E2E=1 与镜像 projectweave-sandbox-cpp-debug:clang19-trixie",
)

CPP = """#include <cstdio>

int fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int add(int a, int b) {
    int r = a + b;
    return r;
}

int main() {
    int x = 40;
    int y = add(x, 2);
    int f = fib(4);
    printf("y=%d f=%d\\n", y, f);
    return 0;
}
"""


@pytest.fixture()
def e2e_client(client: TestClient, db_session):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    yield client
    service.set_session_factory(SessionLocal)


def _leftovers() -> list[str]:
    proc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=pw.debug=1"],
        capture_output=True, text=True, timeout=20,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _create(client: TestClient, **overrides):
    payload = {
        "language": "cpp",
        "entryPoint": "src/main.cpp",
        "files": {"src/main.cpp": CPP},
        "breakpoints": [{"path": "src/main.cpp", "lines": [17]}],
    }
    payload.update(overrides)
    resp = client.post("/api/v1/debug-sessions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, sid: str, want: set[str], timeout_s: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/debug-sessions/{sid}")
        assert data.status_code == 200
        snap = data.json()
        last = snap["status"]
        if last in want:
            return snap
        if last == "terminated" and "terminated" not in want:
            return snap
        time.sleep(0.3)
    pytest.fail(f"等待 {want} 超时（最后 {last}）")


def _cmd(client: TestClient, sid: str, command: str) -> dict:
    resp = client.post(f"/api/v1/debug-sessions/{sid}/commands", json={"command": command})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_b_c_breakpoint_step_real_locals(e2e_client: TestClient):
    sid = _create(e2e_client)
    snap = _wait(e2e_client, sid, {"paused"})
    # A：在指定源码行暂停
    assert snap["stopReason"] == "breakpoint"
    assert snap["location"] == {"file": "src/main.cpp", "line": 17, "column": snap["location"]["column"], "frameName": "main"}
    assert snap["breakpoints"][0]["verified"] is True
    # C：局部变量与真实程序一致（y=42、f=3=fib(4) 已执行）
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    values = {v["name"]: v["value"] for v in locals_scope["variables"]}
    assert values["x"] == "40" and values["y"] == "42" and values["f"] == "3"
    # B：单步后当前行更新
    snap = _cmd(e2e_client, sid, "next")
    assert snap["location"]["line"] == 18
    # 清理
    _cmd(e2e_client, sid, "stop")
    _wait(e2e_client, sid, {"terminated"})


def test_d_recursion_stack(e2e_client: TestClient):
    sid = _create(e2e_client, breakpoints=[{"path": "src/main.cpp", "lines": [5]}])
    snap = _wait(e2e_client, sid, {"paused"})
    snap = _cmd(e2e_client, sid, "continue")
    snap = _wait(e2e_client, sid, {"paused"})
    fib_frames = [f for f in snap["stackFrames"] if "fib" in f["name"]]
    assert len(fib_frames) >= 2, snap["stackFrames"]
    assert fib_frames[0]["file"] == "src/main.cpp"
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    assert any(v["name"] == "n" for v in locals_scope["variables"])
    _cmd(e2e_client, sid, "stop")


def test_e_multi_file_breakpoints(e2e_client: TestClient):
    files = {
        "src/math.hpp": "#pragma once\nint add(int a, int b);\n",
        "src/math.cpp": '#include "math.hpp"\nint add(int a, int b) { int r = a + b; return r; }\n',
        "src/main.cpp": (
            '#include <cstdio>\n#include "math.hpp"\n'
            "int main() { int y = add(40, 2); printf(\"%d\\n\", y); return 0; }\n"
        ),
    }
    sid = _create(
        e2e_client, files=files,
        breakpoints=[{"path": "src/main.cpp", "lines": [3]}, {"path": "src/math.cpp", "lines": [2]}],
    )
    snap = _wait(e2e_client, sid, {"paused"})
    assert snap["location"]["file"] == "src/main.cpp" and snap["location"]["line"] == 3
    snap = _cmd(e2e_client, sid, "continue")
    snap = _wait(e2e_client, sid, {"paused"})
    # 跨文件断点：math.cpp 内暂停，栈帧包含 add + main
    assert snap["location"]["file"] == "src/math.cpp" and snap["location"]["line"] == 2
    names = [f["name"] for f in snap["stackFrames"]]
    assert any("add" in n for n in names) and any(n == "main" for n in names)
    _cmd(e2e_client, sid, "stop")


def test_f_build_failure_no_debugger(e2e_client: TestClient):
    sid = _create(e2e_client, files={"src/main.cpp": "int main() { return 0 "})
    snap = _wait(e2e_client, sid, {"terminated"})
    assert snap["endReason"] == "build-failed"
    assert snap["buildDiagnostics"][0]["source"] == "build"
    assert snap["buildDiagnostics"][0]["file"] == "src/main.cpp"
    assert snap["dapLog"] == [], "编译失败不得启动调试器"
    time.sleep(1.0)
    assert _leftovers() == []


def test_g_stop_cleans_container(e2e_client: TestClient):
    sid = _create(e2e_client, files={"src/main.cpp": CPP.replace("fib(4)", "fib(9)")})
    _wait(e2e_client, sid, {"paused"})
    _cmd(e2e_client, sid, "stop")
    snap = _wait(e2e_client, sid, {"terminated"})
    assert snap["endReason"] == "cancelled"
    time.sleep(1.0)
    assert _leftovers() == [], "停止后调试容器必须清理"


def test_h_idle_timeout_reclaims(e2e_client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "debug_idle_timeout_seconds", 3)
    sid = _create(e2e_client)
    _wait(e2e_client, sid, {"paused"})
    # 模拟浏览器断连：完全停止访问 → 空闲超时回收（轮询即活动，断连后不再续期）
    time.sleep(8)
    resp = e2e_client.get(f"/api/v1/debug-sessions/{sid}")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["status"] == "terminated"
    assert snap["endReason"] == "timeout"
    assert "空闲超时" in (snap["error"] or "")
    time.sleep(1.0)
    assert _leftovers() == [], "超时回收后容器必须清理"
