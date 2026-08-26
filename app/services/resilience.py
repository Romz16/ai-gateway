import asyncio
import random
import time
from decimal import Decimal

from app.core.config import Settings
from app.core.errors import GatewayError, ProviderError
from app.domain.models import GenerationRequest, GenerationResult, Identity, LLMProvider, ModelSpec
from app.infrastructure.controls import Controls
from app.infrastructure.database import Repository
from app.observability.telemetry import Telemetry
from app.services.routing import input_bound
from app.services.security import protect_value
from app.services.validation import parse_output


class Executor:
    def __init__(
        self,
        settings: Settings,
        providers: dict[str, LLMProvider],
        controls: Controls,
        repository: Repository,
        telemetry: Telemetry,
    ) -> None:
        self.settings, self.providers, self.controls = settings, providers, controls
        self.repository, self.telemetry = repository, telemetry

    async def run(
        self,
        request: GenerationRequest,
        identity: Identity,
        candidates: list[ModelSpec],
        request_id: str,
        trace_id: str,
        deadline: float,
    ) -> GenerationResult:
        started, spent, attempts = time.monotonic(), Decimal(0), 0
        last_error = "PROVIDER_UNAVAILABLE"
        attempted_providers: set[str] = set()
        for model in candidates:
            if model.provider in attempted_providers:
                continue
            attempted_providers.add(model.provider)
            for retry in range(self.settings.max_retries + 1):
                remaining = deadline - time.monotonic()
                if remaining < model.expected_latency_ms / 1000:
                    last_error = "PROVIDER_TIMEOUT"
                    break
                estimate = model.cost(input_bound(request), request.constraints.max_output_tokens)
                if spent + estimate > min(
                    request.constraints.max_cost_usd, identity.request_budget
                ):
                    last_error = "BUDGET_EXCEEDED"
                    break
                token = await self.controls.circuit_acquire(model.provider, 65)
                if not token:
                    break
                if retry:
                    if not await self.controls.retry_allowed(self.settings.retry_budget_per_minute):
                        break
                    self.telemetry.retries.labels(provider=model.provider).inc()
                attempt_id = await self.repository.reserve(
                    identity,
                    request_id,
                    trace_id,
                    model.provider,
                    model.model,
                    request.task,
                    estimate,
                    input_bound(request),
                    request.constraints.max_output_tokens,
                )
                attempts += 1
                spent += estimate
                if len(attempted_providers) > 1 and retry == 0:
                    self.telemetry.fallbacks.inc()
                    await self.repository.audit(
                        "provider_fallback", request_id, trace_id, identity.tenant_id
                    )
                tick = time.monotonic()
                actual = estimate
                inputs, outputs = input_bound(request), request.constraints.max_output_tokens
                try:
                    with self.telemetry.tracer.start_as_current_span(
                        "provider.generate", record_exception=False, set_status_on_exception=False
                    ) as span:
                        span.set_attribute("gen_ai.provider.name", model.provider)
                        span.set_attribute("gen_ai.request.model", model.model)
                        span.set_attribute("gateway.attempt", attempts)
                        async with asyncio.timeout(
                            min(
                                self.settings.provider_timeout_seconds,
                                max(0.001, deadline - time.monotonic()),
                            )
                        ):
                            response = await self.providers[model.provider].generate(request, model)
                        inputs, outputs = response.usage.input_tokens, response.usage.output_tokens
                        actual = model.cost(inputs, outputs)
                        await self.repository.settle(attempt_id, actual, inputs, outputs)
                        spent += actual - estimate
                        span.set_attribute("gen_ai.usage.input_tokens", inputs)
                        span.set_attribute("gen_ai.usage.output_tokens", outputs)
                    if response.finish_reason not in {"stop", "end_turn", "STOP"}:
                        raise ProviderError("INVALID_MODEL_RESPONSE")
                    if spent > min(request.constraints.max_cost_usd, identity.request_budget):
                        raise GatewayError(
                            "BUDGET_EXCEEDED", "Reported usage exceeded the reserved estimate.", 402
                        )
                    content = parse_output(
                        response.content,
                        request.response_schema,
                        request.constraints.response_format == "json",
                    )
                    content = protect_value(content, identity.pii_policy)
                    # Masking must never turn a valid structured result into an invalid one.
                    if request.response_schema is not None:
                        import json

                        parse_output(json.dumps(content), request.response_schema, True)
                    await self.controls.circuit_finish(
                        model.provider,
                        token,
                        True,
                        self.settings.circuit_threshold,
                        self.settings.circuit_recovery_seconds,
                    )
                    self.telemetry.provider_calls.labels(
                        provider=model.provider, outcome="success"
                    ).inc()
                    return GenerationResult(
                        request_id=request_id,
                        trace_id=trace_id,
                        content=content,
                        provider=model.provider,
                        model=model.model,
                        usage=response.usage,
                        estimated_cost_usd=spent,
                        latency_ms=(time.monotonic() - started) * 1000,
                        fallback_used=len(attempted_providers) > 1,
                        routing_reason="lowest_cost_eligible_model_with_preference",
                        attempts=attempts,
                    )
                except (ProviderError, TimeoutError) as error:
                    fault = (
                        error
                        if isinstance(error, ProviderError)
                        else ProviderError("PROVIDER_TIMEOUT", True)
                    )
                    last_error = fault.code
                    opened = await self.controls.circuit_finish(
                        model.provider,
                        token,
                        False,
                        self.settings.circuit_threshold,
                        self.settings.circuit_recovery_seconds,
                    )
                    if opened:
                        self.telemetry.circuits.labels(provider=model.provider).inc()
                        await self.repository.audit(
                            "provider_circuit_opened", request_id, trace_id, identity.tenant_id
                        )
                    self.telemetry.provider_calls.labels(
                        provider=model.provider, outcome=fault.code
                    ).inc()
                    self.telemetry.event(
                        "provider_failure",
                        request_id=request_id,
                        trace_id=trace_id,
                        provider=model.provider,
                        code=fault.code,
                    )
                    if not fault.transient or retry == self.settings.max_retries or opened:
                        break
                    delay = max(
                        fault.retry_after,
                        random.uniform(0, self.settings.retry_base_seconds * 2**retry),  # nosec B311 - retry jitter only
                    )  # noqa: S311
                    if time.monotonic() + delay + model.expected_latency_ms / 1000 >= deadline:
                        break
                    await asyncio.sleep(delay)
                finally:
                    self.telemetry.provider_duration.labels(provider=model.provider).observe(
                        time.monotonic() - tick
                    )
                    self.telemetry.cost.labels(
                        provider=model.provider, model=model.model, task=request.task
                    ).inc(float(actual))
                    self.telemetry.tokens.labels(provider=model.provider, direction="input").inc(
                        inputs
                    )
                    self.telemetry.tokens.labels(provider=model.provider, direction="output").inc(
                        outputs
                    )
        if last_error == "BUDGET_EXCEEDED":
            raise GatewayError(
                last_error, "The remaining request budget cannot fund another attempt.", 402
            )
        if last_error == "PROVIDER_TIMEOUT":
            raise GatewayError(
                last_error, "No eligible provider completed within the deadline.", 504
            )
        if last_error == "INVALID_MODEL_RESPONSE":
            raise GatewayError(last_error, "No provider produced a valid response.", 502)
        raise GatewayError(
            "PROVIDER_UNAVAILABLE", "No eligible provider is currently available.", 503
        )
