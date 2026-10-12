"""P8.1 CMake Runtime 单元测试（无 Docker）。

覆盖：File API codemodel 解析（真实结构 fixture）、缺回复报错、
CppRunner 各 CMake 阶段 marker → 协议结果映射、失败不伪装通过。
"""

import json
import os

import pytest

from app.domains.executions.languages.base import ExecutionSpecInput
from app.domains.executions.languages.cpp_driver import FileApiError, parse_file_api_targets
from app.domains.executions.languages.cpp_runner import CppRunner
from app.domains.executions.sandbox.base import SandboxResult

runner = CppRunner()

REL_TO_WORK = None  # 真实语义：paths/sources 相对顶层源目录，artifacts 相对 build/


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh)


def _make_file_api_tree(work: str) -> None:
    """构造真实形状的 File API 回复（index → codemodel → target 文件，实物验证语义）。"""
    reply = os.path.join(work, "build", ".cmake", "api", "v1", "reply")

    def target_file(name: str, ttype: str, source_dir: str, artifacts: list[str],
                    sources: list[str], deps: list[str], artifact_exists: bool):
        filename = f"target-{name}.json"
        _write(os.path.join(reply, filename), {
            "name": name,
            "type": ttype,
            "paths": {"source": source_dir, "build": source_dir},
            "sources": [{"path": s} for s in sources],
            "artifacts": [{"path": a} for a in artifacts],
            "dependencies": [{"id": f"^dep-{d}"} for d in deps],
        })
        if artifact_exists:
            for artifact in artifacts:
                _write(os.path.join(work, "build", artifact), "binary")
        return filename

    targets = [
        ("engine", "STATIC_LIBRARY", "engine", ["engine/libengine.a"],
         ["engine/src/World.cpp"], [], True),
        ("game", "EXECUTABLE", "game", ["game"], ["game/main.cpp"], ["engine"], True),
        ("inspect", "EXECUTABLE", "tools", ["inspect"], ["tools/inspect.cpp"], ["engine"], True),
        ("weave_world", "UTILITY", "", [], [], [], False),
    ]
    _write(os.path.join(reply, "index-abc123.json"), {
        "generated": {"version": "1.1"},
        "reply": {  # 真实格式：以 query 名为键的字典
            "cmakeFiles-v1-x": {"kind": "cmakeFiles", "jsonFile": "cmakeFiles-v1-x.json"},
            "codemodel-v2-x": {"kind": "codemodel", "jsonFile": "codemodel-v2-x.json"},
        },
    })
    _write(os.path.join(reply, "codemodel-v2-x.json"), {
        "configurations": [{
            "name": "Debug",
            "targets": [
                {"id": f"^dep-{name}", "name": name, "jsonFile": target_file(
                    name, ttype, sdir, arts, srcs, deps, exists)}
                for name, ttype, sdir, arts, srcs, deps, exists in targets
            ],
        }],
    })


def test_parse_file_api_targets_types_and_runnable(tmp_path):
    _make_file_api_tree(str(tmp_path))
    targets = parse_file_api_targets(str(tmp_path), str(tmp_path / "build"))
    by_name = {t["name"]: t for t in targets}
    assert set(by_name) == {"engine", "game", "inspect", "weave_world"}

    engine = by_name["engine"]
    assert engine["type"] == "STATIC_LIBRARY"
    assert engine["runnable"] is False  # 库目标不可运行
    assert engine["artifacts"] == ["build/engine/libengine.a"]
    assert engine["sources"] == ["engine/src/World.cpp"]
    assert engine["sourceDirectory"] == "engine"
    assert engine["buildDirectory"] == "build/engine"
    assert engine["configuration"] == "Debug"

    game = by_name["game"]
    assert game["type"] == "EXECUTABLE"
    assert game["runnable"] is True
    assert game["artifacts"] == ["build/game"]
    assert game["dependencies"] == ["engine"]

    assert by_name["weave_world"]["type"] == "UTILITY"
    assert by_name["weave_world"]["runnable"] is False


