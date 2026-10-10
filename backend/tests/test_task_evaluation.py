"""任务级验收测试（P4.1）：试点课程、任务级测试绑定、防伪守卫、practice 信任级。"""

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


def setup_project(client: TestClient) -> tuple[str, dict]:
    pid = client.post(
        "/api/v1/projects",
        json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript"]),
    ).json()["id"]
    detail = client.get(f"/api/v1/plans/{pid}").json()
    return pid, {t["taskId"]: t for t in detail["tasks"]}


def evaluate(client: TestClient, pid: str, task_id: str, suite: dict):
    return client.post(f"/api/v1/projects/{pid}/tasks/{task_id}/evaluate", json=suite)


def green_suite(path="src/parser/headings.test.ts"):
    return {
        "files": [{"path": path, "status": "passed", "passed": 5, "failed": 0, "totalCases": 5}],
        "traceId": "t-1",
    }


def test_pilot_course_seeded(eval_client: TestClient):
    pid, tasks = setup_project(eval_client)
    assert set(tasks.keys()) == {"md-heading", "md-inline", "md-module"}
    heading = tasks["md-heading"]
    assert heading["description"]
    assert heading["testFiles"] == ["src/parser/headings.test.ts"]
    assert heading["acceptanceCriteria"]
    assert heading["requiredConcepts"] == ["js.strings", "js.control-flow"]
    assert tasks["md-inline"]["dependsOn"] == ["md-heading"]

    # 初始代码 + 测试文件已种子到 project_files
    files = eval_client.get(f"/api/v1/projects/{pid}/files").json()
    paths = {f["path"] for f in files["items"]}
    assert "src/parser/headings.ts" in paths
    assert "src/parser/headings.test.ts" in paths
    assert "src/parser/inline.test.ts" in paths
    assert "src/parser/transform.ts" in paths


def test_scoped_green_marks_done_with_trust_level_practice(eval_client: TestClient):
    pid, tasks = setup_project(eval_client)
    resp = evaluate(eval_client, pid, "md-heading", green_suite())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is True
    assert body["status"] == "done"
    assert body["trustLevel"] == "practice"  # 客户端自报 ≠ 正式认证
    assert body["rubricVersion"] == "task-scoped-v2"
    assert body["evidenceConcepts"] == ["js.strings", "js.control-flow"]


def test_out_of_scope_test_files_ignored(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    suite = {
        "files": [
            {"path": "src/parser/inline.test.ts", "status": "passed", "passed": 4, "failed": 0, "totalCases": 4},
            {"path": "src/other.test.ts", "status": "passed", "passed": 1, "failed": 0, "totalCases": 1},
        ],
    }
    body = evaluate(eval_client, pid, "md-heading", suite).json()
    assert "忽略非本任务测试文件" in body["warnings"][0]


def test_failing_task_test_needs_fix(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    red = {
        "files": [{"path": "src/parser/headings.test.ts", "status": "failed", "passed": 3, "failed": 2, "totalCases": 5}],
    }
    body = evaluate(eval_client, pid, "md-heading", red).json()
    assert body["passed"] is False
    assert body["status"] == "needs-fix"


def test_zero_cases_not_pass(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    empty = {
        "files": [{"path": "src/parser/headings.test.ts", "status": "passed", "passed": 0, "failed": 0, "totalCases": 0}],
    }
    body = evaluate(eval_client, pid, "md-heading", empty).json()
    assert body["passed"] is False
    assert "零断言" in body["warnings"][0] or "没有执行的测试用例" in body["warnings"][0]


def test_no_bound_tests_needs_fix(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    body = evaluate(eval_client, pid, "md-heading", {"files": []}).json()
    assert body["passed"] is False
    assert body["status"] == "needs-fix"


def test_dependency_gate(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    resp = evaluate(eval_client, pid, "md-inline", green_suite("src/parser/inline.test.ts"))
    assert resp.status_code == 422
    assert "md-heading" in resp.json()["detail"]

    evaluate(eval_client, pid, "md-heading", green_suite())
    ok = evaluate(eval_client, pid, "md-inline", green_suite("src/parser/inline.test.ts"))
    assert ok.status_code == 200 and ok.json()["status"] == "done"


def test_evidence_written_for_required_concepts(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    evaluate(eval_client, pid, "md-heading", green_suite())
    mastery = {m["conceptId"]: m for m in eval_client.get("/api/v1/mastery").json()["items"]}
    assert "js.strings" in mastery
    dom = mastery["js.strings"]["dimensions"]
    assert "application" in dom
    assert dom["application"]["estimate"] == 1.0


def test_task_evaluated_event_with_warnings(eval_client: TestClient):
    pid, _ = setup_project(eval_client)
    evaluate(eval_client, pid, "md-heading", green_suite())
    events = eval_client.get(f"/api/v1/events?projectId={pid}&type=task-evaluated").json()
    assert events["total"] == 1
    payload = events["items"][0]["payload"]
    assert payload["trustLevel"] == "practice"
    assert payload["taskId"] == "md-heading"
