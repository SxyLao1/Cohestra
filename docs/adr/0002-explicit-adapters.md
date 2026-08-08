# ADR 0002: Explicit adapters; no private wake commands

## Status

Accepted for the 0.1.0 architecture baseline.

## Decision

Define a provider-neutral finite broker and explicit adapter contracts. The bridge records claims and outcomes, but adapters own local dispatch. Public defaults include no private wake command, desktop binding, session, or machine route.

## Consequences

Adapters can be reviewed per platform and return unsupported where appropriate. There is no universal wake guarantee, and local dispatch is not proof of remote delivery.
