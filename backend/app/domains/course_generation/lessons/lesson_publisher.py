"""课程内容生产/发布/实例化服务（P7.2，D42）。

流水线（后台线程，release 行持久化进度）：
按任务 DAG 顺序逐任务：LLM 生成材料 → 防伪守卫 → 真实沙箱验证参考实现
（本任务测试 + 回归测试）→ 失败进入 ≤2 修复轮 → 通过则参考快照累积传递
给下一任务 → 全部通过后跑最终集成验证 → ready。
instantiate：从 ready release 创建学生项目（种子首任务 starter + 全部任务）。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.schemas import extract_json_object  # noqa: F401
from app.domains.course_generation.lessons import lesson_builder
from app.domains.course_generation.lessons.schemas import LessonArtifact
from app.domains.course_generation.models import CourseGeneration, CourseRelease
from app.domains.course_generation.execution_profile import (
    derive_execution_profile,
    unsupported_profile_message,
)
from app.domains.course_generation.validation.blueprint_validator import _has_cycle
from app.domains.course_generation.verification.course_verifier import (
    guard_starter,
    merge_files,
    run_in_sandbox,
    verify_cpp_cmake_task,
)

MAX_REPAIR_PER_TASK = 3


def unsupported_language_message(language: str) -> str:
    """无真实沙箱验证器的语言：如实拒绝（不烧 LLM、不伪装成功）。"""
    return (f"暂不支持 {language} 课程的沙箱验证（当前支持 Python/pytest 与 C++/CMake 真实全链验证）。"
            "为不伪造成功，已拒绝生成课程内容；蓝图已保留，待该语言验证器上线后可重试。")


class ReleaseError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 注入点（测试）
_session_factory = None
_provider_factory = None


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def set_provider_factory(factory) -> None:
    global _provider_factory
    _provider_factory = factory


def _session():
    if _session_factory is not None:
        return _session_factory()
    from app.core.db import SessionLocal

    return SessionLocal()


def _provider():
    if _provider_factory is not None:
        return _provider_factory()
    from app.ai.provider import get_provider

    return get_provider()


# ---------------------------------------------------------------- 创建/查询


def build_lessons(db: Session, generation_id) -> CourseRelease:
    gen = db.get(CourseGeneration, _uuid(generation_id))
    if gen is None:
        raise ReleaseError("生成任务不存在", 404)
    if gen.blueprint is None or gen.status not in ("published", "draft"):
        raise ReleaseError("蓝图未就绪（需先完成蓝图生成与验证）")
    profile = derive_execution_profile(gen.blueprint)
    language = profile["primaryLanguage"]
    if not profile["verified"]:
        # 提前拒绝：不做任何 LLM 生成/修复尝试，不产生注定失败的 release
        raise ReleaseError(unsupported_profile_message(profile), 422)
    version = 1 + len(list(db.scalars(
        select(CourseRelease.id).where(CourseRelease.generation_id == gen.id)
    )))
    release = CourseRelease(
        generation_id=gen.id,
        release_version=version,
        status="generating",
        language=language,
        course_title=(gen.blueprint.get("project") or {}).get("title", ""),
        blueprint_snapshot=gen.blueprint,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    threading.Thread(target=_run_build, args=(release.id,), daemon=True,
                     name=f"pw-lessons-{release.id.hex[:8]}").start()
    return release


def get_release(db: Session, release_id) -> CourseRelease:
    row = db.get(CourseRelease, _uuid(release_id))
    if row is None:
        raise ReleaseError("课程版本不存在", 404)
    return row


def list_releases(db: Session, generation_id) -> list[CourseRelease]:
    return list(db.scalars(
        select(CourseRelease)
        .where(CourseRelease.generation_id == _uuid(generation_id))
        .order_by(CourseRelease.release_version.desc())
    ))


def recover_stale_releases(db: Session) -> int:
    """服务重启恢复：卡在 generating/verifying 的 release 标记失败（可重试）。"""
    stale = list(db.scalars(select(CourseRelease).where(
        CourseRelease.status.in_(("generating", "verifying"))
    )))
    for row in stale:
        row.status = "failed"
        row.error = "服务重启中断（可重新生成课程内容产生新版本）"
    db.commit()
    return len(stale)


def instantiate_project(db: Session, release_id, title: str | None = None) -> dict:
    """从 ready release 创建学生项目：首任务 starter + 全部任务种子。"""
    release = get_release(db, release_id)
    if release.status != "ready":
        raise ReleaseError("课程未就绪（lessons 未全部验证通过）")

    from app.domains.projects.models import Project, ProjectFile
    from app.domains.curriculum.models import ProjectTask

    blueprint = _normalize_blueprint(release.blueprint_snapshot or {})
    course_title = title or release.course_title or "课程项目"
    project = Project(
        owner_id="dev-user",
        title=course_title,
        description=(blueprint.get("project") or {}).get("description", ""),
        mode="rebuild",
        complexity="medium",
        target_features=(blueprint.get("project") or {}).get("goals") or [],
        non_goals=(blueprint.get("project") or {}).get("nonGoals") or [],
        stack=[release.language.capitalize()],
        acceptance_criteria=(blueprint.get("project") or {}).get("evidence") and [] or [],
        # 课程项目绑定确定 release 版本
        template_id=f"course-release:{release.id}",
    )
    db.add(project)
    db.flush()

    artifacts = release.artifacts or []
    by_task = {a.get("taskId") or a.get("task_id"): a for a in artifacts}
    order = _task_order(blueprint)
    first = next((a for a in order if a["taskId"] in by_task), None)

    # 种子文件：README + 首任务 starter + 首任务测试
    files: dict[str, str] = {
        "README.md": (
            f"# {course_title}\n\n"
            f"本项目由 ProjectWeave 课程自动创建（release v{release.release_version}）。\n"
            f"按「任务」面板逐步完成；每个任务有初始代码与可运行测试。\n"
        ),
    }
    if first:
        first_artifact = by_task.get(first["taskId"]) or {}
        for f in first_artifact.get("starterFiles") or first_artifact.get("starter_files") or []:
            files[f["path"]] = f["content"]
        for f in first_artifact.get("testFiles") or first_artifact.get("test_files") or []:
            files.setdefault(f["path"], f["content"])
    for path, content in files.items():
        db.add(ProjectFile(project_id=project.id, path=path, content=content))

    # 种子任务（全部任务入图；测试文件路径绑定 + P8.2 CMake 验收契约）
    ms_order = {m["milestoneId"]: i + 1 for i, m in enumerate(blueprint.get("milestones") or [])}
    first_task_row = None
    for spec in order:
        artifact = by_task.get(spec["taskId"])
        manifest = ((artifact or {}).get("buildManifest")
                    or (artifact or {}).get("build_manifest") or {})
        verification = None
        if manifest.get("testNames") or manifest.get("buildTargets"):
            verification = {
                "buildSystem": "cmake",
                "buildTargets": manifest.get("buildTargets") or [],
                "testNames": manifest.get("testNames") or [],
                "verificationProfile": "ctest",
            }
        task_row = ProjectTask(
            project_id=project.id,
            task_id=spec["taskId"],
            milestone=ms_order.get(spec.get("milestoneId"), 1),
            title=spec.get("title", ""),
            description=_task_description(artifact, spec),
            depends_on=spec.get("dependsOn") or [],
            required_concepts=spec.get("requiredConcepts") or [],
            deliverable="; ".join(spec.get("deliverables") or [])[:400],
            test_files=[f["path"] for f in (artifact or {}).get("testFiles") or (artifact or {}).get("test_files") or []],
            starter_files=[f["path"] for f in (artifact or {}).get("starterFiles") or (artifact or {}).get("starter_files") or []],
            acceptance_criteria=spec.get("acceptanceCriteria") or [],
            hints=(artifact or {}).get("hints") or [],
            viz_suggestion="",
            verification=verification,
        )
        db.add(task_row)
        if first and spec["taskId"] == first["taskId"]:
            first_task_row = task_row
    # P7.3：首任务已注入 starter+tests → 标记 in-progress（已激活态）
    if first_task_row is not None and first_task_row.status in ("pending", None):
        first_task_row.status = "in-progress"
    db.commit()
    db.refresh(project)
    return {"project_id": project.id, "first_task_id": first["taskId"] if first else None}


# ---------------------------------------------------------------- 构建流水线


def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _normalize_blueprint(data: dict) -> dict:
    """蓝图统一为 camelCase dict（快照可能来自 model_dump 蛇形或 LLM 驼峰）。"""
    from app.domains.course_generation.schemas import CourseBlueprint

    return CourseBlueprint.model_validate(data).model_dump(mode="json", by_alias=True)


def _task_order(blueprint: dict) -> list[dict]:
    tasks = blueprint.get("tasks") or []
    graph = {t["taskId"]: list(t.get("dependsOn") or []) for t in tasks}
    if _has_cycle(graph):
        raise ReleaseError("任务依赖有环，无法排序")
    ordered, seen = [], set()

    def visit(tid):
        if tid in seen:
            return
        seen.add(tid)
        for dep in graph.get(tid, []):
            visit(dep)
        ordered.append(tid)

    for t in tasks:
        visit(t["taskId"])
    by_id = {t["taskId"]: t for t in tasks}
    return [by_id[tid] for tid in ordered]


def _update(release_id, **fields) -> None:
    try:
        with _session() as db:
            row = db.get(CourseRelease, release_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        pass


def _run_build(release_id: uuid.UUID) -> None:
    try:
        _run_build_inner(release_id)
    except Exception as exc:
        _update(release_id, status="failed", error=f"课程内容生产内部错误：{exc}")


def _process_cpp_task(
    provider, release_id, task_id: str, spec: dict, order: list, total: int,
    milestone_title: str, cumulative_reference: dict[str, str],
    prior_test_names: list[str], evidence: dict[str, str],
    prior_failures: list[str] | None, is_final: bool,
) -> dict:
    """P8.2：单个 C++/CMake 任务——生成 → 守卫 → 八步真实验证 → 有限修复。

    返回 {passed, error, artifact, cumulative_reference, prior_test_names,
    reference_delta}；artifact 已按公开契约（camelCase）组装。
    """
    repairs: list[dict] = []
    _update(release_id, status="verifying", current_task=task_id)

    material = lesson_builder.build_cpp_cmake_task_lesson(
        provider, spec, milestone_title, cumulative_reference, evidence)
    # 重试上下文注入（上一版 release 的失败原因）
    if prior_failures:
        material = lesson_builder.repair_task_lesson(
            provider, material,
            [{"kind": "prior-failure", "message": p} for p in prior_failures],
            "cpp")

    for attempt in range(MAX_REPAIR_PER_TASK + 1):
        problems = guard_starter(
            material.get("starterFiles") or [],
            material.get("referenceFiles") or [],
            material.get("testFiles") or [],
            "cpp",
            expected_files=(material.get("instructions") or {}).get("expectedFiles"),
        )
        if problems:
            if attempt < MAX_REPAIR_PER_TASK:
                material = lesson_builder.repair_task_lesson(
                    provider, material,
                    [{"kind": "guard", "message": p} for p in problems]
                    + [{"kind": "material-context", "message":
                        "当前生成的文件清单与摘要：\n" + _material_context(material)}],
                    "cpp")
                repairs.append({"round": attempt + 1,
                                "problem": "防伪守卫：" + "; ".join(problems[:3]),
                                "changedFiles": [], "outcome": "still-failing"})
                continue
            return _cpp_task_failed(task_id, spec, material, repairs, [],
                                    "防伪守卫：" + "; ".join(problems[:3]))

        verification = verify_cpp_cmake_task(
            material, cumulative_reference, prior_test_names, is_final=is_final)
        if verification.passed:
            manifest = material.get("buildManifest") or {}
            new_tests = [n for n in manifest.get("testNames") or []
                         if n not in prior_test_names]
            artifact = {
                "taskId": task_id,
                "milestoneId": spec.get("milestoneId", ""),
                "language": "cpp",
                "instructions": material.get("instructions")
                or {"title": spec.get("title", task_id)},
                "starterFiles": material.get("starterFiles") or [],
                "testFiles": material.get("testFiles") or [],
                "buildManifest": manifest,
                "hints": material.get("hints") or [],
                "status": "tests-passed",
                "verifications": verification.verifications,
                "repairs": repairs,
                "error": None,
                "generationModel": getattr(provider, "name", ""),
            }
            return {
                "passed": True, "error": None,
                "artifact": artifact,
                "cumulative_reference": verification.reference_files,
                "prior_test_names": [*prior_test_names, *new_tests],
                "reference_delta": [{"path": f["path"], "content": f["content"]}
                                    for f in material.get("referenceFiles") or []],
            }

        # 修复轮：把八步验证的具体问题（含真实诊断）回灌给生成器
        detail = verification.problems[:4] + [
            f"[{v.get('kind')}] {d.get('message', '')}"
            for v in verification.verifications for d in v.get("diagnostics", [])[:3]
        ][:8]
        error_summary = "; ".join(verification.problems[:3]) or "验证未通过"
        if attempt < MAX_REPAIR_PER_TASK:
            material = lesson_builder.repair_task_lesson(
                provider, material,
                [{"kind": "cmake-verification", "message": p} for p in detail],
                "cpp")
            repairs.append({"round": attempt + 1, "problem": error_summary,
                            "changedFiles": [], "outcome": "still-failing"})
            continue
        return _cpp_task_failed(task_id, spec, material, repairs,
                                verification.verifications, error_summary)

    return _cpp_task_failed(task_id, spec, material, repairs, [], "修复轮耗尽")


def _cpp_task_failed(task_id: str, spec: dict, material: dict,
                     repairs: list[dict], verifications: list[dict],
                     error: str) -> dict:
    return {
        "passed": False, "error": error,
        "artifact": {
            "taskId": task_id,
            "milestoneId": spec.get("milestoneId", ""),
            "language": "cpp",
            "instructions": material.get("instructions")
            or {"title": spec.get("title", task_id)},
            "starterFiles": material.get("starterFiles") or [],
            "testFiles": material.get("testFiles") or [],
            "buildManifest": material.get("buildManifest") or {},
            "hints": material.get("hints") or [],
            "status": "failed",
            "verifications": verifications,
            "repairs": repairs,
            "error": error,
            "generationModel": "",
        },
        "cumulative_reference": {}, "prior_test_names": [], "reference_delta": [],
    }


def _artifact_public(artifact: LessonArtifact) -> dict:
    data = artifact.model_dump(mode="json")
    data.pop("reference_files", None)  # 受保护：剥离
    return data


def _material_context(material: dict, limit: int = 4600) -> str:
    """修复轮上下文：文件路径清单 + 常见修复对象（starter/test）的头部摘要。"""
    def inv(kind: str) -> str:
        return ", ".join(
            f"{f.get('path')}({len((f.get('content') or '').splitlines())}行)"
            for f in material.get(kind) or []) or "（无）"

    parts = [
        f"starterFiles: {inv('starterFiles')}",
        f"testFiles: {inv('testFiles')}",
        f"referenceFiles: {inv('referenceFiles')}",
    ]
    for kind in ("starterFiles", "testFiles"):
        for f in (material.get(kind) or [])[:4]:
            head = "\n".join((f.get("content") or "").splitlines()[:12])
            parts.append(f"--- {f.get('path')} 头12行 ---\n{head}")
        if len("\n".join(parts)) > limit:
            break
    return "\n".join(parts)[:limit]


def _prior_failures(db: Session, generation_id, before_version: int) -> dict[str, list[str]]:
    """收集同一 generation 此前失败 release 的逐任务问题（喂给重试生成的 LLM）。

    artifacts 里通过的条目是 camelCase（model_dump by_alias）、失败条目是
    snake_case（手工构造），两种键都兼容。
    """
    failures: dict[str, list[str]] = {}
    rows = list(db.scalars(select(CourseRelease).where(
        CourseRelease.generation_id == generation_id,
        CourseRelease.release_version < before_version,
        CourseRelease.status == "failed",
    )))
    for row in rows:
        for art in row.artifacts or []:
            if art.get("status") != "failed":
                continue
            task_id = art.get("taskId") or art.get("task_id") or ""
            if not task_id:
                continue
            problems = failures.setdefault(task_id, [])
            if art.get("error"):
                problems.append(str(art["error"])[:300])
            for rep in (art.get("repairs") or [])[-3:]:
                if rep.get("problem"):
                    problems.append(f"修复轮未解决：{str(rep['problem'])[:200]}")
        # release 级错误兜底（artifact 缺失时至少把总错误挂到失败任务上）
        tid = (row.verification_report or {}).get("failed_task")
        if tid and row.error and not failures.get(tid):
            failures[tid] = [str(row.error)[:300]]
    return {tid: probs[:6] for tid, probs in failures.items() if probs}


def _run_build_inner(release_id: uuid.UUID) -> None:
    with _session() as db:
        release = db.get(CourseRelease, release_id)
        if release is None:
            return
        blueprint = _normalize_blueprint(release.blueprint_snapshot or {})
        language = release.language
        if language not in ("python", "cpp"):
            # 防御：历史 release 行/竞态兜底（build_lessons 已提前拒绝新请求）
            _update(release_id, status="failed", progress=100,
                    error=unsupported_language_message(language))
            return
        gen = db.get(CourseGeneration, release.generation_id)
        snapshot_files = (gen.snapshot or {}).get("files", {}) if gen else {}
        # 重试上下文：此前失败 release 的逐任务问题（喂给本轮 LLM 规避）
        prior = _prior_failures(db, release.generation_id, release.release_version)

    provider = _provider()
    order = _task_order(blueprint)
    total = len(order)
    artifacts_public: list[dict] = []
    reference_store: dict[str, list[dict]] = {}
    cumulative_reference: dict[str, str] = {}   # 累积参考快照（连续性核心）
    all_test_files: dict[str, str] = {}         # 累积测试（回归用）
    prior_test_names: list[str] = []            # P8.2：cpp 课程累积 CTest 回归名
    ms_titles = {m["milestoneId"]: m["title"] for m in blueprint.get("milestones") or []}
    passed_count = 0

    for index, spec in enumerate(order):
        task_id = spec["taskId"]
        _update(release_id, status="verifying", current_task=task_id,
                progress=int(index * 90 / max(total, 1)))

        evidence = {}
        for ev in spec.get("sourceEvidence") or []:
            path = ev.get("path", "")
            if path in snapshot_files:
                evidence[path] = snapshot_files[path]

        if language == "cpp":
            # ---- P8.2：C++/CMake 流水线（八步真实验证 + 有限修复轮）----
            outcome = _process_cpp_task(
                provider, release_id, task_id, spec, order, total,
                ms_titles.get(spec.get("milestoneId"), ""),
                cumulative_reference, prior_test_names, evidence,
                prior.get(task_id), index == total - 1,
            )
            if not outcome["passed"]:
                artifacts_public.append(outcome["artifact"])
                _update(release_id, status="failed",
                        error=f"任务 {task_id} 验证失败：{outcome['error']}",
                        artifacts=[*artifacts_public], reference_store=reference_store,
                        progress=100, current_task=task_id,
                        verification_report={"passed": passed_count, "total": total,
                                             "failed_task": task_id})
                return
            cumulative_reference = outcome["cumulative_reference"]
            prior_test_names = outcome["prior_test_names"]
            reference_store[task_id] = outcome["reference_delta"]
            artifacts_public.append(outcome["artifact"])
            passed_count += 1
            continue

        material = lesson_builder.build_task_lesson(
            provider, spec, ms_titles.get(spec.get("milestoneId"), ""),
            cumulative_reference, evidence, language,
            prior_failures=prior.get(task_id),
        )
        repairs: list[dict] = []
        verifications: list[dict] = []
        artifact_status = "generated"
        error_msg = None

        for attempt in range(MAX_REPAIR_PER_TASK + 1):
            # -- schema-valid：Pydantic 校验 + 防伪守卫
            try:
                artifact = _coerce_artifact(material, spec, language)
            except Exception as exc:
                error_msg = f"材料结构不合法：{exc}"
                if attempt < MAX_REPAIR_PER_TASK:
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [{"kind": "schema", "message": error_msg}], language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": [], "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            problems = guard_starter(
                material.get("starterFiles") or [],
                material.get("referenceFiles") or [],
                material.get("testFiles") or [],
                language,
                expected_files=(material.get("instructions") or {}).get("expectedFiles"),
            )
            if problems:
                error_msg = "防伪守卫：" + "; ".join(problems[:3])
                if attempt < MAX_REPAIR_PER_TASK:
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [{"kind": "guard", "message": p} for p in problems]
                        + [{"kind": "material-context", "message":
                            "当前生成的文件清单与摘要（修复必须针对这些文件）：\n"
                            + _material_context(material)}],
                        language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": [], "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            # -- build/tests：真实沙箱验证参考实现
            ref_files = merge_files(cumulative_reference,
                                    {f["path"]: f["content"] for f in material["referenceFiles"]})
            task_tests = {f["path"]: f["content"] for f in material["testFiles"]}
            run_files = {**ref_files, **task_tests}
            outcome = run_in_sandbox(
                language, run_files, "test", None,
                list(task_tests.keys()), timeout_s=60.0,
            )
            verifications.append({**outcome.to_dict(), "kind": "reference-tests"})
            if outcome.status != "passed":
                error_msg = f"参考实现测试未通过：{outcome.failed}/{outcome.total} 失败"
                # -- regression：前阶段测试在当前参考上（回归证据）
                if all_test_files:
                    reg_files = {**ref_files, **all_test_files}
                    reg = run_in_sandbox(language, reg_files, "test", None,
                                         list(all_test_files.keys()), timeout_s=60.0)
                    verifications.append({**reg.to_dict(), "kind": "regression"})
                if attempt < MAX_REPAIR_PER_TASK:
                    detail_errors = [
                        {"kind": v.get("kind") or "test", "message": v.get("message", "")}
                        for v in outcome.diagnostics
                    ] or [{"kind": "test", "message": error_msg}]
                    detail_errors.append({
                        "kind": "stdout",
                        "message": (outcome.stdout_tail or "")[-1500:],
                    })
                    detail_errors.append({
                        "kind": "stderr",
                        "message": (outcome.stderr_tail or "")[-800:],
                    })
                    material = lesson_builder.repair_task_lesson(
                        provider, material, detail_errors, language)
                    repairs.append({"round": attempt + 1, "problem": error_msg,
                                    "changedFiles": sorted(set(material.get("referenceFiles", []) and
                                                              [f["path"] for f in material["referenceFiles"]] +
                                                              [f["path"] for f in material.get("testFiles", [])])),
                                    "outcome": "still-failing"})
                    continue
                artifact_status = "failed"
                break

            # 通过：starter 期望失败证据（测试有效性 + 不泄露答案）
            starter_run = {**merge_files(cumulative_reference,
                                          {f["path"]: f["content"] for f in material["starterFiles"]}),
                           **task_tests}
            starter_outcome = run_in_sandbox(
                language, starter_run, "test", None,
                list(task_tests.keys()), timeout_s=45.0,
            )
            starter_ok = starter_outcome.status == "failed" or starter_outcome.failed > 0
            verifications.append({
                **starter_outcome.to_dict(),
                "kind": "starter-expected-fail",
                "status": "passed" if starter_ok else "failed",
            })
            if not starter_ok:
                # starter 全过 = 测试对本任务核心无效（答案泄露或测试空转）
                error_msg = "starter 全部测试通过——测试未覆盖本任务待实现逻辑（疑似泄露/空转）"
                if attempt < MAX_REPAIR_PER_TASK:
                    leak_context = json.dumps({
                        "starter": {f["path"]: f["content"][:1200] for f in material.get("starterFiles", [])},
                        "tests": {f["path"]: f["content"][:1200] for f in material.get("testFiles", [])},
                    }, ensure_ascii=False)
                    material = lesson_builder.repair_task_lesson(
                        provider, material,
                        [
                            {"kind": "starter-passes",
                             "message": error_msg + "。当前 starter 与测试内容：" + leak_context[:6000]
                             + "。修复方向：starter 必须删除本任务核心实现只留 TODO 骨架（保留接口签名/文档字符串）；或者测试必须新增针对待实现功能的断言。"},
                        ], language)
                    continue
                artifact_status = "failed"
                break

            # 成功：更新修复轮结论 + 累积快照
            if repairs:
                repairs[-1]["outcome"] = "fixed"
            cumulative_reference = ref_files
            all_test_files.update(task_tests)
            artifact_status = "tests-passed"
            error_msg = None

            artifact.status = artifact_status
            reference_store[task_id] = [{"path": f["path"], "content": f["content"]}
                                        for f in material["referenceFiles"]]
            art_dict = _coerce_artifact(material, spec, language).model_dump(mode="json", by_alias=True)
            art_dict["status"] = artifact_status
            art_dict["verifications"] = verifications
            art_dict["repairs"] = repairs
            art_dict["error"] = None
            art_dict.pop("reference_files", None)
            artifacts_public.append(art_dict)
            passed_count += 1
            break

        if artifact_status != "tests-passed":
            art_dict = {
                "task_id": task_id,
                "milestone_id": spec.get("milestoneId", ""),
                "language": language,
                "instructions": material.get("instructions") or
                                {"title": spec.get("title", task_id)},
                "starter_files": material.get("starterFiles") or [],
                "test_files": material.get("testFiles") or [],
                "hints": material.get("hints") or [],
                "status": "failed",
                "verifications": verifications,
                "repairs": repairs,
                "error": error_msg,
                "artifact_version": attempt + 1 if 'attempt' in dir() else 1,
                "generation_model": getattr(provider, "name", ""),
            }
            artifacts_public.append(art_dict)
            _update(release_id, status="failed", error=f"任务 {task_id} 验证失败：{error_msg}",
                    artifacts=artifacts_public, reference_store=reference_store,
                    progress=100, current_task=task_id,
                    verification_report={"passed": passed_count, "total": total,
                                         "failed_task": task_id})
            return

    # ---- 最终集成
    if language == "cpp":
        # P8.2：cpp 的最终集成（全量 CTest + demo 运行）已在最后一个任务的
        # 八步验证内完成（verify_cpp_cmake_task is_final）；此处只汇总报告。
        _update(release_id, status="verifying", progress=92)
        final_record = next(
            (v for a in artifacts_public for v in a.get("verifications", [])
             if v.get("kind") == "final-integration"), {})
        report = {
            "passed": passed_count, "total": total,
            "finalIntegration": final_record or {"status": "unknown"},
        }
        if not final_record or final_record.get("status") != "passed":
            _update(release_id, status="failed",
                    error="最终集成验证未通过（全部 CTest）",
                    artifacts=artifacts_public, verification_report=report, progress=100)
            return
        _update(release_id, status="ready", progress=100, current_task=None,
                artifacts=artifacts_public, reference_store=reference_store,
                verification_report=report, ready_at=utcnow())
        return

    # python：全部任务测试在最终参考快照上一次通过
    _update(release_id, status="verifying", progress=92)
    final = run_in_sandbox(language, {**cumulative_reference, **all_test_files},
                           "test", None, list(all_test_files.keys()), timeout_s=90.0)
    report = {
        "passed": passed_count, "total": total,
        "finalIntegration": final.to_dict(),
    }
    if final.status != "passed":
        _update(release_id, status="failed",
                error=f"最终集成验证未通过（{final.failed}/{final.total} 失败）",
                artifacts=artifacts_public, verification_report=report, progress=100)
        return

    _update(release_id, status="ready", progress=100, current_task=None,
            artifacts=artifacts_public, reference_store=reference_store,
            verification_report=report, ready_at=utcnow())


def _task_description(artifact: dict | None, spec: dict) -> str:
    instructions = (artifact or {}).get("instructions") or {}
    return (instructions.get("goal") or instructions.get("context")
            or spec.get("description", ""))[:900]


def _coerce_artifact(material: dict, spec: dict, language: str) -> LessonArtifact:
    instructions = dict(material.get("instructions") or {})
    instructions.setdefault("title", spec.get("title", ""))
    return LessonArtifact(
        task_id=spec["taskId"],
        milestone_id=spec.get("milestoneId", ""),
        language=language,
        instructions=instructions,
        starter_files=material.get("starterFiles") or [],
        test_files=material.get("testFiles") or [],
        reference_files=material.get("referenceFiles") or [],
        hints=material.get("hints") or [],
        status="schema-valid",
        generation_model="",
    )
