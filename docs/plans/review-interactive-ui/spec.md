# Interactive review attach

Status: **approved** — 2026-10-17. From operator retro interview; mapped in [implementation.md](implementation.md).

## Source

- Bundle: [README](README.md)
- Retro: [retro.md](retro.md) — investigations: borrow Foundry’s UI not the product; scrollable narrative; accept/reject with color and buttons; presentation-only scope; TUI vs REPL naming; information, questions, and PR feedback

## Operator outcome

From `review-ticket <issue> review attach`, the operator sees the status of the review in the terminal, opens one pull request’s agent output, and accepts, rejects, reclassifies, or edits findings against the commit that was reviewed. The screen uses color, a scrollable document, and buttons. It does not depend on Foundry.

## Problem statement

`review interactive` is a line REPL that reprints a text list. Docs already call it a TUI. Long reviewer output, per-finding explanations, and multi-PR status are easier to read in a stable document with obvious actions. Reviews are stored per commit under `reviews/<issue>/prs/<slug>/commits/<sha>/`, and later pushes must not be treated as the reviewed snapshot.

## Scope

### In scope

- A Textual app launched by `review-ticket <issue> review attach`.
- A status screen built only from local session and commit files.
- A per-PR review screen: finding index, scrollable agent narrative and selected finding, inline explanation edit, and the current triage actions.
- Binding every review view to the commit directory that holds that review.
- Removing the `review interactive` command and `run_interactive_triage` REPL loop.
- Docs that describe `review attach` as the interactive review UI.

### Out of scope

- Foundry as a library, host socket, run list, or workflow engine.
- Changing decision values (`accept` / `reject`), must-fix, summary, event, or reject-automated-review.
- Starting `run-review`, `pr select`, publish, testing-notes prompts, or `authorize` from this UI.
- Live GitHub or Jira refresh inside attach.
- Chat-style Q&A, or a new question protocol.
- File triage fallback removal: `review apply` flags and `review apply --file` stay.

## Decisions

| ID | Decision | Rationale | Retro link |
|----|----------|-----------|------------|
| D1 | Textual is required. No REPL fallback. | Operator wants Foundry-shaped buttons and scroll as the only interactive UI. | Borrow Foundry’s UI, not the product |
| D2 | Two screens: status document, then a PR review screen opened from a PR row. | Status should stay clear at any step; triage happens per PR. | Integrating information, questions, PR feedback |
| D3 | Status content is local: step summary, stored check/build results, PR list, links, and whether a review exists for the stored SHA. | Operator asked for a review-status document, then local files only. | Scrollable narrative; status-sources |
| D4 | PR screen layout is a compact finding index plus one detail pane. | Matches Foundry’s scroll plus action panel without a single long dump. | Scrollable narrative |
| D5 | Inline explanation edit ships in this version and writes the same explanation override as today. | Operator asked for edit in this version. | Integrating information, questions, PR feedback |
| D6 | Actions stay accept, reject, must-fix, edit explanation, edit summary, edit event, reject automated review, save, and close. | Do not change the human-review model yet. | Accept / reject with color and buttons |
| D7 | Command name is `review attach`. | Borrow the Foundry word; replace the REPL command. | Naming mismatch — **superseded:** [tui-end-to-end-return/spec.md](../tui-end-to-end-return/spec.md) renames the entry to `review-ticket <issue> attach`. |
| D8 | The open review is the snapshot under `commits/<sha>/`, not the branch tip. | Artifacts and publish are already SHA-scoped. | Operator follow-up on future commits |
| D9 | If `session.json` `pr_shas` for that PR is a different SHA than the snapshot on screen, show that this review is not the stored commit and that publish will refuse until a new `run-review`. Attach does not run it. | Stale chrome without a network call. | sha-chrome |
| D10 | Delete `review interactive`. | Operator chose removal. | repl-fate |
| D11 | Attach performs no GitHub or Jira calls. | Head comparison uses stored SHAs and on-disk commit directories only. | head-refresh |
| D12 | Opening a PR does not change `active_pr` or `active_sha`. | Viewing or saving one snapshot must not retarget the session. | Scope: presentation only |

