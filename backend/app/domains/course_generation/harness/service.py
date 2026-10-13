"""Session 服务（P8.2.3，D48）：生命周期 + 租约 + 后台执行。

状态机（服务端权威）：pending → developing → (paused ⇄ developing) →
completed | failed | cancelled。复用 D47 租约语义（原子抢占/续租/提交前校验）。
"""

from __future__ import annotations

import json
import threading
import uuid as _uuid

from sqlalchemy import select

from app.domains.course_generation.harness.controller import HarnessController
from app.domains.course_generation.harness.models import CourseDevSession
from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.lesson_publisher import (
    ReleaseError,
    _lease_renew,
    _lease_valid,
    _session,
    utcnow,
)

LEASE_SECONDS = 3600

_session_factory = None
_provider_factory = None


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def set_provider_factory(factory) -> None:
    global _provider_factory
    _provider_factory = factory


def _db():
    if _session_factory is not None:
        return _session_factory()
    from app.core.db import SessionLocal

    return SessionLocal()


def _provider():
    if _provider_factory is not None:
        return _provider_factory()
    from app.ai.provider import get_provider

    return get_provider()


class HarnessSessionError(Exception):
    def __init__(self, message: str, status: int = 422):
        self.status = status
        super().__init__(message)


# ---------------------------------------------------------------- 创建/查询


def start_session(db, generation_id, release_id=None) -> CourseDevSession:
    """创建开发会话：从 generation 蓝图 + 兼容 Checkpoint 初始化任务序列。"""
    from app.domains.course_generation.models import CourseGeneration

    gen = db.get(CourseGeneration, _uuid.UUID(str(generation_id)))
    if gen is None or not gen.blueprint:
        raise HarnessSessionError("生成任务或蓝图不存在", 404)
    from app.domains.course_generation.execution_profile import (
        derive_execution_profile,
    )

    profile = derive_execution_profile(gen.blueprint)
    if profile["primaryLanguage"] != "cpp":
        raise HarnessSessionError("Harness 当前仅支持 C++/CMake 课程", 422)

    from app.domains.course_generation.lessons.lesson_publisher import (
        _normalize_blueprint,
        _task_order,
    )
    from app.domains.course_generation.generation.task_refinement import (
        refine_blueprint,
    )

    refinement = refine_blueprint(gen.blueprint)
    blueprint = refinement.blueprint if refinement.refined else gen.blueprint
    order = _task_order(_normalize_blueprint(blueprint))

    normalized = _normalize_blueprint(blueprint)
    # 已有兼容 Checkpoint 的连续前缀 → 直接标记完成（resume 零 LLM 复用）
    from app.domains.course_generation.lessons.change_set import CHANGESET_PROTOCOL
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )
    from app.domains.course_generation.lessons.lesson_publisher import (
        load_compatible_checkpoints,
    )
    seed_hash = _harness_blueprint_hash({
        "tasks": normalized.get("tasks") or [],
        "milestones": normalized.get("milestones") or []})
    existing = load_compatible_checkpoints(
        gen.id, seed_hash, CHANGESET_PROTOCOL,
        "projectweave-sandbox-cpp:clang15-bookworm", "")
    done_prefix = []
    for tid in [t["taskId"] for t in normalized.get("tasks") or []]:
        if tid in existing:
            done_prefix.append(tid)
        else:
            break

    session = CourseDevSession(
        generation_id=gen.id,
        release_id=_uuid.UUID(str(release_id)) if release_id else None,
        state="pending",
        agent_model="",
        blueprint_revision=1 if refinement.refined else 0,
        workspace={"taskOrder": [t["taskId"] for t in order],
                   "tasks": normalized.get("tasks") or [],
                   "milestones": normalized.get("milestones") or [],
                   "project": normalized.get("project") or {},
                   "completedTaskIds": done_prefix,
                   "refinementMappings": [
                       {"originalTaskId": m.original_task_id,
                        "newTaskIds": list(m.new_task_ids), "reason": m.reason}
                       for m in refinement.mappings]},
        budget={"totalTokens": 2_000_000, "totalSandboxRuns": 120,
                "maxSlices": 40},
        token_usage={"prompt": 0, "completion": 0},
        sandbox_usage={"runs": 0},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db, session_id) -> CourseDevSession:
    row = db.get(CourseDevSession, _uuid.UUID(str(session_id)))
    if row is None:
        raise HarnessSessionError("会话不存在", 404)
    return row


