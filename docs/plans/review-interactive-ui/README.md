# Review interactive operator UI

Status: **implementation map ready** — spec approved 2026-10-17.

| Artifact | Description |
|----------|-------------|
| [retro.md](retro.md) | Operator experience and design investigation |
| [spec.md](spec.md) | Approved feature specification (2026-10-17) |
| [implementation.md](implementation.md) | **Canonical** — deltas, work packages (P1–P8), verifier hooks, build order |

## Summary

Replace the `review interactive` REPL with `review-ticket <issue> review attach`: a Textual status document plus a per-PR review screen. Borrow presentation patterns from the Foundry attach client (scrollable narrative, colored actions, accept/reject buttons) without depending on Foundry or replicating its run/host workflow. Decisions stay the current human-review model. The UI reads local files only and binds each review to the commit snapshot it was generated for.

## Related

- [multi-pr-reviewer-integration](../multi-pr-reviewer-integration/) — triage chain (`run-review` → interactive review → `publish-review`)
- Foundry reference (external): `foundry attach` / `foundry_cli/tui/app.py` on the operator’s machine at `c:\repos\burtlo\foundry`
