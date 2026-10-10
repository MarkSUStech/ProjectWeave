"""执行会话 API 测试（FakeSandbox 注入，无需 Docker）。

验证：状态机、校验/上限、503、取消、增量事件、execution-finished 事件。
"""

import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.domains.executions import service
from app.domains.executions.sandbox.base import SandboxResult


class FakeSandbox:
    """协议兼容的假沙箱：handler(spec, cancel_event, on_output) → SandboxResult。"""

    engine = "fake"

    def __init__(self):
        self.runs: list = []
        self.handler = None
        self.unavailable = False
        self.cleanup_calls = 0

    def available(self):
        if self.unavailable:
            return False, "假沙箱被禁用"
        return True, ""

    def run(self, spec, cancel_event, on_output=None):
        self.runs.append(spec)
        if self.handler is not None:
            return self.handler(spec, cancel_event, on_output)
        return SandboxResult(
            exit_code=0,
            stdout="hello\n"
            + '===PW_RESULT==={"kind": "run", "exitCode": 0, "timedOut": false}\n',
            stderr="",
            started=True,
            engine=self.engine,
            image=spec.image,
        )

    def cleanup_stale(self):
        self.cleanup_calls += 1
        return 0


def _ok_run_result(stdout="hello\n", marker_exit=0):
    marker = f'{{"kind": "run", "exitCode": {marker_exit}, "timedOut": false}}'
    return SandboxResult(
        exit_code=marker_exit,
        stdout=stdout + "===PW_RESULT===" + marker + "\n",
        stderr="",
        started=True,
        engine="fake",
        image="fake-image",
    )


@pytest.fixture()
def fake_sandbox(client, db_session: Session):
    sandbox = FakeSandbox()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_sandbox_manager(sandbox)
    service.set_session_factory(factory)
    yield sandbox
    service.set_sandbox_manager(service.DockerSandboxManager())
    from app.core.db import SessionLocal

    service.set_session_factory(SessionLocal)


def _wait_terminal(client: TestClient, exec_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/executions/{exec_id}")
        assert resp.status_code == 200, resp.text
        if resp.json()["status"] in {"completed", "failed", "timed-out", "cancelled"}:
            return resp.json()
        time.sleep(0.05)
    pytest.fail("执行未在期限内到达终态")


def _create(client: TestClient, **overrides) -> object:
    payload = {
        "language": "python",
        "mode": "run",
        "entryPoint": "src/main.py",
        "files": {"src/main.py": "print('hi')"},
        "timeoutMs": 5000,
    }
    payload.update(overrides)
    return client.post("/api/v1/executions", json=payload)


# ---------------------------------------------------------------- 正常路径


def test_create_and_complete_run(client: TestClient, fake_sandbox):
    resp = _create(client)
    assert resp.status_code == 202, resp.text
    exec_id = resp.json()["id"]
    assert resp.json()["status"] in {"queued", "preparing", "running"}

    final = _wait_terminal(client, exec_id)
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "hello" in final["stdout"]
    assert final["sandbox"]["engine"] == "fake"
    # 服务端执行 ≠ 正式认证：信任级固定 practice（D32）
    assert final["sandbox"]["trustLevel"] == "practice"
    assert final["events"], "输出事件流不应为空"
    assert final["events"][0]["seq"] >= 1
    assert final["runTimeMs"] >= 0
    # 沙箱规格：资源限制与超时已传递
    spec = fake_sandbox.runs[0]
    assert spec.timeout_s == 5.0
    assert spec.env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_program_failure_is_completed_not_failed(client: TestClient, fake_sandbox):
    """程序退出码非 0：会话仍 completed（执行跑完），退出码与诊断如实呈现。"""
    fake_sandbox.handler = lambda spec, cancel, on_output: _ok_run_result(marker_exit=1)
    resp = _create(client)
    final = _wait_terminal(client, resp.json()["id"])
    assert final["status"] == "completed"
    assert final["exitCode"] == 1


def test_execution_finished_event_appended(client: TestClient, fake_sandbox, db_session: Session):
    from app.domains.projects.schemas import ProjectCreate
    from app.domains.projects.service import create_project
    from tests.conftest import VALID_CREATE_PAYLOAD

    project = create_project(db_session, ProjectCreate(**VALID_CREATE_PAYLOAD))
    resp = _create(client, projectId=str(project.id))
    exec_id = resp.json()["id"]
    _wait_terminal(client, exec_id)
    time.sleep(0.2)  # 事件在终态提交后写入
    events = client.get(
        "/api/v1/events", params={"projectId": str(project.id), "type": "execution-finished"}
    ).json()["items"]
    assert any(item["payload"].get("executionId") == exec_id for item in events)
    payload = next(item["payload"] for item in events if item["payload"].get("executionId") == exec_id)
    assert payload["status"] == "completed"
    assert payload["trustLevel"] == "practice"
    assert payload["language"] == "python"


# ---------------------------------------------------------------- 校验失败 422


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"language": "rust"}, "不支持的语言"),
        ({"files": {"../evil.py": "x"}}, "相对段"),
        ({"files": {"/abs.py": "x"}, "entryPoint": "/abs.py"}, "绝对路径"),
        ({"files": {"src/ma:in.py": "x"}, "entryPoint": "src/ma:in.py"}, "非法字符"),
        ({"files": {"__pw/manifest.json": "x"}}, "保留命名空间"),
        ({"entryPoint": "src/missing.py"}, "不在 files"),
        ({"files": {"src/main.js": "x"}}, ".py"),
        ({"timeoutMs": 60000}, "超时上限"),
        ({"mode": "test", "entryPoint": None, "testPaths": []}, "testPaths"),
        ({"stdin": "x" * 70000}, "stdin"),
    ],
)
def test_create_validation_rejections(client: TestClient, fake_sandbox, overrides, fragment):
    resp = _create(client, **overrides)
    assert resp.status_code == 422, resp.text
    assert fragment in resp.json()["detail"]


