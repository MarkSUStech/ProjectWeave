"""P8.2 C++ 课程生成真实学生旅程 E2E（选入：PW_SANDBOX_E2E=1）。

Mock LLM（材料确定）+ **真实 Docker/Clang 15/CMake/CTest**：
种子蓝图 → 逐任务 C++/CMake 材料生成 → 八步验证 → release ready →
实例化学生项目 → 逐任务激活/实现/服务端可信验收 → 最终报告。
同时验证参考实现从普通学生 API 隔离。
"""

import json
import os
import re
import time
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.course_generation.lessons import lesson_publisher
from app.domains.projects.models import ProjectFile

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker + projectweave-sandbox-cpp:clang15-bookworm）",
)

NL = "\n"


# ---------------------------------------------------------------- 三阶段演化工程（确定性材料）


def _task1_material() -> dict:
    root_cmake = (
        "cmake_minimum_required(VERSION 3.16)" + NL
        + "project(WorldSimulation LANGUAGES CXX)" + NL
        + "set(CMAKE_CXX_STANDARD 20)" + NL
        + "set(CMAKE_CXX_STANDARD_REQUIRED ON)" + NL
        + "add_subdirectory(engine)" + NL
        + "enable_testing()" + NL
        + "add_subdirectory(tests)" + NL)
    engine_cmake = (
        "add_library(engine STATIC src/World.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
    world_hpp = (
        "#pragma once" + NL + "namespace engine {" + NL
        + "class World {" + NL + "public:" + NL
        + "    void update(double deltaTime);" + NL
        + "    double elapsed() const;" + NL + "private:" + NL
        + "    double elapsedTime_ = 0.0;" + NL + "};" + NL + "}" + NL)
    world_ref = (
        '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
        + "void World::update(double deltaTime) { elapsedTime_ += deltaTime; }" + NL
        + "double World::elapsed() const { return elapsedTime_; }" + NL
        + "}" + NL)
    world_stub = (
        '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
        + "void World::update(double deltaTime) {" + NL
        + "    // TODO: 根据 deltaTime 累加世界时间" + NL
        + "}" + NL
        + "double World::elapsed() const { return elapsedTime_; }" + NL
        + "}" + NL)
    test_world = (
        '#include "engine/World.hpp"' + NL
        + "#include <cassert>" + NL + "#include <cstdio>" + NL
        + "int main() {" + NL
        + "    engine::World w;" + NL
        + "    w.update(0.5);" + NL
        + "    w.update(1.5);" + NL
        + "    assert(w.elapsed() > 1.999 && w.elapsed() < 2.001);" + NL
        + '    std::printf("world_update ok\\n");' + NL
        + "    return 0;" + NL + "}" + NL)
    tests_cmake = (
        "add_executable(world_tests test_world.cpp)" + NL
        + "target_link_libraries(world_tests PRIVATE engine)" + NL
        + "add_test(NAME world_update COMMAND world_tests)" + NL)
    return {
        "instructions": {"title": "工程骨架与世界时间", "context": "建立 CMake 多模块工程",
                         "goal": "实现 World::update 累加世界时间", "requiredConcepts": [],
                         "features": ["世界更新"], "expectedFiles": ["engine/src/World.cpp"],
                         "ioBehavior": "ctest world_update", "constraints": ["C++20 标准库"],
                         "acceptance": ["world_update 通过"], "relationToPrev": "从零开始",
                         "relationToNext": "为实体系统提供世界容器"},
        "starterFiles": [
            {"path": "CMakeLists.txt", "content": root_cmake},
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/World.hpp", "content": world_hpp},
            {"path": "engine/src/World.cpp", "content": world_stub},
        ],
        "testFiles": [
            {"path": "tests/CMakeLists.txt", "content": tests_cmake},
            {"path": "tests/test_world.cpp", "content": test_world},
        ],
        "referenceFiles": [
            {"path": "CMakeLists.txt", "content": root_cmake},
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/World.hpp", "content": world_hpp},
            {"path": "engine/src/World.cpp", "content": world_ref},
        ],
        "buildManifest": {"buildTargets": ["engine", "world_tests"],
                          "runTargets": [], "testNames": ["world_update"]},
        "hints": [{"level": 1, "text": "累加即可"}, {"level": 2, "text": "elapsedTime_ += deltaTime"},
                  {"level": 3, "text": "成员累加"}, {"level": 4, "text": "参考实现思路"}],
    }


def _task2_material() -> dict:
    starter_base = _task1_material()["referenceFiles"]  # 前序已完成部分原样保留
    entity_hpp = (
        "#pragma once" + NL + "#include <string>" + NL + "namespace engine {" + NL
        + "class Entity {" + NL + "public:" + NL
        + "    void spawn(const std::string& name, double x, double y);" + NL
        + "    std::string describe() const;" + NL
        + "    double x() const;" + NL + "    double y() const;" + NL + "private:" + NL
        + "    std::string name_;" + NL
        + "    double x_ = 0.0;" + NL + "    double y_ = 0.0;" + NL + "};" + NL + "}" + NL)
    entity_ref = (
        '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
        + "void Entity::spawn(const std::string& name, double x, double y) {" + NL
        + "    name_ = name; x_ = x; y_ = y;" + NL + "}" + NL
        + "std::string Entity::describe() const {" + NL
        + '    return name_ + "@" + std::to_string(x_) + "," + std::to_string(y_);' + NL
        + "}" + NL
        + "double Entity::x() const { return x_; }" + NL
        + "double Entity::y() const { return y_; }" + NL + "}" + NL)
    entity_stub = (
        '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
        + "void Entity::spawn(const std::string& name, double x, double y) {" + NL
        + "    // TODO: 记录实体名字与坐标" + NL + "}" + NL
        + 'std::string Entity::describe() const { return ""; }' + NL
        + "double Entity::x() const { return x_; }" + NL
        + "double Entity::y() const { return y_; }" + NL + "}" + NL)
    test_entity = (
        '#include "engine/Entity.hpp"' + NL
        + "#include <cassert>" + NL + "#include <cstdio>" + NL
        + "int main() {" + NL
        + "    engine::Entity e;" + NL
        + '    e.spawn("hero", 1.5, -2.0);' + NL
        + "    const auto d = e.describe();" + NL
        + '    assert(d.find("hero") != std::string::npos);' + NL
        + "    assert(e.x() > 1.49 && e.x() < 1.51);" + NL
        + '    std::printf("entity_spawn ok\\n");' + NL
        + "    return 0;" + NL + "}" + NL)
    engine_cmake = (
        "add_library(engine STATIC src/World.cpp src/Entity.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
    tests_cmake = (
        "add_executable(world_tests test_world.cpp)" + NL
        + "target_link_libraries(world_tests PRIVATE engine)" + NL
        + "add_test(NAME world_update COMMAND world_tests)" + NL
        + "add_executable(entity_tests test_entity.cpp)" + NL
        + "target_link_libraries(entity_tests PRIVATE engine)" + NL
        + "add_test(NAME entity_spawn COMMAND entity_tests)" + NL)
    return {
        "instructions": {"title": "实体系统", "context": "在演化工程上新增实体模块",
                         "goal": "实现 Entity::spawn/describe", "requiredConcepts": [],
                         "features": ["实体生成"], "expectedFiles": ["engine/src/Entity.cpp"],
                         "ioBehavior": "ctest entity_spawn", "constraints": ["不修改已完成 World"],
                         "acceptance": ["entity_spawn 通过且 world_update 回归通过"],
                         "relationToPrev": "世界容器已就绪", "relationToNext": "为集成做准备"},
        "starterFiles": starter_base + [
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/Entity.hpp", "content": entity_hpp},
            {"path": "engine/src/Entity.cpp", "content": entity_stub},
        ],
        "testFiles": [
            {"path": "tests/CMakeLists.txt", "content": tests_cmake},
            {"path": "tests/test_entity.cpp", "content": test_entity},
        ],
        "referenceFiles": starter_base + [
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/Entity.hpp", "content": entity_hpp},
            {"path": "engine/src/Entity.cpp", "content": entity_ref},
        ],
        "buildManifest": {"buildTargets": ["engine", "entity_tests"],
                          "runTargets": [], "testNames": ["entity_spawn"]},
        "hints": [{"level": 1, "text": "保存三个字段"}, {"level": 2, "text": "describe 拼接名字与坐标"},
                  {"level": 3, "text": "name_ + \"@\" + ..."}, {"level": 4, "text": "参考实现思路"}],
    }


def _task3_material() -> dict:
    prev_ref = _task2_material()["referenceFiles"]
    root_cmake = (
        "cmake_minimum_required(VERSION 3.16)" + NL
        + "project(WorldSimulation LANGUAGES CXX)" + NL
        + "set(CMAKE_CXX_STANDARD 20)" + NL
        + "set(CMAKE_CXX_STANDARD_REQUIRED ON)" + NL
        + "add_subdirectory(engine)" + NL
        + "add_subdirectory(app)" + NL
        + "enable_testing()" + NL
        + "add_subdirectory(tests)" + NL)
    app_cmake = (
        "add_executable(worldsim main.cpp)" + NL
        + "target_link_libraries(worldsim PRIVATE engine)" + NL)
    integration_hpp = (
        "#pragma once" + NL + "#include <string>" + NL
        + '#include "engine/World.hpp"' + NL + '#include "engine/Entity.hpp"' + NL
        + "namespace engine {" + NL
        + "std::string simulate_step(World& world, Entity& entity, double dt);" + NL
        + "}" + NL)
    integration_ref = (
        '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
        + "std::string simulate_step(World& world, Entity& entity, double dt) {" + NL
        + "    world.update(dt);" + NL
        + '    return "t=" + std::to_string(world.elapsed()) + " " + entity.describe();' + NL
        + "}" + NL + "}" + NL)
    integration_stub = (
        '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
        + "std::string simulate_step(World& world, Entity& entity, double dt) {" + NL
        + "    // TODO: 推进世界并拼接时间与实体描述" + NL
        + '    return "";' + NL
        + "}" + NL + "}" + NL)
    engine_cmake = (
        "add_library(engine STATIC src/World.cpp src/Entity.cpp src/Integration.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
    main_ref = (
        '#include "engine/Integration.hpp"' + NL
        + "#include <cstdio>" + NL
        + "int main() {" + NL
        + "    engine::World world;" + NL
        + "    engine::Entity hero;" + NL
        + '    hero.spawn("hero", 1.0, 2.0);' + NL
        + '    const auto state = engine::simulate_step(world, hero, 2.0);' + NL
        + '    std::printf("%s\\n", state.c_str());' + NL
        + "    return 0;" + NL + "}" + NL)
    main_stub = main_ref  # main 已给定；本任务挖空在 engine/src/Integration.cpp
    test_integration = (
        '#include "engine/Integration.hpp"' + NL
        + "#include <cassert>" + NL + "#include <cstdio>" + NL
        + "int main() {" + NL
        + "    engine::World world;" + NL
        + "    engine::Entity e;" + NL
        + '    e.spawn("npc", 0.0, 0.0);' + NL
        + '    const auto s = engine::simulate_step(world, e, 3.0);' + NL
        + "    assert(world.elapsed() > 2.99 && world.elapsed() < 3.01);" + NL
        + '    assert(s.find("npc") != std::string::npos);' + NL
        + '    std::printf("worldsim_integration ok\\n");' + NL
        + "    return 0;" + NL + "}" + NL)
    tests_cmake = (
        "add_executable(world_tests test_world.cpp)" + NL
        + "target_link_libraries(world_tests PRIVATE engine)" + NL
        + "add_test(NAME world_update COMMAND world_tests)" + NL
        + "add_executable(entity_tests test_entity.cpp)" + NL
        + "target_link_libraries(entity_tests PRIVATE engine)" + NL
        + "add_test(NAME entity_spawn COMMAND entity_tests)" + NL
        + "add_executable(integration_tests test_integration.cpp)" + NL
        + "target_link_libraries(integration_tests PRIVATE engine)" + NL
        + "add_test(NAME worldsim_integration COMMAND integration_tests)" + NL)
    return {
        "instructions": {"title": "最终集成", "context": "连接世界与实体，交付可运行程序",
                         "goal": "app/worldsim 打印模拟状态", "requiredConcepts": [],
                         "features": ["集成演示"], "expectedFiles": ["engine/src/Integration.cpp"],
                         "ioBehavior": "./worldsim 输出 elapsed 与 entity",
                         "constraints": ["全部测试保持通过"], "acceptance": ["全量 CTest 通过 + demo 运行"],
                         "relationToPrev": "世界与实体均已实现", "relationToNext": "课程完结"},
        "starterFiles": prev_ref + [
            {"path": "CMakeLists.txt", "content": root_cmake},
            {"path": "app/CMakeLists.txt", "content": app_cmake},
            {"path": "app/main.cpp", "content": main_stub},
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/Integration.hpp", "content": integration_hpp},
            {"path": "engine/src/Integration.cpp", "content": integration_stub},
        ],
        "testFiles": [
            {"path": "tests/CMakeLists.txt", "content": tests_cmake},
            {"path": "tests/test_integration.cpp", "content": test_integration},
        ],
        "referenceFiles": prev_ref + [
            {"path": "CMakeLists.txt", "content": root_cmake},
            {"path": "app/CMakeLists.txt", "content": app_cmake},
            {"path": "app/main.cpp", "content": main_ref},
            {"path": "engine/CMakeLists.txt", "content": engine_cmake},
            {"path": "engine/include/engine/Integration.hpp", "content": integration_hpp},
            {"path": "engine/src/Integration.cpp", "content": integration_ref},
        ],
        "buildManifest": {"buildTargets": ["worldsim", "integration_tests"],
                          "runTargets": ["worldsim"], "testNames": ["worldsim_integration"]},
        "hints": [{"level": 1, "text": "组合两个模块"}, {"level": 2, "text": "printf 拼输出"},
                  {"level": 3, "text": "world.elapsed() + hero.describe()"}, {"level": 4, "text": "参考实现思路"}],
    }


MATERIALS = {"t1": _task1_material(), "t2": _task2_material(), "t3": _task3_material()}


def _cpp_blueprint() -> dict:
    return {
        "project": {"title": "世界模拟引擎", "description": "C++20/CMake 世界模拟引擎课程",
                    "sourceUrl": "description:worldsim", "commitSha": "b" * 40, "license": {},
                    "techStack": ["C++20", "CMake", "CTest"], "finalArtifact": "worldsim 可执行程序",
                    "goals": [], "nonGoals": []},
        "milestones": [
            {"milestoneId": "ms-1", "title": "骨架", "deliverables": ["World"], "acceptanceCriteria": ["world_update"], "dependsOn": []},
            {"milestoneId": "ms-2", "title": "实体", "deliverables": ["Entity"], "acceptanceCriteria": ["entity_spawn"], "dependsOn": ["ms-1"]},
            {"milestoneId": "ms-3", "title": "集成", "deliverables": ["worldsim"], "acceptanceCriteria": ["integration"], "dependsOn": ["ms-2"]},
        ],
        "tasks": [
            {"taskId": "t1", "milestoneId": "ms-1", "title": "工程骨架与世界时间", "description": "d",
             "dependsOn": [], "deliverables": ["World"], "acceptanceCriteria": ["world_update"], "sourceEvidence": []},
            {"taskId": "t2", "milestoneId": "ms-2", "title": "实体系统", "description": "d",
             "dependsOn": ["t1"], "deliverables": ["Entity"], "acceptanceCriteria": ["entity_spawn"], "sourceEvidence": []},
            {"taskId": "t3", "milestoneId": "ms-3", "title": "最终集成", "description": "d",
             "dependsOn": ["t2"], "deliverables": ["worldsim"], "acceptanceCriteria": ["integration"], "sourceEvidence": []},
        ],
        "knowledgeRequirements": [],
    }


@pytest.fixture()
def cpp_course_env(client: TestClient, db_session, monkeypatch):
    """Mock LLM（按任务返回确定性材料）+ 真实 Docker 沙箱。"""
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)

    class ScriptedProvider:
        """按当前任务返回确定性材料；修复轮返回同任务材料（模拟完美修复）。"""

        name = "mock-cpp"
        current_task = "t1"
        calls: list[str] = []

        def chat(self, system, user):
            match = re.search(r'"taskId":\s*"(t\d)"', user)
            if match:
                self.current_task = match.group(1)
                self.calls.append(f"build:{self.current_task}")
            else:
                self.calls.append(f"repair:{self.current_task}")
            material = MATERIALS[self.current_task]
            return type("R", (), {"content": json.dumps(material, ensure_ascii=False),
                                  "prompt_tokens": 1, "completion_tokens": 1, "model": "mock"})()

    monkeypatch.setattr(lesson_publisher, "_provider_factory", lambda: ScriptedProvider())

    from app.domains.course_generation.models import CourseGeneration
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    blueprint = _cpp_blueprint()
    for t in blueprint["tasks"]:
        t["requiredConcepts"] = []
    row = CourseGeneration(
        id=_uuid.uuid4(), source_url="description:worldsim", status="published", stage=None,
        progress=100, repo_owner=None, repo_name=None, commit_sha="b" * 40,
        default_branch=None, license_info={}, snapshot={"files": {}, "tree": [], "stats": {},
                                                        "license": {}, "meta": {}},
        analysis={"summary": "s", "tech_stack": ["C++20", "CMake"]},
        blueprint=blueprint,
        validation={"passed": True, "issues": [], "checked_at": "2026-10-12T00:00:00Z"},
    )
    db_session.add(row)
    db_session.commit()
    yield client, str(row.id)
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


def _wait_release(client: TestClient, release_id: str, timeout_s: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/course-releases/{release_id}").json()
        if detail["status"] in ("ready", "failed"):
            return detail
        time.sleep(1.0)
    pytest.fail("课程内容生产未在期限内到达终态")


def test_cpp_worldsim_student_journey(cpp_course_env, db_session):
    client, gen_id = cpp_course_env

    # ---- 课程内容生产（真实 CMake/CTest 验证三阶段演化工程）
    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    release_id = resp.json()["id"]
    detail = _wait_release(client, release_id)
    assert detail["status"] == "ready", detail.get("error")
    assert detail["language"] == "cpp"
    assert detail["passedTasks"] == detail["totalTasks"] == 3

    arts = {a["taskId"]: a for a in detail["artifacts"]}
    for tid in ("t1", "t2"):
        kinds = {v["kind"] for v in arts[tid]["verifications"]}
        assert {"cmake-discovery", "reference-tests", "starter-expected-fail"} <= kinds, (tid, kinds)
    final_kinds = {v["kind"] for v in arts["t3"]["verifications"]}
    assert {"cmake-discovery", "reference-tests", "starter-expected-fail",
            "final-integration", "demo-run"} <= final_kinds
    assert arts["t1"]["buildManifest"]["testNames"] == ["world_update"]
    # 参考实现隔离：普通 API 永不下发 referenceFiles
    body = json.dumps(detail)
    assert "referenceFiles" not in body and "reference_store" not in body

    # ---- 实例化学生项目
    inst = client.post(f"/api/v1/course-releases/{release_id}/instantiate",
                       json={"projectTitle": "我的世界引擎课"})
    assert inst.status_code == 201, inst.text
    project_id = inst.json()["projectId"]
    files = {f["path"] for f in client.get(f"/api/v1/projects/{project_id}/files").json()["items"]}
    assert {"CMakeLists.txt", "engine/src/World.cpp", "tests/test_world.cpp"} <= files

    plan = client.get(f"/api/v1/plans/{project_id}").json()
    t1 = next(t for t in plan["tasks"] if t["taskId"] == "t1")
    assert t1["verification"]["buildSystem"] == "cmake"
    assert t1["verification"]["testNames"] == ["world_update"]

    def evaluate(task_id, expect_pass):
        resp = client.post(f"/api/v1/projects/{project_id}/tasks/{task_id}/evaluate",
                           json={"files": [], "traceId": None, "source": "remote"})
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["passed"] is expect_pass, (task_id, result)
        return result

    def student_writes(path_to_content: dict):
        for f in db_session.query(ProjectFile).filter(
                ProjectFile.project_id == _uuid.UUID(project_id)).all():
            if f.path in path_to_content:
                f.content = path_to_content[f.path]
        db_session.commit()

    # ---- t1：starter 状态验收失败（服务端真实沙箱判定，不信客户端）
    evaluate("t1", expect_pass=False)
    student_writes({"engine/src/World.cpp": MATERIALS["t1"]["referenceFiles"][3]["content"]})
    evaluate("t1", expect_pass=True)

    # ---- t2：激活注入实体 starter → 实现 → 验收（含 world_update 回归）
    progress = client.get(f"/api/v1/projects/{project_id}/course-progress").json()
    assert next(t for t in progress["tasks"] if t["taskId"] == "t2")["status"] == "available"
    act = client.post(f"/api/v1/projects/{project_id}/tasks/t2/activate", json={})
    assert act.status_code == 200 and act.json()["activated"], act.text
    evaluate("t2", expect_pass=False)
    student_writes({"engine/src/Entity.cpp": MATERIALS["t2"]["referenceFiles"][-1]["content"]})
    evaluate("t2", expect_pass=True)

    # ---- t3：最终集成 → 全部完成 → 最终报告
    act = client.post(f"/api/v1/projects/{project_id}/tasks/t3/activate", json={})
    assert act.status_code == 200, act.text
    evaluate("t3", expect_pass=False)
    student_writes({"engine/src/Integration.cpp": MATERIALS["t3"]["referenceFiles"][-1]["content"]})
    evaluate("t3", expect_pass=True)

    progress = client.get(f"/api/v1/projects/{project_id}/course-progress").json()
    assert progress["allCompleted"] is True
    report = client.get(f"/api/v1/projects/{project_id}/final-report")
    assert report.status_code == 200, report.text
    assert report.json()["completedTasks"] == 3


# ---------------------------------------------------------------- 真实 LLM 门控（P8.2 验收第十八节）

REAL_LLM = pytest.mark.skipif(
    os.environ.get("PW_COURSE_E2E") != "1" or os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_COURSE_E2E=1 + PW_SANDBOX_E2E=1（真实 DeepSeek + 真实 Docker）",
)


@REAL_LLM
def test_cpp_worldsim_real_llm_generation(cpp_course_env):
    """真实 DeepSeek 从项目描述生成 C++/CMake 世界引擎课程（真实沙箱验证）。

    与 Mock 版共用蓝图种子：差异仅在 LLM 真实生成材料（含可能的修复轮）。
    """
    import json as _json

    from app.ai.provider import DeepSeekProvider

    client, gen_id = cpp_course_env
    lesson_publisher._provider_factory = lambda: DeepSeekProvider()

    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    detail = _wait_release(client, resp.json()["id"], timeout_s=1800)
    # 如实断言：ready 需要全任务通过真实 CMake/CTest 验证
    assert detail["status"] == "ready", (
        f"真实 LLM 课程未全通过：{detail.get('error')}")
    assert detail["passedTasks"] == detail["totalTasks"]
    body = _json.dumps(detail)
    assert "referenceFiles" not in body
