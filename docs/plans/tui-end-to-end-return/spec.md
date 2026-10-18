# TUI end-to-end return for missing testing notes

Status: **approved** — 2026-10-17. From operator retro interview; mapped in [implementation.md](implementation.md).

## Source

- Bundle: [README](README.md)
- Retro: [retro.md](retro.md) — investigations: top-level attach, early-gate entry, missing-notes return in TUI, attach-before-run semantics
- Related: [review-interactive-ui/spec.md](../review-interactive-ui/spec.md) (v1 attach; this spec **supersedes** D7 and **narrows** D11 for the testing-notes gate only)

## Operator outcome

On a ticket such as DOTNETIOT-2099 (Ready for Peer Review, missing or inadequate testing notes), the operator runs **`review-ticket <issue> attach`**, sees the Jira issue context (link, description, team notes), decides accept or reject in the TUI, and—on reject—edits the return message, saves, posts to Jira, and transitions back to In Progress with **two** explicit authorizations—without leaving the attach session or falling back to `notes --reject` + separate `jira` CLI steps.

## Problem statement

Attach v1 is spelled `review attach`, gated on PR/SHA, and performs no Jira actions. Operators expect Foundry-like **`review-ticket <issue> attach`**, early access at the `jira-issue` gate, and in-TUI testing-notes review plus authorize flows. Detection and draft generation already exist in workflow; presentation and authorization are CLI-only.

## Scope

### In scope

- **CLI:** `review-ticket <issue> attach` as the **sole** interactive attach entry; **remove** `review attach`.
- **Entry guard:** Open attach when `session.json` exists for the issue **without** requiring `active_pr` / `active_sha`. Existing PR review screen behavior unchanged (snapshot required; no `run-review` from attach).
- **Testing-notes gate UI** (when workflow step is `jira-issue` and a testing-notes decision is required or in progress):
  - Jira **ticket link** (config-derived URL).
  - **Refresh from Jira** for issue fields needed to show **formatted** description and **team notes** (testing notes body); render in a scrollable region (markdown or equivalent consistent with attach v1).
  - **Accept** / **Reject** controls when workflow allows a decision; after a choice is recorded, those controls are **disabled** (not re-selectable without an explicit revise path if the product already supports `--revise` for notes).
  - **Reject path:** append a **TextArea** pre-filled with the generated rejection/return body (same content as today’s `_write_return_draft` / missing-notes path); **initial focus** in the text area; operator edits; **Save** (keyboard: Tab focus order includes Save) persists decision + draft via the same semantics as `decide_notes` / `notes --reject` and `return-comment.md`.
  - **Post comment:** append authorize UI with **Approve** / **Deny**; Approve runs the same mutation + preview/receipt/idempotency semantics as CLI `authorize` for `jira comment` (body from saved draft).
  - **Transition:** after successful post, append **second** authorize UI for **Approve** / **Deny** to run `jira transition` to the workflow’s in-progress status (e.g. recommendation from session/`step_jira`).
  - **Accept path:** **Accept** records `notes --accept` equivalent, advances workflow, returns operator to the **status screen** inside attach with updated `current_step`, outcome, and `next_command`.
- **Status screen:** Continues to project local session state; when at `jira-issue`, surface entry to the testing-notes view (or auto-present it when attach opens and that gate is active—implementation choice; operator must land on review UI without prior PR selection).
- **Docs:** README command table and attach flow describe `<issue> attach` only; DOTNETIOT-2099-style early return documented.

### Out of scope

- Foundry library, host socket, run list.
- Changing triage vocabulary or human-review decision model on PR screen.
- Live GitHub/Jira refresh on **status** or **PR triage** screens (unchanged from v1).
- `run-review`, `pr select`, **publish-review** authorize in this slice.
- Full UI for every workflow gate beyond testing-notes at `jira-issue` (other steps: status + `next_command` only until follow-up).
- Other return reasons beyond testing-notes gate (same UI pattern may extend later; not required AC here).
- Removing `review apply` / file triage.

## Decisions

