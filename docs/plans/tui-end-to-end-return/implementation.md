# TUI end-to-end return for missing testing notes — implementation map

Status: **ready for orchestration** — companion to [spec.md](spec.md). Canonical map for implementer assignment and verifier checklists. Refresh with `/spec-implementation-map @spec.md` after material spec or code changes.

## Spec alignment

### Strengths (spec)

- D1–D8 and AC 1–11 are closed. Out of scope keeps Foundry, live refresh on status and PR triage, `run-review`, publish authorize, and non-testing-notes returns out of this slice.
- The verification plan already splits parser tests, workflow integration, headless Textual tests with a mocked Jira refresh, and one manual pass.
- Hints match code that already exists: `decide_notes`, `_write_return_draft`, `refresh_issue`, `jira_comment`, and `jira_transition` are the mutation core. The Textual app is already one process with a status screen and a PR screen.

### Strengths (repository)

- `review-ticket <issue> review attach` already starts [ReviewTicketApp](../../../review_ticket/tui/app.py), which pushes [StatusScreen](../../../review_ticket/tui/status_screen.py). [PrReviewScreen](../../../review_ticket/tui/pr_screen.py) already refuses triage when `findings.json` is missing and refuses a second save unless `--revise` was passed in. Textual is a main dependency (`textual>=0.47.0`).
- Missing notes are already detected in [step_jira](../../../review_ticket/workflow.py). Empty `testing_notes` writes `return-comment.md` and sets `next_command` to `notes --reject`. A recorded reject points at `jira comment --body-file … --yes` and recommends `config.in_progress_status`. Notes that are present and undecided point at `notes --accept`. Accept is not offered when the body is empty.
- [decide_notes](../../../review_ticket/workflow.py) records `decisions.testing_notes` (`choice`, `notes`, `notes_hash`, `at`), and on reject sets `session["return_draft"]` via [_write_return_draft](../../../review_ticket/workflow.py). [return_comment](../../../review_ticket/reports.py) is the body template. [put_decision](../../../review_ticket/workflow.py) already enforces `--revise` when the choice changes.
- [jira_comment](../../../review_ticket/workflow.py) and [jira_transition](../../../review_ticket/workflow.py) already preview, journal, and skip a repeat of the same successful fingerprint. [authorize](../../../review_ticket/authorize.py) treats `yes=True` as approved. [refresh_issue](../../../review_ticket/workflow.py) rewrites `issue.json` and `issue-report.md`. Description and testing notes are already plain text from ADF ([normalize path](../../../review_ticket/adapters.py)). The browse URL is `issue["url"]` via [jira_browse_url](../../../review_ticket/adapters.py).
- Headless screen tests already use `App.run_test()` in [test_tui_status.py](../../../tests/test_tui_status.py) and [test_tui_pr.py](../../../tests/test_tui_pr.py). CLI attach tests are in [test_interactive_triage.py](../../../tests/test_interactive_triage.py).

### Gaps and clarifications before build

