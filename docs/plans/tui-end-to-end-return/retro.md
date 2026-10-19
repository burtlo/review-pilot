# End-to-end peer-review return inside the attach TUI

## Purpose and setting

The operator is peer-reviewing Jira issue **DOTNETIOT-2099**, which is in **Ready for Peer Review** and has **no testing notes**. The automated review path correctly surfaced the missing notes. They wanted a single terminal session—modeled on **Foundry attach**—to open the review UI, compose or confirm a **rejection / return comment**, **post it to Jira**, and **move the issue back to In Progress**, without leaving the TUI.

**evaluate-run not run—engine verdict omitted.** (No `.foundry/runs/{run_id}` path was supplied; this retro is CLI/TUI workflow design.)

## Experience in the operator's terms

The operator tried `review-ticket DOTNETIOT-2099 attach` (issue key before the verb `attach`). The CLI rejected `attach` as a top-level command. Their intent was not only findings triage after `run-review`, but the **early return** path when testing notes are absent.

**Follow-up (operator):** They want to **see what would be generated**, **preview** it, **edit in a text area in the TUI** if they choose, **post** it to the Jira ticket, then **move** the ticket—without leaving an interactive session. That is the target experience for missing-notes return (and likely other return reasons later).

## Feedback investigations

### Top-level `attach` vs `review attach`

*Operator signal: “I wanted to run `review-ticket DOTNETIOT-2099 attach`.”*

- **Expected:** A single memorable entry point—`attach` on the issue—that opens the interactive review session (analogous to `foundry attach`).
- **Observed:** Parser error from the operator terminal: `invalid choice: 'attach'`; valid commands are `status`, `assess`, `notes`, `run-review`, …, `review`, … ([`build_parser`](../../../review_ticket/cli.py)). The Textual UI is registered only under **`review attach`**: `review-ticket <issue> review attach` ([`attach_parser`](../../../review_ticket/cli.py), [`run_review_attach`](../../../review_ticket/cli.py)).
- **Friction cost:** Immediate dead end before any UI; reinforces doubt about whether a “TUI-first” product exists for this ticket state.
- **Touchpoints:** [`review_ticket/cli.py`](../../../review_ticket/cli.py) (`review` subparser + `attach`); [README command table](../../../README.md); [review-interactive-ui spec](../review-interactive-ui/spec.md) (command name D7).
- **Interpretation:** The product borrowed the **word** attach from Foundry but kept **issue-scoped CLI grammar** (`<issue> <command> …`). Operators who think “attach to this ticket/run” naturally omit the `review` namespace. This is naming/grammar mismatch, not a missing implementation behind the wrong flag.
- **Options and tradeoffs:**
  - **Alias** `review-ticket <issue> attach` → `review attach` — low cost; two ways to spell the same thing.
  - **Top-level `attach` subcommand** that opens a **session hub** (status + gates + triage) — matches mental model; blurs separation between `review` (human-review artifacts) and workflow gates.
  - **Document only** — zero code; leaves repeat friction for Foundry users.
- **Probe:** In onboarding, do operators who know Foundry try `<issue> attach` first? If yes, alias or hub is justified before adding more TUI screens.
- **Status:** open

### `review attach` opens only after PR + SHA are selected

*Operator signal (paraphrased): Open attach on a ticket still blocked on testing notes, before a full review run.*

- **Expected:** Attach shows **where the review is** (including “testing notes missing—return recommended”) and offers the next human actions.
- **Observed:** `run_review_attach` calls [`_require_review_session`](../../../review_ticket/workflow.py) → [`_require_identity`](../../../review_ticket/workflow.py), which raises if `active_pr` or `active_sha` is missing: *“Run the review entry point first.”* The Textual [`StatusScreen`](../../../review_ticket/tui/status_screen.py) projects local session state, but the CLI gate runs **before** the app starts ([`run_review_attach`](../../../review_ticket/cli.py)).
- **Friction cost:** For DOTNETIOT-2099-style tickets, the operator cannot open the status document at the **jira-issue** gate even though that gate is when they need to act; they must use plain CLI commands first.
- **Touchpoints:** [`step_jira_issue` missing-notes branch](../../../review_ticket/workflow.py) (`next_command` → `notes --reject`); [`ReviewTicketApp`](../../../review_ticket/tui/app.py); [spec out-of-scope](../review-interactive-ui/spec.md) (“Starting … testing-notes prompts … from this UI”).
- **Interpretation:** Attach was scoped as **post–`run-review` triage** (spec D2, D11), while the operator’s scenario is **pre-review return**. The status screen is a good fit for surfacing `ACTION_REQUIRED`, but the entry guard ties attach to PR/SHA selection.
- **Options and tradeoffs:**
  - **Relax guard:** allow `review attach` whenever `session.json` exists; PR screen still requires snapshot files — status-only mode for early gates.
  - **Separate `review-ticket <issue> attach` hub** that does not call `_require_identity` — clearer product story; two attach entrypoints unless unified.
  - **Keep guard; CLI-only early return** — smallest code; contradicts “all in TUI.”
- **Probe:** Should the status document list **action buttons** for the current `next_command` (e.g. “Reject testing notes”) when `current_step` is `jira-issue`?
- **Status:** open

### Missing testing notes: return draft, Jira comment, and transition are CLI-only

*Operator signal: “Generate the rejection note, choose to post it to the issue, then move the ticket back to In Progress—all within the TUI.”*

