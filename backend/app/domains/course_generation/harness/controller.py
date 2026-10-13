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
    eval_fingerprint: str = ""      # 最近评估绑定的工作区指纹（D49）
    resumed: bool = False           # 本 slice 是否从 Runtime 恢复
    acceptance: object = None       # 冻结验收契约（D49）
    final_phase: str = ""           # developing | repairing（D50）
    control_state: dict = None      # {pause_requested, cancel_requested}（D50）
    _control_reader: object = None
    # D51：工作记忆 / 循环检测 / 分层恢复
    memory: object = None
    loops: object = None
    recovery_level: int = 0          # 0 正常 | 1 提醒 | 2 重规划 | 3 上下文重置
    saved_checkpoint_fingerprint: str = ""  # D51：保存时指纹
    max_recovery: int = 3
    max_stagnation: int = 5          # 连续无进展轮数 → 恢复
    timeline: list = None
    no_progress: int = 0
    completed: bool = False
    checkpoint_saved: bool = False

    # ---------------- 工具回调（ToolRegistry handler 目标） ----------------

    def record_sandbox_run(self) -> None:
        self.sandbox_runs += 1

    # ---------------- Evaluation Fingerprint（D49） ----------------

    def evaluation_fingerprint(self) -> str:
        """当前工作区与验收契约的精确指纹（评估只能证明该指纹的版本）。"""
        from app.domains.course_generation.lessons.consistency_validator import (
            snapshot_hash_of,
        )

        def _hash(value) -> str:
            return snapshot_hash_of({"v": json.dumps(
                value, sort_keys=True, ensure_ascii=False, default=str)})

        payload = json.dumps({
            "taskId": self.task_spec.get("taskId", ""),
            "revision": self.workspace.revision,
            "referenceHash": snapshot_hash_of(self.workspace.reference_files),
            "starterHash": snapshot_hash_of(self.workspace.starter_overlay),
            "manifestHash": _hash(self.workspace.manifest),
            "instructionsHash": _hash(self.workspace.instructions),
            "hintsHash": _hash(self.workspace.hints),
            "priorTests": sorted(self.prior_tests or []),
            "baseHash": snapshot_hash_of(
                self.workspace.base_snapshot.get("referenceFiles", {})),
            "blueprintHash": self.blueprint_hash,
            "acceptanceHash": (self.acceptance.contract_hash()
                               if self.acceptance else ""),
            "evaluationVersion": "harness-eval-v1",
        }, sort_keys=True, ensure_ascii=False)
        return snapshot_hash_of({"fingerprint": payload})

    def _invalidate_evaluation(self, reason: str) -> None:
        """任何工作区/材料修改后：旧评估立即失效（Stale）。"""
        if self.last_evaluation is not None:
            self.last_evaluation = None
            self.eval_fingerprint = ""
            self.last_feedback = {
                "evaluation": {"engineering": "stale",
                               "pedagogy": "stale",
                               "stability": "stale"},
                "staleReason": reason,
                "note": "工作区已修改——需重新 evaluate_lesson",
            }

    def _control_check(self) -> str:
        """D50 Cooperative Cancellation：查询服务端控制状态。

        返回 "continue" | "paused" | "cancelled"。LLM 调用前、工具执行前、
        Checkpoint/发布前由 run 循环调用。每次实时读 DB（不缓存）。
        """
        reader = getattr(self, "_control_reader", None)
        state = reader() if reader else self.control_state
        if state is None:
            return "continue"
        if state.get("cancel_requested"):
            return "cancelled"
        if state.get("pause_requested"):
            return "paused"
        return "continue"

    def _persist_repair_checkpoint(self) -> None:
        """Final Repair 成果持久化：追加修复检查点（旧检查点不变）。

        task_id = 原最后任务 + "-final"，task_seq 保持最后任务序——
        发布按 task_id 集合匹配 blueprint（-final 不入学生任务）。
        """
        last_task = (self.workspace.base_snapshot.get("testOrder") or [])
        repair_id = "__final_repair__"
        with self.db_factory() as db:
            from app.domains.course_generation.models import CourseCheckpoint

            # 清理旧修复条目（同 task_id 只留最新）
            olds = db.scalars(
                __import__("sqlalchemy").select(CourseCheckpoint).where(
                    CourseCheckpoint.generation_id == self.generation_id,
                    CourseCheckpoint.task_id == repair_id))
            for old in olds:
                db.delete(old)
            manifest = dict(self.workspace.manifest or {})
            manifest.setdefault("testNames",
                                list(self.prior_tests or []))
            db.add(CourseCheckpoint(
                release_id=self.release_id,
                generation_id=self.generation_id,
                task_seq=len(last_task),
                task_id=repair_id,
                blueprint_hash=self.blueprint_hash,
                protocol_version="cpp-changeset-v1",
                sandbox_image="projectweave-sandbox-cpp:clang15-bookworm",
                snapshot_files=dict(self.workspace.reference_files),
                task_spec_hash="",
                prev_snapshot_hash="",
                test_registry=list(self.prior_tests or []),
                artifact={
                    "taskId": repair_id, "milestoneId": "", "language": "cpp",
                    "instructions": self.workspace.instructions or {},
                    "starterFiles": [], "testFiles": [],
                    "buildManifest": manifest, "hints": [],
                    "status": "tests-passed",
                    "verifications": (self.last_evaluation.verifications
                                      if self.last_evaluation else []),
                    "repairs": [], "error": None,
                },
                reference_delta=[],
                verification_evidence=(self.last_evaluation.verifications
                                      if self.last_evaluation else []),
                diagnostics={"harness": "final-repair", "phase": "repairing"},
            ))
            db.commit()

    def _session_lease_valid(self) -> bool:
        """会话租约校验（CourseDevSession 行，非 GenerationJob）。"""
        if self.job_lease is None:
            return True  # 测试直连（无租约）路径
        session_row_id, token = self.job_lease
        from datetime import datetime, timezone

        from app.domains.course_generation.harness.models import CourseDevSession

        try:
            with self.db_factory() as db:
                row = db.get(CourseDevSession, session_row_id)
                if row is None or row.lease_token != token:
                    return False
                if row.cancel_requested or row.state not in ("developing", "paused"):
                    return row.state == "developing" and not row.cancel_requested
                return True
        except Exception:
            return False

    def invalidate_evaluation_after_change(self) -> None:
        """工具回调：apply/update 成功后由 tools.py 调用。"""
        self._invalidate_evaluation("工作区文件/材料修改")

    def init_memory(self) -> None:
        from app.domains.course_generation.harness.memory import (
            LoopDetector,
            WorkingMemory,
        )

        self.memory = WorkingMemory(
            task_id=self.task_spec.get("taskId", ""),
            goal=self.task_spec.get("title", ""),
            workspace_revision=self.workspace.revision)
        self.loops = LoopDetector()

    def load_memory(self, data: dict) -> None:
        from app.domains.course_generation.harness.memory import LoopDetector

        self.init_memory()
        if data:
            from app.domains.course_generation.harness.memory import WorkingMemory

            self.memory = WorkingMemory.from_dict(data)
            self.memory.workspace_revision = self.workspace.revision
        self.loops = LoopDetector()

    def init_acceptance_contract(self, task_spec: dict,
                                 prior_tests: list[str]) -> None:
        """任务开始时冻结验收契约（Agent 不可修改）。"""
        from app.domains.course_generation.harness.acceptance import (
            build_acceptance_contract,
        )

        self.acceptance = build_acceptance_contract(task_spec, prior_tests)

    def validate_manifest_update(self, new_manifest: dict) -> list[str]:
        """update_course_material 的 manifest 变更不得降低冻结契约。"""
        if self.acceptance is None:
            return []
        from app.domains.course_generation.harness.acceptance import (
            validate_manifest_against_contract,
        )

        return validate_manifest_against_contract(
            self.acceptance, new_manifest, self.workspace.manifest)

    def evaluate_current(self) -> dict:
        material = self.workspace.material_dict()
        expected = (self.workspace.instructions or {}).get("expectedFiles") or []
        declared = set(self.workspace.starter_overlay)
        expected = [p for p in expected if p in declared] or sorted(declared)
        # D50：把权威 expectedFiles 注入材料（下游 verify/守卫同源判定，
        # 避免空 instructions 时退化为全工程启发式泄露误报）
        if not (self.workspace.instructions or {}).get("expectedFiles"):
            self.workspace.instructions = {
                **(self.workspace.instructions or {}),
                "expectedFiles": expected,
                "title": (self.workspace.instructions or {}).get(
                    "title", self.task_spec.get("title", "任务"))}
            material["instructions"] = dict(self.workspace.instructions)
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
        if self.last_evaluation is not None and self.last_evaluation.engineering == "passed":
            self.memory.rounds_since_progress = 0
            self.memory.last_progress = "evaluate_lesson 通过（engineering=passed）"
            if "评估通过" not in self.memory.completed_steps:
                self.memory.completed_steps.append("评估通过")
        self.last_feedback = (self.last_evaluation.to_feedback()
                              if self.last_evaluation else self.last_feedback)
        # Fingerprint 绑定：本次评估只证明这个精确版本（D49）
        self.eval_fingerprint = self.evaluation_fingerprint()
        self.last_feedback["fingerprint"] = self.eval_fingerprint
        return {"independent": True, **self.last_feedback}

    def save_checkpoint(self) -> dict:
        # Verified Checkpoint Policy（D49）：engineering + stability + pedagogy
        # 确定性部分全部通过 + Fingerprint 与当前工作区一致 + Lease 有效
        if (self.last_evaluation is None
                or self.last_evaluation.engineering != "passed"):
            return {"ok": False,
                    "error": "拒绝保存：独立评估未通过（engineering != passed）。"
                             "先 evaluate_lesson 并修复失败。"}
        if self.last_evaluation.stability not in ("passed", "not-evaluated"):
            return {"ok": False,
                    "error": "拒绝保存：实验稳定性未通过"
                             f"（{self.last_evaluation.stability}）——重复沙箱结果不稳定"}
        if self.last_evaluation.pedagogy == "failed":
            return {"ok": False,
                    "error": "拒绝保存：教学约束未通过（starter 预期失败等）"}
        current_fp = self.evaluation_fingerprint()
        if self.eval_fingerprint and current_fp != self.eval_fingerprint:
            return {"ok": False,
                    "error": "拒绝保存：评估后工作区已修改（Fingerprint 不匹配）——"
                             "必须重新 evaluate_lesson。"}
        if not self._session_lease_valid():
            return {"ok": False,
                    "error": "拒绝保存：会话租约已失效（被接管/过期），本 worker 停止写入"}
        # D51 Checkpoint 版本绑定：记录保存时指纹（后续修改 → submit 拒绝）
        self.saved_checkpoint_fingerprint = current_fp
        release_ref = self.release_id  # 开发中允许 NULL（D49 外键语义修复）
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
        self._invalidate_evaluation("回滚到已验证基线")
        return {"ok": True, "rolledBackTo": "last-verified-checkpoint",
                "revision": 0}

    def submit_task(self) -> dict:
        if not self.checkpoint_saved:
            result = self.save_checkpoint()
            if not result.get("ok"):
                return {"ok": False,
                        "error": "submit 拒绝：未保存 Verified Checkpoint（"
                                 + result.get("error", "") + ")"}
        # D51 Checkpoint 版本绑定：保存后若工作区再修改 → submit 拒绝
        saved_fp = getattr(self, "saved_checkpoint_fingerprint", "")
        if saved_fp and self.evaluation_fingerprint() != saved_fp:
            return {"ok": False,
                    "error": "submit 拒绝：Checkpoint 保存后工作区已被修改"
                             "（Fingerprint 不匹配）——重新 evaluate_lesson 并"
                             " save_checkpoint，或 rollback_workspace 回到检查点"}
        # D51 Final Repair：修复提交时保存修复快照为新的 Verified 检查点
        if self.final_phase == "repairing":
            self._persist_repair_checkpoint()
        self.completed = True
        return {"ok": True, "taskCompleted": True,
                "note": "任务通过独立验收并已固化；本 slice 结束"}

    # ---------------- Agent 循环（真实 function calling） ----------------

    def load_runtime(self, snapshot: dict) -> bool:
        """从 Runtime Snapshot 恢复未完成工作区与 Agent 上下文（D49）。

        兼容校验：任务/蓝图哈希/基线哈希/协议版本任一不匹配即拒绝恢复
        （返回 False——调用方从头初始化，不静默覆盖已保存工作）。
        """
        if not snapshot or snapshot.get("protocolVersion") != "harness-runtime-v1":
            return False
        if snapshot.get("taskId") != self.task_spec.get("taskId", ""):
            return False
        if snapshot.get("blueprintHash") != self.blueprint_hash:
            return False
        if snapshot.get("baseSnapshotHash") != self._base_hash():
            return False
        ws = snapshot.get("workspace") or {}
        if not ws.get("referenceFiles") and not ws.get("starterOverlay"):
            return False
        self.workspace = CourseWorkspace(ws)
        self.llm_messages = list(snapshot.get("agentMessages") or [])
        self.last_feedback = dict(snapshot.get("lastEvaluation") or {})
        self.eval_fingerprint = snapshot.get("lastFingerprint") or ""
        self.checkpoint_saved = bool(snapshot.get("checkpointSaved"))
        self.load_memory(snapshot.get("workingMemory") or {})
        self.memory.workspace_revision = self.workspace.revision
        self.resumed = True
        return True

    @staticmethod
    def _sanitize_messages(messages: list) -> list:
        """保证消息历史对 DeepSeek 合法（D50）。

        每条含 tool_calls 的 assistant 消息后必须紧跟对应的 tool 响应；
        slice 中断（暂停/预算）可能留下孤儿 tool_calls——补一个
        "执行被中断" 的 tool 响应使其合法，否则 API 400。
        """
        out = []
        for message in messages:
            out.append(message)
            if message.get("role") == "assistant" and message.get("tool_calls"):
                emitted = set()
                for call in message["tool_calls"]:
                    cid = call.get("id") if isinstance(call, dict) else call[                         "function"]["id"]
                    emitted.add(cid)
                # 扫描后续是否已有响应（在原 messages 中）
        # 简化两遍法：重建序列
        result = []
        i = 0
        msgs = list(messages)
        while i < len(msgs):
            message = msgs[i]
            result.append(message)
            if message.get("role") == "assistant" and message.get("tool_calls"):
                expected = {c.get("id") for c in message["tool_calls"]
                            if isinstance(c, dict)}
                answered = set()
                j = i + 1
                while j < len(msgs) and msgs[j].get("role") == "tool":
                    answered.add(msgs[j].get("tool_call_id"))
                    result.append(msgs[j])
                    j += 1
                missing = expected - answered
                for cid in sorted(missing):
                    result.append({
                        "role": "tool", "tool_call_id": cid,
                        "content": '{"interrupted": true, '
                                   '"note": "该工具调用被暂停/预算中断，未执行"}'})
                i = j
            else:
                i += 1
        # 尾部孤儿 tool 消息（无前导 tool_calls）删除
        cleaned = []
        pending_ids = set()
        for message in result:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                pending_ids = {c.get("id") for c in message["tool_calls"]}
                cleaned.append(message)
            elif message.get("role") == "tool":
                if message.get("tool_call_id") in pending_ids:
                    cleaned.append(message)
                    pending_ids.discard(message.get("tool_call_id"))
                # 孤儿 tool（无对应 tool_calls）丢弃
            else:
                if message.get("role") == "assistant" and not message.get("tool_calls")                         and message.get("content") is None:
                    continue  # 空 assistant 跳过
                cleaned.append(message)
        return cleaned

    def _inject_memory_system(self) -> None:
        """把工作记忆注入 system 消息末尾（Layer 1 固定约束之上）。"""
        if self.memory is None:
            return
        summary = self.memory.summary_prompt()
        system = next((m for m in self.llm_messages
                       if m.get("role") == "system"), None)
        if system is None:
            return
        marker = "\n## 工作记忆"
        base = system["content"].split(marker)[0]
        system["content"] = base + marker + "（Harness 维护，可验证事实）\n" \
            + summary.split("\n", 1)[1] if "\n" in summary else base + summary

    def _compact_context(self) -> None:
        """D51 上下文压缩：保留 system + 最近工具交互边界内的消息。

        只在完整工具交互边界截断（不切断 tool_calls 配对）；压缩计数真实记录。
        """
        keep_tail = 16
        system = [m for m in self.llm_messages if m.get("role") == "system"]
        rest = [m for m in self.llm_messages if m.get("role") != "system"]
        if len(rest) <= keep_tail:
            return
        tail = rest[-keep_tail:]
        # 边界校正：tail 开头若是 tool 响应，向后丢到 assistant 边界
        while tail and tail[0].get("role") == "tool":
            tail.pop(0)
        summary_note = {
            "role": "user", "content":
                "（上下文已压缩）此前较旧的工具交互已汇总进工作记忆。"
                "已读取文件清单/已修改文件/已知问题见 system 工作记忆部分——"
                "不要重复读取相同版本的文件。",
        }
        self.llm_messages = [*system, summary_note, *tail]
        self.llm_messages = self._sanitize_messages(self.llm_messages)
        if self.memory:
            self.memory.stats["compactions"] += 1
        self._append_timeline("context-compaction", ok=True,
                              summary=f"上下文压缩（保留尾部 {len(tail)} 条）")

    def _run_recovery(self) -> None:
        """D51 分层恢复：1 提醒 → 2 重规划注入 → 3 上下文重置 → 停止。"""
        self.recovery_level += 1
        if self.memory:
            self.memory.stats["recoveries"] += 1
        self.memory.rounds_since_progress = 0  # 本轮重置（防每轮触发）
        level = self.recovery_level
        self._append_timeline("recovery", ok=True,
                              summary=f"停滞恢复 Level {level}")
        if level == 1:
            self.llm_messages.append({
                "role": "user", "content":
                    "检测到你连续多轮没有产生有效进展（可能重复读取了相同文件）。"
                    "请查看 system 中的工作记忆：已读取文件无需重复读取；"
                    "直接选择能推进任务的下一步（apply_file_changes / cmake_build /"
                    " run_ctest / evaluate_lesson）。路径参数不要加引号。"})
        elif level == 2:
            plan = self._build_recovery_plan()
            self.llm_messages.append({
                "role": "user", "content":
                    "你已多次停滞。Harness 重新规划如下（基于真实工作记忆）：\n"
                    + json.dumps(plan, ensure_ascii=False, indent=1)
                    + "\n请按 firstAction 开始执行，不要再次读取已列出的文件。"})
        else:
            self._compact_context()

    def _build_recovery_plan(self) -> dict:
        """从 Task Spec + Working Memory + 真实 Workspace 构建恢复计划。"""
        memory = self.memory.to_dict() if self.memory else {}
        next_steps = []
        if not memory.get("modifiedFiles"):
            next_steps.append("用 apply_file_changes 创建/修改本任务核心文件")
        next_steps.extend(["cmake_build 验证构建", "run_ctest 验证测试",
                           "evaluate_lesson 独立评估",
                           "save_checkpoint + submit_task"])
        first = "apply_file_changes" if not memory.get("modifiedFiles") \
            else "cmake_build"
        return {
            "reason": "stagnation-loop",
            "taskId": self.task_spec.get("taskId", ""),
            "goal": self.task_spec.get("title", ""),
            "knownState": {
                "workspaceRevision": self.workspace.revision,
                "alreadyReadFiles": [f["path"] for f in
                                     memory.get("inspectedFiles", [])][:10],
                "modifiedFiles": memory.get("modifiedFiles", []),
                "knownProblems": memory.get("knownProblems", []),
            },
            "nextSteps": next_steps,
            "firstAction": first,
        }

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
        # D50：恢复/中断后的消息清洗（孤儿 tool_calls 补响应）
        self.llm_messages = self._sanitize_messages(self.llm_messages)
        # D51：兜底初始化（service 正常构建；测试直连保护）
        if self.memory is None:
            self.init_memory()
        # D51：恢复时压缩旧消息（避免重新灌入几十轮重复读取历史）
        if self.resumed and len(self.llm_messages) > 24:
            self._compact_context()
        self._inject_memory_system()
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
            # D50：LLM 调用前检查控制状态（暂停/取消真正中断）
            control = self._control_check()
            if control == "cancelled":
                self._append_timeline("cancelled", ok=False,
                                      summary="用户取消——循环终止")
                break
            if control == "paused":
                self._append_timeline("paused", ok=False,
                                      summary="用户暂停——循环在安全边界停止")
                break
            # D51：停滞检测——连续 max_stagnation 轮无有效进展 → 分层恢复
            self.memory.rounds_since_progress += 1
            self.memory.workspace_revision = self.workspace.revision
            if self.memory.rounds_since_progress >= self.max_stagnation:
                self._run_recovery()
                if self.recovery_level > self.max_recovery:
                    self._append_timeline(
                        "stalled", ok=False,
                        summary=f"停滞且恢复 {self.recovery_level} 次未收敛——"
                                "受控暂停（保存状态与诊断）")
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
                # D50：每个工具执行前检查（耗时沙箱前同样生效）
                control = self._control_check()
                if control in ("cancelled", "paused"):
                    self._append_timeline(control, ok=False,
                                          summary=f"用户{control}——跳过工具 "
                                                  f"{call.get('name', '')}")
                    break
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
            # Runtime Snapshot（D49）：未完成任务的完整恢复载荷
            "runtimeSnapshot": {
                "taskId": self.task_spec.get("taskId", ""),
                "blueprintHash": self.blueprint_hash,
                "baseSnapshotHash": self._base_hash(),
                "workspaceRevision": self.workspace.revision,
                "workspace": self.workspace.to_dict(),
                "agentMessages": self._sanitize_messages(
                    (self.llm_messages or [])[-24:]),
                "workingMemory": (self.memory.to_dict()
                                  if self.memory else None),
                "lastEvaluation": (self.last_feedback or {}),
                "lastFingerprint": self.eval_fingerprint,
                "consumedTokens": self.tokens,
                "sandboxRuns": self.sandbox_runs,
                "checkpointSaved": self.checkpoint_saved,
                "protocolVersion": "harness-runtime-v1",
            },
        }

    def _base_hash(self) -> str:
        from app.domains.course_generation.lessons.consistency_validator import (
            snapshot_hash_of,
        )

        return snapshot_hash_of(
            self.workspace.base_snapshot.get("referenceFiles", {}))


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
