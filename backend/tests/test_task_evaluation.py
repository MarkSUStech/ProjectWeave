"""阶段验收测试：确定性判定、依赖闸门、application 维证据与事件。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.concepts.service import ensure_seed_concepts
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD


@pytest.fixture()
def eval_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def setup_project(client: TestClient, stack: list[str] | None = None) -> tuple[str, dict]:
    pid = client.post(
        "/api/v1/projects",
        json=dict(VALID_CREATE_PAYLOAD, stack=stack or ["TypeScript", "React"]),
    ).json()["id"]
    # 生成学习路线（同时种子任务图）
    detail = client.get(f"/api/v1/plans/{pid}").json()
    return pid, {t["taskId"]: t for t in detail["tasks"]}


GREEN = {"totalFiles": 1, "totalPassed": 3, "totalFailed": 0, "errorFiles": 0, "traceId": "t-1"}


def evaluate(client: TestClient, pid: str, task_id: str, suite: dict):
    return client.post(f"/api/v1/projects/{pid}/tasks/{task_id}/evaluate", json=suite)


def test_green_suite_marks_done_and_writes_application_evidence(eval_client: TestClient):
    pid, tasks = setup_project(eval_client)
    assert tasks["task-scaffold"]["status"] == "pending"

    resp = evaluate(eval_client, pid, "task-scaffold", GREEN)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is True
    assert body["status"] == "done"
    assert body["rubricVersion"] == "suite-green-v1"
    assert body["evidenceConcepts"] == ["browser.dom"]

    # application 维首次出现真实估计（coding 证据，D19 映射）
    mastery = {
        m["conceptId"]: m for m in eval_client.get("/api/v1/mastery").json()["items"]
    }
    dom = mastery["browser.dom"]["dimensions"]
    assert "application" in dom
    assert dom["application"]["estimate"] == 1.0
    assert dom["application"]["evidenceCount"] == 1

    # 任务状态经计划接口可见
    tasks_after = {
        t["taskId"]: t for t in eval_client.get(f"/api/v1/plans/{pid}").json()["tasks"]
    }
    assert tasks_after["task-scaffold"]["status"] == "done"

    # 事件
    events = eval_client.get(
        f"/api/v1/events?projectId={pid}&type=task-evaluated"
    ).json()
    assert events["total"] == 1
    assert events["items"][0]["payload"]["taskId"] == "task-scaffold"
    assert events["items"][0]["payload"]["passed"] is True


def test_failing_suite_marks_needs_fix_and_records_failed_evidence(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    red = {"totalFiles": 1, "totalPassed": 1, "totalFailed": 2, "errorFiles": 0, "traceId": "t-2"}
    resp = evaluate(eval_client, pid, "task-scaffold", red)
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is False and body["status"] == "needs-fix"

    # 失败同样是证据：application 估计如实下降
    dom = {
        m["conceptId"]: m
        for m in eval_client.get("/api/v1/mastery").json()["items"]
    }["browser.dom"]["dimensions"]
    assert dom["application"]["estimate"] == 0.0

    # 修复后重新验收 → done，证据累积
    evaluate(eval_client, pid, "task-scaffold", GREEN)
    dom2 = {
        m["conceptId"]: m
        for m in eval_client.get("/api/v1/mastery").json()["items"]
    }["browser.dom"]["dimensions"]
    assert dom2["application"]["evidenceCount"] == 2
    assert dom2["application"]["estimate"] == 0.5


def test_dependency_gate_rejects_evaluation(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    # task-input 依赖 task-scaffold（尚未 done）
    resp = evaluate(eval_client, pid, "task-input", GREEN)
    assert resp.status_code == 422
    assert "前置任务尚未完成" in resp.json()["detail"]
    assert "task-scaffold" in resp.json()["detail"]

    # 完成前置后可通过
    evaluate(eval_client, pid, "task-scaffold", GREEN)
    ok = evaluate(eval_client, pid, "task-input", GREEN)
    assert ok.status_code == 200 and ok.json()["status"] == "done"


def test_error_files_count_as_failure(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    broken = {"totalFiles": 2, "totalPassed": 1, "totalFailed": 0, "errorFiles": 1, "traceId": "t"}
    body = evaluate(eval_client, pid, "task-scaffold", broken).json()
    assert body["passed"] is False and body["status"] == "needs-fix"


def test_empty_suite_rejected(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    empty = {"totalFiles": 0, "totalPassed": 0, "totalFailed": 0, "errorFiles": 0}
    body = evaluate(eval_client, pid, "task-scaffold", empty).json()
    assert body["passed"] is False  # 没有测试执行就不能算通过


def test_unknown_task_or_project_404(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    assert evaluate(eval_client, pid, "task-nonexistent", GREEN).status_code == 404
    resp = client_post = eval_client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/tasks/task-scaffold/evaluate",
        json=GREEN,
    )
    assert resp.status_code == 404
    assert client_post  # 引用以避免误判未使用
