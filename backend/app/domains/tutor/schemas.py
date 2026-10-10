"""Tutor 契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domains.projects.schemas import APIModel


class TutorExtrasInput(APIModel):
    """前端随请求提供的最小编辑上下文（§10.3 最小化采集）。"""
    currentTaskId: str | None = Field(default=None, max_length=100)
    currentCode: dict | None = None  # {path, content}（content 服务端截断到 2000 字符）
    recentRunResult: dict | None = None  # {status, summary}


class TutorTurnRequest(APIModel):
    projectId: UUID
    question: str = Field(min_length=1, max_length=2000)
    # 用户明确请求答案级帮助（H4，设计 §8.3）；未勾选时 Gate 拒绝 H4 提案
    requestAnswerLevel: bool = False
    extras: TutorExtrasInput | None = None


class WorkspaceActionRead(APIModel):
    kind: str
    level: str = Field(pattern="^A[012]$")
    reason: str
    payload: dict


class TutorDecisionRead(APIModel):
    id: UUID
    project_id: UUID
    question: str
    trigger: str
    intent: str
    hint_level: int
    message: str
    target_concepts: list[str]
    explanation: str
    confidence: float
    outcome: str
    outcome_reason: str
    workspace_actions: list[WorkspaceActionRead] = Field(default_factory=list)
    policy_version: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    created_at: datetime


class TutorTurnResponse(APIModel):
    decision: TutorDecisionRead


class TutorDecisionList(APIModel):
    items: list[TutorDecisionRead]
    total: int
