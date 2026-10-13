"""P8.2.3.1 确定性加固测试（无 Docker）：Fingerprint/Stale/Resume/PublishPolicy。"""

import pytest

from app.domains.course_generation.harness.controller import HarnessController
from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.change_set import FileChange, content_hash


def _controller(ws=None):
    ws = ws or CourseWorkspace({"referenceFiles": {}, "starterOverlay": {},
                                "baseSnapshot": {"referenceFiles": {}}})
    ctrl = HarnessController(
        db_factory=None, session_id=None, workspace=ws,
        provider=type("P", (), {"name": "test"})(),
        task_spec={"taskId": "t1", "title": "T"},
        prior_tests=[])
    ctrl.timeline = []
    ctrl.llm_messages = []
    return ctrl, ws


def _apply(ws, changes):
    return ws.apply_changes([FileChange.model_validate(c) for c in changes])


class _FakeEval:
    def __init__(self, engineering="passed", stability="passed", pedagogy="passed"):
        self.engineering = engineering
        self.stability = stability
        self.pedagogy = pedagogy
        self.verifications = []
        self.problems = []


# ---------------------------------------------------------------- Fingerprint


def test_fingerprint_changes_on_any_modification():
    ctrl, ws = _controller()
    _apply(ws, [{"path": "a.cpp", "operation": "create", "content": "x"}])
    fp1 = ctrl.evaluation_fingerprint()
    _apply(ws, [{"path": "a.cpp", "operation": "update",
                 "baseHash": content_hash("x"), "content": "y"}])
    assert ctrl.evaluation_fingerprint() != fp1
    # starter overlay 修改也变
    _apply(ws, [{"path": "a.cpp", "operation": "update", "content": "stub",
                 "target": "starter"}])
    assert ctrl.evaluation_fingerprint() != fp1
    # manifest 修改也变
    ws.update_material(manifest={"testNames": ["t"]})
    assert ctrl.evaluation_fingerprint() != fp1


def test_fingerprint_stable_when_no_change():
    ctrl, _ = _controller()
    assert ctrl.evaluation_fingerprint() == ctrl.evaluation_fingerprint()


# ---------------------------------------------------------------- Stale


def test_modification_invalidates_evaluation():
    ctrl, ws = _controller()
    ctrl.last_evaluation = _FakeEval()
    ctrl.eval_fingerprint = ctrl.evaluation_fingerprint()
    ctrl.last_feedback = {"evaluation": {"engineering": "passed"}}
    ctrl._invalidate_evaluation("测试修改")
    assert ctrl.last_evaluation is None
    assert ctrl.last_feedback["evaluation"]["engineering"] == "stale"
    assert ctrl.eval_fingerprint == ""


# ---------------------------------------------------------------- Checkpoint Policy


def test_checkpoint_rejected_on_stale_fingerprint():
    """评估通过后修改文件 → 指纹不匹配 → 保存拒绝（TOCTOU 防护）。"""
    ctrl, ws = _controller()
    ctrl.last_evaluation = _FakeEval()
    ctrl.eval_fingerprint = "old-fingerprint"  # 评估时的指纹
    result = ctrl.save_checkpoint()
    assert result["ok"] is False
    assert "Fingerprint 不匹配" in result["error"]


def test_checkpoint_rejected_on_stability_failure():
    ctrl, _ = _controller()
    ctrl.last_evaluation = _FakeEval(stability="flaky-suspected")
    result = ctrl.save_checkpoint()
    assert result["ok"] is False
    assert "稳定性" in result["error"]


def test_checkpoint_rejected_on_pedagogy_failure():
    ctrl, _ = _controller()
    ctrl.last_evaluation = _FakeEval(pedagogy="failed")
    result = ctrl.save_checkpoint()
    assert result["ok"] is False
    assert "教学约束" in result["error"]


def test_checkpoint_requires_evaluation():
    ctrl, _ = _controller()
    assert ctrl.save_checkpoint()["ok"] is False


# ---------------------------------------------------------------- Resume


