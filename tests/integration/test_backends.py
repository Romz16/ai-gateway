"""Run against dedicated, disposable PostgreSQL and Redis databases."""

import asyncio
import os
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.errors import GatewayError
from app.infrastructure.controls import Controls
from app.infrastructure.database import ApiKey, Application, Repository, Tenant
from app.services.security import digest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL") or not os.getenv("TEST_REDIS_URL"),
        reason="Set TEST_DATABASE_URL and TEST_REDIS_URL for real backend tests.",
    ),
]


@pytest.fixture
async def backends():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    repository = Repository(engine)
    name = "integration-" + str(uuid4())
    async with repository.sessions.begin() as session:
        session.add(
            Tenant(id=name, allowed_providers=["fake"], daily_budget=Decimal("0.01"), rpm=5)
        )
        await session.flush()
        session.add(Application(id=name, tenant_id=name))
        await session.flush()
        session.add(
            ApiKey(
                id=str(uuid4()),
                application_id=name,
                key_hash=digest(name),
                scopes=["generation:execute"],
            )
        )
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    controls = Controls(redis, namespace=name)
    identity = await repository.authenticate(name)
    yield repository, controls, identity
    await redis.aclose()
    await engine.dispose()


async def test_atomic_budget_under_race(backends):
    repository, _, identity = backends
    results = await asyncio.gather(
        *[
            repository.reserve(
                identity,
                str(uuid4()),
                "0" * 32,
                "fake",
                "test",
                "classification",
                Decimal("0.006"),
                1,
                1,
            )
            for _ in range(20)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, str) for r in results) == 1
    assert sum(isinstance(r, GatewayError) for r in results) == 19


async def test_rate_limit_shared_between_instances(backends):
    _, controls, identity = backends
    other = Controls(controls.redis, controls.namespace)
    results = await asyncio.gather(
        *[(controls if i % 2 else other).rate_limit(identity) for i in range(20)],
        return_exceptions=True,
    )
    assert sum(r is None for r in results) == 5
    assert sum(isinstance(r, GatewayError) for r in results) == 15


async def test_concurrency_and_circuit_shared_between_instances(backends):
    _, controls, identity = backends
    other = Controls(controls.redis, controls.namespace)
    identity = replace(identity, concurrency=1)
    token = await controls.lease(identity, 10000, 100)
    with pytest.raises(GatewayError):
        await other.lease(identity, 10000, 100)
    await other.release(identity, token)
    assert await controls.lease(identity, 10000, 100)
    circuit = await controls.circuit_acquire("fake", 1)
    await controls.circuit_finish("fake", circuit, False, 1, 30)
    assert not await other.circuit_acquire("fake", 1)
