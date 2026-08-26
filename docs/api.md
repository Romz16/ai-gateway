# API guide

Authentication uses Authorization: Bearer YOUR_KEY. Identity comes from the credential, never from the request body. Unknown payload fields are rejected.

| Endpoint | Scope | Purpose |
|---|---|---|
| GET /health | None | Process liveness |
| GET /ready | None | PostgreSQL and Redis readiness |
| POST /v1/generate | generation:execute | Text or JSON generation |
| POST /v1/generate/structured | generation:execute | Generation with a required JSON schema |
| GET /v1/usage | usage:read | Application-scoped usage and recent attempts |
| GET /v1/providers/status | providers:read | Passive circuit state for permitted providers |
| GET /metrics | Private operational network | Prometheus exposition |

The canonical payload uses messages and constraints. The introductory input/requirements shorthand in the source specification is not a second supported API shape.

Supported tasks: classification, summarization, extraction, reasoning and code_analysis.
Quality profiles: economy, balanced and quality.
The response includes the selected provider/model, reported token usage, total request cost across attempts, routing reason, latency, fallback flag and cache flag.

## Structured output

```json
{
  "task": "extraction",
  "messages": [{"role": "user", "content": "Extract the category."}],
  "response_schema": {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": ["general"]}},
    "required": ["category"],
    "additionalProperties": false
  }
}
```

Supported schema keywords are type, properties, required, additionalProperties, items, enum, const, minimum, maximum, minLength, maxLength, minItems, maxItems, description and title. Depth is limited to eight. Remote references, recursive references and regex constraints are rejected.

Schemas are validated locally regardless of provider capabilities. Invalid JSON, non-finite JSON numbers, truncation and schema violations cause rejection or a permitted provider fallback. There is no unbounded repair loop. Same-provider schema repair is not implemented.

## Errors

Errors contain a stable code, a safe message, request_id and trace_id. Common statuses are 401 for credentials, 403 for scope or isolation violations, 402 for budgets, 422 for validation/routing constraints, 429 for rate/concurrency limits, 502 for invalid output, 503 for dependency/provider availability and 504 for deadline expiry.

## Idempotency and cache

Send a unique Idempotency-Key of at most 128 ASCII letters, digits, dots, underscores, colons or hyphens. A replay returns the original operation response. Errors leave an unresolved marker rather than silently allowing another paid operation.

Set cache to true only if temporary output retention is acceptable. It defaults to false. Cache hits report zero new provider cost and tokens. They are still authenticated and rate limited.

## Usage filters

provider, model, start_date and end_date filter the authenticated application's usage. Use timezone-aware ISO 8601 dates; start is inclusive and end is exclusive. tenant and application may only equal the credential's own identifiers. Aggregates cover the requested interval; recent_attempts is capped at 100 rows.

Values named estimated_cost_usd are estimates based on the configured catalog, not invoices.
