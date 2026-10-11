"""Course Verifier（P7.2，D42）：真实沙箱验证课程材料。

核心原则：LLM 只生成；测试是否通过只由真实执行判定。
- 参考实现：构建/导入 + 本任务测试 + 回归（前任务测试）+ 最终集成；
- starter：结构检查 + 测试**预期失败**（证明测试有效、不泄露答案）；
- 防伪守卫：starter 含 TODO、不含参考核心、测试断言非空转。

直接复用执行层的 LanguageRunner + DockerSandboxManager（不建 HTTP 往返）。
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import uuid
from dataclasses import dataclass, field

from app.domains.executions.sandbox.docker_sandbox import DockerSandboxManager
from app.domains.executions.languages.python_runner import PythonRunner

_sandbox = None


def get_sandbox():
    global _sandbox
    if _sandbox is None:
        _sandbox = DockerSandboxManager()
    return _sandbox


@dataclass
class VerifyOutcome:
    status: str  # passed | failed | error | skipped
    exit_code: int | None = None
    total: int = 0
    passed: int = 0
    failed: int = 0
    diagnostics: list[dict] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status, "exit_code": self.exit_code,
            "total": self.total, "passed": self.passed, "failed": self.failed,
            "diagnostics": self.diagnostics[:20],
            "stdout_tail": self.stdout_tail[-800:],
            "stderr_tail": self.stderr_tail[-800:],
            "duration_ms": self.duration_ms,
        }


def run_in_sandbox(
    language: str, files: dict[str, str],
    mode: str, entry: str | None, test_paths: list[str],
    timeout_s: float = 60.0,
) -> VerifyOutcome:
    """在真实 Docker 沙箱执行一组文件（run/test）。"""
    import threading

    if language != "python":
        return VerifyOutcome(status="skipped")  # v1：python；cpp 走 PythonRunner 同型扩展

    # 根级 conftest：让 pytest 把工作区根加入 sys.path（包导入可用）
    if mode == "test" and "conftest.py" not in files:
        files = {**files, "conftest.py": ""}
    spec_input = _SpecInput(
        exec_id=str(uuid.uuid4()), mode=mode, entry_point=entry,
        test_paths=test_paths, files=files, stdin="", timeout_s=timeout_s,
    )
    spec = PythonRunner().build_spec(spec_input, timeout_s)
    result = get_sandbox().run(spec, threading.Event())
    if not result.started:
        return VerifyOutcome(status="error", stderr_tail=result.stderr[:800])

    import json as _json

    marker = None
    m = re.search(r"^===PW_RESULT===(\{.*\})\s*$", result.stdout, re.MULTILINE)
    if m:
        try:
            marker = _json.loads(m.group(1))
        except _json.JSONDecodeError:
            marker = None

    outcome = VerifyOutcome(
        status="failed", exit_code=result.exit_code,
        stdout_tail=result.stdout, stderr_tail=result.stderr,
        duration_ms=result.duration_ms,
    )
    if result.timed_out:
        outcome.status = "failed"
        outcome.stderr_tail = "执行超时（沙箱已终止）"
        return outcome

    if mode == "run":
        outcome.status = "passed" if result.exit_code == 0 else "failed"
        return outcome

    # test 模式：解析逐用例结果
    if marker and isinstance(marker.get("tests"), list):
        outcome.total = len(marker["tests"])
        for t in marker["tests"]:
            st = t.get("status")
            if st == "passed":
                outcome.passed += 1
            else:
                outcome.failed += 1
                outcome.diagnostics.append({
                    "kind": "test-failure",
                    "file": t.get("file"), "line": t.get("line"),
                    "message": (t.get("error") or t.get("name") or "")[:300],
                })
        for fe in marker.get("fileErrors", []):
            outcome.diagnostics.append({
                "kind": "collection-error",
                "file": fe.get("file"), "message": (fe.get("error") or "")[:300],
            })
    else:
        # 无标记（编译/导入失败）：从 stderr 提取 Traceback 摘要
        tb = re.findall(r'File "([^"]+)", line (\d+).*?\n(\w+Error:.*)', result.stderr)
        for path, line, msg in tb[-5:]:
            outcome.diagnostics.append({
                "kind": "traceback", "file": path.replace("/sandbox/work/", ""),
                "line": int(line), "message": msg[:300],
            })
    outcome.status = "passed" if (
        outcome.exit_code == 0 and outcome.total > 0 and outcome.failed == 0
        and not outcome.diagnostics
    ) else "failed"
    return outcome


class _SpecInput:
    """适配 LanguageRunner.build_spec 的输入形状。"""

    def __init__(self, exec_id, mode, entry_point, test_paths, files, stdin, timeout_s):
        self.exec_id = exec_id
        self.mode = mode
        self.entry_point = entry_point
        self.test_paths = test_paths
        self.files = files
        self.stdin = stdin
        self.timeout_s = timeout_s


# ---------------------------------------------------------------- 防伪守卫（确定性）


TODO_RE = re.compile(r"#\s*TODO|#\s*todo|/\*\s*TODO|<!--\s*TODO")


def guard_starter(starter_files: list[dict], reference_files: list[dict],
                  test_files: list[dict]) -> list[str]:
    """starter 防伪守卫：结构/TODO/答案泄露/测试空转。返回问题列表。"""
    problems: list[str] = []
    starter_paths = {f["path"] for f in starter_files}
    ref_paths = {f["path"] for f in reference_files}
    if not starter_files:
        problems.append("starter 为空——学生需要可开始的工程结构")
    if not test_files:
        problems.append("测试为空——无法验证任务完成")
    if not reference_files:
        problems.append("参考实现为空——无法验证课程可通关")

    # TODO 标记（至少一个源文件含 TODO）
    starter_code = "\n".join(f.get("content", "") for f in starter_files if f["path"].endswith(".py"))
    if starter_files and not TODO_RE.search(starter_code):
        problems.append("starter 缺少 TODO 标记（学生无从知道待实现区域）")

    # 答案泄露：starter 不得与 reference 的核心实现完全一致
    for ref in reference_files:
        if ref["path"] not in starter_paths:
            continue
        starter = next(f["content"] for f in starter_files if f["path"] == ref["path"])
        if starter.strip() == ref.get("content", "").strip() and ref["path"].endswith(".py"):
            body = _code_body(ref.get("content", ""))
            if len(body) > 200:  # 只有内容实质时才算泄露
                problems.append(f"starter 与 reference 完全一致（答案泄露）：{ref['path']}")

    # 测试空转守卫
    test_code = "\n".join(f.get("content", "") for f in test_files)
    if test_files:
        if re.search(r"assert\s+True\s*(#|$)", test_code):
            problems.append("测试含 `assert True` 空断言")
        if not re.search(r"\bassert\b|\bdef test_", test_code):
            problems.append("测试文件没有任何断言或测试函数")
        if len(re.findall(r"\bdef test_|\bdef \w*test", test_code)) == 0:
            problems.append("没有 pytest 测试函数")
    return problems


def _code_body(content: str) -> str:
    """去掉注释/空行后的代码体（用于泄露判定的最小启发）。"""
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        lines.append(line)
    return "\n".join(lines)


def merge_files(base: dict[str, str], changes: dict[str, str]) -> dict[str, str]:
    """累积合并：base 之上应用 changes（新增/覆盖）——阶段连续性的文件级实现。"""
    merged = dict(base)
    merged.update(changes)
    return merged