def test_runtime_snapshot_roundtrip():
    """Runtime Snapshot 保存 → 新 controller → 原样恢复（文件/消息/指纹）。"""
    ctrl1, ws1 = _controller()
    _apply(ws1, [
        {"path": "engine/Entity.hpp", "operation": "create", "content": "class E {};"},
        {"path": "engine/Entity.cpp", "operation": "create", "content": "// impl"},
        {"path": "engine/Entity.cpp", "operation": "update", "content": "// TODO stub",
         "target": "starter"},
    ])
    ws1.update_material(manifest={"testNames": ["entity"]})
    ctrl1.llm_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "apply_file_changes", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'},
    ]
    ctrl1.eval_fingerprint = ctrl1.evaluation_fingerprint()
    ctrl1.last_feedback = {"evaluation": {"engineering": "passed"}}
    snapshot = ctrl1._slice_result()["runtimeSnapshot"]

    # 新控制器（模拟 resume）恢复
    ctrl2, _ = _controller()  # 全新 workspace（空基线）
    assert ctrl2.load_runtime(snapshot) is True
    assert ctrl2.workspace.reference_files["engine/Entity.hpp"] == "class E {};"
    assert ctrl2.workspace.starter_overlay["engine/Entity.cpp"] == "// TODO stub"
    assert ctrl2.workspace.manifest == {"testNames": ["entity"]}
    assert ctrl2.workspace.revision == ws1.revision
    assert len(ctrl2.llm_messages) == 3
    assert ctrl2.llm_messages[2]["tool_call_id"] == "call_1"
    assert ctrl2.eval_fingerprint == ctrl1.eval_fingerprint
    # 恢复后指纹仍与当前工作区一致（未失真）
    assert ctrl2.evaluation_fingerprint() == ctrl2.eval_fingerprint


def test_resume_rejects_incompatible_snapshot():
    ctrl, _ = _controller()
    other = {"protocolVersion": "harness-runtime-v1", "taskId": "t9",
             "blueprintHash": "x", "baseSnapshotHash": "y",
             "workspace": {"referenceFiles": {"a": "b"}}}
    assert ctrl.load_runtime(other) is False
    wrong_proto = dict(other, taskId="t1", protocolVersion="v0")
    assert ctrl.load_runtime(wrong_proto) is False





# ---------------------------------------------------------------- AcceptanceContract


def test_acceptance_contract_freezes_behaviors_and_regression():
    from app.domains.course_generation.harness.acceptance import (
        build_acceptance_contract,
        validate_manifest_against_contract,
    )

    contract = build_acceptance_contract(
        {"taskId": "t2", "title": "Entity",
         "acceptanceCriteria": ["Entity 创建后拥有有效 ID"]},
        prior_tests=["world_update"])
    assert contract.required_behaviors == ["Entity 创建后拥有有效 ID"]
    assert contract.prior_regression_tests == ["world_update"]
    assert contract.contract_hash()

    # Agent 可以增/改名自己的测试，但前序回归不可删除
    ok = validate_manifest_against_contract(
        contract, {"testNames": ["world_update", "entity_spawn"]}, None)
    assert ok == []
    bad = validate_manifest_against_contract(
        contract, {"testNames": ["entity_spawn"]}, {"testNames": ["world_update"]})
    assert any("world_update" in p for p in bad)


def test_controller_rejects_manifest_lowering():
    ctrl, _ = _controller()
    ctrl.init_acceptance_contract(
        {"taskId": "t1", "title": "T", "acceptanceCriteria": ["a"]},
        prior_tests=["prev_test"])
    ctrl.workspace.manifest = {"testNames": ["prev_test", "own_test"]}
    violations = ctrl.validate_manifest_update({"testNames": ["own_test"]})
    assert any("prev_test" in v for v in violations)
    # 保留前序 → 合法
    assert ctrl.validate_manifest_update(
        {"testNames": ["prev_test", "renamed"]}) == []


# ---------------------------------------------------------------- Final Repair 死状态（D50）


def test_build_final_repair_controller_not_422():
    """全部任务完成但发布失败 → _build_controller 进入修复控制器（不再 422）。"""
    from datetime import timedelta
    from unittest import mock

    from app.domains.course_generation.harness import service as hs
    from app.domains.course_generation.harness.models import CourseDevSession

    row = CourseDevSession(
        id=__import__("uuid").uuid4(), generation_id=__import__("uuid").uuid4(),
        state="final-repairing",
        workspace={"taskOrder": ["t1"], "tasks": [
            {"taskId": "t1", "milestoneId": "ms-1", "title": "T",
             "dependsOn": [], "deliverables": ["x"], "acceptanceCriteria": ["a"]}],
            "milestones": [{"milestoneId": "ms-1", "title": "m",
                            "deliverables": ["x"], "acceptanceCriteria": ["a"],
                            "dependsOn": []}],
            "completedTaskIds": ["t1"],
            "publishFailure": "最终全量 CTest 未通过：链接错误"})
    checkpoint = {"t1": {"task_seq": 0, "task_id": "t1",
                         "snapshot_files": {"CMakeLists.txt": "x"},
                         "test_registry": ["world_update"],
                         "artifact": {"buildManifest": {}},
                         "snapshot_hash": "h", "prev_snapshot_hash": "",
                         "reference_delta": [], "verification_evidence": [],
                         "diagnostics": {}, "task_spec_hash": "",
                         "created_at": ""}}
    with mock.patch(
        "app.domains.course_generation.lessons.lesson_publisher.load_compatible_checkpoints",
        return_value=checkpoint), \
         mock.patch.object(hs, "_provider", lambda: type("P", (), {"name": "x"})()):
        controller = hs._build_controller(row, lease=(row.id, "tok"))
    assert controller.final_phase == "repairing"
    assert controller.task_spec["taskId"] == "__final_repair__"
    assert "CMakeLists.txt" in controller.workspace.reference_files
    assert row.state == "final-repairing"