def session_status(db, session_id) -> dict:
    row = get_session(db, session_id)
    return {
        "sessionId": str(row.id), "state": row.state,
        "currentTaskId": row.current_task_id,
        "workspaceRevision": row.workspace_revision,
        "toolCallCount": row.tool_call_count,
        "evaluationCount": row.evaluation_count,
        "tokenUsage": row.token_usage, "sandboxUsage": row.sandbox_usage,
        "budget": row.budget, "lastFeedback": row.last_feedback,
        "timeline": (row.timeline or [])[-40:],
        "error": row.error,
        "completedTaskIds": (row.workspace or {}).get("completedTaskIds") or [],
        "publishedReleaseId": (row.workspace or {}).get("publishedReleaseId"),
        "publishFailure": (row.workspace or {}).get("publishFailure"),
    }


# ---------------------------------------------------------------- 控制


def pause_session(db, session_id) -> dict:
    row = get_session(db, session_id)
    if row.state in ("completed", "cancelled"):
        raise HarnessSessionError(f"会话已 {row.state}，无法暂停", 422)
    # D50：设置持久化标志——正在执行的 worker 在下一个 LLM/工具边界
    # 实时读取并停止（Cooperative Pause）；空闲会话直接 paused
    row.pause_requested = True
    if row.state not in ("developing", "final-repairing"):
        row.state = "paused"
    db.commit()
    return {"state": row.state, "pauseRequested": True}


def cancel_session(db, session_id) -> dict:
    row = get_session(db, session_id)
    if row.state != "cancelled":
        row.cancel_requested = True
        row.state = "cancelled"
        db.commit()
    return {"state": "cancelled"}


def _claim_session_lease(session_id) -> tuple | None:
    """原子抢占会话租约（复用 D47 行锁语义）。"""
    from datetime import timedelta

    from sqlalchemy import update as _update

    token = _uuid.uuid4().hex
    now = utcnow()
    with _db() as db:
        row = db.get(CourseDevSession, session_id,
                     with_for_update=True)
        if row is None:
            return None
        from app.domains.course_generation.lessons.lesson_publisher import _aware

        expired = (_aware(row.lease_expires_at) is None
                   or _aware(row.lease_expires_at) < now)
        if row.state == "developing" and not expired and row.lease_token:
            db.rollback()
            return None
        row.lease_token = token
        row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        row.state = "developing"
        db.commit()
        return row.id, token


# ---------------------------------------------------------------- 执行 slice


