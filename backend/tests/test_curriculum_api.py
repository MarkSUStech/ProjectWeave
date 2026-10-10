"""课程规划测试：任务图种子、路线生成、掌握驱动差异、版本链。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.assessments.question_bank import QUESTION_BANK
from app.domains.concepts.service import ensure_seed_concepts
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD


@pytest.fixture()
def curriculum_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def create_project(client: TestClient) -> str:
    return client.post(
        "/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript", "React"])
    ).json()["id"]


def run_assessment(client: TestClient, project_id: str, correct: bool):
    session = client.post("/api/v1/assessments/start", json={"projectId": project_id}).json()
    bank = {q["id"]: q for q in QUESTION_BANK}
    answers = [
        {
            "itemId": item["itemId"],
            "selectedOptionIndex": bank[item["itemId"]]["answerIndex"]
            if correct
            else (bank[item["itemId"]]["answerIndex"] + 1) % 4,
        }
        for item in session["items"]
    ]
    resp = client.post(f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers})
    assert resp.status_code == 200


def test_plan_generates_task_graph_and_all_learning_activities(curriculum_client: TestClient):
    pid = create_project(curriculum_client)
    resp = curriculum_client.get(f"/api/v1/plans/{pid}")
    assert resp.status_code == 200
    body = resp.json()

    # 任务图：样板课程 6 任务
    assert len(body["tasks"]) == 6
    assert body["tasks"][0]["taskId"] == "task-scaffold"
    assert body["tasks"][0]["milestone"] == 1

    plan = body["plan"]
    assert plan["planVersion"] == 1
    learn = [a for a in plan["activities"] if a["type"] == "learn-concept"]
    practice = [a for a in plan["activities"] if a["type"] == "practice-task"]
    assert len(practice) == 6

    # 未诊断：所有直接要求概念及其先修闭包都要学（含未诊断的概念）
    direct = {"browser.dom", "js.objects", "js.callbacks-events", "js.strings", "js.functions",
              "browser.storage", "js.arrays", "eng.errors", "eng.testing", "eng.modules",
              "ts.annotations"}
    planned = {a["conceptId"] for a in learn}
    assert direct <= planned
    # 先修闭包：js.callbacks-events 的先修 js.closures 应被包含
    assert "js.closures" in planned
    assert all(a["reason"] for a in plan["activities"])
    assert plan["skipped"] == []
    # 顺序编号连续且学习活动先于同任务实践
    orders = [a["order"] for a in plan["activities"]]
    assert orders == list(range(1, len(orders) + 1))


def test_mastered_learner_gets_shorter_route(curriculum_client: TestClient):
    """AT-01/AT-02 的 MVP 验证：不同能力情况 → 不同路线。"""
    pid = create_project(curriculum_client)

    baseline = curriculum_client.get(f"/api/v1/plans/{pid}").json()["plan"]
    baseline_learn = {a["conceptId"] for a in baseline["activities"] if a["type"] == "learn-concept"}

    # 全对诊断（覆盖 8 个概念，全部 estimate=1.0）
    run_assessment(curriculum_client, pid, correct=True)
    replanned = curriculum_client.post(f"/api/v1/plans/{pid}/replan").json()

    after_learn = {a["conceptId"] for a in replanned["activities"] if a["type"] == "learn-concept"}
    skipped = {s["conceptId"] for s in replanned["skipped"]}

    # 已诊断且全对的概念被跳过（掌握阈值：1 条证据 confidence=0.5 ≤ 阈值 → 仍需学！）
    # 注意：单次诊断每概念 1 条证据，confidence=0.5 不超过阈值 → 不会跳过；
    # 因此本用例先做两次全对诊断以累积证据。
    run_assessment(curriculum_client, pid, correct=True)
    replanned2 = curriculum_client.post(f"/api/v1/plans/{pid}/replan").json()
    skipped2 = {s["conceptId"] for s in replanned2["skipped"]}
    learned2 = {a["conceptId"] for a in replanned2["activities"] if a["type"] == "learn-concept"}

    assert len(skipped2) > 0, "两次全对诊断后应有概念被判定已掌握而跳过"
    assert skipped2.isdisjoint(learned2)
    assert baseline_learn - skipped2 == learned2
    # 版本递增且跳过项带原因
    assert replanned2["planVersion"] == 3
    assert all(s["reason"].startswith("已掌握") for s in replanned2["skipped"])


def test_get_plan_is_idempotent(curriculum_client: TestClient):
    pid = create_project(curriculum_client)
    first = curriculum_client.get(f"/api/v1/plans/{pid}").json()["plan"]
    second = curriculum_client.get(f"/api/v1/plans/{pid}").json()["plan"]
    assert first["id"] == second["id"] and first["planVersion"] == 1


def test_replan_keeps_version_history(curriculum_client: TestClient):
    pid = create_project(curriculum_client)
    v1 = curriculum_client.get(f"/api/v1/plans/{pid}").json()["plan"]
    v2 = curriculum_client.post(f"/api/v1/plans/{pid}/replan").json()
    assert v2["planVersion"] == 2
    assert v1["id"] != v2["id"]

    from app.core.db import SessionLocal  # noqa: F401 – 验证走 API 即可
    # 再次 GET 返回最新版本
    latest = curriculum_client.get(f"/api/v1/plans/{pid}").json()["plan"]
    assert latest["planVersion"] == 2


def test_plan_for_unknown_project_404(curriculum_client: TestClient):
    resp = curriculum_client.get("/api/v1/plans/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
