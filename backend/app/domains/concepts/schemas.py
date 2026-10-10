"""知识概念的 API 契约。"""

from datetime import datetime

from pydantic import Field

from app.domains.projects.schemas import APIModel


class ConceptRead(APIModel):
    id: str = Field(max_length=100)
    title: str
    domain: str
    description: str
    prerequisites: list[str]
    objectives: list[str]
    assessment_methods: list[str]
    examples: list[str]
    version: int
    updated_at: datetime


class ConceptList(APIModel):
    items: list[ConceptRead]
    total: int
    domains: list[str]
