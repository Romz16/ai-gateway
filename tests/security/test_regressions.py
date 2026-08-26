from app.infrastructure.database import ApiKey


async def test_cache_is_not_shared_between_tenants(client, runtime, payload):
    payload["cache"] = True
    assert (await client.post("/v1/generate", json=payload)).status_code == 200
    other = await client.post(
        "/v1/generate", json=payload, headers={"Authorization": "Bearer test-beta"}
    )
    assert other.status_code == 200
    assert other.json()["cache_hit"] is False
    assert runtime.providers["fake"].calls == 2


async def test_idempotency_does_not_merge_redacted_inputs(client, payload):
    payload["task"] = "summarization"
    payload["messages"][0]["content"] = "Contact first@example.com."
    first = await client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "pii-key"})
    assert first.status_code == 200
    payload["messages"][0]["content"] = "Contact second@example.com."
    assert (
        await client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "pii-key"})
    ).status_code == 409


async def test_revocation_blocks_idempotent_replay(client, runtime, payload):
    assert (
        await client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "revocation"})
    ).status_code == 200
    async with runtime.repository.sessions.begin() as session:
        key = await session.get(ApiKey, "alpha")
        key.revoked = True
    assert (
        await client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "revocation"})
    ).status_code == 401


async def test_unexpected_exception_does_not_escape(client, runtime, payload, monkeypatch, caplog):
    async def fail(*args, **kwargs):
        raise RuntimeError("private-secret-in-error")

    monkeypatch.setattr(runtime.service, "generate", fail)
    response = await client.post("/v1/generate", json=payload)
    assert response.status_code == 500
    assert "private-secret" not in response.text
    assert "private-secret" not in caplog.text
