"""P8.2 C++ 课程单元测试（无 Docker）：验证器失败路径、泄露精确判定、验收契约。"""

from unittest import mock

import pytest

from app.domains.course_generation.lessons import lesson_builder
from app.domains.course_generation.verification import course_verifier
from app.domains.course_generation.verification.course_verifier import (
    guard_starter,
    verify_cpp_cmake_task,
)


def _material(expected_files=None, starter_overrides=None, manifest=None):
    return {
        "instructions": {"title": "t", "expectedFiles": expected_files or ["engine/src/World.cpp"]},
        "starterFiles": [
            {"path": "CMakeLists.txt", "content": "# root cmake\n" * 30},
            {"path": "engine/CMakeLists.txt", "content": "add_library(engine STATIC src/World.cpp)\n" * 5},
            {"path": "engine/include/engine/World.hpp", "content": "#pragma once\nclass World{};\n"},
            {"path": "engine/src/World.cpp", "content": '#include "engine/World.hpp"\n// TODO: 实现更新\n'},
        ],
        "testFiles": [
            {"path": "tests/CMakeLists.txt", "content": "add_test(NAME world_update COMMAND w)\n"},
            {"path": "tests/test_world.cpp", "content": "#include <cassert>\nint main(){assert(1==1);}\n"},
        ],
        "referenceFiles": [
            {"path": "CMakeLists.txt", "content": "# root cmake\n" * 30},
            {"path": "engine/CMakeLists.txt", "content": "add_library(engine STATIC src/World.cpp)\n" * 5},
            {"path": "engine/include/engine/World.hpp", "content": "#pragma once\nclass World{};\n"},
            {"path": "engine/src/World.cpp", "content": '#include "engine/World.hpp"\nvoid World::update(){}\n' * 5},
        ],
        "buildManifest": manifest or {"buildTargets": ["engine"],
                                      "testNames": ["world_update"]},
    }


# ---------------------------------------------------------------- 泄露精确判定


def test_guard_leak_only_for_expected_files():
    """头文件与前序文件 starter=reference 属正常；仅本任务实现文件一致算泄露。"""
    m = _material()
    problems = guard_starter(m["starterFiles"], m["referenceFiles"], m["testFiles"],
                             "cpp", expected_files=["engine/src/World.cpp"])
    assert not any("泄露" in p for p in problems)  # 实现文件已挖空；hpp 一致不判

    leaked = _material()
    leaked["starterFiles"][3]["content"] = leaked["referenceFiles"][3]["content"]
    problems = guard_starter(leaked["starterFiles"], leaked["referenceFiles"],
                             leaked["testFiles"], "cpp",
                             expected_files=["engine/src/World.cpp"])
    assert any("World.cpp" in p and "泄露" in p for p in problems)


def test_guard_cmake_test_registration_is_not_test_body():
    """tests/CMakeLists.txt 是注册脚本：合法；但缺少 .cpp 测试源文件要报错。"""
    m = _material()
    assert not any("CMakeLists" in p for p in guard_starter(
        m["starterFiles"], m["referenceFiles"], m["testFiles"], "cpp",
        expected_files=["engine/src/World.cpp"]))

    no_cpp = _material()
    no_cpp["testFiles"] = [no_cpp["testFiles"][0]]  # 只剩注册脚本
    problems = guard_starter(no_cpp["starterFiles"], no_cpp["referenceFiles"],
                             no_cpp["testFiles"], "cpp")
    assert any("测试源文件" in p for p in problems)


# ---------------------------------------------------------------- 验证器失败路径（mock 沙箱）


def _outcome(ok=False, tests=None, targets=None, phases=None, diagnostics=None):
    return mock.Mock(
        ok=ok,
        test_results=tests or [],
        cmake={"targets": targets or []},
        phases=phases or [{"name": "build", "status": "completed"}],
        diagnostics=diagnostics or [],
    )


