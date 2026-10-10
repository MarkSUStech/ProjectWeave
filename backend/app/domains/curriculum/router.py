"""课程规划路由（设计 13.1：/plans/{projectId} 与 replan）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.curriculum import service
from app.domains.curriculum.schemas import PlanDetailRead, PlanRead, PlanTaskRead
from app.domains.curriculum.service import PlanError
from app.domains.projects.service import parse_project_id

router = APIRouter(prefix="/plans", tags=["curriculum"])


def _plan_read(plan) -> PlanRead:
    return PlanRead.model_validate(plan)


@router.get("/{project_id}", response_model=PlanDetailRead, summary="当前学习路线（无则生成 v1）")
def get_plan(project_id: str, db: Session = Depends(get_db)) -> PlanDetailRead:
    try:
        pid = parse_project_id(project_id)
        plan = service.generate_plan(db, project_id)
        tasks = service.list_tasks(db, pid)
    except PlanError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    _append_plan_event(db, plan, "plan-generated")
    return PlanDetailRead(
        plan=_plan_read(plan),
        tasks=[PlanTaskRead.model_validate(t) for t in tasks],
    )


@router.post("/{project_id}/replan", response_model=PlanRead, summary="重新规划（新版本，保留历史）")
def replan(project_id: str, db: Session = Depends(get_db)) -> PlanRead:
    try:
        plan = service.generate_plan(db, project_id, bump=True)
    except PlanError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    _append_plan_event(db, plan, "plan-replanned")
    return _plan_read(plan)


def _append_plan_event(db: Session, plan, event_type: str) -> None:
    from datetime import datetime, timezone

    from app.domains.events.service import append_event, server_event_id

    append_event(
        db,
        event_id=server_event_id(event_type, str(plan.id)),
        type=event_type,
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{plan.project_id}",
        project_id=plan.project_id,
        payload={
            "planVersion": plan.plan_version,
            "activities": len(plan.activities),
            "skipped": len(plan.skipped),
        },
    )
