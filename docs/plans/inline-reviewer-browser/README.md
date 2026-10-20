# Inline reviewer browser overlay

Status: **implementation map ready** — spec approved 2026-10-19.

| Artifact | Description |
|----------|-------------|
| [spec.md](spec.md) | Approved feature specification (2026-10-19) |
| [github-files-changed.md](github-files-changed.md) | Observed Files changed UI: logged out, author, and non-author (2026-10-19) |
| [implementation.md](implementation.md) | **Canonical** — deltas, work packages (P1–P7), verifier hooks, build order |
| [path-line-navigation-feedback.md](path-line-navigation-feedback.md) | Parked 2026-10-19: in-panel clicks scroll to the file; line navigation failed |

## Summary

Side-loaded Chromium extension that opens GitHub **Files changed** from review-ticket links, verifies the **All commits** range and head SHA, and stages **all automated findings** into a pending review (draft line comments with suggestion markdown, off-diff text in **Finish your review**). It clicks **Start a review** on a composer when needed and never submits. Revisit-safe placement uses a visible finding marker and preflight. UI observations are in [github-files-changed.md](github-files-changed.md).

## Related

- [tui-review-flow](../tui-review-flow/) — attach TUI retro motivating inline diff context
- [review-interactive-ui](../review-interactive-ui/) — SHA-scoped snapshots and local-only attach boundary
- [multi-pr-reviewer-integration](../multi-pr-reviewer-integration/) — automated `findings.json` and publish payload shape
