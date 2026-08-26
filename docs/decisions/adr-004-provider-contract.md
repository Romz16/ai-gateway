# ADR-004: Provider-neutral domain contract

Status: Accepted

## Context

Provider APIs differ in message shape, token usage and error behavior.

## Decision

Define a typed asynchronous protocol and HTTP adapters. Keep vendor SDKs out of business logic.

## Alternatives

Vendor SDKs are convenient but can hide retry behavior and couple the domain to changing types.

## Consequences

Transport logic is explicit and tested. Maintaining wire adapters is an ongoing responsibility.
