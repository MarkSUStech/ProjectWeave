"""P8.2.3.3（D51）专项测试：路径规范化/循环检测/工作记忆/压缩/恢复/
Checkpoint 绑定/Final Repair 发布链。"""

import json
from unittest import mock

import pytest

from app.domains.course_generation.harness.controller import HarnessController
from app.domains.course_generation.harness.memory import (
    LoopDetector,
    WorkingMemory,
    normalize_path_arg,
)
from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.change_set import FileChange


def _controller(ws=None, task_id="t1"):
    ws = ws or CourseWorkspace({"referenceFiles": {"a.cpp": "int a;"},
                                "starterOverlay": {},
                                "baseSnapshot": {"referenceFiles": {}}})
    ctrl = HarnessController(
        db_factory=None, session_id=None, workspace=ws,
        provider=type("P", (), {"name": "test"})(),
        task_spec={"taskId": task_id, "title": "T"}, prior_tests=[])
    ctrl.timeline = []
    ctrl.llm_messages = []
    return ctrl, ws


def _result(content=None, tool_calls=None):
    return type("R", (), {
        "content": content, "tool_calls": tool_calls or [],
        "prompt_tokens": 10, "completion_tokens": 10, "model": "t"})()


# ---------------------------------------------------------------- 根因修复：路径规范化


def test_normalize_path_arg_strips_quotes():
    """t4 死循环根因：模型传带引号路径。"""
    assert normalize_path_arg('"tests/test_x.cpp"') == "tests/test_x.cpp"
    assert normalize_path_arg("'src/main.cpp'") == "src/main.cpp"
    assert normalize_path_arg("  CMakeLists.txt ") == "CMakeLists.txt"
    assert normalize_path_arg("`app/main.cpp`") == "app/main.cpp"
    assert normalize_path_arg("plain/path.cpp") == "plain/path.cpp"


# ---------------------------------------------------------------- Loop Detector


def test_loop_detector_fingerprint_and_counts():
    detector = LoopDetector(warn_after=1, hard_after=3)
    fp = detector.fingerprint("read_workspace_file",
                              {"path": '"a.cpp"', "offset": 0}, 5, "hash1")
    assert detector.observe(fp) == 1
    assert detector.observe(fp) == 2
    assert detector.observe(fp) == 3  # 达到 hard
    # 修改后（hash 变）→ 新指纹，合法重读
    fp2 = detector.fingerprint("read_workspace_file",
                               {"path": "a.cpp", "offset": 0}, 6, "hash2")
    assert detector.observe(fp2) == 1
    # 不同范围 → 新指纹
    fp3 = detector.fingerprint("read_workspace_file",
                               {"path": "a.cpp", "offset": 100}, 6, "hash2")
    assert detector.observe(fp3) == 1


# ---------------------------------------------------------------- Working Memory


def test_working_memory_read_tracking():
    memory = WorkingMemory(task_id="t1")
    assert memory.record_read("a.cpp", "h1", 1, 0, 100) is True   # 首次
    assert memory.record_read("a.cpp", "h1", 1, 0, 100) is False  # 完全重复
    assert memory.record_read("a.cpp", "h1", 1, 10, 90) is False   # 完全被 [0,100] 覆盖
    assert memory.record_read("a.cpp", "h1", 1, 50, 150) is True   # [100,150] 是新范围
    assert memory.record_read("a.cpp", "h1", 1, 0, 150) is False   # 并集已覆盖
    assert memory.record_read("a.cpp", "h1", 1, 200, 300) is True  # 新范围
    assert memory.record_read("a.cpp", "h2", 1, 0, 100) is True    # 版本变化
    assert memory.record_read("a.cpp", "h2", 2, 0, 100) is True    # revision 变化


def test_working_memory_roundtrip_and_summary():
    memory = WorkingMemory(task_id="t4", goal="Demo")
    memory.record_read("CMakeLists.txt", "h", 3, 0, 100)
    memory.record_modification("app/main.cpp", "创建 Demo 入口")
    memory.known_problems.append("链接错误")
    data = memory.to_dict()
    restored = WorkingMemory.from_dict(data)
    assert restored.goal == "Demo"
    assert "CMakeLists.txt" in restored.inspected
    assert restored.modified_files == ["app/main.cpp"]
    summary = restored.summary_prompt()
    assert "Demo" in summary and "CMakeLists.txt" in summary
    assert "无需重复读取" in summary


# ---------------------------------------------------------------- 循环防护读取工具（真实 handler）


