# Scope and acceptance mapping

This release implements the mandatory gateway MVP. The broader specification also contains future or optional features; those are distinguished below.

| Acceptance criterion | Implementation / evidence |
|---|---|
| AC-01 / AC-02: unified, replaceable providers | Domain protocol; five HTTP adapters; shared contract suite |
| AC-03 / AC-06: bounded transient retries | Executor; 429/5xx/timeout tests; global retry budget |
| AC-04: circuit breaker | Redis closed/open/half-open state; single-probe and recovery tests |
| AC-05: policy-aware fallback | Executor eligibility, deadline and spending checks |
| AC-07: request cost limits | Decimal estimates and durable attempt reservations |
| AC-08: tenant usage | PostgreSQL ledger and application-scoped usage endpoint |
| AC-09: distributed rate limits | Redis Lua; real multi-instance integration test |
| AC-10: validated structured output | Restricted JSON Schema; parse, validate, protect and revalidate |
| AC-11: invalid key rejection | Wrong, expired and revoked key tests |
| AC-12: tenant isolation | Cross-tenant and cross-application tests |
| AC-13: secret-safe telemetry | Sanitized errors and logging; leak regression tests |
| AC-14: PII policies | Allow/mask/block tests and input/output checks |
| AC-15: tracing | Request span, stage spans, OTLP exporter, response correlation |

## Deliberate implementation choices

- The API supports the canonical messages/constraints payload, not the introductory shorthand.
- Provider status is passive circuit state, not an active billable health check.
- Invalid structured output may fall back once per eligible provider; there is no same-provider repair agent.
- Tenant budgets are hard admission limits. Automated economy-only mode and configurable soft-limit alerting are not included.
- The catalog is a versioned JSON configuration. It is not duplicated in database configuration tables.
- Authentication management is an operator CLI, not an enterprise IAM system or public admin API.
- Usage exposes aggregates and the most recent 100 attempts. A paginated audit/usage export is future work.
- Redis is required and fails closed. Cache-only graceful degradation is not separately configurable.
- The router uses configured quality and latency estimates, not historical learning.
- Streaming, tool calls, multimodal input, semantic cache, RAG, Kubernetes, billing and ML routing are outside this release.

## Release limitations

Budget estimates are conservative but are not vendor invoices. Idempotency is not exactly-once delivery across Redis data loss. PII regex and prompt heuristics do not guarantee security. External adapters need live tests with the owner's credentials before production use. See the validation report for the exact checks run for this package.
