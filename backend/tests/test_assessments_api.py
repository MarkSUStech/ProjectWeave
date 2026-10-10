"""能力诊断 API 测试：选题、判定、三档估计、重复提交与校验。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.assessments.question_bank import QUESTION_BANK
from app.domains.concepts.service import ensure_seed_concepts
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD


@pytest.fixture()
def assessment_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def create_project(client: TestClient, stack: list[str]) -> str:
    payload = dict(VALID_CREATE_PAYLOAD, stack=stack)
    return client.post("/api/v1/projects", json=payload).json()["id"]


def start(client: TestClient, project_id: str):
    resp = client.post("/api/v1/assessments/start", json={"projectId": project_id})
    assert resp.status_code == 201, resp.text
    return resp.json()


def answers_for(session: dict, force: int | None = None) -> list[dict]:
    """构造全量作答；force=None 时按题库给正确答案（测试视角：直接引用题库键）。"""
    bank = {q["id"]: q for q in QUESTION_BANK}
    out = []
    for item in session["items"]:
        selected = force if force is not None else bank[item["itemId"]]["answerIndex"]
        out.append({"itemId": item["itemId"], "selectedOptionIndex": selected})
    return out


def test_start_selects_items_without_answers(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript", "React"])
    session = start(assessment_client, pid)
    assert session["status"] == "in-progress"
    assert 1 <= len(session["items"]) <= 8
    for item in session["items"]:
        assert set(item.keys()) == {"itemId", "conceptId", "prompt", "options", "difficulty"}
        assert len(item["options"]) == 4
        assert "answerIndex" not in item  # 答案绝不下发
    # 前端栈 → 四个域都可能出现；至少包含 javascript 域题目
    assert any(i["conceptId"].startswith("js.") for i in session["items"])


def test_selection_order_follows_concept_depth(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript", "React"])
    session = start(assessment_client, pid)
    concepts = [i["conceptId"] for i in session["items"]]
    # js.values-types 是图深度最浅的入口概念，应排在前两题内
    assert "js.values-types" in concepts[:2]
    assert len(set(concepts)) == len(concepts)  # 每概念一题


def test_submit_all_correct_marks_likely_mastered(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript", "React"])
    session = start(assessment_client, pid)
    resp = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit",
        json={"answers": answers_for(session)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["completedAt"]
    labels = {c["conceptId"]: c["label"] for c in body["results"]["concepts"]}
    assert all(label == "likely-mastered" for label in labels.values())
    assert all(q["correct"] for q in body["results"]["questions"])
    # 提交后回读：结果持久化在会话上
    reread = assessment_client.get(f"/api/v1/assessments/{session['id']}").json()
    assert reread["status"] == "completed"
    assert reread["results"]["concepts"] == body["results"]["concepts"]


def test_submit_all_wrong_marks_likely_gap(assessment_client: TestClient):
    pid = create_project(assessment_client, ["React"])
    session = start(assessment_client, pid)
    # 用一个必然全错的选项索引：对每题选择正确答案之外的第一个选项
    bank = {q["id"]: q for q in QUESTION_BANK}
    answers = [
        {
            "itemId": item["itemId"],
            "selectedOptionIndex": (bank[item["itemId"]]["answerIndex"] + 1) % 4,
        }
        for item in session["items"]
    ]
    resp = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers}
    )
    labels = [c["label"] for c in resp.json()["results"]["concepts"]]
    assert all(label == "likely-gap" for label in labels)


def test_duplicate_submit_conflict(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript"])
    session = start(assessment_client, pid)
    first = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit",
        json={"answers": answers_for(session)},
    )
    assert first.status_code == 200
    second = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit",
        json={"answers": answers_for(session)},
    )
    assert second.status_code == 409


def test_partial_submit_rejected(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript"])
    session = start(assessment_client, pid)
    answers = answers_for(session)[:-1]  # 缺最后一题
    resp = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers}
    )
    assert resp.status_code == 422
    assert "缺少作答" in resp.json()["detail"]
    # 会话仍可继续提交
    ok = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit",
        json={"answers": answers_for(session)},
    )
    assert ok.status_code == 200


def test_unknown_item_rejected(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript"])
    session = start(assessment_client, pid)
    answers = answers_for(session)
    answers[0]["itemId"] = "q.not-exist"
    resp = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers}
    )
    assert resp.status_code == 422
    assert "未知题目" in resp.json()["detail"]


def test_out_of_range_option_rejected(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript"])
    session = start(assessment_client, pid)
    answers = answers_for(session)
    answers[0]["selectedOptionIndex"] = 9
    resp = assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers}
    )
    assert resp.status_code == 422


def test_start_for_unknown_project_404(assessment_client: TestClient):
    resp = assessment_client.post(
        "/api/v1/assessments/start",
        json={"projectId": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


def test_session_detail_404(assessment_client: TestClient):
    assert (
        assessment_client.get("/api/v1/assessments/not-a-uuid").status_code == 404
    )


def test_project_assessment_history(assessment_client: TestClient):
    pid = create_project(assessment_client, ["TypeScript"])
    session = start(assessment_client, pid)
    assessment_client.post(
        f"/api/v1/assessments/{session['id']}/submit",
        json={"answers": answers_for(session)},
    )
    history = assessment_client.get(f"/api/v1/projects/{pid}/assessments").json()
    assert history["total"] == 1
    assert history["items"][0]["status"] == "completed"
    assert history["items"][0]["results"]["concepts"]


def test_non_frontend_stack_limits_domains(assessment_client: TestClient):
    pid = create_project(assessment_client, ["Python"])
    session = start(assessment_client, pid)
    # 非前端栈 → javascript + engineering，不含 ts./browser. 概念
    for item in session["items"]:
        assert not item["conceptId"].startswith(("ts.", "browser."))