def test_read_tool_loop_guard_returns_cached_then_blocked():
    from app.domains.course_generation.harness.tools import build_harness_tools
    from app.agents.schemas import ToolContext

    ctrl, ws = _controller()
    ctrl.init_memory()
    ctx = ToolContext(db=None, project_id=None)
    registry = build_harness_tools(ws, ctrl)

    # 带引号路径 → 规范化后成功读取（根因修复）
    r1 = registry._tools["read_workspace_file"].handler(ctx, path='"a.cpp"')
    assert "content" in r1 and r1["content"] == "int a;"
    # 相同范围重复 → 缓存摘要（不再返回完整内容）
    r2 = registry._tools["read_workspace_file"].handler(ctx, path="a.cpp")
    assert r2["status"] == "already-read"
    assert ctrl.memory.stats["cachedReads"] == 1
    # 继续重复 → repeated-no-new-information
    r3 = registry._tools["read_workspace_file"].handler(ctx, path="a.cpp")
    assert r3["status"] == "repeated-no-new-information"
    assert "recommendedActions" in r3


# ---------------------------------------------------------------- 压缩


def test_compact_context_preserves_pairing_and_system():
    ctrl, _ = _controller()
    ctrl.init_memory()
    ctrl.llm_messages = [
        {"role": "system", "content": "SYS"},
        *[{"role": "user", "content": f"old {i}"} for i in range(20)],
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r"},
        {"role": "assistant", "content": "done"},
    ]
    ctrl._compact_context()
    assert ctrl.llm_messages[0]["role"] == "system"
    assert ctrl.llm_messages[0]["content"] == "SYS"
    # tool_calls 配对保持
    cleaned = HarnessController._sanitize_messages(ctrl.llm_messages)
    tool_calls_msgs = [m for m in cleaned if m.get("tool_calls")]
    tool_msgs = [m for m in cleaned if m.get("role") == "tool"]
    assert len(tool_msgs) >= len(tool_calls_msgs)
    for m in tool_msgs:
        assert any(m["tool_call_id"] in
                   {c.get("id") for c in t["tool_calls"]}
                   for t in tool_calls_msgs)
    assert ctrl.memory.stats["compactions"] == 1


# ---------------------------------------------------------------- Progress + Recovery


def test_stagnation_triggers_recovery_levels():
    """连续无进展 → L1 提醒 → L2 重规划 → L3 压缩 → 超 max 停止。"""
    ctrl, _ = _controller()
    ctrl.init_memory()
    ctrl.max_stagnation = 1
    ctrl.llm_messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "u"},
    ]
    provider_calls = {"n": 0}

    class LoopProvider:
        name = "loop"

        def chat_with_tools(self, messages, tools):
            provider_calls["n"] += 1
            # 返回文本（无工具）→ 无进展
            return _result(content="thinking...")

    ctrl.provider = LoopProvider()
    ctrl.control_state = None
    ctrl.run()
    # 恢复发生过且未无限循环
    assert ctrl.memory.stats["recoveries"] >= 1
    assert ctrl.recovery_level <= ctrl.max_recovery + 1
    assert provider_calls["n"] <= 20  # 未失控
    assert any(e.get("kind") == "recovery"
               for e in ctrl.timeline)


def test_modification_resets_stagnation():
    ctrl, _ = _controller()
    ctrl.init_memory()
    ctrl.memory.rounds_since_progress = 4
    ctrl.memory.record_modification("a.cpp", "修改 a.cpp")
    assert ctrl.memory.rounds_since_progress == 0
    assert ctrl.memory.stats["meaningfulEdits"] == 1


# ---------------------------------------------------------------- Checkpoint 版本绑定


def test_submit_rejected_after_post_checkpoint_modification():
    """保存 Checkpoint 后修改工作区 → submit 拒绝（D51 绑定）。"""
    ctrl, ws = _controller()
    ctrl.init_memory()
    # 模拟评估通过 + 保存
    ctrl.last_evaluation = type("E", (), {
        "engineering": "passed", "stability": "passed", "pedagogy": "passed",
        "verifications": [], "problems": []})()
    ctrl.eval_fingerprint = ctrl.evaluation_fingerprint()
    ctrl.saved_checkpoint_fingerprint = ctrl.eval_fingerprint
    ctrl.checkpoint_saved = True
    assert ctrl.submit_task()["ok"] is True

    # 保存后修改 → 指纹变化 → submit 拒绝
    ctrl2, ws2 = _controller()
    ctrl2.init_memory()
    ctrl2.last_evaluation = ctrl.last_evaluation
    ctrl2.eval_fingerprint = ctrl2.evaluation_fingerprint()
    ctrl2.saved_checkpoint_fingerprint = ctrl2.eval_fingerprint
    ctrl2.checkpoint_saved = True
    ws2.apply_changes([FileChange(path="b.cpp", operation="create",
                                  content="new")])
    result = ctrl2.submit_task()
    assert result["ok"] is False
    assert "Fingerprint 不匹配" in result["error"]


# ---------------------------------------------------------------- normalize quote paths in apply


def test_apply_changes_normalizes_quoted_paths():
    from app.domains.course_generation.harness.tools import _apply_changes

    ctrl, ws = _controller()
    ctrl.init_memory()
    result = _apply_changes(ws, [
        {"path": '"b.cpp"', "operation": "create", "content": "int b;"}],
        harness=ctrl)
    assert result.get("ok"), result
    assert "b.cpp" in ws.reference_files
    assert ctrl.memory.stats["meaningfulEdits"] == 1


