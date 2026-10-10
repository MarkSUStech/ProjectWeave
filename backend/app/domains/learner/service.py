"""学习证据与掌握估计的业务逻辑（确定性管线，无 LLM）。

流程对应设计 6.5 的 EvidenceValidator → MasteryUpdater → ConfidenceCalculator：
- 校验证据（概念存在、维度与证据类型匹配）；
- 估计 = 该维度全部证据的通过率（推断值，非客观分数）；
- 置信度随证据数保守递增并封顶（0.9），低置信在界面显示"尚不确定"。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.concepts.models import KnowledgeConcept
from app.domains.learner.models import (
    MASTERY_MODEL_VERSION,
    LearningEvidence,
    LearnerMastery,
)

# 证据类型 → 可影响的维度（预测题反映理解；其余维度待后续证据类型接入）
EVIDENCE_DIMENSIONS = {
    "prediction": "understanding",
    "explanation": "understanding",
    "coding": "application",
    "debugging": "debugging",
    "transfer": "independence",
}

CONFIDENCE_BASE = 0.3
CONFIDENCE_STEP = 0.2
CONFIDENCE_MAX = 0.9


def dimension_of(evidence_type: str) -> str | None:
    return EVIDENCE_DIMENSIONS.get(evidence_type)


def _confidence_of(evidence_count: int) -> float:
    return round(min(CONFIDENCE_MAX, CONFIDENCE_BASE + CONFIDENCE_STEP * evidence_count), 2)


def record_evidence(
    db: Session,
    owner_id: str,
    concept_id: str,
    evidence_type: str,
    outcome: str,
    rubric_version: str = "",
    source_kind: str = "assessment",
    source_id=None,
    item_id: str | None = None,
) -> None:
    """写入一条证据并更新对应维度的掌握估计（EvidenceValidator→Updater→Confidence）。"""
    dimension = dimension_of(evidence_type)
    if dimension is None:
        raise ValueError(f"未知证据类型：{evidence_type}")
    if outcome not in ("passed", "failed"):
        raise ValueError(f"未知证据结果：{outcome}")
    if db.get(KnowledgeConcept, concept_id) is None:
        raise ValueError(f"概念不存在：{concept_id}")

    db.add(
        LearningEvidence(
            owner_id=owner_id,
            concept_id=concept_id,
            evidence_type=evidence_type,
            outcome=outcome,
            rubric_version=rubric_version,
            source_kind=source_kind,
            source_id=source_id,
            item_id=item_id,
        )
    )
    db.flush()

    history = list(
        db.scalars(
            select(LearningEvidence).where(
                LearningEvidence.owner_id == owner_id,
                LearningEvidence.concept_id == concept_id,
                LearningEvidence.evidence_type == evidence_type,
            )
        )
    )
    passed = sum(1 for e in history if e.outcome == "passed")
    total = len(history)
    estimate = round(passed / total, 2)

    mastery = db.scalar(
        select(LearnerMastery).where(
            LearnerMastery.owner_id == owner_id, LearnerMastery.concept_id == concept_id
        )
    )
    if mastery is None:
        mastery = LearnerMastery(owner_id=owner_id, concept_id=concept_id, dimensions={})
        db.add(mastery)
    dimensions = dict(mastery.dimensions or {})
    dimensions[dimension] = {
        "estimate": estimate,
        "confidence": _confidence_of(total),
        "evidenceCount": total,
        "lastObservedAt": history[-1].created_at.isoformat(),
    }
    mastery.dimensions = dimensions
    mastery.model_version = MASTERY_MODEL_VERSION
    db.commit()


def list_mastery(db: Session, owner_id: str) -> list[LearnerMastery]:
    return list(
        db.scalars(
            select(LearnerMastery)
            .where(LearnerMastery.owner_id == owner_id)
            .order_by(LearnerMastery.concept_id)
        )
    )
