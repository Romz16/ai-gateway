import asyncio
import time
from decimal import Decimal

from app.core.config import Settings
from app.core.errors import GatewayError
from app.domain.models import GenerationRequest, GenerationResult, Identity, TokenUsage
from app.infrastructure.controls import Controls
from app.infrastructure.database import Repository
from app.observability.telemetry import Telemetry
from app.services.resilience import Executor
from app.services.routing import Router
from app.services.security import fingerprint, secure_request
from app.services.validation import validate_schema


class GenerationService:
    def __init__(
        self,
        settings: Settings,
        router: Router,
        executor: Executor,
        controls: Controls,
        repository: Repository,
        telemetry: Telemetry,
    ) -> None:
        self.settings, self.router, self.executor = settings, router, executor
        self.controls, self.repository, self.telemetry = controls, repository, telemetry

    async def generate(
        self,
        request: GenerationRequest,
        identity: Identity,
        request_id: str,
        trace_id: str,
        idempotency_key: str | None = None,
        started_at: float | None = None,
    ) -> GenerationResult:
        started = started_at if started_at is not None else time.monotonic()
        duration = min(request.constraints.max_latency_ms, self.settings.max_deadline_ms) / 1000
        lease: str | None = None
        try:
            async with asyncio.timeout(max(0, started + duration - time.monotonic())):
                with self.telemetry.tracer.start_as_current_span(
                    "rate_limit", record_exception=False, set_status_on_exception=False
                ):
                    await self.controls.rate_limit(identity)
                with self.telemetry.tracer.start_as_current_span(
                    "security", record_exception=False, set_status_on_exception=False
                ):
                    if request.response_schema is not None:
                        validate_schema(request.response_schema)
                    safe = secure_request(request, identity, self.settings.enable_prompt_security)
                    if safe.messages != request.messages:
                        await self.repository.audit(
                            "pii_detected", request_id, trace_id, identity.tenant_id
                        )
                # Identity and catalog revision isolate responses after permission/pricing changes.
                key = fingerprint(request, identity, self.router.version)
                storage_key = None
                if idempotency_key:
                    storage_key, prior = await self.controls.claim(
                        identity, idempotency_key, key, self.settings.idempotency_ttl_seconds
                    )
                    if prior:
                        return GenerationResult.model_validate(prior)
                with self.telemetry.tracer.start_as_current_span(
                    "routing", record_exception=False, set_status_on_exception=False
                ):
                    candidates = self.router.candidates(safe, identity)
                cached = await self.controls.cached(key) if safe.cache else None
                if cached:
                    result = GenerationResult.model_validate(cached).model_copy(
                        update={
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "cache_hit": True,
                            "estimated_cost_usd": Decimal(0),
                            "attempts": 0,
                            "fallback_used": False,
                            "usage": TokenUsage(input_tokens=0, output_tokens=0),
                        }
                    )
                    self.telemetry.cache.labels(outcome="hit").inc()
                else:
                    if safe.cache:
                        self.telemetry.cache.labels(outcome="miss").inc()
                    lease = await self.controls.lease(identity, 90000, self.settings.max_inflight)
                    result = await self.executor.run(
                        safe, identity, candidates, request_id, trace_id, started + duration
                    )
                    if safe.cache:
                        await self.controls.cache(
                            key, result.model_dump(mode="json"), self.settings.cache_ttl_seconds
                        )
                result.latency_ms = (time.monotonic() - started) * 1000
                if storage_key:
                    await self.controls.complete(
                        storage_key,
                        key,
                        result.model_dump(mode="json"),
                        self.settings.idempotency_ttl_seconds,
                    )
                await self.repository.audit(
                    "generation_completed", request_id, trace_id, identity.tenant_id
                )
                return result
        except TimeoutError as exc:
            raise GatewayError(
                "PROVIDER_TIMEOUT", "The request deadline was reached.", 504
            ) from exc
        finally:
            if lease:
                # Leases also expire after crashes. Cleanup is bounded by Redis socket timeouts.
                await self.controls.release(identity, lease)