def test_create_rejects_too_many_files(client: TestClient, fake_sandbox):
    files = {f"src/f{i}.py": "x" for i in range(201)}
    resp = _create(client, files=files, entryPoint="src/f0.py")
    assert resp.status_code == 422
    assert "文件数超上限" in resp.json()["detail"]


def test_create_rejects_total_size(client: TestClient, fake_sandbox):
    files = {f"src/f{i}.py": "x" * 100_000 for i in range(50)}
    resp = _create(client, files=files, entryPoint="src/f0.py")
    assert resp.status_code == 422
    assert "总大小" in resp.json()["detail"]


# ---------------------------------------------------------------- 不可用 503


def test_sandbox_unavailable_returns_503(client: TestClient, fake_sandbox):
    fake_sandbox.unavailable = True
    resp = _create(client)
    assert resp.status_code == 503
    assert "假沙箱被禁用" in resp.json()["detail"]


def test_execution_disabled_returns_422(client: TestClient, fake_sandbox, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "execution_enabled", False)
    resp = _create(client)
    assert resp.status_code == 422
    assert "禁用" in resp.json()["detail"]


# ---------------------------------------------------------------- 终态异常


def test_timeout_marks_timed_out(client: TestClient, fake_sandbox):
    fake_sandbox.handler = lambda spec, cancel, on_output: SandboxResult(
        exit_code=137, stdout="", stderr="", started=True, timed_out=True, killed=True
    )
    resp = _create(client)
    final = _wait_terminal(client, resp.json()["id"])
    assert final["status"] == "timed-out"
    assert final["timedOut"] is True


def test_sandbox_start_failure_marks_failed(client: TestClient, fake_sandbox):
    fake_sandbox.handler = lambda spec, cancel, on_output: SandboxResult(
        exit_code=None, stdout="", stderr="docker: permission denied", started=False
    )
    resp = _create(client)
    final = _wait_terminal(client, resp.json()["id"])
    assert final["status"] == "failed"
    assert "permission denied" in final["error"]


def test_protocol_error_marks_failed(client: TestClient, fake_sandbox):
    fake_sandbox.handler = lambda spec, cancel, on_output: SandboxResult(
        exit_code=1, stdout="no marker here", stderr="", started=True
    )
    final = _wait_terminal(client, _create(client).json()["id"])
    assert final["status"] == "failed"
    assert "结果标记" in final["error"]


# ---------------------------------------------------------------- 取消


def test_cancel_running_execution(client: TestClient, fake_sandbox):
    started = threading.Event()

    def slow_handler(spec, cancel_event, on_output):
        started.set()
        if on_output:
            on_output("stdout", "working...\n")
        # 模拟长任务：等待取消信号（服务层会设置它）
        for _ in range(100):
            if cancel_event.is_set():
                return SandboxResult(
                    exit_code=137, stdout="working...\n", stderr="", started=True, killed=True,
                    engine="fake", image=spec.image,
                )
            time.sleep(0.05)
        return _ok_run_result()

    fake_sandbox.handler = slow_handler
    resp = _create(client, timeoutMs=8000)
    exec_id = resp.json()["id"]
    assert started.wait(timeout=3)

    cancel_resp = client.post(f"/api/v1/executions/{exec_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    assert cancel_resp.json()["alreadyFinished"] is False

    final = _wait_terminal(client, exec_id)
    assert final["status"] == "cancelled"
    assert final["cancelled"] is True


def test_cancel_finished_is_idempotent(client: TestClient, fake_sandbox):
    exec_id = _create(client).json()["id"]
    _wait_terminal(client, exec_id)
    resp = client.post(f"/api/v1/executions/{exec_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["alreadyFinished"] is True
    assert resp.json()["status"] == "completed"


# ---------------------------------------------------------------- 查询


def test_get_unknown_returns_404(client: TestClient):
    assert client.get(f"/api/v1/executions/{uuid.uuid4()}").status_code == 404
    assert client.post(f"/api/v1/executions/{uuid.uuid4()}/cancel").status_code == 404


def test_after_seq_incremental_events(client: TestClient, fake_sandbox):
    def multi_output(spec, cancel_event, on_output):
        if on_output:
            on_output("stdout", "line-1\n")
            on_output("stdout", "line-2\n")
        return _ok_run_result(stdout="")

    fake_sandbox.handler = multi_output
    exec_id = _create(client).json()["id"]
    final = _wait_terminal(client, exec_id)
    seqs = [event["seq"] for event in final["events"]]
    assert seqs == sorted(seqs)
    last = seqs[-1]
    # 增量读取：只返回新事件
    resp = client.get(f"/api/v1/executions/{exec_id}", params={"afterSeq": last - 1})
    assert resp.status_code == 200
    assert [event["seq"] for event in resp.json()["events"]] == [last]


def test_output_truncated_at_cap(client: TestClient, fake_sandbox, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "execution_output_max_chars", 1000)
    fake_sandbox.handler = lambda spec, cancel, on_output: _ok_run_result(stdout="x" * 5000)
    final = _wait_terminal(client, _create(client).json()["id"])
    assert len(final["stdout"]) < 1100
    assert "已截断" in final["stdout"]
