import asyncio
import json
import random
from typing import Any

from app.core.errors import ProviderError
from app.domain.models import GenerationRequest, ModelSpec, ProviderResponse, TokenUsage


def fixture(schema: dict[str, Any]) -> Any:
    """Generate a small deterministic fixture, not a real model answer."""
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type", "object")
    if kind == "object":
        return {k: fixture(v) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [fixture(schema.get("items", {})) for _ in range(min(schema.get("minItems", 1), 10))]
    if kind in {"number", "integer"}:
        return schema.get("minimum", 0)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return "example"[: schema.get("maxLength", 7)].ljust(min(schema.get("minLength", 0), 100), "x")


class FakeProvider:
    def __init__(
        self,
        failure_rate: float = 0,
        timeout_rate: float = 0,
        invalid_rate: float = 0,
        latency_ms: float = 5,
        seed: int = 42,
        failures: list[str] | None = None,
    ) -> None:
        self.failure_rate, self.timeout_rate, self.invalid_rate = (
            failure_rate,
            timeout_rate,
            invalid_rate,
        )
        self.latency_ms, self.random = latency_ms, random.Random(seed)  # nosec B311 - deterministic fault injection, not cryptography
        self.failures = list(failures or [])
        self.calls = 0

    async def generate(self, request: GenerationRequest, model: ModelSpec) -> ProviderResponse:
        self.calls += 1
        if self.failures:
            failure = self.failures.pop(0)
            if failure:
                raise ProviderError(failure, failure != "PERMANENT")
        await asyncio.sleep(self.latency_ms / 1000)
        if self.random.random() < self.timeout_rate:
            await asyncio.sleep(60)
        if self.random.random() < self.failure_rate:
            raise ProviderError("PROVIDER_UNAVAILABLE", True)
        text = next(m.content for m in reversed(request.messages) if m.role == "user")
        if request.response_schema is not None:
            content = json.dumps(fixture(request.response_schema))
        elif request.task == "classification":
            content = (
                "positive"
                if any(w in text.lower() for w in ("good", "great", "excellent"))
                else "neutral"
            )
        elif request.task == "reasoning":
            content = "42" if "6 * 7" in text else "Demonstration reasoning result."
        elif request.task == "extraction":
            content = json.dumps({"text": text[:80]})
        else:
            content = " ".join(text.split()[:20])
        if request.constraints.response_format == "json" and request.response_schema is None:
            content = json.dumps({"result": content})
        if self.random.random() < self.invalid_rate:
            content = "{invalid-json"
        # The fake provider honors output limits, including a visible truncation reason.
        budget = request.constraints.max_output_tokens * 4
        finish = "length" if len(content) > budget else "stop"
        content = content[:budget]
        return ProviderResponse(
            content=content,
            finish_reason=finish,
            usage=TokenUsage(
                input_tokens=max(1, len(text.encode()) // 4),
                output_tokens=max(1, len(content.encode()) // 4),
            ),
        )
