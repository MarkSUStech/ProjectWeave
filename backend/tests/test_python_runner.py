"""PythonRunner 纯单元测试：文件包构造、结果解析、语言校验（无需 Docker）。"""

import io
import json
import tarfile

from app.domains.executions.languages.base import ExecutionSpecInput
from app.domains.executions.languages.python_runner import PythonRunner
from app.domains.executions.sandbox.base import SandboxResult

runner = PythonRunner()


def spec(mode="run", entry="src/main.py", files=None, test_paths=None, stdin=""):
    return ExecutionSpecInput(
        exec_id="00000000-0000-0000-0000-000000000001",
        mode=mode,
        entry_point=entry,
        test_paths=test_paths or [],
        files=files if files is not None else {"src/main.py": "print('hi')"},
        stdin=stdin,
        timeout_s=10,
    )


# ---------------------------------------------------------------- validate


def test_validate_rejects_non_py_entry_and_missing_entry():
    # 入口非 .py 被拒；项目数据文件（如 README.md）放行
    errors = runner.validate_files(spec(files={"README.md": "x"}, entry="src/main.py", test_paths=[]))
    assert errors == [] or all("README" not in e for e in errors)

    errors = runner.validate_files(spec(files={"src/main.js": "x"}, entry="src/main.js"))
    assert any("入口" in e for e in errors)

    errors = runner.validate_files(spec(mode="test", entry=None, test_paths=[]))
    assert any("测试文件" in e for e in errors)


# ---------------------------------------------------------------- archive


def test_build_archive_contains_manifest_driver_and_sorted_files():
    files = {"b.py": "print(2)", "a.py": "print(1)"}
    data = runner.build_spec(spec(files=files), 7.5).stdin_archive
    assert data is not None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
        manifest = json.load(tar.extractfile("__pw/manifest.json"))
    assert names[0] == "__pw/manifest.json"
    assert names[1] == "__pw/driver.py"
    assert names[2:] == ["a.py", "b.py"]  # 确定性排序
    assert manifest["entry"] == "src/main.py"
    assert manifest["timeoutSec"] == 7.5
    assert manifest["mode"] == "run"


def test_build_spec_command_and_env_whitelist():
    sandbox_spec = runner.build_spec(spec(), 10)
    assert sandbox_spec.command[0:2] == ["sh", "-c"]
    assert "tar -xzf - -C /sandbox/work" in sandbox_spec.command[2]
    assert sandbox_spec.env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert sandbox_spec.container_name.startswith("pw-exec-")
    # 关键隔离参数由沙箱管理器施加，Runner 不负责（这里只确认规格可构造）。
    assert sandbox_spec.image == "projectweave-sandbox-python:3.12"


# ---------------------------------------------------------------- run 模式解析


def test_parse_run_success():
    result = SandboxResult(
        exit_code=0, stdout="hello\n===PW_RESULT==={\"kind\": \"run\", \"exitCode\": 0, \"timedOut\": false}\n",
        stderr="", started=True, duration_ms=120,
    )
    outcome = runner.parse_result(result, spec())
    assert outcome.ok is True
    assert outcome.exit_code == 0
    assert outcome.diagnostics == []
    assert outcome.phases[0]["name"] == "run"
    assert outcome.phases[0]["status"] == "completed"


def test_parse_run_traceback_maps_file_and_line():
    stderr = (
        "Traceback (most recent call last):\n"
        "  File \"src/main.py\", line 4, in <module>\n"
        "    1 / 0\n"
        "ZeroDivisionError: division by zero\n"
    )
    result = SandboxResult(
        exit_code=1,
        stdout="===PW_RESULT==={\"kind\": \"run\", \"exitCode\": 1, \"timedOut\": false}\n",
        stderr=stderr, started=True,
    )
    outcome = runner.parse_result(result, spec())
    assert outcome.ok is False
    assert outcome.exit_code == 1
    assert outcome.diagnostics[0]["file"] == "src/main.py"
    assert outcome.diagnostics[0]["line"] == 4
    assert outcome.diagnostics[0]["message"].startswith("ZeroDivisionError")
    assert outcome.diagnostics[0]["source"] == "runtime"


