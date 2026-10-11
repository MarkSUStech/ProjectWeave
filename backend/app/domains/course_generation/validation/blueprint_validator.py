"""Blueprint Validator（P7.1，D42）：确定性结构/依赖/证据/概念校验。

LLM 只产建议；合法性由本模块的普通 Python 判定。校验项：
1 taskId/milestoneId 唯一；2 依赖指向存在任务（DAG 无环）；3 每任务有交付；
4 核心里程碑有验收条件；5 里程碑依赖存在且无环；6 任务归属存在的里程碑；
7 知识引用 = 现有图谱 ∪ 蓝图候选概念；8 证据路径存在于仓库快照；
9 testStrategy 不得声称"已通过/已验证"；10 里程碑 ≥4、任务 ≥8、
存在可独立开始的任务与最终交付任务；11 license needs_review → warning。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domains.course_generation.schemas import (
    CourseBlueprint,
    ValidationIssue,
    ValidationResult,
)

FORBIDDEN_TEST_CLAIMS = ("已通过", "已验证", "已经通过", "已全部通过", "tests pass", "已测试通过")


def validate_blueprint(
    blueprint: CourseBlueprint, snapshot_files: list[str],
    existing_concepts: set[str], license_needs_review: bool,
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    def err(code: str, message: str, path: str = ""):
        issues.append(ValidationIssue(code=code, message=message, severity="error", path=path))

    def warn(code: str, message: str, path: str = ""):
        issues.append(ValidationIssue(code=code, message=message, severity="warning", path=path))

    # 1 ID 唯一性
    task_ids = [t.task_id for t in blueprint.tasks]
    if len(task_ids) != len(set(task_ids)):
        err("duplicate-task-id", "任务 taskId 重复")
    ms_ids = [m.milestone_id for m in blueprint.milestones]
    if len(ms_ids) != len(set(ms_ids)):
        err("duplicate-milestone-id", "里程碑 milestoneId 重复")

    id_set = set(task_ids)
    ms_set = set(ms_ids)

    # 2 任务依赖存在 + 3 无环
    graph: dict[str, list[str]] = {tid: [] for tid in task_ids}
    for task in blueprint.tasks:
        for dep in task.depends_on:
            if dep not in id_set:
                err("unknown-task-dep", f"任务 {task.task_id} 依赖不存在的任务 {dep}")
            else:
                graph[task.task_id].append(dep)
    if _has_cycle(graph):
        err("task-cycle", "任务依赖存在环")

    # 3 每任务交付
    for task in blueprint.tasks:
        if not task.deliverables:
            err("empty-deliverable", f"任务 {task.task_id} 缺少交付物", task.task_id)
        if not task.description.strip():
            warn("empty-description", f"任务 {task.task_id} 描述为空", task.task_id)

    # 4 里程碑验收 + 5 里程碑依赖
    for ms in blueprint.milestones:
        if not ms.acceptance_criteria:
            err("milestone-no-acceptance", f"里程碑 {ms.milestone_id} 缺少验收条件")
        if not ms.deliverables:
            err("milestone-no-deliverable", f"里程碑 {ms.milestone_id} 缺少交付物")
        for dep in ms.depends_on:
            if dep not in ms_set:
                err("unknown-ms-dep", f"里程碑 {ms.milestone_id} 依赖不存在的里程碑 {dep}")
    ms_graph = {m.milestone_id: [d for d in m.depends_on if d in ms_set] for m in blueprint.milestones}
    if _has_cycle(ms_graph):
        err("milestone-cycle", "里程碑依赖存在环")

    # 6 任务归属
    for task in blueprint.tasks:
        if task.milestone_id not in ms_set:
            err("orphan-task", f"任务 {task.task_id} 归属不存在的里程碑 {task.milestone_id}")

    # 7 知识引用
    candidate_concepts = {k.concept_id for k in blueprint.knowledge_requirements}
    for task in blueprint.tasks:
        for concept in task.required_concepts:
            if concept not in existing_concepts and concept not in candidate_concepts:
                err("unknown-concept", f"任务 {task.task_id} 引用未知概念 {concept}")
    for knowledge in blueprint.knowledge_requirements:
        if knowledge.is_existing and knowledge.concept_id not in existing_concepts:
            err("false-existing-concept", f"概念 {knowledge.concept_id} 声称已有但不在知识图谱")
        for prereq in knowledge.prerequisites:
            if prereq not in existing_concepts and prereq not in candidate_concepts:
                warn("unknown-concept-prereq", f"候选概念 {knowledge.concept_id} 的先修 {prereq} 未定义")

    # 8 证据路径回溯
    file_set = set(snapshot_files)

    def check_evidence(evidences, owner: str):
        for evidence in evidences:
            if evidence.path not in file_set:
                err("evidence-not-in-snapshot", f"{owner} 的证据路径不在仓库快照中：{evidence.path}")

    check_evidence(blueprint.project.evidence, "project")
    for task in blueprint.tasks:
        check_evidence(task.source_evidence, task.task_id)
        if not task.source_evidence:
            warn("task-no-evidence", f"任务 {task.task_id} 无来源证据")
    no_evidence = [t.task_id for t in blueprint.tasks if not t.source_evidence]
    if len(no_evidence) > len(blueprint.tasks) // 2:
        warn("majority-tasks-no-evidence", f"超过一半任务缺少来源证据：{no_evidence[:5]}")

    # 9 测试声明
    for task in blueprint.tasks:
        for claim in FORBIDDEN_TEST_CLAIMS:
            if claim in task.test_strategy:
                err("test-claim-unverified", f"任务 {task.task_id} 的 testStrategy 含未验证断言：{claim}")

    # 10 结构底线
    if len(blueprint.milestones) < 4:
        err("too-few-milestones", f"里程碑数量不足（{len(blueprint.milestones)} < 4）")
    if len(blueprint.tasks) < 8:
        err("too-few-tasks", f"任务数量不足（{len(blueprint.tasks)} < 8）")
    startable = [t.task_id for t in blueprint.tasks if not t.depends_on]
    if not startable:
        err("no-startable-task", "没有可独立开始的任务（全部任务有依赖）")
    final_ms = [m for m in blueprint.milestones if not any(m.milestone_id in other.depends_on for other in blueprint.milestones)]
    if final_ms and not final_ms[0].deliverables:
        err("final-ms-no-deliverable", "最终里程碑缺少交付物")

    # 11 许可证需审查
    if license_needs_review:
        warn("license-needs-review", "仓库许可证未明确识别——发布/复制源码前需人工审查")

    return ValidationResult(
        passed=not any(i.severity == "error" for i in issues),
        issues=issues,
        checked_at=datetime.now(timezone.utc),
    )


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    color: dict[str, int] = {node: 0 for node in graph}

    def dfs(node: str) -> bool:
        color[node] = 1
        for dep in graph.get(node, []):
            if color.get(dep) == 1:
                return True
            if color.get(dep) == 0 and dfs(dep):
                return True
        color[node] = 2
        return False

    return any(color[n] == 0 and dfs(n) for n in graph)
