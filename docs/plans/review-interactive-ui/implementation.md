# Interactive review attach — implementation map

Status: **ready for orchestration** — companion to [spec.md](spec.md). Canonical map for implementer assignment and verifier checklists. Refresh with `/spec-implementation-map @spec.md` after material spec or code changes.

## Spec alignment

### Strengths (spec)

- D1–D12 and AC 1–12 are closed. Out of scope keeps Foundry, live GitHub/Jira, publish, and the accept/amend/ignore vocabulary out of this build.
- The verification plan already splits domain unit tests, headless Textual tests, a non-TTY CLI test, and one Windows Terminal manual pass.
- Implementation hints match the code that already exists: `TriageState` and `human_document_from_state` stay the domain core; a new `review_ticket/tui/` package drives them.

### Strengths (repository)

- Triage state, save shape, and publish-preview counts already live in [interactive_triage.py](../../../review_ticket/interactive_triage.py). `human_document_from_state` matches the `review apply --file` document. Tests in [test_interactive_triage.py](../../../tests/test_interactive_triage.py) lock that parity.
- Reviews are already stored per commit at `reviews/<issue>/prs/<slug>/commits/<sha>/review/` (`findings.json`, `human-review.json`, `reviewer-report.md`, `review-preview.md`, `diff-lines.json`). [apply_review](../../../review_ticket/workflow.py) writes the human document, proposed payload, preview markdown, and the `--revise` refusal.
- [show_status](../../../review_ticket/workflow.py) already reads `session.json` without Jira or GitHub. Session fields for AC 2 are present: `current_step`, `last_completed_step`, `outcome`, `next_command`, `active_prs`, `pr_shas`. Check rows are stored in `github-checks.json` (`checks[]` with `name`, `required`, `bucket`, `state`, `link`) and can be rendered with [format_checks_table](../../../review_ticket/reports.py). PR URLs are local via `pr.json` or a constructed GitHub URL in `_pr_url_for_ref`.
- The operator session for the manual probe already has three active PRs and `pr_shas` (`reviews/DOTNETIOT-2550/session.json`, gitignored).

### Gaps and clarifications before build

| Topic | Present state | Spec requirement | Suggested resolution |
|-------|---------------|------------------|----------------------|
| Which directory is the open review | `load_triage_state` always uses `session["active_sha"]` for `active_pr`. | AC 4 opens the PR’s stored SHA. AC 6 shows a snapshot that is not `pr_shas`. | Stored SHA is `pr_shas[ref]`, with `active_sha` only when `ref` is `active_pr` and `pr_shas` has no entry (same fallback as `_pr_scope`). If `commits/<stored>/review/findings.json` exists, that is the open review and there is no stale banner. If it does not, and exactly one other commit directory for that PR has `findings.json`, open that snapshot and show AC 6. If several others exist, open the `findings.json` with the newest mtime and show both SHAs. If none exist, AC 5 on the stored SHA. |
| Status progress vs a stale snapshot | No progress enum. | AC 2: no snapshot, undecided, or human review recorded. AC 10 updates the row after save. | Progress is about the stored SHA: no `findings.json` → no snapshot; findings and no `human-review.json` → undecided; `human-review.json` present → human review recorded. Name the SHA in the label. A review that exists only under an older SHA does not mark the stored SHA recorded. After saving that older snapshot, the row still states the stored SHA has no snapshot, and the PR screen keeps the AC 6 banner. |
| Save path calls the network and retargets the active PR | `apply_review` writes `human-review.json` for `active_sha` only, then `put_decision` and `resume`. `resume` runs Jira and GitHub steps. | D11 and D12: no network; do not change `active_pr` or `active_sha`. AC 9 writes the snapshot SHA. AC 11 keeps `review apply` behavior. | Extract the file writes (human document, proposed payload, preview markdown, `human_review` decision for that SHA) into a function that takes identity + SHA. Attach calls it and `save_session` without `resume` and without changing `active_pr` / `active_sha`. `review apply` still calls `resume`. |
| Quit must not create a session | `ensure_session` writes `session.json` when missing. `load_triage_state` uses it. | AC 3: quitting the status screen does not write `session.json`. | Status open and quit use `read_json` on the existing file. Missing session: show the issue key and “No review session exists yet.” Do not create a file. |
| Publish refusal wording | `publish_review` compares live GitHub HEAD to `active_sha` and refuses on mismatch. It does not compare `pr_shas` to an older commit directory. | D9: the screen says this review is not the stored commit and that publish will refuse until `run-review` for the stored SHA. Attach does not run it. | Banner copy only. Do not add a publish gate and do not call `get_head_sha`. |
| Several docs still name the REPL | README, `review_preview` footer (“interactive TUI”), workflow `next_command`, chain hints, and [operator-guide.md](../multi-pr-reviewer-integration/operator-guide.md). Tests assert `review interactive` in [test_acceptance.py](../../../tests/test_acceptance.py) and [test_regression_multi_pr.py](../../../tests/test_regression_multi_pr.py). | AC 12 names README and the preview copy. D10 removes the command, so leftover handoffs would point at a missing command. | Update those four surfaces and the two tests in P8. Leave the historical multi-PR implementation map as history. |
| Textual version | Not a dependency. [pyproject.toml](../../../pyproject.toml) depends only on PyYAML. | D1: Textual is required, not an extra. | Add `textual` to main `dependencies` with a lower bound that supports Python ≥3.11 and `App.run_test`. No optional extra. |
| In-session second save | `--revise` is a process flag checked before the REPL starts. | AC 9: a second save without `--revise` is refused when a human review is already recorded. | Pass `--revise` into the app. After a successful save, a later save in the same process is refused unless that flag was set. |
| Link control | `_pr_url_for_ref` returns a URL string. | AC 2: a link-style control per PR row. | Show the local URL. Do not open a browser and do not fetch the page. |
| Close vs today’s quit | `q` raises `WorkflowError` and the CLI exits 2. | AC 9: Close returns to the status screen without writing. | Close pops the PR screen and discards unsaved edits. Quitting the status screen exits 0. Non-TTY `review attach` still exits 2. |

