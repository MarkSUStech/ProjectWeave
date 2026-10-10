"""知识概念的路由（只读；写入属于课程内容管理，走种子与后续 CMS）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.concepts import service
from app.domains.concepts.schemas import ConceptList, ConceptRead
from app.domains.concepts.service import ConceptNotFoundError

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("", response_model=ConceptList, summary="概念列表（可按 domain 过滤）")
def list_concepts(
    domain: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
) -> ConceptList:
    concepts = service.list_concepts(db, domain)
    return ConceptList(
        items=[ConceptRead.model_validate(c) for c in concepts],
        total=len(concepts),
        domains=sorted({c.domain for c in concepts}),
    )


@router.get("/{concept_id}", response_model=ConceptRead, summary="概念详情")
def get_concept(concept_id: str, db: Session = Depends(get_db)) -> ConceptRead:
    try:
        concept = service.get_concept(db, concept_id)
    except ConceptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="concept not found") from exc
    return ConceptRead.model_validate(concept)
