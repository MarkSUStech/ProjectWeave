"""课程生成 REST API（P7.1）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.course_generation import service
from app.domains.course_generation.lessons import lesson_publisher
from app.domains.course_generation.lessons.schemas import (
    ArtifactPublicRead,
    InstantiateRequest,
    InstantiateResponse,
    ReleaseDetailRead,
    ReleaseRead,
)
from app.domains.course_generation.schemas import (
    GenerationAnalysisRead,
    GenerationBlueprintRead,
    GenerationCreated,
    GenerationCreate,
    GenerationPublishRead,
    GenerationRead,
)
from app.domains.course_generation.sources.github_adapter import GitHubAdapterError

router = APIRouter(prefix="/course-generations", tags=["course-generation"])


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None


def _to_read(row) -> GenerationRead:
    return GenerationRead(
        id=row.id, source_url=row.source_url, status=row.status,
        stage=row.stage, progress=row.progress, error=row.error,
        warnings=row.warnings or [], repo_owner=row.repo_owner,
        repo_name=row.repo_name, commit_sha=row.commit_sha,
        default_branch=row.default_branch, license=row.license_info,
        stats=(row.snapshot or {}).get("stats"),
        repair_rounds=row.repair_rounds, published_at=row.published_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.post("", response_model=GenerationCreated, status_code=202)
def create(payload: GenerationCreate, db: Session = Depends(get_db)) -> GenerationCreated:
    try:
        row = service.create_generation(db, payload)
    except GitHubAdapterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except service.CourseGenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return GenerationCreated(id=row.id, status=row.status, progress=row.progress)


@router.get("/{gen_id}", response_model=GenerationRead)
def get(gen_id: str, db: Session = Depends(get_db)) -> GenerationRead:
    try:
        return _to_read(service.get_generation(db, _parse_id(gen_id)))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None


@router.get("/{gen_id}/analysis", response_model=GenerationAnalysisRead)
def get_analysis(gen_id: str, db: Session = Depends(get_db)) -> GenerationAnalysisRead:
    try:
        row = service.get_generation(db, _parse_id(gen_id))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None
    return GenerationAnalysisRead(
        id=row.id, status=row.status,
        analysis=row.analysis, tool_calls=row.analysis_tool_calls or [],
    )


@router.get("/{gen_id}/blueprint", response_model=GenerationBlueprintRead)
def get_blueprint(gen_id: str, db: Session = Depends(get_db)) -> GenerationBlueprintRead:
    try:
        row = service.get_generation(db, _parse_id(gen_id))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None
    return GenerationBlueprintRead(
        id=row.id, status=row.status,
        blueprint=row.blueprint, validation=row.validation,
    )


@router.post("/{gen_id}/validate", response_model=GenerationBlueprintRead)
def revalidate(gen_id: str, db: Session = Depends(get_db)) -> GenerationBlueprintRead:
    try:
        row = service.revalidate(db, _parse_id(gen_id))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None
    except service.CourseGenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return GenerationBlueprintRead(
        id=row.id, status=row.status, blueprint=row.blueprint, validation=row.validation,
    )


@router.post("/{gen_id}/retry", response_model=GenerationRead)
def retry(gen_id: str, db: Session = Depends(get_db)) -> GenerationRead:
    try:
        return _to_read(service.retry_generation(db, _parse_id(gen_id)))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None
    except service.CourseGenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.post("/{gen_id}/publish", response_model=GenerationPublishRead)
def publish(gen_id: str, db: Session = Depends(get_db)) -> GenerationPublishRead:
    try:
        row = service.publish(db, _parse_id(gen_id))
    except service.CourseGenerationNotFoundError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None
    except service.CourseGenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return GenerationPublishRead(
        id=row.id, status=row.status, published_at=row.published_at,
        task_count=len(row.published_tasks or []),
        milestone_count=len({t["milestone"] for t in (row.published_tasks or [])}),
    )


# ---------------------------------------------------------------- P7.2 课程内容/发布/实例化


def _public_artifact(a: dict) -> ArtifactPublicRead:
    """公开材料：剥离 H4（答案级帮助走 Tutor Gate）与参考实现相关字段。"""
    data = dict(a)
    hints = [h for h in (data.get("hints") or []) if (h.get("level") or h.get("hintLevel") or 1) <= 3]
    data["hints"] = hints
    return ArtifactPublicRead.model_validate(data)


def _release_read(row) -> ReleaseRead:
    artifacts = row.artifacts or []
    passed = sum(1 for a in artifacts if a.get("status") == "tests-passed")
    failed = sum(1 for a in artifacts if a.get("status") in ("failed", "unsupported"))
    return ReleaseRead(
        id=row.id, generation_id=row.generation_id,
        release_version=row.release_version, status=row.status,
        language=row.language, total_tasks=len(artifacts),
        passed_tasks=passed, failed_tasks=failed,
        progress=row.progress, current_task=row.current_task,
        error=row.error, course_title=row.course_title,
        ready_at=row.ready_at, created_at=row.created_at,
        verification_report=row.verification_report or {},
    )


@router.post("/{gen_id}/build-lessons", response_model=ReleaseRead, status_code=202)
def build_lessons(gen_id: str, db: Session = Depends(get_db)) -> ReleaseRead:
    try:
        row = lesson_publisher.build_lessons(db, _parse_id(gen_id))
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _release_read(row)


@router.get("/{gen_id}/releases", response_model=list[ReleaseRead])
def list_releases(gen_id: str, db: Session = Depends(get_db)) -> list[ReleaseRead]:
    try:
        return [_release_read(r) for r in lesson_publisher.list_releases(db, _parse_id(gen_id))]
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.get("/{gen_id}/lessons", response_model=ReleaseDetailRead)
def get_lessons(gen_id: str, db: Session = Depends(get_db)) -> ReleaseDetailRead:
    releases = lesson_publisher.list_releases(db, _parse_id(gen_id))
    if not releases:
        raise HTTPException(status_code=404, detail="尚无课程内容（先 build-lessons）")
    row = releases[0]
    base = _release_read(row)
    return ReleaseDetailRead(**base.model_dump(),
                             artifacts=[_public_artifact(a) for a in (row.artifacts or [])])


releases_router = APIRouter(prefix="/course-releases", tags=["course-generation"])


@releases_router.get("/{release_id}", response_model=ReleaseDetailRead)
def get_release(release_id: str, db: Session = Depends(get_db)) -> ReleaseDetailRead:
    try:
        row = lesson_publisher.get_release(db, _parse_id(release_id))
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    base = _release_read(row)
    return ReleaseDetailRead(**base.model_dump(),
                             artifacts=[_public_artifact(a) for a in (row.artifacts or [])])


@releases_router.get("/{release_id}/checkpoints")
def list_checkpoints(release_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """已验证检查点（公开信息：任务/序号/测试注册/时间——不含参考快照）。"""
    from sqlalchemy import select as _select

    from app.domains.course_generation.models import CourseCheckpoint

    try:
        release = lesson_publisher.get_release(db, _parse_id(release_id))
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    rows = db.scalars(_select(CourseCheckpoint).where(
        CourseCheckpoint.generation_id == release.generation_id
    ).order_by(CourseCheckpoint.task_seq))
    return [{
        "taskId": r.task_id, "taskSeq": r.task_seq,
        "testNames": list((r.artifact or {}).get("buildManifest", {}).get("testNames", [])),
        "verifiedAt": r.created_at.isoformat() if r.created_at else "",
        "protocolVersion": r.protocol_version,
    } for r in rows]


@releases_router.post("/{release_id}/resume", response_model=ReleaseRead, status_code=202)
def resume_release(release_id: str, db: Session = Depends(get_db)) -> ReleaseRead:
    """从最后一个已验证检查点继续：新建 release 版本（不覆盖旧版），
    已验证任务直接复用（不调 LLM），仅重新生成失败任务起的剩余部分。"""
    try:
        release = lesson_publisher.get_release(db, _parse_id(release_id))
        if release.status == "ready":
            raise HTTPException(status_code=422, detail="该版本已就绪，无需恢复")
        if release.language != "cpp":
            raise HTTPException(status_code=422, detail="仅 C++ 课程支持检查点恢复")
        row = lesson_publisher.build_lessons(db, str(release.generation_id))
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return _release_read(row)


@releases_router.post("/{release_id}/tasks/{task_id}/retry", response_model=ReleaseRead, status_code=202)
def retry_task(release_id: str, task_id: str, db: Session = Depends(get_db)) -> ReleaseRead:
    """单任务重试 = 从检查点恢复（该任务之前的已验证任务全部复用）。"""
    return resume_release(release_id, db)


@releases_router.post("/{release_id}/instantiate", response_model=InstantiateResponse, status_code=201)
def instantiate(release_id: str, payload: InstantiateRequest | None = None,
                db: Session = Depends(get_db)) -> InstantiateResponse:
    try:
        result = lesson_publisher.instantiate_project(
            db, _parse_id(release_id),
            title=(payload.project_title if payload else None),
        )
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    return InstantiateResponse(**result)


# ---------------------------------------------------------------- P7.3 学习生命周期

from app.domains.course_generation.lessons import lifecycle as lc


project_course_router = APIRouter(prefix="/projects", tags=["course-generation"])


@project_course_router.get("/{project_id}/course-progress")
def get_course_progress(project_id: str, db: Session = Depends(get_db)):
    try:
        return lc.compute_lifecycle_status(db, _parse_id(project_id))
    except lc.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@project_course_router.post("/{project_id}/tasks/{task_id}/activate")
def activate_task(project_id: str, task_id: str, db: Session = Depends(get_db)):
    try:
        return lc.activate_task(db, _parse_id(project_id), task_id)
    except lc.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@project_course_router.get("/{project_id}/final-report")
def get_final_report(project_id: str, db: Session = Depends(get_db)):
    try:
        return lc.final_verification_report(db, _parse_id(project_id))
    except lc.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


# ---------------------------------------------------------------- P7.3 描述驱动课程生成


@router.post("/from-project", response_model=GenerationCreated, status_code=202)
def generate_from_project(
    payload: dict,
    db: Session = Depends(get_db),
) -> GenerationCreated:
    """从项目规格（描述/栈/功能）生成课程——不依赖 GitHub。"""
    from app.domains.course_generation import service as gen_service

    try:
        row = gen_service.create_from_project_spec(db, payload)
    except gen_service.CourseGenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"创建失败：{exc}") from None
    return GenerationCreated(id=row.id, status=row.status, progress=row.progress)