| Topic | Present state | Spec requirement | Suggested resolution |
|-------|---------------|------------------|----------------------|
| Attach spelling and entry guard | Parser registers `review attach` only. [run_review_attach](../../../review_ticket/cli.py) calls `_require_review_session` → `_require_identity`, then refuses to open if `human-review.json` exists without `--revise`. | D1–D3, AC 1–2. Sole command is `review-ticket <issue> attach`. Open when `session.json` exists and `active_pr` / `active_sha` are absent. PR screen behavior stays. | Add top-level `attach` (keep `--revise`). Delete the `review attach` subparser. Open only if `session.json` is already on disk; do not call `ensure_session`. Do not call `_require_identity`. Drop the pre-app `human-review.json` check; the PR screen already enforces `--revise` on save. |
| Missing session | `ensure_session` creates `session.json`. | AC 2 assumes the file exists. The missing-file case is unspecified. | `WorkflowError`: no session yet; run `review-ticket <issue>` first. Do not start Textual. |
| Non-TTY copy | Error names `review attach` and points only at `review apply --file`. | Assumption: non-TTY fails and points at non-interactive CLI paths. | Mention `notes`, `jira comment` / `jira transition`, and `review apply --file`. Exit 2. Do not start Textual. |
| When the notes screen appears | Status is the only screen. No testing-notes view. | Scope leaves auto-present vs a status entry as an implementation choice. The operator must land on the review UI without selecting a PR. | Auto-push the testing-notes screen when `current_step` is `jira-issue` and the testing-notes decision is absent or `reject` (comment or transition not finished). Escape or an explicit back returns to status. Other steps stay on status with `next_command` only. |
| Stdin prompt inside the TUI | [step_jira](../../../review_ticket/workflow.py) calls `_prompt_notes` when `app.interactive` is true, notes are non-empty, and no decision is stored. Attach on a TTY sets `interactive=True`. | D4: Accept/Reject are Textual controls. | Do not call `resume` / `step_jira` to paint the screen. Read the session and call `refresh_issue`. Call `resume` only after `decisions.testing_notes` is stored, so the stdin prompt does not run. |
| Edited return body vs `decide_notes` | `decide_notes(..., "reject")` always rewrites `return-comment.md` from a fixed reason plus the `--notes` string. `step_jira` may already have written a different reason (`No testing notes were found…` vs `missing or not adequate…`). | AC 6: the TextArea is the return body; Save persists that body and the same session artifacts as `notes --reject`. | Prefill from existing `return-comment.md` when `step_jira` wrote it; otherwise `return_comment(...)`. Add an optional draft-body argument on the reject path of `decide_notes` (CLI omit = today’s template). TUI Save passes the TextArea text so a later `resume` does not regenerate the file. `step_jira`’s reject branch already keeps `session["return_draft"]` and does not rewrite it. |
| Accept when notes are empty | `step_jira` never offers `notes --accept` for an empty body. | Assumption: Accept is hidden or disabled; Reject is the path for DOTNETIOT-2099. | Hide Accept when refreshed `testing_notes` is empty. Show both when the body is non-empty and no decision is stored. |
| Controls after a decision | `put_decision` rejects a different choice unless `revise=True`. | AC 5: Accept/Reject become non-interactive after save. Assumption: an existing decision follows CLI `--revise`. | Disable both buttons after a successful save. Top-level `--revise` re-enables them and is passed through to `put_decision`, same as `notes --revise`. The PR screen keeps its own use of that flag. |
| Post preview and target status | `authorize` prompts on stdin. `jira_comment` then `finish` sets `recommendation` to null. Transition status on the CLI comes from `config.in_progress_status`, which `step_jira` had copied into `recommendation` before the comment. | D6, AC 7–8: TUI Approve/Deny is the authorization. Transition uses the workflow in-progress status. Deny changes nothing. | Show the same preview strings `jira_comment` / `jira_transition` would print. Approve calls those functions with `yes=True` and the saved `return-comment.md`. Transition status is `config.in_progress_status`, not the post-comment `recommendation`. Deny does not call them. Idempotent “already posted” still advances the UI to the next authorize step. |
| After a successful transition | `jira_transition` leaves `current_step` as-is and sets `last_completed_step` to `disposition` (existing CLI). The spec does not name a landing screen. | D8: stay in the one app. | Pop to the status screen and reload. Do not add a third summary screen. Do not change `jira_transition`’s session write. |
| Handoffs still say `review attach` | `next_command` in `step_publication` and after automated review, `_review_chain_hint`, [review_preview](../../../review_ticket/reports.py), [README](../../../README.md), and [operator-guide.md](../multi-pr-reviewer-integration/operator-guide.md). Tests assert that string. [review-interactive-ui spec D7](../review-interactive-ui/spec.md) still names `review attach`. | AC 1: `review attach` is not a command. AC 11: README documents early return through `attach`. | Point those handoffs at `review-ticket <issue> attach`. Add a one-line superseded note on review-interactive-ui D7. Leave that spec’s historical AC text in place. |

### Acceptance criteria traceability