def run_slice(session_id) -> dict:
    """执行一个开发 slice（当前任务直到完成/预算/暂停）。"""
    lease = _claim_session_lease(session_id)
    if lease is None:
        raise HarnessSessionError("会话正在被其他 worker 执行", 409)
    with _db() as db:
        row = db.get(CourseDevSession, session_id)
        if row.cancel_requested:
            row.state = "cancelled"
            db.commit()
            return {"state": "cancelled"}
        controller = _build_controller(row, lease)
        row.state = "developing"
        db.commit()

    # D49 双层预算：会话总 Token 上限（跨 slice 累计不重置）
    with _db() as db:
        row = db.get(CourseDevSession, session_id)
        usage = row.token_usage or {}
        budget = row.budget or {}
        if (usage.get("totalTokens") or 0) >= budget.get("totalTokens", 2_000_000):
            row.state = "paused"
            row.error = "会话总 Token 预算耗尽（提高预算后可 resume）"
            db.commit()
            return {"state": "paused", "completed": False, "rounds": 0,
                    "toolCalls": 0, "tokens": 0, "sandboxRuns": 0,
                    "workspaceRevision": row.workspace_revision,
                    "timeline": []}

    result = controller.run()

    with _db() as db:
        row = db.get(CourseDevSession, session_id)
        if row.cancel_requested:
            row.state = "cancelled"
        elif result["completed"] and row.state == "final-repairing":
            # D50：修复完成 → 保存修复快照为新检查点（不改旧）→ 重发
            republish = _republish_after_repair(db, row)
            if republish.get("ok"):
                row.state = "completed"
                row.release_id = _uuid.UUID(republish["releaseId"])
                row.error = None
                row.workspace["publishedReleaseId"] = republish["releaseId"]
            else:
                error = republish.get("error", "")
                row.workspace["publishFailure"] = error[:600]
                if _classify_publish_failure(error) == "infrastructure":
                    row.state = "paused"
                    row.error = "重发基础设施失败：" + error[:300]
                else:
                    row.state = "final-repairing"
                    row.error = "修复后仍未通过：" + error[:300]
        elif result["completed"]:
            _advance_or_complete(db, row, result)
        else:
            row.state = "paused"
            row.error = "slice 预算耗尽（可 resume 继续）"
        row.workspace = _merge_workspace(row, result)
        # Runtime Snapshot 持久化（未完成任务可原样恢复；完成时清除）
        row.workspace["runtimeSnapshot"] = (
            result.get("runtimeSnapshot") if not result["completed"] else None)
        row.workspace_revision = result["workspaceRevision"]
        row.tool_call_count += result["toolCalls"]
        row.evaluation_count += 1 if result.get("lastFeedback") else 0
        usage = row.token_usage or {}
        row.token_usage = {**usage, "slices": (usage.get("slices") or 0) + 1,
                           "lastSliceTokens": result["tokens"],
                           "totalTokens": (usage.get("totalTokens") or 0) + result["tokens"]}
        sandbox = row.sandbox_usage or {}
        row.sandbox_usage = {**sandbox,
                             "runs": (sandbox.get("runs") or 0) + result["sandboxRuns"]}
        row.last_feedback = result.get("lastFeedback") or {}
        row.timeline = (row.timeline or []) + result["timeline"]
        row.updated_at = utcnow()
        # D50：控制标志收敛（worker 已停 → paused / cancelled）
        if row.pause_requested and row.state not in ("completed",):
            row.state = "paused"
            row.pause_requested = False
        if row.cancel_requested:
            row.state = "cancelled"
        db.commit()
        return {
            "state": row.state, "completed": result["completed"],
            "rounds": result["rounds"], "toolCalls": result["toolCalls"],
            "tokens": result["tokens"], "sandboxRuns": result["sandboxRuns"],
            "workspaceRevision": result["workspaceRevision"],
            "timeline": result["timeline"],
        }


