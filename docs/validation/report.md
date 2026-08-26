# Release validation

Validation date: 26 August 2026.

## Verified

- 114 tests passed in the Linux Python 3.12 container, including real PostgreSQL and Redis integration tests.
- Application statement coverage: 90.99%. CLI and the fake HTTP server entrypoint are excluded from this coverage metric.
- Windows Python 3.13 local suite passed: 111 tests; three real-backend tests skipped locally and then passed in Docker.
- Ruff lint and format checks passed.
- Mypy passed for all 25 application source files.
- Bandit completed with no findings. Two narrow B311 suppressions cover deterministic fault injection and retry jitter, not credential generation.
- The pinned runtime dependency audit reported no known vulnerabilities.
- The corrected gateway image had zero HIGH/CRITICAL findings with available fixes in Trivy.
- Gitleaks reported no secrets in the selected release files.
- Docker image build, automatic migration and demo-key bootstrap succeeded.
- HTTP generation, structured output, idempotent replay, invalid-key rejection and tenant isolation passed.
- A real HTTP outage experiment opened the primary circuit, returned a backup response and restored the local fake provider.
- Prometheus reported the gateway target as up; Jaeger listed ai-gateway traces; Grafana returned the provisioned dashboard.
- Cost and resilience experiments completed 6,000 total synthetic requests and saved raw JSONL data.

## Security review

The initial base-image scan found a fixable high-severity OpenSSL issue. The Dockerfile now installs available operating-system security updates during build. See container-scan.json for the final image scan and its exact scope.

Image environment and build-history metadata were removed from the distributed scanner report to avoid false positives on the base image public GPG signing fingerprint. Vulnerability findings and package evidence are unchanged.

The container scan checks HIGH and CRITICAL findings with available fixes. It does not mean the image is free of every vulnerability. Runtime Python dependencies were checked separately with pip-audit. Monitoring images are local demonstration dependencies and were not part of the gateway-image scan.

## Evidence

- [Container test output](container-tests.txt)
- [Bandit report](bandit.json)
- [Dependency audit](dependency-audit.json)
- [Container scan](container-scan.json)
- [Secret scan](secrets-scan.json)
- [HTTP smoke test](http-smoke.json)
- [Measured benchmark table](../../benchmarks/results/README.md)

## Not verified

- Live OpenAI, Anthropic, Gemini or Ollama inference with the owner's accounts and models.
- Production traffic, cloud deployment, high-availability failover, disaster recovery or sustained load.
- GitHub-hosted workflow execution; the workflow files are included for the first repository push.
- Full security compliance, complete PII removal or protection against every prompt injection.
- Real model-quality comparisons or real vendor-cost savings.

External provider contract tests validate synthetic HTTP responses and errors. Demo prices are intentionally synthetic. Production rollout remains the repository owner's responsibility.
