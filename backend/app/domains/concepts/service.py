"""知识图业务逻辑：DAG 校验、查询、幂等种子。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.concepts.models import KnowledgeConcept
from app.domains.concepts.seed import SEED_CONCEPTS


class ConceptNotFoundError(Exception):
    def __init__(self, concept_id: str) -> None:
        super().__init__(f"concept not found: {concept_id}")


def validate_graph(concepts: dict[str, list[str]]) -> None:
    """校验先修图：无悬空引用、无环（设计文档 5.3：不得产生不可解释的循环先修）。"""
    for concept_id, prerequisites in concepts.items():
        for prerequisite in prerequisites:
            if prerequisite not in concepts:
                raise ValueError(f"悬空的先修引用：{concept_id} -> {prerequisite}")
            if prerequisite == concept_id:
                raise ValueError(f"概念不能以自身为先修：{concept_id}")

    # DFS 三色标记检测环
    state: dict[str, int] = {}  # 0=未访问 1=访问中 2=完成

    def visit(node: str) -> None:
        mark = state.get(node, 0)
        if mark == 1:
            raise ValueError(f"先修关系存在环，涉及概念：{node}")
        if mark == 2:
            return
        state[node] = 1
        for prerequisite in concepts[node]:
            visit(prerequisite)
        state[node] = 2

    for concept_id in concepts:
        visit(concept_id)


def list_concepts(db: Session, domain: str | None = None) -> list[KnowledgeConcept]:
    stmt = select(KnowledgeConcept).order_by(KnowledgeConcept.domain, KnowledgeConcept.id)
    if domain is not None:
        stmt = stmt.where(KnowledgeConcept.domain == domain)
    return list(db.scalars(stmt))


def get_concept(db: Session, concept_id: str) -> KnowledgeConcept:
    concept = db.get(KnowledgeConcept, concept_id)
    if concept is None:
        raise ConceptNotFoundError(concept_id)
    return concept


def ensure_seed_concepts(db: Session) -> int:
    """空表时写入种子概念（幂等），返回写入数量。

    种子内容是确定性模板（围绕样板课程的初始知识图），
    升级种子时在 seed.py 中递增 version 字段。
    """
    validate_graph({c["id"]: c["prerequisites"] for c in SEED_CONCEPTS})
    existing = db.scalar(select(func.count()).select_from(KnowledgeConcept))
    if (existing or 0) > 0:
        return 0
    db.add_all(
        KnowledgeConcept(
            id=c["id"],
            title=c["title"],
            domain=c["domain"],
            description=c["description"],
            prerequisites=c["prerequisites"],
            objectives=c["objectives"],
            assessment_methods=c["assessment_methods"],
            examples=c["examples"],
            version=c["version"],
        )
        for c in SEED_CONCEPTS
    )
    db.commit()
    return len(SEED_CONCEPTS)
