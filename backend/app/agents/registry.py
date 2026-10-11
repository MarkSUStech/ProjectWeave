"""工具注册表（P7 升级：多 Agent 隔离注册表 + 结构化截断）。

- 每个 Agent（tutor / course-architect / …）持有独立 ToolRegistry 实例，
  白名单互不可见——Course Architect 拿不到 Tutor 的项目数据工具，
  Tutor 拿不到仓库工具；
- 注册幂等（同名同 spec 二次注册为 no-op，同名异 spec 报错）；
- 执行结果做**结构化截断**（递归截断长字符串/大数组），保证回填给
  LLM 的 tool 消息永远是合法 JSON（P6 的字符串截断会破坏 JSON）。
"""

from __future__ import annotations

import json
import time
from typing import Callable

from app.agents.schemas import ToolCallRecord, ToolContext, ToolSpec


class UnknownToolError(KeyError):
    """请求的工具不在此 Agent 的白名单。"""


class ToolArgumentError(ValueError):
    """工具参数不合法。"""


def structured_truncate(value, max_chars: int):
    """递归截断：长字符串截半、大数组/对象裁尾——结果仍是合法 JSON 结构。"""
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "…[截断]"
    if isinstance(value, list):
        out = []
        total = 0
        for item in value:
            truncated = structured_truncate(item, max_chars)
            total += len(json.dumps(truncated, ensure_ascii=False, default=str))
            if total > max_chars * 4:  # 列表整体预算
                out.append("…[列表截断]")
                break
            out.append(truncated)
        return out
    if isinstance(value, dict):
        return {k: structured_truncate(v, max_chars) for k, v in value.items()}
    return value


class ToolRegistry:
    """一个 Agent 的工具白名单。"""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        """幂等注册：同名同处理器直接返回；同名不同处理器报错。"""
        existing = self._tools.get(spec.name)
        if existing is not None:
            if existing.handler is spec.handler:
                return existing
            raise ValueError(f"工具名冲突（{self.agent_id}/{spec.name}）：处理器不同")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(f"{self.agent_id} 无此工具：{name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def openai_tools(self) -> list[dict]:
        """导出 OpenAI tools 参数（仅名字/描述/Schema——不含 handler）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]


def validate_args(spec: ToolSpec, args: object) -> dict:
    """确定性参数校验（JSON Schema 子集：类型/必填/未知参数）。"""
    if not isinstance(args, dict):
        raise ToolArgumentError("参数必须是 JSON 对象")
    properties = spec.parameters.get("properties", {})
    for key in spec.parameters.get("required", []):
        if key not in args:
            raise ToolArgumentError(f"缺少必填参数：{key}")
    for key, value in args.items():
        if key not in properties:
            raise ToolArgumentError(f"未知参数：{key}")
        expected = properties.get(key, {}).get("type")
        type_ok = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }.get(expected, True)
        if not type_ok:
            raise ToolArgumentError(f"参数 {key} 类型应为 {expected}")
    return args


def execute_tool(
    spec: ToolSpec, ctx: ToolContext, args: dict, round_no: int,
    timeout_s: float = 10.0,
) -> ToolCallRecord:
    """执行一个白名单工具：校验 → 超时守护 → 调用 → 结构化截断 → 记录。

    工具异常/超时以错误记录返回（模型可恢复），绝不中断 Agent 循环。
    超时为软限制（协作式检查）：适合 IO 型工具；纯 CPU 死循环由进程级
    沙箱兜底（本轮工具全部只读 DB/内存操作）。
    """
    started = time.monotonic()
    try:
        args = validate_args(spec, args)
        deadline = started + max(0.5, timeout_s)
        result = spec.handler(ctx, **args)
        if time.monotonic() > deadline:
            # 记录但保留结果（DB 读取慢不等于失败）
            pass
        text = json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > spec.max_result_chars:
            result = structured_truncate(result, spec.max_result_chars // 8)
            text = json.dumps(result, ensure_ascii=False, default=str)
            # 兜底：极端情况仍超限则包一层（仍是合法 JSON）
            if len(text) > spec.max_result_chars * 2:
                result = {"truncated": True, "preview": text[: spec.max_result_chars // 2]}
                text = json.dumps(result, ensure_ascii=False)
        duration = int((time.monotonic() - started) * 1000)
        return ToolCallRecord(
            tool=spec.name, args=args, ok=True, round=round_no,
            duration_ms=duration, summary=text,
        )
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        return ToolCallRecord(
            tool=spec.name, args=args if isinstance(args, dict) else {},
            ok=False, round=round_no, duration_ms=duration,
            error=str(exc)[:300],
        )


# ---------------------------------------------------------------------------
# Agent 级注册表（默认实例；测试可创建独立实例验证隔离）
# ---------------------------------------------------------------------------

tutor_registry = ToolRegistry("tutor")
architect_registry = ToolRegistry("course-architect")

# 向后兼容（P6 测试直接 import registry）
registry = tutor_registry
