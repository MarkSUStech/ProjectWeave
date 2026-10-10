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


def build_archive(spec: ExecutionSpecInput, timeout_s: float) -> bytes:
    manifest = {
        "mode": spec.mode,
        "entry": spec.entry_point,
        "testPaths": spec.test_paths,
        "stdin": spec.stdin,
        "timeoutSec": timeout_s,
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
        """入口/测试必须是 C++ 源文件；其余文件视为项目数据放行（CMakeLists.txt/data 均合法）。"""
        errors: list[str] = []
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
        return SandboxSpec(
            image=self.image,
            command=BOOTSTRAP_COMMAND,
            stdin_archive=build_archive(spec, timeout_s),
            timeout_s=timeout_s,
            container_name=f"pw-exec-{spec.exec_id[:12]}",
            exec_id=spec.exec_id,
            # D34：编译型语言需要执行编译产物 → exec tmpfs（服务端规格，客户端不可控）
            exec_workspace=True,
            tmpfs_size_mb=256,
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
            outcome.phases = [{"name": "run" if spec.mode == "run" else "test", "status": "failed", "duration_ms": result.duration_ms}]
            return outcome

        phase = (marker_payload or {}).get("phase")

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
