import json
from pathlib import Path

from app.core.errors import GatewayError
from app.domain.models import GenerationRequest, Identity, ModelSpec
from app.services.security import digest


def input_bound(request: GenerationRequest) -> int:
    """Conservative UTF-8 byte estimate plus message/schema envelope allowance."""
    schema = json.dumps(request.response_schema) if request.response_schema else ""
    return sum(len(m.content.encode()) + 32 for m in request.messages) + len(schema.encode()) + 256


class Router:
    def __init__(self, models: list[ModelSpec]) -> None:
        self.models = models
        self.version = digest(
            json.dumps([m.model_dump(mode="json") for m in models], sort_keys=True)
        )

    @classmethod
    def from_file(cls, path: Path, enabled: set[str]) -> "Router":
        data = json.loads(path.read_text(encoding="utf-8"))
        models = [ModelSpec.model_validate(m) for m in data["models"]]
        return cls([m for m in models if m.provider in enabled])

    def candidates(self, request: GenerationRequest, identity: Identity) -> list[ModelSpec]:
        c = request.constraints
        minimum = {"economy": 1, "balanced": 2, "quality": 3}[c.quality]
        if request.task in {"reasoning", "code_analysis"}:
            minimum = max(minimum, 3)
        allowed = set(identity.allowed_providers)
        if c.allowed_providers is not None:
            allowed &= set(c.allowed_providers)
        bound = input_bound(request)
        candidates = [
            m
            for m in self.models
            if m.provider in allowed
            and m.quality >= minimum
            and request.task in m.tasks
            and m.expected_latency_ms <= c.max_latency_ms
            and bound + c.max_output_tokens <= m.context_tokens
            and m.cost(bound, c.max_output_tokens) <= min(c.max_cost_usd, identity.request_budget)
        ]
        candidates.sort(
            key=lambda m: (
                m.provider != c.preferred_provider,
                m.cost(bound, c.max_output_tokens),
                m.expected_latency_ms,
            )
        )
        if not candidates:
            raise GatewayError(
                "NO_ELIGIBLE_MODEL", "No model meets the request and tenant policy.", 422
            )
        return candidates
