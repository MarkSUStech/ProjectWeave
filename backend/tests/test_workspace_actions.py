"""WorkspaceAction 分级与联防测试（§10.2 / AT-05 / D23 H4 联动）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.provider import MockProvider
from app.core.db import get_db
from app.domains.concepts.service import ensure_seed_concepts
from app.domains.tutor.service import validate_workspace_actions
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD


# ---------- 纯函数：分级与校验 ----------


def test_valid_actions_classified_by_kind():
    actions, dropped = validate_workspace_actions(
        [
            {"kind": "display-notice", "reason": "r", "payload": {"message": "看这里"}},
            {"kind": "switch-layout", "reason": "r", "payload": {"mode": "debugging"}},
        ],
        request_answer_level=False,
    )
    assert dropped == []
    assert [(a["kind"], a["level"]) for a in actions] == [
        ("display-notice", "A0"),
        ("switch-layout", "A1"),
    ]


def test_propose_patch_requires_answer_level():
    patch = {"kind": "propose-patch", "reason": "r",
             "payload": {"path": "src/main.ts", "description": "补齐函数"}}
    actions, dropped = validate_workspace_actions([patch], request_answer_level=False)
    assert actions == []
    assert any("答案级" in d for d in dropped)

    actions2, dropped2 = validate_workspace_actions([patch], request_answer_level=True)
    assert dropped2 == []
    assert actions2[0]["level"] == "A2"


def test_invalid_actions_dropped_with_reasons():
    actions, dropped = validate_workspace_actions(
        [
            {"kind": "delete-files", "payload": {}},
            {"kind": "switch-layout", "payload": {"mode": "party"}},
            {"kind": "display-notice", "payload": {}},
            {"kind": "propose-patch", "payload": {"path": "a.ts"}},  # 缺 description
            "not-an-object",
        ],
        request_answer_level=True,
    )
    assert actions == []
    assert len(dropped) == 5


def test_non_list_and_cap():
    assert validate_workspace_actions("nope", True)[1][0].startswith("workspaceActions 非法")
    many = [{"kind": "display-notice", "payload": {"message": "m"}} for _ in range(6)]
    actions, _ = validate_workspace_actions(many, True)
    assert len(actions) == 3  # MAX_WORKSPACE_ACTIONS


# ---------- 端到端：决策携带动作 + H4 联动落库 ----------


@pytest.fixture()
def wa_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def turn(client: TestClient, pid: str, provider: MockProvider, answer_level: bool = False):
    import json

    from app.domains.tutor.router import get_provider
    original = get_provider
    import app.domains.tutor.router as tutor_router

    tutor_router.get_provider = lambda: provider
    try:
        resp = client.post(
            "/api/v1/tutor/turns",
            json={"projectId": pid, "question": "q", "requestAnswerLevel": answer_level},
        )
    finally:
        tutor_router.get_provider = original
    assert resp.status_code == 201, resp.text
    return resp.json()["decision"]


def test_decision_carries_gated_actions(wa_client: TestClient):
    pid = wa_client.post(
        "/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript"])
    ).json()["id"]
    provider = MockProvider()
    provider.default_response = {
        "intent": "hint", "hintLevel": 2, "message": "切到调试模式看看变量",
        "targetConceptIds": [], "explanation": "r", "confidence": 0.6,
        "workspaceActions": [
            {"kind": "switch-layout", "reason": "排查失败", "payload": {"mode": "debugging"}},
            {"kind": "delete-everything", "reason": "x", "payload": {}},
        ],
    }
    decision = turn(wa_client, pid, provider)
    kinds = [(a["kind"], a["level"]) for a in decision["workspaceActions"]]
    assert kinds == [("switch-layout", "A1")]
    assert "未知动作类型" in decision["outcomeReason"]

    # 历史回读一致
    history = wa_client.get(f"/api/v1/tutor/decisions?projectId={pid}").json()
    assert history["items"][0]["workspaceActions"][0]["kind"] == "switch-layout"


def test_patch_action_only_with_answer_level(wa_client: TestClient):
    pid = wa_client.post(
        "/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript"])
    ).json()["id"]
    provider = MockProvider()
    provider.default_response = {
        "intent": "explain", "hintLevel": 4, "message": "参考实现如下",
        "targetConceptIds": [], "explanation": "r", "confidence": 0.8,
        "workspaceActions": [
            {"kind": "propose-patch", "reason": "给答案",
             "payload": {"path": "src/main.ts", "description": "完整实现"}},
        ],
    }
    # 未请求答案级：H4 消息降级 + A2 动作移除
    decision = turn(wa_client, pid, provider, answer_level=False)
    assert decision["workspaceActions"] == []
    assert decision["outcome"] == "degraded"  # H4 消息被门控（D23）

    # 明确请求：消息与 A2 动作均放行
    decision2 = turn(wa_client, pid, provider, answer_level=True)
    assert decision2["workspaceActions"][0]["level"] == "A2"
    assert decision2["outcome"] == "accepted"
