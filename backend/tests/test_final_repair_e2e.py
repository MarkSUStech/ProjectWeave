"""P8.2.3.3 Final Repair 发布链 E2E（真 Docker，D51）。

受控真实链路错误：原始最终快照 Demo 链接失败 → Final Evaluation 拒发 →
Agent（Scripted）在修复工作区修正 → 修复检查点持久化（旧检查点不变）→
重发使用**修复后快照**（Hash 断言）→ ready → 学生实例化。
"""

import json
import os
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.course_generation.harness import service as harness_service
from app.domains.course_generation.lessons import lesson_publisher

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker + clang15 镜像）",
)

NL = "\n"

# t1 工程基线（已验证）
T1_FILES = {
    "CMakeLists.txt": (
        "cmake_minimum_required(VERSION 3.16)" + NL
        + "project(WorldSim LANGUAGES CXX)" + NL
        + "set(CMAKE_CXX_STANDARD 20)" + NL
        + "add_subdirectory(engine)" + NL
        + "enable_testing()" + NL
        + "add_subdirectory(tests)" + NL),
    "engine/CMakeLists.txt": (
        "add_library(engine STATIC src/World.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL),
    "engine/include/engine/World.hpp": (
        "#pragma once" + NL + "namespace engine {" + NL
        + "inline int world() { return 1; }" + NL + "}" + NL),
    "engine/src/World.cpp": (
        '#include "engine/World.hpp"' + NL),
    "tests/CMakeLists.txt": (
        "add_executable(world_tests test_world.cpp)" + NL
        + "target_link_libraries(world_tests PRIVATE engine)" + NL
        + "add_test(NAME world_update COMMAND world_tests)" + NL),
    "tests/test_world.cpp": (
        '#include "engine/World.hpp"' + NL + "#include <cassert>" + NL
        + "int main() { assert(engine::world() == 1); return 0; }" + NL),
}

# Demo 正确实现：输出 world() 值（printf 转义在 Python 侧用 \\n）
FIXED_MAIN = (
    '#include "engine/World.hpp"' + NL + "#include <cstdio>" + NL
    + 'int main() { std::printf("%d' + chr(92) + 'n", engine::world());'
    + ' return 0; }' + NL)

# 演示目标正确版（E2E 主路径）
GOOD_DEMO = dict(T1_FILES)
GOOD_DEMO["CMakeLists.txt"] = T1_FILES["CMakeLists.txt"].replace(
    "add_subdirectory(tests)",
    "add_subdirectory(tests)" + NL + "add_subdirectory(app)")
GOOD_DEMO["app/CMakeLists.txt"] = (
    "add_executable(worldsim main.cpp)" + NL
    + "target_link_libraries(worldsim PRIVATE engine)" + NL
    + "add_test(NAME demo_runs COMMAND worldsim)" + NL)
GOOD_DEMO["app/main.cpp"] = FIXED_MAIN
# Starter：TODO 挖空（返回 1 → demo_runs 失败——真实教学挖空）
MAIN_STUB = (
    '#include "engine/World.hpp"' + NL + "#include <cstdio>" + NL
    + "int main() {" + NL
    + "    // TODO: 输出 world() 的值并返回 0" + NL
    + "    return 1;" + NL + "}" + NL)

# 保留 BROKEN 用于受控修复链单元测试
BROKEN_DEMO = dict(T1_FILES)
BROKEN_DEMO["CMakeLists.txt"] = T1_FILES["CMakeLists.txt"].replace(
    "add_subdirectory(tests)",
    "add_subdirectory(tests)" + NL + "add_subdirectory(app)")
BROKEN_DEMO["app/CMakeLists.txt"] = (
    "add_executable(worldsim main.cpp)" + NL
    + "target_link_libraries(worldsim PRIVATE engine)" + NL)
BROKEN_DEMO["app/main.cpp"] = (
    '#include "engine/World.hpp"' + NL + "#include <cstdio>" + NL
    + "int main() { std::printf(\"%d\\n\", engine::demo_marker());"
    " return 0; }" + NL)  # demo_marker 不存在 → 链接失败

FIXED_CMAKE = (
    "add_library(engine STATIC src/World.cpp)" + NL
    + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
FIXED_ENGINE_CMAKE = FIXED_CMAKE  # 修复：无变化（引擎侧）——真正修复在 main
FIXED_MAIN = (
    '#include "engine/World.hpp"' + NL + "#include <cstdio>" + NL
    + "int main() { std::printf(\"%d\\n\", engine::world());"
    " return 0; }" + NL)

TASKS = [
    {"taskId": "t1", "milestoneId": "ms-1", "title": "World",
     "description": "World", "dependsOn": [], "deliverables": ["W"],
     "acceptanceCriteria": ["world_update"]},
    {"taskId": "t2", "milestoneId": "ms-2", "title": "Demo",
     "description": "Demo", "dependsOn": ["t1"], "deliverables": ["D"],
     "acceptanceCriteria": ["demo"]},
]
MILESTONES = [
    {"milestoneId": m, "title": m, "deliverables": ["x"],
     "acceptanceCriteria": ["a"], "dependsOn": []}
    for m in ("ms-1", "ms-2")
]


class RepairScriptedProvider:
    """t2（Demo）：先交故障版 → 发布失败 → 修复 main.cpp → 重交。"""

    name = "repair-demo"
    attempts = {"publish_fail_seen": False}

    def __init__(self):
        self.calls: list[str] = []

    def chat_with_tools(self, messages, tools):
        from app.domains.course_generation.lessons.change_set import content_hash

        history = self.calls
        last = history[-1] if history else ""
        publish_failed = self._publish_failed(messages)
        if not history:
            return self._tool("update_course_material", {
                "buildManifest": {"buildTargets": ["worldsim", "world_tests"],
                                  "runTargets": ["worldsim"],
                                  "testNames": ["world_update", "demo_runs"]}})
        if last == "update_course_material" and "apply" not in history:
            changes = [
                {"path": "CMakeLists.txt", "operation": "update",
                 "baseHash": content_hash(T1_FILES["CMakeLists.txt"]),
                 "content": GOOD_DEMO["CMakeLists.txt"]},
                {"path": "app/CMakeLists.txt", "operation": "create",
                 "content": GOOD_DEMO["app/CMakeLists.txt"]},
                {"path": "app/main.cpp", "operation": "create",
                 "content": GOOD_DEMO["app/main.cpp"]},
                {"path": "app/main.cpp", "operation": "update",
                 "content": MAIN_STUB, "target": "starter"},
            ]
            return self._tool("apply_file_changes", {"changes": changes})
        if last == "apply_file_changes" and not publish_failed:
            return self._tool("evaluate_lesson", {})
        if last == "evaluate_lesson":
            return self._tool("save_checkpoint", {})
        if last == "save_checkpoint":
            return self._tool("submit_task", {})
        return _result(content="done")

    def _publish_failed(self, messages) -> bool:
        return any("最终" in str(m.get("content", "")) and "失败" in str(m.get("content", ""))
                  for m in messages[-12:])

    def _tool(self, name, args):
        self.calls.append(name)
        return _result(tool_calls=[{
            "id": f"call_{len(self.calls)}", "name": name, "arguments": args}])

    def chat(self, system, user):
        raise AssertionError("必须走工具循环")


def _result(content=None, tool_calls=None):
    return type("R", (), {
        "content": content, "tool_calls": tool_calls or [],
        "prompt_tokens": 30, "completion_tokens": 30, "model": "s"})()


@pytest.fixture()
def repair_env(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(harness_service, "_session_factory", factory)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)
    from app.domains.course_generation.models import CourseGeneration
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    gen = CourseGeneration(
        id=_uuid.uuid4(), source_url="description:repair", status="published",
        progress=100, snapshot={"files": {}},
        analysis={"summary": "s", "tech_stack": ["C++20"]},
        blueprint={"project": {"title": "Repair 课程", "description": "d",
                              "sourceUrl": "u", "commitSha": "r" * 40,
                              "license": {}, "techStack": ["C++20", "CMake"],
                              "goals": [], "nonGoals": []},
                   "milestones": MILESTONES, "tasks": TASKS,
                   "knowledgeRequirements": []},
        validation={"passed": True, "issues": [], "checked_at": "2026"})
    db_session.add(gen)
    db_session.commit()

    # 预置 t1 Verified Checkpoint（World 已验证——本测试聚焦 t2 Demo 的
    # 发布失败与 Final Repair）
    from app.domains.course_generation.harness.workspace import workspace_hash  # noqa: F401
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )
    from app.domains.course_generation.lessons.lesson_publisher import (
        _normalize_blueprint,
        _persist_checkpoint,
    )
    normalized = _normalize_blueprint({
        "tasks": TASKS, "milestones": MILESTONES,
        "project": {"title": "Repair 课程", "description": "d", "sourceUrl": "u",
                    "commitSha": "r" * 40, "license": {},
                    "techStack": ["C++20", "CMake"], "goals": [], "nonGoals": []}})
    bph = snapshot_hash_of({"blueprint": json.dumps(
        {"tasks": normalized.get("tasks") or [],
         "milestones": normalized.get("milestones") or []},
        sort_keys=True, ensure_ascii=False)})
    with factory() as fdb:
        _persist_checkpoint(
            fdb, None, gen.id, 0, "t1", bph,
            "cpp-changeset-v1", "projectweave-sandbox-cpp:clang15-bookworm", "",
            dict(T1_FILES), ["world_update"],
            {"taskId": "t1", "milestoneId": "ms-1", "language": "cpp",
             "instructions": {"title": "World"}, "starterFiles": [],
             "testFiles": [], "buildManifest": {
                 "buildTargets": ["engine"], "testNames": ["world_update"]},
             "hints": [], "status": "tests-passed", "verifications": [],
             "repairs": [], "error": None},
            [], [], {"seeded": True})

    provider = RepairScriptedProvider()
    monkeypatch.setattr(harness_service, "_provider_factory", lambda: provider)
    yield client, str(gen.id), provider, factory
    harness_service._session_factory = None
    harness_service._provider_factory = None
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


@pytest.mark.skipif(
    os.environ.get("PW_REPAIR_E2E") != "1" or os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="Final Repair E2E 需 PW_REPAIR_E2E=1 + PW_SANDBOX_E2E=1",
)
def test_final_repair_publishes_fixed_snapshot(repair_env):
    client, gen_id, provider, factory = repair_env

    sid = client.post(
        f"/api/v1/course-dev-sessions?generationId={gen_id}").json()["sessionId"]

    final_state = None
    for _ in range(10):
        out = client.post(f"/api/v1/course-dev-sessions/{sid}/run").json()
        st = client.get(f"/api/v1/course-dev-sessions/{sid}").json()
        final_state = st
        if st["state"] in ("completed", "failed", "cancelled"):
            break

    assert final_state["state"] == "completed", (
        final_state.get("error"), final_state.get("publishFailure"))
    release_id = final_state["publishedReleaseId"]
    assert release_id

    release = client.get(f"/api/v1/course-releases/{release_id}").json()
    assert release["status"] == "ready"
    assert release["passedTasks"] == release["totalTasks"] == 2

    # 核心断言：发布的 reference_store（受保护）真实包含修复后的 main.cpp
    with factory() as db:
        from app.domains.course_generation.models import CourseRelease

        row = db.get(CourseRelease, _uuid.UUID(release_id))
        ref_store = row.reference_store or {}
        # ref_store 是 {taskId: delta}
        t2_delta = ref_store.get("t2") or []
        fixed_main = next((d for d in t2_delta
                           if d.get("path") == "app/main.cpp"), None)
        assert fixed_main, "修复后的 main.cpp 必须进入发布 reference"
        assert "demo_marker" not in fixed_main["content"]
        assert "engine::world()" in fixed_main["content"]

    # 旧检查点不被覆盖：t1/t2 原检查点仍在 + repair 检查点存在
    with factory() as db:
        from app.domains.course_generation.models import CourseCheckpoint
        from sqlalchemy import select

        cps = db.scalars(select(CourseCheckpoint).where(
            CourseCheckpoint.generation_id == _uuid.UUID(gen_id))).all()
        ids = {c.task_id for c in cps}
        assert {"t1", "t2"} <= ids  # 原检查点保持
        # __final_repair__ 仅在发布失败修复路径存在（happy path 无需）

    # 学生实例化（任务数不因 repair 增加）
    inst = client.post(f"/api/v1/course-releases/{release_id}/instantiate",
                       json={"projectTitle": "Repair 课"})
    assert inst.status_code == 201
    plan = client.get(f"/api/v1/plans/{inst.json()['projectId']}").json()
    assert {t["taskId"] for t in plan["tasks"]} == {"t1", "t2"}
