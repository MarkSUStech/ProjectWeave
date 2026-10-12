"""CppRunner 纯单元测试：诊断解析、源集选择、CMake 契约校验、结果映射（无需 Docker）。"""

import io
import json
import tarfile

from app.domains.executions.languages.base import ExecutionSpecInput
from app.domains.executions.languages.cpp_driver import (
    FileApiError,
    find_entry_like_sources,
    is_test_file,
    parse_file_api_targets,
    select_run_sources,
    select_test_sources,
)
from app.domains.executions.languages.cpp_runner import (
    CppRunner,
    build_archive,
    parse_build_diagnostics,
    parse_cmake_configure_diagnostics,
)
from app.domains.executions.sandbox.base import SandboxResult

runner = CppRunner()


def spec(mode="run", entry="src/main.cpp", files=None, test_paths=None, stdin="",
         build_system="direct", cmake_action=None, target_name=None, selected_tests=None):
    return ExecutionSpecInput(
        exec_id="00000000-0000-0000-0000-000000000002",
        mode=mode,
        entry_point=entry,
        test_paths=test_paths or [],
        files=files if files is not None else {"src/main.cpp": "int main() { return 0; }"},
        stdin=stdin,
        timeout_s=20,
        build_system=build_system,
        cmake_action=cmake_action,
        target_name=target_name,
        selected_tests=selected_tests or [],
    )


# ---------------------------------------------------------------- 诊断解析


def test_parse_clang_error_with_location():
    stderr = (
        "src/main.cpp:5:12: error: use of undeclared identifier 'foo'\n"
        "    foo();\n"
    )
    diags = parse_build_diagnostics(stderr)
    assert diags[0]["file"] == "src/main.cpp"
    assert diags[0]["line"] == 5
    assert diags[0]["column"] == 12
    assert diags[0]["source"] == "build"
    assert "undeclared identifier" in diags[0]["message"]


def test_parse_missing_header_fatal():
    stderr = "src/main.cpp:1:10: fatal error: 'nope.hpp' file not found\n"
    diags = parse_build_diagnostics(stderr)
    assert diags[0]["severity"] == "error"
    assert diags[0]["file"] == "src/main.cpp"
    assert diags[0]["line"] == 1


def test_parse_gnu_ld_link_error_with_source_location():
    stderr = (
        "/usr/bin/ld: /sandbox/tmp/main-abc.o: in function `main':\n"
        "/sandbox/work/src/main.cpp:3: undefined reference to `add(int, int)'\n"
        "clang: error: linker command failed with exit code 1\n"
    )
    diags = parse_build_diagnostics(stderr)
    assert len(diags) == 1
    assert diags[0]["file"] == "src/main.cpp"  # /sandbox/work/ 前缀已归一化
    assert diags[0]["line"] == 3
    assert "add" in diags[0]["message"]


def test_parse_lld_link_error_without_location():
    stderr = "ld.lld: error: undefined symbol: add(int, int)\n>>> referenced by main.cpp\n"
    diags = parse_build_diagnostics(stderr)
    assert diags[0]["file"] is None
    assert diags[0]["line"] is None
    assert "add" in diags[0]["message"]


def test_parse_warning_and_note_severities():
    stderr = (
        "src/main.cpp:2:9: warning: unused variable 'x' [-Wunused-variable]\n"
        "src/main.cpp:3:5: note: in instantiation of function template specialization\n"
    )
    diags = parse_build_diagnostics(stderr)
    assert diags[0]["severity"] == "warning"
    assert diags[1]["severity"] == "info"


def test_parse_clean_output_is_empty():
    assert parse_build_diagnostics("") == []
    assert parse_build_diagnostics("compiling...\n") == []


# ---------------------------------------------------------------- 源集选择（driver 纯函数）


def test_select_run_sources_includes_lib_tus_excludes_other_programs():
    files = {
        "src/main.cpp": "int main(){}",
        "src/math.cpp": "int add(int a,int b){return a+b;}",
        "src/math.hpp": "#pragma once",
        "tests/test_math.cpp": "int main(){}",
        # 其他独立程序（课程任务/脚手架）：含 main，不混入入口的链接
        "src/tasks/task2.cpp": "int main(){ return 0; }",
        "src/tasks/task3.cpp": "int main(){ bump(&a); }",  # 含未完成 TODO 的独立任务
    }
    sources = select_run_sources(files, "src/main.cpp")
    assert sources[0] == "src/main.cpp"
    assert "src/math.cpp" in sources  # 无 main 的实现单元参与链接
    assert "tests/test_math.cpp" not in sources  # 测试文件不混入 run 构建
    assert "src/math.hpp" not in sources  # 头文件不参与命令行编译
    assert "src/tasks/task2.cpp" not in sources  # 其他独立程序排除
    assert "src/tasks/task3.cpp" not in sources

    # 入口是任务文件时：脚手架与其他任务（含 main）被排除；无 main 的实现单元仍参与
    sources2 = select_run_sources(files | {"src/tasks/task1.cpp": "#include <cstdio>" + chr(10) + "int main(){ return 0; }"}, "src/tasks/task1.cpp")
    assert sources2 == ["src/tasks/task1.cpp", "src/math.cpp"]