def _build_controller(row: CourseDevSession, lease: tuple) -> HarnessController:
    """从会话行构建控制器（含 Checkpoint 基线恢复）。"""
    ws_data = row.workspace or {}
    task_order = ws_data.get("taskOrder") or []
    tasks = {t["taskId"]: t for t in ws_data.get("tasks") or []}
    prior_done = ws_data.get("completedTaskIds") or []
    next_task = next((tid for tid in task_order if tid not in prior_done), None)
    if next_task is None:
        # D50：全部任务完成但发布未成功 → Final Repair（修复死状态）：
        # 基于最后 Verified Checkpoint 构建修复工作区（不报 422）
        return _build_final_repair_controller(row, lease)
    task_spec = tasks.get(next_task) or {"taskId": next_task, "title": next_task}

    # 从兼容 Checkpoint 恢复基线
    from app.domains.course_generation.lessons.change_set import CHANGESET_PROTOCOL
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )
    from app.domains.course_generation.lessons.lesson_publisher import (
        load_compatible_checkpoints,
    )
    # 统一哈希入口（与测试/服务一致的键序与结构）
    blueprint_hash = _harness_blueprint_hash(ws_data)
    checkpoints = load_compatible_checkpoints(
        row.generation_id, blueprint_hash, CHANGESET_PROTOCOL,
        "projectweave-sandbox-cpp:clang15-bookworm", "")
    prior_tests: list[str] = []
    base_files: dict[str, str] = {}
    for tid in task_order:
        if tid in prior_done and tid in checkpoints:
            prior_tests = checkpoints[tid]["test_registry"]
            base_files = checkpoints[tid]["snapshot_files"]
    if prior_done and not base_files:
        # 无兼容检查点但有已完成记录（蓝图变更）：重新从头（如实降级）
        prior_done = []
        ws_data["completedTaskIds"] = []

    row.current_task_id = next_task
    row.current_task_seq = task_order.index(next_task)

    workspace = CourseWorkspace({
        "referenceFiles": base_files,
        "starterOverlay": {},
        "manifest": {}, "instructions": {}, "hints": [],
        "revisions": [],
        "baseSnapshot": {
            "referenceFiles": base_files, "starterOverlay": {},
            "manifest": {}, "instructions": {}, "hints": [],
            "taskOrder": task_order, "completedTaskIds": prior_done,
            "priorTests": prior_tests, "blueprintHash": blueprint_hash,
        },
    })
    milestones = {m["milestoneId"]: m["title"]
                  for m in ws_data.get("milestones") or []}

    controller = HarnessController(
        db_factory=_db, session_id=row.id, workspace=workspace,
        provider=_provider(), task_spec=task_spec,
        milestone_title=milestones.get(task_spec.get("milestoneId", ""), ""),
        prior_tests=prior_tests,
        is_final=task_order.index(next_task) == len(task_order) - 1,
        release_id=row.release_id, generation_id=row.generation_id,
        task_seq=row.current_task_seq, blueprint_hash=blueprint_hash,
        job_lease=lease,
        timeline=[],
    )
    # D49：冻结验收契约（任务开始时固化；Resume 后保持同一契约）
    controller.init_acceptance_contract(task_spec, prior_tests)
    # D50：注入控制状态读取器（每轮实时查 DB——Pause/Cancel 真正中断循环）
    session_id_ref = row.id

    def _read_control():
        with _db() as cdb:
            fresh = cdb.get(CourseDevSession, session_id_ref)
            if fresh is None:
                return {"pause_requested": True, "cancel_requested": True}
            return {"pause_requested": bool(fresh.pause_requested or False),
                    "cancel_requested": bool(fresh.cancel_requested or False)}
    controller.control_state = _read_control()  # 初始快照
    controller._control_reader = _read_control
    # D49 Resume：同任务/同蓝图/同基线的 Runtime Snapshot → 原样恢复
    runtime = (row.workspace or {}).get("runtimeSnapshot")
    resumed = bool(runtime) and controller.load_runtime(runtime)
    row.workspace = {**(row.workspace or {}), "runtimeResumed": resumed}
    return controller


# ---------------------------------------------------------------- Final 阶段（D50）

# 失败分类：只有源代码/课程材料错误才交给 Agent 修复
FINAL_FAILURE_CLASSES = {
    "engineering": "final-repairing",        # 编译/链接/测试/Demo 失败 → Agent 修
    "contract": "final-repairing",           # 课程契约（artifact/测试注册）→ Agent 修
    "infrastructure": "paused",              # 数据库/租约/沙箱不可用 → 等待恢复
}


def _republish_after_repair(db, row: CourseDevSession) -> dict:
    """Final Repair 完成：以修复工作区保存新 Verified Checkpoint 并重发。

    不篡改旧 Checkpoint——追加修复检查点（task_id 加 -repair 后缀，task_seq
    不变会与原重复 → 用 task_seq=len(order)+repair 计数）。旧链保持。
    """
    ws = row.workspace or {}
    runtime = ws.get("runtimeSnapshot") or {}
    files = (runtime.get("workspace") or {}).get("referenceFiles") or {}
    if not files:
        # submit 前已有 checkpoint_saved → controller 内部已保存
        pass
    return _publish_release(db, row)


