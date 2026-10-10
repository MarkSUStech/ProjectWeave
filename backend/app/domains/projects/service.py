"""projects 领域的业务逻辑。

只做确定性操作（校验、持久化、版本号维护），
不包含任何 AI 调用——那是后续 Tutor/Project Engine 分析阶段的事。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.projects.models import Project
from app.domains.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"project not found: {project_id}")


def parse_project_id(project_id: str) -> uuid.UUID:
    """将路径参数解析为 UUID；非法格式视为资源不存在（404）。"""
    try:
        return uuid.UUID(project_id)
    except ValueError:
        raise ProjectNotFoundError(project_id) from None


# 规格相关字段：修改其中任意字段会提升 spec_version，供前端提示“规格已变更”。
SPEC_FIELDS = {
    "title",
    "description",
    "mode",
    "complexity",
    "target_features",
    "non_goals",
    "stack",
    "milestones",
    "acceptance_criteria",
}


def create_project(db: Session, payload: ProjectCreate, owner_id: str = "dev-user") -> Project:
    project = Project(
        owner_id=owner_id,
        title=payload.title,
        description=payload.description,
        mode=payload.mode.value,
        complexity=payload.complexity.value,
        target_features=payload.target_features,
        non_goals=payload.non_goals,
        stack=payload.stack,
        milestones=[m.model_dump(mode="json") for m in payload.milestones],
        acceptance_criteria=payload.acceptance_criteria,
    )
    db.add(project)
    db.flush()  # 生成项目 id，供初始脚手架文件引用
    from app.domains.projects.file_service import starter_files_for

    db.add_all(starter_files_for(project))
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, parse_project_id(project_id))
    if project is None:
        raise ProjectNotFoundError(project_id)
    return project


def list_projects(db: Session, owner_id: str | None = None) -> list[Project]:
    stmt = select(Project).order_by(Project.created_at.desc(), Project.id.desc())
    if owner_id is not None:
        stmt = stmt.where(Project.owner_id == owner_id)
    return list(db.scalars(stmt))


def update_project(db: Session, project_id: str, payload: ProjectUpdate) -> Project:
    project = get_project(db, project_id)
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    spec_changed = False
    for field, value in changes.items():
        setattr(project, field, value)
        if field in SPEC_FIELDS:
            spec_changed = True
    if spec_changed:
        project.spec_version += 1
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: str) -> None:
    project = get_project(db, project_id)
    # 显式删除关联文件：SQLite 默认不级联外键，跨库行为保持一致。
    from sqlalchemy import delete

    from app.domains.projects.models import ProjectFile

    db.execute(delete(ProjectFile).where(ProjectFile.project_id == project.id))
    db.delete(project)
    db.commit()