def test_select_test_sources_excludes_entry_like_files():
    files = {
        "src/main.cpp": "int main(){ return 0; }",          # 含 main → 排除
        "src/math.cpp": "int add(int a,int b){return a+b;}",
        "src/math.hpp": "#pragma once",
        "tests/test_math.cpp": "#include \"../src/math.hpp\"\nint main(){}",
    }
    entry_like = find_entry_like_sources(files)
    assert entry_like == {"src/main.cpp"}
    sources = select_test_sources(files, "tests/test_math.cpp", entry_like)
    assert sources[0] == "tests/test_math.cpp"
    assert "src/math.cpp" in sources
    assert "src/main.cpp" not in sources  # 避免多 main 链接冲突


def test_is_test_file_patterns():
    assert is_test_file("tests/test_math.cpp")
    assert is_test_file("src/math_test.cpp")
    assert is_test_file("tests/test_math.cxx")
    assert not is_test_file("src/math.cpp")
    assert not is_test_file("src/test_util.hpp")


# ---------------------------------------------------------------- P8.1 CMake 契约校验


def test_validate_cmake_requires_root_cmake_lists():
    errors = runner.validate_files(spec(
        build_system="cmake", cmake_action="discover", entry=None,
        files={"src/main.cpp": "int main(){}"}))
    assert any("CMakeLists.txt" in e for e in errors)


def test_validate_cmake_build_run_requires_target():
    files = {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)"}
    for action in ("build", "run"):
        errors = runner.validate_files(spec(
            build_system="cmake", cmake_action=action, entry=None, files=files))
        assert any("targetName" in e for e in errors), (action, errors)
    # discover 不需要 target
    assert runner.validate_files(spec(
        build_system="cmake", cmake_action="discover", entry=None, files=files)) == []


def test_validate_cmake_rejects_bad_test_names():
    files = {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)"}
    errors = runner.validate_files(spec(
        mode="test", build_system="cmake", entry=None, files=files,
        selected_tests=["ok_name", "../escape"]))
    assert any("非法测试名" in e for e in errors)


def test_manifest_carries_cmake_fields():
    data = build_archive(spec(
        build_system="cmake", cmake_action="run", target_name="game", entry=None,
        files={"CMakeLists.txt": ""}), 60)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        manifest = json.load(tar.extractfile("__pw/manifest.json"))
    assert manifest["buildSystem"] == "cmake"
    assert manifest["cmakeAction"] == "run"
    assert manifest["targetName"] == "game"
    # direct 模式不受影响
    direct = build_archive(spec(), 20)
    with tarfile.open(fileobj=io.BytesIO(direct), mode="r:gz") as tar:
        assert json.load(tar.extractfile("__pw/manifest.json"))["buildSystem"] == "direct"


def test_parse_cmake_configure_error_location():
    stderr = (
        "CMake Error at CMakeLists.txt:7 (add_executable):\n"
        "  Cannot find source file:\n"
        "    missing.cpp\n"
    )
    diags = parse_cmake_configure_diagnostics(stderr)
    assert diags and diags[0]["file"] == "CMakeLists.txt"
    assert diags[0]["line"] == 7
    assert diags[0]["stage"] == "configure"
    # 无结构化错误行时兜底给摘要
    fallback = parse_cmake_configure_diagnostics("Some fatal configuration problem\n")
    assert fallback and "CMake 配置失败" in fallback[0]["message"]


# ---------------------------------------------------------------- 规格与映射


def test_build_spec_declares_exec_workspace():
    sandbox_spec = runner.build_spec(spec(), 20)
    assert sandbox_spec.exec_workspace is True  # D34：编译产物需要执行
    assert sandbox_spec.tmpfs_size_mb >= 128
    assert sandbox_spec.image == "projectweave-sandbox-cpp:clang15-bookworm"
    # 白名单环境变量
    assert sandbox_spec.env["HOME"] == "/sandbox/home"


def test_build_archive_contains_manifest_driver_and_sources():
    data = build_archive(spec(files={"src/a.cpp": "int a(){}", "src/b.cpp": "int b(){}"}), 9.5)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
        manifest = json.load(tar.extractfile("__pw/manifest.json"))
    assert names[:2] == ["__pw/manifest.json", "__pw/driver.py"]
    assert names[2:] == ["src/a.cpp", "src/b.cpp"]
    assert manifest["entry"] == "src/main.cpp"
    assert manifest["timeoutSec"] == 9.5


