# Global inline review relay

Status: **approved for implementation** — 2026-10-19.

## Source

- Bundle: [README](README.md)
- Motivation: operator workflow with one bridge process, multiple Jira tickets, and multiple PRs per ticket ([inline-reviewer-browser](../plans/inline-reviewer-browser/))
- Replaces: per-issue / per-`active_pr` snapshot binding in `review_ticket.inline_review.serve_inline_review`

## Operator outcome

1. Start the relay once (any terminal): `review-ticket serve-inline-review` with `REVIEW_PILOT_BRIDGE_TOKEN` set.
2. In other terminals, run the normal ticket workflow (`review-ticket DOTNETIOT-3333 …`, `run-review`, `attach`, etc.). Automated output lands under `reviews/<ISSUE>/prs/…/commits/<sha>/review/findings.json` as today.
3. Open **Files changed** from the review status link (or any URL on that PR’s changes tab). The side panel loads findings for that **owner/repo#number** from disk without restarting the bridge or switching `active_pr`.
4. When more than one stored review matches the same PR, the relay serves the **newest** match and the panel warns that other candidates exist.

## Problem statement

Today `serve-inline-review` resolves one `(issue, owner, repo, number, sha)` at process start and returns **404** for any other `GET /snapshot` query. Multi-PR tickets (for example DOTNETIOT-2550) and multi-ticket development require stopping and restarting the bridge with `--pr` or changing `active_pr`. The on-disk layout is already global; only the HTTP handler is artificially scoped.

## Scope

### In scope

