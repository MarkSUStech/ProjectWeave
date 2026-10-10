"""AI Provider 测试：DeepSeek 请求构造/解析/错误分类 + disabled 降级。"""

import json

import httpx
import pytest

from app.ai.provider import (
    DeepSeekProvider,
    MockProvider,
    ProviderDisabledError,
    ProviderError,
    get_provider,
)


def make_provider(handler) -> DeepSeekProvider:
    return DeepSeekProvider(
        api_key="sk-test",
        base_url="https://api.test",
        model="m1",
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_request_and_parse():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert str(request.url) == "https://api.test/chat/completions"
        assert request.headers["Authorization"] == "Bearer sk-test"
        assert body["model"] == "m1"
        assert body["messages"][0] == {"role": "system", "content": "SYS"}
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"intent":"hint"}'}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45},
            "model": "m1",
        })

    result = make_provider(handler).chat("SYS", "USR")
    assert result.content == '{"intent":"hint"}'
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 45
    assert result.model == "m1"


def test_deepseek_auth_error():
    provider = make_provider(lambda req: httpx.Response(401, text="bad key"))
    with pytest.raises(ProviderError, match="认证失败"):
        provider.chat("s", "u")


def test_deepseek_rate_limit():
    provider = make_provider(lambda req: httpx.Response(429, text="slow"))
    with pytest.raises(ProviderError, match="限流"):
        provider.chat("s", "u")


def test_deepseek_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    provider = make_provider(handler)
    with pytest.raises(ProviderError, match="网络错误"):
        provider.chat("s", "u")


def test_missing_key_raises_disabled():
    with pytest.raises(ProviderDisabledError):
        DeepSeekProvider(api_key="", transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_get_provider_disabled_by_default(monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ai_provider", "disabled")
    with pytest.raises(ProviderDisabledError):
        get_provider()


def test_get_provider_unknown_name(monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ai_provider", "gpt-99")
    with pytest.raises(ProviderError, match="未知 AI Provider"):
        get_provider()


def test_mock_provider_records_calls():
    provider = MockProvider()
    result = provider.chat("s", "u")
    assert json.loads(result.content)["intent"] == "hint"
    assert provider.calls == [{"system": "s", "user": "u"}]