def test_parse_file_api_missing_reply(tmp_path):
    with pytest.raises(FileApiError):
        parse_file_api_targets(str(tmp_path), str(tmp_path / "build"))


def test_parse_file_api_no_codemodel(tmp_path):
    reply = tmp_path / "build" / ".cmake" / "api" / "v1" / "reply"
    reply.mkdir(parents=True)
    _write(str(reply / "index-x.json"), {"reply": [{"kind": "cmakeFiles"}]})
    with pytest.raises(FileApiError, match="codemodel"):
        parse_file_api_targets(str(tmp_path), str(tmp_path / "build"))


# ---------------------------------------------------------------- marker → 协议结果


def cmake_spec(mode="run", action="run", target="game"):
    return ExecutionSpecInput(
        exec_id="00000000-0000-0000-0000-000000000003", mode=mode,
        entry_point=None, test_paths=[], files={"CMakeLists.txt": ""},
        stdin="", timeout_s=60,
        build_system="cmake", cmake_action=action, target_name=target,
    )


def _sandbox_with_marker(marker: dict) -> SandboxResult:
    return SandboxResult(
        exit_code=0,
        stdout="===PW_RESULT===" + json.dumps(marker, ensure_ascii=False) + "\n",
        stderr="", started=True, engine="docker", image="cpp",
    )


def test_parse_discover_surfaces_targets():
    targets = [{"name": "game", "type": "EXECUTABLE", "runnable": True,
                "sourceDirectory": "game", "buildDirectory": "build",
                "sources": ["game/main.cpp"], "artifacts": ["build/game"],
                "dependencies": ["engine"], "configuration": "Debug"}]
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-discovered", "configureExit": 0,
        "configureMs": 900, "generator": "Ninja", "cmakeVersion": "cmake version 3.25.1",
        "targets": targets,
    }), cmake_spec(action="discover"))
    assert outcome.ok and outcome.cmake["operation"] == "discover"
    assert outcome.cmake["targets"][0]["name"] == "game"
    assert outcome.cmake["targets"][0]["dependencies"] == ["engine"]
    assert outcome.cmake["cmakeVersion"].startswith("cmake version")
    assert outcome.phases == [{"name": "configure", "status": "completed",
                               "exit_code": 0, "duration_ms": 900}]


def test_parse_configure_failure_stage_and_diagnostics():
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-failed", "stage": "configure", "exitCode": 1,
        "rawStderr": "CMake Error at CMakeLists.txt:3 (project):\n  syntax error",
    }), cmake_spec())
    assert not outcome.ok
    assert outcome.cmake["operation"] == "run"
    assert outcome.diagnostics[0]["stage"] == "configure"
    assert outcome.diagnostics[0]["file"] == "CMakeLists.txt"
    assert outcome.diagnostics[0]["line"] == 3
    assert [p["name"] for p in outcome.phases] == ["configure", "build", "run"]
    assert outcome.phases[1]["status"] == "skipped"  # 构建未发生，不伪装


def test_parse_target_not_found_and_not_runnable():
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-failed", "stage": "target-not-found",
        "exitCode": 2, "target": "nope", "rawStderr": "目标不存在：nope（已发现：game）",
    }), cmake_spec(target="nope"))
    assert outcome.diagnostics[0]["stage"] == "target-not-found"
    assert "已发现" in outcome.diagnostics[0]["message"]

    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-failed", "stage": "target-not-runnable",
        "exitCode": 2, "target": "engine",
        "rawStderr": "目标 engine 类型为 STATIC_LIBRARY，不可运行",
    }), cmake_spec(target="engine"))
    assert "STATIC_LIBRARY" in outcome.diagnostics[0]["message"]


def test_parse_run_result_phases_and_exit():
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-ran", "target": "game", "artifact": "build/game",
        "runExit": 0, "timedOut": False, "runMs": 33, "signal": None, "buildMs": 1200,
    }), cmake_spec())
    assert outcome.ok and outcome.cmake["artifact"] == "build/game"
    assert [p["name"] for p in outcome.phases] == ["configure", "build", "run"]
    assert outcome.phases[-1]["exit_code"] == 0


