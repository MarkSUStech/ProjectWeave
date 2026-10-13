"""Independent Course Evaluator（P8.2.3，D48）。

Agent 不得自行宣布课程合格：评估由本模块独立执行（复用 P8.2
verify_cpp_cmake_task 八步真实验证），附加实验稳定性（重复 Clean Sandbox）
与轻量 Mutation Testing（有预算）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.course_generation.verification.course_verifier import (
    run_cmake_operation,
    verify_cpp_cmake_task,
)

# 轻量变异算子（.cpp 实现行级替换；每算子最多 N 个变异体）
_MUTATION_OPS = [
    ("==", "!="),
    ("!=", "=="),
    (">", ">="),
    ("<", "<="),
]


@dataclass
class EvaluationReport:
    engineering: str = "not-evaluated"      # passed | failed | not-evaluated
    pedagogy: str = "not-evaluated"         # passed | failed | heuristic | not-evaluated
    stability: str = "not-evaluated"        # passed | flaky-suspected | not-evaluated
    verifications: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    stability_detail: dict = field(default_factory=dict)
    mutation_detail: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_feedback(self) -> dict:
        """→ Agent 结构化反馈（分类失败 + 建议检查文件）。"""
        failures = []
        for problem in self.problems[:8]:
            failures.append({
                "category": _categorize(problem),
                "message": problem[:300],
                "suggestedInspection": _suggest_files(problem),
            })
        return {
            "evaluation": {
                "engineering": self.engineering,
                "pedagogy": self.pedagogy,
                "stability": self.stability,
            },
            "failures": failures,
            "verifications": [
                {"kind": v.get("kind"), "status": v.get("status"),
                 "note": v.get("note", "")}
                for v in self.verifications
            ],
            "stability": self.stability_detail,
            "mutation": {k: v for k, v in self.mutation_detail.items()
                         if k != "mutants"},
        }


def evaluate_lesson(material: dict, base_files: dict, prior_tests: list[str],
                    is_final: bool, stability_runs: int = 2) -> EvaluationReport:
    """八步真实验证 + 教学约束（内含）+ 稳定性重复执行。"""
    report = EvaluationReport()
    verification = verify_cpp_cmake_task(
        material, base_files, prior_tests, is_final=is_final)
    report.verifications = verification.verifications
    report.problems = verification.problems
    report.engineering = "passed" if verification.passed else "failed"
    # 教学法：starter-expected-fail 记录为 passed 即满足确定性部分；
    # 其余维度（提示渐进性等）为启发式——标注而非断言
    starter_ok = any(v.get("kind") == "starter-expected-fail"
                     and v.get("status") == "passed"
                     for v in verification.verifications)
    report.pedagogy = ("passed" if starter_ok and verification.passed
                       else ("heuristic" if verification.passed else "failed"))
    if verification.passed and stability_runs > 0:
        report.stability_detail = run_stability(
            verification.reference_files, material.get("buildManifest", {}),
            runs=stability_runs)
        report.stability = ("passed" if report.stability_detail.get("flakySuspected") is False
                            else "flaky-suspected")
        if report.stability != "passed":
            report.problems.append("实验稳定性存疑：" + str(
                report.stability_detail.get("failureDistribution"))[:200])
    return report


def run_stability(reference_files: dict, manifest: dict, runs: int = 2) -> dict:
    """重复 Clean Sandbox 全量 CTest（同一候选课程多次独立执行）。"""
    test_names = manifest.get("testNames") or []
    attempts, passes, failure_count = 0, 0, 0
    failure_details: list = []
    for _ in range(runs):
        attempts += 1
        outcome = run_cmake_operation(reference_files, mode="test",
                                      selected_tests=test_names)
        if outcome.ok:
            passes += 1
        else:
            failure_count += 1
            failure_details.append([d.get("message", "")[:120]
                                    for d in (outcome.diagnostics or [])[:3]])
    return {
        "attempts": attempts, "passes": passes,
        "failures": failure_count,
        "failureDistribution": failure_details,
        "flakySuspected": attempts > 0 and failure_count > 0,
    }


def run_mutation_testing(reference_files: dict, manifest: dict,
                         max_mutants: int = 4) -> dict:
    """轻量 Mutation Testing（D48）：检测公开测试是否真正约束行为。

    限制：行级算子（==/!=、>/>=、</<=），仅 .cpp 实现；每个变异体进独立
    沙箱跑必需测试。compile-error/timeout 记为 invalid-mutant——不算检出。
    """
    test_names = manifest.get("testNames") or []
    impl_files = [p for p, c in reference_files.items()
                  if p.endswith(".cpp") and "test" not in p.lower()
                  and not p.lower().startswith("tests/")]
    mutants = []
    generated = 0
    for path in impl_files:
        if generated >= max_mutants:
            break
        content = reference_files[path]
        lines = content.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if generated >= max_mutants:
                break
            for old, new in _MUTATION_OPS:
                if old in line and "assert" not in line.lower():
                    mutated = list(lines)
                    mutated[i] = line.replace(old, new, 1)
                    files = dict(reference_files)
                    files[path] = "".join(mutated)
                    status = _run_mutant(files, test_names)
                    mutants.append({"file": path, "line": i + 1,
                                    "op": f"{old}->{new}", "status": status})
                    generated += 1
                    break
    killed = sum(1 for m in mutants if m["status"] == "killed")
    valid = sum(1 for m in mutants if m["status"] in ("killed", "survived"))
    return {
        "mutants": mutants,
        "generated": len(mutants),
        "killed": killed,
        "survived": sum(1 for m in mutants if m["status"] == "survived"),
        "invalid": sum(1 for m in mutants if m["status"] not in ("killed", "survived")),
        "score": round(killed / valid, 2) if valid else None,
        "note": "轻量算子、有预算上限；分数为质量证据而非通过阈值",
    }


def _run_mutant(files: dict, test_names: list[str]) -> str:
    outcome = run_cmake_operation(files, mode="test", selected_tests=test_names)
    if outcome.ok:
        return "survived"
    build_failed = any(p.get("name") == "build" and p.get("status") == "failed"
                       for p in (outcome.phases or []))
    return "compile-error" if build_failed else "killed"


_CATEGORY_RULES = [
    ("linker-error", ("链接", "undefined", "ld:")),
    ("compiler-error", ("编译", "error:", "fatal error")),
    ("ctest-missing", ("不存在", "未发现", "注册")),
    ("starter-invalid", ("starter", "泄露", "空转", "坏工程")),
    ("regression", ("回归",)),
    ("configure-error", ("Configure", "CMake 配置")),
    ("test-failure", ("测试未通过", "断言")),
]


def _categorize(problem: str) -> str:
    for category, keys in _CATEGORY_RULES:
        if any(k in problem for k in keys):
            return category
    return "unknown"


_SUGGEST_RE = re.compile(r"([A-Za-z0-9_/.-]+\.(?:cpp|hpp|h|txt))")


def _suggest_files(problem: str) -> list[str]:
    return list(dict.fromkeys(_SUGGEST_RE.findall(problem)))[:4]
