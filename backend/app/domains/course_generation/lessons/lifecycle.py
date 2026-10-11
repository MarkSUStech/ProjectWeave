"""学生课程进度：任务生命周期、激活、安全合并与最终验收（P7.3，D43）。

状态机（服务端权威）：locked → available → active → needs-fix → completed
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.course_generation.lessons.lesson_publisher import ReleaseError
from app.domains.course_generation.models import CourseRelease
from app.domains.curriculum.models import ProjectTask
from app.domains.projects.models import Project, ProjectFile
from app.domains.projects.service import get_project

TASK_LIFECYCLE = ("locked", "available", "active", "needs-fix", "completed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# ---------------------------------------------------------------- 三方合并


@dataclass
class MergeResult:
    ok: bool
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)


def three_way_merge(
    base_files: dict[str, str],      # 上一阶段基线（前置任务 starter+tests）
    target_files: dict[str, str],    # 本任务 starter + tests
    student_files: dict[str, str],   # 学生当前文件
) -> MergeResult:
    """安全合并：学生代码只要与基线不同就保留（除非与课程变更冲突）。"""
    result = MergeResult(ok=True)
    all_paths = set(target_files) | set(student_files) | set(base_files)

    for path in sorted(all_paths):
        base = base_files.get(path)
        target = target_files.get(path)
        student = student_files.get(path)

        if target is None and student is None:
            continue

        if student is None:
            if target is not None:
                result.files[path] = target
                result.created.append(path)
            continue

        if target is None:
            result.files[path] = student
            result.preserved.append(path)
            continue

        if base is None:
            if student.strip() == target.strip():
                result.files[path] = student
            elif "TODO" in student:
                result.files[path] = target
                result.updated.append(path)
            else:
                result.conflicts.append({
                    "path": path, "reason": "新文件内容不一致",
                    "suggestion": "保留学生版本或用课程 starter 覆盖",
                })
                result.files[path] = student
            continue

        student_changed = base.strip() != student.strip()
        course_changed = base.strip() != target.strip()

        if not student_changed:
            result.files[path] = target
            if course_changed:
                result.updated.append(path)
            continue

        if student.strip() == target.strip():
            result.files[path] = student
        elif not course_changed:
            result.files[path] = student
            result.preserved.append(path)
        else:
            result.conflicts.append({
                "path": path, "reason": "学生修改与课程变更冲突",
                "suggestion": "请手动合并",
            })
            result.files[path] = student

    result.ok = not result.conflicts
    return result


# ---------------------------------------------------------------- 进度查询


def _release_for_project(db: Session, project: Project) -> CourseRelease | None:
    if not project.template_id or not project.template_id.startswith("course-release:"):
        return None
    release_id = project.template_id.split(":", 1)[1]
    return db.get(CourseRelease, _uuid(release_id))


def compute_lifecycle_status(db: Session, project_id) -> dict:
    """计算所有任务的生命周期状态（服务端权威）。"""
    project = db.get(Project, _uuid(project_id))
    if project is None:
        raise ReleaseError("项目不存在", 404)
    release = _release_for_project(db, project)
    if release is None:
        return {"courseMode": False, "tasks": []}

    tasks = list(db.scalars(
        select(ProjectTask).where(ProjectTask.project_id == project.id)
        .order_by(ProjectTask.milestone)
    ))
    by_id = {t.task_id: t for t in tasks}
    statuses: dict[str, str] = {}
    deps = {t.task_id: list(t.depends_on or []) for t in tasks}

    def status_of(tid: str, visiting: set) -> str:
        if tid in statuses:
            return statuses[tid]
        if tid in visiting:
            return "locked"
        visiting.add(tid)
        task = by_id.get(tid)
        if task is None:
            return "locked"
        if task.status == "done":
            statuses[tid] = "completed"
        elif task.status == "needs-fix":
            statuses[tid] = "needs-fix"
        elif task.status == "in-progress":
            statuses[tid] = "active"
        else:
            all_done = all(
                status_of(dep, visiting) == "completed"
                for dep in deps.get(tid, [])
            )
            statuses[tid] = "available" if all_done else "locked"
        return statuses[tid]

    for t in tasks:
        status_of(t.task_id, set())

    completed = sum(1 for s in statuses.values() if s == "completed")
    return {
        "courseMode": True,
        "releaseId": str(release.id),
        "releaseVersion": release.release_version,
        "currentTask": next((tid for tid, s in statuses.items() if s == "active"), None),
        "completedCount": completed,
        "totalCount": len(tasks),
        "allCompleted": completed == len(tasks) and len(tasks) > 0,
        "tasks": [
            {
                "taskId": tid,
                "status": statuses[tid],
                "dependsOn": deps.get(tid, []),
                "milestone": by_id[tid].milestone,
                "title": by_id[tid].title,
            }
            for tid in sorted(statuses, key=lambda x: by_id[x].milestone)
        ],
    }


# ---------------------------------------------------------------- 任务激活


def activate_task(db: Session, project_id, task_id: str) -> dict:
    """激活任务：依赖闸门 → 三方安全合并 → 注入文件 → 更新状态（幂等）。"""
    project = get_project(db, str(project_id))
    release = _release_for_project(db, project)
    if release is None:
        raise ReleaseError("项目不是课程项目", 422)

    task = db.scalar(
        select(ProjectTask).where(
            ProjectTask.project_id == project.id, ProjectTask.task_id == task_id
        )
    )
    if task is None:
        raise ReleaseError("任务不存在", 404)

    if task.status in ("in-progress", "needs-fix"):
        return {"activated": True, "alreadyActive": True,
                "filesCreated": [], "conflicts": []}
    if task.status == "done":
        raise ReleaseError("任务已完成，无需激活", 422)

    progress = compute_lifecycle_status(db, project.id)
    status_map = {t["taskId"]: t["status"] for t in progress["tasks"]}
    if status_map.get(task_id) == "locked":
        blocking = [d for d in (task.depends_on or []) if status_map.get(d) != "completed"]
        raise ReleaseError(f"前置任务未完成：{', '.join(blocking)}", 422)

    artifacts = {a.get("taskId"): a for a in (release.artifacts or [])}
    artifact = artifacts.get(task_id)
    if artifact is None:
        raise ReleaseError("课程材料中无此任务", 404)

    current_files = {
        f.path: f.content for f in db.scalars(
            select(ProjectFile).where(ProjectFile.project_id == project.id)
        )
    }

    prev_dep = (task.depends_on or [None])[0]
    base_files = {}
    if prev_dep and prev_dep in artifacts:
        prev_art = artifacts[prev_dep]
        base_files = {f["path"]: f["content"] for f in prev_art.get("starterFiles") or []}
        for f in prev_art.get("testFiles") or []:
            base_files.setdefault(f["path"], f["content"])

    target_files = {f["path"]: f["content"] for f in artifact.get("starterFiles") or []}
    for f in artifact.get("testFiles") or []:
        target_files[f["path"]] = f["content"]

    merged = three_way_merge(base_files, target_files, current_files)

    if not merged.ok:
        return {
            "activated": False, "conflicts": merged.conflicts,
            "filesCreated": [], "message": "文件冲突需要确认后才能激活",
        }

    try:
        existing = {f.path: f for f in db.scalars(
            select(ProjectFile).where(ProjectFile.project_id == project.id)
        )}
        for path in merged.created:
            if path not in existing:
                db.add(ProjectFile(
                    project_id=project.id, path=path, content=merged.files[path]
                ))
        for path in merged.updated:
            if path in existing:
                existing[path].content = merged.files[path]
        task.status = "in-progress"
        db.commit()
    except Exception:
        db.rollback()
        raise ReleaseError("激活失败（已回滚，未修改任何文件）", 500)

    return {
        "activated": True, "alreadyActive": False,
        "filesCreated": merged.created, "filesUpdated": merged.updated,
        "conflicts": [],
        "starterPaths": [f["path"] for f in artifact.get("starterFiles") or []],
        "testPaths": [f["path"] for f in artifact.get("testFiles") or []],
    }


# ---------------------------------------------------------------- 完成后解锁


def on_task_completed(db: Session, project_id, task_id: str) -> list[str]:
    """任务完成后返回刚解锁的任务 ID 列表（供前端提示）。"""
    progress = compute_lifecycle_status(db, project_id)
    return [
        t["taskId"] for t in progress["tasks"]
        if t["status"] == "available" and task_id in t["dependsOn"]
    ]


# ---------------------------------------------------------------- 最终验收


def final_verification_report(db: Session, project_id) -> dict:
    """最终项目验收报告（全部任务完成时）。"""
    project = get_project(db, str(project_id))
    release = _release_for_project(db, project)
    if release is None:
        raise ReleaseError("项目不是课程项目", 422)

    progress = compute_lifecycle_status(db, project.id)
    if not progress["allCompleted"]:
        raise ReleaseError(
            f"课程尚未全部完成（{progress['completedCount']}/{progress['totalCount']}）", 422
        )

    report_row = release.verification_report or {}
    final = report_row.get("finalIntegration") or {}
    artifacts = {a.get("taskId"): a for a in (release.artifacts or [])}

    tasks_with_pass = []
    for t in progress["tasks"]:
        art = artifacts.get(t["taskId"])
        has_pass = any(
            v.get("status") == "passed" for v in (art or {}).get("verifications", [])
        )
        tasks_with_pass.append({"taskId": t["taskId"], "referenceVerified": has_pass})

    files = {f.path: len(f.content or "") for f in db.scalars(
        select(ProjectFile).where(ProjectFile.project_id == project.id)
    )}

    return {
        "projectTitle": project.title,
        "sourceUrl": release.blueprint_snapshot.get("project", {}).get("sourceUrl", ""),
        "releaseVersion": release.release_version,
        "completedTasks": progress["completedCount"],
        "totalTasks": progress["totalCount"],
        "referenceIntegrationVerified": final.get("status") == "passed",
        "referenceTestCounts": {
            "total": final.get("total", 0), "passed": final.get("passed", 0),
            "failed": final.get("failed", 0),
        },
        "studentFiles": len(files),
        "nonGoals": release.blueprint_snapshot.get("project", {}).get("nonGoals", []),
        "finalArtifact": release.blueprint_snapshot.get("project", {}).get("finalArtifact", ""),
        "completedAt": utcnow().isoformat(),
        "note": "报告基于课程验证与学生学习记录；AI 参考实现的验证不视为学生独立完成的证据。",
    }
