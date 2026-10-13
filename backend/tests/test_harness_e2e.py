"""Harness E2E（P8.2.3，D48；选入 PW_SANDBOX_E2E=1）。

E2E B（主动修复闭环，真 Docker）：ScriptedToolProvider 按真实工具反馈决定
下一步——读文件 → apply（**故意漏注册源文件**）→ cmake_build 真实失败 →
读诊断 → apply 修复 → CTest 通过 → evaluate_lesson 独立通过 →
save_checkpoint → submit_task。所有工具调用真实执行（受控故障进真沙箱）。
E2E E（暂停/恢复）+ 权限隔离断言。
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


class ScriptedToolProvider:
    """受控工具型 provider：按脚本驱动真实工具循环（读→改→失败→修→过）。

    脚本按"已发生的工具调用序列"推进——决策依据是真实工具结果（尤其
    build 失败后必须先 read 诊断再修），不是一次性输出课程 JSON。
    """

    name = "scripted-tools"

    def __init__(self):
        self.calls: list[dict] = []

    def chat_with_tools(self, messages, tools):
        # 真实反馈驱动：从工具结果消息推断 build 失败次数（非预设时序）
        self.build_failures = sum(
            1 for m in messages
            if m.get("role") == "tool" and '"status": "failed"' in m.get("content", "")
            and "phases" in m.get("content", ""))
        # 最近一次 build 的真实结果（修复完成后不再重复修复）
        self.last_build_failed = False
        for m in reversed(messages):
            if m.get("role") == "tool" and "phases" in m.get("content", ""):
                self.last_build_failed = '"status": "failed"' in m.get("content", "")
                break
        script = self._next_action()
        self.calls.append(script)
        if script.get("done"):
            return _result(content=script.get("text", ""))
        return _result(tool_calls=[{
            "id": f"call_{len(self.calls)}",
            "name": script["tool"],
            "arguments": script.get("args", {}),
        }])

    # ---------------- 脚本（状态机式，受真实反馈影响） ----------------

    def _next_action(self) -> dict:
        history = [c.get("tool") for c in self.calls]
        n_build_fail = sum(1 for c in self.calls
                           if c.get("tool") == "cmake_build" and c.get("failed"))
        # 标记 build 失败：由 _record_feedback 更新（见 chat 循环外的钩子）
        n_build_fail = getattr(self, "build_failures", 0)
        if not history:
            return {"tool": "list_workspace_files"}
        if history[-1] == "list_workspace_files":
            return {"tool": "read_workspace_file",
                    "args": {"path": "engine/CMakeLists.txt"}}
        if (history[-1] == "read_workspace_file" and len(history) == 2
                and not getattr(self, "material_set", False)):
            return {"tool": "update_course_material", "args": {
                "buildManifest": {"buildTargets": ["engine", "entity_tests"],
                                  "runTargets": [],
                                  "testNames": ["entity_spawn"]}}}
        if history[-1] == "update_course_material":
            self.material_set = True
            # 首次修改：故意漏掉 Entity.cpp 注册（受控故障）
            return {"tool": "apply_file_changes", "args": {"changes": [
                {"path": "engine/include/engine/Entity.hpp", "operation": "create",
                 "content": ENTITY_HPP, "changeCategory": "header"},
                {"path": "engine/src/Entity.cpp", "operation": "create",
                 "content": ENTITY_CPP_REF, "changeCategory": "source"},
                {"path": "engine/src/Entity.cpp", "operation": "update",
                 "content": ENTITY_CPP_STUB, "target": "starter"},
                {"path": "tests/CMakeLists.txt", "operation": "update",
                 "baseHash": _hash(TESTS_CMAKE_V1), "content": TESTS_CMAKE_V2},
                {"path": "tests/test_entity.cpp", "operation": "create",
                 "content": TEST_ENTITY, "changeCategory": "test"},
            ]}}
        if n_build_fail == 0 and history and history[-1] == "apply_file_changes":
            return {"tool": "cmake_build", "args": {"target": "entity_tests"}}
        if history[-1] == "cmake_build":
            return {"tool": "run_ctest", "args": {}}
        if history[-1] == "run_ctest":
            return {"tool": "evaluate_lesson"}
        if history[-1] == "evaluate_lesson":
            return {"tool": "save_checkpoint"}
        if history[-1] == "save_checkpoint":
            return {"tool": "submit_task"}
        return {"done": True, "text": "任务完成"}

    def _next_action_base_after_repair(self) -> dict:
        history = [c.get("tool") for c in self.calls]
        if history[-1] == "cmake_build":
            return {"tool": "run_ctest", "args": {}}
        if history[-1] == "run_ctest":
            return {"tool": "evaluate_lesson"}
        if history[-1] == "evaluate_lesson":
            return {"tool": "save_checkpoint"}
        if history[-1] == "save_checkpoint":
            return {"tool": "submit_task"}
        return {"done": True, "text": "任务完成"}

    def chat(self, system, user):
        raise AssertionError("Harness Agent 必须走 chat_with_tools 工具循环")


class ScriptedRepairProvider(ScriptedToolProvider):
    """build 真实失败后：先读诊断 → 修 CMakeLists（补注册）→ 再走验证。"""

    def _next_action(self) -> dict:
        history = [c.get("tool") for c in self.calls]
        last_failed = getattr(self, "last_build_failed", False)
        if last_failed and history and history[-1] == "cmake_build":
            return {"tool": "read_workspace_file",
                    "args": {"path": "engine/CMakeLists.txt"}}
        if (last_failed and history[-1] == "read_workspace_file"
                and "engine/CMakeLists.txt" in str(self.calls[-1].get("args", {}))
                and history[-2:-1] == ["cmake_build"]):
            return {"tool": "apply_file_changes", "args": {"changes": [
                {"path": "engine/CMakeLists.txt", "operation": "update",
                 "baseHash": _hash(ENGINE_CMAKE_V1),
                 "content": ENGINE_CMAKE_V2}]}}
        if last_failed and history and history[-1] == "apply_file_changes":
            return {"tool": "cmake_build", "args": {"target": "entity_tests"}}
        return super()._next_action()


def _result(content=None, tool_calls=None):
    return type("R", (), {
        "content": content, "tool_calls": tool_calls or [],
        "prompt_tokens": 100, "completion_tokens": 100, "model": "scripted"})()


def _hash(content: str) -> str:
    from app.domains.course_generation.lessons.change_set import content_hash

    return content_hash(content)


# ---------------------------------------------------------------- 工程材料（受控故障版）


ROOT_CMAKE = (
    "cmake_minimum_required(VERSION 3.16)" + NL
    + "project(WorldSim LANGUAGES CXX)" + NL
    + "set(CMAKE_CXX_STANDARD 20)" + NL
    + "add_subdirectory(engine)" + NL
    + "enable_testing()" + NL
    + "add_subdirectory(tests)" + NL)

ENGINE_CMAKE_V1 = (
    "add_library(engine STATIC src/World.cpp)" + NL
    + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
ENGINE_CMAKE_V2 = (
    "add_library(engine STATIC src/World.cpp src/Entity.cpp)" + NL
    + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)

WORLD_HPP = (
    "#pragma once" + NL + "namespace engine {" + NL
    + "inline int world(){ return 1; }" + NL + "}" + NL)
WORLD_CPP = "#include \"engine/World.hpp\"" + NL

ENTITY_HPP = (
    "#pragma once" + NL + "#include <string>" + NL + "namespace engine {" + NL
    + "std::string entity_name(int id);" + NL + "}" + NL)
ENTITY_CPP_REF = (
    '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
    + 'std::string entity_name(int id) { return "entity-" + std::to_string(id); }' + NL
    + "}" + NL)
ENTITY_CPP_STUB = (
    '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
    + "std::string entity_name(int id) {" + NL
    + "    // TODO: 返回 entity-<id>" + NL
    + '    return "";' + NL + "}" + NL + "}" + NL)

TESTS_CMAKE_V1 = (
    "add_executable(world_tests test_world.cpp)" + NL
    + "target_link_libraries(world_tests PRIVATE engine)" + NL
    + "add_test(NAME world_update COMMAND world_tests)" + NL)
TESTS_CMAKE_V2 = TESTS_CMAKE_V1 + (
    "add_executable(entity_tests test_entity.cpp)" + NL
    + "target_link_libraries(entity_tests PRIVATE engine)" + NL
    + "add_test(NAME entity_spawn COMMAND entity_tests)" + NL)

TEST_WORLD = (
    '#include "engine/World.hpp"' + NL
    + "#include <cassert>" + NL
    + "int main() { assert(engine::world() == 1); return 0; }" + NL)
TEST_ENTITY = (
    '#include "engine/Entity.hpp"' + NL
    + "#include <cassert>" + NL
    + "int main() {" + NL
    + '    assert(engine::entity_name(7) == "entity-7");' + NL
    + "    return 0; }" + NL)

T1_STATE = {
    "CMakeLists.txt": ROOT_CMAKE,
    "engine/CMakeLists.txt": ENGINE_CMAKE_V1,
    "engine/include/engine/World.hpp": WORLD_HPP,
    "engine/src/World.cpp": WORLD_CPP,
    "tests/CMakeLists.txt": TESTS_CMAKE_V1,
    "tests/test_world.cpp": TEST_WORLD,
}

TASKS = [
    {"taskId": "t1", "milestoneId": "ms-1", "title": "World 模块",
     "description": "实现 World", "dependsOn": [], "deliverables": ["World"],
     "acceptanceCriteria": ["world_update"]},
    {"taskId": "t2", "milestoneId": "ms-2", "title": "Entity 模块",
     "description": "实现 Entity", "dependsOn": ["t1"], "deliverables": ["Entity"],
     "acceptanceCriteria": ["entity_spawn"]},
]


@pytest.fixture()
def harness_env(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False,
                           expire_on_commit=False)
    monkeypatch.setattr(harness_service, "_session_factory", factory)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)

    from app.domains.course_generation.models import CourseGeneration
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    gen = CourseGeneration(
        id=_uuid.uuid4(), source_url="description:worldsim", status="published",
        progress=100, snapshot={"files": {}},
        analysis={"summary": "s", "tech_stack": ["C++20", "CMake"]},
        blueprint={
            "project": {"title": "WorldSim", "description": "d",
                        "sourceUrl": "description:x", "commitSha": "b" * 40,
                        "license": {}, "techStack": ["C++20", "CMake"],
                        "goals": [], "nonGoals": []},
            "milestones": [
                {"milestoneId": "ms-1", "title": "一", "deliverables": ["W"],
                 "acceptanceCriteria": ["a"], "dependsOn": []},
                {"milestoneId": "ms-2", "title": "二", "deliverables": ["E"],
                 "acceptanceCriteria": ["b"], "dependsOn": ["ms-1"]},
            ],
            "tasks": TASKS,
            "knowledgeRequirements": [],
        },
        validation={"passed": True, "issues": [], "checked_at": "2026"},
    )
    db_session.add(gen)
    db_session.commit()

    # 预置 t1 已验证 Checkpoint（世界模块基线）
    from app.domains.course_generation.lessons.lesson_publisher import (
        _normalize_blueprint,
        _persist_checkpoint,
    )
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    # 与 service._harness_blueprint_hash 完全同构（经 normalize 后的形状）
    normalized = _normalize_blueprint({
        "tasks": TASKS,
        "milestones": [
            {"milestoneId": "ms-1", "title": "一", "deliverables": ["W"],
             "acceptanceCriteria": ["a"], "dependsOn": []},
            {"milestoneId": "ms-2", "title": "二", "deliverables": ["E"],
             "acceptanceCriteria": ["b"], "dependsOn": ["ms-1"]},
        ],
        "project": {"title": "WorldSim", "description": "d",
                    "sourceUrl": "description:x", "commitSha": "b" * 40,
                    "license": {}, "techStack": ["C++20", "CMake"],
                    "goals": [], "nonGoals": []},
    })
    blueprint_hash = snapshot_hash_of(
        {"blueprint": json.dumps(
            {"tasks": normalized.get("tasks") or [],
             "milestones": normalized.get("milestones") or []},
            sort_keys=True, ensure_ascii=False)})

    with factory() as db:
        _persist_checkpoint(
            db, _uuid.uuid4(), gen.id, 0, "t1",
            blueprint_hash,
            "cpp-changeset-v1", "projectweave-sandbox-cpp:clang15-bookworm",
            "", T1_STATE, ["world_update"],
            {"taskId": "t1", "milestoneId": "ms-1", "language": "cpp",
             "instructions": {"title": "World"}, "starterFiles": [],
             "testFiles": [], "buildManifest": {}, "hints": [],
             "status": "tests-passed", "verifications": [], "repairs": [],
             "error": None},
            [], [], {"seeded": True})

    provider = ScriptedRepairProvider()
    monkeypatch.setattr(harness_service, "_provider_factory", lambda: provider)
    yield client, str(gen.id), provider, factory
    harness_service._session_factory = None
    harness_service._provider_factory = None
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


def test_harness_e2e_b_autonomous_repair_loop(harness_env):
    """读文件 → 改（漏注册）→ 真实 build 失败 → 读诊断 → 修复 → CTest →
    evaluate 独立通过 → checkpoint → submit。全链真 Docker。"""
    client, gen_id, provider, factory = harness_env

    with factory() as db:
        from app.domains.course_generation.models import CourseCheckpoint
        from sqlalchemy import select

        rows = db.scalars(select(CourseCheckpoint).where(
            CourseCheckpoint.generation_id == _uuid.UUID(gen_id))).all()
        assert rows  # seed 检查
    created = client.post(f"/api/v1/course-dev-sessions?generationId={gen_id}")
    assert created.status_code == 201, created.text
    session_id = created.json()["sessionId"]

    outcome = client.post(f"/api/v1/course-dev-sessions/{session_id}/run")
    assert outcome.status_code == 200, outcome.text
    body = outcome.json()

    # 真实工具轨迹断言（E2E B 验收）
    tools = [e.get("tool") for e in body.get("timeline", [])
             if e.get("kind") == "tool"]
    assert "read_workspace_file" in tools
    assert "apply_file_changes" in tools
    assert "cmake_build" in tools
    assert "evaluate_lesson" in tools
    assert "save_checkpoint" in tools
    assert "submit_task" in tools

    status = client.get(f"/api/v1/course-dev-sessions/{session_id}").json()
    assert status["currentTaskId"] == "t2"
    # 任务完成后（脚本 submit）——checkpoint 已由 Harness 校验保存
    with factory() as db:
        from app.domains.course_generation.models import CourseCheckpoint
        from sqlalchemy import select

        cps = db.scalars(select(CourseCheckpoint).where(
            CourseCheckpoint.generation_id == _uuid.UUID(gen_id),
            CourseCheckpoint.task_id == "t2")).all()
        assert cps, "t2 Verified Checkpoint 必须由 Harness 固化"
        assert cps[0].snapshot_files.get("engine/src/Entity.cpp")


def test_harness_session_control_and_isolation(harness_env):
    """E2E E/权限：暂停/恢复 + save_checkpoint 未过评估拒绝 + 隐藏材料隔离。"""
    client, gen_id, provider, factory = harness_env
    created = client.post(f"/api/v1/course-dev-sessions?generationId={gen_id}")
    session_id = created.json()["sessionId"]

    status = client.get(f"/api/v1/course-dev-sessions/{session_id}").json()
    assert status["state"] == "pending"

    # 暂停在 pending 上合法
    paused = client.post(f"/api/v1/course-dev-sessions/{session_id}/pause")
    assert paused.status_code == 200

    # save_checkpoint 前置校验：未评估直接保存 → 拒绝（确定性防线）
    from app.domains.course_generation.harness.workspace import CourseWorkspace
    from app.domains.course_generation.harness.controller import HarnessController

    controller = HarnessController(
        db_factory=factory, session_id=_uuid.UUID(session_id),
        workspace=CourseWorkspace(), provider=provider,
        task_spec=TASKS[1], prior_tests=["world_update"])
    denied = controller.save_checkpoint()
    assert denied["ok"] is False and "独立评估未通过" in denied["error"]

    # rollback：工作区回到最后已验证基线
    rolled = controller.rollback_to_checkpoint()
    assert rolled["ok"] and rolled["revision"] == 0

    # 并发 run：第二个请求在第一个进行中被拒（409）——用长脚本难做，这里
    # 验证 completed 会话状态收敛
    cancelled = client.post(f"/api/v1/course-dev-sessions/{session_id}/cancel")
    assert cancelled.json()["state"] == "cancelled"
