# Benchmark methodology

Run:

```bash
python -m benchmarks.run --experiment cost --requests 1000
python -m benchmarks.run --experiment resilience --requests 1000
```

Both commands require the development dependencies and make no paid API calls. They execute actual gateway ASGI requests using SQLite, fakeredis with Lua and the deterministic FakeProvider. These runs do not validate PostgreSQL contention, network throughput or real model quality.

## Cost experiment

The dataset contains four classification cases, three summaries, two extractions and one reasoning case. Repeating it 100 times gives the requested 40/30/20/10 distribution.

Baseline always selects the strongest fake model, disables retries and caching, and uses the same gateway API envelope. Gateway uses deterministic routing, permitted fallback and exact caching. The ten distinct repeated cases intentionally show a cache-friendly workload. This is not a claim that production traffic has the same hit rate.

Prices are synthetic. The quality proxy checks exact values or expected text properties. Both fake models return deterministic fixtures, so the proxy is a test of plumbing, not evidence that a cheaper real model has equal quality.

## Resilience experiment

Each strategy receives 1,000 requests with 30% independent failure probability on primary provider attempts. Compare baseline, retry, retry plus circuit breaker, and retry plus circuit breaker plus fallback.

The random seed is fixed per strategy. Retries change the number of random draws, so faults are reproducible within each strategy but are not paired at identical logical request positions. A circuit without fallback can intentionally reduce success while preventing repeated provider traffic.

The summary reports relative failure reduction against baseline. It is a comparison between strategies, not a measurement of individually paired recovered requests.

## Output and integrity

Each run writes one JSONL file per strategy and a summary.json containing the runtime, platform, seed, P50/P95/P99, throughput, success rate, fallback rate, cache rate, token usage, estimated cost and quality proxy. Failed and unresolved provider attempts remain included in the ledger totals.

Latency is end-to-end ASGI duration measured with a monotonic clock. Throughput is sequential throughput. It is not maximum parallel capacity. Windows scheduling, background services and local storage affect timings.

Use tests/load/gateway.js with k6 against a dedicated deployed tenant to measure network load. The initial targets are 99.9% successful internal processing and P95 internal overhead below 100 ms; this reference does not claim to have achieved those production SLOs.
