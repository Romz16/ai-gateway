# Measured synthetic benchmarks

Executed on 26 August 2026. These are local synthetic-provider measurements, not production guarantees.

## Cost experiment

| Strategy | Success | P50 ms | P95 ms | P99 ms | Req/s | Total estimated USD | Fallback | Cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 100.0% | 56.07 | 83.81 | 125.22 | 15.77 | 0.1638000000 | 0.0% | 0.0% |
| gateway | 100.0% | 18.46 | 56.84 | 100.05 | 37.94 | 0.0000543000 | 0.0% | 99.0% |

Runtime: 3.13.1; Windows-11-10.0.26200-SP0. Seed: 42.

Environment: Sequential ASGI requests; SQLite; fakeredis with Lua; in-process FakeProvider.

## Resilience experiment

| Strategy | Success | P50 ms | P95 ms | P99 ms | Req/s | Total estimated USD | Fallback | Cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 73.2% | 52.11 | 122.12 | 203.44 | 16.32 | 0.2210613000 | 0.0% | 0.0% |
| retry | 98.1% | 63.00 | 131.71 | 165.09 | 13.80 | 0.3342754000 | 0.0% | 0.0% |
| circuit | 1.2% | 16.59 | 25.27 | 51.92 | 54.97 | 0.0008660000 | 0.0% | 0.0% |
| fallback | 100.0% | 56.57 | 104.12 | 160.44 | 15.36 | 0.0364298000 | 83.2% | 0.0% |

Runtime: 3.13.1; Windows-11-10.0.26200-SP0. Seed: 42.

Environment: Sequential ASGI requests; SQLite; fakeredis with Lua; in-process FakeProvider.

## Interpretation

The cost scenario repeats ten distinct fixtures 100 times. A 99% cache hit rate is expected for this intentionally repetitive workload.
The circuit-only strategy rejects requests while the sole provider is open. This protects upstream capacity but does not preserve application success without fallback.
Different strategies take different wall-clock time, so the number of half-open recovery opportunities can differ. Do not rank latency without considering rejected requests.
Quality proxies are deterministic fixture checks, not real model-quality evaluations. Cost includes conservative unresolved reservations.
