"""Python 语言运行器（P4.2b 第一版：CPython 3.12 + pytest 预装镜像）。

- run：python -u <entry>，stdin 来自请求，traceback → 文件/行号诊断；
- test：pytest Python API（driver 内 Recorder 插件）→ 逐用例结果；
- 多文件：项目内相对 import 天然支持（工作目录 = 解包后的项目根）；
- 第三方包：镜像未预装的包直接 import 失败（不做 pip install，见 D32）。
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

DRIVER_PATH = Path(__file__).with_name("python_driver.py")
RESERVED_PREFIX = "__pw"

# 容器内引导命令：建目录 → 解包 → 进入工作区 → 执行驱动。
BOOTSTRAP_COMMAND = [
    "sh", "-c",
    "mkdir -p /sandbox/work /sandbox/tmp /sandbox/home"
    " && tar -xzf - -C /sandbox/work"
    " && cd /sandbox/work"
    " && exec python -u __pw/driver.py",
]

# 白名单环境变量：只传运行必需项，不继承任何服务端配置。
CONTAINER_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "HOME": "/sandbox/home",
    "TMPDIR": "/sandbox/tmp",
}

# Python traceback 帧：  File "src/main.py", line 4, in <module>
_FRAME_RE = re.compile(r'^\s*File "([^"]+)", line (\d+)')
# 结果标记行（driver 打印在 stdout 尾部）
_MARKER_RE = re.compile(r"^===PW_RESULT===(\{.*\})\s*$", re.MULTILINE)

# 容器工作目录前缀：Python 3.11+ 会把 __main__ 的路径绝对化，映射回项目相对路径
_WORKDIR_PREFIX = "/sandbox/work/"


def _normalize_path(file_name: str) -> str:
    if file_name.startswith(_WORKDIR_PREFIX):
        return file_name[len(_WORKDIR_PREFIX):]
    return file_name


def build_archive(spec: ExecutionSpecInput, timeout_s: float) -> bytes:
    """项目文件 + manifest + driver → gzip tar（作为容器 stdin）。"""
    manifest = {
        "mode": spec.mode,
        "entry": spec.entry_point,
        "testPaths": spec.test_paths,
        "stdin": spec.stdin,
        "timeoutSec": timeout_s,
    }
    buffer = io.BytesIO()
    # deterministic 排序便于快照对比
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


def parse_traceback(stderr: str, fallback_file: str | None) -> list[dict]:
    """stderr 中的 Python traceback → 文件/行号诊断（确定性解析，无 LLM）。"""
    if not stderr.strip():
        return []
    frames = []
    for line in stderr.splitlines():
        match = _FRAME_RE.match(line)
        if match:
            frames.append((match.group(1), int(match.group(2))))
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    message = lines[-1] if lines else "运行失败"
    if frames:
        file_name, line_no = frames[-1]
        return [
            {
                "severity": "error",
                "message": message,
                "file": _normalize_path(file_name),
                "line": line_no,
                "source": "runtime",
            }
        ]
    return [{"severity": "error", "message": stderr.strip()[-600:], "file": fallback_file, "source": "runtime"}]


class PythonRunner(LanguageRunner):
    """Python 3.12 固定版本运行器。"""

    language = "python"
    image = "projectweave-sandbox-python:3.12"

    def validate_files(self, spec: ExecutionSpecInput) -> list[str]:
        errors: list[str] = []
        for path in spec.files:
            if not path.endswith(".py"):
                errors.append(f"Python 执行只允许 .py 文件：{path}")
        if spec.mode == "run":
            if not spec.entry_point:
                errors.append("run 模式必须提供 entryPoint")
            elif not spec.entry_point.endswith(".py"):
                errors.append("入口文件必须是 .py")
        else:
            if not spec.test_paths:
                errors.append("test 模式必须提供至少一个测试文件")
            for path in spec.test_paths:
                if not path.endswith(".py"):
                    errors.append(f"测试文件必须是 .py：{path}")
        return errors

    def build_spec(self, spec: ExecutionSpecInput, timeout_s: float) -> SandboxSpec:
        return SandboxSpec(
            image=self.image,
            command=BOOTSTRAP_COMMAND,
            stdin_archive=build_archive(spec, timeout_s),
            timeout_s=timeout_s,
            container_name=f"pw-exec-{spec.exec_id[:12]}",
            exec_id=spec.exec_id,
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
            # 驱动未上报（容器启动失败 / 引导命令失败）
            outcome.protocol_error = outcome.protocol_error or "沙箱未返回执行结果标记"
            outcome.diagnostics = [
                {
                    "severity": "error",
                    "message": (result.stderr.strip()[-600:] or "沙箱执行异常退出"),
                    "source": "runtime",
                }
            ]
            outcome.phases = [{"name": "run" if spec.mode == "run" else "test", "status": "failed", "duration_ms": result.duration_ms}]
            return outcome

        if result.timed_out:
            outcome.phases = [
                {"name": "run" if spec.mode == "run" else "test", "status": "failed", "duration_ms": result.duration_ms}
            ]
            return outcome

        if spec.mode == "run":
            timed_out_flag = bool(marker_payload and marker_payload.get("timedOut"))
            exit_code = marker_payload.get("exitCode") if marker_payload else result.exit_code
            outcome.exit_code = exit_code
            outcome.timed_out = timed_out_flag
            outcome.ok = exit_code == 0 and not timed_out_flag
            outcome.diagnostics = parse_traceback(result.stderr, spec.entry_point) if not outcome.ok else []
            outcome.phases = [
                {
                    "name": "run",
                    "status": "completed" if outcome.ok else "failed",
                    "duration_ms": result.duration_ms,
                    "exit_code": exit_code,
                }
            ]
            return outcome

        # test 模式：pytest 结果映射
        tests = (marker_payload or {}).get("tests", [])
        file_errors = (marker_payload or {}).get("fileErrors", [])
        outcome.timed_out = bool((marker_payload or {}).get("timedOut"))
        for test in tests:
            if test.get("file"):
                test["file"] = _normalize_path(str(test["file"]))
        by_file: dict[str, dict] = {}
        for test in tests:
            file_key = test.get("file") or ""
            record = by_file.setdefault(
                file_key, {"path": file_key, "status": "passed", "cases": [], "error": None}
            )
            status = test.get("status", "error")
            record["cases"].append(
                {
                    "name": test.get("name", ""),
                    "status": status,
                    "error": test.get("error"),
                    "file": test.get("file"),
                    "line": test.get("line"),
                    "duration_ms": test.get("duration_ms", 0),
                }
            )
        for file_error in file_errors:
            file_key = file_error.get("file") or ""
            record = by_file.setdefault(
                file_key, {"path": file_key, "status": "passed", "cases": [], "error": None}
            )
            record["status"] = "error"
            record["error"] = file_error.get("error")

        test_results = []
        for record in by_file.values():
            if record["status"] != "error":
                statuses = {case["status"] for case in record["cases"]}
                record["status"] = "failed" if statuses & {"failed", "error"} else "passed"
            test_results.append(record)

        outcome.test_results = test_results
        outcome.ok = bool(test_results) and all(r["status"] == "passed" for r in test_results)
        outcome.diagnostics = [
            {
                "severity": "error",
                "message": case.get("error") or "断言失败",
                "file": case.get("file"),
                "line": case.get("line"),
                "source": "test",
            }
            for r in test_results
            for case in r["cases"]
            if case["status"] in ("failed", "error")
        ]
        outcome.phases = [
            {
                "name": "test",
                "status": "completed" if outcome.ok else "failed",
                "duration_ms": result.duration_ms,
                "exit_code": (marker_payload or {}).get("exitCode", result.exit_code),
            }
        ]
        return outcome