### Acceptance criteria traceability

| AC | Present | Delta / work |
|----|---------|----------------|
| 1 | `review interactive` is a REPL behind `review_sub`. No Textual app. | **P1**, **P5**, **P7** — `review attach` opens the status screen; delete the `interactive` subparser. |
| 2 | `show_status` prints issue, one PR line, step, outcome, and `next`. No per-PR check table or review-progress enum. | **P4**, **P5** — read-only projection and status widgets. |
| 3 | `show_status` does not call GitHub or Jira when the file exists. `ensure_session` writes a new file. | **P4**, **P5** — read-only open and quit. |
| 4 | Opening triage uses `active_sha` and does not navigate. | **P2**, **P6** — open the stored SHA; do not write `active_pr` or `active_sha`. |
| 5 | Missing `findings.json` raises `WorkflowError` and tells the operator to run `run-review`. | **P6** — empty screen, no actions, no command to start `run-review`. |
| 6 | No comparison of `pr_shas` to other commit directories. | **P4**, **P6** — stale banner using the selection rule above. |
| 7 | REPL reprints every finding as one text list. Narrative is only in `reviewer-report.md` on disk. Counts exist in `preview_counts_from_state`. | **P6** — index, scroll pane, header counts. |
| 8 | Commands `t`, `f`, `e`, `s`, `v`, `x`, `w`, `q`. Toggle cycles accept/reject. | **P2**, **P6** — separate accept and reject buttons; same decision values. |
| 9 | `apply_review` writes the active SHA and then `resume`. Close is an error exit. | **P3**, **P6** — snapshot save; Close writes nothing; `--revise` gate. |
| 10 | Status text does not list per-PR human-review progress. | **P4**, **P5** — re-read files when returning to status. |
| 11 | `review apply` flags and `--file` already call `apply_review`. | **P3** — keep that path on `resume`. Regression tests stay. |
| 12 | README and `review_preview` call the REPL an interactive TUI / `review interactive`. | **P8** |

---

## Repository layout

The CLI in [cli.py](../../../review_ticket/cli.py) dispatches `review interactive` to `run_interactive_triage`, then `apply_review`. Domain state is in [interactive_triage.py](../../../review_ticket/interactive_triage.py). Session and commit files go through [storage.py](../../../review_ticket/storage.py) and [workflow.py](../../../review_ticket/workflow.py). There is no `review_ticket/tui/` package.

