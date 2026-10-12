"""C++ 语言运行器（P4.2c 第一版：Clang 15 + C++20 + 可选 CMake/Ninja）。

- run：入口 + 非测试翻译单元 → clang++ 链接为真实可执行程序后运行；
  存在 CMakeLists.txt 时走 cmake -G Ninja（目标 = 入口文件名去扩展名）；
- test：逐测试文件编译为独立可执行程序运行（exit 0 且有输出 = 通过；
  空测试不判通过——练习信任级下也不当证据）；
- 编译参数由服务端固定（-std=c++20 -O0 -g -Wall -Wextra），不拼接用户命令；
- 需要 exec 工作区（D34）：编译产物在一次性容器 tmpfs 内执行。
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path

from app.domains.executions.languages.base import (
    ExecutionSpecInput,
    LanguageRunner,
    ParsedOutcome,
)
from app.domains.executions.sandbox.base import SandboxResult, SandboxSpec

DRIVER_PATH = Path(__file__).with_name("cpp_driver.py")
RESERVED_PREFIX = "__pw"

BOOTSTRAP_COMMAND = [
    "sh", "-c",
    "mkdir -p /sandbox/work /sandbox/tmp /sandbox/home"
    " && tar -xzf - -C /sandbox/work"
    " && cd /sandbox/work"
    " && exec python3 -u __pw/driver.py",
]

CONTAINER_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "HOME": "/sandbox/home",
    "TMPDIR": "/sandbox/tmp",
}

# clang/gcc 诊断行：file:line:col: error|warning|note: message
_DIAG_RE = re.compile(r"^(?:\./)?([^:\n][^:\n]*):(\d+):(\d+):\s*(fatal error|error|warning|note):\s*(.+)$")
# 链接器符号缺失：GNU ld（undefined reference to `x'）与 lld（undefined symbol: x）
_LINK_UNDEF_RE = re.compile(r"undefined (?:reference(?: to)?|symbol)\s*[:`]?\s*[\"']?([^\s'\"()]+)", re.IGNORECASE)
# 链接错误行中定位源文件（GNU ld 会给出 src.cpp:NN）
_SRC_LOC_RE = re.compile(r"([^\s:]+\.(?:cpp|cc|cxx)):(\d+)")
_MARKER_RE = re.compile(r"^===PW_RESULT===(\{.*\})\s*$", re.MULTILINE)

SOURCE_EXTENSIONS = {".cpp", ".cc", ".cxx"}
WORKDIR_PREFIX = "/sandbox/work/"
MAX_DIAGNOSTICS = 50
# 目标/测试名白名单（与驱动端同规则；防路径穿越与命令注入）
TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")


def build_archive(spec: ExecutionSpecInput, timeout_s: float) -> bytes:
    manifest = {
        "mode": spec.mode,
        "entry": spec.entry_point,
        "testPaths": spec.test_paths,
        "stdin": spec.stdin,
        "timeoutSec": timeout_s,
        # P8.1 CMake 项目 profile（direct 模式忽略这些字段）
        "buildSystem": spec.build_system,
        "cmakeAction": spec.cmake_action,
        "targetName": spec.target_name,
        "selectedTests": spec.selected_tests,
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        def _add(name: str, data: str) -> None:
            payload = data.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))

        _add("__pw/manifest.json", json.dumps(manifest, ensure_ascii=False))
        _add("__pw/driver.py", DRIVER_PATH.read_text(encoding="utf-8"))
        for path in sorted(spec.files):
            _add(path, spec.files[path])
    return buffer.getvalue()


# CMake Configure 错误：CMake Error at CMakeLists.txt:5 (add_executable):
_CMAKE_ERROR_RE = re.compile(r"CMake Error(?: at|\s+in)?\s+([^\s:]+\.(?:txt|cmake)):(\d+)")


def parse_cmake_configure_diagnostics(stderr: str) -> list[dict]:
    """CMake Configure 错误输出 → 结构化诊断（configure 阶段专用）。"""
    diagnostics: list[dict] = []
    for match in _CMAKE_ERROR_RE.finditer(stderr):
        file_name, line_no = match.group(1), int(match.group(2))
        # 错误正文：从匹配行取（含消息的下一行）
        line_start = stderr.find("\n", match.end())
        message = stderr[line_start + 1:stderr.find("\n", line_start + 1)].strip() \
            if line_start != -1 else ""
        diagnostics.append({
            "severity": "error",
            "message": f"CMake 配置错误：{message[:300]}" if message else "CMake 配置错误",
            "file": file_name.removeprefix(WORKDIR_PREFIX),
            "line": line_no,
            "source": "build",
            "stage": "configure",
        })
        if len(diagnostics) >= MAX_DIAGNOSTICS:
            break
    if not diagnostics and stderr.strip():
        diagnostics.append({
            "severity": "error",
            "message": "CMake 配置失败：" + stderr.strip().splitlines()[-1][:300],
            "source": "build", "stage": "configure",
        })
    return diagnostics


def parse_build_diagnostics(stderr: str) -> list[dict]:
    """clang/gcc 诊断输出 → 结构化诊断（文件/行/列/级别，确定性解析）。"""
    diagnostics: list[dict] = []
    for line in stderr.splitlines():
        stripped = line.strip()
        match = _DIAG_RE.match(stripped)
        if match:
            file_name, line_no, column, severity, message = match.groups()
            diagnostics.append({
                "severity": "error" if "error" in severity else ("warning" if severity == "warning" else "info"),
                "message": message.strip(),
                "file": file_name.removeprefix(WORKDIR_PREFIX),
                "line": int(line_no),
                "column": int(column),
                "source": "build",
            })
            continue
        link_match = _LINK_UNDEF_RE.search(stripped)
        if link_match:
            symbol = link_match.group(1)
            # GNU ld 在同一行给出源位置（src.cpp:NN）；lld 只给符号 → file=None
            locations = _SRC_LOC_RE.findall(stripped)
            file_name = locations[-1][0].removeprefix(WORKDIR_PREFIX) if locations else None
            line_no = int(locations[-1][1]) if locations else None
            diagnostics.append({
                "severity": "error",
                "message": f"链接错误：未定义的符号 {symbol}（声明了但未提供实现或未参与链接）",
                "file": file_name,
                "line": line_no,
                "source": "build",
            })
        if len(diagnostics) >= MAX_DIAGNOSTICS:
            break
    return diagnostics


def _map_tests(raw_tests: list[dict]) -> list[dict]:
    """driver 测试记录 → 协议 TestFileOutcome（每个测试文件一组）。"""
    results = []
    for test in raw_tests:
        status = test.get("status", "error")
        error = test.get("error")
        if error is None and status == "failed":
            error = f"测试失败（退出码 {test.get('exitCode')}）"
        cases = [{
            "name": test.get("name", ""),
            "status": "passed" if status == "passed" else ("failed" if status == "failed" else "error"),
            "error": error,
            "file": test.get("file"),
            "line": None,
            "duration_ms": test.get("durationMs", 0),
        }]
        results.append({
            "path": test.get("file") or test.get("name") or "",
            "status": "passed" if status == "passed" else ("failed" if status == "failed" else "error"),
            "cases": cases,
            "error": error,
        })
    return results


class CppRunner(LanguageRunner):
    """Clang 15 / C++20 运行器（exec 工作区，D34）。"""

    language = "cpp"
    image = "projectweave-sandbox-cpp:clang15-bookworm"

    def validate_files(self, spec: ExecutionSpecInput) -> list[str]:
        """direct：入口/测试必须是 C++ 源文件；cmake：CMake 工程规则（P8.1）。"""
        errors: list[str] = []
        if spec.build_system == "cmake":
            if "CMakeLists.txt" not in spec.files:
                errors.append("cmake 构建需要根目录 CMakeLists.txt（在 files 中）")
            if spec.mode == "run":
                action = spec.cmake_action or "run"
                if action in ("build", "run") and not spec.target_name:
                    errors.append(f"cmake {action} 操作必须提供 targetName（来自 discover 结果）")
            else:
                for name in spec.selected_tests:
                    if not TARGET_NAME_RE.match(name):
                        errors.append(f"非法测试名：{name!r}")
            return errors

        if spec.mode == "run":
            if not spec.entry_point:
                errors.append("run 模式必须提供 entryPoint")
            elif Path(spec.entry_point).suffix not in SOURCE_EXTENSIONS:
                errors.append("入口文件必须是 C++ 源文件（.cpp/.cc/.cxx）")
        else:
            if not spec.test_paths:
                errors.append("test 模式必须提供至少一个测试文件")
            for path in spec.test_paths:
                if Path(path).suffix not in SOURCE_EXTENSIONS:
                    errors.append(f"测试文件必须是 C++ 源文件：{path}")
        return errors

    def build_spec(self, spec: ExecutionSpecInput, timeout_s: float) -> SandboxSpec:
        is_cmake = spec.build_system == "cmake"
        return SandboxSpec(
            image=self.image,
            command=BOOTSTRAP_COMMAND,
            stdin_archive=build_archive(spec, timeout_s),
            timeout_s=timeout_s,
            container_name=f"pw-exec-{spec.exec_id[:12]}",
            exec_id=spec.exec_id,
            # D34：编译型语言需要执行编译产物 → exec tmpfs（服务端规格，客户端不可控）
            # P8.1：CMake 构建需要更大工作区（源码 + 构建目录 + 工具链临时文件）
            exec_workspace=True,
            tmpfs_size_mb=512 if is_cmake else 256,
            env=dict(CONTAINER_ENV),
        )

    def parse_result(self, result: SandboxResult, spec: ExecutionSpecInput) -> ParsedOutcome:
        outcome = ParsedOutcome(exit_code=result.exit_code, timed_out=result.timed_out)

        marker_payload = None
        match = _MARKER_RE.search(result.stdout)
        if match:
            try:
                marker_payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                outcome.protocol_error = "结果标记解析失败"

        if marker_payload is None and result.started and not result.timed_out and not result.killed:
            outcome.protocol_error = outcome.protocol_error or "沙箱未返回执行结果标记"
            outcome.diagnostics = [
                {"severity": "error", "message": (result.stderr.strip()[-600:] or "沙箱执行异常退出"), "source": "runtime"}
            ]
            outcome.phases = [{"name": "build", "status": "failed", "duration_ms": result.duration_ms}]
            return outcome

        if result.timed_out:
            phase_name = "run" if spec.mode == "run" else "test"
            if spec.build_system == "cmake":
                outcome.cmake = {"operation": spec.cmake_action or ("test" if spec.mode == "test" else "run")}
                phase_name = {"discover": "configure", "build": "build", "run": "run"}.get(
                    spec.cmake_action, "test" if spec.mode == "test" else "run")
            outcome.phases = [{"name": phase_name, "status": "failed", "duration_ms": result.duration_ms}]
            return outcome

        phase = (marker_payload or {}).get("phase")

        # ---- P8.1 CMake profile ----
        if phase and phase.startswith("cmake-") and spec.build_system == "cmake":
            return self._parse_cmake_result(marker_payload, spec, result)

        if phase == "build-failed":
            build_exit = (marker_payload or {}).get("buildExit")
            raw = (marker_payload or {}).get("buildDiagnosticsRaw", "") or result.stderr
            outcome.exit_code = build_exit
            outcome.ok = False
            outcome.diagnostics = parse_build_diagnostics(raw) or [
                {"severity": "error", "message": "构建失败（无结构化诊断）", "file": spec.entry_point, "source": "build"}
            ]
            outcome.phases = [
                {"name": "build", "status": "failed", "duration_ms": (marker_payload or {}).get("buildMs", 0), "exit_code": build_exit},
                {"name": "run", "status": "skipped"},
            ]
            return outcome

        if spec.mode == "run":
            run_exit = (marker_payload or {}).get("runExit")
            timed_out_flag = bool((marker_payload or {}).get("timedOut"))
            signal = (marker_payload or {}).get("signal")
            outcome.exit_code = run_exit
            outcome.timed_out = timed_out_flag
            outcome.ok = run_exit == 0 and not timed_out_flag
            diagnostics: list[dict] = []
            if timed_out_flag:
                diagnostics.append({"severity": "error", "message": "运行超时，已终止", "file": spec.entry_point, "source": "runtime"})
            elif signal:
                diagnostics.append({"severity": "error", "message": f"运行时崩溃（{signal}，退出码 {run_exit}）", "file": spec.entry_point, "source": "runtime"})
            elif run_exit not in (0, None):
                diagnostics.append({"severity": "error", "message": f"程序以退出码 {run_exit} 结束", "file": spec.entry_point, "source": "runtime"})
            outcome.diagnostics = diagnostics
            outcome.phases = [
                {"name": "build", "status": "completed", "exit_code": 0},
                {"name": "run", "status": "completed" if outcome.ok else "failed",
                 "duration_ms": (marker_payload or {}).get("runMs", 0), "exit_code": run_exit},
            ]
            return outcome

        # test 模式
        raw_tests = (marker_payload or {}).get("tests", [])
        test_results = _map_tests(raw_tests)
        outcome.test_results = test_results
        outcome.ok = bool(test_results) and all(r["status"] == "passed" for r in test_results)
        outcome.diagnostics = [
            {
                "severity": "error",
                "message": case.get("error") or "测试失败",
                "file": case.get("file"),
                "source": "test",
            }
            for r in test_results
            for case in r["cases"]
            if case["status"] in ("failed", "error")
        ]
        outcome.phases = [
            {"name": "build", "status": "completed", "exit_code": 0},
            {"name": "test", "status": "completed" if outcome.ok else "failed",
             "duration_ms": sum(r["cases"][0]["duration_ms"] for r in test_results if r["cases"]),
             "exit_code": result.exit_code},
        ]
        return outcome

    # ---------------------------------------------------------------- P8.1 CMake 解析

    def _parse_cmake_result(self, payload: dict, spec: ExecutionSpecInput,
                            result: SandboxResult) -> ParsedOutcome:
        phase = payload.get("phase")
        stage = payload.get("stage", "")
        timed_out = bool(payload.get("timedOut"))

        # ---- 失败：按 stage 区分 configure / build / 目标 / 产物 ----
        if phase == "cmake-failed":
            raw = payload.get("rawStderr", "") or result.stderr
            outcome = ParsedOutcome(exit_code=payload.get("exitCode"), timed_out=timed_out)
            outcome.cmake = {
                "operation": spec.cmake_action or ("test" if spec.mode == "test" else "run"),
                "target": payload.get("target"),
            }
            if stage in ("validate", "target-not-found", "target-not-runnable",
                         "artifact-missing", "file-api", "ctest-discovery"):
                outcome.diagnostics = [{
                    "severity": "error", "message": raw.strip()[:400] or f"阶段失败：{stage}",
                    "source": "build", "stage": stage,
                }]
            elif stage == "configure":
                outcome.diagnostics = parse_cmake_configure_diagnostics(raw)
            else:  # build：编译/链接错误走 clang 诊断解析，链接解析兜底
                outcome.diagnostics = parse_build_diagnostics(raw) or [{
                    "severity": "error", "message": "构建失败：" + raw.strip().splitlines()[-1][:300]
                    if raw.strip() else "构建失败（无输出）",
                    "source": "build", "stage": "build",
                }]
                for diag in outcome.diagnostics:
                    diag.setdefault("stage", "build")
                    diag.setdefault("source", "build")
            failed_phase = {"configure": "configure", "build": "build"}.get(stage, "build")
            # 阶段序列如实反映进度：configure 已跑（除 validate 在最前拒绝）
            phases = []
            if stage != "validate" and failed_phase != "configure":
                phases.append({"name": "configure", "status": "completed"})
            phases.append({"name": failed_phase, "status": "failed",
                           "exit_code": payload.get("exitCode"),
                           "duration_ms": payload.get("buildMs", 0)})
            if failed_phase == "configure":
                phases.append({"name": "build", "status": "skipped"})
            if spec.mode == "test" or spec.cmake_action == "run":
                phases.append({"name": "test" if spec.mode == "test" else "run",
                               "status": "skipped"})
            outcome.phases = phases
            return outcome

        # ---- discover：目标列表 ----
        if phase == "cmake-discovered":
            outcome = ParsedOutcome(ok=True, exit_code=0)
            targets = [self._public_target(t) for t in payload.get("targets", [])]
            outcome.cmake = {
                "operation": "discover", "targets": targets,
                "generator": payload.get("generator"),
                "cmakeVersion": payload.get("cmakeVersion"),
            }
            outcome.phases = [{"name": "configure", "status": "completed",
                               "exit_code": payload.get("configureExit", 0),
                               "duration_ms": payload.get("configureMs", 0)}]
            return outcome

        # ---- build（只构建不运行）----
        if phase == "cmake-built":
            outcome = ParsedOutcome(ok=True, exit_code=0)
            outcome.cmake = {
                "operation": "build", "target": payload.get("target"),
                "generator": payload.get("generator"),
                "cmakeVersion": payload.get("cmakeVersion"),
            }
            outcome.phases = [
                {"name": "configure", "status": "completed"},
                {"name": "build", "status": "completed",
                 "duration_ms": payload.get("buildMs", 0), "exit_code": 0},
            ]
            return outcome

        # ---- run：构建 + 执行产物 ----
        if phase == "cmake-ran":
            run_exit = payload.get("runExit")
            timed_out = bool(payload.get("timedOut"))
            signal = payload.get("signal")
            outcome = ParsedOutcome(exit_code=run_exit, timed_out=timed_out,
                                    ok=run_exit == 0 and not timed_out)
            outcome.cmake = {
                "operation": "run", "target": payload.get("target"),
                "artifact": payload.get("artifact"),
                "generator": payload.get("generator"),
                "cmakeVersion": payload.get("cmakeVersion"),
            }
            diagnostics: list[dict] = []
            if timed_out:
                diagnostics.append({"severity": "error", "message": "运行超时，已终止",
                                    "source": "runtime", "stage": "run"})
            elif signal:
                diagnostics.append({"severity": "error",
                                    "message": f"运行时崩溃（{signal}，退出码 {run_exit}）",
                                    "source": "runtime", "stage": "run"})
            elif run_exit not in (0, None):
                diagnostics.append({"severity": "error",
                                    "message": f"程序以退出码 {run_exit} 结束",
                                    "source": "runtime", "stage": "run"})
            outcome.diagnostics = diagnostics
            outcome.phases = [
                {"name": "configure", "status": "completed"},
                {"name": "build", "status": "completed", "duration_ms": payload.get("buildMs", 0)},
                {"name": "run", "status": "completed" if outcome.ok else "failed",
                 "duration_ms": payload.get("runMs", 0), "exit_code": run_exit},
            ]
            return outcome

        # ---- test：CTest 结构化结果 ----
        if phase == "cmake-tested":
            tests = payload.get("tests") or []
            ctest_exit = payload.get("ctestExit")
            junit_error = payload.get("junitError")
            required_missing = payload.get("requiredMissing") or []
            not_selected = set(payload.get("notSelected") or [])
            outcome = ParsedOutcome(exit_code=ctest_exit, timed_out=timed_out)
            outcome.cmake = {
                "operation": "test",
                "discovered_tests": payload.get("discovered", []),
                "required_missing": required_missing,
                "not_selected": sorted(not_selected),
                "generator": payload.get("generator"),
                "cmakeVersion": payload.get("cmakeVersion"),
            }
            # ctest 测试 → 协议 TestFileOutcome（每测试一组；未选择项透传 skipped）
            outcome.test_results = [{
                "path": t.get("name", ""),
                "status": t.get("status", "error"),
                "cases": [{
                    "name": t.get("name", ""),
                    "status": t.get("status", "error"),
                    "error": t.get("error"),
                    "file": None, "line": None,
                    "duration_ms": t.get("durationMs", 0),
                }],
                "error": t.get("error"),
            } for t in tests]
            # 通过判定只看本次要求执行的测试（选择模式=选中项；全量=全部）：
            # 未选择的 skipped 不影响；要求执行的 skipped（Not Run/DISABLED）不得通过。
            executed = [t for t in tests
                        if t.get("status") != "skipped" or t.get("name") in required_missing]
            outcome.ok = bool(executed) and ctest_exit == 0 and not timed_out \
                and not junit_error and not required_missing \
                and all(t.get("status") == "passed" for t in tests
                        if t.get("name") not in not_selected)
            diagnostics: list[dict] = []
            if junit_error:
                diagnostics.append({"severity": "error", "message": junit_error,
                                    "source": "test", "stage": "test"})
            if timed_out:
                diagnostics.append({"severity": "error", "message": "CTest 执行超时",
                                    "source": "test", "stage": "test"})
            for t in tests:
                if t.get("name") in not_selected:
                    continue
                if t.get("status") in ("failed", "error", "skipped"):
                    diagnostics.append({
                        "severity": "error",
                        "message": f"{t.get('name')}：{t.get('error') or '测试未通过'}",
                        "source": "test", "stage": "test",
                    })
            outcome.diagnostics = diagnostics
            outcome.phases = [
                {"name": "configure", "status": "completed"},
                {"name": "build", "status": "completed", "duration_ms": payload.get("buildMs", 0)},
                {"name": "test", "status": "completed" if outcome.ok else "failed",
                 "duration_ms": payload.get("ctestMs", 0), "exit_code": ctest_exit},
            ]
            return outcome

        # 未知 cmake 阶段 → 协议错误（不伪装）
        outcome = ParsedOutcome(protocol_error=f"未知 CMake 结果阶段：{phase}")
        return outcome

    @staticmethod
    def _public_target(t: dict) -> dict:
        """File API 目标 → 对外元数据（白名单字段；丢弃容器内绝对路径）。"""
        return {
            "name": t.get("name", ""),
            "type": t.get("type", "UNKNOWN"),
            "runnable": bool(t.get("runnable")),
            "source_directory": t.get("sourceDirectory", ""),
            "build_directory": t.get("buildDirectory", ""),
            "sources": list(t.get("sources") or []),
            "artifacts": list(t.get("artifacts") or []),
            "dependencies": list(t.get("dependencies") or []),
            "configuration": t.get("configuration", ""),
        }
