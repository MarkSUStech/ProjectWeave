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


# 泄露判定认定的"实现载体"扩展名：C++ 只有翻译单元（头文件=接口给定），
# Python 为 .py。测试文件是验收工具（本就给定），永远不算泄露。
LEAK_SOURCE_EXTS = {"python": {".py"}, "cpp": {".cpp", ".cc", ".cxx"},
                    "typescript": {".ts", ".tsx"}}


def _is_test_like(path: str) -> bool:
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    return (lower.startswith("tests/") or lower.startswith("test/")
            or base.startswith("test_") or base.endswith("_test")
            or base.endswith("_test.cpp") or base.endswith("_test.py"))


def _is_impl_source(path: str, language: str) -> bool:
    """答案泄露判定用：真实实现载体（翻译单元/.py；不含头文件与 CMake 脚本）。"""
    if _is_test_like(path):
        return False
    return path.lower().endswith(tuple(LEAK_SOURCE_EXTS.get(language, {".py"})))


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
    """C++ 约定（ENV profile）：测试为独立可执行程序，断言 + main + 返回码判定。

    CMakeLists.txt/.cmake 是测试注册（add_test），不是测试本体——跳过本体
    规则，但要求至少存在一个 .cpp/.cc/.cxx 测试源文件。
    """
    problems: list[str] = []
    mains = 0
    cpp_test_sources = 0
    for f in test_files:
        path, code = f.get("path", ""), f.get("content", "") or ""
        if not path.lower().endswith((".cpp", ".cc", ".cxx")):
            if path.lower().endswith((".txt", ".cmake")) and "cmakelists" in path.lower():
                continue  # 测试注册脚本（add_test），合法
            problems.append(f"{path}: C++ 测试须为 .cpp/.cc 源文件或 CMakeLists 注册")
            continue
        cpp_test_sources += 1
        if re.search(r"\bint\s+main\s*\(", code):
            mains += 1
        else:
            problems.append(f"{path}: 缺少 main 入口（C++ 测试靠返回码判定）")
        if not re.search(r"\bassert\s*\(|\bEXPECT_|\bASSERT_|\bCHECK\s*\(", code):
            problems.append(f"{path}: 没有任何断言（assert/EXPECT_*/ASSERT_*）——测试空转")
        if re.search(r"\bassert\s*\(\s*true\s*\)", code, re.IGNORECASE):
            problems.append(f"{path}: assert(true) 恒真断言")
    if test_files and (mains == 0 or cpp_test_sources == 0):
        problems.append("没有任何含 main 的可执行测试程序（需要 .cpp 测试源文件）")
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
                  test_files: list[dict], language: str = "python",
                  expected_files: list[str] | None = None) -> list[str]:
    """starter 防伪守卫（按语言）：结构/有效 TODO/答案泄露/测试空转。返回问题列表。

    expected_files = 本任务要求学生实现的文件（instructions.expectedFiles）。
    答案泄露判定：expected_files 提供时，只在这些文件上判 starter==reference
    （头文件/前序已完成文件在 starter 与 reference 一致是正常工程演化，
    不是泄露）；缺省回退到源码文件等同性启发。
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
    # （仅真实源码文件；CMakeLists 等构建配置在结构完整的 CMake 课程中
    # starter=reference 属正常——挖空在实现文件，不在构建脚本）
    starter_paths = {f["path"] for f in starter_files}
    expected_set = set(expected_files or [])
    for ref in reference_files:
        path = ref["path"]
        if path not in starter_paths:
            continue
        if expected_set:
            # 精确判定：本任务要求实现**且是真实实现源码**的文件才算答案载体。
            # 工程骨架类任务 expectedFiles 常含 CMakeLists/头文件——构建配置与
            # 接口在 starter 中给定属正常教学（D45：不能因 starter 缺 CMake
            # 指令判坏工程，同理不因构建文件一致判泄露）。
            if path not in expected_set or not _is_impl_source(path, language):
                continue
        elif not _is_impl_source(path, language):
            continue
        starter = next(f["content"] for f in starter_files if f["path"] == path)
        if starter.strip() == (ref.get("content", "") or "").strip():
            body = _code_body(ref.get("content", ""))
            if len(body) > 60:  # 只有内容实质时才算泄露
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


# ---------------------------------------------------------------- C++ / CMake 课程验证（P8.2，D45）
# 复用 P8.1 执行系统（同一 CppRunner + DockerSandboxManager + marker 协议），
# 不存在第二套 C++ 构建系统。

from app.domains.executions.languages.base import ExecutionSpecInput, ParsedOutcome  # noqa: E402
from app.domains.executions.languages.cpp_runner import CppRunner  # noqa: E402

_cpp_runner = CppRunner()


def run_cmake_operation(
    files: dict[str, str],
    mode: str = "test",
    cmake_action: str | None = None,
    target_name: str | None = None,
    selected_tests: list[str] | None = None,
    timeout_s: float = 180.0,
) -> ParsedOutcome:
    """在真实受限沙箱执行一个 CMake 操作（discover/build/run/test 全链复用 P8.1）。"""
    import threading

    spec = ExecutionSpecInput(
        exec_id=str(uuid.uuid4()), mode=mode, entry_point=None, test_paths=[],
        files=dict(files), stdin="", timeout_s=timeout_s,
        build_system="cmake", cmake_action=cmake_action,
        target_name=target_name, selected_tests=list(selected_tests or []),
    )
    sandbox_spec = _cpp_runner.build_spec(spec, timeout_s)
    result = get_sandbox().run(sandbox_spec, threading.Event())
    return _cpp_runner.parse_result(result, spec)


@dataclass
class CppTaskVerification:
    """一个 C++/CMake 任务的八步验证结果。"""

    passed: bool = False
    problems: list[str] = field(default_factory=list)
    verifications: list[dict] = field(default_factory=list)
    reference_files: dict[str, str] = field(default_factory=dict)  # 累积参考快照
    test_names: list[str] = field(default_factory=list)


def _record(kind: str, outcome: ParsedOutcome, note: str = "") -> dict:
    """ParsedOutcome → SandboxVerification 形状记录。"""
    tests = outcome.test_results or []
    return {
        "kind": kind,
        "status": "passed" if outcome.ok else "failed",
        "exit_code": outcome.exit_code,
        "total_tests": len(tests),
        "passed_tests": sum(1 for t in tests if t.get("status") == "passed"),
        "failed_tests": sum(1 for t in tests if t.get("status") != "passed"),
        "diagnostics": (outcome.diagnostics or [])[:20],
        "stderr_tail": "\n".join(d.get("message", "") for d in (outcome.diagnostics or [])[:5])[:800],
        "duration_ms": 0,
        **({"note": note} if note else {}),
    }


def verify_cpp_cmake_task(
    material: dict,
    cumulative_reference: dict[str, str],  # 前序任务累积参考工程
    prior_test_names: list[str],           # 此前阶段要求保留的 CTest 名
    is_final: bool = False,
) -> CppTaskVerification:
    """八步验证：源校验 → Configure → 目标发现 → 构建 → 参考测试（含回归）→
    starter 预期失败 →（最终）全量集成 + demo 运行。真实沙箱，绝不伪装。"""
    result = CppTaskVerification()

    # ---- Step 1：源校验（语言化守卫：TODO/泄露/测试空转 + 工程结构）
    problems = guard_starter(
        material.get("starterFiles") or [],
        material.get("referenceFiles") or [],
        material.get("testFiles") or [],
        "cpp",
        expected_files=(material.get("instructions") or {}).get("expectedFiles"),
    )
    manifest = material.get("buildManifest") or {}
    build_targets = list(manifest.get("buildTargets") or [])
    test_names = list(manifest.get("testNames") or [])
    run_targets = list(manifest.get("runTargets") or [])
    expected_failure_phase = manifest.get("expectedFailurePhase")

    ref_paths = {f["path"] for f in material.get("referenceFiles") or []}
    if "CMakeLists.txt" not in ref_paths and "CMakeLists.txt" not in cumulative_reference:
        problems.append("参考工程缺少根 CMakeLists.txt")
    if not test_names and not expected_failure_phase:
        problems.append("任务未声明任何 CTest 测试（buildManifest.testNames 为空）")
    if problems:
        result.problems = problems
        return result

    # CMake 课程中测试是工程的一部分（CMakeLists 注册 add_test）——
    # 参考工程 = 前序累积 + 本任务参考实现 + 本任务测试
    reference_files = merge_files(
        cumulative_reference,
        {f["path"]: f["content"] for f in (material.get("referenceFiles") or [])
         + (material.get("testFiles") or [])},
    )
    starter_project = merge_files(
        cumulative_reference,
        {f["path"]: f["content"] for f in (material.get("starterFiles") or [])
         + (material.get("testFiles") or [])},
    )
    result.reference_files = reference_files
    result.test_names = test_names

    # ---- Step 2+3：Configure + File API 目标发现（真实执行）
    discover = run_cmake_operation(reference_files, mode="run", cmake_action="discover")
    result.verifications.append(_record("cmake-discovery", discover))
    if not discover.ok:
        result.problems.append(
            "CMake Configure 失败：" + "；".join(
                d.get("message", "") for d in discover.diagnostics[:3]))
        return result
    discovered_names = {t["name"] for t in (discover.cmake or {}).get("targets") or []}
    missing_targets = [t for t in build_targets if t not in discovered_names]
    if missing_targets:
        result.problems.append(
            f"声明的构建目标未被发现：{', '.join(missing_targets)}"
            f"（实际：{', '.join(sorted(discovered_names))[:200]}）")
        result.verifications[-1]["status"] = "failed"
        return result

    # ---- Step 4+5+7：全量构建 + 参考测试（本任务 required + 前序回归一次跑）
    required = sorted(set(test_names) | set(prior_test_names))
    reference_run = run_cmake_operation(
        reference_files, mode="test", selected_tests=required)
    result.verifications.append(_record(
        "reference-tests", reference_run,
        note=f"required={test_names}" + (f" regression={prior_test_names}" if prior_test_names else ""),
    ))
    if not reference_run.ok:
        failed = [t.get("path") for t in reference_run.test_results or []
                  if t.get("status") != "passed" and t.get("status") != "skipped"]
        result.problems.append(
            f"参考实现测试未通过：{', '.join(failed) or '无结构化结果'}；"
            + "；".join(d.get("message", "") for d in reference_run.diagnostics[:3]))
        return result

    # ---- Step 6：starter 预期失败（工程可构建 + 要求的测试失败）
    starter_run = run_cmake_operation(
        starter_project, mode="test", selected_tests=test_names)
    starter_record = _record("starter-expected-fail", starter_run)
    if expected_failure_phase:
        # "修复构建"类任务：允许目标性预期失败，需诊断含关键词
        keywords = manifest.get("expectedFailureKeywords") or []
        diag_text = " ".join(d.get("message", "") for d in starter_run.diagnostics)
        phase_failed = any(
            p.get("name") == expected_failure_phase and p.get("status") == "failed"
            for p in starter_run.phases)
        ok = phase_failed and (not keywords or any(k in diag_text for k in keywords))
        starter_record["status"] = "passed" if ok else "failed"
        if not ok:
            result.problems.append(
                f"starter 未呈现声明的预期失败（{expected_failure_phase}）")
        result.verifications.append(starter_record)
        result.passed = ok
        return result

    build_phase = next((p for p in starter_run.phases if p.get("name") == "build"), {})
    required_failed = [t for t in starter_run.test_results or []
                       if t.get("path") in set(test_names)
                       and t.get("status") in ("failed", "error", "skipped")]
    if build_phase.get("status") == "failed":
        starter_record["status"] = "failed"
        result.problems.append(
            "starter 工程无法构建（坏工程不是合格 starter）："
            + "；".join(d.get("message", "") for d in starter_run.diagnostics[:3]))
        result.verifications.append(starter_record)
        return result
    if not required_failed:
        starter_record["status"] = "failed"
        result.problems.append(
            "starter 上全部要求测试通过——测试未覆盖待实现功能（疑似泄露/空转）")
        result.verifications.append(starter_record)
        return result
    starter_record["status"] = "passed"
    starter_record["note"] = f"预期失败：{[t.get('path') for t in required_failed]}"
    result.verifications.append(starter_record)

    # ---- Step 8：最终集成（全量测试 + demo 运行）
    if is_final:
        full_run = run_cmake_operation(reference_files, mode="test")
        result.verifications.append(_record("final-integration", full_run))
        if not full_run.ok:
            result.problems.append("最终集成验证未通过（全部 CTest）")
            return result
        for run_target in run_targets:
            demo = run_cmake_operation(
                reference_files, mode="run", cmake_action="run", target_name=run_target)
            result.verifications.append(_record("demo-run", demo, note=f"target={run_target}"))
            if not demo.ok:
                result.problems.append(f"最终演示目标运行失败：{run_target}")
                return result

    result.passed = True
    return result
