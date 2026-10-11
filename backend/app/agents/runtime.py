"""Agent Runtime：后端控制的多轮工具调用循环。

流程：LLM 提议 tool_calls → 白名单校验 → 服务端执行（注入 ToolContext）
→ 结果作为 role=tool 消息回填 → 下一轮；模型返回纯文本（无 tool_calls）
即最终教学决策。预算由 policy 强制；耗尽时注入"立即输出"指令再做一次
无工具调用，仍失败则抛 AgentError。
"""

from __future__ import annotations

import json

from app.agents import policy
from app.agents.context import FORCE_FINAL_MESSAGE
from app.agents.registry import UnknownToolError, execute_tool, registry
from app.agents.schemas import (
    AgentBudget,
    AgentError,
    AgentRunResult,
    ToolCallRecord,
    ToolContext,
    ToolLoopResult,
)


def run_agent(
    provider,
    messages: list[dict],
    ctx: ToolContext,
    budget: AgentBudget | None = None,
) -> AgentRunResult:
    """执行 Agent 循环。provider 需实现 chat_with_tools（能力检测由调用方做）。"""
    budget = budget or AgentBudget()
    records: list[ToolCallRecord] = []
    rounds = 0
    prompt_tokens = 0
    completion_tokens = 0
    model = ""
    stop_reason = "final-answer"
    working = list(messages)
    forced = False  # 已注入"立即输出"指令（只注入一次）

    def total_used() -> int:
        return prompt_tokens + completion_tokens

    while True:
        try:
            policy.check_round(budget, rounds)
        except policy.BudgetExceededError as exc:
            raise AgentError(f"Agent 轮数耗尽且未产出最终决策：{exc}") from exc
        rounds += 1
        result: ToolLoopResult = provider.chat_with_tools(
            working, registry.openai_tools() if not forced else []
        )
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens
        model = model or result.model

        # 最终答案：模型返回文本且无工具调用
        if not result.tool_calls:
            if result.content and result.content.strip():
                return AgentRunResult(
                    final_content=result.content,
                    tool_calls=records, rounds=rounds,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    model=model, stop_reason=stop_reason,
                )
            # 空内容且无工具调用：视为异常轮，注入提示继续
            working.append({"role": "user", "content": FORCE_FINAL_MESSAGE})
            forced = True
            continue

        if forced:
            # 收尾轮仍请求工具：忽略请求，再推一次收尾指令（轮数检查会终止）
            working.append({"role": "user", "content": FORCE_FINAL_MESSAGE})
            continue

        # 工具调用预算
        try:
            policy.check_tool_calls(budget, len(records), len(result.tool_calls))
        except policy.BudgetExceededError:
            working.append({"role": "user", "content": FORCE_FINAL_MESSAGE})
            forced = True
            stop_reason = "budget-calls"
            continue

        # 记录 assistant 的 tool_calls 消息（OpenAI 完整协议格式回填：
        # 每个调用需 type=function + function{name, arguments(JSON 字符串)}）
        working.append({
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": [
                {
                    "id": call.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                    },
                }
                for call in result.tool_calls
            ],
        })

        for call in result.tool_calls:
            name = call.get("name", "")
            try:
                spec = registry.get(name)
            except UnknownToolError:
                record = ToolCallRecord(
                    tool=name, args=call.get("arguments", {}), ok=False,
                    round=rounds, duration_ms=0,
                    error=f"未知工具：{name}（白名单外）",
                )
                records.append(record)
                working.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", name),
                    "content": json.dumps({"error": record.error}, ensure_ascii=False),
                })
                continue

            args = call.get("arguments", {})
            record = execute_tool(spec, ctx, args, rounds)
            records.append(record)
            payload = json.loads(record.summary) if record.ok else {"error": record.error}
            working.append({
                "role": "tool",
                "tool_call_id": call.get("id", name),
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            })

        # Token 预算：超限则下一轮强制收尾
        try:
            policy.check_tokens(budget, total_used())
        except policy.BudgetExceededError:
            working.append({"role": "user", "content": FORCE_FINAL_MESSAGE})
            forced = True
            stop_reason = "budget-tokens"

        # 轮数将尽：下一轮是最后一轮，提前注入收尾指令
        if not forced and rounds >= budget.max_rounds - 1:
            working.append({"role": "user", "content": FORCE_FINAL_MESSAGE})
            forced = True
            stop_reason = "budget-rounds"

    # 不可达：check_round 会在 max_rounds 耗尽时抛出
    raise AgentError("Agent 循环异常退出")


def agent_record_to_dicts(records: list[ToolCallRecord]) -> list[dict]:
    """调用轨迹 → 可 JSON 化列表（落库/下发前端）。"""
    return [
        {
            "tool": r.tool,
            "args": r.args,
            "ok": r.ok,
            "round": r.round,
            "durationMs": r.duration_ms,
            "summary": (r.summary[:400] + "…") if len(r.summary) > 400 else r.summary,
            "error": r.error,
        }
        for r in records
    ]
