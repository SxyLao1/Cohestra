## Summary

Describe the behavior change and user-visible boundary.

## Branch and Promotion

- Base branch: `dev` / `main`
- [ ] Feature or fix PR targets `dev`
- [ ] This is the stable `dev` -> `main` promotion PR
- [ ] This PR does not develop directly on `main`

## Linked Issue

- Linked issue: `Closes #N` / `Fixes #N` / `N/A`
- [ ] If an issue is linked, the closing keyword is appropriate and the issue is
  expected to be complete when this PR merges.
- [ ] If no issue is linked, `N/A` is stated explicitly.
- [ ] After merge, verify that a linked issue closed; do not use a closing
  keyword for unfinished work.

## Verification

- [ ] Tests and relevant checks run
- [ ] Documentation updated
- [ ] No live database, secret, session, personal memory, or private route included
- [ ] Explicit paths and recovery behavior reviewed
- [ ] CI completed for the target branch

## Risk

State compatibility, adapter/platform impact, and rollback notes:
