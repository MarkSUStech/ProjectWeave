"""课程内容生产/发布/实例化服务（P7.2，D42）。

流水线（后台线程，release 行持久化进度）：
按任务 DAG 顺序逐任务：LLM 生成材料 → 防伪守卫 → 真实沙箱验证参考实现
（本任务测试 + 回归测试）→ 失败进入 ≤2 修复轮 → 通过则参考快照累积传递
给下一任务 → 全部通过后跑最终集成验证 → ready。
instantiate：从 ready release 创建学生项目（种子首任务 starter + 全部任务）。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.schemas import extract_json_object  # noqa: F401
from app.domains.course_generation.lessons import lesson_builder
from app.domains.course_generation.lessons.schemas import LessonArtifact
from app.domains.course_generation.models import CourseGeneration, CourseRelease
from app.domains.course_generation.execution_profile import (
    derive_execution_profile,
    unsupported_profile_message,
)
from app.domains.course_generation.validation.blueprint_validator import _has_cycle
from app.domains.course_generation.verification.course_verifier import (
    guard_starter,
    merge_files,
    run_in_sandbox,
    verify_cpp_cmake_task,
)

MAX_REPAIR_PER_TASK = 3


def unsupported_language_message(language: str) -> str:
    """无真实沙箱验证器的语言：如实拒绝（不烧 LLM、不伪装成功）。"""
    return (f"暂不支持 {language} 课程的沙箱验证（当前支持 Python/pytest 与 C++/CMake 真实全链验证）。"
            "为不伪造成功，已拒绝生成课程内容；蓝图已保留，待该语言验证器上线后可重试。")


class ReleaseError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 注入点（测试）
_session_factory = None
_provider_factory = None


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def set_provider_factory(factory) -> None:
    global _provider_factory
    _provider_factory = factory


def _session():
    if _session_factory is not None:
        return _session_factory()
    from app.core.db import SessionLocal

    return SessionLocal()


def _provider():
    if _provider_factory is not None:
        return _provider_factory()
    from app.ai.provider import get_provider

    return get_provider()


def _routed_provider(base_provider, role: str):
    """P8.2.2 模型路由：按角色返回配置的模型实例（空配置 = 基础 provider）。

    仅当注入的是真实 DeepSeek provider 且配置了非默认模型时才构造新实例；
    Mock/测试 provider 原样返回（测试永不触发收费模型）。
    """
    from app.core.config import settings

    model_map = {
        "generation": settings.course_generation_model,
        "reasoning": settings.course_reasoning_model,
        "repair": settings.course_repair_model,
    }
    model = model_map.get(role, "")
    if not model or getattr(base_provider, "name", "") == "mock":
        return base_provider
    try:
        from app.ai.provider import DeepSeekProvider

        routed = DeepSeekProvider(model=model)
        return routed
    except Exception:
        return base_provider  # 路由失败退回默认（不阻塞生成）


# ---------------------------------------------------------------- 创建/查询


def build_lessons(db: Session, generation_id) -> CourseRelease:
    gen = db.get(CourseGeneration, _uuid(generation_id))
    if gen is None:
        raise ReleaseError("生成任务不存在", 404)
    if gen.blueprint is None or gen.status not in ("published", "draft"):
        raise ReleaseError("蓝图未就绪（需先完成蓝图生成与验证）")
    profile = derive_execution_profile(gen.blueprint)
    language = profile["primaryLanguage"]
    if not profile["verified"]:
        # 提前拒绝：不做任何 LLM 生成/修复尝试，不产生注定失败的 release
        raise ReleaseError(unsupported_profile_message(profile), 422)

    # P8.2.2 任务拆分：高复杂度终点集成任务确定性细化——只作用于本 release
    # 的私有蓝图快照（gen.blueprint 与既有 Checkpoint/Release 不被触碰）。
    blueprint_for_release = gen.blueprint
    refinement_summary = {"refined": False, "mappings": [], "complexity": []}
    if language == "cpp":
        from app.domains.course_generation.generation.task_refinement import (
            refine_blueprint,
        )

        refinement = refine_blueprint(gen.blueprint)
        if refinement.refined:
            blueprint_for_release = refinement.blueprint
            refinement_summary = refinement.summary()

    version = 1 + len(list(db.scalars(
        select(CourseRelease.id).where(CourseRelease.generation_id == gen.id)
    )))
    release = CourseRelease(
        generation_id=gen.id,
        release_version=version,
        status="generating",
        language=language,
        course_title=(gen.blueprint.get("project") or {}).get("title", ""),
        blueprint_snapshot=blueprint_for_release,
        verification_report={"taskRefinement": refinement_summary},
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    threading.Thread(target=_run_build, args=(release.id,), daemon=True,
                     name=f"pw-lessons-{release.id.hex[:8]}").start()
    return release


def get_release(db: Session, release_id) -> CourseRelease:
    row = db.get(CourseRelease, _uuid(release_id))
    if row is None:
        raise ReleaseError("课程版本不存在", 404)
    return row


def list_releases(db: Session, generation_id) -> list[CourseRelease]:
    return list(db.scalars(
        select(CourseRelease)
        .where(CourseRelease.generation_id == _uuid(generation_id))
        .order_by(CourseRelease.release_version.desc())
    ))


def recover_stale_releases(db: Session) -> int:
    """服务重启恢复：卡在 generating/verifying 的 release 标记失败（可重试）。"""
    stale = list(db.scalars(select(CourseRelease).where(
        CourseRelease.status.in_(("generating", "verifying"))
    )))
    for row in stale:
        row.status = "failed"
        row.error = "服务重启中断（可从检查点恢复：重新生成课程内容将复用已验证任务）"
    db.commit()
    # 关联 Job 标记 interrupted（等待显式 resume）
    from app.domains.course_generation.models import GenerationJob

    interrupted = 0
    for row in stale:
        jobs = list(db.scalars(select(GenerationJob).where(
            GenerationJob.release_id == row.id,
            GenerationJob.status == "running",
        )))
        for job in jobs:
            job.status = "interrupted"
            job.lease_token = None
            interrupted += 1
    db.commit()
    return len(stale)


# ---------------------------------------------------------------- Generation Job（P8.2.1）


JOB_LEASE_SECONDS = 900  # 单任务课程生成远小于此；每任务开始时续租


def _aware(dt):
    """SQLite 读回 naive 时间统一补 UTC（PG 返回 aware 原样）。"""
    import datetime as _dt

    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)


def _claim_job(release_id, generation_id) -> tuple | None:
    """原子抢占 Job（P8.2.2）：条件 UPDATE，同一 release 同时至多一个 worker。

    返回 (job_id, lease_token)；已有活跃 worker（running 且租约未过期）→ None。
    """
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import update as _update

    from app.domains.course_generation.models import GenerationJob

    token = _uuid.uuid4().hex
    now = utcnow()
    with _session() as db:
        existing = db.scalar(select(GenerationJob).where(
            GenerationJob.release_id == release_id))
        if existing is None:
            job = GenerationJob(
                release_id=release_id, generation_id=generation_id,
                status="running", lease_token=token,
                lease_expires_at=now + timedelta(seconds=JOB_LEASE_SECONDS),
                retry_count=1,
            )
            db.add(job)
            db.commit()
            return job.id, token
        # 原子抢占（事务 + 行锁）：非 running，或租约已过期（旧 worker 失联）。
        # PG 用 FOR UPDATE 行锁；SQLite 单写者天然串行——判定在 Python 侧
        # 完成（避免 naive/aware 时间在 SQL 端比较的方言差异）。
        locked = db.get(GenerationJob, existing.id, with_for_update=True)
        if locked is None:
            return None
        lease_expired = (_aware(locked.lease_expires_at) is None
                         or _aware(locked.lease_expires_at) < now)
        if locked.status == "running" and not lease_expired:
            db.rollback()
            return None  # 另一 worker 持有有效租约
        locked.status = "running"
        locked.lease_token = token
        locked.error = None
        locked.lease_expires_at = now + timedelta(seconds=JOB_LEASE_SECONDS)
        locked.retry_count = (locked.retry_count or 0) + 1
        locked.completed_task_ids = []
        locked.reused_task_ids = []
        db.commit()
        return locked.id, token


def _lease_renew(job_lease: tuple) -> None:
    """续租（每任务开始时）。"""
    from datetime import timedelta

    from sqlalchemy import update as _update

    from app.domains.course_generation.models import GenerationJob

    job_id, token = job_lease
    try:
        with _session() as db:
            db.execute(
                _update(GenerationJob).where(GenerationJob.id == job_id)
                .where(GenerationJob.lease_token == token)
                .values(lease_expires_at=utcnow() + timedelta(seconds=JOB_LEASE_SECONDS)))
            db.commit()
    except Exception:
        pass


def _lease_valid(job_lease: tuple) -> bool:
    """当前 worker 的租约是否仍有效（提交 Checkpoint/ready 前必须校验）。"""
    from app.domains.course_generation.models import GenerationJob

    if job_lease is None:
        return True  # 旧路径（无 lease）不阻塞——兼容测试
    job_id, token = job_lease
    with _session() as db:
        row = db.get(GenerationJob, job_id)
        if row is None or row.lease_token != token or row.status != "running":
            return False
        expires = _aware(row.lease_expires_at)
        return expires is None or expires > utcnow()


def _job_update(job_id, **fields) -> None:
    if job_id is None:
        return
    try:
        with _session() as db:
            from app.domains.course_generation.models import GenerationJob

            row = db.get(GenerationJob, job_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        pass  # Job 记录失败不影响课程生成本身


def instantiate_project(db: Session, release_id, title: str | None = None) -> dict:
    """从 ready release 创建学生项目：首任务 starter + 全部任务种子。"""
    release = get_release(db, release_id)
    if release.status != "ready":
        raise ReleaseError("课程未就绪（lessons 未全部验证通过）")

    from app.domains.projects.models import Project, ProjectFile
    from app.domains.curriculum.models import ProjectTask

    blueprint = _normalize_blueprint(release.blueprint_snapshot or {})
    course_title = title or release.course_title or "课程项目"
    project = Project(
        owner_id="dev-user",
        title=course_title,
        description=(blueprint.get("project") or {}).get("description", ""),
        mode="rebuild",
        complexity="medium",
        target_features=(blueprint.get("project") or {}).get("goals") or [],
        non_goals=(blueprint.get("project") or {}).get("nonGoals") or [],
        stack=[release.language.capitalize()],
        acceptance_criteria=(blueprint.get("project") or {}).get("evidence") and [] or [],
        # 课程项目绑定确定 release 版本
        template_id=f"course-release:{release.id}",
    )
    db.add(project)
    db.flush()

    artifacts = release.artifacts or []
    by_task = {a.get("taskId") or a.get("task_id"): a for a in artifacts}
    order = _task_order(blueprint)
    first = next((a for a in order if a["taskId"] in by_task), None)

    # 种子文件：README + 首任务 starter + 首任务测试
    files: dict[str, str] = {
        "README.md": (
            f"# {course_title}\n\n"
            f"本项目由 ProjectWeave 课程自动创建（release v{release.release_version}）。\n"
            f"按「任务」面板逐步完成；每个任务有初始代码与可运行测试。\n"
        ),
    }
    if first:
        first_artifact = by_task.get(first["taskId"]) or {}
        for f in first_artifact.get("starterFiles") or first_artifact.get("starter_files") or []:
            files[f["path"]] = f["content"]
        for f in first_artifact.get("testFiles") or first_artifact.get("test_files") or []:
            files.setdefault(f["path"], f["content"])
    for path, content in files.items():
        db.add(ProjectFile(project_id=project.id, path=path, content=content))

    # 种子任务（全部任务入图；测试文件路径绑定 + P8.2 CMake 验收契约）
    ms_order = {m["milestoneId"]: i + 1 for i, m in enumerate(blueprint.get("milestones") or [])}
    first_task_row = None
    for spec in order:
        artifact = by_task.get(spec["taskId"])
        manifest = ((artifact or {}).get("buildManifest")
                    or (artifact or {}).get("build_manifest") or {})
        verification = None
        if manifest.get("testNames") or manifest.get("buildTargets"):
            verification = {
                "buildSystem": "cmake",
                "buildTargets": manifest.get("buildTargets") or [],
                "testNames": manifest.get("testNames") or [],
                "verificationProfile": "ctest",
            }
        task_row = ProjectTask(
            project_id=project.id,
            task_id=spec["taskId"],
            milestone=ms_order.get(spec.get("milestoneId"), 1),
            title=spec.get("title", ""),
            description=_task_description(artifact, spec),
            depends_on=spec.get("dependsOn") or [],
            required_concepts=spec.get("requiredConcepts") or [],
            deliverable="; ".join(spec.get("deliverables") or [])[:400],
            test_files=[f["path"] for f in (artifact or {}).get("testFiles") or (artifact or {}).get("test_files") or []],
            starter_files=[f["path"] for f in (artifact or {}).get("starterFiles") or (artifact or {}).get("starter_files") or []],
            acceptance_criteria=spec.get("acceptanceCriteria") or [],
            hints=(artifact or {}).get("hints") or [],
            viz_suggestion="",
            verification=verification,
        )
        db.add(task_row)
        if first and spec["taskId"] == first["taskId"]:
            first_task_row = task_row
    # P7.3：首任务已注入 starter+tests → 标记 in-progress（已激活态）
    if first_task_row is not None and first_task_row.status in ("pending", None):
        first_task_row.status = "in-progress"
    db.commit()
    db.refresh(project)
    return {"project_id": project.id, "first_task_id": first["taskId"] if first else None}


# ---------------------------------------------------------------- 构建流水线


def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _normalize_blueprint(data: dict) -> dict:
    """蓝图统一为 camelCase dict（快照可能来自 model_dump 蛇形或 LLM 驼峰）。"""
    from app.domains.course_generation.schemas import CourseBlueprint

    return CourseBlueprint.model_validate(data).model_dump(mode="json", by_alias=True)


def _task_order(blueprint: dict) -> list[dict]:
    tasks = blueprint.get("tasks") or []
    graph = {t["taskId"]: list(t.get("dependsOn") or []) for t in tasks}
    if _has_cycle(graph):
        raise ReleaseError("任务依赖有环，无法排序")
    ordered, seen = [], set()

    def visit(tid):
        if tid in seen:
            return
        seen.add(tid)
        for dep in graph.get(tid, []):
            visit(dep)
        ordered.append(tid)

    for t in tasks:
        visit(t["taskId"])
    by_id = {t["taskId"]: t for t in tasks}
    return [by_id[tid] for tid in ordered]


def _update(release_id, **fields) -> None:
    try:
        with _session() as db:
            row = db.get(CourseRelease, release_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        pass


def _run_build(release_id: uuid.UUID) -> None:
    try:
        _run_build_inner(release_id)
    except Exception as exc:
        _update(release_id, status="failed", error=f"课程内容生产内部错误：{exc}")


# ---------------------------------------------------------------- P8.2.1 增量流水线（D46）


def _test_like_path(path: str) -> bool:
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    return (lower.startswith("tests/") or "test" in base
            or "cmakelists.txt" in lower)


def _split_starter_test(starter_files: dict[str, str]):
    """starter 工程 → (starterFiles, testFiles) 两组件（testFiles=测试注册与测试源）。"""
    starters = [{"path": p, "content": c} for p, c in sorted(starter_files.items())
                if not _test_like_path(p)]
    tests = [{"path": p, "content": c} for p, c in sorted(starter_files.items())
             if _test_like_path(p)]
    return starters, tests


def _material_from_state(state: dict) -> dict:
    """内部状态（ref/starter 文件字典 + 元数据）→ 验证器/守卫的材料形状。"""
    starter_files = dict(state["reference_files"])
    starter_files.update(state["starter_overlay"])
    starters, tests = _split_starter_test(starter_files)
    ref_all = dict(state["reference_files"])
    _, ref_tests = _split_starter_test(ref_all)
    return {
        "instructions": state["instructions"],
        "starterFiles": starters,
        "testFiles": tests,
        "referenceFiles": [
            {"path": p, "content": c} for p, c in sorted(ref_all.items())
            if not _test_like_path(p)
        ] + ref_tests,
        "buildManifest": state["manifest"],
        "hints": state["hints"],
    }


def _persist_checkpoint(db, release_id, generation_id, task_seq: int, task_id: str,
                        blueprint_hash: str, protocol: str, sandbox_image: str,
                        source_commit: str, reference_files: dict,
                        test_registry: list, artifact: dict, reference_delta: list,
                        evidence: list, diagnostics: dict,
                        task_spec_hash: str = "", prev_snapshot_hash: str = "") -> None:
    from app.domains.course_generation.models import CourseCheckpoint
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    db.add(CourseCheckpoint(
        release_id=release_id, generation_id=generation_id,
        task_seq=task_seq, task_id=task_id,
        blueprint_hash=blueprint_hash, protocol_version=protocol,
        sandbox_image=sandbox_image, source_commit=source_commit,
        snapshot_files=reference_files,
        snapshot_hash=snapshot_hash_of(reference_files),
        task_spec_hash=task_spec_hash, prev_snapshot_hash=prev_snapshot_hash,
        test_registry=list(test_registry),
        artifact=artifact, reference_delta=reference_delta,
        verification_evidence=evidence, diagnostics=diagnostics,
    ))
    db.commit()


def load_compatible_checkpoints(generation_id, blueprint_hash: str,
                                protocol: str, sandbox_image: str,
                                source_commit: str) -> dict[str, dict]:
    """按任务取最新兼容检查点（blueprint/协议/镜像/源版本一致才可复用）。"""
    from sqlalchemy import select as _select

    from app.domains.course_generation.models import CourseCheckpoint

    with _session() as db:
        rows = db.scalars(_select(CourseCheckpoint).where(
            CourseCheckpoint.generation_id == generation_id
        ).order_by(CourseCheckpoint.task_seq.desc(), CourseCheckpoint.created_at.desc()))
        picked: dict[str, dict] = {}
        for row in rows:
            if (row.blueprint_hash == blueprint_hash
                    and row.protocol_version == protocol
                    and (row.sandbox_image or "") == sandbox_image
                    and (row.source_commit or "") == source_commit
                    and row.task_id not in picked):
                picked[row.task_id] = {
                    "task_spec_hash": row.task_spec_hash or "",
                    "prev_snapshot_hash": row.prev_snapshot_hash or "",
                    "snapshot_hash": row.snapshot_hash or "",
                    "task_seq": row.task_seq,
                    "task_id": row.task_id,
                    "snapshot_files": dict(row.snapshot_files or {}),
                    "test_registry": list(row.test_registry or []),
                    "artifact": dict(row.artifact or {}),
                    "reference_delta": list(row.reference_delta or []),
                    "verification_evidence": list(row.verification_evidence or []),
                    "diagnostics": dict(row.diagnostics or {}),
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
    # 只保留严格递增序列（task_seq 连续 0..n）且前序快照链一致——
    # 链断（任务 ID/依赖/验收语义变化）默认不复用
    by_seq = sorted(picked.values(), key=lambda c: c["task_seq"])
    usable: dict[str, dict] = {}
    expect = 0
    prev_hash = ""
    for cp in by_seq:
        if cp["task_seq"] != expect:
            break
        if expect > 0 and cp.get("prev_snapshot_hash") and cp["prev_snapshot_hash"] != prev_hash:
            break  # 前序快照链不匹配（上游任务重生成过）
        usable[cp["task_id"]] = cp
        prev_hash = cp.get("snapshot_hash", "")
        expect += 1
    return usable


def _process_cpp_task(
    provider, release_id, generation_id, blueprint_hash: str,
    task_seq: int, task_id: str, spec: dict,
    milestone_title: str, cumulative_reference: dict[str, str],
    prior_test_names: list[str], evidence: dict[str, str],
    prior_failures: list[str] | None, is_final: bool,
    job_lease: tuple | None = None,
) -> dict:
    """P8.2.1 增量流水线：ChangeSet 生成 → 确定性合成 → 一致性 → 八步验证
    → 最小补丁修复 → 通过后固化 Checkpoint。

    返回 {passed, error, artifact, cumulative_reference, prior_test_names,
    reference_delta, diagnostics}。
    """
    from app.domains.course_generation.lessons.change_applier import (
        apply_file_changes,
        compose_project_files,
    )
    from app.domains.course_generation.lessons.change_set import (
        CHANGESET_PROTOCOL,
        LessonChangeSet,
        content_hash,
    )
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
        validate_material,
    )
    from app.domains.course_generation.lessons.cpp_repair_agent import (
        RepairBudget,
        classify_failure,
        repair_with_agent,
    )

    _update(release_id, status="verifying", current_task=task_id)
    # 增量协议：1 次生成 + 最多 5 轮最小补丁（验证硬标准不变；集成类任务
    # 一次修复常需 2-3 轮收敛，3 轮实测偏紧）
    budget = RepairBudget(max_llm_calls=1 + 5)
    repairs: list[dict] = []
    sandbox_image = "projectweave-sandbox-cpp:clang15-bookworm"

    base_files = dict(cumulative_reference)
    snapshot_id = "root" if not base_files else f"verified:{task_id}:seq{task_seq - 1}"
    snapshot_hash = snapshot_hash_of(base_files)
    prev_contract = {
        "buildManifest": {"testNames": prior_test_names},
        "verifiedTests": prior_test_names,
    }

    state: dict | None = None       # {reference_files, starter_overlay, instructions, manifest, hints}
    raw_changeset: dict | None = None
    schema_error: str | None = None

    def _apply_repair_patch(patch: list[dict]) -> tuple[bool, list[dict]]:
        """修复补丁应用到当前参考工程（baseHash=当前内容）。"""
        normalized = []
        for entry in patch:
            copy = dict(entry)
            # 容错补默认：DeepSeek 常省略可选字段导致整轮补丁作废
            copy.setdefault("operation", "update" if copy.get("content") else "delete")
            copy.setdefault("reason", "")
            copy.setdefault("changeCategory", "source")
            copy.setdefault("target", "reference")
            if copy["operation"] in ("update", "delete") and not copy.get("baseHash"):
                current = (state or {}).get("reference_files", {}).get(copy.get("path", ""))
                if current is not None:
                    copy["baseHash"] = content_hash(current)
            normalized.append(copy)
        try:
            from app.domains.course_generation.lessons.change_set import FileChange

            changes = [FileChange.model_validate(entry) for entry in normalized]
        except Exception as exc:  # noqa: BLE001 —— 补丁结构非法如实返回
            return False, [{"errorCode": "schema-error", "filePath": "<patch>",
                            "expected": "合法 FileChange", "actual": str(exc)[:200],
                            "suggestedRepairScope": "<patch>"}]
        starter_changes = [c for c in changes if c.target == "starter"]
        ref_changes = [c for c in changes if c.target != "starter"]
        # 防线：修复补丁不得修改前序任务已验证的测试源（防破坏回归）——
        # 铁律的确定性兜底（LLM 违规直接拒绝该条补丁）
        protected_tests = {p for p in base_files
                           if p.startswith("tests/") and p.endswith((".cpp", ".cc"))}
        violating = [c.path for c in ref_changes if c.path in protected_tests
                     and c.operation in ("update", "delete")]
        if violating:
            return False, [{
                "errorCode": "protected-prior-test",
                "filePath": p, "expected": "前序已验证测试保持不变",
                "actual": f"补丁请求 {next(c.operation for c in ref_changes if c.path == p)}",
                "suggestedRepairScope": "本任务自己的测试/注册",
            } for p in violating]
        if starter_changes:
            # starter 挖空补丁：直接覆盖 overlay（挖空语义：TODO + 默认返回）
            for change in starter_changes:
                if change.operation == "delete":
                    state["starter_overlay"].pop(change.path, None)
                else:
                    state["starter_overlay"][change.path] = change.content
        if not ref_changes:
            return True, [{"path": c.path, "operation": c.operation,
                           "hash": content_hash(c.content), "reason": c.reason,
                           "changeCategory": c.change_category, "target": "starter"}
                          for c in starter_changes]
        applied = apply_file_changes(state["reference_files"], ref_changes)
        if not applied.ok:
            return False, applied.conflicts
        state["reference_files"] = applied.files
        return True, [*applied.applied,
                      *[{"path": c.path, "operation": c.operation,
                         "hash": content_hash(c.content), "reason": c.reason,
                         "changeCategory": c.change_category, "target": "starter"}
                        for c in starter_changes]]

    last_errors: list[dict] = []
    last_problems: list[str] = []
    # P8.2.2：修复进度跟踪（熔断依据）与确定性修复统计
    error_history: list[set] = []
    stagnant_rounds = 0
    deterministic_fixes = 0

    def _error_signature(errors: list[dict]) -> set:
        return {(e.get("errorCode"), (e.get("filePath") or "")[:80],
                 (e.get("actual") or "")[:60]) for e in errors}

    def _record_round(errors: list[dict]) -> None:
        nonlocal stagnant_rounds
        sig = _error_signature(errors)
        error_history.append(sig)
        if len(error_history) >= 2 and sig == error_history[-2]:
            stagnant_rounds += 1
        elif len(error_history) >= 2:
            before = error_history[-2]
            if not (sig - before):  # 未解决任何旧错误（可能新增或持平）
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

    def _deterministic_manifest_fix() -> bool:
        """manifest.testNames 与实际注册名的保守对齐（不猜 CMake 语义）。

        条件（全部满足才动）：consistency 报 registration-mismatch；工程里
        存在恰好一个「已注册但未被 manifest 引用」的新测试 与 恰好一个
        「manifest 引用但不存在」的名字 → 判定 LLM 命名笔误，按注册名为准
        修正 manifest（验收语义 = 该测试真实存在并通过，不弱化）。
        """
        nonlocal deterministic_fixes
        from app.domains.course_generation.lessons.consistency_validator import (
            _ADD_TEST_RE,
        )
        mismatched = [e for e in last_errors
                      if e.get("errorCode") == "ctest-registration-mismatch"]
        if not mismatched:
            return False
        registered: list[str] = []
        for path, content in state["reference_files"].items():
            if "cmakelists.txt" in path.lower():
                registered.extend(_ADD_TEST_RE.findall(content))
        manifest_tests = list(state["manifest"].get("testNames") or [])
        unknown = [n for n in manifest_tests if n not in registered]
        unreferenced = [n for n in registered
                        if n not in manifest_tests and n not in prior_test_names]
        if len(unknown) == 1 and len(unreferenced) == 1:
            state["manifest"]["testNames"] = [
                unreferenced[0] if n == unknown[0] else n for n in manifest_tests]
            deterministic_fixes += 1
            repairs.append({
                "round": len(repairs) + 1,
                "problem": f"确定性修复：manifest 测试名 {unknown[0]} → {unreferenced[0]}"
                           f"（与实际注册一致）",
                "changedFiles": ["<buildManifest>"],
                "outcome": "deterministic-fix",
            })
            return True
        return False

    for attempt in range(8):  # 1 生成 + 5 修复 + 1 熔断重生成 + 1 兜底
        # ---- 生成 / 再生成
        if state is None:
            extra = ""
            if schema_error:
                extra = f"上次输出未通过 ChangeSet 结构校验：{schema_error}。请修正 JSON 结构。"
            elif prior_failures:
                extra = "上一版课程此任务失败原因（务必规避）：" + "; ".join(prior_failures[:4])
            response = lesson_builder.build_cpp_cmake_changeset(
                _routed_provider(provider, "reasoning"), spec, milestone_title,
                base_files, snapshot_id, snapshot_hash, prev_contract,
                extra_instructions=extra)
            budget.llm_calls += 1
            raw_changeset = response
            try:
                change_set = LessonChangeSet.model_validate(raw_changeset)
            except Exception as exc:  # noqa: BLE001
                schema_error = str(exc)[:400]
                if not budget.llm_allowed():
                    return _cpp_task_failed(
                        task_id, spec, {"instructions": {}}, repairs, [],
                        f"ChangeSet 结构不合法且预算耗尽：{schema_error}")
                continue
            ref_apply, starter_apply = compose_project_files(base_files, change_set)
            if not ref_apply.ok or not starter_apply.ok:
                conflicts = ref_apply.conflicts or starter_apply.conflicts
                # P8.2.2 确定性修复①：纯哈希类冲突 → 服务端回填 baseHash 重试
                # （LLM 抄错哈希不再消耗修复轮/重新生成）
                from app.domains.course_generation.lessons.change_applier import (
                    hash_only_conflicts,
                    repair_base_hashes,
                )

                if hash_only_conflicts(conflicts):
                    fixed_reference = repair_base_hashes(base_files, change_set.reference_changes)
                    fixed_tests = repair_base_hashes(base_files, change_set.test_changes)
                    retry_set = change_set.model_copy(update={
                        "reference_changes": fixed_reference,
                        "test_changes": fixed_tests,
                    })
                    ref2, starter2 = compose_project_files(base_files, retry_set)
                    if ref2.ok and starter2.ok:
                        deterministic_fixes += 1
                        repairs.append({
                            "round": len(repairs) + 1,
                            "problem": "确定性修复：baseHash 回填（"
                                       + str(len(conflicts)) + " 处，服务端校准）",
                            "changedFiles": sorted({c.get("filePath", "") for c in conflicts}),
                            "outcome": "deterministic-fix",
                        })
                        change_set = retry_set
                        ref_apply, starter_apply = ref2, starter2
                        conflicts = []
                if conflicts:
                    last_errors = conflicts
                    schema_error = "变更集冲突：" + "; ".join(
                        f"{c.get('errorCode')}@{c.get('filePath')}"
                        f"（期望 {str(c.get('expected'))[:60]}，实际 {str(c.get('actual'))[:60]}）"
                        for c in conflicts[:4])
                    repairs.append({"round": len(repairs) + 1,
                                    "problem": schema_error[:300],
                                    "changedFiles": sorted({c.get("filePath", "") for c in conflicts}),
                                    "outcome": "regenerated"})
                    if not budget.llm_allowed():
                        return _cpp_task_failed(
                            task_id, spec, {"instructions": {}}, repairs, [],
                            f"变更集冲突且预算耗尽：{schema_error[:300]}")
                    state = None
                    continue
            starter_overlay = {c.path: c.content for c in change_set.starter_changes
                               if c.operation in ("create", "update")}
            state = {
                "reference_files": ref_apply.files,
                "starter_overlay": starter_overlay,
                "instructions": change_set.instructions.model_dump(by_alias=True),
                "manifest": change_set.build_manifest.model_dump(by_alias=True),
                "hints": [h.model_dump(by_alias=True) for h in change_set.hints],
            }

        material = _material_from_state(state)
        # 泄露候选对齐"实际声明挖空"的文件：expectedFiles ∩ starter 变更集——
        # LLM 把前序已完成文件误列入 expectedFiles 时不误判泄露（挖空证据
        # 以 starter_changes 为准；那些文件 starter=reference 属正常继承）。
        declared_impl = set(state["starter_overlay"])
        expected_files = [p for p in (state["instructions"].get("expectedFiles") or [])
                          if p in declared_impl] or sorted(declared_impl)

        # ---- 确定性一致性验证（真实 Docker 之前）
        consistency_errors = validate_material(
            task_id, state["reference_files"],
            {**state["reference_files"], **state["starter_overlay"]},
            state["manifest"], base_files, expected_files)
        # ---- 防伪守卫（泄露/TODO/测试空转）
        guard_errors = guard_starter(
            material["starterFiles"], material["referenceFiles"], material["testFiles"],
            "cpp", expected_files=expected_files)
        guard_structured = [{"errorCode": "guard-violation", "filePath": "material",
                             "expected": "守卫规则", "actual": g[:200],
                             "suggestedRepairScope": g.split("：")[-1][:120]}
                            for g in guard_errors]

        if consistency_errors or guard_structured:
            last_errors = [*consistency_errors, *guard_structured]
            last_problems = [f"{e.get('errorCode')}: {e.get('actual')}"
                             for e in last_errors[:4]]
            _record_round(last_errors)
            # P8.2.2 确定性修复②：manifest 测试名与实际注册保守对齐
            if _deterministic_manifest_fix():
                continue
            # P8.2.2 熔断：连续两轮无净改善 → 停止补丁策略，重新生成本任务
            # （已通过任务的 Checkpoint 不受影响）
            if stagnant_rounds >= 2:
                repairs.append({
                    "round": len(repairs) + 1,
                    "problem": "修复熔断：连续两轮未减少错误——改用重新生成策略",
                    "changedFiles": [], "outcome": "circuit-break",
                })
                if budget.llm_allowed():
                    stagnant_rounds = 0
                    error_history.clear()
                    schema_error = "此前修复未收敛：" + "; ".join(last_problems[:3])
                    state = None
                    continue
                return _cpp_task_failed(
                    task_id, spec, material, repairs, [],
                    "一致性检查未通过（修复熔断且预算耗尽）：" + "; ".join(last_problems[:3]))
            if not budget.llm_allowed():
                return _cpp_task_failed(
                    task_id, spec, material, repairs, [],
                    "一致性检查未通过且修复预算耗尽：" + "; ".join(last_problems[:3]))
            repair = repair_with_agent(
                _routed_provider(provider, "repair"), spec,
                classify_failure(last_problems, [e["errorCode"] for e in last_errors]),
                last_errors, [], state["reference_files"],
                {"manifest": state["manifest"]}, budget,
                [r.get("problem", "") for r in repairs])
            if repair.ok and _apply_repair_patch(repair.patch)[0]:
                repairs.append({"round": len(repairs) + 1,
                                "problem": "; ".join(last_problems[:3]),
                                "changedFiles": [p.get("path") for p in repair.patch],
                                "outcome": "repaired"})
                continue
            return _cpp_task_failed(task_id, spec, material, repairs, [],
                                    "一致性检查未通过：" + "; ".join(last_problems[:3]))

        # ---- 八步真实验证（复用 P8.1 CMake Runtime）
        verification = verify_cpp_cmake_task(
            material, base_files, prior_test_names, is_final=is_final)
        budget.sandbox_runs += 4  # 估算：discover+ref+starter(+final)
        if verification.passed:
            manifest = state["manifest"]
            new_tests = [n for n in manifest.get("testNames") or []
                         if n not in prior_test_names]
            registry = [*prior_test_names, *new_tests]
            artifact = {
                "taskId": task_id,
                "milestoneId": spec.get("milestoneId", ""),
                "language": "cpp",
                "instructions": state["instructions"],
                "starterFiles": material["starterFiles"],
                "testFiles": material["testFiles"],
                "buildManifest": manifest,
                "hints": material["hints"],
                "status": "tests-passed",
                "verifications": verification.verifications,
                "repairs": repairs,
                "error": None,
                "generationModel": getattr(provider, "name", ""),
            }
            reference_delta = [
                {"path": p, "content": c}
                for p, c in sorted(verification.reference_files.items())
                if base_files.get(p) != c
            ]
            diagnostics = {
                "repairs": len(repairs), "llmCalls": budget.llm_calls,
                "tokensUsed": budget.tokens_used,
                "sandboxRuns": budget.sandbox_runs,
                "firstAttemptPassed": not repairs,
                "deterministicFixes": deterministic_fixes,
                "trace": [{"round": r.get("round"), "problem": (r.get("problem") or "")[:200],
                           "outcome": r.get("outcome")} for r in repairs],
            }
            if not _lease_valid(job_lease):
                return _cpp_task_failed(
                    task_id, spec, material, repairs, verification.verifications,
                    "Job 租约已失效（被接管或过期），本 worker 停止写入")
            task_spec_hash = content_hash(
                json.dumps(spec, sort_keys=True, ensure_ascii=False))
            with _session() as db:
                _persist_checkpoint(
                    db, release_id, generation_id, task_seq, task_id,
                    blueprint_hash, CHANGESET_PROTOCOL, sandbox_image,
                    "", verification.reference_files, registry,
                    artifact, reference_delta, verification.verifications, diagnostics,
                    task_spec_hash=task_spec_hash,
                    prev_snapshot_hash=snapshot_hash)
            return {
                "passed": True, "error": None, "artifact": artifact,
                "cumulative_reference": verification.reference_files,
                "prior_test_names": registry,
                "reference_delta": reference_delta,
                "diagnostics": diagnostics,
            }

        # ---- 真实验证失败 → 最小补丁修复
        verify_problems = verification.problems or ["验证未通过"]
        _record_round([{"errorCode": "verification-failure",
                        "filePath": "; ".join(verify_problems[:2]),
                        "actual": "; ".join(verify_problems[:2])}])
        verify_structured = [{
            "errorCode": "verification-failure",
            "filePath": (v.get("kind") or ""),
            "expected": "真实验证通过",
            "actual": (v.get("stderr_tail") or "")[:200] or verify_problems[0][:200],
            "suggestedRepairScope": "tests/CMakeLists.txt",
        } for v in verification.verifications if v.get("status") == "failed"][:4]
        diag_messages = [
            f"[{v.get('kind')}] {d.get('message', '')}"
            for v in verification.verifications for d in v.get("diagnostics", [])[:3]
        ][:10]
        # 相关文件 = 本任务变更的源码/头 + 全部 CMakeLists（链接/编译错误的
        # 修复需要看到声明处与实现处，而不只是测试注册）
        task_changed = {p: c for p, c in state["reference_files"].items()
                        if base_files.get(p) != c}
        relevant_for_repair = {
            p: c for p, c in task_changed.items()
            if p.endswith((".cpp", ".cc", ".hpp", ".h", ".txt", ".cmake"))}
        for must in ("CMakeLists.txt", "tests/CMakeLists.txt"):
            if must in state["reference_files"]:
                relevant_for_repair[must] = state["reference_files"][must]
        if not budget.llm_allowed():
            return _cpp_task_failed(task_id, spec, material, repairs,
                                    verification.verifications,
                                    "验证未通过且修复预算耗尽：" + "; ".join(verify_problems[:2]))
        # 熔断：验证类错误连续两轮无改善 → 重新生成当前任务变更集
        if stagnant_rounds >= 2:
            repairs.append({
                "round": len(repairs) + 1,
                "problem": "修复熔断：验证错误连续未收敛——改用重新生成策略",
                "changedFiles": [], "outcome": "circuit-break",
            })
            stagnant_rounds = 0
            error_history.clear()
            schema_error = "此前验证修复未收敛：" + "; ".join(verify_problems[:3])
            state = None
            continue
        repair = repair_with_agent(
            _routed_provider(provider, "repair"), spec,
            classify_failure(verify_problems + diag_messages),
            verify_structured or [{"errorCode": "verification-failure",
                                   "filePath": "", "expected": "通过",
                                   "actual": verify_problems[0][:200],
                                   "suggestedRepairScope": "tests/CMakeLists.txt"}],
            diag_messages or verify_problems,
            relevant_for_repair,
            {"manifest": state["manifest"]}, budget,
            [r.get("problem", "") for r in repairs])
        applied_ok = bool(repair.ok and repair.patch) and _apply_repair_patch(repair.patch)[0]
        if applied_ok:
            repairs.append({"round": len(repairs) + 1,
                            "problem": "; ".join(verify_problems[:3]),
                            "changedFiles": [p.get("path") for p in repair.patch],
                            "outcome": "repaired"})
            continue
        return _cpp_task_failed(task_id, spec, material, repairs,
                                verification.verifications,
                                "; ".join(verify_problems[:3]))

    return _cpp_task_failed(task_id, spec, {"instructions": {}}, repairs, [],
                            "修复预算耗尽")


def _cpp_task_failed(task_id: str, spec: dict, material: dict,
                     repairs: list[dict], verifications: list[dict],
                     error: str) -> dict:
    material = material or {}
    return {
        "passed": False, "error": error,
        "artifact": {
            "taskId": task_id,
            "milestoneId": spec.get("milestoneId", ""),
            "language": "cpp",
            "instructions": material.get("instructions")
            or {"title": spec.get("title", task_id)},
            "starterFiles": material.get("starterFiles") or [],
            "testFiles": material.get("testFiles") or [],
            "buildManifest": material.get("buildManifest") or {},
            "hints": material.get("hints") or [],
            "status": "failed",
            "verifications": verifications,
            "repairs": repairs,
            "error": error,
            "generationModel": "",
        },
        "cumulative_reference": {}, "prior_test_names": [], "reference_delta": [],
        "diagnostics": {"repairs": len(repairs)},
    }


def _artifact_public(artifact: LessonArtifact) -> dict:
    data = artifact.model_dump(mode="json")
    data.pop("reference_files", None)  # 受保护：剥离
    return data


def _material_context(material: dict, limit: int = 4600) -> str:
    """修复轮上下文：文件路径清单 + 常见修复对象（starter/test）的头部摘要。"""
    def inv(kind: str) -> str:
        return ", ".join(
            f"{f.get('path')}({len((f.get('content') or '').splitlines())}行)"
            for f in material.get(kind) or []) or "（无）"

    parts = [
        f"starterFiles: {inv('starterFiles')}",
        f"testFiles: {inv('testFiles')}",
        f"referenceFiles: {inv('referenceFiles')}",
    ]
    for kind in ("starterFiles", "testFiles"):
        for f in (material.get(kind) or [])[:4]:
            head = "\n".join((f.get("content") or "").splitlines()[:12])
            parts.append(f"--- {f.get('path')} 头12行 ---\n{head}")
        if len("\n".join(parts)) > limit:
            break
    return "\n".join(parts)[:limit]


def _prior_failures(db: Session, generation_id, before_version: int) -> dict[str, list[str]]:
    """收集同一 generation 此前失败 release 的逐任务问题（喂给重试生成的 LLM）。

    artifacts 里通过的条目是 camelCase（model_dump by_alias）、失败条目是
    snake_case（手工构造），两种键都兼容。
    """
    failures: dict[str, list[str]] = {}
    rows = list(db.scalars(select(CourseRelease).where(
        CourseRelease.generation_id == generation_id,
        CourseRelease.release_version < before_version,
        CourseRelease.status == "failed",
    )))
    for row in rows:
        for art in row.artifacts or []:
            if art.get("status") != "failed":
                continue
            task_id = art.get("taskId") or art.get("task_id") or ""
            if not task_id:
                continue
            problems = failures.setdefault(task_id, [])
            if art.get("error"):
                problems.append(str(art["error"])[:300])
            for rep in (art.get("repairs") or [])[-3:]:
                if rep.get("problem"):
                    problems.append(f"修复轮未解决：{str(rep['problem'])[:200]}")
        # release 级错误兜底（artifact 缺失时至少把总错误挂到失败任务上）
        tid = (row.verification_report or {}).get("failed_task")
        if tid and row.error and not failures.get(tid):
            failures[tid] = [str(row.error)[:300]]
    return {tid: probs[:6] for tid, probs in failures.items() if probs}


def _run_build_inner(release_id: uuid.UUID) -> None:
    with _session() as db:
        release = db.get(CourseRelease, release_id)
        if release is None:
            return
        blueprint = _normalize_blueprint(release.blueprint_snapshot or {})
        language = release.language
        if language not in ("python", "cpp"):
            # 防御：历史 release 行/竞态兜底（build_lessons 已提前拒绝新请求）
            _update(release_id, status="failed", progress=100,
                    error=unsupported_language_message(language))
            return
        gen = db.get(CourseGeneration, release.generation_id)
        snapshot_files = (gen.snapshot or {}).get("files", {}) if gen else {}
        # 重试上下文：此前失败 release 的逐任务问题（喂给本轮 LLM 规避）
        prior = _prior_failures(db, release.generation_id, release.release_version)

    provider = _provider()
    order = _task_order(blueprint)
    total = len(order)
    artifacts_public: list[dict] = []
    reference_store: dict[str, list[dict]] = {}
    cumulative_reference: dict[str, str] = {}   # 累积参考快照（连续性核心）
    all_test_files: dict[str, str] = {}         # 累积测试（回归用）
    prior_test_names: list[str] = []            # P8.2：cpp 课程累积 CTest 回归名
    ms_titles = {m["milestoneId"]: m["title"] for m in blueprint.get("milestones") or []}
    passed_count = 0

    # ---- P8.2.1：Job 持久化 + Checkpoint 兼容复用（断点续生成）----
    from app.domains.course_generation.lessons.change_set import CHANGESET_PROTOCOL
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )
    blueprint_hash = snapshot_hash_of(
        {"blueprint": json.dumps(blueprint, sort_keys=True, ensure_ascii=False)})
    job_lease = _claim_job(release_id, release.generation_id)
    if job_lease is None:
        _update(release_id, status="failed", progress=100,
                error="另一 worker 正在生成该版本（Job 租约冲突），稍后重试")
        return
    job_id = job_lease[0]
    reused_tasks: list[str] = []
    compatible_checkpoints: dict[str, dict] = {}
    if language == "cpp":
        compatible_checkpoints = load_compatible_checkpoints(
            release.generation_id, blueprint_hash, CHANGESET_PROTOCOL,
            "projectweave-sandbox-cpp:clang15-bookworm", "")

    for index, spec in enumerate(order):
        task_id = spec["taskId"]
        _lease_renew(job_lease)
        _update(release_id, status="verifying", current_task=task_id,
                progress=int(index * 90 / max(total, 1)))

        evidence = {}
        for ev in spec.get("sourceEvidence") or []:
            path = ev.get("path", "")
            if path in snapshot_files:
                evidence[path] = snapshot_files[path]

        if language == "cpp":
            # ---- P8.2.1：C++ 增量流水线（Checkpoint 复用 → 生成 → 八步验证）----
            checkpoint = compatible_checkpoints.get(task_id)
            if checkpoint is not None:
                # 断点恢复：直接复用已真实验证的任务（不调 LLM）
                cumulative_reference = checkpoint["snapshot_files"]
                prior_test_names = checkpoint["test_registry"]
                reference_store[task_id] = checkpoint["reference_delta"]
                artifacts_public.append(checkpoint["artifact"])
                passed_count += 1
                reused_tasks.append(task_id)
                _update(release_id, current_task=task_id)
                continue

            outcome = _process_cpp_task(
                provider, release_id, release.generation_id, blueprint_hash,
                index, task_id, spec,
                ms_titles.get(spec.get("milestoneId"), ""),
                cumulative_reference, prior_test_names, evidence,
                prior.get(task_id), index == total - 1,
                job_lease=job_lease,
            )
            _job_update(job_id, current_task=task_id,
                        completed_task_ids=[a["taskId"] for a in artifacts_public
                                            if a.get("status") == "tests-passed"],
                        reused_task_ids=reused_tasks)
            if not outcome["passed"]:
                artifacts_public.append(outcome["artifact"])
                _update(release_id, status="failed",
                        error=f"任务 {task_id} 验证失败：{outcome['error']}",
                        artifacts=[*artifacts_public], reference_store=reference_store,
                        progress=100, current_task=task_id,
                        verification_report={"passed": passed_count, "total": total,
                                             "failed_task": task_id})
                _job_update(job_id, status="failed",
                            error=f"任务 {task_id} 验证失败：{outcome['error']}")
                return
            cumulative_reference = outcome["cumulative_reference"]
            prior_test_names = outcome["prior_test_names"]
            reference_store[task_id] = outcome["reference_delta"]
            artifacts_public.append(outcome["artifact"])
            passed_count += 1
            continue

        material = lesson_builder.build_task_lesson(
            provider, spec, ms_titles.get(spec.get("milestoneId"), ""),
            cumulative_reference, evidence, language,
            prior_failures=prior.get(task_id),
        )
        repairs: list[dict] = []
        verifications: list[dict] = []
        artifact_status = "generated"
        error_msg = None

        for attempt in range(MAX_REPAIR_PER_TASK + 1):
            # -- schema-valid：Pydantic 校验 + 防伪守卫
            try:
                artifact = _coerce_artifact(material, spec, language)
            except Exception as exc:
                error_msg = f"材料结构不合法：{exc}"
                if attempt < MAX_REPAIR_PER_TASK:
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [{"kind": "schema", "message": error_msg}], language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": [], "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            problems = guard_starter(
                material.get("starterFiles") or [],
                material.get("referenceFiles") or [],
                material.get("testFiles") or [],
                language,
                expected_files=(material.get("instructions") or {}).get("expectedFiles"),
            )
            if problems:
                error_msg = "防伪守卫：" + "; ".join(problems[:3])
                if attempt < MAX_REPAIR_PER_TASK:
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [{"kind": "guard", "message": p} for p in problems]
                        + [{"kind": "material-context", "message":
                            "当前生成的文件清单与摘要（修复必须针对这些文件）：\n"
                            + _material_context(material)}],
                        language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": [], "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            # -- build/tests：真实沙箱验证参考实现
            ref_files = merge_files(cumulative_reference,
                                    {f["path"]: f["content"] for f in material["referenceFiles"]})
            task_tests = {f["path"]: f["content"] for f in material["testFiles"]}
            run_files = {**ref_files, **task_tests}
            outcome = run_in_sandbox(
                language, run_files, "test", None,
                list(task_tests.keys()), timeout_s=60.0,
            )
            verifications.append({**outcome.to_dict(), "kind": "reference-tests"})
            if outcome.status != "passed":
                error_msg = f"参考实现测试未通过：{outcome.failed}/{outcome.total} 失败"
                # -- regression：前阶段测试在当前参考上（回归证据）
                if all_test_files:
                    reg_files = {**ref_files, **all_test_files}
                    reg = run_in_sandbox(language, reg_files, "test", None,
                                         list(all_test_files.keys()), timeout_s=60.0)
                    verifications.append({**reg.to_dict(), "kind": "regression"})
                if attempt < MAX_REPAIR_PER_TASK:
                    detail_errors = [
                        {"kind": v.get("kind") or "test", "message": v.get("message", "")}
                        for v in outcome.diagnostics
                    ] or [{"kind": "test", "message": error_msg}]
                    detail_errors.append({
                        "kind": "stdout",
                        "message": (outcome.stdout_tail or "")[-1500:],
                    })
                    detail_errors.append({
                        "kind": "stderr",
                        "message": (outcome.stderr_tail or "")[-800:],
                    })
                    material = lesson_builder.repair_task_lesson(
                        provider, material, detail_errors, language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": sorted(set(material.get("referenceFiles", []) and
                                                              [f["path"] for f in material["referenceFiles"]] +
                                                              [f["path"] for f in material.get("testFiles", [])])),
                                    "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            # 通过：starter 期望失败证据（测试有效性 + 不泄露答案）
            starter_run = {**merge_files(cumulative_reference,
                                          {f["path"]: f["content"] for f in material["starterFiles"]}),
                           **task_tests}
            starter_outcome = run_in_sandbox(
                language, starter_run, "test", None,
                list(task_tests.keys()), timeout_s=45.0,
            )
            starter_ok = starter_outcome.status == "failed" or starter_outcome.failed > 0
            verifications.append({
                **starter_outcome.to_dict(),
                "kind": "starter-expected-fail",
                "status": "passed" if starter_ok else "failed",
            })
            if not starter_ok:
                # starter 全过 = 测试对本任务核心无效（答案泄露或测试空转）
                error_msg = "starter 全部测试通过——测试未覆盖本任务待实现逻辑（疑似泄露/空转）"
                if attempt < MAX_REPAIR_PER_TASK:
                    leak_context = json.dumps({
                        "starter": {f["path"]: f["content"][:1200] for f in material.get("starterFiles", [])},
                        "tests": {f["path"]: f["content"][:1200] for f in material.get("testFiles", [])},
                    }, ensure_ascii=False)
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [
                            {"kind": "starter-passes",
                             "message": error_msg + "。当前 starter 与测试内容：" + leak_context[:6000]
                             + "。修复方向：starter 必须删除本任务核心实现只留 TODO 骨架（保留接口签名/文档字符串）；或者测试必须新增针对待实现功能的断言。"},
                        ], language)
                    continue
                artifact_status = "failed"
                break

            # 成功：更新修复轮结论 + 累积快照
            if repairs:
                repairs[-1]["outcome"] = "fixed"
            cumulative_reference = ref_files
            all_test_files.update(task_tests)
            artifact_status = "tests-passed"
            error_msg = None

            artifact.status = artifact_status
            reference_store[task_id] = [{"path": f["path"], "content": f["content"]}
                                        for f in material["referenceFiles"]]
            art_dict = _coerce_artifact(material, spec, language).model_dump(mode="json", by_alias=True)
            art_dict["status"] = artifact_status
            art_dict["verifications"] = verifications
            art_dict["repairs"] = repairs
            art_dict["error"] = None
            art_dict.pop("reference_files", None)
            artifacts_public.append(art_dict)
            passed_count += 1
            break

        if artifact_status != "tests-passed":
            art_dict = {
                "task_id": task_id,
                "milestone_id": spec.get("milestoneId", ""),
                "language": language,
                "instructions": material.get("instructions") or
                                {"title": spec.get("title", task_id)},
                "starter_files": material.get("starterFiles") or [],
                "test_files": material.get("testFiles") or [],
                "hints": material.get("hints") or [],
                "status": "failed",
                "verifications": verifications,
                "repairs": repairs,
                "error": error_msg,
                "artifact_version": attempt + 1 if 'attempt' in dir() else 1,
                "generation_model": getattr(provider, "name", ""),
            }
            artifacts_public.append(art_dict)
            _update(release_id, status="failed", error=f"任务 {task_id} 验证失败：{error_msg}",
                    artifacts=artifacts_public, reference_store=reference_store,
                    progress=100, current_task=task_id,
                    verification_report={"passed": passed_count, "total": total,
                                         "failed_task": task_id})
            return

    # ---- 最终集成
    if language == "cpp":
        # P8.2：cpp 的最终集成（全量 CTest + demo 运行）已在最后一个任务的
        # 八步验证内完成（verify_cpp_cmake_task is_final）；此处只汇总报告。
        _update(release_id, status="verifying", progress=92)
        final_record = next(
            (v for a in artifacts_public for v in a.get("verifications", [])
             if v.get("kind") == "final-integration"), {})
        report = {
            "passed": passed_count, "total": total,
            "finalIntegration": final_record or {"status": "unknown"},
            "taskRefinement": (release.verification_report or {}).get("taskRefinement"),
        }
        if not final_record or final_record.get("status") != "passed":
            _update(release_id, status="failed",
                    error="最终集成验证未通过（全部 CTest）",
                    artifacts=artifacts_public, verification_report=report, progress=100)
            _job_update(job_id, status="failed", error="最终集成验证未通过")
            return
        if not _lease_valid(job_lease):
            _job_update(job_id, status="failed",
                        error="Job 租约失效，ready 发布被拒绝（数据未损坏）")
            return
        _update(release_id, status="ready", progress=100, current_task=None,
                artifacts=artifacts_public, reference_store=reference_store,
                verification_report={
                    **report,
                    "diagnostics": {"reusedTasks": reused_tasks,
                                    "llmSavedByReuse": len(reused_tasks)},
                }, ready_at=utcnow())
        _job_update(job_id, status="completed", reused_task_ids=reused_tasks)
        return

    # python：全部任务测试在最终参考快照上一次通过
    _update(release_id, status="verifying", progress=92)
    final = run_in_sandbox(language, {**cumulative_reference, **all_test_files},
                           "test", None, list(all_test_files.keys()), timeout_s=90.0)
    report = {
        "passed": passed_count, "total": total,
        "finalIntegration": final.to_dict(),
    }
    if final.status != "passed":
        _update(release_id, status="failed",
                error=f"最终集成验证未通过（{final.failed}/{final.total} 失败）",
                artifacts=artifacts_public, verification_report=report, progress=100)
        return

    _update(release_id, status="ready", progress=100, current_task=None,
            artifacts=artifacts_public, reference_store=reference_store,
            verification_report=report, ready_at=utcnow())


def _task_description(artifact: dict | None, spec: dict) -> str:
    instructions = (artifact or {}).get("instructions") or {}
    return (instructions.get("goal") or instructions.get("context")
            or spec.get("description", ""))[:900]


def _coerce_artifact(material: dict, spec: dict, language: str) -> LessonArtifact:
    instructions = dict(material.get("instructions") or {})
    instructions.setdefault("title", spec.get("title", ""))
    return LessonArtifact(
        task_id=spec["taskId"],
        milestone_id=spec.get("milestoneId", ""),
        language=language,
        instructions=instructions,
        starter_files=material.get("starterFiles") or [],
        test_files=material.get("testFiles") or [],
        reference_files=material.get("referenceFiles") or [],
        hints=material.get("hints") or [],
        status="schema-valid",
        generation_model="",
    )