| Path | Role |
|------|------|
| [review_ticket/cli.py](../../../review_ticket/cli.py) | `review` subcommands: `show`, `apply`, `interactive` |
| [review_ticket/interactive_triage.py](../../../review_ticket/interactive_triage.py) | `TriageState`, load, commands, REPL loop |
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | `apply_review`, `show_status`, `publish_review`, `next_command`, `_render` |
| [review_ticket/reports.py](../../../review_ticket/reports.py) | Preview footer and `format_checks_table` |
| [review_ticket/storage.py](../../../review_ticket/storage.py) | `session.json` and `commits/<sha>/` |
| [review_ticket/policy.py](../../../review_ticket/policy.py) | `Check` fields stored in `github-checks.json` |
| [pyproject.toml](../../../pyproject.toml) | Dependencies; Textual absent |
| [tests/test_interactive_triage.py](../../../tests/test_interactive_triage.py) | Document parity, command save, non-TTY |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) | `_seed_publishable`; asserts `review interactive` |
| [README.md](../../../README.md) | Operator commands and the human-review step |

---

## Workstreams mapped to decisions

### D1, D7, D10 — Textual only, command name `review attach`

**Present:** `review interactive` is the only interactive command. It requires a TTY, reprints a text list, and reads `>` commands. Textual is not installed.

**Required:** `review-ticket <issue> review attach` is the only interactive UI. Non-TTY exits with an error that points at `review apply --file` and does not start a REPL. Delete `run_interactive_triage` and the `interactive` parser once tests call state helpers directly.

| Resource | Role |
|----------|------|
| [cli.py](../../../review_ticket/cli.py) | Add `attach`, remove `interactive` |
| [interactive_triage.py](../../../review_ticket/interactive_triage.py) | Delete the REPL loop in **P7** |
| [pyproject.toml](../../../pyproject.toml) | Required `textual` dependency |

**Risks:** Headless tests need `App.run_test`. There is no GitHub Actions workflow in this repo; verification is local `pytest` plus the spec’s Windows Terminal pass.

### D2, D3, D11 — Status document from local files

**Present:** `review show` / `status` print a text block for the session. Check payloads already exist per commit when `step_checks` has run. Opening `status` does not refresh GitHub.

**Required:** A Textual status screen: issue, current step, last completed step, outcome, next command; a check/build table per active PR’s stored SHA from `github-checks.json` when present; one row per active PR with repo, number, stored SHA, a link-style control, and review progress. Quit does not write `session.json`. No GitHub or Jira calls.

| Resource | Role |
|----------|------|
| [workflow.py](../../../review_ticket/workflow.py) `show_status`, `_render`, `_pr_url_for_ref` | Field and URL sources; do not reuse `resume` |
| [reports.py](../../../review_ticket/reports.py) `format_checks_table` | Column meanings for the check table |
| `commits/<sha>/github-checks.json` | Stored checks, outcome, summary |

**Risks:** A missing `github-checks.json` must render as absent, not trigger `assess`.

### D4, D5, D6 — PR screen, inline edit, current actions

**Present:** One scrolling text list. Explanation, summary, and event are line prompts. Accept/reject is one toggle (`undecided` → accept → reject → accept). Must-fix toggles. Reject-automated clears findings and sets `rejected_review`. Save uses `human_document_from_state`.

**Required:** Compact finding index and one scrollable detail pane (reviewer narrative plus the selected finding’s explanation and suggested change). Buttons: accept, reject, must-fix, edit explanation in the pane, edit summary, edit event, reject automated review, save, close. Labels stay words. No accept/amend/ignore.

| Resource | Role |
|----------|------|
| [interactive_triage.py](../../../review_ticket/interactive_triage.py) | State and document shape |
| `review/reviewer-report.md` | Narrative body |
| Finding `explanation` and `suggested_change` | Detail pane |

**Risks:** Widgets must set `decision` to `accept` or `reject` directly. The old `t` cycle is not the button model.

### D8, D9, D12 — Snapshot SHA, stale chrome, session targeting

**Present:** Load and save use `active_sha`. Publish refusal is a live HEAD check inside `publish_review`. Other commit directories are only scanned by `_previous_finding_rows` during `run-review`.

**Required:** The open review is `commits/<sha>/`. If that SHA differs from `pr_shas` for the PR, show both SHAs and the publish-refusal sentence. Attach does not run `run-review`. Viewing or saving does not change `active_pr` or `active_sha`.

| Resource | Role |
|----------|------|
| [storage.py](../../../review_ticket/storage.py) `commit_dir` | Snapshot path |
| [workflow.py](../../../review_ticket/workflow.py) `apply_review`, `publish_review` | Save side effects and the real publish refusal |
| [interactive_triage.py](../../../review_ticket/interactive_triage.py) `load_triage_state` | Today bound to `active_sha` |

