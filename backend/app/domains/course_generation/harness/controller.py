"""Harness 控制器（P8.2.3，D48）：CourseDevelopmentAgent 循环 + 会话生命周期。

核心分离：Agent（LLM）只提出行动；本控制器执行工具、执行独立评估、
管理预算/租约/检查点。真实多轮 function-calling（复用 DeepSeek
chat_with_tools），工具结果真实回填——不存在伪造调用。
"""

from __future__ import annotations

import json
import threading
import uuid as _uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.agents.schemas import ToolContext
from app.domains.course_generation.harness.evaluator import (
    EvaluationReport,
    evaluate_lesson,
    run_mutation_testing,
)
from app.domains.course_generation.harness.models import CourseDevSession
from app.domains.course_generation.harness.tools import build_harness_tools
from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.lesson_publisher import (
    ReleaseError,
    _lease_renew,
    _lease_valid,
    _persist_checkpoint,
    _session,
    utcnow,
)

AGENT_SYSTEM_PROMPT = """你是 ProjectWeave 的课程开发 Agent，在一个受控工作区中**持续开发**教学工程。
你通过工具循环工作：读文件 → 修改 → 真实构建/测试 → 查看诊断 → 再修复 → 评估 → 提交。

## 当前任务
{task_brief}

## 已验证基线（不得破坏）
- 前序测试注册表：{prior_tests}
- 基线文件清单：{baseline_files}

## 工具使用策略
1. 先 list_workspace_files / read_workspace_file 理解现状（不必每次全读）；
2. apply_file_changes 做增量修改（update 用 read 返回的当前 hash）；
3. cmake_build / run_ctest 真实验证（结果含真实诊断）；
4. evaluate_lesson 触发独立验收（你不能自评通过）；
5. 评估通过 → save_checkpoint → submit_task 进入下一任务；
6. 改坏了 → rollback_workspace 回到最近已验证状态重来。

## 铁律
- 只通过工具行动；修改走 apply_file_changes（原子、严格哈希）；
- 不得删除/弱化前序测试（Evaluator 会拒绝并回滚）；
- starter 挖空变更用 target="starter"（基线=参考版）；
- buildManifest.testNames 必须与 tests/CMakeLists.txt 注册一致；
- 完成当前任务后必须 submit_task（而不是继续改）；
- 预算由 Harness 控制，收到 budget-exceeded 反馈时立即收尾提交或说明。"""

# 预算（每任务 slice）
DEFAULT_BUDGET = {
    "maxRounds": 24,           # LLM 调用轮数（含评估后的 save/submit 收尾）
    "maxToolCalls": 60,        # 工具调用总数
    "maxTokens": 300_000,
    "maxSandboxRuns": 20,
    "maxConsecutiveNoProgress": 4,
}