def _classify_publish_failure(error: str) -> str:
    infra_keys = ("数据库", "租约", "lease", "Docker 不可达", "沙箱不可用",
                  "IntegrityError", "OperationalError", "timeout")
    if any(k in error for k in infra_keys):
        return "infrastructure"
    return "engineering"


def _build_final_repair_controller(row: CourseDevSession, lease: tuple):
    """发布失败后的修复控制器：基线 = 最后 Verified Checkpoint。

    Agent 可读文件/受控修改/重跑构建测试/再评估；不篡改已固化 Checkpoint。
    """
    from app.domains.course_generation.harness.workspace import CourseWorkspace
    from app.domains.course_generation.lessons.change_set import CHANGESET_PROTOCOL
    from app.domains.course_generation.lessons.lesson_publisher import (
        load_compatible_checkpoints,
    )

    ws_data = row.workspace or {}
    task_order = ws_data.get("taskOrder") or []
    blueprint_hash = _harness_blueprint_hash(ws_data)
    checkpoints = load_compatible_checkpoints(
        row.generation_id, blueprint_hash, CHANGESET_PROTOCOL,
        "projectweave-sandbox-cpp:clang15-bookworm", "")
    # 最后一个可用检查点为修复基线
    last_cp = None
    for tid in reversed(task_order):
        if tid in checkpoints:
            last_cp = checkpoints[tid]
            break
    if last_cp is None:
        raise HarnessSessionError("无可用 Verified Checkpoint，无法修复", 422)

    manifest = (last_cp.get("artifact") or {}).get("buildManifest") or {}
    workspace = CourseWorkspace({
        "referenceFiles": last_cp["snapshot_files"],
        "starterOverlay": {},
        "manifest": manifest,
        "instructions": {"title": "Final Integration Repair",
                         "goal": "修复最终集成/发布失败", "expectedFiles": []},
        "hints": [],
        "revisions": [],
        "baseSnapshot": {
            "referenceFiles": last_cp["snapshot_files"],
            "manifest": manifest,
            "phase": "final-repair",
            "failure": (ws_data.get("publishFailure") or "")[:600],
            "testOrder": task_order,
            "priorTests": last_cp.get("test_registry") or [],
        },
    })
    controller = HarnessController(
        db_factory=_db, session_id=row.id, workspace=workspace,
        provider=_provider(),
        task_spec={"taskId": "__final_repair__",
                   "title": "Final Integration Repair",
                   "description": "修复最终集成失败：" + (ws_data.get("publishFailure") or "")[:200],
                   "acceptanceCriteria": ["全量 CTest 通过", "Demo 运行成功"]},
        milestone_title="最终集成",
        prior_tests=last_cp.get("test_registry") or [],
        is_final=True,
        release_id=row.release_id, generation_id=row.generation_id,
        task_seq=len(task_order), blueprint_hash=blueprint_hash,
        job_lease=lease, timeline=[],
    )
    controller.init_acceptance_contract(
        controller.task_spec, last_cp.get("test_registry") or [])
    controller.final_phase = "repairing"
    row.state = "final-repairing"
    return controller


def _run_final_phase(db, row: CourseDevSession, result: dict) -> None:
    """任务全完成后执行 Final Evaluation → publish / final-repairing。

    区分失败类型：工程/契约失败 → final-repairing（Agent 可修）；
    基础设施失败 → paused（等待恢复，不让 AI 改代码）。
    """
    ws = row.workspace or {}
    publish = _publish_release(db, row)
    if publish.get("ok"):
        row.state = "completed"
        row.release_id = _uuid.UUID(publish["releaseId"])
        row.error = None
        ws["publishedReleaseId"] = publish["releaseId"]
        ws["finalEvaluation"] = publish.get("finalReport") or {}
        ws.pop("publishFailure", None)
    else:
        error = publish.get("error", "")
        failure_class = _classify_publish_failure(error)
        ws["publishFailure"] = error[:600]
        ws["publishFailureClass"] = failure_class
        if failure_class == "infrastructure":
            row.state = "paused"
            row.error = "发布基础设施失败（等待恢复后重试）：" + error[:300]
        else:
            row.state = "final-repairing"
            row.error = "最终集成失败（Agent 可修复）：" + error[:300]
    row.workspace = ws


