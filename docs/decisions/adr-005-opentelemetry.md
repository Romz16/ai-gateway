# ADR-005: OpenTelemetry with sanitized attributes

Status: Accepted

## Context

An operation must be traceable without collecting its prompt.

## Decision

Create request and stage spans with identifiers, model names and usage. Export through OTLP without recording exception payloads.

## Alternatives

Vendor-specific tracing reduces portability. Full payload capture increases privacy and retention risk.

## Consequences

Troubleshooting relies on metadata and reproducible fixtures. Exporter outages do not authorize unsafe requests.