@dataclass
class HarnessController:
    """一个会话 slice 的控制器（绑定 workspace 与 session 行）。"""

    db_factory: object = None
    session_id: object = None
    workspace: CourseWorkspace = None
    provider: object = None
    task_spec: dict = None
    milestone_title: str = ""
    prior_tests: list = None
    is_final: bool = False
    release_id: object = None
    generation_id: object = None
    task_seq: int = 0
    blueprint_hash: str = ""
    job_lease: tuple = None
    # 用量
    rounds: int = 0
    tool_calls: int = 0
    tokens: int = 0
    sandbox_runs: int = 0
    llm_messages: list = None
    last_feedback: dict = None
    last_evaluation: EvaluationReport = None
    timeline: list = None
    no_progress: int = 0
    completed: bool = False
    checkpoint_saved: bool = False

    # ---------------- 工具回调（ToolRegistry handler 目标） ----------------

    def record_sandbox_run(self) -> None:
        self.sandbox_runs += 1

    def evaluate_current(self) -> dict:
        material = self.workspace.material_dict()
        expected = (self.workspace.instructions or {}).get("expectedFiles") or []
        declared = set(self.workspace.starter_overlay)
        expected = [p for p in expected if p in declared] or sorted(declared)
        # 独立一致性 + 守卫（复用）
        from app.domains.course_generation.lessons.consistency_validator import (
            validate_material,
        )
        from app.domains.course_generation.verification.course_verifier import (
            guard_starter,
        )
        errors = validate_material(
            self.task_spec.get("taskId", ""), self.workspace.reference_files,
            {**self.workspace.reference_files, **self.workspace.starter_overlay},
            self.workspace.manifest,
            self.workspace.base_snapshot.get("referenceFiles", {}),
            expected)
        guard = guard_starter(material["starterFiles"], material["referenceFiles"],
                              material["testFiles"], "cpp", expected_files=expected)
        if errors or guard:
            self.last_evaluation = EvaluationReport(
                engineering="failed",
                problems=[f"{e.get('errorCode')}: {e.get('actual')}" for e in errors[:4]]
                + guard[:3])
        else:
            self.last_evaluation = evaluate_lesson(
                material, self.workspace.base_snapshot.get("referenceFiles", {}),
                self.prior_tests or [], self.is_final, stability_runs=2)
        self.last_feedback = self.last_evaluation.to_feedback()
        return {"independent": True, **self.last_feedback}

    def save_checkpoint(self) -> dict:
        if (self.last_evaluation is None
                or self.last_evaluation.engineering != "passed"):
            return {"ok": False,
                    "error": "拒绝保存：独立评估未通过（engineering != passed）。"
                             "先 evaluate_lesson 并修复失败。"}
        release_ref = self.release_id or self.generation_id  # 无 release 时挂 generation（可追溯）
        with self.db_factory() as db:
            _persist_checkpoint(
                db, release_ref, self.generation_id, self.task_seq,
                self.task_spec.get("taskId", ""), self.blueprint_hash,
                "cpp-changeset-v1", "projectweave-sandbox-cpp:clang15-bookworm",
                "", self.last_evaluation_reference_files(),
                self.registry_after_save(), self._artifact(),
                self._reference_delta(), self.last_evaluation.verifications,
                {"harness": True, "rounds": self.rounds,
                 "toolCalls": self.tool_calls, "tokens": self.tokens,
                 "sandboxRuns": self.sandbox_runs})
        self.checkpoint_saved = True
        return {"ok": True, "checkpoint": "verified",
                "note": "已固化（含稳定性）；可 submit_task 进入下一任务"}

    def rollback_to_checkpoint(self) -> dict:
        base = self.workspace.base_snapshot
        self.workspace = CourseWorkspace({
            "referenceFiles": base.get("referenceFiles", {}),
            "starterOverlay": base.get("starterOverlay", {}),
            "manifest": base.get("manifest", {}),
            "instructions": base.get("instructions", {}),
            "hints": base.get("hints", []),
            "revisions": [],
            "baseSnapshot": base,
        })
        self.workspace.revision = 0
        self.no_progress = 0
        return {"ok": True, "rolledBackTo": "last-verified-checkpoint",
                "revision": 0}

    def submit_task(self) -> dict:
        if not self.checkpoint_saved:
            result = self.save_checkpoint()
            if not result.get("ok"):
                return {"ok": False,
                        "error": "submit 拒绝：未保存 Verified Checkpoint（"
                                 + result.get("error", "") + ")"}
        self.completed = True
        return {"ok": True, "taskCompleted": True,
                "note": "任务通过独立验收并已固化；本 slice 结束"}

    # ---------------- Agent 循环（真实 function calling） ----------------

    def run(self) -> dict:
        registry = build_harness_tools(self.workspace, self)
        tools_schema = [
            {"type": "function",
             "function": {"name": spec.name, "description": spec.description,
                          "parameters": spec.parameters}}
            for name, spec in registry._tools.items()
        ]
        brief = json.dumps(self.task_spec, ensure_ascii=False)[:1200]
        system = AGENT_SYSTEM_PROMPT.format(
            task_brief=brief,
            prior_tests=", ".join(self.prior_tests or []) or "（首任务）",
            baseline_files=", ".join(
                sorted(self.workspace.base_snapshot.get("referenceFiles", {}))[:20])
            or "（空工程）",
        )
        self.llm_messages = self.llm_messages or [
            {"role": "system", "content": system},
            {"role": "user", "content":
                f"请开发任务 {self.task_spec.get('taskId')}："
                f"{self.task_spec.get('title', '')}。通过 evaluate_lesson 并"
                " save_checkpoint + submit_task 完成。"},
        ]
        budget = DEFAULT_BUDGET
        ctx = ToolContext(db=None, project_id=None)

        while not self.completed:
            if (self.rounds >= budget["maxRounds"]
                    or self.tool_calls >= budget["maxToolCalls"]
                    or self.tokens >= budget["maxTokens"]
                    or self.sandbox_runs >= budget["maxSandboxRuns"]):
                self._append_timeline("budget", ok=False,
                                      summary=f"slice 预算耗尽（rounds={self.rounds},"
                                              f" tools={self.tool_calls},"
                                              f" tokens={self.tokens},"
                                              f" sandbox={self.sandbox_runs}）——"
                                              "保存状态等待恢复")
                break
            self.rounds += 1
            result = self.provider.chat_with_tools(self.llm_messages, tools_schema)
            self.tokens += int(result.prompt_tokens or 0) + int(result.completion_tokens or 0)
            if not result.tool_calls:
                if result.content:
                    self.llm_messages.append(
                        {"role": "assistant", "content": result.content})
                    self.llm_messages.append({
                        "role": "user", "content":
                            "请继续用工具推进（完成需 evaluate→save_checkpoint→"
                            "submit_task）；不要只输出文本。"})
                    self.no_progress += 1
                    if self.no_progress >= budget["maxConsecutiveNoProgress"]:
                        break
                continue
            self.llm_messages.append({
                "role": "assistant", "content": result.content or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(
                                      c.get("arguments", {}), ensure_ascii=False)}}
                    for c in result.tool_calls]})
            for call in result.tool_calls:
                self.tool_calls += 1
                outcome = self._execute_tool(registry, ctx, call)
                self.llm_messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(outcome, ensure_ascii=False,
                                          default=str)[:TOOL_MSG_LIMIT]})
            if self.completed:
                break
        return self._slice_result()

    TOOL_MSG_LIMIT = 3500

    def _execute_tool(self, registry, ctx, call) -> dict:
        name = call.get("name", "")
        args = call.get("arguments") or {}
        try:
            spec = registry._tools.get(name)
            if spec is None:
                raise KeyError(name)
            outcome = spec.handler(ctx, **args)
            self._append_timeline("tool", tool=name, ok=True,
                                  args=_args_summary(args),
                                  summary=_outcome_summary(outcome))
            return outcome
        except Exception as exc:  # noqa: BLE001 —— 工具失败如实回填
            self._append_timeline("tool", tool=name, ok=False,
                                  args=_args_summary(args), error=str(exc)[:200])
            return {"error": f"工具执行失败：{exc}"}

    # ---------------- 内部 ----------------

    def last_evaluation_reference_files(self) -> dict:
        material = self.workspace.material_dict()
        # verify 返回的 reference_files = 参考工程 + 测试；这里以工作区参考为准
        return dict(self.workspace.reference_files)

    def registry_after_save(self) -> list:
        manifest_tests = self.workspace.manifest.get("testNames") or []
        return [*self.prior_tests, *[t for t in manifest_tests
                                     if t not in (self.prior_tests or [])]]

    def _artifact(self) -> dict:
        material = self.workspace.material_dict()
        return {
            "taskId": self.task_spec.get("taskId", ""),
            "milestoneId": self.task_spec.get("milestoneId", ""),
            "language": "cpp",
            "instructions": self.workspace.instructions or
                            {"title": self.task_spec.get("title", "")},
            "starterFiles": material["starterFiles"],
            "testFiles": material["testFiles"],
            "buildManifest": self.workspace.manifest,
            "hints": self.workspace.hints,
            "status": "tests-passed",
            "verifications": (self.last_evaluation.verifications
                              if self.last_evaluation else []),
            "repairs": [], "error": None,
            "generationModel": getattr(self.provider, "name", ""),
        }

    def _reference_delta(self) -> list:
        base = self.workspace.base_snapshot.get("referenceFiles", {})
        return [{"path": p, "content": c}
                for p, c in sorted(self.workspace.reference_files.items())
                if base.get(p) != c]

    def _append_timeline(self, kind, tool=None, ok=True, args=None,
                         summary=None, error=None) -> None:
        self.timeline.append({
            "seq": len(self.timeline) + 1, "at": utcnow().isoformat(),
            "kind": kind, "tool": tool, "ok": ok,
            "args": args or {}, "summary": (summary or "")[:300],
            "error": error,
        })

    def _slice_result(self) -> dict:
        return {
            "completed": self.completed,
            "checkpointSaved": self.checkpoint_saved,
            "rounds": self.rounds, "toolCalls": self.tool_calls,
            "tokens": self.tokens, "sandboxRuns": self.sandbox_runs,
            "workspaceRevision": self.workspace.revision,
            "workspace": self.workspace.to_dict(),
            "timeline": self.timeline,
            "lastFeedback": self.last_feedback or {},
            "messages": self.llm_messages,
        }


def _args_summary(args: dict) -> dict:
    out = {}
    for key, value in (args or {}).items():
        text = json.dumps(value, ensure_ascii=False, default=str)
        out[key] = text[:120] + ("…" if len(text) > 120 else "")
    return out


def _outcome_summary(outcome) -> str:
    if isinstance(outcome, dict):
        keys = ("status", "ok", "revision", "engineering", "error")
        return "; ".join(f"{k}={outcome[k]}" for k in keys if k in outcome) or \
            ",".join(list(outcome)[:4])
    return str(outcome)[:200]


TOOL_MSG_LIMIT = 3500