| ID | Decision | Rationale | Retro link |
|----|----------|-----------|------------|
| D1 | Primary command: `review-ticket <issue> attach` | Foundry-shaped entry; no `review` before `attach` | Top-level attach |
| D2 | Remove `review attach` | Single spelling | Top-level attach |
| D3 | Relax `_require_identity` for attach open | Early `jira-issue` access | PR/SHA guard |
| D4 | Testing-notes scroll + accept/reject + reject TextArea + save + post + transition | Operator interview flow | Missing notes CLI-only |
| D5 | Jira refresh on testing-notes view open | Accurate bodies at decision time | Missing notes CLI-only |
| D6 | Post then separate transition authorize | Matches CLI chain | Missing notes CLI-only |
| D7 | Accept → workflow advance, stay in attach status | Session hub | Attach-before-run |
| D8 | One Textual app (status + PR screen + testing-notes flow) | Same interface as v1 attach | Cross-cutting hub |

## Assumptions

- When testing notes are **empty**, workflow still **recommends reject**; **Accept** is hidden or disabled (workflow does not offer `notes --accept` today). **Reject** remains the primary path for DOTNETIOT-2099-class tickets.
- **Deny** on authorize steps leaves session unchanged and keeps the operator on the same step to edit or retry.
- **Revise:** If a testing-notes decision already exists, behavior matches CLI `--revise` rules before a new accept/reject.
- Jira refresh for this screen is **limited** to fields needed for link, description, and testing notes—not a general “live dashboard” amendment to all attach screens.
- Non-TTY `attach` fails with a clear error pointing at non-interactive CLI paths (extend v1 behavior).

## Acceptance criteria

1. `review-ticket <issue> attach` on a TTY opens the Textual attach app. `review-ticket <issue> review attach` is **not** a valid command (parser/docs/tests updated).
2. With only `reviews/<issue>/session.json` and **no** `active_pr`/`active_sha`, attach **opens** and shows the status screen (no “Run the review entry point first” guard).
3. For `current_step` / workflow state at `jira-issue` with missing testing notes, attach presents the testing-notes experience without requiring `run-review`.
4. Opening that experience **refreshes** issue data from Jira and shows a **clickable/openable ticket link**, scrollable **formatted description**, and scrollable **team/testing notes** body.
5. Operator can choose **Reject**; Accept/Reject controls become **non-interactive** after the decision is saved.
6. On **Reject**, a **TextArea** appears with the **pre-populated** return/rejection body; focus is in the text area; operator can edit; **Save** persists the same artifacts and session decisions as `review-ticket <issue> notes --reject` (including `return-comment.md` / `return_draft`).
7. After save, UI presents **Post to Jira** with **Approve** / **Deny**; Approve uses CLI-equivalent **authorize** preview and receipt for the comment mutation.
8. After successful post, UI presents **Transition** (to in-progress status) with **Approve** / **Deny**; Approve uses CLI-equivalent authorize for transition.
9. On **Accept** (when notes are present and workflow allows), session advances as `notes --accept` would; attach shows the **status screen** with updated step and next recommended action.
10. PR review screen from attach remains unchanged: no snapshot → no triage actions; opening PR does not require identity guard at attach entry.
11. README documents early return via `attach` instead of the three-step CLI-only chain for the primary operator story.

## Verification plan

- **CLI tests:** `review attach` removed; `<issue> attach` registered; non-TTY error message.
- **Workflow integration tests:** attach entry without PR/SHA; reject save invokes same session/decision/draft paths as `decide_notes` reject.
- **Headless Textual tests:** testing-notes screen from fixture session (missing notes): render link + bodies after mocked `refresh_issue`; reject → TextArea → save; mocked authorize approve for comment then transition (deny leaves state).
- **Manual:** DOTNETIOT-2099 or equivalent—`review-ticket <issue> attach` from empty/missing-notes state through post + transition; accept path on a ticket **with** notes through to next `next_command` on status.

## Implementation hints (optional)

- Register `attach` on the issue subparser; delete `review` subparser `attach` and `run_review_attach` wiring from `review` only (keep other `review` commands).
- Replace or branch `_require_review_session` / `_require_identity` at attach **entry** only; PR screen keeps snapshot checks.
- New screen or mode under `review_ticket/tui/` driven by `step_jira` / session outcome; call `refresh_issue`, `decide_notes`, existing `jira_comment` / `jira_transition` through shared authorize helpers adapted for Textual (per review-interactive-ui deferred item).
- Reuse `testing_notes_decision_preview` / `_write_return_draft` for initial TextArea content.

## Deferred / follow-up

- Authorize screens for **publish-review** and other gates in the same visual language.
- Action buttons on status for arbitrary `next_command` beyond testing-notes.
- Rename/product copy: “issue session” vs “commit review snapshot” in docs.
- Extend reject/return UI to non-testing-notes return reasons.
