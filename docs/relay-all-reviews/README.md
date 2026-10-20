# Global inline review relay

Status: **spec ready for implementation** — 2026-10-19.

| Artifact | Description |
|----------|-------------|
| [spec.md](spec.md) | Replace single-PR bridge binding with a reviews-directory lookup |

## Summary

One long-lived `review-ticket serve-inline-review` process serves snapshots for **any** pull request that has automated `findings.json` on disk, across all Jira issues under the configured reviews root. The browser extension identifies the PR from GitHub; the relay resolves issue and SHA when the deep link omits them or when multiple tickets reviewed the same PR.

## Related

- [inline-reviewer-browser](../plans/inline-reviewer-browser/) — extension, SHA gate, Prepare semantics (unchanged except snapshot fetch)
- [extensions/inline-reviewer/README.md](../../extensions/inline-reviewer/README.md) — operator setup (to be updated when this ships)

## Supersedes

The **single-PR lock** described in [inline-reviewer-browser implementation P2](../plans/inline-reviewer-browser/implementation.md) (`serve-inline-review` bound to `active_pr` and rejecting other `GET /snapshot` identities). That behavior is removed, not deprecated.