def test_classify_publish_failure_infra_vs_engineering():
    assert hs_classify("数据库连接失败 IntegrityError") == "infrastructure"
    assert hs_classify("租约已失效") == "infrastructure"
    assert hs_classify("最终全量 CTest 未通过：链接错误") == "engineering"


def hs_classify(error):
    from app.domains.course_generation.harness.service import (
        _classify_publish_failure,
    )

    return _classify_publish_failure(error)


# ---------------------------------------------------------------- Cooperative 取消（D50）


def test_cancel_blocks_llm_and_tools():
    """cancel_requested → run 循环立即终止（不再调 LLM/工具）。"""
    calls = {"llm": 0}

    class CancelledProvider:
        name = "cancel-test"

        def chat_with_tools(self, messages, tools):
            calls["llm"] += 1
            return _result(tool_calls=[{
                "id": f"c{calls['llm']}", "name": "list_workspace_files",
                "arguments": {}}])

    ctrl, ws = _controller()
    ctrl.provider = CancelledProvider()
    ctrl.control_state = {"pause_requested": False, "cancel_requested": True}
    ctrl._control_reader = lambda: ctrl.control_state
    result = ctrl.run()
    assert calls["llm"] == 0          # LLM 从未被调用（真正中断）
    assert result["completed"] is False
    assert any(e.get("kind") == "cancelled" for e in result["timeline"])


def test_pause_blocks_next_llm_round():
    calls = {"llm": 0}

    class OneToolProvider:
        name = "pause-test"

        def chat_with_tools(self, messages, tools):
            calls["llm"] += 1
            return _result(tool_calls=[{
                "id": f"c{calls['llm']}", "name": "list_workspace_files",
                "arguments": {}}])

    ctrl, ws = _controller()
    ctrl.provider = OneToolProvider()
    ctrl.control_state = {"pause_requested": False, "cancel_requested": False}
    state = {"paused": False}

    def reader():
        # 第一次 LLM 后收到暂停请求（模拟用户在工具执行期间暂停）
        state["paused"] = calls["llm"] >= 1
        return {"pause_requested": state["paused"],
                "cancel_requested": False}
    ctrl._control_reader = reader
    result = ctrl.run()
    assert calls["llm"] == 1          # 第二轮 LLM 前检测到暂停
    assert any(e.get("kind") == "paused" for e in result["timeline"])


def test_cancel_blocks_publish():
    from app.domains.course_generation.harness.service import _publish_release
    from app.domains.course_generation.harness.models import CourseDevSession

    row = CourseDevSession(
        id=__import__("uuid").uuid4(), generation_id=__import__("uuid").uuid4(),
        cancel_requested=True,
        workspace={"taskOrder": [], "tasks": [], "milestones": []})
    result = _publish_release(None, row)
    assert result["ok"] is False and "取消" in result["error"]


def _result(content=None, tool_calls=None):
    return type("R", (), {
        "content": content, "tool_calls": tool_calls or [],
        "prompt_tokens": 10, "completion_tokens": 10, "model": "test"})()


def test_sanitize_messages_orphan_tool_calls():
    """中断后的孤儿 tool_calls 补响应；孤儿 tool 消息删除（DeepSeek 400 修复）。"""
    ctrl, _ = _controller()
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_workspace_file", "arguments": "{}"}},
            {"id": "c2", "type": "function",
             "function": {"name": "list_workspace_files", "arguments": "{}"}}]},
        # c1 已响应，c2 被中断（孤儿 tool_calls）
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok": 1}'},
    ]
    cleaned = HarnessController._sanitize_messages(messages)
    tool_ids = [m.get("tool_call_id") for m in cleaned if m.get("role") == "tool"]
    assert tool_ids == ["c1", "c2"]  # c2 补中断响应
    c2 = next(m for m in cleaned
              if m.get("role") == "tool" and m.get("tool_call_id") == "c2")
    assert "中断" in c2["content"]
    # 孤儿 tool（无前导 tool_calls）被删
    orphan = [{"role": "tool", "tool_call_id": "ghost", "content": "x"}]
    assert HarnessController._sanitize_messages(orphan) == []
