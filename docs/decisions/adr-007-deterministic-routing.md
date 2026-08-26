# ADR-007: Deterministic routing before learned routing

Status: Accepted

## Context

The initial router must be explainable, cheap and testable.

## Decision

Apply explicit eligibility rules and choose by preference, cost and expected latency.

## Alternatives

Learned routing would require labeled data, model evaluation and drift monitoring.

## Consequences

Quality tiers and latency estimates require operator review. Historical adaptive routing is deferred.
