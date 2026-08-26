# ADR-006: Exact caching before semantic caching

Status: Accepted

## Context

Similar prompts can require different answers or permissions.

## Decision

Use an exact fingerprint of request, tenant security context and catalog revision. Disable caching unless requested.

## Alternatives

Semantic caching requires similarity thresholds, quality evaluation and stronger isolation analysis.

## Consequences

Cache hits are predictable but limited. Redis may temporarily hold output only after client opt-in.
