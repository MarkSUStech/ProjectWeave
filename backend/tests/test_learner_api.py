"""学习者模型测试：证据写入、掌握估计、置信度与 API。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.assessments.question_bank import QUESTION_BANK
from app.domains.concepts.service import ensure_seed_concepts
from app.domains.learner import service as learner_service
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD

MASTERY = "/api/v1/mastery"


@pytest.fixture()
def learner_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def run_assessment(client: TestClient, stack: list[str], correct: bool) -> dict:
    pid = client.post("/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=stack)).json()["id"]
    session = client.post("/api/v1/assessments/start", json={"projectId": pid}).json()
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
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_submit_writes_evidence_and_mastery(learner_client: TestClient, db_session: Session):
    result = run_assessment(learner_client, ["TypeScript", "React"], correct=True)

    mastery = learner_client.get(MASTERY).json()
    assert mastery["total"] == len({c["conceptId"] for c in result["results"]["concepts"]})
    for item in mastery["items"]:
        dims = item["dimensions"]
        # 只有 understanding 维有估计；其余维度不存在（无证据不编造）
        assert set(dims.keys()) == {"understanding"}
        u = dims["understanding"]
        assert u["estimate"] == 1.0
        assert u["evidenceCount"] == 1
        assert u["confidence"] == 0.5  # 0.3 + 0.2*1
        assert u["lastObservedAt"]
        assert item["modelVersion"] == "rule-v1"


def test_repeated_assessment_accumulates_evidence(learner_client: TestClient):
    run_assessment(learner_client, ["TypeScript"], correct=True)
    run_assessment(learner_client, ["TypeScript"], correct=False)

    mastery = {m["conceptId"]: m for m in learner_client.get(MASTERY).json()["items"]}
    assert mastery, "应有掌握记录"
    sample = next(iter(mastery.values()))
    u = sample["dimensions"]["understanding"]
    assert u["evidenceCount"] == 2
    assert u["estimate"] == 0.5  # 1 对 1 错
    assert u["confidence"] == 0.7  # 0.3 + 0.2*2


def test_confidence_caps_at_0_9(db_session: Session):
    ensure_seed_concepts(db_session)
    for _ in range(5):
        learner_service.record_evidence(
            db_session, "dev-user", "js.values-types", "prediction", "passed"
        )
    mastery = learner_service.list_mastery(db_session, "dev-user")
    u = mastery[0].dimensions["understanding"]
    assert u["evidenceCount"] == 5
    assert u["confidence"] == 0.9  # 封顶


def test_record_evidence_validates_inputs(db_session: Session):
    ensure_seed_concepts(db_session)
    with pytest.raises(ValueError, match="未知证据类型"):
        learner_service.record_evidence(db_session, "dev-user", "js.values-types", "gut-feeling", "passed")
    with pytest.raises(ValueError, match="概念不存在"):
        learner_service.record_evidence(db_session, "dev-user", "nope.nothing", "prediction", "passed")
    with pytest.raises(ValueError, match="未知证据结果"):
        learner_service.record_evidence(db_session, "dev-user", "js.values-types", "prediction", "maybe")


def test_mastery_empty_before_any_assessment(learner_client: TestClient):
    assert learner_client.get(MASTERY).json() == {"items": [], "total": 0}
