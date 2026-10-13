"""Course Harness 工具注册表（P8.2.3，D48）。

复用 P6 ToolRegistry（白名单 + 结构化截断）。工具分四组：Workspace /
Execution / Evaluation / Recovery。全部由服务端真实执行——不存在模拟
工具结果；Agent 无法提交任意 Shell（执行工具固定走受限 Docker CMake
Runtime）。
"""

from __future__ import annotations

from app.agents.registry import ToolRegistry
from app.agents.schemas import ToolSpec
from app.domains.course_generation.lessons.change_set import FileChange
from app.domains.course_generation.verification.course_verifier import (
    run_cmake_operation,
)

# 工具结果回填上限（字符）——防提示爆炸
TOOL_RESULT_LIMIT = 4000


def build_harness_tools(workspace, harness) -> ToolRegistry:
    """构建绑定当前 Workspace/Session 的工具白名单。

    workspace: CourseWorkspace；harness: HarnessController（评估/检查点/预算）。
    """
    reg = ToolRegistry("course-dev-agent")

    # ---------------- Workspace 工具 ----------------

    reg.register(ToolSpec(
        name="list_workspace_files",
        description="列出当前课程工作区文件（路径/大小/哈希/类别）。可选路径前缀过滤。",
        parameters={"type": "object",
                    "properties": {"prefix": {"type": "string"}},
                    "required": []},
        handler=lambda ctx, prefix="": {"files": workspace.list_files(prefix)[:60]},
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="read_workspace_file",
        description="读取工作区文件内容（支持行偏移与行数上限；同时给出 starter 挖空版预览）。",
        parameters={"type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "default": 0},
                        "limit": {"type": "integer", "default": 400}},
                    "required": ["path"]},
        handler=lambda ctx, path="", offset=0, limit=400:
            workspace.read_file(path, int(offset), int(limit)),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="apply_file_changes",
        description="原子应用文件变更列表（FileChange：create/update/delete + 完整新内容 + "
                    "target=reference|starter）。update 需 baseHash（可用 list/read 获取）；"
                    "starter 挖空变更基线为参考版（服务端权威回填）。",
        parameters={"type": "object",
                    "properties": {
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "operation": {"type": "string",
                                                  "enum": ["create", "update", "delete"]},
                                    "baseHash": {"type": "string"},
                                    "content": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "changeCategory": {"type": "string"},
                                    "target": {"type": "string",
                                               "enum": ["reference", "starter"]},
                                },
                                "required": ["path", "operation", "content"],
                            }}},
                    "required": ["changes"]},
        handler=lambda ctx, changes=None: _apply_changes(workspace, changes or []),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="update_course_material",
        description="更新课程材料元数据（buildManifest 的 buildTargets/runTargets/testNames、"
                    "instructions、hints）。验收目标不可借此删除——Evaluator 独立裁决。",
        parameters={"type": "object",
                    "properties": {
                        "buildManifest": {"type": "object"},
                        "instructions": {"type": "object"},
                        "hints": {"type": "array"},
                    }},
        handler=lambda ctx, buildManifest=None, instructions=None, hints=None:
            _update_material(workspace, buildManifest, instructions, hints,
                             harness=harness),
        max_result_chars=2000,
    ))

    # ---------------- Execution 工具（真实 Docker CMake Runtime） ----------------

    def _run_cmake(mode, cmake_action=None, target=None, selected=None, project="reference"):
        files = dict(workspace.reference_files)
        if project == "starter":
            files.update(workspace.starter_overlay)
        outcome = run_cmake_operation(
            files, mode=mode, cmake_action=cmake_action, target_name=target,
            selected_tests=selected)
        harness.record_sandbox_run()
        return {
            "status": "passed" if outcome.ok else "failed",
            "phases": outcome.phases,
            "exitCode": outcome.exit_code,
            "diagnostics": (outcome.diagnostics or [])[:8],
            "tests": [
                {"name": t.get("path"), "status": t.get("status"),
                 "error": (t.get("error") or "")[:200]}
                for t in (outcome.test_results or [])[:20]],
            "targets": [t.get("name") for t in (outcome.cmake or {}).get("targets") or []],
            "workspaceRevision": workspace.revision,
        }

    reg.register(ToolSpec(
        name="cmake_configure",
        description="在受限 Docker 沙箱对当前工程执行真实 CMake Configure + File API 目标发现。",
        parameters={"type": "object",
                    "properties": {"project": {"type": "string",
                                               "enum": ["reference", "starter"]}},
                    "required": []},
        handler=lambda ctx, project="reference": _run_cmake(
            "run", cmake_action="discover", project=project),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="cmake_build",
        description="真实构建指定目标（cmake --build --target；受限沙箱）。",
        parameters={"type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"]},
        handler=lambda ctx, target="": _run_cmake(
            "run", cmake_action="build", target=target),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="run_ctest",
        description="运行 CTest（可指定测试名集合；缺省=manifest 声明的必需测试）。",
        parameters={"type": "object",
                    "properties": {
                        "tests": {"type": "array", "items": {"type": "string"}},
                        "all": {"type": "boolean", "default": False}},
                    "required": []},
        handler=lambda ctx, tests=None, all=False: _run_cmake(
            "test", selected=None if all else (tests or workspace.manifest.get("testNames"))),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="run_executable",
        description="构建并运行可执行目标（demo 验证）。",
        parameters={"type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"]},
        handler=lambda ctx, target="": _run_cmake(
            "run", cmake_action="run", target=target),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    # ---------------- Evaluation 工具（独立 Evaluator） ----------------

    reg.register(ToolSpec(
        name="evaluate_lesson",
        description="对当前任务执行独立课程验收（工程正确性/教学约束/稳定性）。"
                    "Agent 不能自行宣布合格——必须以此工具的独立结果为准。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: harness.evaluate_current(),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    reg.register(ToolSpec(
        name="get_evaluation_feedback",
        description="读取最近一次评估的结构化反馈（失败分类/相关文件/建议检查）。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: harness.last_feedback or {"info": "尚无评估"},
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    # ---------------- Recovery 工具 ----------------

    reg.register(ToolSpec(
        name="save_checkpoint",
        description="保存 Verified Checkpoint。前置条件：evaluate_lesson 的 engineering=passed"
                    "（Harness 校验，失败即拒绝）。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: harness.save_checkpoint(),
        max_result_chars=2000,
    ))

    reg.register(ToolSpec(
        name="rollback_workspace",
        description="放弃当前工作区修改，恢复到最近 Verified Checkpoint（保留审计历史）。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: harness.rollback_to_checkpoint(),
        max_result_chars=2000,
    ))

    reg.register(ToolSpec(
        name="submit_task",
        description="声明当前任务开发完成（触发 Harness 最终评估与检查点；通过则进入下一任务）。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: harness.submit_task(),
        max_result_chars=TOOL_RESULT_LIMIT,
    ))

    return reg


def _apply_changes(workspace, raw_changes):
    normalized = []
    for entry in raw_changes:
        copy = dict(entry)
        copy.setdefault("operation", "update" if copy.get("content") else "delete")
        copy.setdefault("reason", "")
        copy.setdefault("changeCategory", "source")
        copy.setdefault("target", "reference")
        normalized.append(copy)
    try:
        changes = [FileChange.model_validate(entry) for entry in normalized]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "conflicts": [{
            "errorCode": "schema-error", "filePath": "<patch>",
            "expected": "合法 FileChange", "actual": str(exc)[:200]}]}
    result = workspace.apply_changes(changes)
    if result.get("ok"):
        harness.invalidate_evaluation_after_change()  # D49：修改即失效
    return result


def _update_material(workspace, manifest, instructions, hints, harness=None):
    manifest = manifest if isinstance(manifest, dict) else None
    instructions = instructions if isinstance(instructions, dict) else None
    hints = hints if isinstance(hints, list) else None
    if manifest is None and instructions is None and hints is None:
        return {"ok": False, "error": "至少提供一项材料更新"}
    if manifest is not None and harness is not None:
        violations = harness.validate_manifest_update(manifest)
        if violations:
            return {"ok": False,
                    "error": "冻结契约拒绝 manifest 变更：" + "; ".join(violations[:3])}
    workspace.update_material(manifest=manifest, instructions=instructions, hints=hints)
    harness.invalidate_evaluation_after_change()  # D49
    return {"ok": True, "revision": workspace.revision}
