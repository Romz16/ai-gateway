import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.exceptions import HTTPException

from app.api.middleware import RequestBoundary
from app.core.config import Settings
from app.core.errors import GatewayError
from app.domain.models import GenerationRequest, GenerationResult, Identity, LLMProvider
from app.infrastructure.controls import Controls
from app.infrastructure.database import Repository
from app.observability.telemetry import Telemetry, configure_logging
from app.providers.fake import FakeProvider
from app.providers.http import (
    AnthropicProvider,
    FakeHTTPProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
)
from app.services.generation import GenerationService
from app.services.resilience import Executor
from app.services.routing import Router


@dataclass
class Runtime:
    repository: Repository
    controls: Controls
    service: GenerationService
    telemetry: Telemetry
    providers: dict[str, LLMProvider]


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging()
    telemetry = runtime.telemetry if runtime else Telemetry(settings.otel_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        if runtime:
            yield
            return
        engine = create_async_engine(
            settings.database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True
        )
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.provider_timeout_seconds, connect=1),
            limits=httpx.Limits(max_connections=settings.max_inflight),
            follow_redirects=False,
            trust_env=False,
        )
        providers: dict[str, LLMProvider] = {"ollama": OllamaProvider(client, settings.ollama_url)}
        for name, provider_class, url in [
            ("openai", OpenAIProvider, "https://api.openai.com/v1"),
            ("anthropic", AnthropicProvider, "https://api.anthropic.com/v1"),
            ("gemini", GeminiProvider, "https://generativelanguage.googleapis.com/v1beta"),
        ]:
            key = getattr(settings, f"{name}_api_key").get_secret_value()
            if key:
                providers[name] = provider_class(client, url, key)
        if settings.enable_fake_provider:
            providers.update(
                fake=FakeHTTPProvider(client, settings.fake_provider_url),
                fake_backup=FakeProvider(latency_ms=15),
            )
        repository, controls = Repository(engine), Controls(redis)
        router = Router.from_file(settings.catalog_path, set(providers))
        if not router.models:
            raise RuntimeError("No configured models are available.")
        executor = Executor(settings, providers, controls, repository, telemetry)
        app.state.runtime = Runtime(
            repository,
            controls,
            GenerationService(settings, router, executor, controls, repository, telemetry),
            telemetry,
            providers,
        )
        try:
            await repository.ping()
            await redis.ping()
            yield
        finally:
            await client.aclose()
            await redis.aclose()
            await engine.dispose()
            await asyncio.to_thread(telemetry.traces.shutdown)

    app = FastAPI(
        title="Production AI Gateway",
        version="0.1.0",
        lifespan=lifespan,
        description="Unified generation with tenant policies, bounded retries and cost governance.",
    )
    if runtime:
        app.state.runtime = runtime
    app.add_middleware(RequestBoundary, telemetry=telemetry, max_body_bytes=settings.max_body_bytes)

    def state(request: Request) -> Runtime:
        return request.app.state.runtime  # type: ignore[no-any-return]

    def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
        headers = {"Retry-After": "60"} if status == 429 else None
        if status == 401:
            headers = {"WWW-Authenticate": "Bearer"}
        return JSONResponse(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                    "trace_id": request.state.trace_id,
                }
            },
            status_code=status,
            headers=headers,
        )

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, error: GatewayError) -> JSONResponse:
        identity = getattr(request.state, "identity", None)
        try:
            await state(request).repository.audit(
                error.code.lower(),
                request.state.request_id,
                request.state.trace_id,
                identity.tenant_id if identity else None,
            )
        except SQLAlchemyError:
            telemetry.event("audit_unavailable", request_id=request.state.request_id)
        return error_response(request, error.code, error.message, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            request, "INVALID_REQUEST", "The request does not match the API schema.", 422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(
            request,
            "INVALID_REQUEST",
            "The requested resource or method is unavailable.",
            error.status_code,
        )

    async def dependency_error(request: Request, error: Exception) -> JSONResponse:
        telemetry.event("dependency_unavailable", request_id=request.state.request_id)
        return error_response(
            request, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable.", 503
        )

    app.add_exception_handler(RedisError, dependency_error)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, dependency_error)  # type: ignore[arg-type]

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        telemetry.event(
            "internal_error", request_id=getattr(request.state, "request_id", "unknown")
        )
        return error_response(request, "INTERNAL_ERROR", "The request could not be completed.", 500)

    def authorize(scope: str):  # type: ignore[no-untyped-def]
        async def dependency(
            request: Request, authorization: str | None = Header(None)
        ) -> Identity:
            if (
                not authorization
                or not authorization.startswith("Bearer ")
                or len(authorization) > 520
            ):
                raise GatewayError("AUTHENTICATION_FAILED", "A valid API key is required.", 401)
            with telemetry.tracer.start_as_current_span(
                "authentication", record_exception=False, set_status_on_exception=False
            ):
                try:
                    async with asyncio.timeout(2):
                        identity = await state(request).repository.authenticate(authorization[7:])
                except TimeoutError as exc:
                    raise GatewayError(
                        "DEPENDENCY_UNAVAILABLE", "Authentication is temporarily unavailable.", 503
                    ) from exc
            request.state.identity = identity
            if scope not in identity.scopes:
                raise GatewayError(
                    "AUTHORIZATION_FAILED", "The API key lacks the required scope.", 403
                )
            return identity

        return dependency

    @app.get("/health", tags=["Operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["Operations"])
    async def ready(request: Request) -> dict[str, str]:
        async with asyncio.timeout(3):
            await state(request).repository.ping()
            await state(request).controls.redis.ping()
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(telemetry.registry), media_type=CONTENT_TYPE_LATEST)

    async def execute(
        payload: GenerationRequest,
        request: Request,
        identity: Identity,
        idempotency_key: str | None,
    ) -> GenerationResult:
        if idempotency_key and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
            raise GatewayError("INVALID_REQUEST", "Invalid Idempotency-Key header.", 422)
        return await state(request).service.generate(
            payload,
            identity,
            request.state.request_id,
            request.state.trace_id,
            idempotency_key,
            started_at=request.state.started_at,
        )

    generation_auth = authorize("generation:execute")
    usage_auth = authorize("usage:read")
    providers_auth = authorize("providers:read")

    @app.post("/v1/generate", response_model=GenerationResult, tags=["Generation"])
    async def generate(
        payload: GenerationRequest,
        request: Request,
        identity: Identity = Depends(generation_auth),
        idempotency_key: str | None = Header(None),
    ) -> GenerationResult:
        return await execute(payload, request, identity, idempotency_key)

    @app.post("/v1/generate/structured", response_model=GenerationResult, tags=["Generation"])
    async def structured(
        payload: GenerationRequest,
        request: Request,
        identity: Identity = Depends(generation_auth),
        idempotency_key: str | None = Header(None),
    ) -> GenerationResult:
        if payload.response_schema is None:
            raise GatewayError(
                "INVALID_REQUEST", "Structured generation requires response_schema.", 422
            )
        return await execute(payload, request, identity, idempotency_key)

    @app.get("/v1/usage", tags=["Operations"])
    async def usage(
        request: Request,
        provider: str | None = None,
        model: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant: str | None = None,
        application: str | None = None,
        identity: Identity = Depends(usage_auth),
    ) -> dict[str, Any]:
        if (tenant and tenant != identity.tenant_id) or (
            application and application != identity.application_id
        ):
            raise GatewayError(
                "AUTHORIZATION_FAILED", "Cross-tenant or cross-application access is denied.", 403
            )
        if start_date and end_date and start_date >= end_date:
            raise GatewayError("INVALID_REQUEST", "start_date must be earlier than end_date.", 422)
        return await state(request).repository.usage(
            identity, provider, model, start_date, end_date
        )

    @app.get("/v1/providers/status", tags=["Operations"])
    async def provider_status(
        request: Request, identity: Identity = Depends(providers_auth)
    ) -> dict[str, Any]:
        result = {}
        for provider in state(request).providers:
            if provider not in identity.allowed_providers:
                continue
            circuit = await state(request).controls.circuit_status(provider)
            result[provider] = {
                "status": "available" if circuit == "closed" else "degraded",
                "circuit_breaker": circuit,
                "health_source": "passive circuit state; not an upstream health check",
            }
        return result

    return app
