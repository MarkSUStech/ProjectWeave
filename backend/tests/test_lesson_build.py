"""P7.2 课程内容测试：Mock LLM + 真实 Docker Python 沙箱（验证参考实现真跑）。"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import SessionLocal
from app.domains.course_generation import service as gen_service
from app.domains.course_generation.lessons import lesson_builder, lesson_publisher
from app.domains.course_generation.verification.course_verifier import (
    guard_starter,
    merge_files,
    run_in_sandbox,
)
from app.ai.provider import MockProvider

NL = chr(10)


def _material(violation: str = "") -> dict:
    """合法材料：Value 类（reference 完整 / starter 挖空 / 测试断言核心行为）。"""
    ref = (
        "class Value:" + NL
        + "    def __init__(self, data, _children=()):" + NL
        + "        self.data = data" + NL
        + "        self.grad = 0.0" + NL
        + "        self._backward = lambda: None" + NL
        + "        self._prev = set(_children)" + NL
        + NL
        + "    def __add__(self, other):" + NL
        + "        other = other if isinstance(other, Value) else Value(other)" + NL
        + "        out = Value(self.data + other.data, (self, other))" + NL
        + "        return out" + NL
        + NL
        + "    def __mul__(self, other):" + NL
        + "        other = other if isinstance(other, Value) else Value(other)" + NL
        + "        out = Value(self.data * other.data, (self, other))" + NL
        + "        return out" + NL
        + NL
        + "    def backward(self):" + NL
        + "        self.grad = 1.0" + NL
        + "        # 简化拓扑遍历教学版" + NL
        + "        nodes = [self]" + NL
        + "        while nodes:" + NL
        + "            node = nodes.pop()" + NL
        + "            node._backward()" + NL
        + "        return self.grad" + NL
    )
    starter = (
        "class Value:" + NL
        + "    def __init__(self, data, _children=()):" + NL
        + "        self.data = data" + NL
        + "        self.grad = 0.0" + NL
        + "        self._prev = set(_children)" + NL
        + NL
        + "    # TODO: 实现 __add__（返回新 Value，记录 _children）" + NL
        + NL
        + "    # TODO: 实现 __mul__" + NL
    )
    test = (
        "from micrograd.value import Value" + NL
        + NL
        + "def test_add():" + NL
        + "    a = Value(2.0)" + NL
        + "    b = Value(3.0)" + NL
        + "    assert (a + b).data == 5.0" + NL
        + NL
        + "def test_mul():" + NL
        + "    assert (Value(2.0) * Value(4.0)).data == 8.0" + NL
    )
    material = {
        "instructions": {
            "title": "Value 与运算", "context": "自动微分引擎基础", "goal": "实现 Value 四则运算",
            "requiredConcepts": [], "features": ["加法", "乘法"],
            "expectedFiles": ["micrograd/value.py"], "ioBehavior": "Value(2)+Value(3).data==5",
            "constraints": ["只用标准库"], "acceptance": ["测试全过"],
            "relationToPrev": "从零开始", "relationToNext": "为计算图提供节点",
        },
        "starterFiles": [{"path": "micrograd/value.py", "content": starter}],
        "testFiles": [{"path": "tests/test_value.py", "content": test}],
        "referenceFiles": [{"path": "micrograd/value.py", "content": ref}],
        "hints": [
            {"level": 1, "text": "想想 __add__ 要返回什么"},
            {"level": 2, "text": "返回新的 Value，data 相加，_children 记录两个操作数"},
            {"level": 3, "text": "out = Value(self.data + other.data, (self, other))"},
            {"level": 4, "text": "参考 __add__ 实现"},
        ],
    }
    if violation == "leak":
        material["starterFiles"][0]["content"] = ref  # starter = 参考实现 → 泄露
    if violation == "no-todo":
        material["starterFiles"][0]["content"] = starter.replace("# TODO", "# 实现")
    if violation == "assert-true":
        material["testFiles"][0]["content"] = (
            "from micrograd.value import Value" + NL + NL + "def test_x():" + NL + "    assert True" + NL
        )
    if violation == "ref-broken":
        material["referenceFiles"][0]["content"] = ref.replace(
            "self.data + other.data", "self.data - other.data")  # 参考实现错误 → 测试失败
    return material


# ---------------------------------------------------------------- 防伪守卫（纯单测）


def test_guard_passes_valid():
    assert guard_starter(
        _material()["starterFiles"], _material()["referenceFiles"], _material()["testFiles"]
    ) == []


@pytest.mark.parametrize("violation, fragment", [
    ("leak", "泄露"),
    ("no-todo", "TODO"),
    ("assert-true", "assert True"),
])
def test_guard_catches_violations(violation, fragment):
    m = _material(violation)
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"])
    assert any(fragment in p for p in problems), problems


# ---------------------------------------------------------------- 语言化守卫（Python 结构化 / C++ / TS）


def test_guard_python_structured():
    """AST 结构化：语法错误/空转测试带文件与函数名；空壳函数也算有效待实现。"""
    m = _material()
    bad = {"path": "tests/test_bad.py", "content": "def test_x(:" + NL + "    pass" + NL}
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], [bad])
    assert any("语法错误" in p and "tests/test_bad.py" in p for p in problems), problems

    vacuous = {"path": "tests/test_v.py", "content": "def test_nothing():" + NL + "    x = 1" + NL}
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], [vacuous])
    assert any("test_nothing" in p and "空转" in p for p in problems), problems

    # 无 TODO 标记但有空壳函数（raise NotImplementedError）→ 有效待实现区域
    stub = {"path": "micrograd/value.py",
            "content": "class Value:" + NL + "    def __init__(self, d):" + NL
                       + "        self.data = d" + NL + "    def backward(self):" + NL
                       + "        raise NotImplementedError" + NL}
    problems = guard_starter([stub], m["referenceFiles"], m["testFiles"])
    assert not any("TODO" in p for p in problems), problems

    # 裸 TODO（无描述）不算有效标记
    bare = {"path": "micrograd/value.py",
            "content": "class Value:" + NL + "    # TODO" + NL + "    pass" + NL}
    problems = guard_starter([bare], m["referenceFiles"], m["testFiles"])
    assert any("TODO" in p for p in problems), problems


def _cpp_material() -> dict:
    """C++ 课程材料（与线上失败样本同构）：TODO 在 CMakeLists/源码，测试为可执行程序。"""
    return {
        "starterFiles": [
            {"path": "CMakeLists.txt",
             "content": ("cmake_minimum_required(VERSION 3.16)" + NL
                         + "project(weave LANGUAGES CXX)" + NL + NL
                         + "# TODO: 设置 C++17 标准（CMAKE_CXX_STANDARD）" + NL
                         + "# TODO: 声明 weave_core 静态库目标" + NL)},
            {"path": "include/weave/version.h",
             "content": "#pragma once" + NL + "#include <string>" + NL
                        + "namespace weave {" + NL + "std::string version();" + NL + "}" + NL},
            {"path": "src/core/version.cpp",
             "content": ("#include \"weave/version.h\"" + NL + "namespace weave {" + NL
                         + "// TODO: 返回 \"0.1.0\"" + NL
                         + "std::string version() { return \"\"; }" + NL + "}" + NL)},
        ],
        "referenceFiles": [
            {"path": "src/core/version.cpp",
             "content": ("#include \"weave/version.h\"" + NL + "namespace weave {" + NL
                         + "std::string version() { return \"0.1.0\"; }" + NL + "}" + NL)},
            {"path": "include/weave/version.h",
             "content": "#pragma once" + NL + "#include <string>" + NL
                        + "namespace weave {" + NL + "std::string version();" + NL + "}" + NL},
            {"path": "CMakeLists.txt",
             "content": "cmake_minimum_required(VERSION 3.16)" + NL + ("# pad" + NL) * 40},
        ],
        "testFiles": [
            {"path": "tests/test_engine.cpp",
             "content": ("#include <cassert>" + NL + "#include <string>" + NL
                         + "#include \"weave/version.h\"" + NL + "int main() {" + NL
                         + "  const std::string v = weave::version();" + NL
                         + "  assert(!v.empty());" + NL + "  return 0;" + NL + "}" + NL)},
        ],
    }


def test_guard_cpp_material_from_real_failure():
    """回归（线上 v3/v4 失败样本）：C++ 材料不得再被 Python-only 规则误拒。"""
    m = _cpp_material()
    assert guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"], "cpp") == []


def test_guard_cpp_violations():
    m = _cpp_material()
    # 全部 TODO 变裸标记（无描述）→ 拒绝
    import re as _re

    for f in m["starterFiles"]:
        f["content"] = _re.sub(r"TODO[:：][^\n]*", "TODO", f["content"])
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"], "cpp")
    assert any("TODO" in p for p in problems), problems

    m2 = _cpp_material()
    m2["testFiles"][0]["content"] = m2["testFiles"][0]["content"].replace(
        "assert(!v.empty());", "")
    problems = guard_starter(m2["starterFiles"], m2["referenceFiles"], m2["testFiles"], "cpp")
    assert any("断言" in p for p in problems), problems

    m3 = _cpp_material()
    m3["testFiles"][0]["content"] = m3["testFiles"][0]["content"].replace("int main() {", "int run() {")
    problems = guard_starter(m3["starterFiles"], m3["referenceFiles"], m3["testFiles"], "cpp")
    assert any("main" in p for p in problems), problems


def test_guard_typescript_rules():
    m = {
        "starterFiles": [{"path": "src/stack.ts",
                          "content": "export class Stack {" + NL + "  // TODO: push 压栈" + NL + "}" + NL}],
        "referenceFiles": [{"path": "src/stack.ts",
                            "content": ("export class Stack {" + NL
                                        + "  private items: number[] = [];" + NL
                                        + "  push(x: number) { this.items.push(x); }" + NL
                                        + "}" + NL) * 3}],
        "testFiles": [{"path": "tests/stack.test.ts",
                       "content": ("import { describe, it, expect } from 'vitest'" + NL
                                   + "describe('Stack', () => {" + NL
                                   + "  it('pushes', () => { expect(new Stack()).toBeTruthy() })" + NL
                                   + "})" + NL)}],
    }
    assert guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"], "typescript") == []

    m["testFiles"][0]["content"] = "import { describe } from 'vitest'" + NL + "describe('x', () => {})" + NL
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"], "typescript")
    assert any("it/test" in p for p in problems), problems
    assert any("expect" in p for p in problems), problems


def test_guard_unknown_language():
    problems = guard_starter([{"path": "a.py", "content": "# TODO: x"}],
                             [{"path": "a.py", "content": "x = 1"}],
                             [{"path": "t.py", "content": "def test_a():\n    assert True\n"}],
                             "rust")
    assert any("未知课程语言" in p for p in problems), problems


def test_merge_files_cumulative():
    merged = merge_files({"a.py": "1", "b.py": "2"}, {"b.py": "3", "c.py": "4"})
    assert merged == {"a.py": "1", "b.py": "3", "c.py": "4"}


# ---------------------------------------------------------------- 真实沙箱（Docker，选入本地常跑——镜像常在）


@pytest.mark.skipif(
    __import__("os").environ.get("PW_SANDBOX_E2E") != "1",
    reason="真实沙箱验证需 PW_SANDBOX_E2E=1（Python 镜像）",
)
class TestSandboxVerify:
    def test_reference_passes(self):
        m = _material()
        files = {f["path"]: f["content"] for f in m["referenceFiles"] + m["testFiles"]}
        out = run_in_sandbox("python", files, "test", None, ["tests/test_value.py"])
        assert out.status == "passed", out.to_dict()
        assert out.total == 2 and out.passed == 2

    def test_broken_reference_fails_with_diagnostics(self):
        m = _material("ref-broken")
        files = {f["path"]: f["content"] for f in m["referenceFiles"] + m["testFiles"]}
        out = run_in_sandbox("python", files, "test", None, ["tests/test_value.py"])
        assert out.status == "failed" and out.failed >= 1

    def test_starter_expected_fail(self):
        m = _material()
        starter_files = {f["path"]: f["content"] for f in m["starterFiles"] + m["testFiles"]}
        out = run_in_sandbox("python", starter_files, "test", None, ["tests/test_value.py"])
        assert out.failed > 0  # TODO 区域 → 测试失败（证据：测试有效不泄露）


# ---------------------------------------------------------------- 流水线（Mock LLM + 假沙箱注入）


class FakeSandbox:
    """可控沙箱：reference→passed；starter→failed（期望失败）。"""

    def run(self, spec, cancel_event, on_output=None):
        from app.domains.executions.sandbox.base import SandboxResult
        import tarfile
        import io as _io

        with tarfile.open(fileobj=_io.BytesIO(spec.stdin_archive), mode="r:gz") as tar:
            files = {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers()}
        all_code = NL.join(files.values())
        has_todo = "TODO" in all_code
        status = "failed" if has_todo else "passed"
        exit_code = 1 if has_todo else 0
        marker = {
            "kind": "pytest", "exitCode": exit_code, "timedOut": False,
            "tests": [{"name": "t1", "file": "tests/test_value.py", "line": 1,
                       "status": status, "durationMs": 5}],
            "fileErrors": [],
        }
        stdout = "===PW_RESULT===" + json.dumps(marker, ensure_ascii=False) + NL
        return SandboxResult(
            exit_code=1 if has_todo else 0, stdout=stdout, stderr="",
            output_events=[("stdout", stdout)], started=True,
            duration_ms=42, engine="fake", image=spec.image,
        )


def _blueprint() -> dict:
    tasks = [
        {"taskId": "t1", "milestoneId": "ms-1", "title": "Value 与运算",
         "description": "d", "dependsOn": [], "requiredConcepts": [],
         "deliverables": ["value.py"], "acceptanceCriteria": ["测试全过"],
         "sourceEvidence": []},
        {"taskId": "t2", "milestoneId": "ms-2", "title": "计算图",
         "description": "d", "dependsOn": ["t1"], "requiredConcepts": [],
         "deliverables": ["graph"], "acceptanceCriteria": ["回归通过"],
         "sourceEvidence": []},
        *[{"taskId": f"t{i}", "milestoneId": "ms-2", "title": f"任务{i}",
           "description": "d", "dependsOn": ["t2"], "requiredConcepts": [],
           "deliverables": [f"d{i}"], "acceptanceCriteria": ["通过"],
           "sourceEvidence": []} for i in range(3, 9)],
    ]
    return {
        "project": {"title": "从零实现自动微分引擎", "description": "d",
                    "sourceUrl": "u", "commitSha": "a" * 40, "license": {},
                    "techStack": ["Python"], "finalArtifact": "引擎", "goals": [], "nonGoals": []},
        "milestones": [
            {"milestoneId": "ms-1", "title": "数值基础", "deliverables": ["Value"],
             "acceptanceCriteria": ["加法"], "dependsOn": []},
            {"milestoneId": "ms-2", "title": "图与训练", "deliverables": ["MLP"],
             "acceptanceCriteria": ["训练"], "dependsOn": ["ms-1"]},
        ],
        "tasks": tasks,
        "knowledgeRequirements": [],
    }


@pytest.fixture()
def build_env(client: TestClient, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(lesson_publisher, "_session_factory", factory)
    monkeypatch.setattr(
        "app.domains.course_generation.verification.course_verifier._sandbox", FakeSandbox()
    )
    provider = MockProvider()
    material = _material()
    # 每任务一次 chat（生成）；无修复（假沙箱全过）
    provider.chat = lambda system, user: type("R", (), {"content": json.dumps(material, ensure_ascii=False), "prompt_tokens": 100, "completion_tokens": 200, "model": "mock"})()
    monkeypatch.setattr(lesson_publisher, "_provider_factory", lambda: provider)
    yield client, provider, material
    lesson_publisher._session_factory = None
    lesson_publisher._provider_factory = None


def _seed_published_generation(client: TestClient, db_session) -> str:
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    """直接造一个已发布蓝图的 generation（确定性，无后台线程竞态）。"""
    import uuid as _uuid

    from tests.test_course_generation import _valid_blueprint

    from app.domains.course_generation.models import CourseGeneration

    blueprint = _valid_blueprint()
    blueprint["project"]["techStack"] = ["Python"]
    for t in blueprint["tasks"]:
        t["requiredConcepts"] = []
    row = CourseGeneration(
        id=_uuid.uuid4(),
        source_url="https://github.com/karpathy/micrograd",
        status="published",
        stage=None, progress=100,
        repo_owner="karpathy", repo_name="micrograd",
        commit_sha="a" * 40, default_branch="master",
        license_info={"spdx": "MIT"},
        snapshot={"files": {"README.md": "# m", "micrograd/engine.py": "class Value: pass"},
                  "tree": [], "stats": {}, "license": {}, "meta": {},
                  "owner": "karpathy", "repo": "micrograd",
                  "defaultBranch": "master", "commitSha": "a" * 40},
        analysis={"summary": "s", "tech_stack": ["Python"]},
        blueprint=blueprint,
        validation={"passed": True, "issues": [], "checked_at": "2026-10-11T00:00:00Z"},
    )
    db_session.add(row)
    db_session.commit()
    return str(row.id)


def test_build_lessons_to_ready_and_instantiate(client: TestClient, build_env, db_session):
    provider = build_env[1]
    monkey_material = _material()

    # 1) 建生成任务并同步驱动到 published
    gen_id = _seed_published_generation(client, db_session)

    # 2) build-lessons（同步假沙箱全过）
    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    release = resp.json()
    assert release["status"] in ("generating", "verifying")

    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/course-releases/{release['id']}").json()
        if detail["status"] in ("ready", "failed"):
            break
        time.sleep(0.2)
    assert detail["status"] == "ready", detail["error"]
    assert detail["totalTasks"] == detail["passedTasks"] == 9

    # 参考实现隔离：API 响应绝不含 referenceFiles
    body = json.dumps(detail)
    assert "referenceFiles" not in body and "reference_store" not in body

    # lessons 材料含 starter/tests/hints 且无 reference
    artifact = detail["artifacts"][0]
    assert artifact["starterFiles"] and artifact["testFiles"]
    assert {h["level"] for h in artifact["hints"]} == {1, 2, 3}  # H4 由服务端剥离（Tutor Gate 控制）

    # 3) 实例化学习项目
    inst = client.post(f"/api/v1/course-releases/{release['id']}/instantiate",
                       json={"projectTitle": "我的 micrograd 课"})
    assert inst.status_code == 201, inst.text
    project_id = inst.json()["projectId"]
    assert inst.json()["firstTaskId"] == "t1"

    # 项目有首任务 starter 文件与测试；任务图完整
    files = {f["path"] for f in client.get(f"/api/v1/projects/{project_id}/files").json()["items"]}
    assert "micrograd/value.py" in files and "tests/test_value.py" in files
    plan = client.get(f"/api/v1/plans/{project_id}").json()
    plan_tasks = plan.get("tasks") or []
    assert len(plan_tasks) == 9
    assert plan_tasks[0]["testFiles"] == ["tests/test_value.py"]

    # 4) 非 ready 禁止实例化（重复调用已实例化的 release 仍 ready → 幂等成功第二项目）
    inst2 = client.post(f"/api/v1/course-releases/{release['id']}/instantiate")
    assert inst2.status_code == 201


def test_release_recover_stale(client: TestClient, build_env, db_session):
    """重启恢复：卡在 generating 的 release 被标 failed（可重试）。"""
    from app.domains.course_generation.models import CourseRelease

    gen_id = _seed_published_generation(client, db_session)
    # 手动插入一个卡住的 release
    db = db_session
    db.add(CourseRelease(generation_id=__import__("uuid").UUID(gen_id), status="generating"))
    db.commit()
    recovered = lesson_publisher.recover_stale_releases(db)
    assert recovered >= 1


def test_build_lessons_retry_feeds_prior_failures(client: TestClient, build_env, db_session):
    """重试生成（v2）：上一次失败 release 的守卫问题进入新一轮 LLM 提示。"""
    import time
    import uuid as _uuid

    from app.domains.course_generation.models import CourseRelease

    provider = build_env[1]
    prompts: list[str] = []
    original_chat = provider.chat

    def capture_chat(system, user):
        prompts.append(user)
        return original_chat(system, user)

    provider.chat = capture_chat

    gen_id = _seed_published_generation(client, db_session)
    # 造一个失败的 v1：t1 被防伪守卫拒绝且修复轮未解决
    db_session.add(CourseRelease(
        generation_id=_uuid.UUID(gen_id), release_version=1, status="failed",
        language="python", error="任务 t1 验证失败：防伪守卫：starter 缺少 TODO 标记",
        artifacts=[{"task_id": "t1", "status": "failed",
                    "error": "防伪守卫：starter 缺少 TODO 标记（学生无从知道待实现区域）",
                    "repairs": [{"round": 1, "problem": "防伪守卫：starter 缺少 TODO 标记",
                                 "outcome": "still-failing"}]}],
        verification_report={"passed": 0, "total": 9, "failed_task": "t1"},
    ))
    db_session.commit()

    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 202, resp.text
    release = resp.json()
    assert release["releaseVersion"] == 2

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/course-releases/{release['id']}").json()
        if detail["status"] in ("ready", "failed"):
            break
        time.sleep(0.2)
    assert detail["status"] == "ready", detail["error"]

    # t1 的生成提示包含上次的守卫问题；后续任务不携带
    assert "PRIOR_FAILURES" in prompts[0]
    assert "starter 缺少 TODO 标记" in prompts[0]
    assert "PRIOR_FAILURES" not in prompts[1]


def test_prior_failures_unit(db_session):
    """_prior_failures 单元：camelCase/snake_case 条目与 release 级兜底都收集。"""
    import uuid as _uuid

    from app.domains.course_generation.models import CourseRelease

    gen_id = _uuid.uuid4()
    db_session.add_all([
        CourseRelease(
            generation_id=gen_id, release_version=1, status="ready",
        ),
        CourseRelease(
            generation_id=gen_id, release_version=2, status="failed",
            error="任务 t2 验证失败：参考实现测试未通过",
            artifacts=[{"taskId": "t1", "status": "tests-passed"},
                       {"task_id": "t2", "status": "failed",
                        "error": "防伪守卫：测试文件没有任何断言",
                        "repairs": [{"round": 1, "problem": "防伪守卫：测试文件没有任何断言",
                                     "outcome": "still-failing"}]}],
            verification_report={"passed": 1, "total": 9, "failed_task": "t2"},
        ),
        CourseRelease(
            generation_id=gen_id, release_version=3, status="failed",
            error="任务 t3 验证失败：服务重启中断",
            verification_report={"failed_task": "t3"},  # 无 artifacts → release 级兜底
        ),
    ])
    db_session.commit()

    result = lesson_publisher._prior_failures(db_session, gen_id, before_version=4)
    assert set(result) == {"t2", "t3"}
    assert any("断言" in p for p in result["t2"])
    assert result["t3"] == ["任务 t3 验证失败：服务重启中断"]


def test_build_lessons_rejects_unsupported_language(client: TestClient, build_env, db_session):
    """未验证语言组合（P8.2 起 C++/CMake 已支持 → 用 TypeScript 验证拒绝路径）：
    提前 422——不创建 release、不消耗 LLM 调用、明确报告限制。"""
    import uuid as _uuid

    from app.domains.course_generation.models import CourseGeneration, CourseRelease

    gen_id = _seed_published_generation(client, db_session)
    row = db_session.get(CourseGeneration, _uuid.UUID(gen_id))
    bp = dict(row.blueprint or {})
    project = dict(bp.get("project") or {})
    project["tech_stack"] = ["TypeScript", "React"]
    project["techStack"] = ["TypeScript", "React"]
    bp["project"] = project
    row.blueprint = bp
    db_session.commit()

    calls: list[str] = []
    provider = build_env[1]
    original_chat = provider.chat

    def counting_chat(system, user):
        calls.append(user)
        return original_chat(system, user)

    provider.chat = counting_chat

    resp = client.post(f"/api/v1/course-generations/{gen_id}/build-lessons")
    assert resp.status_code == 422, resp.text
    assert "暂不支持 typescript" in resp.json()["detail"]
    assert db_session.query(CourseRelease).count() == 0   # 无 release 行
    assert calls == []                                     # 零 LLM 调用
