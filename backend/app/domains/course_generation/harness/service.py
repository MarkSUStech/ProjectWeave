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
                   "completedTaskIds": done_prefix},
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
    if row.state == "developing":
        row.state = "paused"   # worker 在每个工具轮检查后收敛退出
    db.commit()
    return {"state": row.state}


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
        raise HarnessSessionError("全部任务已完成", 422)
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
    # D49 Resume：同任务/同蓝图/同基线的 Runtime Snapshot → 原样恢复
    runtime = (row.workspace or {}).get("runtimeSnapshot")
    resumed = bool(runtime) and controller.load_runtime(runtime)
    row.workspace = {**(row.workspace or {}), "runtimeResumed": resumed}
    return controller


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
        # D49：全部任务完成 → Final Evaluation + CourseRelease 自动发布
        publish = _publish_release(db, row)
        if publish.get("ok"):
            row.state = "completed"
            row.release_id = _uuid.UUID(publish["releaseId"])
            row.error = None
            ws["publishedReleaseId"] = publish["releaseId"]
        else:
            # 发布失败：不进 completed——保留检查点，可继续修复重发
            row.state = "failed"
            row.error = "最终发布失败：" + publish.get("error", "")[:400]
            ws["publishFailure"] = publish.get("error", "")[:600]
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
    missing = [tid for tid in task_order if tid not in checkpoints]
    if missing:
        return {"ok": False, "error": f"缺少 Verified Checkpoint：{missing}"}

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

    full = run_cmake_operation(final_files, mode="test")
    if not full.ok:
        return {"ok": False,
                "error": "最终全量 CTest 未通过：" + "; ".join(
                    d.get("message", "")[:120] for d in (full.diagnostics or [])[:3])}
    for target in run_targets:
        demo = run_cmake_operation(final_files, mode="run",
                                   cmake_action="run", target_name=target)
        if not demo.ok:
            return {"ok": False, "error": f"最终演示目标运行失败：{target}"}

    gen = db.get(CourseGeneration, row.generation_id)
    version = 1 + len(list(db.scalars(select(CourseRelease.id).where(
        CourseRelease.generation_id == row.generation_id))))
    release = CourseRelease(
        generation_id=row.generation_id,
        release_version=version,
        status="ready",
        language="cpp",
        course_title=(gen.blueprint.get("project") or {}).get("title", "")
        if gen and gen.blueprint else "",
        progress=100,
        blueprint_snapshot=gen.blueprint if gen else {},
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
    return {"ok": True, "releaseId": str(release.id)}


def _harness_blueprint_hash(ws_data: dict) -> str:
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    return snapshot_hash_of(
        {"blueprint": json.dumps(
            {"tasks": ws_data.get("tasks") or [],
             "milestones": ws_data.get("milestones") or []},
            sort_keys=True, ensure_ascii=False)})