def test_validate_rejects_wrong_entry_and_test_types():
    errors = runner.validate_files(spec(entry="src/main.hpp", files={"src/main.hpp": "x"}))
    assert any("入口" in e for e in errors)
    errors = runner.validate_files(spec(mode="test", entry=None, test_paths=["tests/test_math.py"]))
    assert any("C++ 源文件" in e for e in errors)


def _cpp_stdout(payload: dict) -> str:
    return "===PW_RESULT===" + json.dumps(payload, ensure_ascii=False) + "\n"


def test_parse_build_failed_maps_diagnostics_and_skips_run():
    stderr = "src/main.cpp:3:5: error: expected ';'\n"
    result = SandboxResult(
        exit_code=1, stdout=_cpp_stdout({"kind": "cpp", "phase": "build-failed", "buildExit": 1,
                                          "buildDiagnosticsRaw": stderr, "buildTool": "clang++", "buildMs": 40}),
        stderr=stderr, started=True,
    )
    outcome = runner.parse_result(result, spec())
    assert outcome.ok is False
    assert outcome.diagnostics[0]["file"] == "src/main.cpp"
    assert outcome.diagnostics[0]["line"] == 3
    assert outcome.diagnostics[0]["source"] == "build"
    # 编译失败 → run 阶段显式 skipped（不得报告为执行成功）
    assert outcome.phases[0] == {"name": "build", "status": "failed", "duration_ms": 40, "exit_code": 1}
    assert outcome.phases[1] == {"name": "run", "status": "skipped"}


def test_parse_run_success_and_crash():
    ok_result = SandboxResult(
        exit_code=0,
        stdout="hello\n" + _cpp_stdout({"kind": "cpp", "phase": "ran", "buildExit": 0, "runExit": 0,
                                         "timedOut": False, "runMs": 3, "signal": None}),
        stderr="", started=True,
    )
    outcome = runner.parse_result(ok_result, spec())
    assert outcome.ok is True
    assert outcome.phases[1]["status"] == "completed"

    crash = SandboxResult(
        exit_code=139,
        stdout=_cpp_stdout({"kind": "cpp", "phase": "ran", "buildExit": 0, "runExit": 139,
                            "timedOut": False, "runMs": 2, "signal": "SIGSEGV"}),
        stderr="", started=True,
    )
    outcome = runner.parse_result(crash, spec())
    assert outcome.ok is False
    assert any("SIGSEGV" in d["message"] for d in outcome.diagnostics)


def test_parse_tests_pass_fail_empty():
    payload = {
        "kind": "cpp", "phase": "tested",
        "tests": [
            {"name": "tests/test_ok.cpp", "file": "tests/test_ok.cpp", "passed": True, "status": "passed",
             "exitCode": 0, "durationMs": 5, "stdoutTail": "ok 2\n"},
            {"name": "tests/test_fail.cpp", "file": "tests/test_fail.cpp", "passed": False, "status": "failed",
             "exitCode": 1, "durationMs": 4, "stdoutTail": "not ok\n"},
            {"name": "tests/test_empty.cpp", "file": "tests/test_empty.cpp", "passed": False, "status": "error",
             "exitCode": 0, "durationMs": 1, "error": "空测试：无任何输出（测试可执行程序需产生输出以证明断言执行）"},
        ],
    }
    outcome = runner.parse_result(
        SandboxResult(exit_code=1, stdout=_cpp_stdout(payload), stderr="", started=True),
        spec(mode="test", entry=None, test_paths=["tests/test_ok.cpp", "tests/test_fail.cpp", "tests/test_empty.cpp"]),
    )
    assert outcome.ok is False
    by_path = {r["path"]: r for r in outcome.test_results}
    assert by_path["tests/test_ok.cpp"]["status"] == "passed"
    assert by_path["tests/test_fail.cpp"]["status"] == "failed"
    assert by_path["tests/test_empty.cpp"]["status"] == "error"
    assert "空测试" in by_path["tests/test_empty.cpp"]["error"]
    assert outcome.diagnostics[0]["source"] == "test"


def test_parse_test_build_failure_is_error_not_pass():
    payload = {
        "kind": "cpp", "phase": "tested",
        "tests": [
            {"name": "tests/broken.cpp", "file": "tests/broken.cpp", "passed": False, "status": "error",
             "exitCode": 1, "durationMs": 30, "error": "编译失败：tests/broken.cpp:2:1: error: expected }"},
        ],
    }
    outcome = runner.parse_result(
        SandboxResult(exit_code=1, stdout=_cpp_stdout(payload), stderr="", started=True),
        spec(mode="test", entry=None, test_paths=["tests/broken.cpp"]),
    )
    assert outcome.ok is False
    assert outcome.test_results[0]["status"] == "error"
    assert "编译失败" in outcome.test_results[0]["error"]
