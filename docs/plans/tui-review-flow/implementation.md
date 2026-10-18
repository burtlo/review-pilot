# Review Ticket TUI — implementation map

Status: **ready for orchestration** — companion to [spec.md](spec.md). Canonical map for implementer assignment and verifier checklists. Refresh with `/spec-implementation-map @spec.md` after material spec or code changes.

The spec has no decision IDs and no numbered acceptance criteria. Traceability uses **scenarios A–J** and **spec sections**. The spec status line is still “Design specification for implementation”; this map treats that file as the source of truth because a full map was requested.

## Spec alignment

### Strengths (spec)

- Sections 3–4, 13, and 21 fix the interaction contract: stacked layout, one decision panel with six states, three GitHub outcomes, and eighteen rules that keep evidence, local decisions, publication, and workflow outcomes apart.
- Section 2 keeps the CLI as the mutation authority and names the screens to extend (status, testing notes, PR triage) instead of a new workflow engine.
- Section 18’s artifact tree matches the directories the app already writes. New state is specified as schema extensions, not a migration.
- Section 17’s outcome labels match `Outcome` in [models.py](../../../review_ticket/models.py).
- Scenarios A–J cover the early-return path, the happy path, SHA change, and failed external calls.

### Strengths (repository)

- `review-ticket <issue> attach` starts [ReviewTicketApp](../../../review_ticket/tui/app.py), which pushes [StatusScreen](../../../review_ticket/tui/status_screen.py) and, when `current_step` is `jira-issue` and testing notes are undecided or rejected, [TestingNotesScreen](../../../review_ticket/tui/testing_notes_screen.py).
- Testing-notes accept/reject already calls [decide_notes](../../../review_ticket/workflow.py). Reject can persist an edited `return-comment.md`. Post and transition call [jira_comment](../../../review_ticket/workflow.py) and [jira_transition](../../../review_ticket/workflow.py) with `yes=True`. Repeat posts are skipped via [successful_action](../../../review_ticket/storage.py) on `actions.jsonl`. Headless coverage is in [test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py).
- [project_review_status](../../../review_ticket/status_projection.py) reads `session.json` and per-commit `github-checks.json` with no network. Progress is `no_snapshot` / `undecided` / `recorded` from `findings.json` and `human-review.json`. [test_tui_status.py](../../../tests/test_tui_status.py) locks a three-PR fixture.
- [PrReviewScreen](../../../review_ticket/tui/pr_screen.py) triages one snapshot through [interactive_triage.py](../../../review_ticket/interactive_triage.py) and [save_snapshot_review](../../../review_ticket/workflow.py). Save does not call `resume` and does not publish. A stale open SHA is bannered. Close does not write.
- Ticket-level check and analyzer aggregation already exists: [step_checks](../../../review_ticket/workflow.py), [step_analyzers](../../../review_ticket/workflow.py), [evaluate_readiness](../../../review_ticket/policy.py) (`WAITING` while required checks are pending), [evaluate_analyzers](../../../review_ticket/policy.py), and combined `readiness.md` / `analyzers.md`.
- SHA-scoped files already live under `reviews/<issue>/prs/<slug>/commits/<sha>/`. [publish_review](../../../review_ticket/workflow.py) refuses a live HEAD mismatch, matches an existing GitHub review before creating one, and skips a repeat of the same payload fingerprint. [record_tests](../../../review_ticket/workflow.py) stores image digest and refuses results whose SHA does not match. [testing_outcome](../../../review_ticket/policy.py) treats `blocked` / `environment` as `BLOCKED`, not an implementation defect.
- `run-review` with no `reviewer_command` writes a context bundle and points at `import-review` ([_execute_reviewer](../../../review_ticket/workflow.py)). `test prepare` / `test fetch` / `test launch` already exist.

### Gaps and clarifications before build

