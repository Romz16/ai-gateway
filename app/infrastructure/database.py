from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.errors import GatewayError
from app.domain.models import Identity
from app.services.security import digest


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    allowed_providers: Mapped[list[str]] = mapped_column(JSON)
    pii_policy: Mapped[str] = mapped_column(String(8), default="mask")
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("10"))
    monthly_budget: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("100"))
    request_budget: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("0.05"))
    rpm: Mapped[int] = mapped_column(Integer, default=60)
    requests_per_day: Mapped[int] = mapped_column(Integer, default=10000)
    concurrency: Mapped[int] = mapped_column(Integer, default=10)
    daily_tokens: Mapped[int] = mapped_column(Integer, default=1000000)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecord(Base):
    """A durable attempt reservation; unresolved attempts remain conservatively charged."""

    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    trace_id: Mapped[str] = mapped_column(String(32))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    task: Mapped[str] = mapped_column(String(30))
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(String(80), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    trace_id: Mapped[str] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def ping(self) -> None:
        async with self.sessions() as session:
            await session.execute(select(Tenant.id).limit(1))

    async def authenticate(self, raw: str) -> Identity:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(ApiKey, Application, Tenant)
                    .join(Application, ApiKey.application_id == Application.id)
                    .join(Tenant, Application.tenant_id == Tenant.id)
                    .where(ApiKey.key_hash == digest(raw))
                )
            ).first()
            if row is None:
                raise GatewayError("AUTHENTICATION_FAILED", "A valid API key is required.", 401)
            key, application, tenant = row
            expiry = key.expires_at
            if key.revoked or (expiry and expiry.replace(tzinfo=UTC) <= now()):
                raise GatewayError("AUTHENTICATION_FAILED", "A valid API key is required.", 401)
            return Identity(
                tenant.id,
                application.id,
                key.id,
                frozenset(key.scopes),
                tuple(tenant.allowed_providers),
                tenant.pii_policy,
                tenant.rpm,
                tenant.requests_per_day,
                tenant.concurrency,
                tenant.daily_tokens,
                tenant.daily_budget,
                tenant.monthly_budget,
                tenant.request_budget,
            )

    async def reserve(
        self,
        identity: Identity,
        request_id: str,
        trace_id: str,
        provider: str,
        model: str,
        task: str,
        cost: Decimal,
        input_tokens: int,
        output_tokens: int,
    ) -> str:
        async with self.sessions.begin() as session:
            # The tenant row serializes admission across all gateway replicas.
            tenant = (
                await session.execute(
                    select(Tenant).where(Tenant.id == identity.tenant_id).with_for_update()
                )
            ).scalar_one()
            current = now()
            day = current.replace(hour=0, minute=0, second=0, microsecond=0)
            month = day.replace(day=1)
            base = select(
                func.coalesce(func.sum(UsageRecord.cost), 0),
                func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0),
            ).where(UsageRecord.tenant_id == identity.tenant_id)
            daily_cost, daily_tokens = (
                await session.execute(base.where(UsageRecord.created_at >= day))
            ).one()
            monthly_cost, _ = (
                await session.execute(base.where(UsageRecord.created_at >= month))
            ).one()
            if (
                daily_cost + cost > tenant.daily_budget
                or monthly_cost + cost > tenant.monthly_budget
                or daily_tokens + input_tokens + output_tokens > tenant.daily_tokens
            ):
                raise GatewayError(
                    "BUDGET_EXCEEDED", "The tenant budget or token limit is exhausted.", 402
                )
            attempt_id = str(uuid4())
            session.add(
                UsageRecord(
                    id=attempt_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    tenant_id=identity.tenant_id,
                    application_id=identity.application_id,
                    provider=provider,
                    model=model,
                    task=task,
                    cost=cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )
            return attempt_id

    async def settle(
        self,
        attempt_id: str,
        cost: Decimal,
        input_tokens: int,
        output_tokens: int,
        state: str = "estimated",
    ) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(UsageRecord, attempt_id)
            if record is None:
                raise RuntimeError("Attempt reservation is missing.")
            # Usage can exceed the estimate if upstream accounting changes. Record it honestly.
            record.cost, record.input_tokens = cost, input_tokens
            record.output_tokens, record.state = output_tokens, state

    async def audit(
        self, event: str, request_id: str, trace_id: str, tenant_id: str | None = None
    ) -> None:
        async with self.sessions.begin() as session:
            session.add(
                AuditEvent(
                    event=event, request_id=request_id, trace_id=trace_id, tenant_id=tenant_id
                )
            )

    async def usage(
        self,
        identity: Identity,
        provider: str | None = None,
        model: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        query = select(UsageRecord).where(
            UsageRecord.tenant_id == identity.tenant_id,
            UsageRecord.application_id == identity.application_id,
        )
        if provider:
            query = query.where(UsageRecord.provider == provider)
        if model:
            query = query.where(UsageRecord.model == model)
        if start:
            query = query.where(UsageRecord.created_at >= start)
        if end:
            query = query.where(UsageRecord.created_at < end)
        async with self.sessions() as session:
            aggregate = query.with_only_columns(
                func.count(),
                func.coalesce(func.sum(UsageRecord.cost), 0),
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            )
            count, cost, inputs, outputs = (await session.execute(aggregate)).one()
            rows = (
                await session.scalars(query.order_by(UsageRecord.created_at.desc()).limit(100))
            ).all()
            return {
                "tenant_id": identity.tenant_id,
                "application_id": identity.application_id,
                "attempts": count,
                "estimated_cost_usd": str(cost),
                "input_tokens": inputs,
                "output_tokens": outputs,
                "recent_attempts": [
                    {
                        "request_id": r.request_id,
                        "provider": r.provider,
                        "model": r.model,
                        "state": r.state,
                        "cost_usd": str(r.cost),
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ],
            }