| AC | Present | Delta / work |
|----|---------|----------------|
| 1 | `review attach` is the only Textual command. Top-level `attach` is an argparse error. | **P1**, **P5** — register `<issue> attach`; delete `review attach`; update handoff copy and tests. |
| 2 | Attach raises “Run the review entry point first” when `active_pr` or `active_sha` is missing. | **P1** — open the status screen from an existing `session.json` with no PR identity. |
| 3 | No testing-notes screen. Early tickets never reach the app. | **P2** — auto-present the notes screen at `jira-issue` without `run-review`. |
| 4 | `refresh_issue` and `issue-report.md` exist. The TUI never calls them. Status and PR screens do not fetch Jira. | **P2** — refresh on notes-screen open; link, description, and testing-notes panes. |
| 5 | Decision is `notes --accept` / `notes --reject` on the CLI. | **P2**, **P3** — Reject control; both controls disabled after save. |
| 6 | `_write_return_draft` runs inside `decide_notes` and overwrites the file from a template. | **P3** — TextArea, focus, Save of the edited body plus the same decision fields and `return_draft`. |
| 7 | `jira comment` authorizes on stdin or `--yes`. | **P4** — Post Approve/Deny in the TUI; Approve calls `jira_comment` on the saved draft. |
| 8 | `jira transition` is a second CLI command. | **P4** — second Approve/Deny after a successful post; status is `in_progress_status`. |
| 9 | `decide_notes` accept advances via `resume`. The TUI never calls it. | **P3** — Accept returns to the status screen with the updated step and `next_command`. |
| 10 | PR screen already blocks actions with no snapshot and does not change `active_pr` / `active_sha`. Entry still requires identity. | **P1** — leave [pr_screen.py](../../../review_ticket/tui/pr_screen.py) behavior; only the entry guard changes. |
| 11 | README command table and step 5 say `review attach`. The early return is the three CLI commands. | **P5** |

---

## Repository layout

The CLI in [cli.py](../../../review_ticket/cli.py) dispatches `review attach` to `run_review_attach`, which refuses to start unless a PR and SHA are selected. The Textual shell is [tui/app.py](../../../review_ticket/tui/app.py). Testing-notes detection, the return draft, and Jira mutations live in [workflow.py](../../../review_ticket/workflow.py). There is no testing-notes screen.

| Path | Role |
|------|------|
| [review_ticket/cli.py](../../../review_ticket/cli.py) | `build_parser`, `run_review_attach`, `notes` / `jira` dispatch |
| [review_ticket/tui/app.py](../../../review_ticket/tui/app.py) | `ReviewTicketApp`; mounts `StatusScreen` |
| [review_ticket/tui/status_screen.py](../../../review_ticket/tui/status_screen.py) | Read-only status; PR rows open the review screen |
| [review_ticket/tui/pr_screen.py](../../../review_ticket/tui/pr_screen.py) | Snapshot triage; empty state and `--revise` save gate |
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | `step_jira`, `decide_notes`, `refresh_issue`, `jira_comment`, `jira_transition`, `_require_identity` |
| [review_ticket/authorize.py](../../../review_ticket/authorize.py) | Preview plus `--yes` or stdin |
| [review_ticket/reports.py](../../../review_ticket/reports.py) | `return_comment`, `testing_notes_decision_preview`, `issue_report` |
| [review_ticket/adapters.py](../../../review_ticket/adapters.py) | Normalized `description`, `testing_notes`, browse `url` |
| [tests/test_interactive_triage.py](../../../tests/test_interactive_triage.py) | Non-TTY and TTY attach CLI tests |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | Headless status screen |
| [README.md](../../../README.md) | Command table and the Jira / human-review steps |

---

## Workstreams mapped to decisions

### D1, D2 — `review-ticket <issue> attach` replaces `review attach`

**Present:** `attach` is only under the `review` subparser. `run_review_attach` requires a TTY, then identity, then refuses a recorded human review.

**Required:** One spelling on the issue parser. `review attach` is an argparse error. `--revise` remains and still reaches the PR screen.

| Resource | Role |
|----------|------|
| [cli.py](../../../review_ticket/cli.py) | Register `attach`; delete `review`’s attach parser |
| [test_interactive_triage.py](../../../tests/test_interactive_triage.py) | Parser and non-TTY coverage |

**Risks:** Handoff strings and tests still emit `review attach` until P5. Shipping P1 alone makes those strings point at a removed command.

### D3 — Open from `session.json` only

**Present:** `_require_identity` raises when `active_pr` or `active_sha` is missing. The PR screen separately refuses actions when the snapshot has no `findings.json`.

