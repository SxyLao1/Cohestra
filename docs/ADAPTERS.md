# Adapter Guide

An adapter connects Cohestra state to a provider or local runtime. It is outside the SQLite bridge. The bridge records an atomic wake claim but does not invoke an adapter or know private desktop commands.

Adapters should declare a stable identifier and supported runtime, validate task-scoped input, apply local allowlists, preserve correlation without logging secrets, and distinguish unsupported, pre-launch failure, dispatched, and unknown delivery outcomes.

Adapters must not discover state from personal folders, browser profiles, or live databases; embed credentials, sessions, private routes, or machine-specific wake bindings in public configuration; or run arbitrary event text.

```text
Leader event -> bridge wake claim -> adapter validation -> local dispatch
     ^                                                   |
     +------- claim result: dispatched or launch_failed--+
```

Delivery confirmation is provider-specific and may remain unknown after local dispatch. Unsupported is a valid cross-platform health result; do not provide a generic fallback that attempts a private desktop wake command.