# ---------------------------------------------------------------- Final Repair 发布链（受控单元）


def test_publish_uses_repair_snapshot_over_last_checkpoint(tmp_path, monkeypatch):
    """Gate 3：__final_repair__ 检查点存在 → 发布快照 = 修复版（非旧版）。"""
    from app.domains.course_generation.harness import service as hs
    from app.domains.course_generation.harness.models import CourseDevSession
    from app.domains.course_generation.models import CourseCheckpoint
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.domains.course_generation.models import (  # noqa: F401 注册全部模型
        CourseGeneration,
        CourseRelease,
    )
    import app.domains.course_generation.harness.models  # noqa: F401
    import app.domains.curriculum.models  # noqa: F401
    import app.domains.projects.models  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(hs, "_session_factory", factory)
    from app.domains.course_generation.lessons import lesson_publisher as _lp
    monkeypatch.setattr(_lp, "_session_factory", factory)

    with factory() as db:
        gen = CourseGeneration(
            id=_uuid(), source_url="d:x", status="published", progress=100,
            blueprint={"project": {"title": "T", "description": "d",
                                   "sourceUrl": "u", "commitSha": "a" * 40,
                                   "license": {}, "techStack": ["C++20"],
                                   "goals": [], "nonGoals": []}},)
        db.add(gen)
        session = CourseDevSession(
            id=_uuid(), generation_id=gen.id,
            state="final-repairing",
            workspace={"taskOrder": ["t1"], "tasks": [
                {"taskId": "t1", "milestoneId": "ms-1", "title": "T",
                 "dependsOn": [], "deliverables": ["x"],
                 "acceptanceCriteria": ["a"]}],
                "milestones": [{"milestoneId": "ms-1", "title": "m",
                                "deliverables": ["x"],
                                "acceptanceCriteria": ["a"], "dependsOn": []}],
                "completedTaskIds": ["t1"]})
        db.add(session)
        # 原检查点（旧版 main）
        db.add(CourseCheckpoint(
            release_id=None, generation_id=gen.id, task_seq=0, task_id="t1",
            blueprint_hash=hs._harness_blueprint_hash(session.workspace),
            protocol_version="cpp-changeset-v1",
            sandbox_image="projectweave-sandbox-cpp:clang15-bookworm",
            snapshot_files={"app/main.cpp": "OLD"},
            test_registry=["w"],
            artifact={"taskId": "t1", "buildManifest": {
                "buildTargets": [], "testNames": ["w"], "runTargets": []}}))
        # 修复检查点（新版 main）
        db.add(CourseCheckpoint(
            release_id=None, generation_id=gen.id, task_seq=1,
            task_id="__final_repair__",
            blueprint_hash=hs._harness_blueprint_hash(session.workspace),
            protocol_version="cpp-changeset-v1",
            sandbox_image="projectweave-sandbox-cpp:clang15-bookworm",
            snapshot_files={"app/main.cpp": "FIXED"},
            test_registry=["w"],
            artifact={"taskId": "__final_repair__", "buildManifest": {
                "buildTargets": [], "testNames": ["w"], "runTargets": []}},
            reference_delta=[{"path": "app/main.cpp", "content": "FIXED"}]))
        db.commit()

        captured = {}

        def fake_run(files, mode="test", **kwargs):
            captured["final_files"] = dict(files)
            return type("O", (), {"ok": True, "test_results": [],
                                  "diagnostics": []})()

        import app.domains.course_generation.harness.service as _svc
        import app.domains.course_generation.harness.evaluator as _ev
        import app.domains.course_generation.verification.course_verifier as _cv
        ok_stability = {"attempts": 2, "passes": 2, "failures": 0,
                        "failureDistribution": [], "flakySuspected": False}
        with mock.patch.object(_cv, "run_cmake_operation",
                               side_effect=fake_run),              mock.patch.object(_ev, "run_cmake_operation",
                              side_effect=fake_run),              mock.patch.object(_ev, "run_stability",
                              side_effect=lambda *a, **k: dict(ok_stability)):
            result = hs._publish_release(db, session)

        assert result["ok"], result
        assert captured["final_files"]["app/main.cpp"] == "FIXED"
        assert result["finalReport"]["usedFinalRepairSnapshot"] is True
        # 原 t1 检查点未被覆盖
        t1 = db.scalar(__import__("sqlalchemy").select(CourseCheckpoint).where(
            CourseCheckpoint.task_id == "t1"))
        assert t1.snapshot_files["app/main.cpp"] == "OLD"
        # 发布的 reference_store 含修复 delta
        release = db.scalar(__import__("sqlalchemy").select(CourseRelease))
        assert release.reference_store["t1"][0]["content"] == "FIXED"


def _uuid():
    import uuid

    return uuid.uuid4()
