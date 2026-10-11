"""第一批只读教学工具（P6，白名单注册）。

全部调用已有业务模型/服务（不重新实现文件系统、调试器或运行器）；
全部以 ctx.project_id 做行级过滤——LLM 无法指定项目，路径穿越与
跨项目访问在 DB 查询层即被拒绝。
"""

from __future__ import annotations

from sqlalchemy import select

from app.agents.registry import tutor_registry
from app.agents.schemas import ToolContext, ToolSpec


def _project_files(ctx: ToolContext):
    from app.domains.projects.models import ProjectFile

    return list(ctx.db.scalars(
        select(ProjectFile)
        .where(ProjectFile.project_id == ctx.project_id)
        .order_by(ProjectFile.path)
    ))


def _list_project_files(ctx: ToolContext) -> dict:
    files = _project_files(ctx)
    return {
        "files": [{"path": f.path, "chars": len(f.content or "")} for f in files],
        "total": len(files),
    }


def _read_project_file(ctx: ToolContext, path: str, max_chars: int = 4000) -> dict:
    from app.domains.executions.service import validate_file_path

    err = validate_file_path(path)
    if err:
        raise ValueError(err)
    # 行级过滤：只可能命中当前项目的文件（路径穿越在 validate + 查询双重拒绝）
    from app.domains.projects.models import ProjectFile

    row = ctx.db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == ctx.project_id, ProjectFile.path == path
        )
    )
    if row is None:
        raise FileNotFoundError(f"文件不存在：{path}")
    limit = max(200, min(int(max_chars), 8000))
    content = row.content or ""
    return {
        "path": path,
        "content": content[:limit] + ("…（截断）" if len(content) > limit else ""),
        "totalChars": len(content),
        "truncated": len(content) > limit,
    }


def _get_current_task(ctx: ToolContext, task_id: str | None = None) -> dict:
    from app.domains.curriculum.models import ProjectTask

    wanted = task_id or ctx.current_task_id
    tasks = list(ctx.db.scalars(
        select(ProjectTask)
        .where(ProjectTask.project_id == ctx.project_id)
        .order_by(ProjectTask.milestone)
    ))
    task = next((t for t in tasks if t.task_id == wanted), None)
    if task is None and not wanted:
        task = next((t for t in tasks if t.status != "done"), tasks[0] if tasks else None)
    if task is None:
        raise FileNotFoundError("项目中没有任务（当前项目可能无课程）")
    return {
        "taskId": task.task_id,
        "title": task.title,
        "description": task.description,
        "goal": task.deliverable,
        "status": task.status,
        "requiredConcepts": task.required_concepts,
        "testFiles": task.test_files,
        "acceptanceCriteria": task.acceptance_criteria,
        "dependsOn": task.depends_on,
        "hints": task.hints,
        "vizSuggestion": task.viz_suggestion,
    }


