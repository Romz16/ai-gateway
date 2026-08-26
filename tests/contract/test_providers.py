import httpx
import pytest

from app.core.errors import ProviderError
from app.domain.models import GenerationRequest, ModelSpec
from app.providers.http import (
    AnthropicProvider,
    FakeHTTPProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
)

ADAPTERS = [
    (
        OpenAIProvider,
        {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        },
        "/chat/completions",
    ),
    (
        AnthropicProvider,
        {
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
        "/messages",
    ),
    (
        GeminiProvider,
        {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        },
        "/models/test:generateContent",
    ),
    (
        OllamaProvider,
        {
            "message": {"content": "ok"},
            "prompt_eval_count": 10,
            "eval_count": 2,
            "done_reason": "stop",
        },
        "/api/chat",
    ),
    (
        FakeHTTPProvider,
        {"content": "ok", "usage": {"input_tokens": 10, "output_tokens": 2}},
        "/generate",
    ),
]


@pytest.fixture
def model():
    return ModelSpec(
        provider="test",
        model="test",
        input_per_million=1,
        output_per_million=2,
        quality=2,
        expected_latency_ms=10,
        tasks=[],
        effective_from="2026-08-26",
        pricing_note="Test",
    )


@pytest.mark.parametrize("adapter,data,path", ADAPTERS)
async def test_shared_response_contract(adapter, data, path, model, payload):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = adapter(client, "https://provider.example", "secret")
        request = GenerationRequest.model_validate(payload)
        request.response_schema = {"type": "object"}
        result = await provider.generate(request, model)
    assert result.content == "ok"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 2
    assert seen[0].url.path == path
    assert "secret" not in str(seen[0].url)


@pytest.mark.parametrize("adapter,data,path", ADAPTERS)
@pytest.mark.parametrize(
    "status,transient",
    [
        (400, False),
        (401, False),
        (403, False),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
    ],
)
async def test_normalized_errors(adapter, data, path, status, transient, model, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="SECRET"))
    ) as client:
        with pytest.raises(ProviderError) as captured:
            await adapter(client, "https://provider.example").generate(
                GenerationRequest.model_validate(payload), model
            )
    assert captured.value.transient is transient
    assert "SECRET" not in str(captured.value)


@pytest.mark.parametrize("adapter,data,path", ADAPTERS)
@pytest.mark.parametrize("failure", ["timeout", "network", "malformed", "oversized"])
async def test_transport_and_invalid_responses(adapter, data, path, failure, model, payload):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private URL", request=request)
        if failure == "network":
            raise httpx.ConnectError("private URL", request=request)
        return httpx.Response(200, content=b"x" * (600000 if failure == "oversized" else 10))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError):
            await adapter(client, "https://provider.example").generate(
                GenerationRequest.model_validate(payload), model
            )