def test_verify_fails_when_manifest_target_not_discovered():
    material = _material(manifest={"buildTargets": ["ghost"], "testNames": ["world_update"]})
    with mock.patch.object(course_verifier, "run_cmake_operation",
                           return_value=_outcome(ok=True, targets=[{"name": "engine"}])):
        result = verify_cpp_cmake_task(material, {}, [])
    assert not result.passed
    assert any("ghost" in p and "未被发现" in p for p in result.problems)


def test_verify_fails_when_reference_tests_fail():
    material = _material()
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}]),  # discover
        _outcome(ok=False, tests=[{"path": "world_update", "status": "failed"}]),  # reference
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes):
        result = verify_cpp_cmake_task(material, {}, [])
    assert not result.passed
    assert any("参考实现测试未通过" in p for p in result.problems)


def test_verify_fails_when_starter_build_broken():
    material = _material()
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}]),               # discover
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),  # reference
        _outcome(ok=False, tests=[], phases=[{"name": "build", "status": "failed"}]),  # starter
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes):
        result = verify_cpp_cmake_task(material, {}, [])
    assert not result.passed
    assert any("坏工程" in p for p in result.problems)


def test_verify_fails_when_starter_passes_all_tests():
    material = _material()
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes):
        result = verify_cpp_cmake_task(material, {}, [])
    assert not result.passed
    assert any("泄露" in p or "空转" in p for p in result.problems)


def test_verify_happy_path_with_expected_starter_failure():
    material = _material()
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),
        _outcome(ok=False, tests=[{"path": "world_update", "status": "failed"}]),
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes):
        result = verify_cpp_cmake_task(material, {}, [], is_final=False)
    assert result.passed
    kinds = [v["kind"] for v in result.verifications]
    assert kinds == ["cmake-discovery", "reference-tests", "starter-expected-fail"]


def test_verify_final_task_runs_integration_and_demo():
    material = _material(manifest={"buildTargets": ["engine"], "runTargets": ["worldsim"],
                                   "testNames": ["world_update"]})
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}, {"name": "worldsim"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),
        _outcome(ok=False, tests=[{"path": "world_update", "status": "failed"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),  # 全量
        _outcome(ok=True),  # demo
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes) as run:
        result = verify_cpp_cmake_task(material, {}, [], is_final=True)
    assert result.passed
    kinds = [v["kind"] for v in result.verifications]
    assert kinds[-2:] == ["final-integration", "demo-run"]
    # demo 调用带目标名与 run action
    assert run.call_args_list[-1].kwargs.get("cmake_action") == "run"
    assert run.call_args_list[-1].kwargs.get("target_name") == "worldsim"


def test_verify_regression_names_join_reference_run():
    material = _material()
    outcomes = [
        _outcome(ok=True, targets=[{"name": "engine"}]),
        _outcome(ok=True, tests=[{"path": "world_update", "status": "passed"}]),
        _outcome(ok=False, tests=[{"path": "world_update", "status": "failed"}]),
    ]
    with mock.patch.object(course_verifier, "run_cmake_operation", side_effect=outcomes) as run:
        result = verify_cpp_cmake_task(material, {}, ["entity_spawn"])
    assert result.passed
    selected = run.call_args_list[1].kwargs.get("selected_tests")
    assert set(selected) == {"world_update", "entity_spawn"}  # 回归并入参考测试


# ---------------------------------------------------------------- 生成器契约


def test_cpp_builder_prompt_has_no_pytest_and_requires_manifest():
    calls = {}

    class P:
        def chat(self, system, user):
            calls["system"] = system
            calls["user"] = user
            return type("R", (), {"content": '{"starterFiles":[]}'})()

    lesson_builder.build_cpp_cmake_task_lesson(
        P(), {"taskId": "t1", "title": "x"}, "m1", {}, {})
    assert "CMake" in calls["system"] and "CTest" in calls["system"]
    assert "pytest" not in calls["system"]
    assert "buildManifest" in calls["system"]
    assert "PREV_REFERENCE" in calls["user"] and "t1" in calls["user"]


def test_material_without_tests_rejected():
    material = _material(manifest={"buildTargets": ["engine"], "testNames": []})
    result = verify_cpp_cmake_task(material, {}, [])
    assert not result.passed
    assert any("testNames" in p for p in result.problems)
