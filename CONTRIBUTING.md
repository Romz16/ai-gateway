# Contributing

Use Python 3.12 or newer. Create an isolated virtual environment, install requirements-dev.lock, and install this package with pip install --no-deps -e .

Before opening a pull request, run ruff check ., ruff format --check ., mypy app, pytest --cov=app, bandit -r app -q and pip-audit -r requirements.lock. Run docker compose --profile test run --build --rm tests for real backend coverage.

Keep the domain independent of vendor SDKs. Add tests for failure behavior, tenant boundaries and spending changes. Never commit credentials, real customer prompts or personal data. Use synthetic fixtures.

Document API changes and architectural decisions. Report performance only with a reproducible script, configuration and raw results. Describe what was tested and what remains unverified.

Use clear English in code, comments, documentation and issues. Prefer precise B2/C1 language over marketing claims.