- **CLI:** `review-ticket serve-inline-review` with optional `--port` (default **8765**) and reviews directory from config. **No Jira issue argument** on this command. Remove `review-ticket <issue> serve-inline-review` and remove `--pr` / `--sha` from the serve command.
- **Bridge process:** Same transport and auth as today: bind **127.0.0.1** only, `REVIEW_PILOT_BRIDGE_TOKEN` required, `GET /snapshot` only, `Authorization: Bearer <token>`, no `Access-Control-Allow-Origin: *`, JSON responses, `Cache-Control: no-store`.
- **Lookup:** Scan the configured reviews root for automated reviews matching `owner`, `repo`, and `number`. Optional query filters `issue` and `sha`. Serve `build_snapshot` output (same finding row shape as today: `id`, `title`, `path`, `line`, `start_line`, `side`, `on_diff`, `body`, `scan_text`, plus top-level `summary_block`).
- **Disambiguation:** When multiple candidates remain after filters, choose the candidate with the greatest **review artifact mtime** (see [Resolution](#resolution)). Include resolution metadata in the JSON so the extension can warn when `candidate_count > 1`.
- **Extension:** Request snapshots with required `owner`, `repo`, `number`; optional `sha` and `issue` from captured deep-link params. Call the bridge when `sha` is absent (stop requiring `review_pilot_sha` for the HTTP request). Show a panel warning when the snapshot reports `candidate_count > 1`.
- **Deep links:** Unchanged — review-ticket status and CLI `pr:` lines continue to use `files_changed_url` with `review_pilot_issue` and `review_pilot_sha`. Those parameters disambiguate and pin SHA when present; the relay must honor them when filtering candidates.
- **Tests:** Python unit/integration tests for lookup, tie-break, filters, 404, and auth; extension unit tests for optional `sha` in URL building and panel warning copy.

### Out of scope

- Reading `human-review.json` or triage state (snapshot still lists **all** `findings.json` rows, same as current bridge).
- Multi-port or remote bind; TLS; mDNS discovery.
- Extension allowlist, SHA gate, Prepare, preflight, or selector behavior (except snapshot fetch and new warning UI).
- Index file or database cache (directory scan on each request is acceptable for single-operator scale; optimize later if needed).
- `github.enterprise.com`.

## Definitions

| Term | Meaning |
|------|---------|
| **Candidate** | A tuple `(issue_key, owner, repo, number, sha)` where `reviews/<issue>/prs/<slug>/commits/<sha>/review/findings.json` exists and `findings` is a non-empty JSON array. |
| **Review artifact mtime** | Maximum of `st_mtime` for `findings.json` and, if present, `reviews/<issue>/prs/<slug>/commits/<sha>/review/reviewer-report.md`. Used only to order candidates. |
| **PR identity** | `owner`, `repo`, `number` (integer) matching `parse_pr_ref` / GitHub path. |
| **Snapshot body** | Output of `build_snapshot` in `review_ticket/inline_review.py` after this change (fields may gain resolution metadata). |

## CLI

### Command

```text
review-ticket serve-inline-review [--port PORT]
```

- Reads `reviews_dir` from `.review-ticket.yaml` / config (same as other commands).
- Requires `REVIEW_PILOT_BRIDGE_TOKEN` in the environment of **this** process.
- Prints the listen URL (`http://127.0.0.1:<port>/snapshot`) and blocks until interrupted.
- Does not read or write `session.json`.

### Parser change

`serve-inline-review` is registered **without** a required issue positional argument. The main CLI entry must allow this subcommand to run when `argv` is only `serve-inline-review` (and global flags). Other commands keep `review-ticket <issue> …`.

## HTTP API

### `GET /snapshot`

**Query parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | yes | GitHub owner |
| `repo` | yes | Repository name |
| `number` | yes | Pull request number (decimal integer) |
| `sha` | no | If set, only candidates with this exact 40-hex commit SHA |
| `issue` | no | If set, only candidates under `reviews/<issue>/` |

Malformed `number`, missing `owner`/`repo`/`number`, or empty required fields → **400** `{"error":"bad_request"}`.

Missing or invalid `Authorization` → **401** `{"error":"unauthorized"}`.

Wrong path → **404** `{"error":"not_found"}`.

No matching candidate → **404** `{"error":"not_found","message":"No automated review for {owner}/{repo}#{number}"}` (message is human-readable; exact wording may vary).

Success → **200** JSON object (see [Response shape](#response-shape)).

### Response shape

All fields from today’s snapshot, plus:

| Field | Type | Description |
|-------|------|-------------|
| `candidate_count` | integer | Number of candidates considered after `owner`/`repo`/`number` and optional `issue`/`sha` filters |
| `resolved_issue` | string | Jira issue key for the chosen candidate |
| `resolved_sha` | string | Full SHA for the chosen candidate |
| `resolution` | string | Always `"newest_mtime"` when `candidate_count >= 1` |

Existing fields unchanged: `issue`, `pr`, `owner`, `repo`, `number`, `sha`, `findings`, `summary_block`.

**Note:** Top-level `issue` and `sha` in the snapshot must match the **chosen** candidate (`resolved_issue` / `resolved_sha`), not merely the optional query filters.

When `candidate_count > 1`, the extension must show a non-blocking warning in the side panel (below issue/PR/SHA summary, above the finding list), for example:

> Multiple automated reviews exist for this pull request. Showing the newest on disk ({resolved_issue} @ {short sha}). Open the link from the ticket you are reviewing to pin issue and SHA.

### Resolution

1. Enumerate all issue directories under `reviews_dir` (directory names that pass `require_issue_key` or equivalent validation).
2. For each issue, locate `prs/{owner}-{repo}-pr-{number}/commits/*/review/findings.json`.
3. Keep paths where `findings` is a non-empty array.
4. Apply filters:
   - If `issue` query present → keep only that issue key.
   - If `sha` query present → keep only that SHA (must satisfy `is_full_sha`).
5. If zero rows → 404.
6. If one or more rows → pick the row with maximum **review artifact mtime**. Ties (same mtime) break by lexicographic order of `(issue_key, sha)` descending so the result is deterministic.
7. Build snapshot via `snapshot_for_store` / `build_snapshot` for the winning row.

The bridge does **not** compare GitHub’s live HEAD to stored SHA; the extension SHA gate still uses snapshot `sha`.

## Extension behavior changes

### Snapshot request

`planSnapshotRequest` (and `buildSnapshotUrl`):

- Require captured PR identity (`owner`, `repo`, `number`) and settings token/port.
- Add `issue` query param when `captured.issue` is non-empty.
- Add `sha` query param when `captured.sha` is non-empty.
- **Do not** fail with `missing-sha` solely because `review_pilot_sha` was stripped; still call the bridge without `sha` when absent.

`missing-sha` may remain only if the panel needs a reviewed SHA for **Prepare** after load (SHA gate uses snapshot `sha` from the response). If the gate can run on `snapshot.sha`, remove `missing-sha` as a pre-fetch blocker.

### Panel

- When `candidate_count > 1`, render the warning defined above.
- When bridge returns 404 `not_found`, keep existing blocked copy (“no snapshot for this pull request and reviewed SHA” — update message to “No automated review found for this pull request” when sha was not part of the request).
- Idle / allowlist / unauthorized behavior unchanged.

## Review-ticket UI and links

No new screen is required.

- **Status document** and PR list markdown links continue to use `pr_url_for_ref` → `files_changed_url` when a full stored SHA exists.
- Operators should prefer those links so `review_pilot_issue` and `review_pilot_sha` narrow candidates to one row when possible.

Optional follow-up (not required for this bundle): print full Files changed URLs in `run-review` success output for every tracked PR.

## Security

Unchanged from [inline-reviewer-browser spec](../plans/inline-reviewer-browser/spec.md):

- Token only in bridge env and extension storage; never in GitHub URLs or page DOM.
- Loopback bind only.
- Allowlist gates whether the extension calls the bridge at all.

The global lookup exposes **any** matching review under `reviews_dir` to a holder of the bridge token. That matches the single-operator threat model.

## Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| R1 | One `serve-inline-review` command with no issue argument | Operator runs one daemon across tickets |
| R2 | Remove per-issue serve and `--pr` / `--sha` on serve | No deprecated path; active development |
| R3 | Lookup by `owner` + `repo` + `number` across all issues | Matches extension identity from GitHub URL |
| R4 | Optional `issue` and `sha` query params | Deep link pins; manual GitHub navigation still works |
| R5 | Newest by review artifact mtime when multiple candidates | Operator choice 2026-10-19 |
| R6 | `candidate_count > 1` → panel warning | Surfaces ambiguity without blocking |
| R7 | Non-empty `findings` array required | “Automated review” means agent output exists |
| R8 | Snapshot JSON shape backward compatible except new metadata fields | Extension and tests can adopt incrementally |

## Acceptance criteria

1. `review-ticket serve-inline-review` starts on 127.0.0.1 without an issue key; `review-ticket DOTNETIOT-2550 serve-inline-review` is not a valid invocation (parser error or unknown command).
2. With reviews for Zuul #156, KT.IoT #144, and UI.Admin #354 under one or more issues, a single bridge process returns **200** for each PR’s `GET /snapshot?owner=…&repo=…&number=…` with the correct findings count per commit.
3. When two candidates exist for the same PR (fixture: two issue dirs, same `owner/repo#number`, different SHAs, both with `findings.json`), request without `sha` returns the newer mtime and `candidate_count: 2`.
4. When `issue` and `sha` query params match one candidate, `candidate_count` is 1 and no warning is shown in the extension panel.
5. Request for a PR with no `findings.json` returns **404** with `error: not_found`.
6. Missing or wrong Bearer token returns **401**.
7. Extension on an allowlisted repo loads findings when the GitHub URL has no `review_pilot_sha` but disk has a review for that PR (newest wins; warning if `candidate_count > 1`).
8. Extension behavior for SHA gate, Prepare, and allowlist unchanged when deep link includes full `review_pilot_issue` and `review_pilot_sha`.
9. `pytest` covers lookup, mtime ordering, filters, and HTTP handler; `node --test` in `extensions/inline-reviewer` covers URL building and panel warning rendering.

## Verification plan

- **Fixtures:** Temporary `reviews/` tree with two issues, one PR, two SHAs; assert winner by touching `findings.json` mtime.
- **Regression:** DOTNETIOT-2550-style triple in workspace (if present in dev env) manual smoke — one bridge, three tabs.
- **Docs:** Update `extensions/inline-reviewer/README.md` — global serve, lookup rules, warning, remove issue-scoped serve examples.

## Implementation map (outline)

| Area | Touchpoints |
|------|-------------|
| Lookup | New `find_review_candidates` / `resolve_snapshot` in `review_ticket/inline_review.py` (or `review_ticket/inline_review_lookup.py`) |
| Server | `serve_inline_review(store, port)` — `load_snapshot` calls resolver, no identity equality check |
| CLI | `review_ticket/cli.py` — top-level or issue-optional parser branch for `serve-inline-review` |
| Extension | `lib/snapshot-request.js`, `lib/panel-model.js`, side panel render |
| Tests | `tests/test_inline_review.py` (expand), extension tests |

## Deferred

- Persisted index (`reviews/.inline-index.json`) for large trees.
- `GET /snapshot/candidates` debug endpoint listing all matches without building full snapshot.
- Prefer candidate whose SHA equals GitHub `head-commit-link` when mtime ties.
