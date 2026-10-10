"""学习者模型契约。"""

from datetime import datetime

from pydantic import Field

from app.domains.projects.schemas import APIModel


class DimensionEstimate(APIModel):
    """单维度估计：系统推断值 + 置信度（低置信应显示"尚不确定"）。"""

    estimate: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidenceCount: int = Field(ge=1)
    lastObservedAt: str


class MasteryRead(APIModel):
    concept_id: str
    dimensions: dict[str, DimensionEstimate]
    model_version: str
    updated_at: datetime


class MasteryList(APIModel):
    items: list[MasteryRead]
    total: int
