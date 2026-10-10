"""API 路由聚合。"""

from fastapi import APIRouter

from app.domains.assessments.router import project_scoped as assessments_project_router
from app.domains.assessments.router import router as assessments_router
from app.domains.concepts.router import router as concepts_router
from app.domains.curriculum.router import router as curriculum_router
from app.domains.events.router import router as events_router
from app.domains.learner.router import router as learner_router
from app.domains.settings.router import router as settings_router
from app.domains.tutor.router import router as tutor_router
from app.domains.projects.file_router import (
    project_router as project_files_extra_router,
)
from app.domains.projects.file_router import router as project_files_router
from app.domains.projects.router import router as projects_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(projects_router)
api_router.include_router(project_files_router)
api_router.include_router(project_files_extra_router)
api_router.include_router(concepts_router)
api_router.include_router(assessments_router)
api_router.include_router(assessments_project_router)
api_router.include_router(learner_router)
api_router.include_router(curriculum_router)
api_router.include_router(events_router)
api_router.include_router(tutor_router)
api_router.include_router(settings_router)


@api_router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
