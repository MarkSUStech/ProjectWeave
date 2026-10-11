"""真实课程生成 E2E（选入：PW_COURSE_E2E=1；真实 GitHub + 真实 DeepSeek）。

验证：公开仓库导入 → commit SHA 固定 → 真实分析（含工具调用）→
真实蓝图（≥4 里程碑 ≥8 任务 DAG 合法 + 证据回溯）→ 持久化 → API 可读 → 发布。
不使用任何预写 Micrograd 课程内容冒充生成结果。
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import SessionLocal
from app.domains.course_generation import service

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_COURSE_E2E") != "1",
    reason="需 PW_COURSE_E2E=1、可访问 api.github.com 与已配置 DeepSeek（PW_AI_PROVIDER=deepseek）",
)

REPO = "https://github.com/karpathy/micrograd"


@pytest.fixture()
def e2e(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    # 测试环境默认禁用 AI——E2E 显式构造真实 DeepSeek Provider（读 .env 的 Key）
    from app.ai.provider import DeepSeekProvider

    provider = DeepSeekProvider()
    monkeypatch.setattr(service, "_provider_factory", lambda: provider)
    yield client
    service.set_session_factory(SessionLocal)
    service._provider_factory = None


def _wait(client: TestClient, gen_id: str, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/course-generations/{gen_id}").json()
        if data["status"] in {"draft", "published", "failed"}:
            return data
        time.sleep(2)
    pytest.fail("生成超时")


def test_micrograd_course_generation(e2e: TestClient):
    resp = e2e.post("/api/v1/course-generations", json={"repositoryUrl": REPO})
    assert resp.status_code == 202, resp.text
    gen_id = resp.json()["id"]

    final = _wait(e2e, gen_id)
    assert final["status"] == "draft", final.get("error")
    assert final["commitSha"] and len(final["commitSha"]) == 40
    assert final["repoName"] == "micrograd"

    # 分析：真实工具调用 + 证据分级
    analysis = e2e.get(f"/api/v1/course-generations/{gen_id}/analysis").json()
    assert analysis["analysis"]["summary"]
    assert analysis["toolCalls"], "分析必须有真实工具调用轨迹"
    tools = {t["tool"] for t in analysis["toolCalls"]}
    assert tools & {"get_repository_metadata", "list_repository_tree", "read_repository_file"}
    kinds = {c.get("kind") for c in (analysis["analysis"].get("modules") or [])}
    assert kinds <= {"confirmed", "inferred", "unknown"} and "confirmed" in kinds

    # 蓝图：结构底线 + DAG + 证据回溯
    bp = e2e.get(f"/api/v1/course-generations/{gen_id}/blueprint").json()
    assert bp["validation"]["passed"], [i for i in bp["validation"]["issues"] if i["severity"] == "error"]
    blueprint = bp["blueprint"]
    assert len(blueprint["milestones"]) >= 4
    assert len(blueprint["tasks"]) >= 8
    assert "自动微分" in blueprint["project"]["title"] or "autograd" in blueprint["project"]["title"].lower() or "微分" in blueprint["project"]["title"]
    # 每个任务证据路径都在快照中（验证器已保证）；抽查至少 5 个任务有证据
    evidenced = [t for t in blueprint["tasks"] if t["sourceEvidence"]]
    assert len(evidenced) >= 5
    # 知识点全部是已有或候选
    for k in blueprint["knowledgeRequirements"]:
        assert isinstance(k["isExisting"], bool)

    # 发布
    pub = e2e.post(f"/api/v1/course-generations/{gen_id}/publish")
    assert pub.status_code == 200
    body = pub.json()
    assert body["taskCount"] >= 8 and body["milestoneCount"] >= 4
    print("\n=== micrograd 课程蓝图标题:", blueprint["project"]["title"])
    print("=== 里程碑:", [m["title"] for m in blueprint["milestones"]])
    print("=== 修复轮:", final["repairRounds"], "| 工具调用:", len(analysis["toolCalls"]))
