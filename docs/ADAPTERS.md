# Adapter Guide

[简体中文](zh-CN/ADAPTERS.md)

An adapter connects Cohestra state to a provider or local runtime. It is outside the SQLite bridge. The bridge records an atomic wake claim but does not invoke an adapter or know private desktop commands.

Adapters should declare a stable identifier and supported runtime, validate task-scoped input, apply local allowlists, preserve correlation without logging secrets, and distinguish unsupported, pre-launch failure, dispatched, and unknown delivery outcomes.

| Provider | Public support state | Initial overlay state |
| --- | --- | --- |
| Codex | manual-only | disabled/manual |
| Claude | headless candidate | disabled/manual |
| WorkBuddy | headless candidate | disabled/manual |
| ZCode | headless candidate | disabled/manual |
| Freebuff | cataloged/manual-only; automation unsupported | disabled/manual |

`detect` identifies safe candidates and `configure` scaffolds a private overlay.
Without `--provider`, configure selects a detected non-`unsupported` candidate
on `PATH`; it defaults to no overwrite and rejects Git worktrees and symlinks.
This reduces path and template entry, not runtime review: the recipient must
provide and approve the concrete local launch binding.

Adapters must not discover state from personal folders, browser profiles, or live databases; embed credentials, sessions, private routes, or machine-specific wake bindings in public configuration; or run arbitrary event text. Wake support is optional; when an adapter is unavailable, ineligible, or cannot validate a request, it must fail closed as unsupported and must not dispatch a fallback command.

```text
Leader event -> bridge wake claim -> adapter validation -> local dispatch
     ^                                                   |
     +------- claim result: dispatched or launch_failed--+
```

Delivery confirmation is provider-specific and may remain unknown after local dispatch. Publishing an event does not imply a wake request. Unsupported is a valid cross-platform health result; do not provide a generic fallback that attempts a private desktop wake command.

A candidate is not a verified wake. Delivery may be called verified only after a
correlated response and acknowledgement are recorded; current commands do not
perform that verification.
