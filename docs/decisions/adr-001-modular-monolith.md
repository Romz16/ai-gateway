# ADR-001: Modular monolith

Status: Accepted

## Context

The request pipeline has several policies but one operational purpose.

## Decision

Keep API, domain, services and infrastructure in one deployable application.

## Alternatives

Microservices would add network boundaries and distributed failure modes before a demonstrated need.

## Consequences

Deployments and debugging stay simple. Modules can be extracted if independent scaling becomes necessary.