**Risks:** Calling `apply_review` from a non-active PR would write the wrong SHA and then hit the network.

---

## Orchestration packages

| ID | Title | Surfaces | Depends on | Primary paths | Verify (AC / tests) |
|----|-------|----------|------------|---------------|---------------------|
| P1 | Require Textual; add `review_ticket/tui` | code, config | — | [pyproject.toml](../../../pyproject.toml), `review_ticket/tui/` | Import and `App.run_test` smoke |
| P2 | Load by SHA; named transitions | code | — | [interactive_triage.py](../../../review_ticket/interactive_triage.py), [tests/test_interactive_triage.py](../../../tests/test_interactive_triage.py) | AC 8 transitions; existing document tests |
| P3 | Snapshot save without `resume` | code | P2 | [workflow.py](../../../review_ticket/workflow.py) | AC 9 file write; AC 11 `review apply` unchanged |
| P4 | Read-only status projection | code | — | new module under `review_ticket/tui/` or `review_ticket/` | AC 2, AC 3, AC 6 data, AC 10 labels |
| P5 | Status screen | cli-ui | P1, P4 | `review_ticket/tui/` | AC 1–3, AC 10 render |
| P6 | PR review screen | cli-ui | P1, P2, P3, P5 | `review_ticket/tui/` | AC 4–9 |
| P7 | `review attach` replaces `review interactive` | cli-ui | P5, P6 | [cli.py](../../../review_ticket/cli.py) | AC 1; non-TTY hint |
| P8 | Docs and handoff strings | docs | P7 | [README.md](../../../README.md), [reports.py](../../../review_ticket/reports.py), [workflow.py](../../../review_ticket/workflow.py), operator guide | AC 12 |

### Package briefs (for implementer agents)

#### P1 — Require Textual; add `review_ticket/tui`

- **Goal:** Textual is a required dependency and the app package exists.
- **Deliverables:** `textual` in `[project].dependencies`. Package `review_ticket/tui/` with an app class that boots under `App.run_test`. No Foundry import.
- **Out of scope:** Screens, CLI subcommand, deleting the REPL.
- **Touchpoints:** [pyproject.toml](../../../pyproject.toml).

#### P2 — Load by SHA; named transitions

- **Goal:** Widgets and tests can load and mutate triage for an explicit PR identity and SHA.
- **Deliverables:** `load_triage_state` (or a sibling) takes identity + SHA. Named operations for accept, reject, must-fix, explanation, summary, event, and reject-automated, matching today’s state effects. `human_document_from_state` and `preview_counts_from_state` stay. Retarget [test_interactive_triage.py](../../../tests/test_interactive_triage.py) off the `t`/`e`/`w` strings where those tests only exist to poke state. Keep the REPL callable until **P7**.
- **Out of scope:** Widgets, file writes, changing decision vocabulary, `added` findings.
- **Touchpoints:** [interactive_triage.py](../../../review_ticket/interactive_triage.py).

#### P3 — Snapshot save without `resume`

- **Goal:** Persist a human review for a chosen SHA without network I/O and without changing `active_pr` or `active_sha`.
- **Deliverables:** Shared writer used by attach: `human-review.json`, and the same `proposed-review.json` and `review-preview.md` updates `apply_review` performs; `put_decision(..., sha=snapshot)` then `save_session`. Refuse when `human-review.json` exists unless `revise` is true. Refuse when findings are undecided unless `rejected_review`. `apply_review` still targets `active_sha` and still calls `resume`.
- **Out of scope:** Textual save button, publish, `run-review`.
- **Touchpoints:** [workflow.py](../../../review_ticket/workflow.py) `apply_review`.

#### P4 — Read-only status projection

- **Goal:** A pure data model for the status screen, built only from files.
- **Deliverables:** Function from an existing session plus store paths to issue key, step, last completed step, outcome, next command, per-PR check rows, and PR rows (repo, number, stored SHA, URL, progress). Snapshot selection follows the gap table. No `ensure_session`, no `resume`, no `get_head_sha`. Unit tests with a three-PR fixture under `tmp_path`, including a stale SHA and a missing `github-checks.json`.
- **Out of scope:** Widgets.
- **Touchpoints:** [storage.py](../../../review_ticket/storage.py), [workflow.py](../../../review_ticket/workflow.py) URL helper, [reports.py](../../../review_ticket/reports.py) check fields.

#### P5 — Status screen

