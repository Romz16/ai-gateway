async def test_generate_cache_and_idempotency(client, runtime, payload):
    payload["cache"] = True
    first = await client.post("/v1/generate", json=payload)
    assert first.status_code == 200
    assert first.json()["content"] == "positive"
    second = await client.post("/v1/generate", json=payload)
    assert second.json()["cache_hit"] is True
    assert second.json()["estimated_cost_usd"] == "0"
    assert runtime.providers["fake"].calls == 1
    third = await client.post(
        "/v1/generate", json=payload, headers={"Idempotency-Key": "operation-1"}
    )
    replay = await client.post(
        "/v1/generate", json=payload, headers={"Idempotency-Key": "operation-1"}
    )
    assert replay.json() == third.json()
    payload["messages"][0]["content"] = "Different content"
    conflict = await client.post(
        "/v1/generate", json=payload, headers={"Idempotency-Key": "operation-1"}
    )
    assert conflict.status_code == 409


async def test_operations(client, payload):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).status_code == 200
    assert (await client.get("/missing")).status_code == 404
    assert (await client.get("/v1/providers/status")).json()["fake"]["circuit_breaker"] == "closed"
    response = await client.post("/v1/generate", json=payload)
    assert response.headers["x-request-id"] == response.json()["request_id"]
    metrics = (await client.get("/metrics")).text
    assert "gateway_estimated_cost_usd_total" in metrics
    assert "test-alpha" not in metrics
    assert (await client.get("/v1/usage?provider=fake&model=demo-small")).json()["attempts"] == 1


async def test_structured_output(client, payload):
    payload["response_schema"] = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["general"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["category", "confidence"],
        "additionalProperties": False,
    }
    response = await client.post("/v1/generate/structured", json=payload)
    assert response.status_code == 200
    assert response.json()["content"] == {"category": "general", "confidence": 0}
