"""Agent 契约：工具规格、调用记录、预算与运行结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolContext:
    """服务端注入的工具执行上下文——LLM 不可见、不可指定。

    project_id 由 Tutor 服务从请求解析；工具以它与 LLM 提供的相对路径
    联合查询（DB 行级过滤），从根上杜绝跨项目访问与路径穿越。
    """

    db: Any  # SQLAlchemy Session（工具只读）
    project_id: Any  # str | UUID（__post_init__ 归一化为 UUID）
    owner_id: str = "dev-user"
    # 当前任务（前端 extras 传入；get_current_task 工具使用）
    current_task_id: str | None = None

    def __post_init__(self) -> None:
        import uuid as _uuid

        if isinstance(self.project_id, str):
            self.project_id = _uuid.UUID(self.project_id)


@dataclass
class ToolSpec:
    """白名单工具规格：名字、描述、JSON Schema 参数与处理器。

    handler(ctx: ToolContext, **args) -> dict —— 只读，返回可 JSON 化数据。
    """

    name: str
    description: str
    parameters: dict  # JSON Schema（OpenAI function 格式）
    handler: Callable[[ToolContext], dict]
    # 单次返回内容截断上限（字符），registry 兜底
    max_result_chars: int = 6000


@dataclass
class ToolCallRecord:
    """一次工具调用的完整可追踪记录（落库到 TeachingDecision.tool_calls）。"""

    tool: str
    args: dict
    ok: bool
    round: int
    duration_ms: int
    # 成功：结果 JSON 文本；失败：None
    summary: str = ""
    error: str | None = None


@dataclass
class AgentBudget:
    """Agent 资源预算（policy.py 强制；模型不可绕过）。"""

    max_rounds: int = 4          # LLM 调用轮数（含最终输出轮）
    max_tool_calls: int = 8      # 全程工具调用总次数
    max_total_tokens: int = 12000
    max_read_chars: int = 8000   # read_project_file 单次内容上限


@dataclass
class ToolLoopResult:
    """Provider 一轮返回：要么 tool_calls，要么最终文本。"""

    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    # [{id, name, arguments(dict)}]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


@dataclass
class AgentRunResult:
    """一次 Agent 运行的产物：最终文本 + 完整调用轨迹 + 用量。"""

    final_content: str
    tool_calls: list[ToolCallRecord]
    rounds: int
    prompt_tokens: int
    completion_tokens: int
    model: str
    stop_reason: str  # final-answer | budget-tokens | budget-rounds | budget-calls | forced-final


class AgentError(Exception):
    """Agent 运行失败（预算耗尽且无法产出最终决策等）。"""
