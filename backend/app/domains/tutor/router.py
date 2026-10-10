"""Tutor 路由：教学回合与决策历史。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.provider import get_provider
from app.core.db import get_db
from app.domains.projects.service import parse_project_id
from app.domains.tutor import service
from app.domains.tutor.schemas import (
    TutorDecisionList,
    TutorDecisionRead,
    TutorTurnRequest,
    TutorTurnResponse,
)
from app.domains.tutor.service import TutorError

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post(
    "/turns",
    response_model=TutorTurnResponse,
    status_code=status.HTTP_201_CREATED,
    summary="教学回合（上下文组装 → LLM 提案 → Policy Gate，含 H4 门控）",
)
def create_turn(payload: TutorTurnRequest, db: Session = Depends(get_db)) -> TutorTurnResponse:
    try:
        provider = get_provider()
    except Exception as exc:  # ProviderDisabledError / ProviderError
        raise HTTPException(status_code=503, detail=f"AI 未配置或不可用：{exc}") from exc
    try:
        decision = service.create_turn(
            db,
            str(payload.projectId),
            payload.question,
            provider,
            request_answer_level=payload.requestAnswerLevel,
        )
    except TutorError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception as exc:  # 网络/认证等 ProviderError
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{exc}") from exc

    # 学习事件：tutor-turn（含决策摘要，不存全文）
    from datetime import datetime, timezone

    from app.domains.events.service import append_event, server_event_id

    append_event(
        db,
        event_id=server_event_id("tutor-turn", str(decision.id)),
        type="tutor-turn",
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{decision.project_id}",
        project_id=decision.project_id,
        payload={
            "intent": decision.intent,
            "hintLevel": decision.hint_level,
            "outcome": decision.outcome,
            "trigger": decision.trigger,
            "answerRequested": payload.requestAnswerLevel,
            "tokens": decision.prompt_tokens + decision.completion_tokens,
        },
    )
    return TutorTurnResponse(decision=TutorDecisionRead.model_validate(decision))


@router.get(
    "/suggestions",
    response_model=TutorTurnResponse | None,
    summary="主动建议（按介入模式与失败证据，冷却 60s）",
)
def get_suggestion(
    projectId: str = Query(max_length=64), db: Session = Depends(get_db)
) -> TutorTurnResponse | None:
    try:
        provider = get_provider()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI 未配置或不可用：{exc}") from exc
    try:
        decision, _reason = service.get_suggestion(db, projectId, provider)
    except TutorError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{exc}") from exc
    if decision is None:
        return None
    # 自动建议同样记事件（trigger=auto）
    from datetime import datetime, timezone

    from app.domains.events.service import append_event, server_event_id

    append_event(
        db,
        event_id=server_event_id("tutor-turn", str(decision.id)),
        type="tutor-turn",
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{decision.project_id}",
        project_id=decision.project_id,
        payload={
            "intent": decision.intent,
            "hintLevel": decision.hint_level,
            "outcome": decision.outcome,
            "trigger": "auto",
            "answerRequested": False,
            "tokens": decision.prompt_tokens + decision.completion_tokens,
        },
    )
    return TutorTurnResponse(decision=TutorDecisionRead.model_validate(decision))


@router.get("/decisions", response_model=TutorDecisionList, summary="教学决策历史")
def list_decisions(
    projectId: str = Query(max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> TutorDecisionList:
    decisions = service.list_decisions(db, parse_project_id(projectId), limit)
    return TutorDecisionList(
        items=[TutorDecisionRead.model_validate(d) for d in decisions], total=len(decisions)
    )
