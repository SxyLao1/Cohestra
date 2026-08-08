# Contributing to Cohestra

## Before proposing a change

This repository is pre-release and has no selected open-source license. Obtain
project-owner authorization before reusing code, submitting external patches,
or publishing derived artifacts.

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

## Change boundaries

- Do not add implicit database discovery or a default live state path.
- Keep adapter-specific launch behavior outside bridge persistence.
- Make destructive recovery require explicit snapshot and rollback paths.
- Document migrations, compatibility impact, and failure behavior.
