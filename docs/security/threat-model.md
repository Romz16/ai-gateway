# Threat model

## Scope and trust boundaries

The client, input messages, schemas, provider responses and network are untrusted. API keys identify a tenant and an application. Client payloads cannot override these identities. Operators control catalog entries, provider endpoints, credentials and tenant policy.

The gateway does not execute tools, browse model-generated URLs, evaluate output as code or provide agents with external permissions.

| Threat | Controls | Residual risk |
|---|---|---|
| Stolen API key | Hashed storage, scopes, expiry, revocation, tenant budgets | The key can act within its existing rights until revoked |
| Cross-tenant access | Server-derived identity, scoped SQL, isolated cache and idempotency | Application bugs still require independent review |
| Prompt injection | Input bounds, instruction separation, heuristic blocking, no tool execution | A single classifier or prompt cannot reliably solve injection |
| Sensitive data disclosure | Allow/mask/block policies; safe logs; opt-in content caching | Regex can miss data and produce false positives |
| Compromised provider | Bounded responses, strict JSON parsing, schema validation, output PII checks | Semantically wrong but valid output may pass |
| Resource exhaustion | Body and output limits, deadlines, leases, rate and retry budgets | Upstream traffic should be protected at the reverse proxy |
| Overspending | PostgreSQL reservations, Decimal accounting, per-attempt checks | Token estimates and provider invoices may differ |
| SSRF | No client-controlled endpoint, redirect following disabled, no remote schema references | Misconfigured operator endpoints require egress filtering |
| Supply chain compromise | Locked dependencies, audit, secret and container scans | Scanners cannot detect every malicious package |
| Operational misconfiguration | Production configuration guards, documented rollout checklist | Local Compose is not a hardened public deployment |

## PII policy

The basic detector recognizes common email, CPF, card, phone, token and API-key patterns. It does not validate every national identifier, detect names and addresses reliably, or anonymize meaning. Numeric JSON values are not automatically treated as personal data.

PII detection reduces risk; it is not a guarantee of anonymization. Use a reviewed DLP service where sensitivity requires stronger protection. Masking an output can invalidate a schema; the gateway validates again and rejects it instead of silently returning an invalid result.

## Credential handling

Generated API keys use cryptographic randomness. Only a SHA-256 digest is stored in the database; high entropy makes offline guessing impractical. Expiry and revocation are checked on every request. Provider keys live in environment variables or a managed secret store.

The local bootstrap writes its demo key to a restricted Docker volume. It is never included in source, the README or an image layer. The only static database password belongs to the isolated local example.

## Telemetry and public endpoints

Logs contain fixed event names and identifiers, never raw provider exceptions. Metrics avoid tenant and API-key labels. Health, readiness, OpenAPI and metrics are unauthenticated for local operations; block them at an ingress boundary in production. Keep monitoring on a private network.

The local Grafana configuration enables anonymous viewing and binds only to localhost. Replace it with authenticated access before deployment.

## Reference

The controls address risks described by the [OWASP GenAI Security Project](https://genai.owasp.org/), including injection, information disclosure, improper output handling and unbounded consumption. This project does not claim formal compliance or complete protection.
