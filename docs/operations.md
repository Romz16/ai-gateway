# Operations guide

## Local startup

Copy .env.example to .env and run docker compose up --build -d. Migrations complete before the bootstrap job creates a credential. The gateway starts only after PostgreSQL, Redis and the fake HTTP provider are healthy.

Read the key with:

```bash
docker compose exec gateway cat /srv/secrets/demo-api-key
```

This explicitly displays a secret. Do not paste it into Git, screenshots or public logs.

## Add a real provider

1. Copy config/models.external.example.json to a new catalog file.
2. Replace every placeholder model and price. Review availability, token limits, task support and latency assumptions against your account.
3. Set CATALOG_PATH to that file and configure the relevant provider API key.
4. Create a tenant credential with the provider allowlist. Existing demo tenants permit only fake providers.
5. Run a small paid smoke test only after setting provider-side spending limits.

```bash
docker compose exec gateway python -m app.cli create-key --tenant real-demo --application real-demo-app --providers openai,anthropic
```

Existing tenant policy is not overwritten by create-key. Use a reviewed database change to modify budgets or allowlists. There is no unauthenticated administrative API.

For Ollama, pull a suitable model separately, configure its model name and reviewed context limit, and set OLLAMA_URL. Zero API price excludes hardware and energy.

## Key revocation

```bash
docker compose exec gateway python -m app.cli revoke-key --id KEY_ID
```

Keys expire after 90 days by default. Rotation means creating a new key, updating the client, then revoking the old one.

## Fault injection

Set FAKE_PROVIDER_FAILURE_RATE=0.30 or FAKE_PROVIDER_TIMEOUT_RATE=0.10 in .env, then recreate the fake provider:

```bash
docker compose up -d --force-recreate fake-provider
```

Send uncached requests. Inspect /v1/providers/status, the retry counters, audit rows and Jaeger traces. The backup provider has no injected failures. To restore normal behavior, reset the rates to zero and recreate the service.

## Failure handling

| Situation | Expected action |
|---|---|
| PostgreSQL unavailable | Generation fails closed; restore database and inspect reserved attempts |
| Redis unavailable or full | Generation fails closed; restore capacity without flushing active controls |
| Provider outage | Check circuit state, permissions, remaining deadline and request budget |
| Invalid output | Review schema compatibility; invalid content is not returned as valid |
| Budget exhausted | Inspect tenant ledger and unresolved reservations before raising limits |
| Idempotency 409 | The request differs or the original operation is unresolved; do not blindly rotate keys |
| Tracing unavailable | Requests continue; inspect exporter connectivity separately |

## Production rollout checklist

- Use a separate deployment manifest. The supplied Compose file is a local demonstration.
- Disable fake providers and remove demo credentials.
- Require HTTPS at ingress, enforce IP limits and cap headers, bodies and connections.
- Use PostgreSQL TLS and Redis TLS with authentication, a private network and least-privilege roles.
- Run migrations as a dedicated release job. Do not grant DDL rights to the runtime database role.
- Use a secret manager, immutable image digests, signed artifacts and an approved dependency update process.
- Set provider-side budget limits and verify catalog prices against invoices.
- Configure monitoring authentication, alert delivery and retention.
- Test backup restoration and Redis failover. Configure PostgreSQL point-in-time recovery.
- Review PII policy, regional processing requirements and the optional response retention.
- Run the real backend tests, load test and paid provider smoke tests before enabling traffic.
- Treat the availability and overhead SLOs as targets until measured on your deployment.

## Retention and reconciliation

PostgreSQL stores credential hashes, tenant policy, usage metadata and audit events. No prompt or output columns exist. Define legal and business retention before deployment. Archive audit and usage records with a scheduled, reviewed maintenance job; keep the active month available for budget enforcement.

Unresolved reservations remain charged, including after a worker crash. The reference does not automatically reconcile vendor invoices. A production reconciliation process must record adjustments with a reason and audit trail.

## Shutdown

docker compose down stops the local stack and preserves volumes. Deleting volumes also removes database history and demo keys; do that only when intentionally resetting the demonstration.
