"""课程路由：学习路线查询/重规划 + 阶段任务验收（设计 §13.1 evaluate）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.curriculum import service
from app.domains.curriculum.schemas import (
    EvaluationResultRead,
    EvaluationSuiteInput,
    PlanDetailRead,
    PlanRead,
    PlanTaskRead,
)
from app.domains.curriculum.service import PlanError
from app.domains.projects.service import ProjectNotFoundError, parse_project_id

router = APIRouter(prefix="/plans", tags=["curriculum"])
tasks_scoped = APIRouter(prefix="/projects/{project_id}/tasks", tags=["curriculum"])


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


@tasks_scoped.post(
    "/{task_id}/evaluate",
    response_model=EvaluationResultRead,
    summary="阶段任务验收（测试套件全绿 = 通过；确定性判定，非 AI）",
)
def evaluate_task(
    project_id: str,
    task_id: str,
    payload: EvaluationSuiteInput,
    db: Session = Depends(get_db),
) -> EvaluationResultRead:
    from app.domains.projects.service import get_project

    try:
        pid = parse_project_id(project_id)
        get_project(db, project_id)  # 项目存在性校验（404）
        task, passed, _blocked = service.evaluate_task(
            db,
            pid,
            task_id,
            payload.model_dump(by_alias=True),
        )
    except (PlanError, ProjectNotFoundError) as exc:
        raise HTTPException(status_code=getattr(exc, "status", 404), detail=str(exc)) from exc

    # 学习证据（§6.5）：coding 证据影响 application 维（D19 映射）；
    # 失败同样是证据——估计如实反映，不粉饰。
    from app.domains.learner.service import record_evidence

    concepts = list(task.required_concepts or [])
    for concept_id in concepts:
        record_evidence(
            db,
            owner_id="dev-user",
            concept_id=concept_id,
            evidence_type="coding",
            outcome="passed" if passed else "failed",
            rubric_version=f"eval:{service.EVALUATION_RUBRIC_VERSION}",
            source_kind="task",
            item_id=task.task_id,
        )

    # 事件（D21 编排模式：router 层追加）
    from datetime import datetime, timezone

    from app.domains.events.service import append_event
    from app.domains.events.service import server_event_id

    append_event(
        db,
        event_id=server_event_id(
            "task-evaluated", str(task.project_id), task.task_id, task.status, payload.traceId or ""
        ),
        type="task-evaluated",
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{task.project_id}",
        project_id=task.project_id,
        payload={
            "taskId": task.task_id,
            "passed": passed,
            "totalFiles": payload.totalFiles,
            "totalPassed": payload.totalPassed,
            "totalFailed": payload.totalFailed,
            "errorFiles": payload.errorFiles,
            "traceId": payload.traceId,
        },
    )
    return EvaluationResultRead(
        taskId=task.task_id,
        status=task.status,
        passed=passed,
        rubricVersion=service.EVALUATION_RUBRIC_VERSION,
        evidenceConcepts=concepts,
    )
