"""诊断会话的 API 契约。作答判定为确定性规则，不涉及 LLM。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domains.projects.schemas import APIModel


class AssessmentItemPublic(APIModel):
    """下发到客户端的题目：绝不包含 answerIndex。"""

    itemId: str
    conceptId: str
    prompt: str
    options: list[str]
    difficulty: int = Field(ge=1, le=3)


class AssessmentStartRequest(APIModel):
    projectId: UUID


class AssessmentAnswerInput(APIModel):
    itemId: str = Field(min_length=1, max_length=100)
    selectedOptionIndex: int = Field(ge=0, le=3)


class AssessmentSubmitRequest(APIModel):
    answers: list[AssessmentAnswerInput] = Field(min_length=1)


class ConceptResultRead(APIModel):
    conceptId: str
    label: str
    correctCount: int
    total: int


class QuestionResultRead(APIModel):
    itemId: str
    conceptId: str
    correct: bool
    selectedOptionIndex: int
    correctOptionIndex: int


class AssessmentResults(APIModel):
    concepts: list[ConceptResultRead]
    questions: list[QuestionResultRead]


class AssessmentSessionRead(APIModel):
    id: UUID
    projectId: UUID
    status: str
    items: list[AssessmentItemPublic]
    results: AssessmentResults | None = None
    createdAt: datetime
    completedAt: datetime | None = None


class AssessmentSessionBrief(APIModel):
    id: UUID
    status: str
    createdAt: datetime
    completedAt: datetime | None
    results: AssessmentResults | None = None


class AssessmentSessionList(APIModel):
    items: list[AssessmentSessionBrief]
    total: int