**Required:** Attach starts. The status screen shows. The PR screen’s snapshot and save rules stay as they are.

| Resource | Role |
|----------|------|
| [workflow.py](../../../review_ticket/workflow.py) | `_require_identity` stays for review commands; attach stops calling it |
| [pr_screen.py](../../../review_ticket/tui/pr_screen.py) | Unchanged empty state and save refusal |

**Risks:** Calling `ensure_session` would create a session the operator did not ask for. Read the file; do not create it.

### D4, D5, D8 — Testing-notes screen in the same app

**Present:** `refresh_issue` writes the normalized issue. `issue_report` already lays out description and testing notes as markdown text. The app never shows them. `testing_notes_decision_preview` is the CLI decision prompt, not the Jira return body.

**Required:** On open, refresh from Jira. Show a link, a scrollable description, and a scrollable testing-notes body. Accept/Reject when the workflow still wants a decision. One Textual app.

| Resource | Role |
|----------|------|
| [workflow.py](../../../review_ticket/workflow.py) `refresh_issue` | Live issue fields |
| [adapters.py](../../../review_ticket/adapters.py) | `url`, `description`, `testing_notes` |
| New `review_ticket/tui/testing_notes_screen.py` | The screen |

**Risks:** `resume` before a decision can block on `_prompt_notes`. Refresh is a live `acli` call; tests must script the runner.

### D4, D6 — Reject draft, post, then transition

**Present:** Reject draft and the two mutations are three CLI commands. `authorize` reads stdin.

**Required:** Reject shows a focused TextArea. Save writes the edited body and the decision. Then Post Approve/Deny, then Transition Approve/Deny. Deny leaves the session unchanged.

| Resource | Role |
|----------|------|
| [decide_notes](../../../review_ticket/workflow.py) | Decision record; needs a draft-body override |
| [jira_comment](../../../review_ticket/workflow.py) / [jira_transition](../../../review_ticket/workflow.py) | Called with `yes=True` after the TUI approves |
| [authorize.py](../../../review_ticket/authorize.py) | Unchanged stdin path for the CLI |

**Risks:** A naive `decide_notes` reject call discards the operator’s edit. `jira_comment` clears `recommendation`; the transition target must be `config.in_progress_status`.

### D7 — Accept returns to status

**Present:** `decide_notes(..., "accept")` then `resume` completes `jira-issue` and continues the workflow. The TUI does not call it.

**Required:** Accept records that decision and the status screen shows the new `current_step`, outcome, and `next_command`.

| Resource | Role |
|----------|------|
| [decide_notes](../../../review_ticket/workflow.py) | Accept path can call it directly |
| [status_screen.py](../../../review_ticket/tui/status_screen.py) | Reload on resume |

**Risks:** `resume` after accept may call GitHub. That is the existing `notes --accept` behavior. The screen test should stub the runner so the workflow can pass the Jira gate and stop at the next local gate.

---

## Orchestration packages

| ID | Title | Surfaces | Depends on | Primary paths | Verify (AC / tests) |
|----|-------|----------|------------|---------------|---------------------|
| P1 | Top-level `attach` without a PR/SHA guard | cli-ui, code | — | [cli.py](../../../review_ticket/cli.py) | AC 1 (parser), AC 2, AC 10; `tests/test_interactive_triage.py` |
| P2 | Testing-notes screen: refresh, link, bodies, choices | cli-ui, code | P1 | `review_ticket/tui/testing_notes_screen.py`, [app.py](../../../review_ticket/tui/app.py) | AC 3, AC 4, AC 5 controls; new headless test |
| P3 | Reject TextArea save and Accept → status | cli-ui, code | P2 | [workflow.py](../../../review_ticket/workflow.py) `decide_notes`, notes screen | AC 5, AC 6, AC 9 |
| P4 | Post and transition authorize | cli-ui, code | P3 | notes screen, `jira_comment`, `jira_transition` | AC 7, AC 8 |
| P5 | Docs and handoffs name `<issue> attach` | docs | P1 | [README.md](../../../README.md), [reports.py](../../../review_ticket/reports.py), [workflow.py](../../../review_ticket/workflow.py) hints, operator guide | AC 1 docs/tests, AC 11 |

