"""可替换的 LLM Provider Adapter（设计 §11.2/§11.4）。

- DeepSeekProvider：真实实现（OpenAI 兼容 chat/completions），记录 Token 用量；
- MockProvider：确定性桩，**仅用于测试**（AGENTS 规则：Mock 与真实实现分离）；
- disabled：未配置时明确降级（raise ProviderDisabledError），绝不伪造回复。
"""

import json
from dataclasses import dataclass

import httpx

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

    def chat(self, system: str, user: str) -> LLMResult:
        raise NotImplementedError


class DeepSeekProvider(LLMProvider):
    """DeepSeek（OpenAI 兼容 API）。系统提示与用户内容分开发送。

    transport 参数仅供测试注入 httpx.MockTransport，生产为 None（默认 httpx）。
    """

    name = "deepseek"

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
        data = response.json()
        try:
            message = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"DeepSeek 响应格式异常：{json.dumps(data)[:200]}") from exc
        return LLMResult(
            content=message,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=data.get("model", self.model),
        )


class MockProvider(LLMProvider):
    """测试专用确定性桩：返回预设 JSON（在测试中按需覆写 default_response）。"""

    name = "mock"

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

    def chat(self, system: str, user: str) -> LLMResult:
        self.calls.append({"system": system, "user": user})
        return LLMResult(
            content=json.dumps(self.default_response, ensure_ascii=False),
            prompt_tokens=len(system) + len(user),
            completion_tokens=64,
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
