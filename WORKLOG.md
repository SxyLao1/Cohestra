# Public Worklog

## 0.1.0 engineering baseline

| Area | State | Evidence boundary |
| --- | --- | --- |
| SQLite bridge | Implemented and locally tested | Source and focused tests define the package surface. |
| Schema-7 task, claim, leader, escalation, backup, restore | Implemented and locally tested | Exposed through `cohestra-bridge --db PATH`. |
| Workspace registry, selective guide/sync/health | Implemented and locally tested | Exposed through `cohestra workspace`; mutation is explicit. |
| Provider-neutral finite broker and adapters | Implemented and locally tested | No provider or desktop wake binding is bundled as public default. |
| Documentation and GitHub workflows | Configured | Static files are local; no remote workflow has been observed. |
| Package, release, and registry publication | Remote-unverified / not performed | No remote mutation, GitHub Release, or PyPI publication is claimed. |

## Extraction provenance

The public baseline was selectively and one-way extracted from a customized
local coordination workspace. Personal memory, live databases, credentials,
session IDs, machine paths, private routes, and concrete desktop wake bindings
were excluded. This worklog does not identify local source locations or
reproduce internal collaboration state.

## Local verification - 2026-08-08

The following checks passed on Windows with Python 3.12:

- 61 tests with 67.72 percent branch coverage against a 65 percent initial gate.
- Ruff lint and format checks across source, tests, and release scripts.
- Mypy strict checking across 18 package source files.
- Actionlint checks for CI and tag-build workflows.
- Project-contract and sensitive-data scans across 56 source and documentation text files.
- Wheel and source distribution build, content inspection, and Twine metadata checks.
- Isolated wheel CLI smoke for version, bridge/workspace help, schema-7 initialization, and health.

The multi-OS matrix is configured but remains remote-unverified until the repository is hosted and CI runs.
