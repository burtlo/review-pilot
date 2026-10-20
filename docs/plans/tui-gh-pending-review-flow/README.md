# TUI → GitHub pending review flow

Status: **retro captured** — 2026-10-19.

| Artifact | Description |
|----------|-------------|
| [retro.md](retro.md) | Operator product feedback: stage findings on GitHub as a pending review instead of primary TUI triage; comment layout and author-facing summary |
| `spec.md` | *(not started)* — use [/retro-feature-interview](../../../.cursor/skills/retro-feature-interview/SKILL.md) after retro is stable |

## Related

- [tui-review-flow](../tui-review-flow/) — attach hub, per-PR triage (`PrReviewScreen`), `human-review.json`
- [inline-reviewer-browser](../inline-reviewer-browser/) — DOM-based staging on Files changed (SHA gate, selectors)
- [multi-pr-reviewer-integration](../multi-pr-reviewer-integration/) — `publish-review` submits via `gh api` with `event` set

## Theme

Shift the **primary human editing surface** from local TUI preview to **GitHub’s pending pull request review** (inline + thread comments the author sees), while review-ticket still owns findings, triage decisions, and payload generation.
