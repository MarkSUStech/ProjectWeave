"""课程规划：任务图种子 + 规则化学习路线生成（设计 §7.2/7.3）。

规划器为确定性规则（无 LLM）：
- 沿任务依赖拓扑序展开；
- 每个任务的知识要求扩展为先修闭包；
- 掌握判断：understanding 缺失 → 学习；estimate < 0.75 或 confidence ≤ 0.5 → 补课；
  已掌握（≥0.75 且高置信）→ 跳过并记录原因（设计 7.3：路线变更可解释）。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.concepts.models import KnowledgeConcept
from app.domains.curriculum.models import LearningPlan, ProjectTask
from app.domains.curriculum.pilot_course import PILOT_COURSE_TASKS, PILOT_TEST_FILE_CONTENTS
from app.domains.curriculum.templates import SAMPLE_COURSE_TASKS
from app.domains.learner.models import LearningEvidence, LearnerMastery
from app.domains.projects.service import ProjectNotFoundError, get_project

# 掌握判定阈值（保守规则；权重调优依赖后续实验，见设计 7.2）
MASTERY_ESTIMATE_THRESHOLD = 0.75
MASTERY_CONFIDENCE_THRESHOLD = 0.5


class PlanError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


class PlanNotFoundError(PlanError):
    def __init__(self, project_id) -> None:
        super().__init__(f"plan not found for project: {project_id}", status=404)


def _course_tasks_for(project) -> tuple[list[dict], dict[str, str]]:
    """按项目模板选择课程（P5.1，D39）：返回 (任务列表, 测试文件内容表)。

    - ts-markdown-v1 → TS 试点课程（原样保留）
    - cpp-pointers-v1 → C++ 指针课程
    - 其他（python-starter-v1/无课程模板）→ 空课程（学习路线如实为空）
    """
    from app.domains.projects.templates import get_template, resolve_template

    template = get_template(project.template_id) or resolve_template(project.stack)
    if template.course_id == "cpp-pointers-v1":
        from app.domains.curriculum.cpp_course import CPP_COURSE_TASKS, CPP_TEST_FILE_CONTENTS

        return CPP_COURSE_TASKS, CPP_TEST_FILE_CONTENTS
    if template.course_id == "ts-markdown-v1":
        return PILOT_COURSE_TASKS, PILOT_TEST_FILE_CONTENTS
    return [], {}


def seed_project_tasks(db: Session, project_id) -> int:
    """按项目模板种子课程任务图 + 初始代码与测试文件；幂等。

    - 已有任务：跳过（重规划/重启不重复种子，也不覆盖用户代码）；
    - 文件种子只在**路径不存在**时写入——任何情况下不覆盖已有文件
      （包括用户对种子文件的修改）；
    - 无课程模板（如 Python）：不种任务，学习路线诚实为空。
    """
    existing = db.scalar(
        select(func.count()).select_from(ProjectTask).where(ProjectTask.project_id == project_id)
    )
    if (existing or 0) > 0:
        return 0

    from app.domains.projects.models import Project as ProjectModel
    from app.domains.projects.service import get_project

    project = get_project(db, str(project_id))
    tasks, test_contents = _course_tasks_for(project)
    if not tasks:
        return 0

    db.add_all(
        ProjectTask(
            project_id=project_id,
            task_id=t["taskId"],
            milestone=t["milestone"],
            title=t["title"],
            description=t["description"],
            depends_on=t.get("dependsOn", []),
            required_concepts=t.get("requiredConcepts", []),
            deliverable=t.get("deliverable", ""),
            effort_band=t.get("effortBand", "medium"),
            test_files=t.get("testFiles", []),
            starter_files=t.get("starterFiles", []),
            acceptance_criteria=t.get("acceptanceCriteria", []),
            hints=t.get("hints", []),
            viz_suggestion=t.get("vizSuggestion", ""),
        )
        for t in tasks
    )
    # 种子初始代码与测试文件到 project_files（只在路径不存在时写——不覆盖用户代码）
    from app.domains.projects.models import ProjectFile

    existing_paths = set(
        db.scalars(select(ProjectFile.path).where(ProjectFile.project_id == project_id))
    )
    for task in tasks:
        for starter in task.get("starterFiles", []):
            if starter["path"] not in existing_paths:
                db.add(
                    ProjectFile(
                        project_id=project_id,
                        path=starter["path"],
                        content=starter["content"],
                    )
                )
                existing_paths.add(starter["path"])
        for test_path in task.get("testFiles", []):
            content = test_contents.get(test_path, "")
            if content and test_path not in existing_paths:
                db.add(ProjectFile(project_id=project_id, path=test_path, content=content))
                existing_paths.add(test_path)
    db.commit()
    return len(tasks)


def list_tasks(db: Session, project_id) -> list[ProjectTask]:
    return list(
        db.scalars(
            select(ProjectTask)
            .where(ProjectTask.project_id == project_id)
            .order_by(ProjectTask.milestone)
        )
    )


# ---------------------------------------------------------------------------
# 阶段验收（设计 §2.3 任务实现通过 / §6.5 判定由确定性程序完成）
# ---------------------------------------------------------------------------

EVALUATION_RUBRIC_VERSION = "task-scoped-v2"


class TaskNotFoundError(PlanError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task not found: {task_id}", status=404)


def get_task(db: Session, project_id, task_id: str) -> ProjectTask:
    task = db.scalar(
        select(ProjectTask).where(
            ProjectTask.project_id == project_id, ProjectTask.task_id == task_id
        )
    )
    if task is None:
        raise TaskNotFoundError(task_id)
    return task


def evaluate_task(
    db: Session,
    project_id,
    task_id: str,
    suite: "dict",
) -> tuple[ProjectTask, bool, list[str], list[str]]:
    """任务级确定性验收（P4.1：绑定 test_files，防伪守卫，practice 信任级）。

    rubric v2：仅统计任务绑定的测试文件结果；至少 1 个绑定测试文件、
    0 失败、0 文件级错误、总用例数 ≥1 → done。判定是程序而非 AI。

    防伪守卫（任务约束 3）：客户端自报结果标记为 practice（非正式验收）；
    无绑定测试/空结果/零断言不判通过。返回 (任务, 是否通过, 依赖缺失, 告警)。
    """
    task = get_task(db, project_id, task_id)
    warnings: list[str] = []

    # 依赖闸门
    blocked: list[str] = []
    by_id = {t.task_id: t for t in list_tasks(db, project_id)}
    for dependency in task.depends_on or []:
        dep_task = by_id.get(dependency)
        if dep_task is None or dep_task.status != "done":
            blocked.append(dependency)
    if blocked:
        raise PlanError(f"前置任务尚未完成：{', '.join(sorted(blocked))}", status=422)

    # 守卫 1：任务必须绑定测试文件
    bound_tests = list(task.test_files or [])
    if not bound_tests:
        warnings.append("任务未绑定测试文件——无法可信评估")
        task.status = "needs-fix"
        db.commit()
        db.refresh(task)
        return task, False, blocked, warnings

    # 守卫 2：客户端只上报了绑定测试的结果（不能拿全项目套件充当）
    reported_files = suite.get("files", [])
    reported_paths = {f.get("path") for f in reported_files if isinstance(f, dict)}
    scoped_files = [f for f in reported_files if isinstance(f, dict) and f.get("path") in bound_tests]
    out_of_scope = [p for p in reported_paths if p not in bound_tests]
    if out_of_scope:
        warnings.append(f"忽略非本任务测试文件：{out_of_scope}")

    # 守卫 3：零用例/零断言不判通过
    total_cases = sum(int(f.get("totalCases", 0)) for f in scoped_files)
    if not scoped_files or total_cases == 0:
        warnings.append("没有执行的测试用例——练习结果不可为通过（防伪）")
        task.status = "needs-fix"
        db.commit()
        db.refresh(task)
        return task, False, blocked, warnings

    # 判定（只看 scoped_files）
    total_failed = sum(int(f.get("failed", 0)) for f in scoped_files)
    error_files = sum(1 for f in scoped_files if f.get("status") == "error")
    passed = total_failed == 0 and error_files == 0

    task.status = "done" if passed else "needs-fix"
    db.commit()
    db.refresh(task)
    return task, passed, blocked, warnings


def get_current_plan(db: Session, project_id) -> LearningPlan | None:
    return db.scalar(
        select(LearningPlan)
        .where(LearningPlan.project_id == project_id)
        .order_by(LearningPlan.plan_version.desc())
        .limit(1)
    )


def _topological_tasks(tasks: list[ProjectTask]) -> list[ProjectTask]:
    """任务按依赖拓扑排序（稳定：同级按 milestone）。"""
    by_id = {t.task_id: t for t in tasks}
    visited: dict[str, int] = {}
    ordered: list[ProjectTask] = []

    def visit(task: ProjectTask) -> None:
        mark = visited.get(task.task_id, 0)
        if mark == 1:
            raise PlanError(f"任务依赖存在环：{task.task_id}", status=422)
        if mark == 2:
            return
        visited[task.task_id] = 1
        for dep in task.depends_on or []:
            if dep not in by_id:
                raise PlanError(f"任务 {task.task_id} 依赖不存在的任务：{dep}", status=422)
            visit(by_id[dep])
        visited[task.task_id] = 2
        ordered.append(task)

    for task in sorted(tasks, key=lambda t: t.milestone):
        visit(task)
    return ordered


def _concept_closure(db: Session, concept_ids: list[str]) -> dict[str, list[str]]:
    """返回 conceptId → 其先修闭包（含自身）；按图深度排序（浅在前）。"""
    concepts = {c.id: c for c in db.scalars(select(KnowledgeConcept))}

    def closure(concept_id: str, seen: set[str]) -> list[str]:
        if concept_id in seen:
            return []
        seen.add(concept_id)
        concept = concepts.get(concept_id)
        if concept is None:
            raise PlanError(f"任务引用了知识库中不存在的概念：{concept_id}", status=422)
        result = [concept_id]
        for prerequisite in concept.prerequisites:
            result.extend(closure(prerequisite, seen))
        return result

    out: dict[str, list[str]] = {}
    for concept_id in concept_ids:
        chain = closure(concept_id, set())
        # 去重并按"先修在前"排序：依赖少的在前
        unique = list(dict.fromkeys(chain))
        unique.sort(key=lambda cid: len(concepts[cid].prerequisites))
        out[concept_id] = unique
    return out


def _is_mastered(mastery: LearnerMastery | None, concept_id: str) -> tuple[bool, str]:
    """返回 (是否已掌握, 原因)。估计是推断：证据不足一律视为未掌握。"""
    if mastery is None:
        return False, "未诊断"
    understanding = (mastery.dimensions or {}).get("understanding")
    if understanding is None:
        return False, "尚无理解维证据"
    if understanding["confidence"] <= MASTERY_CONFIDENCE_THRESHOLD:
        return False, f"证据不足（{understanding['evidenceCount']} 条）"
    if understanding["estimate"] < MASTERY_ESTIMATE_THRESHOLD:
        return False, f"估计偏低（{understanding['estimate']}）"
    return True, (
        f"已掌握（估计 {understanding['estimate']}，{understanding['evidenceCount']} 条证据）"
    )


def generate_plan(db: Session, project_id: str, bump: bool = False) -> LearningPlan:
    """生成学习路线；bump=False 时仅当无历史版本才生成。"""
    try:
        project = get_project(db, project_id)
    except ProjectNotFoundError as exc:
        raise PlanError("project not found", status=404) from exc

    if not bump:
        current = get_current_plan(db, project.id)
        if current is not None:
            return current

    seed_project_tasks(db, project.id)
    tasks = _topological_tasks(list_tasks(db, project.id))

    mastery_map = {
        m.concept_id: m
        for m in db.scalars(
            select(LearnerMastery).where(LearnerMastery.owner_id == "dev-user")
        )
    }

    activities: list[dict] = []
    skipped: list[dict] = []
    planned_concepts: set[str] = set()

    for task in tasks:
        # 任务实践活动（始终保留：掌握知识不等于完成项目交付物）
        activities.append(
            {
                "type": "practice-task",
                "order": 0,
                "taskId": task.task_id,
                "title": task.title,
                "reason": f"里程碑 M{task.milestone} 交付：{task.deliverable}",
            }
        )
        # 任务直接知识要求（不展开闭包进活动标题，闭包作为学习活动单独排）
        required = task.required_concepts or []
        # P7.3：课程候选概念（图谱外）安全降级——跳过闭包计算，不崩溃
        existing_ids = set(db.scalars(select(KnowledgeConcept.id)))
        required = [c for c in required if c in existing_ids]
        closure = _concept_closure(db, required)
        chain_concepts: list[str] = []
        for concept_id in required:
            chain_concepts.extend(closure[concept_id])
        # 依赖浅的先学；去重
        depth = {c.id: len(c.prerequisites) for c in db.scalars(select(KnowledgeConcept))}
        unique_chain = sorted(dict.fromkeys(chain_concepts), key=lambda cid: (depth.get(cid, 0), cid))

        for concept_id in unique_chain:
            if concept_id in planned_concepts:
                continue
            planned_concepts.add(concept_id)
            mastered, reason = _is_mastered(mastery_map.get(concept_id), concept_id)
            if mastered:
                skipped.append({"conceptId": concept_id, "reason": reason})
            else:
                direct = concept_id in required
                activities.append(
                    {
                        "type": "learn-concept",
                        "order": 0,
                        "conceptId": concept_id,
                        "taskId": task.task_id,
                        "reason": ("任务直接要求，" if direct else "先修补课，") + reason,
                    }
                )

    # 活动排序：任务拓扑序内，先学概念再做任务；概念去重（首个需要它的任务处排入）
    learn = [a for a in activities if a["type"] == "learn-concept"]
    practice = [a for a in activities if a["type"] == "practice-task"]
    final: list[dict] = []
    emitted: set[str] = set()
    for task in tasks:
        for activity in learn:
            if activity["taskId"] == task.task_id and activity["conceptId"] not in emitted:
                emitted.add(activity["conceptId"])
                final.append(activity)
        final.append(next(a for a in practice if a["taskId"] == task.task_id))
    for index, activity in enumerate(final, start=1):
        activity["order"] = index

    evidence_count = db.scalar(select(func.count()).select_from(LearningEvidence)) or 0
    reason = (
        f"基于学习证据生成（累计 {evidence_count} 条；"
        f"掌握阈值 {MASTERY_ESTIMATE_THRESHOLD} / 置信阈值 {MASTERY_CONFIDENCE_THRESHOLD}）"
    )

    previous = get_current_plan(db, project.id)
    version = (previous.plan_version + 1) if previous else 1
    plan = LearningPlan(
        project_id=project.id,
        plan_version=version,
        activities=final,
        skipped=skipped,
        reason=reason,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan
