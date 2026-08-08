# Release Process

1. Select and approve a license before describing the repository as open source.
2. Confirm version, changelog, compatibility statement, and migration notes.
3. Run lint, format, type, tests with the initial 65 percent coverage gate, build, install smoke, manifest, and sensitive-data checks.
4. Confirm distributions contain no local state, personal memory, credentials, session IDs, machine paths, private routes, or wake bindings.
5. Obtain explicit authorization for every remote action.

The tag workflow builds distributions and uploads GitHub workflow artifacts. It does not publish to PyPI or create a GitHub Release. A local build or configured workflow is not proof that a remote tag, registry publication, or release exists.

Run `python scripts/check_project.py`, `python scripts/check_sensitive_data.py`, and `python scripts/check_dist.py` as part of the local release gate after the distribution is built.