def test_parse_run_driver_timeout():
    result = SandboxResult(
        exit_code=124, stdout="===PW_RESULT==={\"kind\": \"run\", \"exitCode\": null, \"timedOut\": true}\n",
        stderr="", started=True,
    )
    outcome = runner.parse_result(result, spec())
    assert outcome.timed_out is True
    assert outcome.ok is False


def test_parse_run_no_marker_is_protocol_error():
    result = SandboxResult(exit_code=1, stdout="some output", stderr="boom", started=True)
    outcome = runner.parse_result(result, spec())
    assert outcome.protocol_error is not None
    assert outcome.ok is False


# ---------------------------------------------------------------- test 模式解析


def _pytest_stdout(payload: dict) -> str:
    return "===PW_RESULT===" + json.dumps(payload, ensure_ascii=False) + "\n"


def test_parse_pytest_grouping_and_diagnostics():
    payload = {
        "kind": "pytest",
        "exitCode": 1,
        "timedOut": False,
        "tests": [
            {
                "name": "tests/test_math.py::test_add",
                "status": "passed", "error": None,
                "file": "tests/test_math.py", "line": 2, "duration_ms": 3,
            },
            {
                "name": "tests/test_math.py::test_sub",
                "status": "failed", "error": "assert 3 == 2",
                "file": "tests/test_math.py", "line": 6, "duration_ms": 2,
            },
            {
                "name": "tests/test_str.py::test_len",
                "status": "passed", "error": None,
                "file": "tests/test_str.py", "line": 1, "duration_ms": 1,
            },
        ],
        "fileErrors": [],
    }
    result = SandboxResult(exit_code=1, stdout=_pytest_stdout(payload), stderr="", started=True)
    outcome = runner.parse_result(
        result, spec(mode="test", entry=None, test_paths=["tests/test_math.py", "tests/test_str.py"])
    )
    assert outcome.test_results is not None
    by_path = {r["path"]: r for r in outcome.test_results}
    assert by_path["tests/test_math.py"]["status"] == "failed"
    assert by_path["tests/test_str.py"]["status"] == "passed"
    assert len(by_path["tests/test_math.py"]["cases"]) == 2
    assert outcome.ok is False
    diag = outcome.diagnostics[0]
    assert diag["file"] == "tests/test_math.py"
    assert diag["line"] == 6
    assert diag["source"] == "test"
    assert diag["message"] == "assert 3 == 2"


def test_parse_pytest_all_passed():
    payload = {
        "kind": "pytest", "exitCode": 0, "timedOut": False,
        "tests": [
            {"name": "t1", "status": "passed", "error": None, "file": "tests/a.py", "line": 1, "duration_ms": 1},
        ],
        "fileErrors": [],
    }
    outcome = runner.parse_result(
        SandboxResult(exit_code=0, stdout=_pytest_stdout(payload), stderr="", started=True),
        spec(mode="test", entry=None, test_paths=["tests/a.py"]),
    )
    assert outcome.ok is True
    assert outcome.diagnostics == []


def test_parse_pytest_collection_error_maps_file_error():
    payload = {
        "kind": "pytest", "exitCode": 2, "timedOut": False, "tests": [],
        "fileErrors": [{"file": "tests/broken.py", "error": "ModuleNotFoundError: No module named 'nope'"}],
    }
    outcome = runner.parse_result(
        SandboxResult(exit_code=2, stdout=_pytest_stdout(payload), stderr="", started=True),
        spec(mode="test", entry=None, test_paths=["tests/broken.py"]),
    )
    assert outcome.ok is False
    assert outcome.test_results[0]["status"] == "error"
    assert "ModuleNotFoundError" in outcome.test_results[0]["error"]


def test_parse_pytest_timeout_marker():
    payload = {"kind": "pytest", "exitCode": None, "timedOut": True, "tests": [], "fileErrors": [], "partial": True}
    outcome = runner.parse_result(
        SandboxResult(exit_code=124, stdout=_pytest_stdout(payload), stderr="", started=True),
        spec(mode="test", entry=None, test_paths=["tests/a.py"]),
    )
    assert outcome.timed_out is True
    assert outcome.ok is False