def _merge_workspace(row: CourseDevSession, result: dict) -> dict:
    ws = dict(row.workspace or {})
    ws["runtime"] = result["workspace"]
    if result["completed"]:
        done = set(ws.get("completedTaskIds") or [])
        done.add(row.current_task_id)
        ws["completedTaskIds"] = sorted(done)
    return ws


def _advance_or_complete(db, row: CourseDevSession, result: dict) -> None:
    ws = row.workspace or {}
    order = ws.get("taskOrder") or []
    done = set(ws.get("completedTaskIds") or [])
    done.add(row.current_task_id)
    ws["completedTaskIds"] = sorted(done)
    if len(done) >= len(order):
        # D50：全部任务完成 → Final Evaluation Phase（不再直接 completed）
        _run_final_phase(db, row, result)
    elif row.state == "final-repairing":
        # D50：Final Repair 完成（submit_task）→ 保存修复检查点并重发
        pass
    else:
        row.state = "paused"   # 等待下一 slice（自动或手动 resume）
        row.error = None
    row.workspace = ws


def _publish_release(db, row: CourseDevSession) -> dict:
    """从 Verified Checkpoints 发布 ready CourseRelease（复用既有模型）。

    检查点链完整 → 聚合 artifacts/reference_store → 最终集成真实 CTest
    + Demo 运行 → 全部通过才 ready（数据库事务提交）。
    """
    from app.domains.course_generation.models import CourseGeneration, CourseRelease
    from app.domains.course_generation.lessons.change_set import CHANGESET_PROTOCOL
    from app.domains.course_generation.lessons.lesson_publisher import (
        load_compatible_checkpoints,
    )
    from app.domains.course_generation.verification.course_verifier import (
        run_cmake_operation,
    )

    ws = row.workspace or {}
    task_order = ws.get("taskOrder") or []
    blueprint_hash = _harness_blueprint_hash(ws)
    checkpoints = load_compatible_checkpoints(
        row.generation_id, blueprint_hash, CHANGESET_PROTOCOL,
        "projectweave-sandbox-cpp:clang15-bookworm", "")
    # D50：取消后禁止发布；Lease Fencing（发布前验证会话仍由本 worker 持有）
    if row.cancel_requested:
        return {"ok": False, "error": "会话已取消——禁止发布", "class": "infrastructure"}
    # 幂等：同一 session 已发布 → 直接返回（不重复发布）
    already = (ws.get("publishedReleaseId")
               or str(row.release_id) if row.release_id else None)
    if already:
        return {"ok": True, "releaseId": already, "idempotent": True}
    missing = [tid for tid in task_order if tid not in checkpoints]
    if missing:
        return {"ok": False, "error": f"缺少 Verified Checkpoint：{missing}",
                "class": "contract"}

    ordered = [checkpoints[tid] for tid in task_order]
    for i, cp in enumerate(ordered):
        if cp["task_seq"] != i:
            return {"ok": False,
                    "error": f"检查点序号不连续：{cp['task_id']}(seq={cp['task_seq']})"}
        if (i > 0 and cp.get("prev_snapshot_hash")
                and cp["prev_snapshot_hash"] != ordered[i - 1].get("snapshot_hash")):
            return {"ok": False, "error": f"快照链断裂：{cp['task_id']}"}

    final_cp = ordered[-1]
    final_files = final_cp["snapshot_files"]
    manifest = (final_cp.get("artifact") or {}).get("buildManifest") or {}
    run_targets = manifest.get("runTargets") or []

    # Final Course Evaluation（D50）：全量 CTest + 稳定性 + Demo（真沙箱）
    required_tests = sorted({t for cp in ordered for t in cp.get("test_registry") or []})
    full = run_cmake_operation(final_files, mode="test")
    executed = passed = 0
    if full.test_results:
        executed = len(full.test_results)
        passed = sum(1 for t in full.test_results if t.get("status") == "passed")
    if not full.ok:
        return {"ok": False,
                "error": "最终全量 CTest 未通过：" + "; ".join(
                    d.get("message", "")[:120] for d in (full.diagnostics or [])[:3]),
                "class": "engineering",
                "finalReport": {"status": "failed", "executedTests": executed,
                                "passedTests": passed}}
    demo_results = []
    for target in run_targets:
        demo = run_cmake_operation(final_files, mode="run",
                                   cmake_action="run", target_name=target)
        demo_results.append({"target": target,
                             "status": "passed" if demo.ok else "failed"})
        if not demo.ok:
            return {"ok": False, "error": f"最终演示目标运行失败：{target}",
                    "class": "engineering",
                    "finalReport": {"status": "failed", "demo": demo_results}}
    from app.domains.course_generation.harness.evaluator import run_stability
    stability = run_stability(final_files, {"testNames": required_tests}, runs=2)
    if stability.get("flakySuspected"):
        return {"ok": False, "error": "最终稳定性验证未通过（间歇失败）",
                "class": "engineering",
                "finalReport": {"status": "failed", "stability": stability}}
    final_report = {
        "status": "passed",
        "blueprintHash": blueprint_hash,
        "checkpointCount": len(ordered), "taskCount": len(task_order),
        "requiredTests": required_tests,
        "executedTests": executed, "passedTests": passed,
        "demoTargets": demo_results, "stability": stability,
    }

    # D50 Effective Blueprint 单一权威：Release/Student 使用 session 实际
    # 采用的任务定义（含 Task Refinement 拆分），不回退到 gen.blueprint
    gen = db.get(CourseGeneration, row.generation_id)
    effective_blueprint = {
        "project": ws.get("project") or (
            (gen.blueprint.get("project") if gen and gen.blueprint else {}) or {}),
        "milestones": ws.get("milestones") or [],
        "tasks": ws.get("tasks") or [],
        "knowledgeRequirements": [],
        # 溯源：原始蓝图 → 拆分映射（可审计）
        "effectiveBlueprint": {
            "revision": row.blueprint_revision,
            "hash": blueprint_hash,
            "taskOrder": task_order,
            "mappings": ws.get("refinementMappings") or [],
        },
    }
    # 一致性校验：每个 Artifact taskId 必须在 Effective Blueprint 中
    artifact_ids = {(cp.get("artifact") or {}).get("taskId") for cp in ordered}
    blueprint_ids = set(task_order)
    if artifact_ids != blueprint_ids:
        return {"ok": False,
                "error": f"蓝图一致性失败：artifact={sorted(artifact_ids)} vs "
                         f"blueprint={sorted(blueprint_ids)}",
                "class": "contract"}
    version = 1 + len(list(db.scalars(select(CourseRelease.id).where(
        CourseRelease.generation_id == row.generation_id))))
    release = CourseRelease(
        generation_id=row.generation_id,
        release_version=version,
        status="ready",
        language="cpp",
        course_title=(effective_blueprint.get("project") or {}).get("title", ""),
        progress=100,
        blueprint_snapshot=effective_blueprint,
        artifacts=[cp["artifact"] for cp in ordered],
        reference_store={cp["task_id"]: cp["reference_delta"] for cp in ordered},
        verification_report={
            "passed": len(ordered), "total": len(ordered),
            "finalIntegration": {"status": "passed", "source": "harness-publish"},
            "harness": {"sessionId": str(row.id), "tasks": task_order},
        },
        ready_at=utcnow(),
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return {"ok": True, "releaseId": str(release.id),
            "finalReport": final_report}


def _harness_blueprint_hash(ws_data: dict) -> str:
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    return snapshot_hash_of(
        {"blueprint": json.dumps(
            {"tasks": ws_data.get("tasks") or [],
             "milestones": ws_data.get("milestones") or []},
            sort_keys=True, ensure_ascii=False)})
