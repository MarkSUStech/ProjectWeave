"""学习事件测试：信封校验、幂等、服务端事件源、查询。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.concepts.service import ensure_seed_concepts
from app.main import app

from tests.conftest import VALID_CREATE_PAYLOAD

EVENTS = "/api/v1/events"


@pytest.fixture()
def events_client(client: TestClient, db_session: Session):
    ensure_seed_concepts(db_session)
    yield client


def make_event(**overrides) -> dict:
    base = {
        "eventId": str(uuid.uuid4()),
        "type": "code-run",
        "occurredAt": "2026-10-10T11:00:00Z",
        "aggregateId": "project:some",
        "payload": {"path": "src/main.ts", "status": "ok"},
    }
    base.update(overrides)
    return base


def test_ingest_and_query_roundtrip(events_client: TestClient):
    resp = events_client.post(EVENTS, json={"events": [make_event(), make_event(type="tests-run")]})
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 2, "duplicated": 0}

    listing = events_client.get(EVENTS).json()
    assert listing["total"] == 2
    item = listing["items"][0]
    assert item["type"] in ("code-run", "tests-run")
    assert item["sequence"] >= 1
    assert item["schemaVersion"] == 1


def test_duplicate_event_ids_are_skipped(events_client: TestClient):
    event = make_event()
    first = events_client.post(EVENTS, json={"events": [event]})
    assert first.json()["accepted"] == 1
    second = events_client.post(EVENTS, json={"events": [event, make_event()]})
    assert second.json() == {"accepted": 1, "duplicated": 1}
    assert events_client.get(EVENTS).json()["total"] == 2


def test_unknown_type_rejected(events_client: TestClient):
    resp = events_client.post(EVENTS, json={"events": [make_event(type="keystroke")]})
    assert resp.status_code == 422
    assert "不允许的事件类型" in resp.json()["detail"]


def test_payload_size_limit(events_client: TestClient):
    huge = make_event(payload={"blob": "x" * 5000})
    resp = events_client.post(EVENTS, json={"events": [huge]})
    assert resp.status_code == 422
    assert "payload 过大" in resp.json()["detail"]


def test_batch_limit(events_client: TestClient):
    events = [make_event() for _ in range(21)]
    resp = events_client.post(EVENTS, json={"events": events})
    assert resp.status_code == 422


def test_sequence_increases_per_aggregate(events_client: TestClient):
    ids = [str(uuid.uuid4()) for _ in range(3)]
    events_client.post(
        EVENTS,
        json={"events": [make_event(eventId=i, aggregateId="project:A") for i in ids]},
    )
    events_client.post(
        EVENTS,
        json={"events": [make_event(aggregateId="project:B")]},
    )
    listing = events_client.get(EVENTS, params={"limit": 10}).json()
    seq_a = sorted(
        e["sequence"] for e in listing["items"] if e["aggregateId"] == "project:A"
    )
    assert seq_a == [1, 2, 3]


def test_server_events_emitted_by_real_actions(events_client: TestClient):
    pid = events_client.post(
        "/api/v1/projects", json=dict(VALID_CREATE_PAYLOAD, stack=["TypeScript"])
    ).json()["id"]

    # 文件保存 → file-saved
    events_client.put(
        f"/api/v1/projects/{pid}/files",
        json={"path": "src/x.ts", "content": "let a = 1;"},
    )
    # 学习路线生成 → plan-generated
    events_client.get(f"/api/v1/plans/{pid}")

    project_events = events_client.get(EVENTS, params={"projectId": pid}).json()
    types = {e["type"] for e in project_events["items"]}
    assert {"file-saved", "plan-generated"} <= types

    # 诊断提交 → assessment-submitted（含摘要）
    from app.domains.assessments.question_bank import QUESTION_BANK

    session = events_client.post("/api/v1/assessments/start", json={"projectId": pid}).json()
    bank = {q["id"]: q for q in QUESTION_BANK}
    answers = [
        {"itemId": i["itemId"], "selectedOptionIndex": bank[i["itemId"]]["answerIndex"]}
        for i in session["items"]
    ]
    events_client.post(f"/api/v1/assessments/{session['id']}/submit", json={"answers": answers})

    # 重规划 → plan-replanned
    events_client.post(f"/api/v1/plans/{pid}/replan")

    project_events = events_client.get(EVENTS, params={"projectId": pid}).json()
    types = {e["type"] for e in project_events["items"]}
    assert {"file-saved", "plan-generated", "assessment-submitted", "plan-replanned"} <= types

    assessment = next(e for e in project_events["items"] if e["type"] == "assessment-submitted")
    assert assessment["payload"]["questions"] == len(session["items"])
    assert "mastered" in assessment["payload"]


def test_repeated_get_plan_does_not_duplicate_events(events_client: TestClient):
    pid = events_client.post("/api/v1/projects", json={"title": "幂等"}).json()["id"]
    events_client.get(f"/api/v1/plans/{pid}")
    events_client.get(f"/api/v1/plans/{pid}")
    listing = events_client.get(EVENTS, params={"projectId": pid, "type": "plan-generated"}).json()
    assert listing["total"] == 1  # 确定性 eventId → 幂等跳过


def test_filter_by_type(events_client: TestClient):
    events_client.post(EVENTS, json={"events": [make_event(type="code-run"), make_event(type="tests-run")]})
    listing = events_client.get(EVENTS, params={"type": "code-run"}).json()
    assert all(e["type"] == "code-run" for e in listing["items"])


def test_invalid_uuid_filter(events_client: TestClient):
    assert events_client.get(EVENTS, params={"projectId": "not-a-uuid"}).status_code == 422
