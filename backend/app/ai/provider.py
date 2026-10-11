"""可替换的 LLM Provider Adapter（设计 §11.2/§11.4；P6 增加工具调用协议）。

- DeepSeekProvider：真实实现（OpenAI 兼容 chat/completions），记录 Token 用量；
  `chat()` 单次 JSON 输出（原有契约不变）；`chat_with_tools()` 原生
  function calling（tools 参数 + tool_calls 响应 + role=tool 回填）。
- MockProvider：确定性桩，**仅用于测试**；支持脚本化多轮工具调用
  （scripted_rounds 按轮弹出）。
- disabled：未配置时明确降级（raise ProviderDisabledError），绝不伪造回复。

Provider 与 Agent Runtime 解耦：Provider 只懂消息与工具协议，
循环控制/预算/权限全部在 app/agents/。
"""

import json
from dataclasses import dataclass, field

import httpx

from app.agents.schemas import ToolLoopResult
from app.core.config import settings


class ProviderError(Exception):
    """LLM 调用失败（网络/认证/限流等）。"""


class ProviderDisabledError(ProviderError):
    """AI 未配置——调用方应返回明确的未配置状态，而不是伪造回复。"""


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class LLMProvider:
    name = "abstract"
    supports_tools = False

    def chat(self, system: str, user: str) -> LLMResult:
        raise NotImplementedError

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> ToolLoopResult:
        """Agent 模式一轮调用。tools 为空 = 收尾轮（禁止工具）。

        返回 ToolLoopResult：content（最终文本）或 tool_calls
        [{id, name, arguments(dict)}]。不支持工具的 Provider 不实现此方法
        （supports_tools=False，调用方走单次 chat 降级路径）。
        """
        raise NotImplementedError(f"{self.name} 不支持工具调用")


class DeepSeekProvider(LLMProvider):
    """DeepSeek（OpenAI 兼容 API）。系统提示与用户内容分开发送。

    transport 参数仅供测试注入 httpx.MockTransport，生产为 None（默认 httpx）。
    """

    name = "deepseek"
    supports_tools = True

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: float | None = None,
                 transport=None) -> None:
        self.api_key = settings.deepseek_api_key if api_key is None else api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model
        self.timeout = timeout if timeout is not None else settings.ai_timeout_seconds
        self._client = httpx.Client(transport=transport) if transport is not None else httpx
        if not self.api_key:
            raise ProviderDisabledError("未配置 PW_DEEPSEEK_API_KEY")

    def _post(self, payload: dict) -> dict:
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"DeepSeek 网络错误：{exc}") from exc
        if response.status_code in (401, 403):
            raise ProviderError("DeepSeek 认证失败（检查 API Key）")
        if response.status_code == 429:
            raise ProviderError("DeepSeek 限流，请稍后重试")
        if response.status_code != 200:
            raise ProviderError(f"DeepSeek 返回 {response.status_code}：{response.text[:200]}")
        return response.json()

    @staticmethod
    def _usage(data: dict) -> tuple[int, int]:
        usage = data.get("usage", {})
        return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    def chat(self, system: str, user: str) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        data = self._post(payload)
        try:
            message = data["choices"][0]["message"]["content"]
            pt, ct = self._usage(data)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"DeepSeek 响应格式异常：{json.dumps(data)[:200]}") from exc
        return LLMResult(content=message, prompt_tokens=pt, completion_tokens=ct,
                         model=data.get("model", self.model))

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> ToolLoopResult:
        # 注意：DeepSeek 的 json_object 与 tools 不兼容——工具模式不加
        # response_format，最终 JSON 由系统提示约束（Agent 侧解析失败即降级）。
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        else:
            payload["tool_choice"] = "none"
        data = self._post(payload)
        try:
            message = data["choices"][0]["message"]
            pt, ct = self._usage(data)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"DeepSeek 响应格式异常：{json.dumps(data)[:200]}") from exc

        tool_calls: list[dict] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {"_raw": str(raw_args)[:200]}
            tool_calls.append({
                "id": call.get("id", ""),
                "name": function.get("name", ""),
                "arguments": args,
            })
        return ToolLoopResult(
            content=message.get("content"),
            tool_calls=tool_calls,
            prompt_tokens=pt, completion_tokens=ct,
            model=data.get("model", self.model),
        )


@dataclass
class ScriptedRound:
    """MockProvider 的单轮脚本：tool_calls 或最终内容。"""

    tool_calls: list[dict] = field(default_factory=list)
    content: str | None = None


class MockProvider(LLMProvider):
    """测试专用确定性桩：返回预设 JSON（在测试中按需覆写 default_response）。

    Agent 模式：设置 scripted_rounds=[ScriptedRound(...), ...] 按轮弹出；
    未设置时第一轮请求一个固定工具、第二轮给 default_response。
    chat_with_tools_calls 记录每轮收到的消息（供测试断言工具结果已回填）。
    """

    name = "mock"
    supports_tools = True

    def __init__(self) -> None:
        self.default_response: dict = {
            "intent": "hint",
            "hintLevel": 1,
            "message": "（mock 提示）想一想输入事件发生后，状态是怎么变化的？",
            "targetConceptIds": ["js.callbacks-events"],
            "explanation": "mock 决策",
            "confidence": 0.5,
        }
        self.calls: list[dict] = []
        self.scripted_rounds: list[ScriptedRound] = []
        self.chat_with_tools_calls: list[dict] = []

    @property
    def llm_call_count(self) -> int:
        """合计 LLM 调用次数（chat + chat_with_tools）。"""
        return len(self.calls) + len(self.chat_with_tools_calls)

    def chat(self, system: str, user: str) -> LLMResult:
        self.calls.append({"system": system, "user": user})
        return LLMResult(
            content=json.dumps(self.default_response, ensure_ascii=False),
            prompt_tokens=len(system) + len(user),
            completion_tokens=64,
            model="mock",
        )

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> ToolLoopResult:
        self.chat_with_tools_calls.append({
            "messages": json.dumps(messages, ensure_ascii=False, default=str),
            "tool_names": [t["function"]["name"] for t in tools],
        })
        if self.scripted_rounds:
            scripted = self.scripted_rounds.pop(0)
        else:
            # 默认脚本：第一轮要一个工具，随后给最终决策
            if not any(m.get("role") == "tool" for m in messages):
                scripted = ScriptedRound(tool_calls=[
                    {"id": "call-1", "name": "list_project_files", "arguments": {}}
                ])
            else:
                scripted = ScriptedRound(content=json.dumps(self.default_response, ensure_ascii=False))
        tokens = sum(len(str(m.get("content", ""))) for m in messages)
        return ToolLoopResult(
            content=scripted.content,
            tool_calls=scripted.tool_calls,
            prompt_tokens=tokens, completion_tokens=64,
            model="mock",
        )


def get_provider() -> LLMProvider:
    """按配置返回 Provider；disabled 时抛 ProviderDisabledError。"""
    name = settings.ai_provider.lower()
    if name == "deepseek":
        return DeepSeekProvider()
    if name == "mock":
        return MockProvider()
    if name == "disabled" or name == "":
        raise ProviderDisabledError("AI Provider 未配置（PW_AI_PROVIDER）")
    raise ProviderError(f"未知 AI Provider：{name}")
