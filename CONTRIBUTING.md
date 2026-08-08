# Contributing to Cohestra

## Before proposing a change

This repository is pre-release and licensed under MIT. Contributions submitted
to this repository are provided under the same license unless explicitly agreed
otherwise before submission.

Describe the problem, operational boundary, affected platforms, and verification
evidence. Do not attach live bridge databases, credentials, session data,
personal memory, machine-specific routes, or private wake configuration.

## Development checks

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src/cohestra
python -m pytest --cov=cohestra --cov-report=term-missing --cov-fail-under=65
python -m build
python scripts/check_project.py
python scripts/check_sensitive_data.py
python scripts/check_dist.py
```

Run the installed-wheel smoke check before proposing a packaging change. Keep
bridge commands machine-readable and preserve their explicit `--db` contract.

## Branch and Pull Request Policy

`dev` is the default development branch. Create feature and fix branches from
`dev` and open their pull requests against `dev`. Do not develop directly on
`main`. When a stable development baseline is ready, open one promotion pull
request from `dev` to `main`; do not merge individual feature or fix work
directly to `main`.

Remote source branches are deleted automatically after merge by repository
configuration. This does not replace local cleanup or verification of the
merged result.

When a pull request completes a linked issue, include `Closes #N` or `Fixes #N`
in its body and verify after merge that the issue is closed. Use neither closing
keyword for work that remains incomplete. If the pull request has no linked
issue, state `N/A` explicitly in the PR template.

## Change boundaries

- Do not add implicit database discovery or a default live state path.
- Keep adapter-specific launch behavior outside bridge persistence.
- Make destructive recovery require explicit snapshot and rollback paths.
- Document migrations, compatibility impact, and failure behavior.
