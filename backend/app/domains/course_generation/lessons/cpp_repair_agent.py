"""C++/CMake 专用修复代理（P8.2.1，D46）。

先确定性分类失败（12 类），再让 LLM 输出**针对失败原因的最小 FileChange
补丁**（不是整包重生成）；补丁经同一确定性应用器与完整验证。带预算。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.agents.schemas import extract_json_object
from app.domains.course_generation.lessons.change_set import content_hash

# 失败分类（对应任务规范第十一节）
FAILURE_CLASSES = (
    "schema-error",                # ChangeSet 结构/校验失败
    "file-change-conflict",        # baseHash/重复/受保护删除
    "missing-source-file",         # 引用/包含的文件缺失
    "cmake-configure-error",       # Configure 失败
    "missing-build-target",        # File API 未发现声明的目标
    "compiler-error",              # 编译错误
    "linker-error",                # 链接错误
    "missing-ctest-registration",  # 测试未注册/名字不一致
    "reference-test-failure",      # 参考实现测试失败
    "starter-invalid-failure",     # starter 构建失败/测试未执行/全通过
    "regression-failure",          # 前序回归失败
    "final-integration-failure",   # 最终集成/demo 失败
)

_CLASSIFY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("file-change-conflict", ("base-hash-mismatch", "create-exists", "update-missing",
                              "duplicate-change", "protected-delete", "delete-missing")),
    ("missing-source-file", ("missing-include", "starter-missing-include",
                             "missing-source", "prior-file-deleted")),
    ("missing-ctest-registration", ("ctest-registration-mismatch",
                                    "duplicate-test-registration", "ctest-selection")),
    ("missing-build-target", ("target-not-found", "build-target-mismatch",
                              "run-target-missing", "target-not-runnable")),
    ("cmake-configure-error", ("configure", "missing-root-cmake")),
    ("linker-error", ("链接错误", "undefined", "ld:")),
    ("compiler-error", ("编译", "error:", "fatal error")),
    ("reference-test-failure", ("空转", "断言", "恒真")),
    ("starter-invalid-failure", ("starter", "泄露", "坏工程")),
    ("regression-failure", ("回归", "regression")),
    ("final-integration-failure", ("最终集成", "demo", "final")),
    ("reference-test-failure", ("参考实现测试", "reference")),
    ("schema-error", ("schema", "结构不合法")),
]

REPAIR_SYSTEM_PROMPT = """你是 C++/CMake 课程材料的修复工程师（最小补丁协议）。
你会收到：失败分类、结构化错误清单（文件/期望/实际）、真实构建诊断、
当前工程相关文件全文、当前 ChangeSet。你只输出**修复所需的最小 FileChange
补丁列表**（JSON），绝不重输出整个工程。

## 输出（严格一个 JSON）
{
  "diagnosis": "一句话根因",
  "failureClass": "<照抄给你的分类>",
  "patch": [
    {"path": "...", "operation": "create|update|delete",
     "baseHash": "<update/delete 必填：所给文件当前的 hash>", "content": "完整新文件",
     "reason": "...", "changeCategory": "source|header|cmake|test|documentation",
     "target": "reference|starter"}
  ]
  target 说明：默认 reference（修参考工程/测试注册）；修 starter 挖空类失败
  （泄露/缺 TODO/starter 全通过）用 "starter"——给出挖空版文件（TODO+默认返回）。
}

## 铁律
1. 只修与失败直接相关的文件（错误清单的 suggestedRepairScope 优先）；
2. 修 tests/CMakeLists.txt = 在现有内容上修正/追加注册，**绝不删除既有 add_test**；
3. 不得删除或弱化测试（去断言/DISABLED/改名规避）；确需改**本任务**测试必须 reason 说明且保持验收语义；
   **前序任务的测试源文件（如 tests/test_world.cpp）绝对禁止修改**——它们是已验证回归，改动会被服务端直接拒绝；
