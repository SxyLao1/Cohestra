# Public Worklog

## 0.1.0 engineering baseline

| Area | State | Evidence boundary |
| --- | --- | --- |
| SQLite bridge | Implemented and locally tested | Source and focused tests define the package surface. |
| Schema-7 task, claim, leader, escalation, backup, restore | Implemented and locally tested | Exposed through `cohestra-bridge --db PATH`. |
| Workspace registry, selective guide/sync/health | Implemented and locally tested | Exposed through `cohestra workspace`; mutation is explicit. |
| Provider-neutral finite broker and adapters | Implemented and locally tested | Five provider descriptions, detection, and private-overlay scaffold are bundled; launch bindings remain recipient-local. |
| Documentation and GitHub workflows | Configured and remotely validated on `main` | Run `31241967251` completed 11 CI jobs successfully. New branch changes remain pending PR CI. |
| Main branch protection | Enabled | Force pushes and deletion are blocked; PRs, strict required checks, linear history, and conversation resolution are required. |
| Package, release, and registry publication | Not performed | No GitHub Release or PyPI publication is claimed. |

## Extraction provenance

The public baseline was selectively and one-way extracted from a customized
local coordination workspace. Personal memory, live databases, credentials,
session IDs, machine paths, private routes, and concrete desktop wake bindings
were excluded. This worklog does not identify local source locations or
reproduce internal collaboration state.

## Local verification - 2026-08-08

The following checks passed on Windows with supported local Python runtimes:

- 75 tests passed with one Windows-only POSIX-permission skip and 69.82 percent
  branch coverage against a 65 percent initial gate.
- Ruff lint and format checks across source, tests, and release scripts.
- Mypy strict checking across 23 package source files.
- Actionlint checks for CI and tag-build workflows.
- Project-contract, bilingual-link, and sensitive-data scans across 70 source and
  documentation text files.
- Wheel and source distribution build and content inspection.
- Isolated wheel CLI smoke for version, adapter detection, and bridge help.

The multi-OS matrix completed successfully in GitHub Actions run `31241967251` on `main` (11 jobs). The current branch's adapter and documentation changes remain unverified until pull-request CI completes.