## Assumptions

- Textual is a required project dependency, not an extra.
- Non-TTY invocation of `review attach` fails with an error that points at `review apply --file`. It does not start a REPL.
- Save still requires every finding to be accept or reject, or an explicit reject of the automated review, and still writes `human-review.json` through the existing human-review document shape.
- An existing `human-review.json` still requires `--revise` before it can be replaced.
- “Stored head” means `pr_shas` in `session.json`. Attach does not discover a newer GitHub HEAD by itself.
- Check/build rows come from the stored readiness payload for that SHA (including `github-checks.json` when present).

## Acceptance criteria

1. `review-ticket <issue> review attach` opens a Textual status screen. `review interactive` is not a command.
2. The status screen shows, from local files: issue key, current step, last completed step, outcome, and next command; a check/build table for each active PR’s stored SHA; one row per active PR with repo, number, stored SHA, a link-style control, and review progress (no snapshot, undecided, or human review already recorded).
3. The status screen does not call GitHub or Jira. Quitting it does not write `session.json`.
4. Choosing a PR opens a second screen for that PR’s stored SHA. The session’s `active_pr` and `active_sha` stay unchanged.
5. If that SHA has no `findings.json`, the PR screen says there is no review for this commit and offers no accept/reject actions and no way to start `run-review`.
6. If a review snapshot exists under a different commit directory than `pr_shas` for that PR, the screen shows both SHAs, states that the open review is not the stored commit, and states that publish will refuse until `run-review` is run for the stored SHA.
7. When a snapshot exists, the PR screen shows a finding index and a scrollable detail pane containing the reviewer narrative and the selected finding’s explanation and suggested change. Header chrome shows issue, PR, reviewed SHA, and the same publish preview counts the triage state already computes.
8. Buttons perform the current transitions: accept, reject, must-fix, edit explanation in the detail pane, edit summary, edit event, reject automated review, save, and close. Labels may be words; they do not introduce accept/amend/ignore.
9. Save writes `human-review.json` for the snapshot SHA only when the current save rules pass. Close returns to the status screen without writing. A second save without `--revise` is refused when a human review is already recorded.
10. After a successful save, the status row for that PR shows that a human review is recorded for that SHA.
11. `review apply` flags and `review apply --file` still produce the same human-review document as before.
12. README and the review-preview copy no longer call the REPL an interactive TUI. They name `review attach` and keep file triage as the non-interactive path.

## Verification plan

- Unit tests stay on the triage state transitions and `human_document_from_state`.
- Headless Textual tests cover: status render from a fixture session with three PRs; open PR; stale SHA banner when `pr_shas` and the snapshot directory differ; save and close; `--revise` required.
- CLI test: `review interactive` is rejected; `review attach` on a non-TTY exits with the file-triage hint.
- Manual: `review-ticket DOTNETIOT-2550 review attach` on Windows Terminal — status table, open one PR, scroll a long explanation, accept or reject, edit explanation, save, return, and confirm `human-review.json` matches a fixture produced by the old command sequence.

## Implementation hints

- New package `review_ticket/tui/` for the Textual app. Keep `TriageState`, `human_document_from_state`, and load-from-`findings.json` as the domain core. Drive them from widgets instead of `process_triage_command` strings.
- Delete `run_interactive_triage` and the `review interactive` parser once tests call the state helpers directly.
- Status data is a read-only projection of `session.json`, `pr_shas`, `github-checks.json`, and each `commits/<sha>/review/` tree.
- Theme and layout may follow Foundry attach (`VerticalScroll`, markdown body, button row) by copying patterns, not importing Foundry.

## Deferred / follow-up

- Accept / amend / ignore as a new vocabulary.
- Live head refresh inside attach.
- Collapsible diff hunks in the detail pane.
- Testing-notes and publish-authorize screens in the same visual language.
- A commit-history browser beyond “stored SHA versus snapshot SHA.”
