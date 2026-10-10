"""C++ 内存/指针可视化真实 E2E（P4.5b.1，选入 PW_SANDBOX_E2E=1）。

验收 A-J（真实 LLDB，非模拟）：
A 真实值 / B p→x 已验证 / C *p=20 后 x 更新 / D 递归帧同名隔离 /
E 代次递增（旧引用失效）/ F 堆指针未解析 / G 空指针状态 /
H 运行中不冒充实时（API 侧）/ I 结束清理 / J（由全量回归覆盖）。
"""

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import SessionLocal
from app.domains.debugging import service

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1 与镜像 projectweave-sandbox-cpp-debug:clang19-trixie",
)

CPP = """#include <cstdio>

int fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int main() {
    int x = 10;
    int* p = &x;
    int* np = nullptr;
    int* hp = new int(5);
    *p = 20;
    int f = fib(2);
    printf("%d %d %d", x, *hp, f);
    return 0;
}
"""


@pytest.fixture()
def e2e_client(client: TestClient, db_session):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    yield client
    service.set_session_factory(SessionLocal)


def _create(client: TestClient, lines: list[int]):
    resp = client.post("/api/v1/debug-sessions", json={
        "language": "cpp", "entryPoint": "src/main.cpp",
        "files": {"src/main.cpp": CPP},
        "breakpoints": [{"path": "src/main.cpp", "lines": lines}],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _wait_pause(client: TestClient, sid: str, prev_seq: int = 0, timeout_s: float = 120.0) -> dict:
    """等待新的暂停（pauseSeq > prev_seq）——不把上一次暂停误当新状态。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snap = client.get(f"/api/v1/debug-sessions/{sid}").json()
        if snap["status"] == "paused" and snap["pauseSeq"] > prev_seq:
            return snap
        if snap["status"] == "terminated":
            pytest.fail(f"会话提前终止：{snap['endReason']} {snap['error']}")
        time.sleep(0.3)
    pytest.fail("等待新暂停超时")


def _cmd(client: TestClient, sid: str, command: str) -> dict:
    resp = client.post(f"/api/v1/debug-sessions/{sid}/commands", json={"command": command})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _leftovers() -> list[str]:
    proc = subprocess.run(["docker", "ps", "-aq", "--filter", "label=pw.debug=1"],
                          capture_output=True, text=True, timeout=20)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_a_b_c_f_g_real_values_edges_and_states(e2e_client: TestClient):
    sid = _create(e2e_client, [13])  # *p = 20; 行（此前 x/p/np/hp 已初始化）
    snap = _wait_pause(e2e_client, sid)
    seq = snap["pauseSeq"]

    # A：真实值
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    values = {v["name"]: v["value"] for v in locals_scope["variables"]}
    assert values["x"] == "10"
    graph = snap["pointerGraph"]
    assert graph is not None

    # B：p→x 已验证（地址精确匹配）
    assert graph["verifiedEdges"] == [
        {"from": "p", "to": "x", "address": graph["addresses"]["x"]}
    ]
    assert graph["addresses"]["x"] is not None

    # G：空指针显式状态
    assert any(n["name"] == "np" for n in graph["nullPointers"])

    # F：堆指针未解析（不虚构关系）
    assert any(n["name"] == "hp" for n in graph["unresolvedPointers"])
    assert all(e["from"] != "hp" for e in graph["verifiedEdges"])

    # C：单步执行 *p=20 → x=20（同一地址，新代次）
    snap = _cmd(e2e_client, sid, "next")
    snap = _wait_pause(e2e_client, sid, prev_seq=seq)
    locals_scope = next(s for s in snap["scopes"] if s["name"] == "Locals")
    values = {v["name"]: v["value"] for v in locals_scope["variables"]}
    assert values["x"] == "20"
    assert snap["pointerGraph"]["verifiedEdges"][0]["to"] == "x"

    # E：代次递增
    assert snap["pauseSeq"] > seq

    # I：停止清理
    _cmd(e2e_client, sid, "stop")
    time.sleep(1.0)
    assert _leftovers() == []


def test_d_recursion_same_name_variables_distinct(e2e_client: TestClient):
    sid = _create(e2e_client, [4])  # fib 入口行：每个递归层级都会停
    snap = _wait_pause(e2e_client, sid)
    # continue 进入更深递归（fib(2) → fib(1)）
    _cmd(e2e_client, sid, "continue")
    snap = _wait_pause(e2e_client, sid, prev_seq=snap["pauseSeq"])
    frames = snap["stackFrames"]
    fib_frames = [f for f in frames if "fib" in f["name"]]
    if len(fib_frames) < 2:
        # fib(2) 的第一个断点在自身行，再 continue 进 fib(1)
        _cmd(e2e_client, sid, "continue")
        snap = _wait_pause(e2e_client, sid, prev_seq=snap["pauseSeq"])
        frames = snap["stackFrames"]
        fib_frames = [f for f in frames if "fib" in f["name"]]
    assert len(fib_frames) >= 2, frames

    # 两帧的 n 独立取值（真实不同深度）
    values = []
    for frame in fib_frames[:2]:
        resp = e2e_client.get(f"/api/v1/debug-sessions/{sid}/frames/{frame['id']}/variables")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pauseSeq"] == snap["pauseSeq"]
        locals_scope = next(s for s in body["scopes"] if s["name"] == "Locals")
        n = next(v for v in locals_scope["variables"] if v["name"] == "n")
        values.append(n["value"])
    assert values[0] != values[1], f"递归两帧同名变量 n 应取不同真实值：{values}"
    _cmd(e2e_client, sid, "stop")


def test_h_running_state_not_claimed_as_live(e2e_client: TestClient):
    """运行中快照：状态=running 且 pauseSeq 不变——旧暂停数据不冒充新状态。"""
    sid = _create(e2e_client, [13])
    snap = _wait_pause(e2e_client, sid)
    seq = snap["pauseSeq"]
    # 断点改到 fib 行后 continue → 程序将在断点前长时间运行（这里用立即查询）
    _cmd(e2e_client, sid, "setBreakpoints", breakpoints=[{"path": "src/main.cpp", "lines": [5]}]) \
        if False else None
    # 简化：把断点移到 fib 后 continue；在程序运行窗口内立即查询状态
    resp = e2e_client.post(f"/api/v1/debug-sessions/{sid}/commands", json={
        "command": "setBreakpoints",
        "breakpoints": [{"path": "src/main.cpp", "lines": [5]}],
    })
    assert resp.status_code == 200
    resp = e2e_client.post(f"/api/v1/debug-sessions/{sid}/commands", json={"command": "continue"})
    snap = resp.json()
    # continue 后要么 running（快照 pauseSeq 不变=历史），要么已再次 paused（新代次）
    if snap["status"] == "running":
        assert snap["pauseSeq"] == seq, "运行中不得伪造新代次"
    else:
        assert snap["pauseSeq"] > seq
    _cmd(e2e_client, sid, "stop")
    time.sleep(1.0)
    assert _leftovers() == []