### Package briefs (for implementer agents)

#### P1 — Top-level `attach` without a PR/SHA guard

- **Goal:** `review-ticket <issue> attach` opens the existing Textual app whenever `session.json` exists. `review attach` is gone. No pull request or SHA is required to see status.
- **Deliverables:** Issue-level `attach` with `--revise`. Delete the `review` subparser’s `attach` command and the `review_cmd == "attach"` branch. Entry reads `session.json` and does not call `ensure_session` or `_require_identity`. Remove the pre-app `human-review.json` refusal. Non-TTY `WorkflowError` names `notes`, `jira comment` / `jira transition`, and `review apply --file`. Pass `store`, `issue`, `workflow_app`, and `revise` into `ReviewTicketApp` as today. Missing session is an error that tells the operator to run `review-ticket <issue>` first.
- **Out of scope:** Testing-notes widgets, Jira calls, changing `PrReviewScreen`, renaming `next_command` strings (P5).
- **Touchpoints:** [cli.py](../../../review_ticket/cli.py) `build_parser`, `dispatch`, `run_review_attach`. [test_interactive_triage.py](../../../tests/test_interactive_triage.py).

#### P2 — Testing-notes screen: refresh, link, bodies, choices

- **Goal:** At the `jira-issue` gate, attach shows the ticket, the description, and the testing notes, with Accept/Reject when a decision is still open.
- **Deliverables:** New screen. On open, call `refresh_issue` (not `resume`). Render the browse URL as an openable link (`issue["url"]` / `_jira_url`). Scrollable Markdown for `description` and for `testing_notes` (the normalized team-notes body, not the full comment list). Hide Accept when `testing_notes` is empty; show Reject. `ReviewTicketApp.on_mount` pushes this screen when `current_step` is `jira-issue` and the testing-notes decision is absent or `reject`. Back returns to status. Do not refresh Jira from status or the PR screen.
- **Out of scope:** Save, TextArea, `jira_comment`, `jira_transition`, publish.
- **Touchpoints:** [app.py](../../../review_ticket/tui/app.py), new testing-notes screen, [workflow.py](../../../review_ticket/workflow.py) `refresh_issue` only.

#### P3 — Reject TextArea save and Accept → status

- **Goal:** Reject lets the operator edit the return body and save it the way `notes --reject` records a decision. Accept advances the workflow and shows status.
- **Deliverables:** Reject mounts a `TextArea` focused immediately, prefilled from `return-comment.md` if that file exists, otherwise from `return_comment`. Tab reaches Save. Save writes `decisions.testing_notes` in the same shape as `decide_notes` (`choice`, `notes`, `notes_hash`, `at`), sets `return_draft`, and writes the TextArea text to `return-comment.md`. Optional draft body on `decide_notes` reject so the CLI template stays the default and the TUI body is not regenerated. Then `resume`. Accept and Reject are disabled after save. `--revise` allows a new choice, matching `put_decision`. Accept calls `decide_notes(..., "accept")` and pops to status, which reloads `current_step`, outcome, and `next_command`. Empty notes never show Accept.
- **Out of scope:** Posting or transitioning (P4). Other return reasons.
- **Touchpoints:** `decide_notes`, `_write_return_draft`, `return_comment`, notes screen, [status_screen.py](../../../review_ticket/tui/status_screen.py) reload.

#### P4 — Post and transition authorize

- **Goal:** After a saved reject draft, the operator approves or denies the Jira comment, then approves or denies the transition to in progress, without leaving the app.
- **Deliverables:** Post panel with the comment preview (`Comment on {issue}.` plus the saved body) and Approve / Deny. Approve calls `jira_comment` with the saved body file and `yes=True`. After success or an idempotent “already posted” result, show Transition with preview `Transition {issue} to {status}.` and Approve / Deny. Status is `workflow_app.config.in_progress_status`. Approve calls `jira_transition` with `yes=True`. Deny on either step does not call the mutation and leaves session files unchanged; the operator can edit the TextArea, Save again, and retry. After a successful transition, pop to status and reload. Do not change CLI `authorize` stdin behavior.
- **Out of scope:** `publish-review` authorize, analyzer returns, disposition.
- **Touchpoints:** notes screen, [jira_comment](../../../review_ticket/workflow.py), [jira_transition](../../../review_ticket/workflow.py).

