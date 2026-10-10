"""诊断业务逻辑：选题、确定性判定、概念级估计。

无 LLM 参与：选题按项目技术栈映射域 + 概念图拓扑深度排序，
判定与题库比对，估计按保守三档规则（P2.3 引入置信度与证据模型）。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.assessments.models import AssessmentAnswer, AssessmentSession
from app.domains.assessments.question_bank import QUESTION_BANK, QUESTION_BANK_VERSION
from app.domains.concepts.models import KnowledgeConcept
from app.domains.projects.service import ProjectNotFoundError, get_project, parse_project_id

MAX_ITEMS = 8

LABEL_LIKELY_MASTERED = "likely-mastered"
LABEL_UNCERTAIN = "uncertain"
LABEL_LIKELY_GAP = "likely-gap"


class AssessmentError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


class AssessmentNotFoundError(AssessmentError):
    def __init__(self, session_id) -> None:
        super().__init__(f"assessment session not found: {session_id}", status=404)


def _domains_for_stack(stack: list[str]) -> set[str]:
    """项目技术栈 → 诊断域（设计 6.4：范围由项目需求反推，不做通用语言考试）。"""
    joined = " ".join(stack).lower()
    frontend_markers = ("typescript", "javascript", "react", "vue", "next", "vite", "html", "css")
    if any(marker in joined for marker in frontend_markers):
        return {"javascript", "typescript", "browser", "engineering"}
    return {"javascript", "engineering"}


def _concept_depths(db: Session) -> dict[str, int]:
    """计算每个概念的最长先修链长度（拓扑深度）；图无环由 concepts 域保证。"""
    concepts = list(db.scalars(select(KnowledgeConcept)))
    by_id = {c.id: list(c.prerequisites) for c in concepts}
    depths: dict[str, int] = {}

    def depth(concept_id: str, visiting: set[str]) -> int:
        if concept_id in depths:
            return depths[concept_id]
        if concept_id in visiting:
            return 0  # 防御：异常数据按 0 处理
        visiting.add(concept_id)
        prerequisites = by_id.get(concept_id, [])
        value = 1 + max((depth(p, visiting) for p in prerequisites), default=-1)
        visiting.discard(concept_id)
        depths[concept_id] = value
        return value

    for concept_id in by_id:
        depth(concept_id, set())
    return depths


def select_items(db: Session, stack: list[str]) -> list[dict]:
    """按域过滤题库，概念拓扑深度 + 难度排序，每概念取一题，上限 MAX_ITEMS。"""
    domains = _domains_for_stack(stack)
    depths = _concept_depths(db)
    candidates = [q for q in QUESTION_BANK if q["domain"] in domains]
    candidates.sort(
        key=lambda q: (
            depths.get(q["conceptId"], 0),
            q["difficulty"],
            q["id"],
        )
    )
    picked: list[dict] = []
    seen_concepts: set[str] = set()
    for question in candidates:
        if question["conceptId"] in seen_concepts:
            continue
        picked.append(question)
        seen_concepts.add(question["conceptId"])
        if len(picked) >= MAX_ITEMS:
            break
    return picked


def start_session(db: Session, project_id: str) -> AssessmentSession:
    try:
        project = get_project(db, project_id)
    except ProjectNotFoundError as exc:
        raise AssessmentError("project not found", status=404) from exc
    items = select_items(db, list(project.stack))
    if not items:
        raise AssessmentError("题库没有覆盖该项目技术栈的题目", status=422)
    session = AssessmentSession(
        project_id=project.id,
        status="in-progress",
        selected_items=[
            {"itemId": q["id"], "conceptId": q["conceptId"], "bankVersion": QUESTION_BANK_VERSION}
            for q in items
        ],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id) -> AssessmentSession:
    session = db.get(AssessmentSession, parse_uuid(session_id))
    if session is None:
        raise AssessmentNotFoundError(session_id)
    return session


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise AssessmentNotFoundError(value) from None


def list_sessions(db: Session, project_id: str) -> list[AssessmentSession]:
    pid = parse_uuid(project_id)
    return list(
        db.scalars(
            select(AssessmentSession)
            .where(AssessmentSession.project_id == pid)
            .order_by(AssessmentSession.created_at.desc())
        )
    )


def submit_session(
    db: Session, session_id: str, answers: list[dict]
) -> AssessmentSession:
    """提交作答：确定性判定、写答案行、计算概念三档估计并落库。"""
    session = get_session(db, session_id)
    if session.status == "completed":
        raise AssessmentError("该诊断已提交，不能重复提交", status=409)

    selected_ids = [entry["itemId"] for entry in session.selected_items]
    by_item = {a["itemId"]: a["selectedOptionIndex"] for a in answers}
    if set(by_item) != set(selected_ids):
        missing = set(selected_ids) - set(by_item)
        extra = set(by_item) - set(selected_ids)
        detail = []
        if missing:
            detail.append(f"缺少作答：{sorted(missing)}")
        if extra:
            detail.append(f"未知题目：{sorted(extra)}")
        raise AssessmentError("；".join(detail), status=422)

    bank_by_id = {q["id"]: q for q in QUESTION_BANK}
    per_concept: dict[str, list[bool]] = {}
    question_results = []
    for entry in session.selected_items:
        question = bank_by_id.get(entry["itemId"])
        if question is None:  # 题库演进防御：历史会话题目被移除
            raise AssessmentError(f"题目已不在题库中：{entry['itemId']}", status=422)
        selected = by_item[entry["itemId"]]
        if not isinstance(selected, int) or not 0 <= selected < len(question["options"]):
            raise AssessmentError(f"非法选项：{entry['itemId']}", status=422)
        correct = selected == question["answerIndex"]
        per_concept.setdefault(entry["conceptId"], []).append(correct)
        db.add(
            AssessmentAnswer(
                session_id=session.id,
                item_id=entry["itemId"],
                concept_id=entry["conceptId"],
                selected_option_index=selected,
                correct=correct,
            )
        )
        question_results.append(
            {
                "itemId": entry["itemId"],
                "conceptId": entry["conceptId"],
                "correct": correct,
                "selectedOptionIndex": selected,
                "correctOptionIndex": question["answerIndex"],
            }
        )

    results = []
    for concept_id, outcomes in per_concept.items():
        correct_count = sum(outcomes)
        total = len(outcomes)
        if correct_count == total:
            label = LABEL_LIKELY_MASTERED
        elif correct_count == 0:
            label = LABEL_LIKELY_GAP
        else:
            label = LABEL_UNCERTAIN
        results.append(
            {
                "conceptId": concept_id,
                "label": label,
                "correctCount": correct_count,
                "total": total,
            }
        )
    # 与选题顺序保持一致，便于展示
    order = {entry["conceptId"]: index for index, entry in enumerate(session.selected_items)}
    results.sort(key=lambda r: order.get(r["conceptId"], 0))
    session.results = {"concepts": results, "questions": question_results}
    session.status = "completed"
    from app.domains.assessments.models import utcnow

    session.completed_at = utcnow()
    db.commit()
    db.refresh(session)
    return session