- **Goal:** Textual status document.
- **Deliverables:** Screen bound to the P4 model. PR row activates the PR screen (stub acceptable until **P6** if this package lands first; the navigation target must be the stored-or-stale SHA from P4, not a session write). Quit leaves `session.json` bytes unchanged, including `last_updated`.
- **Out of scope:** Triage buttons, `review apply`.
- **Touchpoints:** `review_ticket/tui/`.

#### P6 — PR review screen

- **Goal:** Triage one snapshot with the current actions.
- **Deliverables:** Header (issue, PR, reviewed SHA, inline vs summary-only counts). Finding index. `VerticalScroll` (or equivalent) containing `reviewer-report.md` and the selected finding’s explanation and suggested change. Inline explanation edit. Buttons from D6. Empty state for AC 5. Stale banner for AC 6. Save calls **P3**. Close returns to status and the status row is rebuilt from disk (AC 10). Unsaved close does not write.
- **Out of scope:** Starting `run-review`, changing `active_pr` / `active_sha`, browser launch, diff-hunk browser, testing-notes, authorize.
- **Touchpoints:** `review_ticket/tui/`, [interactive_triage.py](../../../review_ticket/interactive_triage.py), snapshot writer from **P3**.

#### P7 — `review attach` replaces `review interactive`

- **Goal:** The CLI launches the app and the old command is gone.
- **Deliverables:** `review attach` with `--revise`. Non-TTY `WorkflowError` whose text points at `review apply --file`. Delete `run_interactive_triage`, the `interactive` subparser, and the CLI import. `review show` and `review apply` stay.
- **Out of scope:** Doc rewrites beyond help text on the new parser.
- **Touchpoints:** [cli.py](../../../review_ticket/cli.py).

#### P8 — Docs and handoff strings

- **Goal:** Operator-facing copy names `review attach` and file triage, and no longer describes a REPL as a TUI.
- **Deliverables:** [README.md](../../../README.md) command list and step 5. [reports.py](../../../review_ticket/reports.py) preview footer (`review apply` / `review apply --file`, narrative pointer kept). `next_command` and chain hints in [workflow.py](../../../review_ticket/workflow.py). [operator-guide.md](../multi-pr-reviewer-integration/operator-guide.md) command names. Update the two tests that assert `review interactive`.
- **Out of scope:** Rewriting [multi-pr implementation.md](../multi-pr-reviewer-integration/implementation.md) or orchestration progress history.
- **Touchpoints:** docs and the two `next_command` call sites (`step_publication`, `_execute_reviewer` return).

### Verifier briefs

#### P1 — verification

- **Must prove:** `import review_ticket.tui` works from an install that did not use an extra. A blank app runs under `App.run_test` and exits.
- **Commands / probes:** `python -c "import textual, review_ticket.tui"`; pytest smoke.
- **Regression watch:** `pip install -e .` still installs without the `reviewer` extra. Dev extra stays pytest-only.

#### P2 — verification

- **Must prove:** Loading a non-active SHA does not require that SHA to be `active_sha`. Accept, reject, must-fix, explanation override, summary, event, and reject-automated match previous state effects. `human_document_from_state` still matches the apply-file shape.
- **Commands / probes:** `pytest tests/test_interactive_triage.py`.
- **Regression watch:** `preview_counts_from_state` still counts only `accept` findings that sit on `diff-lines.json`.

#### P3 — verification

- **Must prove:** Save to a SHA that is not `active_sha` writes only that commit’s review files. `active_pr` and `active_sha` are unchanged. No runner invocation (`gh` / `acli`). Second save without `revise` raises the existing human-review error. `review apply --file` and flags still call `resume` and still write `active_sha`.
- **Commands / probes:** New unit test with a scripted runner that fails if a subprocess is called; existing apply tests.
- **Regression watch:** `proposed-review.json` event and summary rules stay those in `apply_review`.

#### P4 — verification

- **Must prove:** Three PR rows from a fixture session. Check table comes from `github-checks.json` and is empty when the file is missing. Progress labels follow the gap table. Stale SHA selection follows the gap table. Function does not write the store.
- **Commands / probes:** New projection tests under `tests/`.
- **Regression watch:** Do not read `reviews/DOTNETIOT-2550/` (gitignored operator data).

#### P5 — verification

- **Must prove:** Headless app shows issue, step, last completed step, outcome, next command, check table, and three PR rows. Quit does not change `session.json`.
- **Commands / probes:** Textual `run_test` pilot on the P4 fixture.
- **Regression watch:** `review-ticket <issue> status` text output stays available (`review show` / `status`).

