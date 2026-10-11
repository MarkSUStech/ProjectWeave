"""课程生成服务（P7.1）：后台流水线 + 进度持久化 + 发布。

流水线（独立线程，状态单调推进并落库，前端轮询）：
pending → fetching（快照+SHA+LICENSE）→ analyzing（Agent 分层分析）
→ generating（蓝图 Agent + 确定性验证 + ≤2 修复轮）→ draft →（publish）published
任何阶段失败 → failed（记录 stage 与原因，可重试）。
身份说明：owner 仍为 dev-user 占位——开发环境单用户；生产多用户隔离
属 P8 认证阶段（D41 明确不宣称已实现）。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runtime import agent_record_to_dicts as _unused  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.domains.course_generation.analysis.repository_analyzer import run_analysis
from app.domains.course_generation.generation.blueprint_generator import (
    run_blueprint_generation,
    run_blueprint_repair,
)
from app.domains.course_generation.models import CourseGeneration, STAGE_PROGRESS
from app.domains.course_generation.schemas import (
    CourseBlueprint,
    GenerationCreate,
    ValidationResult,
)
from app.domains.course_generation.sources.github_adapter import (
    GitHubAdapter,
    GitHubAdapterError,
)
from app.domains.course_generation.validation.blueprint_validator import validate_blueprint

MAX_REPAIR_ROUNDS = 2


class CourseGenerationError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


class CourseGenerationNotFoundError(KeyError):
    pass


# 测试注入点
_session_factory = SessionLocal
_provider_factory = None  # None → app.ai.provider.get_provider
_adapter_factory = None  # None → GitHubAdapter()


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def set_provider_factory(factory) -> None:
    global _provider_factory
    _provider_factory = factory


def set_adapter_factory(factory) -> None:
    global _adapter_factory
    _adapter_factory = factory


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_provider():
    if _provider_factory is not None:
        return _provider_factory()
    from app.ai.provider import get_provider

    return get_provider()


def _get_adapter() -> GitHubAdapter:
    if _adapter_factory is not None:
        return _adapter_factory()
    return GitHubAdapter()


# ---------------------------------------------------------------- 创建/查询/操作


def create_generation(db: Session, payload: GenerationCreate, owner_id: str = "dev-user") -> CourseGeneration:
    # URL 语法先校验（失败即 422，不排队假任务）
    GitHubAdapter().fetch_snapshot  # noqa: B018（仅确保可导入）
    from app.domains.course_generation.sources.github_adapter import parse_github_url

    owner, repo = parse_github_url(payload.repository_url)
    if not getattr(settings, "execution_enabled", True):
        raise CourseGenerationError("课程生成已禁用")

    row = CourseGeneration(
        owner_id=owner_id,
        source_url=payload.repository_url.strip(),
        status="pending",
        repo_owner=owner,
        repo_name=repo,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    threading.Thread(target=_run_pipeline, args=(row.id,), daemon=True,
                     name=f"pw-coursegen-{row.id.hex[:8]}").start()
    return row


def get_generation(db: Session, gen_id) -> CourseGeneration:
    try:
        gen_uuid = uuid.UUID(str(gen_id))
    except ValueError:
        raise CourseGenerationNotFoundError(gen_id) from None
    row = db.get(CourseGeneration, gen_uuid)
    if row is None:
        raise CourseGenerationNotFoundError(gen_id)
    return row


def retry_generation(db: Session, gen_id) -> CourseGeneration:
    """失败重试：从 pending 重新跑（已落库的快照/分析将被覆盖重建）。"""
    row = get_generation(db, gen_id)
    if row.status not in ("failed",):
        raise CourseGenerationError("仅失败的任务可以重试")
    row.status = "pending"
    row.stage = None
    row.error = None
    row.progress = 0
    db.commit()
    db.refresh(row)
    threading.Thread(target=_run_pipeline, args=(row.id,), daemon=True).start()
    return row


def revalidate(db: Session, gen_id) -> CourseGeneration:
    """重新执行确定性验证（要求蓝图已生成）。"""
    row = get_generation(db, gen_id)
    if row.blueprint is None:
        raise CourseGenerationError("蓝图尚未生成，无法验证")
    row.validation = _validate_row_blueprint(row).model_dump(mode="json")
    db.commit()
    db.refresh(row)
    return row


def publish(db: Session, gen_id) -> CourseGeneration:
    """发布审核通过的蓝图（draft→published；不标记为已验证可运行课程）。"""
    row = get_generation(db, gen_id)
    if row.blueprint is None:
        raise CourseGenerationError("蓝图尚未生成")
    if row.validation is None or not row.validation.get("passed"):
        raise CourseGenerationError("验证未通过，不能发布（先修复 error 项）")
    if row.status == "published":
        return row  # 幂等
    # 转换为 curriculum 任务规格（P7.2 项目实例化使用；含 needs-starter-code 标记）
    blueprint = CourseBlueprint.model_validate(row.blueprint)
    published_tasks = [
        {
            "taskId": t.task_id,
            "milestone": _ms_order(blueprint, t.milestone_id),
            "title": t.title,
            "description": t.description,
            "dependsOn": t.depends_on,
            "requiredConcepts": t.required_concepts,
            "deliverable": "; ".join(t.deliverables),
            "effortBand": "medium",
            "testFiles": [],  # P7.1 未生成可执行测试——如实为空
            "starterFiles": [],
            "acceptanceCriteria": t.acceptance_criteria,
            "hints": [{"level": i + 1, "text": h} for i, h in enumerate(t.hints_outline[:4])],
            "vizSuggestion": "",
            "sourceEvidence": [s.model_dump(by_alias=True) for s in t.source_evidence],
        }
        for t in blueprint.tasks
    ]
    row.published_tasks = published_tasks
    row.published_at = utcnow()
    row.status = "published"
    db.commit()
    db.refresh(row)
    return row


def _ms_order(blueprint: CourseBlueprint, milestone_id: str) -> int:
    for index, ms in enumerate(blueprint.milestones, 1):
        if ms.milestone_id == milestone_id:
            return index
    return 1


# ---------------------------------------------------------------- 流水线


def _set_stage(row_id, stage: str, status: str | None = None, error: str | None = None,
               **fields) -> None:
    try:
        with _session_factory() as db:
            row = db.get(CourseGeneration, row_id)
            if row is None:
                return
            row.stage = stage
            row.progress = STAGE_PROGRESS.get(stage, row.progress)
            if status:
                row.status = status
            if error is not None:
                row.error = error
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        pass


def _fail(row_id, stage: str, message: str) -> None:
    _set_stage(row_id, stage, status="failed", error=message)


def _run_pipeline(row_id: uuid.UUID) -> None:
    try:
        _run_pipeline_inner(row_id)
    except GitHubAdapterError as exc:
        _fail(row_id, "fetching", str(exc))
    except Exception as exc:  # 未知异常 → failed，绝不伪装成功
        _fail(row_id, None, f"生成流水线内部错误：{exc}")


def _run_pipeline_inner(row_id: uuid.UUID) -> None:
    with _session_factory() as db:
        row = db.get(CourseGeneration, row_id)
        if row is None:
            return
        url = row.source_url

    # ---- fetching
    _set_stage(row_id, "fetching", status="fetching")
    adapter = _get_adapter()
    snap = adapter.fetch_snapshot(url)
    snapshot_dict = adapter.to_dict(snap)
    warnings = []
    if snap.license.get("needs_review"):
        warnings.append(snap.license.get("note") or "许可证需人工审查")
    if snap.stats.get("content_truncated"):
        warnings.append("仓库内容超快照限额，部分文件未纳入分析")
    _set_stage(row_id, "fetching",
               repo_owner=snap.owner, repo_name=snap.repo,
               commit_sha=snap.commit_sha, default_branch=snap.default_branch,
               license_info=snap.license,
               repo_meta={"description": snap.meta.get("description"),
                          "language": snap.meta.get("language"),
                          "topics": snap.meta.get("topics")},
               snapshot=snapshot_dict, warnings=warnings)

    # ---- analyzing（真实 LLM Agent；分析内容视为不可信数据——
    #      提示词已声明数据边界，见 repository_analyzer.ANALYSIS_SYSTEM_PROMPT）
    _set_stage(row_id, "analyzing", status="analyzing")
    provider = _get_provider()
    analysis, tool_calls = run_analysis(provider, snapshot_dict)
    _set_stage(row_id, "analyzing", analysis=analysis, analysis_tool_calls=tool_calls)

    # ---- generating（蓝图 + 确定性验证 + 修复轮）
    _set_stage(row_id, "generating", status="generating")
    with _session_factory() as db:
        from app.domains.concepts.models import KnowledgeConcept

        known = list(db.scalars(select(KnowledgeConcept.id)))
    source_files = sorted(snapshot_dict["files"].keys())
    blueprint_dict, _gen_tools = run_blueprint_generation(
        provider, {
            "url": url, "owner": snap.owner, "repo": snap.repo,
            "commitSha": snap.commit_sha, "license": snap.license,
        },
        analysis, known, source_files,
    )
    row_fields = {"blueprint": blueprint_dict}

    # ---- validating（确定性；初始结果先落库，再进入 ≤2 修复轮）
    _set_stage(row_id, "validating", status="validating", **row_fields)
    blueprint = CourseBlueprint.model_validate(blueprint_dict)
    result = validate_blueprint(blueprint, source_files, set(known),
                                bool(snap.license.get("needs_review")))
    _set_stage(row_id, "validating",
               blueprint=blueprint.model_dump(mode="json"),
               validation=result.model_dump(mode="json"))
    repairs = 0
    while not result.passed and repairs < MAX_REPAIR_ROUNDS:
        repairs += 1
        try:
            blueprint_dict = run_blueprint_repair(
                provider, blueprint.model_dump(mode="json"),
                [i.model_dump() for i in result.issues if i.severity == "error"],
            )
            blueprint = CourseBlueprint.model_validate(blueprint_dict)
            result = validate_blueprint(blueprint, source_files, set(known),
                                        bool(snap.license.get("needs_review")))
            _set_stage(row_id, "validating",
                       blueprint=blueprint.model_dump(mode="json"),
                       validation=result.model_dump(mode="json"),
                       repair_rounds=repairs)
        except Exception:
            break  # 修复轮失败：保留最后一次有效验证结果，如实标记失败
    _set_stage(row_id, "draft" if result.passed else "validating",
               status="draft" if result.passed else "failed",
               error=None if result.passed else
               "蓝图验证未通过（修复轮耗尽）：" +
               "; ".join(i.message for i in result.issues if i.severity == "error")[:400],
               repair_rounds=repairs)


def _validate_row_blueprint(row: CourseGeneration) -> ValidationResult:
    blueprint = CourseBlueprint.model_validate(row.blueprint)
    with _session_factory() as db:
        from app.domains.concepts.models import KnowledgeConcept

        known = set(db.scalars(select(KnowledgeConcept.id)))
    source_files = sorted((row.snapshot or {}).get("files", {}).keys())
    return validate_blueprint(blueprint, source_files, known,
                              bool((row.license_info or {}).get("needs_review")))
