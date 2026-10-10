"""诊断路由：开始、提交、查询、项目历史。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.assessments import service
from app.domains.assessments.question_bank import QUESTION_BANK
from app.domains.assessments.schemas import (
    AssessmentSessionBrief,
    AssessmentSessionList,
    AssessmentSessionRead,
    AssessmentStartRequest,
    AssessmentSubmitRequest,
)
from app.domains.assessments.service import AssessmentError

router = APIRouter(prefix="/assessments", tags=["assessments"])
project_scoped = APIRouter(prefix="/projects/{project_id}/assessments", tags=["assessments"])


def _bank_item(item_id: str) -> dict:
    return next(q for q in QUESTION_BANK if q["id"] == item_id)


def _session_read(session) -> AssessmentSessionRead:
    items = [
        {
            "itemId": entry["itemId"],
            "conceptId": entry["conceptId"],
            "prompt": question["prompt"],
            "options": question["options"],
            "difficulty": question["difficulty"],
        }
        for entry in session.selected_items
        if (question := _bank_item(entry["itemId"])) is not None
    ]
    return AssessmentSessionRead(
        id=session.id,
        projectId=session.project_id,
        status=session.status,
        items=items,
        results=session.results,
        createdAt=session.created_at,
        completedAt=session.completed_at,
    )


@router.post(
    "/start",
    response_model=AssessmentSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="开始能力诊断（按项目技术栈选题）",
)
def start_assessment(payload: AssessmentStartRequest, db: Session = Depends(get_db)):
    try:
        session = service.start_session(db, str(payload.projectId))
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _session_read(session)


@router.post(
    "/{session_id}/submit",
    response_model=AssessmentSessionRead,
    summary="提交作答（确定性判定 + 概念三档估计）",
)
def submit_assessment(
    session_id: str, payload: AssessmentSubmitRequest, db: Session = Depends(get_db)
):
    try:
        answers = [a.model_dump(by_alias=True) for a in payload.answers]
        session = service.submit_session(db, session_id, answers)
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    # 学习证据与掌握估计更新：编排在 router 层，领域 service 互不依赖（设计 6.5 管线）。
    from app.domains.assessments.question_bank import QUESTION_BANK_VERSION
    from app.domains.learner.service import record_evidence

    for question in session.results["questions"]:
        record_evidence(
            db,
            owner_id="dev-user",
            concept_id=question["conceptId"],
            evidence_type="prediction",
            outcome="passed" if question["correct"] else "failed",
            rubric_version=f"bank-v{QUESTION_BANK_VERSION}",
            source_kind="assessment",
            source_id=session.id,
            item_id=question["itemId"],
        )
    db.refresh(session)

    # 学习事件：诊断提交（摘要 + 概念计数，不存题目细节）
    from datetime import datetime, timezone

    from app.domains.events.service import append_event, server_event_id

    concepts = session.results["concepts"]
    append_event(
        db,
        event_id=server_event_id("assessment-submitted", str(session.id)),
        type="assessment-submitted",
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{session.project_id}",
        project_id=session.project_id,
        payload={
            "sessionId": str(session.id),
            "questions": len(session.results["questions"]),
            "mastered": sum(1 for c in concepts if c["label"] == "likely-mastered"),
            "uncertain": sum(1 for c in concepts if c["label"] == "uncertain"),
            "gap": sum(1 for c in concepts if c["label"] == "likely-gap"),
        },
    )
    return _session_read(session)


@router.get("/{session_id}", response_model=AssessmentSessionRead, summary="诊断会话详情")
def get_assessment(session_id: str, db: Session = Depends(get_db)):
    try:
        session = service.get_session(db, session_id)
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _session_read(session)


@project_scoped.get("", response_model=AssessmentSessionList, summary="项目的诊断历史")
def list_assessments(project_id: str, db: Session = Depends(get_db)):
    sessions = service.list_sessions(db, project_id)
    return AssessmentSessionList(
        items=[
            AssessmentSessionBrief(
                id=s.id,
                status=s.status,
                createdAt=s.created_at,
                completedAt=s.completed_at,
                results=s.results,
            )
            for s in sessions
        ],
        total=len(sessions),
    )
