"""P8.2.3.1 确定性加固测试（无 Docker）：Fingerprint/Stale/Resume/PublishPolicy。"""

import pytest

from app.domains.course_generation.harness.controller import HarnessController
from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.change_set import FileChange, content_hash


def _controller(ws=None):
    ws = ws or CourseWorkspace({"referenceFiles": {}, "starterOverlay": {},
                                "baseSnapshot": {"referenceFiles": {}}})
    return HarnessController(
        db_factory=None, session_id=None, workspace=ws,
        provider=type("P", (), {"name": "test"})(),
        task_spec={"taskId": "t1", "title": "T"},
        prior_tests=[]), ws


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
    ctrl, _ = _controller(task_id="t2")
    other = {"protocolVersion": "harness-runtime-v1", "taskId": "t9",
             "blueprintHash": "x", "baseSnapshotHash": "y",
             "workspace": {"referenceFiles": {"a": "b"}}}
    assert ctrl.load_runtime(other) is False
    wrong_proto = dict(other, taskId="t2", protocolVersion="v0")
    assert ctrl.load_runtime(wrong_proto) is False


def _controller(task_id="t1"):
    ws = CourseWorkspace({"referenceFiles": {}, "starterOverlay": {},
                          "baseSnapshot": {"referenceFiles": {}}})
    return HarnessController(
        db_factory=None, session_id=None, workspace=ws,
        provider=type("P", (), {"name": "test"})(),
        task_spec={"taskId": task_id, "title": "T"},
        prior_tests=[]), ws


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
