"""P2.6 测试：介入模式设置、H4 门控、主动建议与冷却。"""

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.provider import MockProvider
from app.core.db import get_db
from app.domains.concepts.service import ensure_seed_concepts
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD

# 事件时间戳序号：跨 seed 调用单调递增，保证倒序稳定
_event_seq = itertools.count()


@pytest.fixture()
def p26_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def create_project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript"])).json()["id"]


def seed_events(client: TestClient, pid: str, statuses: list[str]):
    """按顺序上报运行事件（occurredAt 全局递增，保证倒序稳定）。"""
    import uuid
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "events": [
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "code-run",
                    "occurredAt": (base + timedelta(seconds=next(_event_seq) * 10)).isoformat(),
                    "aggregateId": f"project:{pid}",
                    "projectId": pid,
                    "payload": {"path": "src/main.ts", "status": status},
                }
                for status in statuses
            ]
        },
    )


# ---------- 介入模式设置 ----------


def test_settings_default_and_update(p26_client: TestClient):
    assert p26_client.get("/api/v1/settings").json() == {"interventionMode": "adaptive"}
    assert (
        p26_client.patch("/api/v1/settings", json={"interventionMode": "guided"}).json()
        == {"interventionMode": "guided"}
    )
    # 持久化：再次读取仍为 guided
    assert p26_client.get("/api/v1/settings").json() == {"interventionMode": "guided"}
    # 非法值被契约层拒绝
    assert p26_client.patch("/api/v1/settings", json={"interventionMode": "loud"}).status_code == 422


# ---------- H4 门控 ----------


def test_h4_blocked_without_explicit_request(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    provider = MockProvider()
    provider.default_response = {
        "intent": "explain", "hintLevel": 4, "message": "完整答案：直接用 useEffect…",
        "targetConceptIds": [], "explanation": "给答案", "confidence": 0.8,
    }
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = p26_client.post("/api/v1/tutor/turns", json={"projectId": pid, "question": "怎么做？"})
    decision = resp.json()["decision"]
    assert decision["outcome"] == "degraded"
    assert "H4" in decision["outcomeReason"]
    assert decision["hintLevel"] == 1  # 降级为安全动作


def test_h4_allowed_with_explicit_request_and_flagged(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    provider = MockProvider()
    provider.default_response = {
        "intent": "explain", "hintLevel": 4, "message": "参考实现如下…",
        "targetConceptIds": [], "explanation": "用户明确请求", "confidence": 0.8,
    }
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = p26_client.post(
        "/api/v1/tutor/turns",
        json={"projectId": pid, "question": "请直接给我这个函数的参考实现", "requestAnswerLevel": True},
    )
    decision = resp.json()["decision"]
    assert decision["outcome"] == "accepted" and decision["hintLevel"] == 4
    # 事件标记 answerRequested（为独立性重测留证据）
    events = p26_client.get(f"/api/v1/events?projectId={pid}&type=tutor-turn").json()
    assert events["items"][0]["payload"]["answerRequested"] is True


# ---------- 主动建议：模式约束 / 失败证据 / 冷却 ----------


def test_suggestion_quiet_mode_never(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    seed_events(p26_client, pid, ["error", "error", "error"])
    p26_client.patch("/api/v1/settings", json={"interventionMode": "quiet"})
    provider = MockProvider()
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}")
    assert resp.status_code == 200 and resp.json() is None
    assert provider.calls == []  # Quiet 模式不调用 LLM


def test_suggestion_requires_consecutive_failures(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    seed_events(p26_client, pid, ["ok", "error", "error"])  # 末尾连续仅 2 次
    provider = MockProvider()
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)
    assert p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}").json() is None
    assert provider.calls == []

    # 再补两次失败 → 连续 4 次 → 生成建议（默认 adaptive）
    seed_events(p26_client, pid, ["error", "error"])
    resp = p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}")
    body = resp.json()
    assert body is not None and body["decision"]["trigger"] == "auto"
    # 建议提示词包含失败证据说明
    assert "连续" in provider.calls[0]["user"]


def test_suggestion_cooldown_60s(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    seed_events(p26_client, pid, ["error", "error", "error"])
    provider = MockProvider()
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    first = p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}").json()
    assert first is not None
    second = p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}").json()
    assert second is None  # 60s 冷却内不再生成
    assert len(provider.calls) == 1


def test_suggestion_guided_mode_works(p26_client: TestClient, monkeypatch):
    pid = create_project(p26_client)
    seed_events(p26_client, pid, ["timeout", "timeout", "timeout"])
    p26_client.patch("/api/v1/settings", json={"interventionMode": "guided"})
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: MockProvider())
    body = p26_client.get(f"/api/v1/tutor/suggestions?projectId={pid}").json()
    assert body is not None and body["decision"]["trigger"] == "auto"