| Topic | Present state | Spec requirement | Suggested resolution |
|-------|---------------|------------------|----------------------|
| Pipeline order | [resume](../../../review_ticket/workflow.py) runs publication before virtualization and testing. [step_publication](../../../review_ticket/workflow.py) stops until `human-review.json` exists and `publication.json` is written. [test_acceptance.py](../../../tests/test_acceptance.py) expects `publish-review` in that position. | §2.1 and §13.4: functional testing precedes GitHub Approve. Early Request Changes is the exception (§9.3, §21.4). | Keep the step functions. Stop treating “local review saved, not published” as a blocker in front of testing. `publish-review` stays explicit. Approve eligibility moves to the predicate in §13.4. Update acceptance tests that encode the old order in **P4**. |
| One active PR after analyzers | Checks and analyzers iterate `active_prs`. [step_automated_review](../../../review_ticket/workflow.py), publication, virtualization, testing, and disposition call [_require_identity](../../../review_ticket/workflow.py) and use `active_sha` only. `run-review` generates one PR. | §1.1 and §7: every PR has three SHA-scoped tracks at once. | Add explicit `identity` + `sha` arguments on generate, publish, prepare/fetch/launch, and record, defaulting to the active PR so today’s CLI still works. The hub passes the selected PR. Do not `pr select` inside the TUI; that collapses `active_prs` to one ref. **P4**, **P6**. |
| Three tracks vs one human file | `review/human-review.json` is the curated automated finding document. [disposition_checklist](../../../review_ticket/policy.py) treats “human reviewed the automated findings” plus a publication receipt as the human gate. | §7 and §10: automated curation, manual code review, and functional testing are separate. §21.6. | Keep `human-review.json` as the automated-track curation file. Add `review/manual-review.json` for §10.1. Keep `testing/test-results.json` and add the disposition fields §12.1 requires. **P4**. |
| One publication receipt | `review/publication.json` stores one event. A second publish of a different body is a new fingerprint and overwrites the file. | §13.5: an early Comment and a later final review are separate receipts. Latest outcome and history both show. | Append `review/publications.jsonl`. Keep `publication.json` as the latest receipt so existing readers keep working. **P4**, **P9**. |
| Testing-notes layout and labels | [TestingNotesScreen](../../../review_ticket/tui/testing_notes_screen.py) uses Accept/Reject. Reject hides description and notes. Post/transition use Approve/Deny. There is no receipt. Transition Deny returns without recording a decline. Recommendation is a sentence in the assessment markdown, not button emphasis. | §4 and §5: Approve/Reject, stable equal buttons, emphasis only, description collapses, notes stay visible, then preview → Yes/No comment → Yes/No transition → receipt. Declines are recorded. | Rebuild this screen on the shared panel in **P1**/**P2**. Map today’s Accept to Approve. Record comment-declined and transition-declined on the testing-notes decision. |
| Readiness is CLI-only | Status shows stored checks per PR. Analyzer rows are printed by the CLI (`analyzer_pr_rows`) and written to `analyzers.md`. No TUI gate. [decide_analyzers](../../../review_ticket/workflow.py) `--return` drafts every finding in scope. | §6: one readiness screen, per-PR SHA rows, Approve only when the gate is satisfiable, Reject draft cites only PRs and findings that need attention, `WAITING` offers refresh instead of Approve/Reject. | **P3** reads local `github-checks.json`, `analyzers.md`, and analyzer decisions. Filter the return draft to non-`READY` PRs and unaddressed findings. Explicit Refresh calls `resume` / `assess`. |
| Hub and generation | Opening a PR with no `findings.json` tells the operator to leave the TUI and run `pr select` then `run-review`. Nothing generates on entry, which matches §8, but there is no View / Generate / Stale table. | §7–§8 and scenario D. | **P5** hub, **P6** preparation. Generation stays an explicit button calling `run-review` or `import-review` for the selected identity. |
| Triage vocabulary and context | PR screen is an index/detail split with accept, reject, must-fix, and a hidden event field. Save requires every finding decided. No source lines. Save writes `human-review.json` and does not publish. | §9: include/exclude, edit the inline comment, code context, local track disposition, narrow terminals stack instead of two columns. Excluded findings stay on disk. | **P7** keeps accept/reject on disk (`decision: accept\|reject`) and labels them Include/Exclude. Default include is allowed only after the reviewer saves; do not publish. Show `diff.patch` context when the file exists. |
| Human code review and diff | No manual-finding artifact and no diff view. | §10, including file/line findings and a disposition the agent cannot satisfy. Layout is marked suggested. | **P8**. Required fields are §10.1. Layout may stack on narrow widths. Duplicate inline comments: suppress a manual finding when path, line, and normalized body match a selected automated finding. No semantic dedup. |
| Functional notes vs result | [record_tests](../../../review_ticket/workflow.py) stores sha, image, digest, result, failure kind, notes, scenarios, evidence. It has no separate reviewer disposition, steps, or expected result. | §12: Pass/Fail/Blocked is not Approve/Comment/Request Changes. | Extend the test-results payload in **P11**. Environment failure stays `BLOCKED` and does not select Request Changes. |
| Ticket disposition UI | CLI [record_disposition](../../../review_ticket/workflow.py) is `approve` / `leave` / `return` for `active_sha`, with `--override`. Checklist is single-PR. | §15: ticket Approve/Reject. Approve requires every included PR. Reject draft cites blockers only. Comment is not Approve. | **P12** evaluates all `active_prs`. Keep CLI `leave` and `--override`. Do not add a third TUI button. |
| SHA change | New HEAD updates `pr_shas` and appends `previous_shas`. Old commit directories remain. Publish refuses a mismatched live HEAD. Test results with the wrong SHA are not evidence. Decisions for the old SHA remain in `decisions` because they are keyed by SHA. Nothing marks them historical in the UI, and a new SHA does not get a copied approval. | §16 and scenario I: visible stale state, history read-only, renew all three tracks, testing-notes acceptance stays. | **P14**. Invalidate only the PR whose SHA changed. Do not invent cross-PR dependency invalidation; §16.1 leaves that case unspecified. |
| Unspecified policy hooks | §15.1 mentions an organization-specific final approval policy. §4.5 lists optional PR comments and bug-writer authorization “where implemented.” §10 and §11 layouts are suggested. | Those sentences do not name a policy file or a bug-writer screen. | Enforce §13.4 only. Leave `pr comment` and `bug` on the CLI ([draft_bug](../../../review_ticket/workflow.py) already exists). Do not add them to the TUI in this map. |
| Pre-check third state | Assessment text recommends Accept or Reject. | §5.1 also says “Needs human judgment.” | Emphasis only. Both buttons stay. No third control. **P2**. |
| Network on accept | `decide_notes` always calls `resume`, which refreshes Jira and can sync GitHub before the next screen paints. | §5.2: advance through the existing operation; §17.2: status stays local; refresh is explicit. | TUI Approve calls `decide_notes` so the session stays authoritative, then opens the readiness view of the stored result. Readiness paint uses files on disk. A Refresh control is what calls `resume` again. **P2**, **P3**. |

### Acceptance criteria traceability

| AC | Present | Delta / work |
|----|---------|----------------|
| A | Accept stores `decisions.testing_notes` and pops to status. `resume` may already sync PRs. No Jira write on accept. | **P2** — land on the readiness view; still no Jira mutation. |
| B | Reject saves a draft and can post then transition. Notes hide. No receipt. Deny is not recorded. Buttons are Approve/Deny. | **P1**, **P2** — panel states, notes stay visible, Yes/No, receipt, recorded declines. |
| C | CLI aggregates PRs and can `--return`, but the draft lists every finding and the TUI has no readiness decision. | **P3** — ticket gate; draft cites only PRs that need attention. |
| D | Missing findings are an empty PR screen with CLI instructions. Stale snapshot opens with a banner. No Generate action. Entering attach does not run the reviewer. | **P6** — View / Generate / Stale; explicit generate only. |
| E | Include/exclude, must-fix, explanation edit, and save-without-publish exist. Event is a text field. No code context. | **P7** — curation UI and local track disposition. Published body is **P9**. |
| F | CLI can `publish-review` with `REQUEST_CHANGES` before testing, then asks for a Jira transition without a composed preview in the TUI. | **P7**, **P8**, **P9**, **P12** — confirmed blocker, preview, authorize, hub receipt, ticket reject draft. |
| G | `test record --result fail --kind implementation` writes results and recommends a transition. No TUI, no separate disposition, no GitHub composition. | **P10**, **P11**, **P9**, **P12**. |
| H | Single-PR checklist can reach `disposition --choice approve` after publish and a passing test. GitHub Approve is allowed before functional testing. Comment is not distinguished from Approve on a hub. | **P4**, **P5**, **P9**, **P11**, **P12**. |
| I | Old commit dirs and SHA-keyed decisions survive. UI does not mark the three tracks stale or block an incompatible payload beyond the live HEAD check in `publish_review`. | **P4**, **P14**. |
| J | Jira comment failure returns `BLOCKED` and testing-notes tests cover it. Publication failure journals `actions.jsonl` and does not write a success receipt. Partial comment-then-failed-transition is not a TUI receipt. Retry of the same Jira body is idempotent. | **P1**, **P9**, **P12** — receipt rows and resume without rebuilding the draft. |

---

## Repository layout

Python package `review_ticket`. The Textual UI is a thin caller of workflow functions. Session and PR evidence live under `reviews/<issue>/` (gitignored). Tests are headless `App.run_test` plus workflow tests with a scripted runner.

| Path | Role |
|------|------|
| [review_ticket/cli.py](../../../review_ticket/cli.py) | Subcommands: `attach`, `notes`, `assess`, `analyzers`, `run-review`, `import-review`, `publish-review`, `test`, `jira`, `disposition` |
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | Authoritative steps, decisions, publication, virtualization, testing |
| [review_ticket/policy.py](../../../review_ticket/policy.py) | Readiness, analyzer, testing, and disposition predicates |
| [review_ticket/tui/app.py](../../../review_ticket/tui/app.py) | Textual shell |
| [review_ticket/tui/status_screen.py](../../../review_ticket/tui/status_screen.py) | Read-only status |
| [review_ticket/status_projection.py](../../../review_ticket/status_projection.py) | Status model |
| [review_ticket/tui/testing_notes_screen.py](../../../review_ticket/tui/testing_notes_screen.py) | Screen 1, partial |
| [review_ticket/tui/pr_screen.py](../../../review_ticket/tui/pr_screen.py) | Automated triage, partial screen 5 |
| [review_ticket/interactive_triage.py](../../../review_ticket/interactive_triage.py) | Finding decisions and payload preview counts |
| [review_ticket/storage.py](../../../review_ticket/storage.py) | `session.json`, commit dirs, `actions.jsonl` |
| [review_ticket/reports.py](../../../review_ticket/reports.py) | Issue, readiness, analyzer, return, and test markdown |
| [tests/test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py) | Scenarios A–B, partial J |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | Status projection UI |
| [tests/test_tui_pr.py](../../../tests/test_tui_pr.py) | Triage save, stale banner |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) | CLI pipeline, including current publish-before-test order |

---

## Workstreams mapped to decisions

### §3–§4 — Shared chrome and decision panel

**Present:** Each screen owns its CSS. Status and testing notes dock a header and footer. The notes dock is a one-off VerticalGroup, not a reusable state machine. No receipt widget. No persistent issue/SHA header.

**Required:** Stacked regions, context header, equal Approve/Reject that do not move when the recommendation changes, then edit → saved preview → Yes/No comment → Yes/No transition → receipt.

| Resource | Role |
|----------|------|
| [testing_notes_screen.py](../../../review_ticket/tui/testing_notes_screen.py) | Closest panel; labels and hide-all-evidence behavior diverge |
| [authorize.py](../../../review_ticket/authorize.py) | CLI yes/no; TUI must not call the stdin prompt |
| [jira_comment](../../../review_ticket/workflow.py) / [jira_transition](../../../review_ticket/workflow.py) | Mutations and idempotent receipts |

**Risks:** A shared widget that calls `authorize()` will block on stdin inside Textual. Pass `yes=True` only after the Yes button.

### §5 — Testing notes

**Present:** Auto-presented from [should_auto_present_testing_notes](../../../review_ticket/tui/testing_notes_screen.py). Refresh on mount calls Jira. Accept and reject persist. Post failure surfaces `BLOCKED`.

**Required:** Scenario A and B, including collapsed description, visible notes, receipt, and no Jira write on Approve.

| Resource | Role |
|----------|------|
| [testing_notes_assessment_markdown](../../../review_ticket/reports.py) | Pre-check copy |
| [decide_notes](../../../review_ticket/workflow.py) | Ticket-scoped decision and optional `draft_body` |
| [test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py) | Regression |

**Risks:** `decide_notes` → `resume` can perform GitHub I/O before the readiness screen is shown.

### §6 — PR readiness and analyzers

**Present:** Multi-PR CLI aggregation and per-SHA analyzer decisions. Status shows checks only. Return drafts include every finding.

**Required:** Ticket-level Approve/Reject, `WAITING` without a decision, refresh, and a draft limited to PRs that need attention.

| Resource | Role |
|----------|------|
| [step_checks](../../../review_ticket/workflow.py) / [step_analyzers](../../../review_ticket/workflow.py) | Collection and worst-outcome aggregation |
| [decide_analyzers](../../../review_ticket/workflow.py) / [assess](../../../review_ticket/workflow.py) | Return, accept dispositions, override, missing-check acknowledgement |
| [analyzers.md](../../../review_ticket/reports.py) writers | Detail report already on disk |

**Risks:** Painting this screen must not call `get_checks` or `get_review_threads`. Those run on Refresh.

### §1.1, §2.1, §17–§18 — Track model and session

**Present:** One cursor (`active_pr`, `active_sha`) after the analyzer gate. Publication blocks testing. `human-review.json` means both “curated findings” and “human reviewed.”

**Required:** Three SHA-scoped tracks, publication not implied by a draft, early Request Changes allowed, history kept, CLI functions reused.

| Resource | Role |
|----------|------|
| [resume](../../../review_ticket/workflow.py) | Order change |
| [put_decision](../../../review_ticket/workflow.py) / [get_decision](../../../review_ticket/workflow.py) | SHA-keyed decisions already exist |
| [save_snapshot_review](../../../review_ticket/workflow.py) | Pattern for “write files, do not resume” |

**Risks:** Acceptance tests encode the old order. CLI defaults must keep single-PR commands working.

### §7 and §14 — Hub

**Present:** Status list opens the triage screen. Progress labels do not mention functional testing or publication.

**Required:** Per-PR track rows, GitHub published vs local, ticket disposition dock, Esc back to status.

| Resource | Role |
|----------|------|
| [status_screen.py](../../../review_ticket/tui/status_screen.py) | Navigation parent |
| [PrStatusRow](../../../review_ticket/status_projection.py) | Extend or add a hub projection beside it |

**Risks:** Reusing the status progress enum would collapse three tracks back into one label.

### §8 — Automated review preparation

**Present:** `run-review` and `import-review` for the active PR. Empty triage screen prints CLI text. Opening the screen does not generate.

**Required:** View / Generate / Stale per PR, generate one or all missing, show failure, no generation on entry.

| Resource | Role |
|----------|------|
| [_execute_reviewer](../../../review_ticket/workflow.py) | Generation and import handoff |
| [pr_screen.py](../../../review_ticket/tui/pr_screen.py) empty state | Replace the “leave the TUI” copy |

**Risks:** Reviewer commands are slow. The TUI action must be explicit and show running/failure. Do not start it from `on_mount`.

### §9 — Automated findings

**Present:** Working triage and local save. Side-by-side layout. No source excerpt.

**Required:** Curation, local disposition, early-blocker handoff into publication. Agent must-fix does not publish by itself.

| Resource | Role |
|----------|------|
| [interactive_triage.py](../../../review_ticket/interactive_triage.py) | Decision model to keep |
| [findings.py](../../../review_ticket/findings.py) | Payload builder; excluded findings stay out of the body |

**Risks:** `triage_document_if_ready` requires every finding decided. Include/exclude can map onto that if Exclude is `reject` and the default before save is undecided.

### §10 — Human code review

**Present:** No separate record. The disposition checklist treats automated curation plus publication as the human gate.

**Required:** Explicit inspection record, manual findings, disposition the agent cannot satisfy.

| Resource | Role |
|----------|------|
| New `review/manual-review.json` beside [human-review.json](../../../review_ticket/workflow.py) | Do not overload the curation file |
| `diff.patch` under the commit dir | Written by `_ensure_diff` during `run-review` |

**Risks:** Approving GitHub from automated findings alone must stay impossible after **P9**.

### §11–§12 — Environment and functional testing

**Present:** CLI prepare/fetch/launch/record with digest binding. No TUI. Notes are one string. Failure kind is `implementation` or `environment`.

**Required:** Readiness display, not a YAML editor. Separate operational result and reviewer disposition. Early return on a functional blocker.

| Resource | Role |
|----------|------|
| [prepare_profile](../../../review_ticket/workflow.py), [fetch_image](../../../review_ticket/workflow.py), [launch_environment](../../../review_ticket/workflow.py) | Reuse |
| [record_tests](../../../review_ticket/workflow.py) | Extend payload |
| [policy.testing_outcome](../../../review_ticket/policy.py) | Keep environment failures as `BLOCKED` |

**Risks:** Launch and fetch hit Docker. Same rule as generation: button only, surface `BLOCKED`, do not convert it into Request Changes.

### §13 — GitHub publication

**Present:** `publish-review` for the active SHA, one receipt, HEAD recheck, idempotent fingerprint. Eligibility is “human-review.json exists,” which today means curated automated findings. `--event` can be `APPROVE` before any functional test.

**Required:** Composition of selected automated findings, manual findings, and functional notes. Approve / Comment / Request Changes with the §13.4 gates. Preview, authorize, multiple receipts, stale payload blocked.

| Resource | Role |
|----------|------|
| [publish_review](../../../review_ticket/workflow.py) | Mutation to wrap, not duplicate |
| [build_review_payload](../../../review_ticket/findings.py) | Inline comments |
| [review_preview](../../../review_ticket/reports.py) | Preview copy to align with the TUI |

**Risks:** Calling `publish_review` after `resume` still advances the old pipeline. **P4** lands first. Live HEAD lookup belongs on the authorize action, not on screen paint.

### §15 — Ticket disposition

**Present:** Single-PR checklist and `approve` / `leave` / `return`. Jira transition is a separate authorized command. GitHub Request Changes recommends `in_progress_status` without a composed return draft in the TUI.

**Required:** Ticket-level Approve and Reject. Approve disabled while any included PR is blocking or unpublished. Reject draft lists blockers only, then the §4 authorization sequence.

| Resource | Role |
|----------|------|
| [record_disposition](../../../review_ticket/workflow.py) | Per-SHA write; ticket rule needs all PRs |
| [return_comment](../../../review_ticket/reports.py) | Draft template to specialize |
| [config.approved_status](../../../review_ticket/config.py) | Approve transition target (`Done` unless configured) |

**Risks:** `record_disposition` refreshes Jira and GitHub before saving. The TUI Reject save must not post. Call the decision write, then Yes/No for comment and transition.

### §16 — SHA history

**Present:** Commit directories and `previous_shas` retain old evidence. Publish compares live HEAD. Functional results must match SHA and digest.

**Required:** Visible historical/stale state, no copied approval, renewed tracks only for the PR that moved, testing-notes decision left intact.

| Resource | Role |
|----------|------|
| [_sync_pull_request](../../../review_ticket/workflow.py) | Detects the new HEAD |
| [status_projection._select_open_snapshot](../../../review_ticket/status_projection.py) | Today’s stale banner is “open an old findings file,” which is a different meaning than “HEAD moved” |

**Risks:** Do not treat the old open-snapshot banner as §16 compliance.

### §17.2 and §20 — Status

**Present:** Local markdown, step, outcome, next command, checks, one progress label. Quit does not write the session. PR pick does not change `active_pr`.

**Required:** Multi-PR track progress, current action, and enough freshness that a mutation is not offered on stale data. Still no network on paint.

| Resource | Role |
|----------|------|
| [status_format.py](../../../review_ticket/tui/status_format.py) | Document body |
| [show_status](../../../review_ticket/workflow.py) | CLI twin; keep it local |

**Risks:** [test_tui_status.py](../../../tests/test_tui_status.py) asserts today’s labels. Update those tests in the same package that changes the labels.

---

## Orchestration packages

| ID | Title | Surfaces | Depends on | Primary paths | Verify (AC / tests) |
|----|-------|----------|------------|---------------|---------------------|
| P1 | Shared context header and decision panel | code, cli-ui | — | `review_ticket/tui/` new panel module; notes screen consumes it in P2 | §3–§4; panel state tests |
| P2 | Testing notes on the shared panel | cli-ui | P1 | [testing_notes_screen.py](../../../review_ticket/tui/testing_notes_screen.py), [reports.py](../../../review_ticket/reports.py) | A, B; [test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py) |
| P3 | PR readiness and analyzer disposition | code, cli-ui | P1 | new readiness view; [decide_analyzers](../../../review_ticket/workflow.py), [policy.py](../../../review_ticket/policy.py) | C; new headless screen tests |
| P4 | Three-track model and publication-after-testing | code | — | [workflow.py](../../../review_ticket/workflow.py), [policy.py](../../../review_ticket/policy.py) | §2.1, §18; [test_acceptance.py](../../../tests/test_acceptance.py) |
| P5 | PR review hub | cli-ui | P1, P4 | new hub screen; [app.py](../../../review_ticket/tui/app.py) | §7, §14; hub tests |
| P6 | Automated review preparation | code, cli-ui | P4, P5 | [workflow.py](../../../review_ticket/workflow.py) `run_review` / import; new prepare view | D |
| P7 | Automated finding triage | cli-ui | P4, P6 | [pr_screen.py](../../../review_ticket/tui/pr_screen.py), [interactive_triage.py](../../../review_ticket/interactive_triage.py) | E; [test_tui_pr.py](../../../tests/test_tui_pr.py) |
| P8 | Human code review track | code, cli-ui | P4, P5 | new manual-review artifact and screen | §10 |
| P9 | GitHub composition and publication | code, cli-ui | P4, P7, P8 | [publish_review](../../../review_ticket/workflow.py), new compose view | F publication half, §13; H’s publish gate after P11 |
| P10 | Test environment view | cli-ui | P4, P5 | [prepare_profile](../../../review_ticket/workflow.py), fetch, launch | §11 |
| P11 | Functional testing track | code, cli-ui | P4, P10 | [record_tests](../../../review_ticket/workflow.py), new screen | G capture half, §12 |
| P12 | Ticket disposition | code, cli-ui | P1, P4, P5, P9, P11 | [record_disposition](../../../review_ticket/workflow.py), hub dock | F ticket half, G, H, §15 |
| P13 | Status track summary | cli-ui | P4 | [status_projection.py](../../../review_ticket/status_projection.py), [status_format.py](../../../review_ticket/tui/status_format.py) | §17.2, §20; [test_tui_status.py](../../../tests/test_tui_status.py) |
| P14 | SHA change and explicit refresh | code, cli-ui | P4 | [_sync_pull_request](../../../review_ticket/workflow.py), hub and status stale flags | I, §6.5, §16 |

### Package briefs (for implementer agents)

#### P1 — Shared context header and decision panel

- **Goal:** One header and one bottom panel that later screens bind to, matching §3 and §4.
- **Deliverables:** Context header widget (issue key, title, stage, active PR, short SHA plus full SHA available, stale marker, recommendation). Decision panel states: Approve/Reject, editing, saved preview, Yes/No comment, Yes/No transition, receipt. Equal button widths. Recommendation changes emphasis only. Receipt lists saved / posted / moved / failed / declined. Unit test the state machine without a live Jira call.
- **Out of scope:** Wiring every screen. Bug writer. GitHub’s three-outcome bar (that is P9).
- **Touchpoints:** New module under `review_ticket/tui/`. No workflow changes.

#### P2 — Testing notes on the shared panel

- **Goal:** Scenarios A and B on the existing notes flow.
- **Deliverables:** Stacked description and notes, notes given more of the evidence height, independent scroll. Reject collapses the description and leaves notes visible. Prefill from `return-comment.md` or [return_comment](../../../review_ticket/reports.py). Save calls `decide_notes(..., draft_body=...)` and does not post. Yes posts `jira_comment`; No records a decline and leaves the draft. Transition Yes/No likewise. Receipt, then pop to status. Approve calls `decide_notes` and routes to the readiness view when that view exists; until P3 lands, pop to status as today. Emphasis from the assessment: missing notes emphasize Reject; present notes emphasize Approve. Both stay enabled when notes are non-empty. Hide or disable Approve when the refreshed body is empty only if that matches current `step_jira` (it never offers accept for an empty body). `--revise` still re-enables a saved decision.
- **Out of scope:** Readiness aggregation. Changing `decide_notes` to skip `resume`.
- **Touchpoints:** [testing_notes_screen.py](../../../review_ticket/tui/testing_notes_screen.py), [test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py).

#### P3 — PR readiness and analyzer disposition

- **Goal:** Scenario C as a TUI gate in front of code review.
- **Deliverables:** Local projection over `active_prs`: PR identity, stored SHA, check outcome, analyzer outcome. Detail pane renders stored `readiness.md` / `analyzers.md` (or the per-commit files). `WAITING` shows Refresh and hides Approve/Reject. Refresh calls `resume` or `assess`. Approve enabled only when every included PR is `READY` or an existing exception is recorded (`missing_checks`, `missing_analyzers`, analyzer `accept_dispositions` / `override`). Approve records that gate and does not call GitHub review APIs. Reject opens the P1 panel with a draft that names only non-ready PRs and their unaddressed findings, then the Jira Yes/No sequence. No discovered PR: show the existing `pr select` guidance; do not invent a PR.
- **Out of scope:** Generating reviews. Per-finding Bugbot triage (that stays the analyzer decision vocabulary: return, accept dispositions, override).
- **Touchpoints:** New screen, [decide_analyzers](../../../review_ticket/workflow.py), [assess](../../../review_ticket/workflow.py), [reports.py](../../../review_ticket/reports.py) draft helper.

#### P4 — Three-track model and publication-after-testing

- **Goal:** Make session and artifacts able to represent §1.1 and §2.1 without a new engine.
- **Deliverables:** Document the track record in code: automated curation (`findings.json` + `human-review.json`), manual review (`manual-review.json`), functional (`test-results.json`), publications (`publications.jsonl` plus latest `publication.json`). Helpers to read track status for one PR/SHA: not started, in progress, complete locally, publication pending, published, stale, blocked, returned. Change `resume` so a saved automated curation no longer blocks virtualization and testing. `step_publication` becomes “report publication state” or moves out of the blocking prefix; `publish-review` remains the mutating command. Add optional identity/SHA parameters to `run_review`, `publish_review`, `prepare_profile`, `fetch_image`, `launch_environment`, and `record_tests`, defaulting to the active PR. Update [disposition_checklist](../../../review_ticket/policy.py) so “human” is the manual track, not “curation file plus receipt.” Update acceptance tests that require `publish-review` before `test prepare`.
- **Out of scope:** New screens. Copying approvals onto a new SHA.
- **Touchpoints:** [workflow.py](../../../review_ticket/workflow.py), [policy.py](../../../review_ticket/policy.py), [test_acceptance.py](../../../tests/test_acceptance.py).

#### P5 — PR review hub

- **Goal:** §7 workspace after readiness.
- **Deliverables:** One block per included PR: title, repo, HEAD SHA, three track labels, GitHub outcome from a receipt only, stale marker, next action. Enter opens the selected track. Actions that are not yet eligible are visible and disabled, with the reason in the row. Ticket Approve/Reject dock is present and disabled until P12. Esc returns to status without discarding files. Navigating does not change `active_pr` or `active_sha`.
- **Out of scope:** Implementing the track screens. Generating reviews on mount.
- **Touchpoints:** New hub screen, [app.py](../../../review_ticket/tui/app.py) routing from status.

#### P6 — Automated review preparation

- **Goal:** Scenario D.
- **Deliverables:** Table of current / missing / stale per PR HEAD. View opens P7 for that SHA. Generate selected and generate-all-missing call the P4 generation entry for those identities only. Failure stays on the row and can be retried. No `reviewer_command`: show the import path and context file, do not write `findings.json`. Busy state while the command runs. Esc returns to the hub with updated rows.
- **Out of scope:** Finding edits. Publishing.
- **Touchpoints:** [workflow.py](../../../review_ticket/workflow.py), new view, [test_reviewer_adapter.py](../../../tests/test_reviewer_adapter.py) patterns for a fake reviewer.

#### P7 — Automated finding triage

- **Goal:** Scenario E on the current PR screen.
- **Deliverables:** Include/exclude, edit explanation, must-fix, save local selections, preserve excluded findings in `human-review.json`. Show file, line, and a diff excerpt when `diff.patch` or `diff-lines.json` can locate it. Narrow width stacks list and detail. Local disposition Approve / Comment / Request Changes stored on the automated track, not published. Request Changes enables the P9 handoff only after the reviewer confirms the blocker; the agent `must_fix` flag alone does not. Save still refuses a second write unless `--revise`. Stale banner remains until P14 sharpens it.
- **Out of scope:** GitHub POST. Manual findings (P8).
- **Touchpoints:** [pr_screen.py](../../../review_ticket/tui/pr_screen.py), [interactive_triage.py](../../../review_ticket/interactive_triage.py), [test_tui_pr.py](../../../tests/test_tui_pr.py).

#### P8 — Human code review track

- **Goal:** §10 record that automated curation cannot satisfy.
- **Deliverables:** `manual-review.json` for the PR SHA: completed flag, notes, manual findings (path, line, blocking, text), disposition, timestamp. Save and Complete do not publish. Request Changes hands off to P9. Diff view can be a scrolling excerpt of `diff.patch` for the selected file; a full editor is out of scope. Duplicate suppression against selected automated findings by path, line, and normalized body.
- **Out of scope:** Launching the app. Replacing `human-review.json`.
- **Touchpoints:** New screen, [workflow.py](../../../review_ticket/workflow.py) writer modeled on `save_snapshot_review`.

#### P9 — GitHub composition and publication

- **Goal:** §13 and the publication half of scenarios F and J.
- **Deliverables:** Checklist of automated and manual findings, editable general comment (functional notes can be inserted when P11 has saved them). Stable Approve / Comment / Request Changes. Preview shows repo, PR, SHA, outcome, comment, selected inline bodies and locations, and omitted findings. Authorize calls `publish_review` with `yes=True` and the chosen event, after a live HEAD check. Approve stays disabled until manual review is complete and functional testing for that SHA passed. Comment stays disabled until manual review is complete. Request Changes is enabled when the reviewer confirmed a blocker on the automated, manual, or functional track. Append a publication receipt; do not drop earlier ones. Failure leaves the draft and shows the error. Retry of the same fingerprint does not create a second GitHub review. Return to the hub showing the receipt outcome, not a merely selected event.
- **Out of scope:** Ticket Jira reject (P12). A separate `pr comment` button.
- **Touchpoints:** [publish_review](../../../review_ticket/workflow.py), [findings.py](../../../review_ticket/findings.py), new compose view.

#### P10 — Test environment view

- **Goal:** §11 status and launch actions.
- **Deliverables:** Show profile presence, image, digest, SHA match, launched or not, and the config path. Prepare / Fetch / Launch call the existing functions for the selected PR SHA. Failure renders `BLOCKED` and does not open Request Changes. Uncertainty when provenance is missing. Operator can still run the printed CLI command outside the TUI. Do not edit compose YAML in the TUI.
- **Out of scope:** Recording pass/fail.
- **Touchpoints:** [workflow.py](../../../review_ticket/workflow.py) test helpers, new view. Mock Docker the way [tests/support.py](../../../tests/support.py) already does.

#### P11 — Functional testing track

- **Goal:** §12 capture, including the split between operational result and disposition.
- **Deliverables:** Extend `record_tests` (or a sibling writer) with steps, observed, expected, plan reference, disposition, and timestamp, still storing digest and SHA. Pass / Fail / Blocked buttons. Disposition Approve / Comment / Request Changes, not inferred from the operational result. Environment block cannot select Request Changes by default. Save does not publish. A blocking disposition offers the P9 Request Changes path. `--revise` still required to replace a saved result.
- **Out of scope:** Docker lifecycle (P10). Ticket draft text (P12).
- **Touchpoints:** [record_tests](../../../review_ticket/workflow.py), [reports.test_results_markdown](../../../review_ticket/reports.py), new screen.

#### P12 — Ticket disposition

- **Goal:** §15 and the Jira half of scenarios F, G, and H.
- **Deliverables:** Hub dock Approve enabled only when testing notes were accepted, readiness/analyzers passed, every included PR has the required tracks for its current SHA, no blocking disposition remains, and each PR has the required GitHub receipt. A published Comment does not count as Approve. Approve records the decision and then Yes/No for `approved_status`. Reject builds a draft from blocking PRs only (code and functional), then the P1 sequence to In Progress. Receipt distinguishes saved, posted, transitioned, declined, and failed. One failing PR is enough to reject the ticket. CLI `leave` stays headless.
- **Out of scope:** Per-PR GitHub composition.
- **Touchpoints:** [record_disposition](../../../review_ticket/workflow.py), [return_comment](../../../review_ticket/reports.py), hub from P5.

#### P13 — Status track summary

- **Goal:** Landing screen shows the three tracks and the next action from local files.
- **Deliverables:** Extend the projection and markdown: issue title if present in `issue.json`, per-PR track labels, publication from receipts, last `session.last_updated` and per-artifact timestamps you already store (`captured_at`, `recorded_at`, `published_at`). No Jira or GitHub calls on paint or quit. Opening a PR still must not write `active_pr`.
- **Out of scope:** Performing those actions from the status screen.
- **Touchpoints:** [status_projection.py](../../../review_ticket/status_projection.py), [status_format.py](../../../review_ticket/tui/status_format.py), [status_screen.py](../../../review_ticket/tui/status_screen.py).

#### P14 — SHA change and explicit refresh

- **Goal:** Scenario I.
- **Deliverables:** When `pr_shas` for one ref changes, keep the old commit directory, mark that PR’s three tracks and receipts historical for the new HEAD, and leave other PRs and the testing-notes decision unchanged. Hub and status show stale versus current. Publication refuses a payload whose inline locations are not on the new diff, in addition to the existing live HEAD check. Historical snapshots open read-only. Refresh on readiness and status re-runs `resume` only when the operator asks.
- **Out of scope:** Cross-PR dependency analysis.
- **Touchpoints:** [_sync_pull_request](../../../review_ticket/workflow.py), projections from P5 and P13, [publish_review](../../../review_ticket/workflow.py).

### Verifier briefs

#### P1 — verification

- **Must prove:** Panel replaces controls in one dock. Approve and Reject stay in the same positions when emphasis changes. Save does not call Jira or GitHub. Yes and No are independent. Receipt shows failure without clearing the draft.
- **Commands / probes:** New unit tests around the state machine. A headless app test that mounts the panel only.
- **Regression watch:** None yet; notes tests start failing only when P2 adopts it.

#### P2 — verification

- **Must prove:** Scenario A stores acceptance and does not write `actions.jsonl`. Scenario B keeps notes visible, posts only after Yes, transitions only after a second Yes, and a failed post leaves the transition hidden. Re-opening shows the saved draft. Deny does not add a successful action.
- **Commands / probes:** `pytest tests/test_tui_testing_notes.py`. Add a case that the description pane is hidden and the notes pane is shown during edit.
- **Regression watch:** CLI `notes --reject` without `draft_body` still uses the template (`test_cli_decide_notes_reject_without_draft_body_uses_template`).

#### P3 — verification

- **Must prove:** Scenario C: two ready PRs do not make the ticket ready while one Bugbot finding is unaddressed. Reject draft names that PR and SHA and omits clean checks. `WAITING` has no Approve. Screen construction does not call the runner.
- **Commands / probes:** Headless test with fixtures patterned on [test_tui_status.py](../../../tests/test_tui_status.py). Workflow test that the filtered draft differs from today’s all-findings `--return` text.
- **Regression watch:** `decide_analyzers` CLI `--return` behavior for operators who want the old full draft. If the CLI text changes, update [test_acceptance.py](../../../tests/test_acceptance.py) in this package and say so.

#### P4 — verification

- **Must prove:** After automated findings are saved, `resume` can reach virtualization without `publication.json`. `publish-review --event APPROVE` is rejected by the eligibility predicate before functional pass. A second PR’s files are addressable without setting `pr_scope` to `single`. Old `human-review.json` still loads.
- **Commands / probes:** `pytest tests/test_acceptance.py tests/test_save_snapshot_review.py`. New tests for the predicate and the identity argument.
- **Regression watch:** Any test asserting `next_command` contains `publish-review` immediately after human save. Idempotent republish of an identical payload must still succeed.

#### P5 — verification

- **Must prove:** Three PRs render three track rows. A local disposition is not labeled published. Esc does not write `session.json`’s `active_pr`. Disabled ticket Approve is visible while a blocker exists.
- **Commands / probes:** Headless hub test with on-disk artifacts only.
- **Regression watch:** [test_open_pr_leaves_active_pr_and_sha_unchanged](../../../tests/test_tui_pr.py).

#### P6 — verification

- **Must prove:** Scenario D labels. Mount does not invoke the reviewer runner. Generate selected runs one identity. Missing `reviewer_command` leaves `findings.json` absent and shows import instructions. A failed runner leaves a retryable error.
- **Commands / probes:** Headless test with `ScriptedRunner`.
- **Regression watch:** [test_reviewer_adapter.py](../../../tests/test_reviewer_adapter.py) and `run-review` on the active PR from the CLI.

#### P7 — verification

- **Must prove:** Scenario E: exclude, edit, keep; save writes `human-review.json`; `actions.jsonl` unchanged; proposed payload omits the excluded finding. Second save without `--revise` is refused. Must-fix from the agent does not set a published event.
- **Commands / probes:** `pytest tests/test_tui_pr.py` plus an include/exclude case.
- **Regression watch:** Close still writes nothing. Stale banner still names both SHAs.

#### P8 — verification

- **Must prove:** Completing manual review writes `manual-review.json` and does not write `publication.json`. GitHub Approve eligibility is still false if this file is missing. A manual finding with the same path, line, and body as a selected automated finding is not duplicated in the preview list.
- **Commands / probes:** New headless screen test and a payload-merge unit test.
- **Regression watch:** `save_snapshot_review` still refuses when `findings.json` is missing.

#### P9 — verification

- **Must prove:** Preview matches the authorized payload. Request Changes works without a functional result when a blocker was confirmed. Approve and Comment stay disabled without manual review. Approve stays disabled without a passing functional result. HEAD mismatch blocks and keeps the draft. A failed `create_review` journals failure and does not write a success receipt. Repeating the successful fingerprint does not call create again. Hub shows Comment and Approve as different labels.
- **Commands / probes:** Workflow tests beside the existing `publish-review` cases in [test_acceptance.py](../../../tests/test_acceptance.py). One headless preview test.
- **Regression watch:** Skip path and remote-match path in `publish_review` still avoid a duplicate POST.

#### P10 — verification

- **Must prove:** Missing profile, missing digest, and launch `ToolError` render `BLOCKED`. A digest fetched for another SHA is not shown as evidence for this SHA. Buttons call prepare/fetch/launch only when pressed.
- **Commands / probes:** Headless test with the scripted Docker runner from [tests/support.py](../../../tests/support.py).
- **Regression watch:** `launch_environment` still refuses a missing fetch. Compose-down is still not invoked.

#### P11 — verification

- **Must prove:** Pass plus Comment stores both fields. Fail plus Request Changes stores steps and evidence and does not publish. Blocked does not set Request Changes. Result SHA or digest mismatch is not a current pass. Save is idempotent until `--revise`.
- **Commands / probes:** Extend record-tests workflow tests and add a headless screen test.
- **Regression watch:** CLI `test record --result pass` still works with the new optional fields defaulted.

#### P12 — verification

- **Must prove:** Scenario H enables ticket Approve only after every PR is complete and published with Approve where required. One Request Changes receipt disables ticket Approve and the reject draft names that PR only. Comment receipt is not treated as approval. Jira comment Yes and transition Yes are separate; a failed transition retries without a second comment. Testing-notes rejection is not required before this path.
- **Commands / probes:** Headless hub test with fixtures. Workflow test for the all-PR predicate.
- **Regression watch:** CLI `disposition --choice leave` and `--override` still behave.

#### P13 — verification

- **Must prove:** Status paint performs no runner calls. Three PRs show track labels from disk. Quit does not modify `session.json`. A PR row still opens the downstream screen without writing `active_pr`.
- **Commands / probes:** `pytest tests/test_tui_status.py`, updated expectations.
- **Regression watch:** Missing session copy stays “No review session exists yet.”

#### P14 — verification

- **Must prove:** Scenario I: after SHA B replaces SHA A, A’s findings, manual notes, test results, and receipts remain readable and are marked historical. B is not approved. The other PR is unchanged. Testing-notes acceptance remains. Publish of A’s inline comments against B is refused. Refresh is the only path that calls the network from readiness or status.
- **Commands / probes:** Workflow test around `_sync_pull_request` plus a hub projection test.
- **Regression watch:** Existing stale-snapshot behavior in [test_tui_pr.py](../../../tests/test_tui_pr.py) still explains a findings file that is not the stored SHA.

---

## Suggested implementation order

**Canonical package sequence:** P1 → P2 → P3 → P4 → P14 → P13 → P5 → P6 → P7 → P8 → P9 → P10 → P11 → P12

P2 and P3 can be staffed together after P1. P4 can start in parallel with P2 and P3; it must finish before P14.

### Build order rationale

Testing notes and readiness are ticket gates. They already have workflow functions and do not need the three-track schema, so they land first and scenarios A–C become testable quickly.

The track model (P4) and SHA rules (P14) land before the hub. Later screens then read one status vocabulary. P13 updates the landing page as soon as that vocabulary exists, while status remains local.

Publication (P9) is before the Docker screens so early Request Changes does not wait on virtualization. Approve stays disabled until P11 writes a passing functional record, which is the §13.4 gate. Environment and functional screens follow so scenario G and the Approve path of scenario H have evidence. Ticket disposition is last because its Approve predicate is the conjunction of those gates. Reject on the hub can be verified as soon as P9 and P12 are both present; full Approve waits for P11.

Doing P14 immediately after P4 avoids building the hub against a single immortal SHA.

---

## Test and fixture resources

| Asset | Use |
|-------|-----|
| [tests/test_tui_testing_notes.py](../../../tests/test_tui_testing_notes.py) | Scenarios A, B, and Jira failure |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | Three-PR local status |
| [tests/test_tui_pr.py](../../../tests/test_tui_pr.py) | Triage, stale banner, no session write |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) | CLI order, publish idempotence, virtualization |
| [tests/test_save_snapshot_review.py](../../../tests/test_save_snapshot_review.py) | Save without `resume` |
| [tests/support.py](../../../tests/support.py) | Scripted runner, Docker guards |
| [tests/test_policy_and_findings.py](../../../tests/test_policy_and_findings.py) | Readiness and finding payload rules |
| Local `reviews/DOTNETIOT-2550/` and `reviews/DOTNETIOT-2099/` | Operator fixtures only; gitignored. Tests should keep using `tmp_path` |

**CI:** `pytest` with `textual` and `PyYAML`. No live `acli`, `gh`, or Docker. Windows is the operator platform; headless Textual tests are the CI path. A manual pass in a narrow terminal (about 80 columns) is still required for §3.1 and is not covered by CI.

---

## Cross-cutting risks summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| `resume` order change breaks CLI expectations and acceptance tests | High | P4 updates tests in the same change. `publish-review` remains the only GitHub review write. |
| TUI action calls `resume` or `authorize` and blocks or publishes early | High | Paint from disk. Mutations use `yes=True` only after Yes. No `on_mount` generation, fetch, or publish. |
| `human-review.json` overloaded as the manual review | High | New `manual-review.json`. Checklist in P4 learns the split. |
| Single `active_pr` cursor hides other PRs during generate/test/publish | High | Identity arguments in P4. Hub must not call `select_pr`. |
| Early Request Changes shipped in a way that also enables Approve | High | Separate predicates in P9. Verifier must try Approve before functional pass and see it disabled. |
| SHA move looks like the old “open stale findings” banner | Medium | P14 uses a different flag from `_select_open_snapshot`. |
| 80-column layout regresses on notes or status | Medium | Keep the existing terminal-size tests; add one narrow-width test per new screen. |
| Live credentials in reviewer or Docker env | Medium | Do not log command environments. Tests stay on `ScriptedRunner`. |
| Spec not marked approved, and §15.1 “org policy” is undefined | Medium | This map freezes the clarifications table. A spec edit that adds a policy file or a bug-writer screen needs a map refresh. |

---

## Related artifacts

- [spec.md](spec.md)
- [README.md](README.md)
- No `retro.md` or `gwt-scenario.md` in this bundle
- [tui-end-to-end-return implementation map](../tui-end-to-end-return/implementation.md) — notes and attach slice already in the tree; this map extends it
- [review-interactive-ui implementation map](../review-interactive-ui/implementation.md) — status and triage slice already in the tree
- [multi-pr-reviewer-integration implementation map](../multi-pr-reviewer-integration/implementation.md) — headless `run-review` and per-PR publish

Those three maps stay canonical for their own bundles. This map does not supersede them.
