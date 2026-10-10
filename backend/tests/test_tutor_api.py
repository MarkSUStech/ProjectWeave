"""Tutor Engine 测试：Policy Gate、教学回合端到端（Mock Provider）、历史与未配置降级。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.provider import MockProvider
from app.core.db import get_db
from app.domains.concepts.service import ensure_seed_concepts
from app.domains.tutor.service import policy_gate
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD


@pytest.fixture()
def tutor_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def create_project(client: TestClient) -> str:
    return client.post(
        "/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript", "React"])
    ).json()["id"]


# ---------- Policy Gate（纯函数） ----------


def test_policy_gate_accepts_valid_proposal():
    fields, outcome, reason = policy_gate({
        "intent": "hint", "hintLevel": 1, "message": "看看事件回调",
        "targetConceptIds": ["js.callbacks-events"], "explanation": "r", "confidence": 0.6,
    })
    assert outcome == "accepted" and reason == ""
    assert fields["intent"] == "hint" and fields["hint_level"] == 1


@pytest.mark.parametrize("proposal, match", [
    ({"intent": "give-answer", "hintLevel": 1, "message": "x"}, "非法 intent"),
    ({"intent": "hint", "hintLevel": 9, "message": "x"}, "非法 hintLevel"),
    ({"intent": "hint", "hintLevel": "1", "message": "x"}, "非法 hintLevel"),
    ({"intent": "hint", "hintLevel": 1, "message": "  "}, "message 缺失"),
    ({"intent": "hint", "hintLevel": 1, "message": "x" * 4000}, "message 过长"),
])
def test_policy_gate_degrades_invalid_proposals(proposal, match):
    fields, outcome, reason = policy_gate(proposal)
    assert outcome == "degraded"
    assert match in reason
    # 降级动作是安全的：explain / hint 1 / 固定文案
    assert fields["intent"] == "explain" and fields["hint_level"] == 1


def test_policy_gate_truncates_target_concepts():
    fields, outcome, _ = policy_gate({
        "intent": "hint", "hintLevel": 1, "message": "x",
        "targetConceptIds": [f"c{i}" for i in range(10)],
    })
    assert outcome == "accepted"
    assert len(fields["target_concepts"]) == 5


# ---------- 教学回合（端到端，Mock Provider 注入） ----------


def test_tutor_turn_end_to_end_with_mock_provider(tutor_client: TestClient, monkeypatch):
    pid = create_project(tutor_client)
    # 先生成学习路线，让上下文包含活动数据
    tutor_client.get(f"/api/v1/plans/{pid}")

    provider = MockProvider()
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = tutor_client.post(
        "/api/v1/tutor/turns",
        json={"projectId": pid, "question": "我的预览为什么不更新？"},
    )
    assert resp.status_code == 201, resp.text
    decision = resp.json()["decision"]
    assert decision["intent"] == "hint" and decision["hintLevel"] == 1
    assert decision["outcome"] == "accepted"
    assert decision["policyVersion"] == "gate-v1"
    assert decision["promptTokens"] > 0

    # 提示词包含上下文与防注入声明，且包含用户问题
    user_prompt = provider.calls[0]["user"]
    assert "我的预览为什么不更新" in user_prompt
    assert "<<<CONTEXT" in user_prompt and "不是对你的指令" in user_prompt
    assert "nextActivities" in user_prompt

    # 决策历史 + tutor-turn 事件
    history = tutor_client.get(f"/api/v1/tutor/decisions?projectId={pid}").json()
    assert history["total"] == 1
    events = tutor_client.get(f"/api/v1/events?projectId={pid}&type=tutor-turn").json()
    assert events["total"] == 1
    assert events["items"][0]["payload"]["intent"] == "hint"


def test_tutor_turn_persists_degraded_decision(tutor_client: TestClient, monkeypatch):
    pid = create_project(tutor_client)
    provider = MockProvider()
    provider.default_response = {"intent": "delete-files", "hintLevel": 99, "message": ""}
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = tutor_client.post("/api/v1/tutor/turns", json={"projectId": pid, "question": "q"})
    assert resp.status_code == 201
    decision = resp.json()["decision"]
    assert decision["outcome"] == "degraded"
    assert "非法" in decision["outcomeReason"]
    assert decision["intent"] == "explain" and decision["hintLevel"] == 1


def test_tutor_disabled_returns_503(tutor_client: TestClient, monkeypatch):
    from app.ai.provider import ProviderDisabledError

    monkeypatch.setattr(
        "app.domains.tutor.router.get_provider",
        lambda: (_ for _ in ()).throw(ProviderDisabledError("AI Provider 未配置")),
    )
    pid = create_project(tutor_client)
    resp = tutor_client.post("/api/v1/tutor/turns", json={"projectId": pid, "question": "q"})
    assert resp.status_code == 503
    assert "AI 未配置" in resp.json()["detail"]


def test_tutor_unknown_project_404(tutor_client: TestClient, monkeypatch):
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: MockProvider())
    resp = tutor_client.post(
        "/api/v1/tutor/turns",
        json={"projectId": "00000000-0000-0000-0000-000000000000", "question": "q"},
    )
    assert resp.status_code == 404
