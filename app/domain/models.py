import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32000)


class Constraints(StrictModel):
    quality: Literal["economy", "balanced", "quality"] = "balanced"
    max_cost_usd: Decimal = Field(Decimal("0.05"), gt=0, le=100)
    max_latency_ms: int = Field(5000, ge=100, le=60000)
    max_output_tokens: int = Field(512, ge=1, le=4096)
    response_format: Literal["text", "json"] = "text"
    preferred_provider: str | None = Field(None, max_length=40)
    allowed_providers: list[str] | None = Field(None, max_length=10)


class GenerationRequest(StrictModel):
    task: Literal["classification", "summarization", "extraction", "reasoning", "code_analysis"]
    messages: list[Message] = Field(min_length=1, max_length=32)
    constraints: Constraints = Field(default_factory=Constraints)
    response_schema: dict[str, Any] | None = None
    cache: bool = False

    @model_validator(mode="after")
    def bounded_input(self) -> "GenerationRequest":
        if sum(len(m.content.encode()) for m in self.messages) > 32000:
            raise ValueError("Message content exceeds the input limit.")
        if not any(m.role == "user" for m in self.messages):
            raise ValueError("At least one user message is required.")
        if self.response_schema is not None and len(json.dumps(self.response_schema)) > 8192:
            raise ValueError("Response schema exceeds the size limit.")
        return self


class ModelSpec(StrictModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    model: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}$")
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    quality: int = Field(ge=1, le=3)
    expected_latency_ms: int = Field(gt=0)
    context_tokens: int = Field(32768, gt=0)
    tasks: list[str]
    effective_from: str
    pricing_note: str

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            input_tokens * self.input_per_million + output_tokens * self.output_per_million
        ) / Decimal(1000000)


class TokenUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ProviderResponse(StrictModel):
    content: str = Field(min_length=1, max_length=262144)
    usage: TokenUsage
    finish_reason: str = "stop"


class GenerationResult(StrictModel):
    request_id: str
    trace_id: str
    content: str | dict[str, Any] | list[Any] | int | float | bool | None
    provider: str
    model: str
    usage: TokenUsage
    estimated_cost_usd: Decimal
    latency_ms: float
    cache_hit: bool = False
    fallback_used: bool = False
    routing_reason: str
    attempts: int
    accounting: str = "estimated"


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    application_id: str
    key_id: str
    scopes: frozenset[str]
    allowed_providers: tuple[str, ...]
    pii_policy: str
    rpm: int
    requests_per_day: int
    concurrency: int
    daily_tokens: int
    daily_budget: Decimal
    monthly_budget: Decimal
    request_budget: Decimal


class LLMProvider(Protocol):
    async def generate(self, request: GenerationRequest, model: ModelSpec) -> ProviderResponse: ...
