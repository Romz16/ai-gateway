.PHONY: up test check integration resilience-demo chaos-demo security-demo cost-demo
up:
	docker compose up --build -d
test:
	python -m pytest -q --cov=app --cov-report=term-missing
check:
	ruff check .
	ruff format --check .
	mypy app
integration:
	docker compose --profile test run --build --rm tests
resilience-demo:
	python -m benchmarks.run --experiment resilience
chaos-demo: resilience-demo
security-demo:
	python -m pytest tests/security -v
cost-demo:
	python -m benchmarks.run --experiment cost --requests 1000