#### P5 — Docs and handoffs name `<issue> attach`

- **Goal:** Operator-facing copy and generated next commands use `review-ticket <issue> attach` and describe the early testing-notes return inside that session.
- **Deliverables:** README command table, Jira step, and human-review step. Early-return story: attach, review notes, reject, post, transition — the three CLI commands remain available and are not the primary story. Update `step_publication` and post-`run-review` `next_command`, `_shows_review_handoff`, and `_review_chain_hint`. Update the `review_preview` footer. Update [operator-guide.md](../multi-pr-reviewer-integration/operator-guide.md) chain steps. One-line note on [review-interactive-ui spec D7](../review-interactive-ui/spec.md) that [this spec](spec.md) supersedes the command name. Fix tests that assert `review attach` as a command or next step: [test_acceptance.py](../../../tests/test_acceptance.py), [test_regression_multi_pr.py](../../../tests/test_regression_multi_pr.py), [test_status_projection.py](../../../tests/test_status_projection.py), [test_tui_status.py](../../../tests/test_tui_status.py).
- **Out of scope:** Rewriting the review-interactive-ui AC list or its implementation map.
- **Touchpoints:** README, reports, workflow hint strings, operator guide, those tests.

### Verifier briefs

#### P1 — verification

- **Must prove:** `review-ticket <issue> attach` is accepted and `review-ticket <issue> review attach` exits 2 as an invalid choice. A session with no `active_pr` and no `active_sha` opens `StatusScreen`. A missing `session.json` does not create one and does not start Textual. Non-TTY exits 2 and the message names a non-interactive path. Opening a PR row with no snapshot still shows the existing empty state and no triage actions.
- **Commands / probes:** Extend [test_interactive_triage.py](../../../tests/test_interactive_triage.py). Headless app test with a session fixture that has only `jira-issue` fields. Re-run one existing [test_tui_pr.py](../../../tests/test_tui_pr.py) empty-snapshot test unchanged.
- **Regression watch:** `review show` and `review apply` still parse. `publish-review` still requires identity. Quit on status still does not rewrite `session.json` ([test_tui_status.py](../../../tests/test_tui_status.py)).

#### P2 — verification

- **Must prove:** A `jira-issue` session with empty testing notes opens the notes screen without `run-review` and without `active_sha`. The screen shows the browse URL, the description text, and the testing-notes text returned by the mocked `refresh_issue`. Accept is absent or disabled when notes are empty. Reject is present. Status and PR screens do not call the Jira runner.
- **Commands / probes:** New headless test. Script the runner so `refresh_issue` returns a fixed `issue.json`. Assert Markdown sources and that `session.json` has no `testing_notes` decision yet.
- **Regression watch:** A session whose `current_step` is `human-review` still lands on status, not the notes screen. PR triage buttons still work on a snapshot fixture.

#### P3 — verification

- **Must prove:** Reject shows a TextArea whose initial text matches the missing-notes `return-comment.md` (or `return_comment` when that file is absent) and focus is on that widget. Editing the text and Save writes that exact text to `return-comment.md`, sets `return_draft`, and stores `decisions.testing_notes.choice == "reject"` with a `notes_hash` of the refreshed testing notes. Accept/Reject are disabled. A second Save without `--revise` does not switch the choice to accept. With non-empty notes, Accept updates the session the way `decide_notes` accept does, and the visible screen is status with the new `current_step` and `next_command`.
- **Commands / probes:** Headless Textual pilot: Reject, set TextArea text, Save, read `session.json` and `return-comment.md`. Separate case with notes present and a runner that lets `resume` finish the Jira gate. Compare the decision object to a `decide_notes` reject/accept fixture, allowing the draft file bytes to be the edited text rather than the template.
- **Regression watch:** CLI `notes --reject` with no draft override still writes the template. `notes --accept` tests, if any, still advance. `put_decision` revise errors stay.

#### P4 — verification

