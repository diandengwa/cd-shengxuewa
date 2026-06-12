# Important Decisions

## 2026-06-01
- Decision: Merge the existing PR #16 directly rather than recreating the changes in a new PR.
  - Reason: The task context explicitly stated that PR #16 already contained all required changes and was open for merging.
  - Impact: Preserved the existing review and commit history; avoided duplicate submissions.

- Decision: Use a merge commit and push it to remote `main`.
  - Reason: The goal was to get the PR integrated into `main` with minimal change to history.
  - Impact: Remote `main` advanced to merge commit `71174caf49f3cf5a382ff865ba3021fcf06fa410`.

- Decision: Return the local checkout to `feature/mvp-xiaoshengchu` after the push.
  - Reason: This keeps the working tree aligned with the original feature branch and avoids leaving the repo on a temporary merge branch.
  - Impact: Subsequent work can continue from the feature branch without confusion.

- Decision: Record the repository migration notice and tool-access failures in the archive.
  - Reason: These issues affected verification and are relevant if the task needs to be resumed or audited later.
  - Impact: Future recovery attempts can start with the correct remote location and avoid the same dead ends.
