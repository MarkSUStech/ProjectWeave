"""任务复杂度分析器（P8.2.2，D47）：课程任务工程复杂度的确定性估算。

输入为蓝图任务规格（deliverables/acceptance/description/依赖），输出可解释的
TaskComplexityReport。静态信息不足时给 unknown/estimate 区间，不伪称精确。
规则通用（按信号计分），不针对特定课程硬编码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 信号词（中英）：集成/多模块/入口/演示/全量测试
_INTEGRATION_RE = re.compile(
    r"集成|整合|integrat|连接|组合|协作|联调|wiring|connect", re.IGNORECASE)
_APP_ENTRY_RE = re.compile(
    r"demo|演示|入口|main|可执行程序|应用程序|app|CLI|最终交付|run.*target", re.IGNORECASE)
_FINAL_SYSTEM_RE = re.compile(
    r"全部测试|全量|最终系统|end.to.end|整体|完整.*验收|final", re.IGNORECASE)
_MODULE_RE = re.compile(r"模块|module|引擎|engine|库|library|系统|system", re.IGNORECASE)
_NEW_TEST_RE = re.compile(r"测试|test|ctest|验收", re.IGNORECASE)

# 阈值（分数 0-100）
SCORE_SPLIT_THRESHOLD = 60
SCORE_MEDIUM = 35


@dataclass
class TaskComplexityReport:
    task_id: str
    score: int
    level: str                      # low | medium | high | unknown
    estimated_changed_files: int = 0
    affected_modules: list[str] = field(default_factory=list)
    requires_new_target: bool = False
    requires_new_tests: bool = False
    is_final_integration: bool = False
    recommended_action: str = "keep"    # keep | split | unknown
    reasons: list[str] = field(default_factory=list)
    # 估算置信度：规格文本稀疏时降低
    confidence: str = "medium"          # low | medium | high

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id, "score": self.score, "level": self.level,
            "estimatedChangedFiles": self.estimated_changed_files,
            "affectedModules": self.affected_modules,
            "requiresNewTarget": self.requires_new_target,
            "requiresNewTests": self.requires_new_tests,
            "isFinalIntegration": self.is_final_integration,
            "recommendedAction": self.recommended_action,
            "reasons": self.reasons, "confidence": self.confidence,
        }


def analyze_task_complexity(task_spec: dict, successor_count: int = 0,
                            task_count: int = 0) -> TaskComplexityReport:
    """确定性复杂度估算：按任务规格信号计分。

    successor_count = 依赖本任务的任务数（0 = 终点任务）。
    """
    task_id = task_spec.get("taskId", "")
    title = task_spec.get("title", "")
    description = task_spec.get("description", "")
    deliverables = [str(d) for d in task_spec.get("deliverables") or []]
    acceptance = [str(a) for a in task_spec.get("acceptanceCriteria") or []]
    text = " ".join([title, description, *deliverables, *acceptance])

    if not text.strip():
        return TaskComplexityReport(task_id=task_id, score=0, level="unknown",
                                    recommended_action="unknown",
                                    reasons=["任务规格为空，无法评估"], confidence="low")

    reasons: list[str] = []
    score = 0

    # 1) 交付物数量（每项 +8，>2 项显著）
    if len(deliverables) >= 3:
        score += 12
        reasons.append(f"交付物较多（{len(deliverables)} 项）")
    elif len(deliverables) == 2:
        score += 6

    # 2) 集成 + 应用入口同时出现（最大风险组合：引擎侧胶水 + 可执行目标）
    has_integration = bool(_INTEGRATION_RE.search(text))
    has_app_entry = bool(_APP_ENTRY_RE.search(text))
    if has_integration and has_app_entry:
        score += 30
        reasons.append("同时要求模块集成与应用入口/演示（两类工程关注点耦合）")

    # 3) 终点任务 + 全量验收
    is_final = successor_count == 0 and task_count > 1
    has_final_system = bool(_FINAL_SYSTEM_RE.search(text))
    if is_final and has_final_system:
        score += 15
        reasons.append("终点任务且要求全量/最终系统验收")

    # 4) 验收条件数量（每个 +4）
    if len(acceptance) >= 3:
        score += 8
        reasons.append(f"验收条件较多（{len(acceptance)} 项）")

    # 5) 模块跨度（按提及的模块词粗估，静态信息有限 → 保守计入）
    module_words = set(_MODULE_RE.findall(text.lower()))
    if len(module_words) >= 3:
        score += 8
        reasons.append("涉及多个模块/子系统词汇")

    # 6) 新测试 + 新目标信号
    requires_new_tests = bool(_NEW_TEST_RE.search(text))
    requires_new_target = has_app_entry
    if requires_new_tests and requires_new_target:
        score += 8
        reasons.append("同时新增测试与可执行目标")

    score = min(score, 100)
    if score >= SCORE_SPLIT_THRESHOLD:
        level, action = "high", "split"
    elif score >= SCORE_MEDIUM:
        level, action = "medium", "keep"
    else:
        level, action = "low", "keep"

    # 置信度：规格文本长度短 → 低
    confidence = "high" if len(text) > 120 else ("medium" if len(text) > 40 else "low")

    return TaskComplexityReport(
        task_id=task_id, score=score, level=level,
        estimated_changed_files=max(2, score // 10),  # 估算区间用途，非精确值
        affected_modules=sorted(module_words)[:5],
        requires_new_target=requires_new_target,
        requires_new_tests=requires_new_tests,
        is_final_integration=is_final and has_integration,
        recommended_action=action if confidence != "low" else "unknown",
        reasons=reasons, confidence=confidence,
    )


def analyze_blueprint(blueprint: dict) -> list[TaskComplexityReport]:
    """整张蓝图的逐任务复杂度报告。"""
    tasks = blueprint.get("tasks") or []
    successors: dict[str, int] = {t.get("taskId", ""): 0 for t in tasks}
    for task in tasks:
        for dep in task.get("dependsOn") or []:
            successors[dep] = successors.get(dep, 0) + 1
    return [analyze_task_complexity(t, successors.get(t.get("taskId", ""), 0), len(tasks))
            for t in tasks]
