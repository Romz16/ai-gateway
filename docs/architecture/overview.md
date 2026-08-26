# Architecture

The gateway is a modular monolith. FastAPI handles transport, the service layer enforces policy, and adapters translate a common domain contract into provider HTTP requests. PostgreSQL is the durable authority for access and spending. Redis coordinates short-lived controls across replicas.

## Module boundaries

| Module | Responsibility | Failure strategy |
|---|---|---|
| API | Authentication, safe errors, body limits and correlation | Reject invalid requests; never echo validation input |
| Security | PII policy and prompt heuristics | Reject blocked content before provider access |
| Router | Explainable filtering and cost ordering | Reject when no candidate meets policy |
| Executor | Attempts, deadlines, retry and fallback | Bounded attempts; preserve uncertain charges |
| Repository | Credential lookup, reservations, usage and audit | Fail closed when persistence is unavailable |
| Controls | Rate limits, leases, circuit state, exact cache and idempotency | Fail closed when Redis is unavailable |
| Adapters | Provider wire formats, usage and error normalization | No redirects; bounded response bodies and HTTP timeouts |
| Telemetry | Safe events, metrics and traces | Export asynchronously; monitoring is not an authorization dependency |

## Admission and spending

A provider attempt receives a durable reservation before network I/O. PostgreSQL locks the tenant row, sums the current UTC day and month, and verifies spending and token limits in one transaction. Multiple gateway replicas cannot admit conflicting reservations for the same tenant.

Successful provider usage replaces the estimate. A timeout, malformed response or process crash may leave a reservation unresolved. Such reservations remain charged. This favors preventing overspend over maximum utilization. Review them against provider billing before making an administrative adjustment.

The per-request ceiling includes all attempts, including retries and fallbacks. Estimates use UTF-8 bytes plus envelope headroom, not a provider tokenizer. Actual provider usage can exceed the estimate if an upstream contract changes. The ledger records that overrun and blocks a successful response. Provider-side account limits remain necessary.

## Distributed state

Rate limits use atomic Lua checks for the API key, application and tenant. Windows begin with the first accepted request and last 60 seconds or 24 hours. Limits are not sliding-window guarantees.

Concurrency uses sorted-set leases with Redis server time. A lease lasts 90 seconds, exceeding the maximum 60-second generation deadline. Process death does not leave a permanent slot. The front proxy and ASGI server must also limit unauthenticated traffic.

Circuit state is shared by provider. A half-open probe has a fencing token so an obsolete probe cannot close a newer circuit. An abandoned probe can be replaced after its lease expires. Redis standalone or Sentinel is supported; Redis Cluster is not supported because some scripts touch keys in different hash slots.

## Cache and idempotency

Exact caching is opt-in per request. The key includes the tenant, application, scopes, provider permissions, PII policy, request budget, catalog revision, messages, parameters and schema. No cache entry is shared across tenants. A hit records zero new tokens and zero new provider cost.

Idempotency is also opt-in through a header. It stores a result for a limited period and rejects a different request under the same key. Pending or uncertain operations return HTTP 409. An idempotent replay returns the original operation identifiers; response headers identify the current HTTP request.

Redis stores response content only when caching or idempotency is requested. Prompts are never written to PostgreSQL, metrics or logs. Cache retention is 120 seconds by default; idempotency retention is one hour. Redis loss can lose replay protection. This is not exactly-once execution.

## Routing policy

Candidates must meet task, quality, context size, expected latency, provider permission and cost constraints. Reasoning and code analysis require quality tier 3. A preferred provider is considered first only if it passes all hard constraints. Other candidates are ordered by estimated cost and expected latency.

Expected latency and quality tiers are operator-supplied estimates. They are not learned performance guarantees. Circuit state is checked immediately before dispatch. Fallback never expands the tenant allowlist.
