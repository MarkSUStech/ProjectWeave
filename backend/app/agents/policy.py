"""Agent 预算与权限策略（确定性代码强制，模型不可绕过）。"""

from __future__ import annotations

from app.agents.schemas import AgentBudget


class BudgetExceededError(Exception):
    """某项预算耗尽（runtime 捕获后转强制收尾）。"""


def check_round(budget: AgentBudget, rounds_done: int) -> None:
    if rounds_done >= budget.max_rounds:
        raise BudgetExceededError(f"轮数上限（{budget.max_rounds}）")


def check_tool_calls(budget: AgentBudget, calls_done: int, incoming: int) -> None:
    if calls_done + incoming > budget.max_tool_calls:
        raise BudgetExceededError(f"工具调用次数上限（{budget.max_tool_calls}）")


def check_tokens(budget: AgentBudget, used_tokens: int) -> None:
    if used_tokens > budget.max_total_tokens:
        raise BudgetExceededError(f"Token 预算上限（{budget.max_total_tokens}）")
