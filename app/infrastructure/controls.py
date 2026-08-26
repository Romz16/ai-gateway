import json
from collections.abc import Awaitable
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from app.core.errors import GatewayError
from app.domain.models import Identity
from app.services.security import digest

RATE = """
for i,key in ipairs(KEYS) do
  if tonumber(redis.call('GET',key) or '0') >= tonumber(ARGV[i*2-1]) then return 0 end
end
for i,key in ipairs(KEYS) do
  local n=redis.call('INCR',key)
  if n==1 then redis.call('EXPIRE',key,ARGV[i*2]) end
end
return 1
"""
LEASE = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
for i,key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE',key,'-inf',now)
  if redis.call('ZCARD',key)>=tonumber(ARGV[i+2]) then return 0 end
end
for _,key in ipairs(KEYS) do
  redis.call('ZADD',key,now+tonumber(ARGV[2]),ARGV[1])
  redis.call('PEXPIRE',key,ARGV[2])
end
return 1
"""
ACQUIRE_CIRCUIT = """
local t=redis.call('TIME'); local now=tonumber(t[1])
local state=redis.call('HGET',KEYS[1],'state') or 'closed'
if state=='open' then
  if now<tonumber(redis.call('HGET',KEYS[1],'until') or '0') then return '' end
  redis.call('HSET',KEYS[1],'state','half_open','probe',ARGV[1],'until',now+tonumber(ARGV[2]))
  return ARGV[1]
elseif state=='half_open' then
  if now<tonumber(redis.call('HGET',KEYS[1],'until') or '0') then return '' end
  redis.call('HSET',KEYS[1],'probe',ARGV[1],'until',now+tonumber(ARGV[2]))
  return ARGV[1]
end
return 'closed'
"""
FINISH_CIRCUIT = """
local state=redis.call('HGET',KEYS[1],'state') or 'closed'
if ARGV[1]~='closed' then
  if state~='half_open' or redis.call('HGET',KEYS[1],'probe')~=ARGV[1] then return 0 end
elseif state~='closed' then return 0 end
if ARGV[2]=='1' then
  redis.call('HSET',KEYS[1],'state','closed','failures',0); return 0
end
local n=redis.call('HINCRBY',KEYS[1],'failures',1)
if state=='half_open' or n>=tonumber(ARGV[3]) then
  local t=redis.call('TIME')
  redis.call('HSET',KEYS[1],'state','open','until',tonumber(t[1])+tonumber(ARGV[4])); return 1
end
return 0
"""


class Controls:
    def __init__(self, redis: Redis, namespace: str = "gateway") -> None:
        self.redis, self.namespace = redis, namespace

    async def _eval(self, script: str, count: int, *args: str | int) -> Any:
        return await cast(Awaitable[Any], self.redis.eval(script, count, *[str(a) for a in args]))

    def key(self, value: str) -> str:
        return f"{self.namespace}:{value}"

    async def rate_limit(self, identity: Identity) -> None:
        scopes = [
            f"tenant:{identity.tenant_id}",
            f"app:{identity.application_id}",
            f"key:{identity.key_id}",
        ]
        keys = [self.key(f"rate:{s}:{period}") for s in scopes for period in ("minute", "day")]
        args = [v for _ in scopes for v in (identity.rpm, 60, identity.requests_per_day, 86400)]
        if not await self._eval(RATE, len(keys), *keys, *args):
            raise GatewayError("RATE_LIMIT_EXCEEDED", "The request rate limit was reached.", 429)

    async def lease(self, identity: Identity, ttl_ms: int, global_limit: int) -> str:
        token = str(uuid4())
        keys = [self.key("inflight"), self.key(f"inflight:{identity.tenant_id}")]
        if not await self._eval(LEASE, 2, *keys, token, ttl_ms, global_limit, identity.concurrency):
            raise GatewayError(
                "RATE_LIMIT_EXCEEDED", "The gateway is at its concurrency limit.", 429
            )
        return token

    async def release(self, identity: Identity, token: str) -> None:
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.zrem(self.key("inflight"), token)
            pipeline.zrem(self.key(f"inflight:{identity.tenant_id}"), token)
            await pipeline.execute()

    async def retry_allowed(self, maximum: int) -> bool:
        return bool(await self._eval(RATE, 1, self.key("retry-budget"), maximum, 60))

    async def circuit_acquire(self, provider: str, lease_seconds: int) -> str:
        result = await self._eval(
            ACQUIRE_CIRCUIT, 1, self.key(f"circuit:{provider}"), str(uuid4()), lease_seconds
        )
        return str(result)

    async def circuit_finish(
        self, provider: str, token: str, success: bool, threshold: int, recovery: int
    ) -> bool:
        return bool(
            await self._eval(
                FINISH_CIRCUIT,
                1,
                self.key(f"circuit:{provider}"),
                token,
                int(success),
                threshold,
                recovery,
            )
        )

    async def circuit_status(self, provider: str) -> str:
        return str(
            await cast(Awaitable[Any], self.redis.hget(self.key(f"circuit:{provider}"), "state"))
            or "closed"
        )

    async def cached(self, fingerprint: str) -> dict[str, Any] | None:
        value = await self.redis.get(self.key(f"cache:{fingerprint}"))
        return json.loads(value) if value else None

    async def cache(self, fingerprint: str, result: dict[str, Any], ttl: int) -> None:
        await self.redis.set(self.key(f"cache:{fingerprint}"), json.dumps(result), ex=ttl)

    async def claim(
        self, identity: Identity, key: str, fingerprint: str, ttl: int
    ) -> tuple[str, dict[str, Any] | None]:
        storage_key = self.key(f"idem:{identity.tenant_id}:{identity.application_id}:{digest(key)}")
        initial = json.dumps({"fingerprint": fingerprint, "state": "pending"})
        if await self.redis.set(storage_key, initial, nx=True, ex=ttl):
            return storage_key, None
        value = await self.redis.get(storage_key)
        if value is None:
            raise GatewayError("IDEMPOTENCY_CONFLICT", "Retry the idempotent request.", 409)
        data = json.loads(value)
        if data["fingerprint"] != fingerprint:
            raise GatewayError(
                "IDEMPOTENCY_CONFLICT", "The key was used with a different request.", 409
            )
        if data["state"] != "complete":
            raise GatewayError(
                "IDEMPOTENCY_IN_PROGRESS", "The operation is pending or unresolved.", 409
            )
        return storage_key, data["result"]

    async def complete(self, key: str, fingerprint: str, result: dict[str, Any], ttl: int) -> None:
        await self.redis.set(
            key,
            json.dumps({"fingerprint": fingerprint, "state": "complete", "result": result}),
            ex=ttl,
        )
