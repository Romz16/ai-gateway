from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.infrastructure.controls import Controls
from app.infrastructure.database import ApiKey, Application, Base, Repository, Tenant
from app.main import Runtime, create_app
from app.observability.telemetry import Telemetry
from app.providers.fake import FakeProvider
from app.services.generation import GenerationService
from app.services.resilience import Executor
from app.services.routing import Router
from app.services.security import digest


@pytest.fixture
async def runtime(tmp_path):
    settings = Settings(
        app_env="test",
        retry_base_seconds=0.001,
        provider_timeout_seconds=0.1,
        circuit_recovery_seconds=1,
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = Repository(engine)
    async with repository.sessions.begin() as session:
        for name in ("alpha", "beta"):
            session.add(Tenant(id=name, allowed_providers=["fake", "fake_backup"], rpm=10000))
            await session.flush()
            session.add(Application(id=name, tenant_id=name))
            await session.flush()
            session.add(
                ApiKey(
                    id=name,
                    application_id=name,
                    key_hash=digest(f"test-{name}"),
                    scopes=["generation:execute", "usage:read", "providers:read"],
                )
            )
        session.add(
            ApiKey(
                id="expired",
                application_id="alpha",
                key_hash=digest("expired"),
                scopes=["generation:execute"],
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        session.add(
            ApiKey(
                id="revoked",
                application_id="alpha",
                key_hash=digest("revoked"),
                scopes=["generation:execute"],
                revoked=True,
            )
        )
        session.add(
            ApiKey(id="limited", application_id="alpha", key_hash=digest("limited"), scopes=[])
        )
    controls = Controls(FakeRedis(decode_responses=True), namespace=str(uuid4()))
    providers = {"fake": FakeProvider(latency_ms=0), "fake_backup": FakeProvider(latency_ms=0)}
    telemetry = Telemetry()
    router = Router.from_file(settings.catalog_path, set(providers))
    executor = Executor(settings, providers, controls, repository, telemetry)
    service = GenerationService(settings, router, executor, controls, repository, telemetry)
    result = Runtime(repository, controls, service, telemetry, providers)
    yield result
    await controls.redis.aclose()
    await engine.dispose()
    telemetry.traces.shutdown()


@pytest.fixture
async def client(runtime):
    app = create_app(Settings(app_env="test"), runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": "Bearer test-alpha"},
    ) as client:
        yield client


@pytest.fixture
def payload():
    return {"task": "classification", "messages": [{"role": "user", "content": "A great service."}]}
