# Review Ticket TUI review flow

Status: **implementation map ready** — [spec](spec.md) is the source of truth (status line: design specification for implementation). Canonical map is [implementation.md](implementation.md).

| Artifact | Description |
|----------|-------------|
| [spec.md](spec.md) | Feature specification for the review TUI |
| [implementation.md](implementation.md) | **Canonical** — deltas, work packages (P1–P14), verifier hooks, build order |

## Summary

Extend the existing Textual attach UI and CLI workflow into one review workspace: testing notes, multi-PR readiness, three SHA-scoped review tracks, authorized GitHub publication, and an authorized Jira ticket disposition. The CLI stays the mutation authority.

## Related

- [tui-end-to-end-return](../tui-end-to-end-return/) — attach command and testing-notes return already in the tree
- [review-interactive-ui](../review-interactive-ui/) — status document and per-PR triage already in the tree
- [multi-pr-reviewer-integration](../multi-pr-reviewer-integration/) — headless reviewer and per-PR publish