- **Must prove:** After save, Approve on post calls the comment mutation once and records a success journal entry for that body. Deny does not call it and does not change `actions.json` or `session.json`. A second Approve of the same body does not post again. After a successful post, the transition panel shows `in_progress_status`. Approve calls `jira_transition` once. Deny leaves the issue untransitioned. After success, status is visible again.
- **Commands / probes:** Headless pilot with a scripted runner that records `acli` comment and transition argv. Assert preview text contains the saved body before Approve. Assert Deny leaves the action log empty.
- **Regression watch:** CLI `jira comment --yes` and `jira transition --yes` still authorize without a TUI. A failed tool result surfaces as `BLOCKED` and does not show the transition panel as successful.

#### P5 — verification

- **Must prove:** README documents `review-ticket <issue> attach` for the early return and for human triage. It does not list `review attach` as a command. Generated `next_command` after automated review and the chain hint use `attach` with no `review` token before it. `review-preview.md` footer matches. Operator guide steps match. Search of tests finds no assertion that `review attach` is a valid command.
- **Commands / probes:** `pytest` on the acceptance, regression, status-projection, and TUI status tests that currently expect `review attach`. Grep README and the operator guide.
- **Regression watch:** `review apply` and `import-review` remain in the chain when the reviewer command is unset. The early-return CLI examples (`notes --reject`, `jira comment`, `jira transition`) stay documented as the non-interactive path.

---

## Suggested implementation order

**Canonical package sequence:** P1 → P2 → P3 → P4 → P5

### Build order rationale

The command and the notes screen are different surfaces. P1 is first so a session with no SHA can open the app (AC 2) before any new widgets exist. P2 is the read-only review and is what makes AC 3–4 true; it depends on that entry so the verifier opens it through `attach`, not a private constructor only. P3 records the decision before P4 is allowed to call Jira mutations, which matches D6 (post only after save, transition only after post). P5 waits until `attach` is a real command so `next_command` and the tests that assert it change once. Doing P5 inside P1 would advertise a notes flow that P2–P4 have not built; the handoff from `run-review` can keep the old words until P5, and P1’s own tests must not treat `review attach` as valid.

1. P1 — parser and entry guard.
2. P2 — notes screen and auto-present.
3. P3 — save and accept.
4. P4 — comment and transition authorize.
5. P5 — README, previews, chain hints, superseded D7 note.

---

## Test and fixture resources

| Asset | Use |
|-------|-----|
| [tests/test_interactive_triage.py](../../../tests/test_interactive_triage.py) | TTY / non-TTY attach; retarget argv to `<issue> attach` |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | `run_test` pattern; status regression |
| [tests/test_tui_pr.py](../../../tests/test_tui_pr.py) | AC 10 empty snapshot and save |
| [tests/support.py](../../../tests/support.py) | `ISSUE`, scripted runner, `make_app` |
| `reviews/<issue>/session.json` with `current_step: jira-issue` and no `active_sha` | AC 2–3 fixture; build in the test, do not commit a live session |
| `issue.json` `testing_notes: ""` vs a non-empty string | Hide Accept vs show Accept |

**CI:** Jira refresh, comment, and transition stay on `ScriptedRunner`. No live `acli` or `gh` in pytest. Headless Textual is in-process `run_test` (same on Windows and Unix). The spec’s manual pass (`review-ticket <issue> attach` through post and transition, plus an accept path) is outside CI.

---

## Cross-cutting risks summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| `decide_notes` reject overwrites the edited TextArea | High | Draft-body argument; CLI default stays the template (P3) |
| `step_jira` stdin prompt runs under a TTY attach | High | Paint from `refresh_issue`; `resume` only after the decision is stored (P2, P3) |
| `jira_comment` clears `recommendation` | Medium | Transition target is `config.in_progress_status` (P4) |
| P1 removes `review attach` while `next_command` still prints it | Medium | P5 in the same release; do not stop the sequence after P1 |
| Live Jira during screen tests | Medium | Scripted runner only |
| `jira_transition` sets `last_completed_step` to `disposition` | Low | Keep current CLI behavior; status shows whatever `finish` wrote |

---

## Related artifacts

- [spec.md](spec.md)
- [retro.md](retro.md)
- [review-interactive-ui/spec.md](../review-interactive-ui/spec.md) — D7 superseded for the command name; D11 narrowed so this gate may call Jira
