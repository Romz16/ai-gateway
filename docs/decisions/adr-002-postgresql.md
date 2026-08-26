# ADR-002: PostgreSQL as the durable authority

Status: Accepted

## Context

Budgets and access rules must survive process and cache failures.

## Decision

Store tenants, applications, key hashes, attempt reservations and audit events in PostgreSQL. Serialize budget admission with a tenant-row lock.

## Alternatives

Redis-only accounting is faster but risks losing durable spending history; an external billing service adds complexity.

## Consequences

Per-tenant contention is a throughput limit. Unknown attempts remain charged and need reconciliation.
