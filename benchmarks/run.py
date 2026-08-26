"""Real executions of a synthetic provider, not a vendor-quality benchmark."""

import argparse
import asyncio
import json
import logging
import math
import platform
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.infrastructure.controls import Controls
from app.infrastructure.database import ApiKey, Application, Base, Repository, Tenant
from app.main import Runtime, create_app
from app.observability.telemetry import Telemetry
from app.providers.fake import FakeProvider
from app.services.generation import GenerationService
from app.services.resilience import Executor
from app.services.routing import Router
from app.services.security import digest


def percentile(values, p):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


async def scenario(name, args, output):
    fault_rate = 0.3 if args.experiment == "resilience" else 0
    retries = 0 if name == "baseline" else 2
    breaker = name in {"circuit", "fallback", "gateway"}
    fallback = name in {"fallback", "gateway"}
    cache = name == "gateway"
    settings = Settings(
        app_env="test",
        max_retries=retries,
        retry_base_seconds=0.001,
        retry_budget_per_minute=100000,
        circuit_threshold=3 if breaker else 1000000,
    )
    scratch = Path(".benchmark-work")
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as folder:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(Path(folder) / "bench.db"))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        repository = Repository(engine)
        async with repository.sessions.begin() as session:
            session.add(
                Tenant(
                    id="benchmark",
                    allowed_providers=["fake", "fake_backup"],
                    daily_budget=100,
                    monthly_budget=1000,
                    request_budget=1,
                    daily_tokens=100000000,
                    rpm=100000,
                    requests_per_day=100000,
                )
            )
            await session.flush()
            session.add(Application(id="benchmark", tenant_id="benchmark"))
            await session.flush()
            session.add(
                ApiKey(
                    id="benchmark",
                    application_id="benchmark",
                    key_hash=digest("benchmark-fixture"),
                    scopes=["generation:execute"],
                )
            )
        controls = Controls(FakeRedis(decode_responses=True), str(uuid4()))
        telemetry = Telemetry()
        providers = {"fake": FakeProvider(failure_rate=fault_rate, latency_ms=1, seed=args.seed)}
        if fallback:
            providers["fake_backup"] = FakeProvider(latency_ms=1, seed=args.seed + 1)
        router = Router.from_file(settings.catalog_path, set(providers))
        if name == "baseline" and args.experiment == "cost":
            router = Router([m for m in router.models if m.model == "demo-strong"])
        executor = Executor(settings, providers, controls, repository, telemetry)
        runtime = Runtime(
            repository,
            controls,
            GenerationService(settings, router, executor, controls, repository, telemetry),
            telemetry,
            providers,
        )
        app = create_app(settings, runtime)
        logging.getLogger("gateway").setLevel(logging.CRITICAL)
        dataset = json.loads(Path("benchmarks/dataset.json").read_text())
        rows = []
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://benchmark",
                headers={"Authorization": "Bearer benchmark-fixture"},
            ) as client:
                for index in range(args.requests):
                    case = dataset[index % len(dataset)]
                    payload = {
                        "task": case["task"],
                        "messages": [{"role": "user", "content": case["input"]}],
                        "cache": cache,
                        "constraints": {"max_cost_usd": "0.1", "max_latency_ms": 5000},
                    }
                    if "schema" in case:
                        payload["response_schema"] = case["schema"]
                    tick = time.perf_counter()
                    response = await client.post("/v1/generate", json=payload)
                    data = response.json()
                    good = response.status_code == 200
                    content = data.get("content")
                    quality = good and (
                        content == case["expected"]
                        if case["method"] == "exact"
                        else case["expected"].lower() in str(content).lower()
                    )
                    rows.append(
                        {
                            "index": index,
                            "case": case["id"],
                            "status": response.status_code,
                            "latency_ms": (time.perf_counter() - tick) * 1000,
                            "provider": data.get("provider"),
                            "model": data.get("model"),
                            "fallback": data.get("fallback_used", False),
                            "cache_hit": data.get("cache_hit", False),
                            "quality_proxy": quality,
                            "attempts": data.get("attempts", 0),
                            "error": data.get("error", {}).get("code"),
                        }
                    )
            elapsed = time.perf_counter() - start
            identity = await repository.authenticate("benchmark-fixture")
            usage = await repository.usage(identity)
            successes = sum(r["status"] == 200 for r in rows)
            summary = {
                "scenario": name,
                "requests": args.requests,
                "elapsed_seconds": elapsed,
                "p50_ms": percentile([r["latency_ms"] for r in rows], 0.5),
                "p95_ms": percentile([r["latency_ms"] for r in rows], 0.95),
                "p99_ms": percentile([r["latency_ms"] for r in rows], 0.99),
                "throughput_rps": args.requests / elapsed,
                "success_rate": successes / args.requests,
                "fallback_rate": sum(r["fallback"] for r in rows) / args.requests,
                "cache_hit_rate": sum(r["cache_hit"] for r in rows) / args.requests,
                "quality_proxy": sum(r["quality_proxy"] for r in rows) / args.requests,
                "total_estimated_cost_usd": usage["estimated_cost_usd"],
                "cost_per_request_usd": str(Decimal(usage["estimated_cost_usd"]) / args.requests),
                "tokens_per_request": (usage["input_tokens"] + usage["output_tokens"])
                / args.requests,
                "provider_attempts": sum(p.calls for p in providers.values()),
                "injected_failure_rate": fault_rate,
            }
            (output / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            return summary
        finally:
            await controls.redis.aclose()
            await engine.dispose()
            telemetry.traces.shutdown()


async def main(args):
    if args.requests < 1:
        raise SystemExit("--requests must be positive.")
    output = Path(args.output) / args.experiment
    output.mkdir(parents=True, exist_ok=True)
    names = (
        ["baseline", "gateway"]
        if args.experiment == "cost"
        else ["baseline", "retry", "circuit", "fallback"]
    )
    results = [await scenario(name, args, output) for name in names]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": args.seed,
        "experiment": args.experiment,
        "environment": (
            "Sequential ASGI requests; SQLite; fakeredis with Lua; in-process FakeProvider"
        ),
        "warning": (
            "Synthetic prices and deterministic fixtures. "
            "No vendor quality, production SLO or cloud performance claim."
        ),
        "results": results,
    }
    if args.experiment == "resilience":
        baseline_failures = 1 - results[0]["success_rate"]
        for result in results:
            result["relative_failure_reduction"] = (
                (result["success_rate"] - results[0]["success_rate"]) / baseline_failures
                if baseline_failures
                else 0
            )
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", choices=["cost", "resilience"], required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="benchmarks/results")
    asyncio.run(main(parser.parse_args()))
