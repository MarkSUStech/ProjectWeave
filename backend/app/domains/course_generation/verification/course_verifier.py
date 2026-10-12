"""Course Verifier（P7.2，D42）：真实沙箱验证课程材料。

核心原则：LLM 只生成；测试是否通过只由真实执行判定。
- 参考实现：构建/导入 + 本任务测试 + 回归（前任务测试）+ 最终集成；
- starter：结构检查 + 测试**预期失败**（证明测试有效、不泄露答案）；
- 防伪守卫：starter 含 TODO、不含参考核心、测试断言非空转。

直接复用执行层的 LanguageRunner + DockerSandboxManager（不建 HTTP 往返）。
"""

from __future__ import annotations

import ast
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
        """键与 SandboxVerification schema 对齐（total_tests 等），可直接进 verifications。"""
        return {
            "status": self.status, "exit_code": self.exit_code,
            "total_tests": self.total, "passed_tests": self.passed,
            "failed_tests": self.failed,
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

    if language not in SANDBOX_VERIFIED_LANGUAGES:
        return VerifyOutcome(
            status="skipped",
            stderr_tail=f"{language} 课程暂不支持真实沙箱验证（当前仅 python）；"
                        "流水线应在生成前拒绝，不应走到此处",
        )

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


# ---------------------------------------------------------------- 防伪守卫（确定性、按语言）

# 各语言源文件扩展名（starter 的 TODO/泄露检查只看这些 + cpp 的构建脚本）
SOURCE_EXTS: dict[str, set[str]] = {
    "python": {".py"},
    "cpp": {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx"},
    "typescript": {".ts", ".tsx", ".js", ".jsx", ".mjs"},
}
LANG_LABEL = {"python": "Python", "cpp": "C++", "typescript": "TypeScript"}
# CMake 构建脚本同样承载 cpp 课程的 TODO（本仓库 cpp 工程约定）
CPP_SCRIPT_SUFFIXES = (".cmake",)
CPP_SCRIPT_NAMES = ("cmakelists.txt",)

# 课程内容已具备真实沙箱验证器的语言（未列出的语言在 build_lessons 提前拒绝）
SANDBOX_VERIFIED_LANGUAGES = ("python",)


def _is_source(path: str, language: str) -> bool:
    lower = path.lower()
    if language == "cpp" and (lower.endswith(CPP_SCRIPT_SUFFIXES)
                              or lower.rsplit("/", 1)[-1] in CPP_SCRIPT_NAMES):
        return True
    return lower.endswith(tuple(SOURCE_EXTS.get(language, SOURCE_EXTS["python"])))


def _has_valid_todo(code: str) -> bool:
    """有效 TODO：标记后跟至少一点描述文字（裸 `TODO` 不算，学生无从下手）。"""
    for m in re.finditer(r"TODO", code, re.IGNORECASE):
        line_rest = code[m.end():code.find("\n", m.end())]
        if len(line_rest.strip().strip("：:*-—")) >= 2:
            return True
    return False


def _strip_docstring(body: list) -> list:
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def _is_hollow_stmt(node) -> bool:
    """pass / ... / raise NotImplementedError —— 空壳语句。"""
    if isinstance(node, ast.Pass):
        return True
    if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and node.value.value is Ellipsis):
        return True
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
        return getattr(node.exc.func, "id", "") == "NotImplementedError"
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name):
        return node.exc.id == "NotImplementedError"
    return False


def _hollow_defs(code: str) -> list[str]:
    """AST 找空壳待实现函数（体仅 docstring/pass/.../raise NotImplementedError）。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = _strip_docstring(node.body)
            if not body or all(_is_hollow_stmt(n) for n in body):
                names.append(node.name)
    return names


def _call_name(func) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _vacuous_test(node) -> bool:
    """无 assert 且无 raises/approx/fail 等有效校验调用 → 空转测试。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            return False
        if isinstance(n, ast.Call):
            name = _call_name(n.func)
            if any(k in name for k in ("raises", "approx", "fail", "assert_")):
                return False
    return True


def _has_assert_true(node) -> bool:
    for n in ast.walk(node):
        if (isinstance(n, ast.Assert) and isinstance(n.test, ast.Constant)
                and n.test.value is True):
            return True
    return False


def _python_test_problems(test_files: list[dict]) -> list[str]:
    """AST 结构化检查：语法可解析（pytest 可收集）+ test_ 函数 + 非空转。"""
    problems: list[str] = []
    test_fn = 0
    for f in test_files:
        path, code = f.get("path", ""), f.get("content", "") or ""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            problems.append(f"{path}: Python 语法错误（pytest 无法收集）第 {exc.lineno} 行：{exc.msg}")
            continue
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test")):
                test_fn += 1
                if _vacuous_test(node):
                    problems.append(f"{path}::{node.name}: 空转测试（没有任何有效断言）")
                if _has_assert_true(node):
                    problems.append(f"{path}::{node.name}: `assert True` 恒真断言")
    if test_fn == 0:
        problems.append("没有 pytest 测试函数（需要 test_ 开头的函数，AST 未发现）")
    return problems


