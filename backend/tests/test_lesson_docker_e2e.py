"""真实 Docker 沙箱课程验证 E2E（选入：PW_SANDBOX_E2E=1）。

Mock LLM（材料确定）+ **真实 Docker Python 沙箱**（projectweave-sandbox-python:3.12）：
build-lessons → 逐任务参考实现真跑 pytest → starter 期望失败（防泄露）→
最终集成 → ready → instantiate。证明课程验证只由真实执行判定，与 FakeSandbox 无关。
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai.provider import MockProvider
from app.domains.course_generation.lessons import lesson_publisher

from tests.test_lesson_build import _material, _seed_published_generation

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker 镜像 projectweave-sandbox-python:3.12）",
)


@pytest.fixture()
def docker_env(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)
    provider = MockProvider()
    material = _material()
    provider.chat = lambda system, user: type("R", (), {
        "content": json.dumps(material, ensure_ascii=False),
        "prompt_tokens": 100, "completion_tokens": 200, "model": "mock",
    })()
    monkeypatch.setattr(lesson_publisher, "_provider_factory", lambda: provider)
    yield client
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


def test_micrograd_course_real_docker_ready(docker_env: TestClient, db_session):
    gen_id = _seed_published_generation(docker_env, db_session)
    resp = docker_env.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    release = resp.json()
    assert release["language"] == "python"

    # 真实 Docker：每任务参考测试 + starter 期望失败 + 最终集成 ≈ 19 次容器执行
    deadline = time.monotonic() + 900
    detail: dict = {}
    while time.monotonic() < deadline:
        detail = docker_env.get(f"/api/v1/course-releases/{release['id']}").json()
        if detail["status"] in ("ready", "failed"):
            break
        time.sleep(1.0)
    assert detail["status"] == "ready", detail.get("error")
    assert detail["passedTasks"] == detail["totalTasks"] == 9

    # 真实执行证据：每个任务都有 reference-tests（真跑 pytest，非 skipped）
    arts = {a["taskId"]: a for a in detail["artifacts"]}
    for tid, art in arts.items():
        kinds = [v["kind"] for v in art["verifications"]]
        assert "reference-tests" in kinds, (tid, kinds)
        ref_run = next(v for v in art["verifications"] if v["kind"] == "reference-tests")
        assert ref_run["status"] == "passed" and ref_run["totalTests"] > 0, (tid, ref_run)

    # 首任务：starter 在真实沙箱中测试失败（证明测试有效、不泄露答案）
    first = arts["t1"]["verifications"]
    starter_run = next(v for v in first if v["kind"] == "starter-expected-fail")
    assert starter_run["status"] == "passed" and starter_run["failedTests"] > 0

    # 实例化学习项目（首任务 starter + 测试落地）
    inst = docker_env.post(f"/api/v1/course-releases/{release['id']}/instantiate",
                           json={"projectTitle": "micrograd（真实沙箱）"})
    assert inst.status_code == 201, inst.text
    assert inst.json()["firstTaskId"] == "t1"
