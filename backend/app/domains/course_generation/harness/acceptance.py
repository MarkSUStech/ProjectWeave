"""Frozen AcceptanceContract（P8.2.3.1，D49）。

由任务规格（Course Architect 目标）+ 前序已验证测试构成，在任务开始时
冻结——Agent 可以实现/命名自己的测试（Agent-Produced Test Implementation），
但不能删除冻结语义要求（必需行为/前序回归/必需构建目标）。
update_course_material 的 manifest 变更由 Harness 校验不得降低契约。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class AcceptanceContract:
    task_id: str
    task_spec_hash: str
    required_behaviors: list[str] = field(default_factory=list)   # 冻结语义要求
    prior_regression_tests: list[str] = field(default_factory=list)
    contract_version: str = "acceptance-v1"

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id,
            "taskSpecHash": self.task_spec_hash,
            "requiredBehaviors": self.required_behaviors,
            "priorRegressionTests": list(self.prior_regression_tests),
            "contractVersion": self.contract_version,
        }

    def contract_hash(self) -> str:
        from app.domains.course_generation.lessons.consistency_validator import (
            snapshot_hash_of,
        )

        return snapshot_hash_of({"contract": json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False)})


def build_acceptance_contract(task_spec: dict,
                              prior_tests: list[str]) -> AcceptanceContract:
    """从冻结输入构建契约（任务验收语义 + 前序回归）。"""
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    behaviors = [str(a) for a in task_spec.get("acceptanceCriteria") or []]
    if not behaviors:
        behaviors = [f"完成 {task_spec.get('title', task_spec.get('taskId', ''))}"]
    return AcceptanceContract(
        task_id=task_spec.get("taskId", ""),
        task_spec_hash=snapshot_hash_of({"spec": json.dumps(
            task_spec, sort_keys=True, ensure_ascii=False, default=str)}),
        required_behaviors=behaviors,
        prior_regression_tests=list(prior_tests or []),
    )


def validate_manifest_against_contract(contract: AcceptanceContract,
                                       new_manifest: dict,
                                       old_manifest: dict | None) -> list[str]:
    """manifest 变更校验：不得删除前序回归要求（Agent 可增/改名自己的测试，
    但 prior_regression_tests 必须保留在新 testNames 或已注册测试中）。

    返回违规列表（空=合法）。语义要求（required_behaviors）由 Evaluator 的
    真实验证裁决——本函数只做确定性的回归不可降级检查。
    """
    problems: list[str] = []
    new_tests = set(new_manifest.get("testNames") or [])
    if old_manifest:
        old_tests = set(old_manifest.get("testNames") or [])
        dropped = old_tests - new_tests
        # 允许改名（Agent 重命名自己的测试），但前序回归不可消失
        for test in contract.prior_regression_tests:
            if test not in new_tests and test in dropped:
                problems.append(
                    f"契约违规：前序回归测试 {test} 被从 manifest 删除")
    for test in contract.prior_regression_tests:
        if test not in new_tests:
            problems.append(
                f"契约违规：必需回归测试 {test} 不在 buildManifest.testNames 中")
    return problems
