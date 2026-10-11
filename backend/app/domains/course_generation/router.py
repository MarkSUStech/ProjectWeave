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
                             artifacts=[ArtifactPublicRead.model_validate(a) for a in (row.artifacts or [])])


releases_router = APIRouter(prefix="/course-releases", tags=["course-generation"])


@releases_router.get("/{release_id}", response_model=ReleaseDetailRead)
def get_release(release_id: str, db: Session = Depends(get_db)) -> ReleaseDetailRead:
    try:
        row = lesson_publisher.get_release(db, _parse_id(release_id))
    except lesson_publisher.ReleaseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    base = _release_read(row)
    return ReleaseDetailRead(**base.model_dump(),
                             artifacts=[ArtifactPublicRead.model_validate(a) for a in (row.artifacts or [])])


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