4. 不得把 starter 补成完整实现，也不得移除 TODO；
5. buildManifest.testNames 不许因为"找不到测试"而被删除——要么修注册，要么修材料一致性；
6. update 的 baseHash 必须用提供的"当前 hash"；content 为完整文件内容。"""


@dataclass
class RepairBudget:
    max_llm_calls: int = 3
    max_tokens: int = 400_000
    max_sandbox_runs: int = 24
    llm_calls: int = 0
    tokens_used: int = 0
    sandbox_runs: int = 0

    def llm_allowed(self, est_tokens: int = 0) -> bool:
        return (self.llm_calls < self.max_llm_calls
                and self.tokens_used + est_tokens <= self.max_tokens)

    def sandbox_allowed(self) -> bool:
        return self.sandbox_runs < self.max_sandbox_runs


@dataclass
class RepairOutcome:
    ok: bool = False
    failure_class: str = "unknown"
    diagnosis: str = ""
    patch: list[dict] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)


def classify_failure(messages: list[str], error_codes: list[str] | None = None) -> str:
    """确定性失败分类（规则表；未命中归 reference-test-failure 兜底→unknown）。"""
    text = (" ".join(error_codes or []) + " " + " ".join(messages)).lower()
    for failure_class, keywords in _CLASSIFY_RULES:
        if any(keyword in text for keyword in keywords):
            return failure_class
    return "reference-test-failure"


def _file_block(files: dict[str, str], paths: list[str], limit: int = 6) -> str:
    """相关文件全文块（含当前 hash，供 update 的 baseHash）。"""
    blocks = []
    for path in paths[:limit]:
        content = files.get(path)
        if content is None:
            blocks.append(f"### {path}（当前不存在）")
            continue
        blocks.append(f"### {path}（当前 baseHash={content_hash(content)}）\n```\n{content}\n```")
    return "\n\n".join(blocks)


def repair_with_agent(
    provider,
    task_spec: dict,
    failure_class: str,
    errors: list[dict],                 # 结构化错误（consistency/applier）
    diagnostics: list[str],             # 真实构建/测试诊断摘要
    relevant_files: dict[str, str],     # 当前合成工程的相关文件（含 tests/CMakeLists 等）
    current_changeset_summary: dict,    # {path: operation} + manifest
    budget: RepairBudget,
    repair_history: list[str],
) -> RepairOutcome:
    """LLM 最小补丁修复。调用方负责应用补丁并完整重验证。"""
    est_tokens = 24_000
    if not budget.llm_allowed(est_tokens):
        return RepairOutcome(ok=False, failure_class=failure_class,
                             diagnosis="修复预算耗尽（LLM 调用/Token 上限）")
    scope_paths = list(dict.fromkeys(
        [e.get("filePath") or e.get("suggestedRepairScope", "") for e in errors
         if e.get("filePath") or e.get("suggestedRepairScope")]
        + ["CMakeLists.txt", "tests/CMakeLists.txt"]))
    scope_paths = [p for p in scope_paths if p]

    error_text = "\n".join(
        f"- [{e.get('errorCode')}] {e.get('filePath')}: 期望 {e.get('expected')}"
        f"｜实际 {e.get('actual')}（修复范围：{e.get('suggestedRepairScope')}）"
        for e in errors[:12]) or "（无结构化错误，见诊断）"
    diag_text = "\n".join(f"- {d[:300]}" for d in diagnostics[:12]) or "（无）"
    history_text = "\n".join(f"- {h[:200]}" for h in repair_history[-4:]) or "（首次修复）"

    user = (
        f"TASK：{json.dumps(task_spec, ensure_ascii=False)[:1500]}\n\n"
        f"失败分类：{failure_class}\n\n"
        f"结构化错误：\n{error_text}\n\n"
        f"真实执行诊断：\n{diag_text}\n\n"
        f"当前 ChangeSet 摘要：{json.dumps(current_changeset_summary, ensure_ascii=False)[:1200]}\n\n"
        f"相关文件（当前状态，update 需照抄 hash）：\n{_file_block(relevant_files, scope_paths)}\n\n"
        f"修复历史（避免重复无效修复）：\n{history_text}\n\n"
        "请输出最小补丁 JSON。"
    )
    budget.llm_calls += 1
    response = provider.chat(REPAIR_SYSTEM_PROMPT, user[:60000])
    budget.tokens_used += int(getattr(response, "prompt_tokens", 0) or 0) + \
        int(getattr(response, "completion_tokens", 0) or 0)
    payload = extract_json_object(response.content)
    if not isinstance(payload, dict) or not isinstance(payload.get("patch"), list):
        return RepairOutcome(ok=False, failure_class=failure_class,
                             diagnosis="修复输出不是合法补丁 JSON")
    return RepairOutcome(
        ok=True,
        failure_class=payload.get("failureClass") or failure_class,
        diagnosis=payload.get("diagnosis", ""),
        patch=payload["patch"],
        token_usage={"promptTokens": int(getattr(response, "prompt_tokens", 0) or 0),
                     "completionTokens": int(getattr(response, "completion_tokens", 0) or 0)},
    )