#### P6 — verification

- **Must prove:** Open PR does not change `active_pr` or `active_sha`. No findings → empty copy and no accept/reject. Stale snapshot shows both SHAs and the publish sentence. Detail pane contains narrative text and the selected explanation. Save writes `human-review.json` for the snapshot SHA. Close does not. Second save without `--revise` is refused. Return to status shows the recorded label for that SHA.
- **Commands / probes:** Headless pilot sequence from the spec verification plan.
- **Regression watch:** Button labels are accept/reject/must-fix, not amend/ignore. No widget starts `run-review`.

#### P7 — verification

- **Must prove:** `review interactive` is rejected by argparse. `review attach` on a non-TTY exits 2 and the stderr mentions `review apply --file`. A TTY path constructs the Textual app (pilot can stub `run`).
- **Commands / probes:** CLI test beside `test_cli_review_interactive_non_tty_errors` (replace that test).
- **Regression watch:** `review apply` and `review show` still parse.

#### P8 — verification

- **Must prove:** README and generated `review-preview.md` do not contain `review interactive` or “interactive TUI”. Workflow output after automated review says `review attach`. Operator guide steps use `review attach`.
- **Commands / probes:** `pytest tests/test_acceptance.py tests/test_regression_multi_pr.py`; search the preview footer.
- **Regression watch:** File-triage instructions still name `review apply` and `review apply --file`.

---

## Suggested implementation order

**Canonical package sequence:** P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8

P2 and P4 do not need P1. P1 must land before P5.

### Build order rationale

Status (D2) and the PR screen (D4) are different surfaces. The projection and the snapshot writer are testable without widgets, so they land before the screens. The PR screen depends on save, so P3 precedes P6. The CLI command waits until both screens exist so `review attach` is not a parser that opens an empty app. Docs and `next_command` change only after the new command is real, so tests that assert the next command move once in P8.

1. P1 — dependency and package.
2. P2 — SHA load and named transitions.
3. P3 — snapshot save that does not call `resume`.
4. P4 — status projection and fixture.
5. P5 — status screen.
6. P6 — PR screen, banner, save, and close.
7. P7 — CLI swap and REPL deletion.
8. P8 — README, preview copy, workflow hints, operator guide, acceptance assertions.

---

## Test and fixture resources

| Asset | Use |
|-------|-----|
| [tests/test_interactive_triage.py](../../../tests/test_interactive_triage.py) | Document shape, counts, non-TTY |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) `_seed_publishable` | One PR, `F001`, `diff-lines.json`, `human-review.json` |
| [tests/support.py](../../../tests/support.py) `make_app` | Scripted runner; assert it is not invoked from attach |
| [tests/test_regression_multi_pr.py](../../../tests/test_regression_multi_pr.py) | Next-command string |
| New three-PR fixture in `tmp_path` | AC 2 headless status. Do not point tests at `reviews/DOTNETIOT-2550/` |
| Manual: `review-ticket DOTNETIOT-2550 review attach` on Windows Terminal | Spec verification plan, after P7 |

**CI:** This repo has no `.github` workflow. `pytest` is local. Headless Textual pilots do not need a TTY. The Windows Terminal pass stays manual.

---

## Cross-cutting risks summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| `apply_review` → `resume` performs GitHub/Jira work | High | P3 writer; verifier asserts the scripted runner is idle |
| Save uses `active_sha` and would write the wrong PR | High | P3 takes an explicit SHA; P6 must not call `apply_review` |
| `ensure_session` creates `session.json` on open | High | P4/P5 read the file; quit compares bytes |
| Removing `review interactive` breaks README, preview, and `next_command` | Medium | P8 is in the sequence, not a follow-up |
| Several older snapshots for one PR | Medium | Newest `findings.json` mtime, both SHAs shown; recorded in the gap table |
| Textual on Windows Terminal differs from `run_test` | Medium | Manual DOTNETIOT-2550 pass stays in the spec; do not treat pilots as a substitute |
| Multi-PR plan text still prefers a small Rich UI | Low | This spec replaces that choice for the review UI. Do not import Rich as the attach UI |

---

## Related artifacts

- [spec.md](spec.md)
- [retro.md](retro.md)
- [README.md](README.md)
- [multi-pr operator guide](../multi-pr-reviewer-integration/operator-guide.md)
- Foundry attach (external reference only, not a dependency): `c:\repos\burtlo\foundry`
