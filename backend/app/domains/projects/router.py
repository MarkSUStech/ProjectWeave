"""projects 领域的 HTTP 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.projects import service
from app.domains.projects.schemas import (
    ProjectCreate,
    ProjectList,
    ProjectRead,
    ProjectUpdate,
)
from app.domains.projects.service import ProjectNotFoundError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建项目目标与初始规格",
)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    project = service.create_project(db, payload)
    return ProjectRead.model_validate(project)


@router.get("", response_model=ProjectList, summary="项目列表")
def list_projects(db: Session = Depends(get_db)) -> ProjectList:
    projects = service.list_projects(db)
    return ProjectList(items=[ProjectRead.model_validate(p) for p in projects], total=len(projects))


@router.get("/{project_id}", response_model=ProjectRead, summary="项目详情")
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectRead:
    try:
        project = service.get_project(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead, summary="更新项目规格")
def update_project(
    project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> ProjectRead:
    try:
        project = service.update_project(db, project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除项目")
def delete_project(project_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        service.delete_project(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
