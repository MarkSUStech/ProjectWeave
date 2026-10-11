"""工具注册表：白名单注册、参数校验与执行（模型只能提议，不能执行）。"""

from __future__ import annotations

from app.agents.schemas import ToolCallRecord, ToolContext, ToolSpec


class UnknownToolError(KeyError):
    """请求的工具不在白名单。"""


class ToolArgumentError(ValueError):
    """工具参数不合法。"""


class _Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"工具重复注册：{spec.name}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def openai_tools(self) -> list[dict]:
        """导出为 OpenAI 兼容 tools 参数（仅名字/描述/Schema——不含 handler）。"""
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


registry = _Registry()


def validate_args(spec: ToolSpec, args: object) -> dict:
    """最小充分校验：args 必须是对象；required 字段存在且类型正确。

    每个 ToolSpec 的 parameters 是 JSON Schema（type/properties/required）；
    这里做确定性检查（而非信任模型自描述），深层校验由各工具的
    Pydantic 模型在 handler 内完成。
    """
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
    spec: ToolSpec, ctx: ToolContext, args: dict, round_no: int
) -> ToolCallRecord:
    """执行一个白名单工具：校验 → 调用 → 截断 → 记录（异常不外抛）。"""
    import json
    import time

    started = time.monotonic()
    try:
        args = validate_args(spec, args)
        result = spec.handler(ctx, **args)
        text = json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > spec.max_result_chars:
            text = text[: spec.max_result_chars] + "…（截断）"
        duration = int((time.monotonic() - started) * 1000)
        return ToolCallRecord(
            tool=spec.name, args=args, ok=True, round=round_no,
            duration_ms=duration, summary=text,
        )
    except Exception as exc:  # 工具失败以错误结果回给模型（可恢复），不中断运行
        duration = int((time.monotonic() - started) * 1000)
        return ToolCallRecord(
            tool=spec.name, args=args if isinstance(args, dict) else {},
            ok=False, round=round_no, duration_ms=duration,
            error=str(exc)[:300],
        )
