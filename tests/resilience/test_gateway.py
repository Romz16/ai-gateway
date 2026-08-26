import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from app.core.errors import GatewayError
from app.domain.models import GenerationRequest


async def test_retry_then_success(client, runtime, payload):
    runtime.providers["fake"].failures = ["PROVIDER_RATE_LIMITED", "PROVIDER_UNAVAILABLE"]
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 200
    assert result.json()["attempts"] == 3
    assert runtime.providers["fake"].calls == 3
    assert (await client.get("/v1/usage")).json()["attempts"] == 3


async def test_circuit_opens_and_falls_back(client, runtime, payload):
    runtime.providers["fake"].failure_rate = 1
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 200
    assert result.json()["fallback_used"] is True
    assert result.json()["provider"] == "fake_backup"
    assert await runtime.controls.circuit_status("fake") == "open"
    assert runtime.providers["fake"].calls == 3
    assert (await client.post("/v1/generate", json=payload)).status_code == 200
    assert runtime.providers["fake"].calls == 3


async def test_permanent_error_never_retried(client, runtime, payload):
    runtime.providers["fake"].failures = ["PERMANENT"]
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 200
    assert runtime.providers["fake"].calls == 1


async def test_all_providers_fail_bounded(client, runtime, payload):
    for provider in runtime.providers.values():
        provider.failure_rate = 1
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 503
    assert sum(p.calls for p in runtime.providers.values()) == 6


async def test_provider_timeout_falls_back(client, runtime, payload):
    runtime.providers["fake"].timeout_rate = 1
    runtime.service.executor.settings.max_retries = 0
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 200
    assert result.json()["fallback_used"] is True


async def test_deadline_cancels_without_fallback(client, runtime, payload):
    runtime.providers["fake"].timeout_rate = 1
    payload["constraints"] = {"max_latency_ms": 100}
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 504
    assert runtime.providers["fake_backup"].calls == 0


async def test_invalid_structured_output_never_returned(client, runtime, payload):
    for provider in runtime.providers.values():
        provider.invalid_rate = 1
    payload["response_schema"] = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    result = await client.post("/v1/generate/structured", json=payload)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "INVALID_MODEL_RESPONSE"


async def test_request_budget_counts_failed_attempts(client, runtime, payload):
    runtime.providers["fake"].failure_rate = 1
    request = GenerationRequest.model_validate(payload)
    identity = await runtime.repository.authenticate("test-alpha")
    model = runtime.service.router.candidates(request, identity)[0]
    from app.services.routing import input_bound

    maximum = model.cost(input_bound(request), 512)
    payload["constraints"] = {"max_cost_usd": str(maximum)}
    result = await client.post("/v1/generate", json=payload)
    assert result.status_code == 402
    assert runtime.providers["fake"].calls == 1


async def test_distributed_concurrency_and_retry_budget(runtime):
    identity = replace(await runtime.repository.authenticate("test-alpha"), concurrency=1)
    token = await runtime.controls.lease(identity, 1000, 100)
    with pytest.raises(GatewayError):
        await runtime.controls.lease(identity, 1000, 100)
    await runtime.controls.release(identity, token)
    assert await runtime.controls.lease(identity, 1000, 100)
    assert await runtime.controls.retry_allowed(1)
    assert not await runtime.controls.retry_allowed(1)


async def test_single_half_open_probe_and_recovery(runtime):
    controls = runtime.controls
    token = await controls.circuit_acquire("fake", 1)
    assert await controls.circuit_finish("fake", token, False, 1, 1)
    assert not await controls.circuit_acquire("fake", 1)
    await controls.redis.hset(controls.key("circuit:fake"), "until", 0)
    probe = await controls.circuit_acquire("fake", 1)
    assert probe != "closed"
    assert not await controls.circuit_acquire("fake", 1)
    await controls.circuit_finish("fake", "stale-probe", True, 1, 1)
    assert await controls.circuit_status("fake") == "half_open"
    await controls.circuit_finish("fake", probe, True, 1, 1)
    assert await controls.circuit_status("fake") == "closed"


async def test_idempotency_concurrent_claim(runtime, payload):
    identity = await runtime.repository.authenticate("test-alpha")
    results = await asyncio.gather(
        *[runtime.controls.claim(identity, "same", "fingerprint", 120) for _ in range(10)],
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert sum(isinstance(r, GatewayError) for r in results) == 9


async def test_pending_reservation_survives_unknown_failure(client, runtime, payload):
    runtime.providers["fake"].failure_rate = 1
    runtime.service.executor.settings.max_retries = 0
    await client.post("/v1/generate", json=payload)
    usage = (await client.get("/v1/usage")).json()
    assert any(
        row["state"] == "reserved" and Decimal(row["cost_usd"]) > 0
        for row in usage["recent_attempts"]
    )
