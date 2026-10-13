"""P8.2.3.2 Level B：四任务从零 Scripted Agent + 真 Docker 全流程 E2E。

从空工程开始：t1 World → t2 Entity → t3 Integration → t4 Demo，每任务
经独立评估（真 CMake/CTest/稳定性）→ Verified Checkpoint → 最终全量验收
+ Demo → 自动发布 ready CourseRelease → 学生实例化 → 逐任务实现/验收/
解锁 → 最终报告。脚本工具调用真实执行（受控序列、真沙箱）。
"""

import json
import os
import time
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.course_generation.harness import service as harness_service
from app.domains.course_generation.lessons import lesson_publisher
from app.domains.projects.models import ProjectFile

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker + clang15 镜像）",
)

NL = "\n"


# ---------------------------------------------------------------- 四任务工程（受控但全链真实验证）


def _cumulative(seq: int) -> dict:
    """任务 N 完成后的累积参考工程。"""
    files = {}
    if seq >= 1:
        files.update({
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
                + "class World {" + NL + "public:" + NL
                + "    void update(double dt);" + NL
                + "    double elapsed() const;" + NL + "private:" + NL
                + "    double t_ = 0.0;" + NL + "};" + NL + "}" + NL),
            "engine/src/World.cpp": (
                '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
                + "void World::update(double dt) { t_ += dt; }" + NL
                + "double World::elapsed() const { return t_; }" + NL + "}" + NL),
            "tests/CMakeLists.txt": (
                "add_executable(world_tests test_world.cpp)" + NL
                + "target_link_libraries(world_tests PRIVATE engine)" + NL
                + "add_test(NAME world_update COMMAND world_tests)" + NL),
            "tests/test_world.cpp": (
                '#include "engine/World.hpp"' + NL + "#include <cassert>" + NL
                + "int main() {" + NL
                + "    engine::World w; w.update(1.5); w.update(0.5);" + NL
                + "    assert(w.elapsed() > 1.99 && w.elapsed() < 2.01);" + NL
                + "    return 0; }" + NL),
        })
    if seq >= 2:
        files["engine/CMakeLists.txt"] = (
            "add_library(engine STATIC src/World.cpp src/Entity.cpp)" + NL
            + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
        files["engine/include/engine/Entity.hpp"] = (
            "#pragma once" + NL + "#include <string>" + NL + "namespace engine {" + NL
            + "class Entity {" + NL + "public:" + NL
            + "    void spawn(const std::string& n, double x, double y);" + NL
            + "    std::string describe() const;" + NL + "private:" + NL
            + "    std::string name_;" + NL + "};" + NL + "}" + NL)
        files["engine/src/Entity.cpp"] = (
            '#include "engine/Entity.hpp"' + NL + "#include <sstream>" + NL
            + "namespace engine {" + NL
            + "void Entity::spawn(const std::string& n, double x, double y) {" + NL
            + "    std::ostringstream os; os << n << \"@\" << x << \",\" << y;" + NL
            + "    name_ = os.str(); }" + NL
            + "std::string Entity::describe() const { return name_; }" + NL
            + "}" + NL)
        files["tests/CMakeLists.txt"] += (
            "add_executable(entity_tests test_entity.cpp)" + NL
            + "target_link_libraries(entity_tests PRIVATE engine)" + NL
            + "add_test(NAME entity_spawn COMMAND entity_tests)" + NL)
        files["tests/test_entity.cpp"] = (
            '#include "engine/Entity.hpp"' + NL + "#include <cassert>" + NL
            + "int main() {" + NL
            + "    engine::Entity e; e.spawn(\"hero\", 1.0, 2.0);" + NL
            + "    assert(e.describe().find(\"hero\") != std::string::npos);" + NL
            + "    return 0; }" + NL)
    if seq >= 3:
        files["engine/CMakeLists.txt"] = (
            "add_library(engine STATIC src/World.cpp src/Entity.cpp src/Integration.cpp)" + NL
            + "target_include_directories(engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)" + NL)
        files["engine/include/engine/Integration.hpp"] = (
            "#pragma once" + NL + "#include <string>" + NL
            + '#include "engine/World.hpp"' + NL + '#include "engine/Entity.hpp"' + NL
            + "namespace engine {" + NL
            + "std::string simulate_step(World& w, Entity& e, double dt);" + NL
            + "}" + NL)
        files["engine/src/Integration.cpp"] = (
            '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
            + "std::string simulate_step(World& w, Entity& e, double dt) {" + NL
            + "    w.update(dt); return e.describe() + \" t=\" " + NL
            + "        + std::to_string(w.elapsed()); }" + NL + "}" + NL)
        files["tests/CMakeLists.txt"] += (
            "add_executable(integration_tests test_integration.cpp)" + NL
            + "target_link_libraries(integration_tests PRIVATE engine)" + NL
            + "add_test(NAME integration_step COMMAND integration_tests)" + NL)
        files["tests/test_integration.cpp"] = (
            '#include "engine/Integration.hpp"' + NL + "#include <cassert>" + NL
            + "int main() {" + NL
            + "    engine::World w; engine::Entity e;" + NL
            + '    e.spawn("npc", 0.0, 0.0);' + NL
            + '    const auto s = engine::simulate_step(w, e, 3.0);' + NL
            + "    assert(w.elapsed() > 2.99 && w.elapsed() < 3.01);" + NL
            + '    assert(s.find("npc") != std::string::npos);' + NL
            + "    return 0; }" + NL)
    if seq >= 4:
        files["CMakeLists.txt"] = (
            "cmake_minimum_required(VERSION 3.16)" + NL
            + "project(WorldSim LANGUAGES CXX)" + NL
            + "set(CMAKE_CXX_STANDARD 20)" + NL
            + "add_subdirectory(engine)" + NL
            + "enable_testing()" + NL
            + "add_subdirectory(app)" + NL
            + "add_subdirectory(tests)" + NL)
        files["app/banner.hpp"] = (
            "#pragma once" + NL + "#include <string>" + NL + "namespace app {" + NL
            + "std::string render_banner();" + NL + "}" + NL)
        files["app/banner.cpp"] = (
            '#include "banner.hpp"' + NL + "namespace app {" + NL
            + 'std::string render_banner() { return "== WorldSim =="; }' + NL
            + "}" + NL)
        files["app/CMakeLists.txt"] = (
            "add_executable(worldsim main.cpp banner.cpp)" + NL
            + "target_include_directories(worldsim PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})" + NL
            + "target_link_libraries(worldsim PRIVATE engine)" + NL)
        files["app/main.cpp"] = (
            '#include "banner.hpp"' + NL
            + '#include "engine/Integration.hpp"' + NL + "#include <cstdio>" + NL
            + "int main() {" + NL
            + '    std::printf("%s\\n", app::render_banner().c_str());' + NL
            + "    engine::World w; engine::Entity e;" + NL
            + '    e.spawn("hero", 1.0, 2.0);' + NL
            + '    const auto s = engine::simulate_step(w, e, 2.0);' + NL
            + '    std::printf("%s\\n", s.c_str());' + NL
            + "    return 0; }" + NL)
        files["tests/CMakeLists.txt"] += (
            "add_executable(banner_tests test_banner.cpp \"../app/banner.cpp\")" + NL
            + "target_include_directories(banner_tests PRIVATE ../app)" + NL
            + "add_test(NAME demo_banner COMMAND banner_tests)" + NL)
        files["tests/test_banner.cpp"] = (
            '#include "banner.hpp"' + NL + "#include <cassert>" + NL
            + "int main() {" + NL
            + "    const auto b = app::render_banner();" + NL
            + '    assert(b.find("WorldSim") != std::string::npos);' + NL
            + "    return 0; }" + NL)
    return files


def _stubs(seq: int) -> dict:
    return {
        1: {"engine/src/World.cpp": (
            '#include "engine/World.hpp"' + NL + "namespace engine {" + NL
            + "void World::update(double dt) {" + NL
            + "    // TODO: 累加时间" + NL + "}" + NL
            + "double World::elapsed() const { return t_; }" + NL + "}" + NL)},
        2: {"engine/src/Entity.cpp": (
            '#include "engine/Entity.hpp"' + NL + "namespace engine {" + NL
            + "void Entity::spawn(const std::string& n, double x, double y) {" + NL
            + "    // TODO: 记录实体位置" + NL + "}" + NL
            + 'std::string Entity::describe() const { return ""; }' + NL
            + "}" + NL)},
        3: {"engine/src/Integration.cpp": (
            '#include "engine/Integration.hpp"' + NL + "namespace engine {" + NL
            + "std::string simulate_step(World& w, Entity& e, double dt) {" + NL
            + "    // TODO: 推进并拼接状态" + NL
            + '    return ""; }' + NL + "}" + NL)},
        4: {"app/banner.cpp": (
            '#include "banner.hpp"' + NL + "namespace app {" + NL
            + "std::string render_banner() {" + NL
            + "    // TODO: 返回演示横幅" + NL
            + '    return ""; }' + NL + "}" + NL)},
    }[seq]


def _manifest(seq: int, cumulative_tests: list[str]) -> dict:
    own = {1: ["world_update"], 2: ["entity_spawn"],
           3: ["integration_step"], 4: ["demo_banner"]}[seq]
    run_targets = ["worldsim"] if seq == 4 else []
    build = {1: ["engine", "world_tests"], 2: ["engine", "entity_tests"],
             3: ["engine", "integration_tests"],
             4: ["worldsim", "banner_tests"]}[seq]
    return {"buildTargets": build, "runTargets": run_targets,
            "testNames": [*cumulative_tests, *own]}


_OWN_TESTS = {1: ["world_update"], 2: ["entity_spawn"],
              3: ["integration_step"], 4: ["demo_banner"]}


class FourTaskScriptedProvider:
    """四任务脚本：每任务 材料→apply→评估→保存→提交（真沙箱验证）。"""

    name = "four-task"

    def __init__(self):
        self.calls: list[str] = []
        self.current_seq = 1

    def chat_with_tools(self, messages, tools):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        # 从 system 识别当前任务
        for seq in (4, 3, 2, 1):
            if f"任务 t{seq}" in system or f'"taskId": "t{seq}"' in system:
                self.current_seq = seq
                break
        seq = self.current_seq
        prefix = f"t{seq}"
        tag = f":{prefix}"
        history = self.calls
        seq_history = [c.split(":", 1)[0] for c in history if c.endswith(tag)]

        if not seq_history:
            cumulative_tests = []
            for s in range(1, seq):
                cumulative_tests.extend(_OWN_TESTS[s])
            return self._tool("update_course_material", {
                "buildManifest": _manifest(seq, cumulative_tests)}, tag)
        last = seq_history[-1]
        if last == "update_course_material":
            changes = self._changes_for(seq)
            return self._tool("apply_file_changes", {"changes": changes}, tag)
        if last == "apply_file_changes":
            return self._tool("evaluate_lesson", {}, tag)
        if last == "evaluate_lesson":
            return self._tool("save_checkpoint", {}, tag)
        if last == "save_checkpoint":
            return self._tool("submit_task", {}, tag)
        return _result(content="done")

    def _changes_for(self, seq: int) -> list[dict]:
        from app.domains.course_generation.lessons.change_set import content_hash

        base = _cumulative(seq - 1) if seq > 1 else {}
        target = _cumulative(seq)
        changes = []
        for path in sorted(set(target) - set(base)):
            changes.append({"path": path, "operation": "create",
                            "content": target[path], "changeCategory": "source"})
        for path in sorted(set(target) & set(base)):
            if target[path] != base[path]:
                changes.append({"path": path, "operation": "update",
                                "baseHash": content_hash(base[path]),
                                "content": target[path], "changeCategory": "cmake"})
        for path, stub in _stubs(seq).items():
            changes.append({"path": path, "operation": "update",
                            "baseHash": content_hash(target[path]),
                            "content": stub, "target": "starter"})
        return changes

    def _tool(self, name, args, tag):
        self.calls.append(f"{name}{tag}")
        return _result(tool_calls=[{
            "id": f"call_{len(self.calls)}", "name": name, "arguments": args}])

    def chat(self, system, user):
        raise AssertionError("必须走工具循环")


def _result(content=None, tool_calls=None):
    return type("R", (), {
        "content": content, "tool_calls": tool_calls or [],
        "prompt_tokens": 50, "completion_tokens": 50, "model": "scripted"})()


TASKS_4 = [
    {"taskId": "t1", "milestoneId": "ms-1", "title": "World 模块",
     "description": "实现 World 时间更新", "dependsOn": [],
     "deliverables": ["World"], "acceptanceCriteria": ["world_update"]},
    {"taskId": "t2", "milestoneId": "ms-2", "title": "Entity 模块",
     "description": "实现 Entity 生成", "dependsOn": ["t1"],
     "deliverables": ["Entity"], "acceptanceCriteria": ["entity_spawn"]},
    {"taskId": "t3", "milestoneId": "ms-3", "title": "Integration",
     "description": "World 与 Entity 协作", "dependsOn": ["t2"],
     "deliverables": ["Integration"], "acceptanceCriteria": ["integration_step"]},
    {"taskId": "t4", "milestoneId": "ms-4", "title": "Demo",
     "description": "最终可执行程序", "dependsOn": ["t3"],
     "deliverables": ["Demo"], "acceptanceCriteria": ["demo 运行"]},
]

MILESTONES_4 = [
    {"milestoneId": f"ms-{i+1}", "title": f"M{i+1}", "deliverables": [t["deliverables"][0]],
     "acceptanceCriteria": t["acceptanceCriteria"], "dependsOn": []}
    for i, t in enumerate(TASKS_4)
]


@pytest.fixture()
def full_course_env(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(harness_service, "_session_factory", factory)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)

    from app.domains.course_generation.models import CourseGeneration
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    gen = CourseGeneration(
        id=_uuid.uuid4(), source_url="description:worldsim4", status="published",
        progress=100, snapshot={"files": {}},
        analysis={"summary": "s", "tech_stack": ["C++20"]},
        blueprint={
            "project": {"title": "WorldSim 四任务", "description": "d",
                        "sourceUrl": "description:worldsim4", "commitSha": "c" * 40,
                        "license": {}, "techStack": ["C++20", "CMake"],
                        "goals": [], "nonGoals": []},
            "milestones": MILESTONES_4, "tasks": TASKS_4,
            "knowledgeRequirements": []},
        validation={"passed": True, "issues": [], "checked_at": "2026"},
    )
    db_session.add(gen)
    db_session.commit()

    provider = FourTaskScriptedProvider()
    monkeypatch.setattr(harness_service, "_provider_factory", lambda: provider)
    yield client, str(gen.id), provider, factory
    harness_service._session_factory = None
    harness_service._provider_factory = None
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


@pytest.mark.skipif(
    os.environ.get("PW_FULL_COURSE_E2E") != "1" or os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="Level B 全课程 E2E 需 PW_FULL_COURSE_E2E=1 + PW_SANDBOX_E2E=1",
)
def test_full_course_autonomous_to_student_journey(full_course_env):
    """Level B：t1→t4 从零开发（真 Docker 逐任务验证）→ 自动发布 →
    学生四任务完整学习旅程。"""
    client, gen_id, provider, factory = full_course_env

    created = client.post(f"/api/v1/course-dev-sessions?generationId={gen_id}")
    assert created.status_code == 201, created.text
    session_id = created.json()["sessionId"]

    # ---- 循环 run 至终态（每 slice 完成一个任务）
    started = time.monotonic()
    final = None
    for _ in range(16):
        out = client.post(f"/api/v1/course-dev-sessions/{session_id}/run").json()
        final = out
        if out.get("state") in ("completed", "failed", "cancelled"):
            break
    duration = int(time.monotonic() - started)

    status = client.get(f"/api/v1/course-dev-sessions/{session_id}").json()
    assert status["state"] == "completed", (
        status.get("error"), status.get("publishFailure"))
    assert status["completedTaskIds"] == ["t1", "t2", "t3", "t4"]
    release_id = status["publishedReleaseId"]
    assert release_id

    release = client.get(f"/api/v1/course-releases/{release_id}").json()
    assert release["status"] == "ready"
    assert release["passedTasks"] == release["totalTasks"] == 4
    assert "referenceFiles" not in json.dumps(release)
    # Effective Blueprint：Release 蓝图含全部四任务（学生实例化用）
    release_tasks = {t["taskId"] for t in release["artifacts"]}  # 有效任务以 artifact 为准
    assert release_tasks == {"t1", "t2", "t3", "t4"}

    # 检查点链（四任务累积）
    with factory() as db:
        from app.domains.course_generation.models import CourseCheckpoint
        from sqlalchemy import select

        cps = db.scalars(select(CourseCheckpoint).where(
            CourseCheckpoint.generation_id == _uuid.UUID(gen_id),
        ).order_by(CourseCheckpoint.task_seq)).all()
        assert [c.task_id for c in cps] == ["t1", "t2", "t3", "t4"]
        # 累积工程：t4 快照含全部模块
        t4_files = set(cps[3].snapshot_files)
        assert {"engine/src/World.cpp", "engine/src/Entity.cpp",
                "engine/src/Integration.cpp", "app/main.cpp"} <= t4_files
        # 回归注册表累积
        assert set(cps[3].test_registry) >= {"world_update", "entity_spawn",
                                            "integration_step"}

    # ---- 学生完整旅程
    inst = client.post(f"/api/v1/course-releases/{release_id}/instantiate",
                       json={"projectTitle": "四任务世界引擎课"})
    assert inst.status_code == 201, inst.text
    project_id = inst.json()["projectId"]

    plan = client.get(f"/api/v1/plans/{project_id}").json()
    assert {t["taskId"] for t in plan["tasks"]} == {"t1", "t2", "t3", "t4"}

    session_factory = factory

    def student_writes(path_to_content):
        with session_factory() as db:
            for f in db.query(ProjectFile).filter(
                    ProjectFile.project_id == _uuid.UUID(project_id)).all():
                if f.path in path_to_content:
                    f.content = path_to_content[f.path]
            db.commit()

    def evaluate(task_id, expect):
        resp = client.post(
            f"/api/v1/projects/{project_id}/tasks/{task_id}/evaluate",
            json={"files": [], "traceId": None, "source": "remote"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["passed"] is expect, (task_id, resp.json())

    cumulative = _cumulative(4)
    stubs_all = {1: _stubs(1), 2: _stubs(2), 3: _stubs(3), 4: _stubs(4)}

    for seq, task_id in enumerate(["t1", "t2", "t3", "t4"], start=1):
        if seq > 1:
            act = client.post(
                f"/api/v1/projects/{project_id}/tasks/{task_id}/activate", json={})
            assert act.status_code == 200, (task_id, act.text)
        evaluate(task_id, expect=False)  # starter 态真实失败
        impl_path = next(iter(stubs_all[seq]))
        student_writes({impl_path: cumulative[impl_path]})
        evaluate(task_id, expect=True)   # 实现后真实 CTest 通过（含回归）

    progress = client.get(
        f"/api/v1/projects/{project_id}/course-progress").json()
    assert progress["allCompleted"] is True
    report = client.get(f"/api/v1/projects/{project_id}/final-report")
    assert report.status_code == 200
    assert report.json()["completedTasks"] == 4
