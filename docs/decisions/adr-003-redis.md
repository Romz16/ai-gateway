# ADR-003: Redis for distributed short-lived controls

Status: Accepted

## Context

Multiple replicas must share rate limits, concurrency leases and circuit state.

## Decision

Use atomic Lua scripts with server time and bounded leases. Keep response retention opt-in.

## Alternatives

Process-local memory cannot enforce global limits. A database-only limiter increases hot-row contention.

## Consequences

Redis becomes a required admission dependency. Use noeviction and private authenticated transport; Cluster is out of scope.