- **Expected:** One interactive flow: confirm return reason → edit draft → authorize Jira comment → authorize transition to In Progress.
- **Observed:** Workflow detects empty notes and recommends return ([`step_jira_issue`](../../../review_ticket/workflow.py), `next_command` `review-ticket {issue} notes --reject`). [`decide_notes`](../../../review_ticket/workflow.py) with `--reject` writes [`return-comment.md`](../../../review_ticket/workflow.py) via `_write_return_draft`. After reject, resume points to **`jira comment --body-file`** then separate **`jira transition --status … --yes`** ([README](../../../README.md)). [`disposition`](../../../review_ticket/cli.py) explicitly **does not** transition Jira. [`authorize`](../../../review_ticket/authorize.py) previews and prompts on stdin for mutating commands—not wired into Textual ([review-interactive-ui retro](../review-interactive-ui/retro.md) “Phase 2”).
- **Friction cost:** Context switch between TUI aspiration and three CLI steps with `--yes` confirmations; easy to stop after draft without posting or transitioning.
- **Touchpoints:** [`testing_notes_decision_preview`](../../../review_ticket/reports.py); [`jira_comment`](../../../review_ticket/workflow.py) / [`jira_transition`](../../../review_ticket/workflow.py); deferred item in [review-interactive-ui spec](../review-interactive-ui/spec.md) (“Testing-notes and publish-authorize screens in the same visual language”).
- **Interpretation:** The product **already automates detection and draft generation** for missing notes; the gap is **presentation and authorization** in one session. The operator’s ask aligns with spec **follow-up**, not with current attach v1 scope.
- **Options and tradeoffs:**
  - **Testing-notes + Jira gate screen** in Textual (preview markdown, edit, Post / Transition buttons calling existing workflow functions) — matches operator outcome; must reuse `authorize` semantics and receipts.
  - **“Return wizard” CLI** with single `--yes` for comment+transition — faster to ship; not TUI.
  - **Foundry-style wait panel** only for `notes --reject` path — narrow scope vs full hub.
- **Probe (answered):** Operator wants **preview the generated Jira body**, **edit in a Textual `TextArea` inside the TUI** (not `$EDITOR` or disk-only edit), then **post to the issue** and **move the ticket** in the same session. Authorize steps for Jira comment and transition should follow the same preview/confirm semantics as CLI [`authorize`](../../../review_ticket/authorize.py).
- **Status:** open — requirement captured; not implemented

### “Attach to the run” when there is no reviewer run yet

*Operator signal (paraphrased): Attach to the run to perform steps through the TUI.*

- **Expected:** “Run” means the **review-ticket session** for the issue (gates, drafts, decisions), not only the `commits/<sha>/review/` artifact tree after `run-review`.
- **Observed:** Docs and chains emphasize `run-review` → `review attach` → `publish-review` ([README](../../../README.md), [multi-pr operator guide](../multi-pr-reviewer-integration/operator-guide.md)). Missing-notes return stops before `run-review`; no `findings.json` path exists yet.
- **Friction cost:** Operator maps Foundry’s run-centric attach onto review-pilot; early-return work has no “run” directory to attach to, so the command they tried does not exist at the grammar level and the command that does exist is gated on PR/SHA.
- **Touchpoints:** [`reviews/<issue>/session.json`](../../../review_ticket/storage.py) lifecycle; workflow step order in [`workflow.py`](../../../review_ticket/workflow.py).
- **Interpretation:** Product language should distinguish **issue session** (Jira + gates) from **commit review snapshot** (automated findings). “Attach” could mean either; v1 implemented only the latter.
- **Options and tradeoffs:**
  - Rename/document: “attach = issue session UI” vs “attach = triage UI” — cheap clarity.
  - Unified session app covering gates 1–8 — high value, high build cost.
- **Probe:** Should `status` screen primary actions come from `session.next_command` and `outcome` rather than from PR rows only?
- **Status:** open

## Cross-cutting design opportunities

1. **Session hub vs triage-only attach:** Operators want Foundry-like **one front door** per issue. Today attach is a **specialized second door** after PR/SHA + reviewer output. Unifying under `<issue> attach` (or aliasing) plus a status-first screen that respects `current_step` would address both grammar and early-return scenarios without duplicating workflow logic.

2. **Authorize in Textual:** Any TUI that posts to Jira or GitHub must embed the same preview/receipt/idempotency as CLI [`authorize`](../../../review_ticket/authorize.py)—otherwise “all in TUI” reintroduces trust gaps. The [review-interactive-ui](../review-interactive-ui/) deferred “testing-notes and publish-authorize” item is the natural next slice for DOTNETIOT-2099-style returns.

3. **Priority:** For tickets blocked on missing testing notes, **return path in TUI** may deliver more operator time savings than additional findings-triage polish, because the ticket never reaches `run-review`.

## Evidence index

| Kind | Reference |
|------|-----------|
| Operator command | `review-ticket DOTNETIOT-2099 attach` (user account) |
| CLI error | `invalid choice: 'attach'` (terminal [1.txt](file:///c:/Users/lf10102100/.cursor/projects/c-repos-burtlo-review-pilot/terminals/1.txt) lines 1028–1030) |
| Correct triage entry | `review-ticket DOTNETIOT-2099 review attach` ([cli.py](../../../review_ticket/cli.py)) |
| CLI return path today | `notes --reject` → `jira comment --body-file … --yes` → `jira transition --status "In Progress" --yes` ([README](../../../README.md)) |
| Attach v1 scope | [review-interactive-ui/spec.md](../review-interactive-ui/spec.md) in/out of scope |
| Related retro | [review-interactive-ui/retro.md](../review-interactive-ui/retro.md) (presentation-only attach, phase 2 gates) |