def test_parse_ctest_results_and_zero_executed_never_passes():
    marker = {
        "kind": "cpp", "phase": "cmake-tested", "ctestExit": 1,
        "tests": [
            {"name": "test_world", "status": "passed", "durationMs": 12, "error": None},
            {"name": "test_terrain", "status": "failed", "durationMs": 9,
             "error": "Assertion failed: terrain_elevation(-1.0) == 99.0"},
        ],
        "discovered": ["test_world", "test_terrain"], "ctestMs": 60, "buildMs": 900,
    }
    outcome = runner.parse_result(_sandbox_with_marker(marker), cmake_spec(mode="test"))
    assert not outcome.ok
    assert outcome.test_results[1]["cases"][0]["status"] == "failed"
    assert any("test_terrain" in d["message"] for d in outcome.diagnostics)
    assert outcome.cmake["discovered_tests"] == ["test_world", "test_terrain"]

    # JUnit 缺失 → 0 个执行 → 永不判通过
    broken = dict(marker, ctestExit=0, tests=[], junitError="CTest 结果报告缺失或无效（未判定为通过）")
    outcome = runner.parse_result(_sandbox_with_marker(broken), cmake_spec(mode="test"))
    assert not outcome.ok
    assert any(d["message"].startswith("CTest 结果报告") for d in outcome.diagnostics)


def test_parse_ctest_selection_mode_unselected_do_not_fail():
    """P8.1.1：选择模式下未选择的 skipped 不影响通过。"""
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-tested", "ctestExit": 0,
        "tests": [
            {"name": "test_world", "status": "passed", "durationMs": 5, "error": None},
            {"name": "test_terrain", "status": "skipped", "durationMs": 0,
             "error": "未在本次选择范围（-R 过滤）"},
        ],
        "discovered": ["test_world", "test_terrain"],
        "requiredMissing": [], "notSelected": ["test_terrain"],
    }), cmake_spec(mode="test"))
    assert outcome.ok  # 只有 test_world 被要求执行且通过
    assert not any(d for d in outcome.diagnostics if "test_terrain" in d["message"])


def test_parse_ctest_required_missing_fails_even_if_others_pass():
    """要求执行的测试未运行（Not Run/DISABLED）→ 不得判通过。"""
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-tested", "ctestExit": 0,
        "tests": [
            {"name": "test_world", "status": "passed", "durationMs": 5, "error": None},
            {"name": "test_terrain", "status": "skipped", "durationMs": 0,
             "error": "要求执行但未运行（Not Run：可能被禁用或被过滤）"},
        ],
        "discovered": ["test_world", "test_terrain"],
        "requiredMissing": ["test_terrain"], "notSelected": [],
    }), cmake_spec(mode="test"))
    assert not outcome.ok
    assert any("test_terrain" in d["message"] for d in outcome.diagnostics)


def test_parse_ctest_not_run_marked_skipped():
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-tested", "ctestExit": 0,
        "tests": [{"name": "test_world", "status": "passed", "durationMs": 5, "error": None},
                  {"name": "test_terrain", "status": "skipped", "durationMs": 0,
                   "error": "未执行（Not Run：可能被过滤或禁用）"}],
        "discovered": ["test_world", "test_terrain"],
    }), cmake_spec(mode="test"))
    assert not outcome.ok  # 有测试未执行 → 整体不通过
    assert outcome.test_results[1]["cases"][0]["status"] == "skipped"


def test_build_only_does_not_report_run_phase():
    outcome = runner.parse_result(_sandbox_with_marker({
        "kind": "cpp", "phase": "cmake-built", "target": "game", "buildMs": 800,
        "artifacts": ["build/game"],
    }), cmake_spec(action="build"))
    assert outcome.ok
    assert [p["name"] for p in outcome.phases] == ["configure", "build"]