def _cpp_test_problems(test_files: list[dict]) -> list[str]:
    """C++ 约定（ENV profile）：测试为独立可执行程序，断言 + main + 返回码判定。"""
    problems: list[str] = []
    mains = 0
    for f in test_files:
        path, code = f.get("path", ""), f.get("content", "") or ""
        if not path.lower().endswith((".cpp", ".cc", ".cxx")):
            problems.append(f"{path}: C++ 测试须为 .cpp/.cc 源文件（独立可执行程序）")
            continue
        if re.search(r"\bint\s+main\s*\(", code):
            mains += 1
        else:
            problems.append(f"{path}: 缺少 main 入口（C++ 测试靠返回码判定）")
        if not re.search(r"\bassert\s*\(|\bEXPECT_|\bASSERT_|\bCHECK\s*\(", code):
            problems.append(f"{path}: 没有任何断言（assert/EXPECT_*/ASSERT_*）——测试空转")
        if re.search(r"\bassert\s*\(\s*true\s*\)", code, re.IGNORECASE):
            problems.append(f"{path}: assert(true) 恒真断言")
    if test_files and mains == 0:
        problems.append("没有任何含 main 的可执行测试程序")
    return problems


def _typescript_test_problems(test_files: list[dict]) -> list[str]:
    """TS 约定（ENV profile）：describe/it/test + expect 断言。"""
    problems: list[str] = []
    cases = 0
    for f in test_files:
        path, code = f.get("path", ""), f.get("content", "") or ""
        cases += len(re.findall(r"\b(?:it|test)\s*[\(\s]", code))
        if not re.search(r"\bexpect\s*\(", code):
            problems.append(f"{path}: 没有 expect 断言——测试空转")
        if re.search(r"expect\s*\(\s*(?:true|1)\s*\)\s*\.\s*toBe\s*\(\s*(?:true|1)\s*\)", code):
            problems.append(f"{path}: expect(true).toBe(true) 恒真断言")
    if test_files and cases == 0:
        problems.append("没有 it/test 测试用例")
    return problems


TEST_GUARDS = {
    "python": _python_test_problems,
    "cpp": _cpp_test_problems,
    "typescript": _typescript_test_problems,
}


def guard_starter(starter_files: list[dict], reference_files: list[dict],
                  test_files: list[dict], language: str = "python") -> list[str]:
    """starter 防伪守卫（按语言）：结构/有效 TODO/答案泄露/测试空转。返回问题列表。

    每条问题带文件路径，直接进入修复模型反馈与前端展示。
    """
    problems: list[str] = []
    if not starter_files:
        problems.append("starter 为空——学生需要可开始的工程结构")
    if not test_files:
        problems.append("测试为空——无法验证任务完成")
    if not reference_files:
        problems.append("参考实现为空——无法验证课程可通关")
    if language not in SOURCE_EXTS:
        problems.append(f"未知课程语言：{language}（守卫仅支持 python/cpp/typescript）")
        return problems

    # -- 有效 TODO（学生可定位待实现区域）；python 额外接受 AST 空壳函数
    starter_sources = [f for f in starter_files if _is_source(f.get("path", ""), language)]
    if starter_files and not starter_sources:
        exts = ", ".join(sorted(SOURCE_EXTS[language]))
        problems.append(f"starter 缺少 {LANG_LABEL[language]} 源文件（期望扩展名：{exts}）")
    elif starter_files:
        todo_paths = [f.get("path") for f in starter_sources
                      if _has_valid_todo(f.get("content", "") or "")]
        stubs: list[str] = []
        if language == "python":
            for f in starter_sources:
                stubs.extend(f"{f.get('path')}::{name}"
                             for name in _hollow_defs(f.get("content", "") or ""))
        if not todo_paths and not stubs:
            problems.append(
                f"starter 缺少有效 TODO 标记或待实现空函数——检查 {LANG_LABEL[language]} "
                f"源文件（{', '.join(f.get('path', '') for f in starter_sources[:4])}）；"
                "TODO 必须带描述文字，或保留空函数体（pass/.../raise NotImplementedError）")

    # -- 答案泄露：starter 不得与 reference 的核心实现完全一致
    starter_paths = {f["path"] for f in starter_files}
    for ref in reference_files:
        path = ref["path"]
        if path not in starter_paths or not _is_source(path, language):
            continue
        starter = next(f["content"] for f in starter_files if f["path"] == path)
        if starter.strip() == (ref.get("content", "") or "").strip():
            body = _code_body(ref.get("content", ""))
            if len(body) > 200:  # 只有内容实质时才算泄露
                problems.append(f"starter 与 reference 完全一致（答案泄露）：{path}")

    # -- 测试空转守卫（按语言的测试约定）
    if test_files:
        problems.extend(TEST_GUARDS[language](test_files))
    return problems


def _code_body(content: str) -> str:
    """去掉注释/空行后的代码体（用于泄露判定的最小启发；兼容 # 与 // 注释）。"""
    lines = []
    for line in (content or "").splitlines():
        stripped = line.strip()
        if (not stripped or stripped.startswith("#") or stripped.startswith("//")
                or stripped.startswith('"""') or stripped.startswith("'''")
                or stripped.startswith("/*")):
            continue
        lines.append(line)
    return "\n".join(lines)


def merge_files(base: dict[str, str], changes: dict[str, str]) -> dict[str, str]:
    """累积合并：base 之上应用 changes（新增/覆盖）——阶段连续性的文件级实现。"""
    merged = dict(base)
    merged.update(changes)
    return merged
