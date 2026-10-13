"""课程任务自动拆分（P8.2.2，D47）：高复杂度任务的确定性细化。

保守策略：只拆「终点集成任务同时承担 模块集成 + 应用入口/演示」这一
可确定边界的模式（按交付物/验收的关键词可分性判定；分不动就不拆）。
拆分只作用于 release 的私有蓝图快照——已发布蓝图/Checkpoint 不被触碰。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from app.domains.course_generation.generation.task_complexity import (
    analyze_blueprint,
)

_ENTRY_RE = re.compile(r"demo|演示|入口|main|可执行|app|程序|运行|CLI", re.IGNORECASE)
_INTEGRATION_RE = re.compile(r"集成|整合|integrat|连接|协作|接口|组合", re.IGNORECASE)


@dataclass
class TaskMapping:
    original_task_id: str
    new_task_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class RefinementResult:
    blueprint: dict
    mappings: list[TaskMapping] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    refined: bool = False

    def summary(self) -> dict:
        return {
            "refined": self.refined,
            "originalTaskCount": len(self.reports),
            "taskCount": len(self.blueprint.get("tasks") or []),
            "mappings": [{
                "originalTaskId": m.original_task_id,
                "newTaskIds": list(m.new_task_ids),
                "reason": m.reason,
            } for m in self.mappings],
            "complexity": self.reports,
        }


def _classify(items: list[str]) -> tuple[list[str], list[str], list[str]]:
    """把交付物/验收分到（集成侧, 入口侧, 无法分类）。"""
    integration_side, entry_side, unclassified = [], [], []
    for item in items:
        entry = bool(_ENTRY_RE.search(item))
        integration = bool(_INTEGRATION_RE.search(item))
        if entry and not integration:
            entry_side.append(item)
        elif integration and not entry:
            integration_side.append(item)
        elif entry and integration:
            integration_side.append(item)  # 混合语义归集成侧（入口任务专注交付程序）
        else:
            unclassified.append(item)
    return integration_side, entry_side, unclassified


def refine_blueprint(blueprint: dict) -> RefinementResult:
    """对高复杂度终点集成任务做确定性拆分；不可分则原样返回。"""
    reports = analyze_blueprint(blueprint)
    result = RefinementResult(blueprint=copy.deepcopy(blueprint),
                              reports=[r.to_dict() for r in reports])
    tasks = result.blueprint.get("tasks") or []
    by_report = {r.task_id: r for r in reports}
    split_done = False

    for index, task in enumerate(list(tasks)):
        task_id = task.get("taskId", "")
        report = by_report.get(task_id)
        if report is None or report.recommended_action != "split":
            continue
        if not report.is_final_integration:
            continue

        deliverables = [str(d) for d in task.get("deliverables") or []]
        acceptance = [str(a) for a in task.get("acceptanceCriteria") or []]
        int_del, entry_del, un_del = _classify(deliverables)
        int_acc, entry_acc, un_acc = _classify(acceptance)
        # 保守边界：不可分类条目过多 → 放弃拆分（不制造语义模糊任务）
        if len(un_del) + len(un_acc) > max(1, (len(deliverables) + len(acceptance)) // 3):
            result.reports[index]["recommendedAction"] = "keep"
            result.reports[index]["reasons"].append("拆分边界不可确定（保守保留）")
            continue
        # 两侧都必须有实际教学内涵（防凑数量）
        if not int_del and not int_acc:
            result.reports[index]["recommendedAction"] = "keep"
            result.reports[index]["reasons"].append("无独立集成侧目标（保守保留）")
            continue
        if not entry_del and not entry_acc:
            result.reports[index]["recommendedAction"] = "keep"
            result.reports[index]["reasons"].append("无独立入口侧目标（保守保留）")
            continue

        deps = list(task.get("dependsOn") or [])
        task_a = {
            **copy.deepcopy(task),
            "taskId": f"{task_id}-a",
            "title": f"{task.get('title', task_id)}（一）：模块集成",
            "description": (task.get("description", "")
                            + " 本任务只实现模块间的集成接口与集成测试，"
                              "不创建应用入口。").strip(),
            "deliverables": int_del or un_del or [f"集成接口"],
            "acceptanceCriteria": int_acc or ["集成测试通过且前序回归保持"],
        }
        task_b = {
            **copy.deepcopy(task),
            "taskId": f"{task_id}-b",
            "title": f"{task.get('title', task_id)}（二）：应用入口与最终验收",
            "description": (task.get("description", "")
                            + " 基于已完成的集成接口创建应用入口/演示目标，"
                              "并保证全量测试通过。").strip(),
            "dependsOn": [f"{task_id}-a"],
            "deliverables": entry_del or [f"演示程序"],
            "acceptanceCriteria": entry_acc or ["全量 CTest 通过且演示程序可运行"],
        }
        # 后继者改挂到 b（终点任务通常无后继，防御性处理）
        for other in result.blueprint.get("tasks") or []:
            other_deps = other.get("dependsOn") or []
            if task_id in other_deps and other.get("taskId") not in (task_id, f"{task_id}-a", f"{task_id}-b"):
                other["dependsOn"] = [f"{task_id}-b" if d == task_id else d
                                      for d in other_deps]

        pos = result.blueprint["tasks"].index(task)
        result.blueprint["tasks"][pos:pos + 1] = [task_a, task_b]
        result.mappings.append(TaskMapping(
            original_task_id=task_id, new_task_ids=[f"{task_id}-a", f"{task_id}-b"],
            reason="；".join(report.reasons) or "高复杂度终点集成任务"))
        split_done = True

    result.refined = split_done
    return result
