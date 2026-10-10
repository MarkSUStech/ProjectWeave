"""Docker 沙箱真实端到端验收（选入：PW_SANDBOX_E2E=1）。

覆盖任务书验收场景 A-G / J（H 由单元测试的 FakeSandbox 覆盖；I 由前端套件覆盖）。
前置：Docker 运行中 + 镜像已构建：
    docker build -t projectweave-sandbox-python:3.12 backend/sandbox/python
"""

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.executions import service
from app.domains.executions.sandbox.docker_sandbox import LABEL_KEY

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="Docker 沙箱 E2E 需 PW_SANDBOX_E2E=1 与已构建镜像 projectweave-sandbox-python:3.12",
)

IMAGE = "projectweave-sandbox-python:3.12"


@pytest.fixture()
def e2e_client(client: TestClient, db_session):
    """真实 Docker 沙箱 + 临时库会话工厂（worker 线程写入同一临时库）。"""
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    yield client
    from app.core.db import SessionLocal

    service.set_session_factory(SessionLocal)


def _leftover_containers() -> list[str]:
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"label={LABEL_KEY}=1", "-q"],
        capture_output=True, text=True, timeout=20,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _create(client: TestClient, **overrides):
    payload = {
        "language": "python",
        "mode": "run",
        "entryPoint": "main.py",
        "files": {"main.py": "print('hi')"},
        "timeoutMs": 15000,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/executions", json=payload)
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, exec_id: str, timeout_s: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/executions/{exec_id}").json()
        if data["status"] in {"completed", "failed", "timed-out", "cancelled"}:
            return data
        time.sleep(0.2)
    pytest.fail("执行未在期限内到达终态")


# ---------------------------------------------------------------- A/B/C 运行


def test_a_hello_run(e2e_client: TestClient):
    exec_id = _create(e2e_client, files={"hello.py": "print('hello world')"}, entryPoint="hello.py")
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "hello world" in final["stdout"]
    assert final["sandbox"]["engine"] == "docker"
    assert final["sandbox"]["image"] == IMAGE
    assert final["sandbox"]["trustLevel"] == "practice"


def test_b_multi_file_import(e2e_client: TestClient):
    files = {
        "utils.py": "def add(a, b):\n    return a + b\n",
        "main.py": "from utils import add\nprint(add(2, 3))\n",
    }
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "5" in final["stdout"]


def test_c_stdin(e2e_client: TestClient):
    files = {"main.py": "name = input()\nprint(f'hello, {name}!')\n"}
    final = _wait(
        e2e_client,
        _create(e2e_client, files=files, stdin="ProjectWeave"),
    )
    assert final["status"] == "completed"
    assert "hello, ProjectWeave!" in final["stdout"]


def test_traceback_maps_file_and_line(e2e_client: TestClient):
    files = {"main.py": "x = 1\ny = 2\nraise ValueError('boom')\n"}
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert final["status"] == "completed"  # 执行跑完，程序失败是业务结果
    assert final["exitCode"] == 1
    diag = final["diagnostics"][0]
    assert diag["file"] == "main.py"
    assert diag["line"] == 3
    assert "ValueError" in diag["message"]


# ---------------------------------------------------------------- D/E pytest


def test_d_pytest_success(e2e_client: TestClient):
    files = {
        "mathlib.py": "def add(a, b):\n    return a + b\n",
        "test_mathlib.py": (
            "from mathlib import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_zero():\n"
            "    assert add(0, 0) == 0\n"
        ),
    }
    exec_id = _create(e2e_client, mode="test", entryPoint=None, testPaths=["test_mathlib.py"], files=files)
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    results = final["testResults"]
    assert len(results) == 1
    assert results[0]["status"] == "passed"
    assert {case["name"].split("::")[-1] for case in results[0]["cases"]} == {"test_add", "test_zero"}
    assert all(case["status"] == "passed" for case in results[0]["cases"])


def test_e_pytest_failure_shows_assertion_and_location(e2e_client: TestClient):
    files = {
        "mathlib.py": "def add(a, b):\n    return a - b  # 故意写错\n",
        "test_mathlib.py": (
            "from mathlib import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        ),
    }
    exec_id = _create(e2e_client, mode="test", entryPoint=None, testPaths=["test_mathlib.py"], files=files)
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "completed"
    assert final["exitCode"] != 0
    results = final["testResults"]
    assert results[0]["status"] == "failed"
    case = results[0]["cases"][0]
    assert case["status"] == "failed"
    assert case["file"] == "test_mathlib.py"
    assert case["line"] == 4
    assert "assert" in (case["error"] or "")
    # 诊断同步带文件/行号（教学面板与 AI 上下文用）
    diag = final["diagnostics"][0]
    assert diag["file"] == "test_mathlib.py"
    assert diag["line"] == 4
    assert diag["source"] == "test"


def test_pytest_collection_error(e2e_client: TestClient):
    files = {"broken_test.py": "import no_such_module_xyz\n\ndef test_x():\n    pass\n"}
    exec_id = _create(e2e_client, mode="test", entryPoint=None, testPaths=["broken_test.py"], files=files)
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "completed"
    results = final["testResults"]
    assert results[0]["status"] == "error"
    assert "no_such_module_xyz" in (results[0]["error"] or "")


# ---------------------------------------------------------------- F/G 限制


def test_f_infinite_loop_times_out_and_cleans(e2e_client: TestClient):
    files = {"loop.py": "while True:\n    pass\n"}
    exec_id = _create(e2e_client, files=files, entryPoint="loop.py", timeoutMs=4000)
    final = _wait(e2e_client, exec_id, timeout_s=60)
    assert final["status"] == "timed-out"
    assert final["timedOut"] is True
    # 整个环境（容器）被终止并清理，不遗留
    time.sleep(1.0)
    assert _leftover_containers() == [], "超时后不应遗留沙箱容器"


def test_g_host_files_and_network_blocked(e2e_client: TestClient):
    files = {
        "probe.py": (
            "import socket\n"
            "# 1) 宿主敏感文件：非 root + 只读根\n"
            "try:\n"
            "    with open('/etc/shadow') as f:\n"
            "        f.read()\n"
            "    print('SHADOW_OK')\n"
            "except PermissionError:\n"
            "    print('SHADOW_DENIED')\n"
            "except OSError as e:\n"
            "    print('SHADOW_ERR:' + type(e).__name__)\n"
            "# 2) 网络：--network none\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
            "    print('NETWORK_OK')\n"
            "except OSError as e:\n"
            "    print('BLOCKED:' + type(e).__name__)\n"
        ),
    }
    final = _wait(e2e_client, _create(e2e_client, files=files, entryPoint="probe.py"))
    assert final["status"] == "completed"
    assert "SHADOW_OK" not in final["stdout"]
    assert "SHADOW_DENIED" in final["stdout"] or "SHADOW_ERR" in final["stdout"]
    assert "NETWORK_OK" not in final["stdout"]
    assert "BLOCKED:" in final["stdout"]


def test_g_rootfs_readonly(e2e_client: TestClient):
    files = {"w.py": "open('/etc/pwned', 'w').write('x')\n"}
    final = _wait(e2e_client, _create(e2e_client, files=files, entryPoint="w.py"))
    assert final["status"] == "completed"
    assert final["exitCode"] != 0
    assert "Error" in final["stderr"]


# ---------------------------------------------------------------- J 取消


def test_j_cancel_running(e2e_client: TestClient):
    files = {"slow.py": "import time\nprint('started', flush=True)\ntime.sleep(60)\n"}
    exec_id = _create(e2e_client, files=files, entryPoint="slow.py", timeoutMs=30000)
    # 等待真实输出出现，确认在运行
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        data = e2e_client.get(f"/api/v1/executions/{exec_id}").json()
        if "started" in data["stdout"]:
            break
        time.sleep(0.2)
    assert "started" in e2e_client.get(f"/api/v1/executions/{exec_id}").json()["stdout"]

    resp = e2e_client.post(f"/api/v1/executions/{exec_id}/cancel")
    assert resp.status_code == 200
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "cancelled"
    # 被取消的环境不继续运行、不遗留
    time.sleep(1.0)
    assert _leftover_containers() == [], "取消后不应遗留沙箱容器"
    # 再次取消幂等
    again = e2e_client.post(f"/api/v1/executions/{exec_id}/cancel")
    assert again.json()["status"] == "cancelled"