def _get_recent_diagnostics(ctx: ToolContext) -> dict:
    """最近执行/调试的真实错误（编译/运行/测试/超时），带文件行号。"""
    from app.domains.executions.models import ExecutionSession

    rows = list(ctx.db.scalars(
        select(ExecutionSession)
        .where(ExecutionSession.project_id == ctx.project_id)
        .order_by(ExecutionSession.created_at.desc())
        .limit(5)
    ))
    diagnostics = []
    for row in rows:
        if row.status in ("completed",) and not (row.diagnostics or []):
            continue
        entry = {
            "executionId": str(row.id),
            "language": row.language,
            "mode": row.mode,
            "status": row.status,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        if row.diagnostics:
            entry["buildDiagnostics"] = row.diagnostics[:5]
        if row.error:
            entry["error"] = row.error[:300]
        if row.stderr_text:
            entry["stderrTail"] = row.stderr_text[-400:]
        if row.test_results:
            failed = [t for t in row.test_results if t.get("status") != "passed"]
            if failed:
                entry["failedTests"] = [
                    {"path": t.get("path"), "error": (t.get("error") or "")[:200]}
                    for t in failed[:5]
                ]
        if row.timed_out:
            entry["timedOut"] = True
        diagnostics.append(entry)
    return {"recentDiagnostics": diagnostics[:5]}


def _get_learner_mastery(ctx: ToolContext, concept_ids: list[str] | None = None) -> dict:
    from app.domains.learner.models import LearnerMastery

    rows = list(ctx.db.scalars(
        select(LearnerMastery).where(LearnerMastery.owner_id == ctx.owner_id)
    ))
    if concept_ids:
        wanted = set(concept_ids)
        rows = [r for r in rows if r.concept_id in wanted]
    return {
        "mastery": [
            {"conceptId": r.concept_id, "dimensions": r.dimensions, "modelVersion": r.model_version}
            for r in rows[:20]
        ]
    }


def _get_debug_snapshot(ctx: ToolContext) -> dict:
    from app.domains.debugging.models import DebugSession

    row = ctx.db.scalar(
        select(DebugSession)
        .where(DebugSession.project_id == ctx.project_id)
        .order_by(DebugSession.created_at.desc())
        .limit(1)
    )
    if row is None:
        return {"debugSession": None, "note": "本项目还没有调试会话"}
    result: dict = {
        "debugSession": {
            "id": str(row.id),
            "status": row.status,
            "endReason": row.end_reason,
            "entryPoint": row.entry_point,
            "pauseSeq": row.pause_seq,
        }
    }
    if row.current_location:
        result["location"] = row.current_location
    if row.stop_reason:
        result["stopReason"] = row.stop_reason
    if row.stack_frames:
        result["stackFrames"] = row.stack_frames[:8]
    if row.scopes:
        locals_scope = next((s for s in row.scopes if s.get("name") == "Locals"), None)
        if locals_scope:
            result["localVariables"] = [
                {"name": v.get("name"), "value": v.get("value"), "type": v.get("type")}
                for v in (locals_scope.get("variables") or [])[:15]
            ]
    if row.pointer_graph:
        result["verifiedPointerEdges"] = row.pointer_graph.get("verifiedEdges", [])
        result["nullPointers"] = [n.get("name") for n in row.pointer_graph.get("nullPointers", [])]
    if row.build_diagnostics:
        result["buildDiagnostics"] = row.build_diagnostics[:5]
    return result


def register_builtin_tools() -> None:
    """幂等注册第一批只读工具（Tutor Agent 使用）。"""
    if tutor_registry.names():
        return
    tutor_registry.register(ToolSpec(
        name="list_project_files",
        description="列出当前项目的全部文件（路径与大小）。用于了解项目结构。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_list_project_files,
        max_result_chars=3000,
    ))
    tutor_registry.register(ToolSpec(
        name="read_project_file",
        description="读取当前项目的一个源码文件（相对路径）。可限制返回字符数。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目内相对路径，如 src/main.cpp"},
                "max_chars": {"type": "integer", "description": "返回内容上限（200-8000，默认 4000）"},
            },
            "required": ["path"],
        },
        handler=_read_project_file,
        max_result_chars=9000,
    ))
    tutor_registry.register(ToolSpec(
        name="get_current_task",
        description="获取当前学习任务（或指定任务）的描述、目标、知识要求、测试与验收条件、渐进提示。",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "任务 ID（省略=当前任务）"}},
            "required": [],
        },
        handler=_get_current_task,
        max_result_chars=5000,
    ))
    tutor_registry.register(ToolSpec(
        name="get_recent_diagnostics",
        description="获取最近几次真实执行/测试的错误：编译诊断（文件:行:列）、运行 stderr、失败测试、超时。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_recent_diagnostics,
        max_result_chars=6000,
    ))
    tutor_registry.register(ToolSpec(
        name="get_learner_mastery",
        description="查询学习者对各知识概念的掌握估计（各维度证据与置信度）。可按概念 id 过滤。",
        parameters={
            "type": "object",
            "properties": {
                "concept_ids": {"type": "array", "items": {"type": "string"}, "description": "概念 id 列表（省略=全部）"},
            },
            "required": [],
        },
        handler=_get_learner_mastery,
        max_result_chars=5000,
    ))
    tutor_registry.register(ToolSpec(
        name="get_debug_snapshot",
        description="获取本项目最近一次调试会话的真实快照：暂停位置、调用栈、局部变量、已验证指针关系。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_debug_snapshot,
        max_result_chars=6000,
    ))
