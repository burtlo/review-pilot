# Plans

Product design threads: retros, specs, and implementation maps.

| Bundle | Status | Summary |
| --- | --- | --- |
| [multi-pr-reviewer-integration](./multi-pr-reviewer-integration/) | in progress — [operator guide](./multi-pr-reviewer-integration/operator-guide.md), [implementation map](./multi-pr-reviewer-integration/implementation.md) | Headless `reviewer_command` adapter, `checkout_command` clones, interactive triage, per-PR publish loop |
| [review-interactive-ui](./review-interactive-ui/) | implementation map ready — [spec](./review-interactive-ui/spec.md), [implementation map](./review-interactive-ui/implementation.md) | `review attach` Textual status document and per-PR triage; replace the `review interactive` REPL; no Foundry dependency |
| [tui-end-to-end-return](./tui-end-to-end-return/) | implementation map ready — [spec](./tui-end-to-end-return/spec.md), [implementation map](./tui-end-to-end-return/implementation.md) | `review-ticket <issue> attach` (remove `review attach`); early gate + testing-notes UI with Jira refresh, post, and transition authorize |
| [tui-review-flow](./tui-review-flow/) | implementation map ready — [spec](./tui-review-flow/spec.md), [implementation map](./tui-review-flow/implementation.md); [retro](./tui-review-flow/retro.md) open | Full review TUI: readiness, three SHA-scoped tracks, authorized GitHub publication, and Jira ticket disposition |
