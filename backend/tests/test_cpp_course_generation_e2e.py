"""P8.2.1 C++ 课程生成真实学生旅程 E2E（选入：PW_SANDBOX_E2E=1）。

Mock LLM（ChangeSet 协议确定性材料）+ **真实 Docker/Clang 15/CMake/CTest**：
种子蓝图 → 逐任务增量 ChangeSet → 确定性合成 → 一致性 → 八步验证 →
checkpoint → release ready → 实例化 → 逐任务激活/实现/服务端可信验收 →
最终报告；附验收 D（断点恢复：t1/t2 复用不调 LLM）。
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
from app.domains.course_generation.lessons.change_set import content_hash
from app.domains.projects.models import ProjectFile

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker + projectweave-sandbox-cpp:clang15-bookworm）",
)

NL = "\n"


# ---------------------------------------------------------------- 工程状态（确定性）


def _state1() -> dict:
    """t1 后的参考工程：骨架 + World（实现）。"""
    return {
        "CMakeLists.txt": (
            "cmake_minimum_required(VERSION 3.16)" + NL
            + "project(WorldSimulation LANGUAGES CXX)" + NL
            + "set(CMAKE_CXX_STANDARD 20)" + NL
            + "set(CMAKE_CXX_STANDARD_REQUIRED ON)" + NL
            + "add_subdirectory(engine)" + NL
            + "enable_testing()" + NL
            + "add_subdirectory(tests)" + NL),
        "engine/CMakeLists.txt": (
            "add_library(engine STATIC src/World.cpp)" + NL
            + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL),
        "engine/include/engine/World.hpp": (
            "#pragma once" + NL + "namespace engine {" + NL
            + "class World {" + NL + "public:" + NL
            + "    void update(double deltaTime);" + NL
            + "    double elapsed() const;" + NL + "private:" + NL
            + "    double elapsedTime_ = 0.0;" + NL + "};" + NL + "}" + NL),
        "engine/src/World.cpp": (
            '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
            + "void World::update(double deltaTime) { elapsedTime_ += deltaTime; }" + NL
            + "double World::elapsed() const { return elapsedTime_; }" + NL
            + "}" + NL),
        "tests/CMakeLists.txt": (
            "add_executable(world_tests test_world.cpp)" + NL
            + "target_link_libraries(world_tests PRIVATE engine)" + NL
            + "add_test(NAME world_update COMMAND world_tests)" + NL),
        "tests/test_world.cpp": (
            '#include "engine/World.hpp"' + NL
            + "#include <cassert>" + NL + "#include <cstdio>" + NL
            + "int main() {" + NL
            + "    engine::World w;" + NL
            + "    w.update(0.5);" + NL
            + "    w.update(1.5);" + NL
            + "    assert(w.elapsed() > 1.999 && w.elapsed() < 2.001);" + NL
            + '    std::printf("world_update ok\\n");' + NL
            + "    return 0;" + NL + "}" + NL),
    }


WORLD_STUB = (
    '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
    + "void World::update(double deltaTime) {" + NL
    + "    // TODO: 根据 deltaTime 累加世界时间" + NL
    + "}" + NL
    + "double World::elapsed() const { return elapsedTime_; }" + NL
    + "}" + NL)


def _state2() -> dict:
    """t2 后：新增 Entity（实现）。"""
    state = _state1()
    state["engine/CMakeLists.txt"] = (
        "add_library(engine STATIC src/World.cpp src/Entity.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
    state["engine/include/engine/Entity.hpp"] = (
        "#pragma once" + NL + "#include <string>" + NL + "namespace engine {" + NL
        + "class Entity {" + NL + "public:" + NL
        + "    void spawn(const std::string& name, double x, double y);" + NL
        + "    std::string describe() const;" + NL
        + "    double x() const;" + NL + "    double y() const;" + NL + "private:" + NL
        + "    std::string name_;" + NL
        + "    double x_ = 0.0;" + NL + "    double y_ = 0.0;" + NL + "};" + NL + "}" + NL)
    state["engine/src/Entity.cpp"] = (
        '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
        + "void Entity::spawn(const std::string& name, double x, double y) {" + NL
        + "    name_ = name; x_ = x; y_ = y;" + NL + "}" + NL
        + "std::string Entity::describe() const {" + NL
        + '    return name_ + "@" + std::to_string(x_) + "," + std::to_string(y_);' + NL
        + "}" + NL
        + "double Entity::x() const { return x_; }" + NL
        + "double Entity::y() const { return y_; }" + NL + "}" + NL)
    state["tests/CMakeLists.txt"] += (
        "add_executable(entity_tests test_entity.cpp)" + NL
        + "target_link_libraries(entity_tests PRIVATE engine)" + NL
        + "add_test(NAME entity_spawn COMMAND entity_tests)" + NL)
    state["tests/test_entity.cpp"] = (
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
    return state


ENTITY_STUB = (
    '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
    + "void Entity::spawn(const std::string& name, double x, double y) {" + NL
    + "    // TODO: 记录实体名字与坐标" + NL + "}" + NL
    + 'std::string Entity::describe() const { return ""; }' + NL
    + "double Entity::x() const { return x_; }" + NL
    + "double Entity::y() const { return y_; }" + NL + "}" + NL)


def _state3() -> dict:
    """t3 后：集成模块 + app demo（最终）。"""
    state = _state2()
    state["CMakeLists.txt"] = (
        "cmake_minimum_required(VERSION 3.16)" + NL
        + "project(WorldSimulation LANGUAGES CXX)" + NL
        + "set(CMAKE_CXX_STANDARD 20)" + NL
        + "set(CMAKE_CXX_STANDARD_REQUIRED ON)" + NL
        + "add_subdirectory(engine)" + NL
        + "add_subdirectory(app)" + NL
        + "enable_testing()" + NL
        + "add_subdirectory(tests)" + NL)
    state["engine/CMakeLists.txt"] = (
        "add_library(engine STATIC src/World.cpp src/Entity.cpp src/Integration.cpp)" + NL
        + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
    state["engine/include/engine/Integration.hpp"] = (
        "#pragma once" + NL + "#include <string>" + NL
        + '#include "engine/World.hpp"' + NL + '#include "engine/Entity.hpp"' + NL
        + "namespace engine {" + NL
        + "std::string simulate_step(World& world, Entity& entity, double dt);" + NL
        + "}" + NL)
    state["engine/src/Integration.cpp"] = (
        '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
        + "std::string simulate_step(World& world, Entity& entity, double dt) {" + NL
        + "    world.update(dt);" + NL
        + '    return "t=" + std::to_string(world.elapsed()) + " " + entity.describe();' + NL
        + "}" + NL + "}" + NL)
    state["app/CMakeLists.txt"] = (
        "add_executable(worldsim main.cpp)" + NL
        + "target_link_libraries(worldsim PRIVATE engine)" + NL)
    state["app/main.cpp"] = (
        '#include "engine/Integration.hpp"' + NL
        + "#include <cstdio>" + NL
        + "int main() {" + NL
        + "    engine::World world;" + NL
        + "    engine::Entity hero;" + NL
        + '    hero.spawn("hero", 1.0, 2.0);' + NL
        + '    const auto state = engine::simulate_step(world, hero, 2.0);' + NL
        + '    std::printf("%s\\n", state.c_str());' + NL
        + "    return 0;" + NL + "}" + NL)
    state["tests/CMakeLists.txt"] += (
        "add_executable(integration_tests test_integration.cpp)" + NL
        + "target_link_libraries(integration_tests PRIVATE engine)" + NL
        + "add_test(NAME worldsim_integration COMMAND integration_tests)" + NL)
    state["tests/test_integration.cpp"] = (
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
    return state


INTEGRATION_STUB = (
    '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
    + "std::string simulate_step(World& world, Entity& entity, double dt) {" + NL
    + "    // TODO: 推进世界并拼接时间与实体描述" + NL
    + '    return "";' + NL
    + "}" + NL + "}" + NL)


STATES = {1: _state1(), 2: _state2(), 3: _state3()}
STUBS = {1: {"engine/src/World.cpp": WORLD_STUB},
         2: {"engine/src/Entity.cpp": ENTITY_STUB},
         3: {"engine/src/Integration.cpp": INTEGRATION_STUB}}


def _diff_changes(base: dict, target: dict) -> list[dict]:
    """确定性推导 FileChange（create/update；测试相关归 testChanges）。"""
    changes = []
    for path in sorted(set(target) - set(base)):
        is_test = path.startswith("tests/")
        changes.append({
            "path": path, "operation": "create", "content": target[path],
            "reason": f"新增 {path}",
            "changeCategory": "test" if is_test else
            ("cmake" if "cmakelists" in path.lower() else "source"),
            "_test": is_test,
        })
    for path in sorted(set(target) & set(base)):
        if target[path] != base[path]:
            is_test = path.startswith("tests/")
            changes.append({
                "path": path, "operation": "update",
                "baseHash": content_hash(base[path]), "content": target[path],
                "reason": f"更新 {path}",
                "changeCategory": "test" if is_test else
                ("cmake" if "cmakelists" in path.lower() else "source"),
                "_test": is_test,
            })
    return changes


TASK_META = {
    1: {"taskId": "t1", "title": "工程骨架与世界时间", "expected": ["engine/src/World.cpp"],
        "manifest": {"buildTargets": ["engine", "world_tests"], "runTargets": [],
                     "testNames": ["world_update"]}},
    2: {"taskId": "t2", "title": "实体系统", "expected": ["engine/src/Entity.cpp"],
        "manifest": {"buildTargets": ["engine", "entity_tests"], "runTargets": [],
                     "testNames": ["entity_spawn"]}},
    3: {"taskId": "t3", "title": "最终集成", "expected": ["engine/src/Integration.cpp"],
        "manifest": {"buildTargets": ["worldsim", "integration_tests"],
                     "runTargets": ["worldsim"], "testNames": ["worldsim_integration"]}},
}


def _changeset_for(seq: int) -> dict:
    meta = TASK_META[seq]
    base = STATES.get(seq - 1, {})
    target = STATES[seq]
    diff = _diff_changes(base, target)
    ref_changes = [{k: v for k, v in c.items() if not k.startswith("_")}
                   for c in diff if not c["_test"]]
    test_changes = [{k: v for k, v in c.items() if not k.startswith("_")}
                    for c in diff if c["_test"]]
    starter_changes = [{
        "path": path,
        "operation": "create" if path not in target else "update",
        "baseHash": content_hash(target[path]),
        "content": stub, "reason": "挖空待实现", "changeCategory": "source",
    } for path, stub in STUBS[seq].items()]
    return {
        "taskId": meta["taskId"],
        "baseSnapshotId": "root" if not base else f"verified:t{seq - 1}",
        "baseSnapshotHash": content_hash(json.dumps(sorted(base))),
        "instructions": {
            "title": meta["title"], "context": "演化工程", "goal": meta["title"],
            "requiredConcepts": [], "features": [], "expectedFiles": meta["expected"],
            "ioBehavior": "ctest", "constraints": [], "acceptance": [],
            "relationToPrev": "", "relationToNext": "",
        },
        "referenceChanges": ref_changes,
        "starterChanges": starter_changes,
        "testChanges": test_changes,
        "buildManifest": meta["manifest"],
        "hints": [{"level": 1, "text": "方向"}, {"level": 2, "text": "概念"},
                  {"level": 3, "text": "结构"}, {"level": 4, "text": "参考级"}],
        "rationale": "确定性测试材料",
    }


CHANGESETS = {1: _changeset_for(1), 2: _changeset_for(2), 3: _changeset_for(3)}


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


class ScriptedProvider:
    """按任务返回确定性 ChangeSet；repair 调用返回空补丁（模拟修复失败/成功可控）。"""

    name = "mock-cpp"
    current_task_seq = 1
    calls: list[str] = []

    def chat(self, system, user):
        if "最小补丁" in system or "修复工程师" in system and "最小补丁" in system:
            self.calls.append(f"repair:t{self.current_task_seq}")
            return type("R", (), {"content": '{"diagnosis":"none","failureClass":"unknown","patch":[]}',
                                  "prompt_tokens": 1, "completion_tokens": 1, "model": "mock"})()
        match = re.search(r'"taskId":\s*"?t(\d)', user)
        if match:
            self.current_task_seq = int(match.group(1))
            self.calls.append(f"build:t{self.current_task_seq}")
        else:
            self.calls.append(f"repair:t{self.current_task_seq}")
            return type("R", (), {"content": '{"diagnosis":"none","failureClass":"unknown","patch":[]}',
                                  "prompt_tokens": 1, "completion_tokens": 1, "model": "mock"})()
        changeset = CHANGESETS[self.current_task_seq]
        return type("R", (), {"content": json.dumps(changeset, ensure_ascii=False),
                              "prompt_tokens": 1, "completion_tokens": 1, "model": "mock"})()


@pytest.fixture()
def cpp_course_env(client: TestClient, db_session, monkeypatch):
    """Mock LLM（ChangeSet 协议）+ 真实 Docker 沙箱。"""
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)
    provider = ScriptedProvider()
    provider.calls = []
    monkeypatch.setattr(lesson_publisher, "_provider_factory", lambda: provider)

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
    yield client, str(row.id), provider
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


_SESSION_FACTORY = None


def _student_session():
    return _SESSION_FACTORY()


def _run_student_journey(client, db_session_factory, release_id: str):
    """实例化 → 逐任务激活/实现/服务端可信验收 → 最终报告（真实沙箱）。"""
    inst = client.post(f"/api/v1/course-releases/{release_id}/instantiate",
                       json={"projectTitle": "我的世界引擎课"})
    assert inst.status_code == 201, inst.text
    project_id = inst.json()["projectId"]

    plan = client.get(f"/api/v1/plans/{project_id}").json()
    t1 = next(t for t in plan["tasks"] if t["taskId"] == "t1")
    assert t1["verification"]["buildSystem"] == "cmake"

    def evaluate(task_id, expect_pass):
        resp = client.post(f"/api/v1/projects/{project_id}/tasks/{task_id}/evaluate",
                           json={"files": [], "traceId": None, "source": "remote"})
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["passed"] is expect_pass, (task_id, result)
        return result

    def student_writes(path_to_content: dict):
        with db_session_factory() as db:
            for f in db.query(ProjectFile).filter(
                    ProjectFile.project_id == _uuid.UUID(project_id)).all():
                if f.path in path_to_content:
                    f.content = path_to_content[f.path]
            db.commit()

    evaluate("t1", expect_pass=False)
    student_writes({"engine/src/World.cpp": STATES[1]["engine/src/World.cpp"]})
    evaluate("t1", expect_pass=True)

    act = client.post(f"/api/v1/projects/{project_id}/tasks/t2/activate", json={})
    assert act.status_code == 200 and act.json()["activated"], act.text
    evaluate("t2", expect_pass=False)
    student_writes({"engine/src/Entity.cpp": STATES[2]["engine/src/Entity.cpp"]})
    evaluate("t2", expect_pass=True)

    act = client.post(f"/api/v1/projects/{project_id}/tasks/t3/activate", json={})
    assert act.status_code == 200, act.text
    evaluate("t3", expect_pass=False)
    student_writes({"engine/src/Integration.cpp": STATES[3]["engine/src/Integration.cpp"]})
    evaluate("t3", expect_pass=True)

    progress = client.get(f"/api/v1/projects/{project_id}/course-progress").json()
    assert progress["allCompleted"] is True
    report = client.get(f"/api/v1/projects/{project_id}/final-report")
    assert report.status_code == 200, report.text
    assert report.json()["completedTasks"] == 3
    return project_id


def test_cpp_worldsim_student_journey(cpp_course_env, db_session):
    global _SESSION_FACTORY
    _SESSION_FACTORY = sessionmaker(bind=db_session.get_bind(),
                                    autoflush=False, expire_on_commit=False)
    client, gen_id, provider = cpp_course_env

    # ---- 课程内容生产（ChangeSet 协议 + 真实 CMake/CTest 八步验证）
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
    assert {"final-integration", "demo-run"} <= final_kinds
    starter_check = next(v for v in arts["t1"]["verifications"]
                         if v["kind"] == "starter-expected-fail")
    assert "world_update" in (starter_check.get("note") or "")
    body = json.dumps(detail)
    assert "referenceFiles" not in body and "reference_store" not in body

    # 检查点 API（公开信息，无参考快照）
    checkpoints = client.get(f"/api/v1/course-releases/{release_id}/checkpoints").json()
    assert [c["taskId"] for c in checkpoints] == ["t1", "t2", "t3"]
    assert "snapshot" not in json.dumps(checkpoints)

    # 生成即修复记录：无修复轮（材料一次通过）
    assert arts["t1"]["repairs"] == []

    # ---- 学生旅程（真实沙箱验收）
    _run_student_journey(client, _SESSION_FACTORY, release_id)


@pytest.mark.skipif(
    os.environ.get("PW_RESUME_E2E") != "1" or os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="验收 D（断点恢复）需 PW_RESUME_E2E=1 + PW_SANDBOX_E2E=1",
)
def test_cpp_resume_from_checkpoint(cpp_course_env, db_session):
    """验收 D：t3 受控失败 → resume → t1/t2 不再调用 LLM → 完成全量。"""
    global _SESSION_FACTORY
    _SESSION_FACTORY = sessionmaker(bind=db_session.get_bind(),
                                    autoflush=False, expire_on_commit=False)
    client, gen_id, provider = cpp_course_env

    # 受控故障：t3 声明不存在的测试名 → 一致性拒绝；修复返回空补丁 → 修复失败
    original = CHANGESETS[3]
    broken = json.loads(json.dumps(original))
    broken["buildManifest"]["testNames"] = ["ghost_test"]
    CHANGESETS[3] = broken
    try:
        resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
        release_id = resp.json()["id"]
        detail = _wait_release(client, release_id)
        assert detail["status"] == "failed"
        assert detail["verificationReport"]["failed_task"] == "t3"
        first_builds = [c for c in provider.calls if c.startswith("build:")]
        assert first_builds == ["build:t1", "build:t2", "build:t3"]
    finally:
        CHANGESETS[3] = original

    # ---- resume：t1/t2 从检查点复用（不调 LLM），仅重生成 t3
    provider.calls.clear()
    resume = client.post(f"/api/v1/course-releases/{release_id}/resume")
    assert resume.status_code == 202, resume.text
    new_release_id = resume.json()["id"]
    detail = _wait_release(client, new_release_id)
    assert detail["status"] == "ready", detail.get("error")
    assert detail["releaseVersion"] == 2

    # 断言：本轮只调用 t3 的 LLM
    assert provider.calls == ["build:t3"], provider.calls
    # 旧 release 不可变（仍 failed）
    old = client.get(f"/api/v1/course-releases/{release_id}").json()
    assert old["status"] == "failed"

    _run_student_journey(client, _SESSION_FACTORY, new_release_id)


# ---------------------------------------------------------------- 真实 LLM 门控（第十八节）

REAL_LLM = pytest.mark.skipif(
    os.environ.get("PW_COURSE_E2E") != "1" or os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_COURSE_E2E=1 + PW_SANDBOX_E2E=1（真实 DeepSeek + 真实 Docker）",
)


@REAL_LLM
def test_cpp_worldsim_real_llm_generation(cpp_course_env, db_session):
    """真实 DeepSeek 增量生成 C++/CMake 世界引擎课程（真实沙箱验证全三任务）。"""
    from app.ai.provider import DeepSeekProvider

    global _SESSION_FACTORY
    _SESSION_FACTORY = sessionmaker(bind=db_session.get_bind(),
                                    autoflush=False, expire_on_commit=False)
    client, gen_id, _provider = cpp_course_env
    lesson_publisher._provider_factory = lambda: DeepSeekProvider()

    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    detail = _wait_release(client, resp.json()["id"], timeout_s=2400)
    assert detail["status"] == "ready", (
        f"真实 LLM 课程未全通过：{detail.get('error')}")
    assert detail["passedTasks"] == detail["totalTasks"] == 3
    body = json.dumps(detail)
    assert "referenceFiles" not in body

    _run_student_journey(client, _SESSION_FACTORY, detail["id"])
