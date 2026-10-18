# Interactive review presentation — Foundry-inspired operator UI

## Purpose and setting

The operator is shaping how **review-pilot** should present human work during peer review: reading automated findings, deciding accept/reject, editing explanations, and eventually other prompts (questions, PR feedback context). They pointed at the **Foundry Textual attach** client (`c:\repos\burtlo\foundry`, documented as `foundry attach`) as the **reference experience**, not as a library to depend on.

**evaluate-run not run—engine verdict omitted.** (No Foundry run path was supplied; this retro is CLI/UX design only.)

The conversation also explored review-pilot’s current triage path and a separate kps-dev-tools Spectre TUI; the operator later asked to **ignore the kps example** and keep Foundry as the sole UI reference.

## Experience in the operator's terms

After automated review produces artifacts under `reviews/<issue>/…/review/`, the operator wants to **stay in the terminal** and move through long reviewer output and per-finding detail without losing context. They care about **color**, a **scrollable main area** for narrative and explanations, and **obvious accept/reject affordances** (buttons, not memorizing single-letter commands). They explicitly do **not** want Foundry’s full operator surface: no run list, host socket, advance/retry lifecycle, or workflow engine—only the parts that help **read and decide** during PR review.

Today, `review-ticket … review interactive` is labeled “TUI” in plans and README, but the implementation is a **REPL** that reprints a text list and accepts `>` commands (`t`, `f`, `e`, `w`, `q`). File-based triage (`review-preview.md`, `human-review.json`) remains the fallback when the experience feels too thin for long-form review.

## Feedback investigations

### “Borrow Foundry’s UI, not the product”

*Operator signal: “I wouldn't want to depend on that library at all—this is about borrowing and implementing what is needed.”*

- **Expected:** Reuse the **look and interaction model** the operator already likes from Foundry attach, implemented inside review-pilot with no coupling to `foundry_cli` or the job host.
- **Observed:** Foundry’s attach UI is Textual-based, host-only RPC, and run-centric ([foundry `docs/features/foundry-tui.md`](file:///c:/repos/burtlo/foundry/docs/features/foundry-tui.md) on the operator machine). review-pilot has **no Textual dependency** today ([`pyproject.toml`](../../../pyproject.toml)); triage logic is already separated in [`interactive_triage.py`](../../../review_ticket/interactive_triage.py).
- **Friction cost:** Without a deliberate borrow, review-pilot will keep shipping a REPL that **under-delivers** on the name “interactive” / “TUI” and pushes operators back to editing JSON or scrolling static markdown in an editor—extra context switching during multi-PR loops ([multi-pr operator guide](../multi-pr-reviewer-integration/operator-guide.md)).
- **Touchpoints:** [`run_interactive_triage`](../../../review_ticket/interactive_triage.py), [`review interactive` CLI](../../../review_ticket/cli.py); preview copy in [`review_preview_markdown`](../../../review_ticket/reports.py) (“Without the interactive TUI…”); plan note preferring lighter UI in [multi-pr `implementation.md`](../multi-pr-reviewer-integration/implementation.md) (rich vs textual—operator preference now favors Foundry-shaped Textual patterns for buttons + scroll).
- **Interpretation:** The integration boundary should stay **file-backed** (`findings.json`, `human-review.json`, same structs as `human_document_from_state`). A new UI layer is a **second front end** on existing domain code, analogous to Foundry’s split between host protocol and attach client—but review-pilot’s “host” is the filesystem and workflow commands, not a socket.
- **Options and tradeoffs:**
  - **Optional `textual` extra** in review-pilot — real buttons and `VerticalScroll`; adds dependency weight (plan previously leaned “small rich UI”).
  - **Rich Live + markup only** — lighter, kps-like; weaker match for “buttons for accept and reject.”
  - **Vendor/copy minimal CSS and layout** from Foundry `tui/app.py` — no import; maintenance when Textual themes change.
- **Probe:** With one finding and a 40-line explanation plus suggested-change fence, does the operator complete accept/reject faster with buttons + scroll than with the current REPL? Time-on-task on a real DOTNETIOT-style review directory.
- **Status:** open

### Scrollable narrative during review

*Operator signal (paraphrased): “The scrolling window area is really great and something that would help during the review.”*

- **Expected:** Long automated narrative (`reviewer-report.md`), finding explanations, and diff-related context are readable **inside** the triage session with stable chrome (header, actions, progress)—not dumped repeatedly each command.
- **Observed:** Foundry run detail uses `VerticalScroll` with `#context-markdown` (`Markdown` widget) and separates scroll from `#action-panel` ([`foundry_cli/tui/app.py`](file:///c:/repos/burtlo/foundry/.cursor/foundry/cli/foundry_cli/tui/app.py) — `#run-scroll`, `#context-markdown`, `#action-panel`). review-pilot REPL calls `_render` on **every** loop iteration and lists all findings as plain lines ([`_render`](../../../review_ticket/interactive_triage.py)).
- **Friction cost:** Cognitive load when explanations are long; hard to compare “what the agent said” with location on the diff; encourages leaving the tool for IDE/browser.
- **Touchpoints:** [`reviewer-report.md` / `review-preview.md` generation](../../../review_ticket/reports.py); context files under `review/context/`; optional future surfacing of `diff.patch` hunks in the scroll pane (not in Foundry, high value for PR review).
- **Interpretation:** Primary pane should be **document-first** (markdown), secondary pane **decision-first** (buttons). Finding list can be a compact index (sidebar or top list) with one “current finding” detail in the scroll region.
- **Options and tradeoffs:**
  - **Single scroll: narrative + selected finding** — simple; may need in-pane headings to jump.
  - **Split: finding list + detail scroll** — closer to IDE diff review; more Textual layout work.
  - **Keep REPL as fallback** — required for CI/non-TTY; no scroll there.
- **Probe:** Which content blocks must appear in-scroll on v1: summary only, or summary + full `reviewer-report` + per-finding explanation + suggested change?
- **Status:** open

### Accept / reject with color and buttons

*Operator signal (paraphrased): “I love the colors and the interface for the ability to represent buttons for the reject and accept.”*

- **Expected:** Clear, themed **Accept** and **Reject** (and related actions) visible without reading a command cheat sheet; visual state for undecided vs decided findings.
- **Observed:** Foundry gate waits mount `Button` widgets with `variant="primary"` for options and rebuild `#action-panel` from wait kind ([`_action_panel_widgets`](file:///c:/repos/burtlo/foundry/.cursor/foundry/cli/foundry_cli/tui/app.py)). review-pilot uses `t <n>` toggle and list markers `[accept]` / `[reject]` / `[undecided]` in text ([`process_triage_command`](../../../review_ticket/interactive_triage.py)).
- **Friction cost:** Slower triage on many findings; easy to forget commands during long sessions; weak signal for “publish preview” impact until `w` save.
- **Touchpoints:** Same triage state machine; publish counts via [`preview_counts_from_state`](../../../review_ticket/interactive_triage.py) / [`review_preview_markdown`](../../../review_ticket/reports.py).
- **Interpretation:** Buttons should call the **same state transitions** as `t` / `f` / `e` today (or thin wrappers), so tests on `process_triage_command` and `human_document_from_state` remain valid. Header can show **inline vs summary-only** counts (already computed for REPL).
- **Options and tradeoffs:**
  - **Two primary buttons + must-fix toggle** — minimal Foundry borrow.
  - **Per-finding button row in list** — faster bulk triage; busier UI.
  - **Keyboard shortcuts bound to buttons** — keeps power-user speed (Foundry uses bindings + buttons).
- **Probe:** Should Reject hide the finding from publish preview immediately in the header counts (live), matching REPL behavior?
- **Status:** open

### Scope: presentation only, not Foundry workflow

*Operator signal (paraphrased): “We don't need to implement all the interface elements and certainly not the workflow system.”*

- **Expected:** No run list, host start prompt, `run.events` polling, advance/retry, execute authorization, or steward technical-context toggle unless review-pilot gains a real need later.
- **Observed:** Foundry attach includes `RunListScreen`, `HostPromptScreen`, operator history RPC, parked-run action panel, technical context markdown ([foundry TUI feature record](file:///c:/repos/burtlo/foundry/docs/features/foundry-tui.md)). review-pilot workflow already owns issue/PR/session steps in [`workflow.py`](../../../review_ticket/workflow.py) (`review interactive` is one command in a chain).
- **Friction cost:** Over-building would duplicate Foundry attach and confuse operators who use both tools; under-building leaves testing-notes and `authorize()` prompts on plain stdin.
- **Touchpoints:** [`_prompt_notes`](../../../review_ticket/workflow.py), [`authorize`](../../../review_ticket/authorize.py) — still line prompts; out of scope for v1 unless bundled into one “review session” screen later.
- **Interpretation:** **Phase 1** = `review interactive` Textual screen only. **Phase 2** (optional) = same visual language for testing-notes gate and publish authorize preview—still not a workflow engine.
- **Options and tradeoffs:**
  - **Triage-only Textual** — smallest slice; chain still mixes REPL-like prompts elsewhere.
  - **`review-ticket attach <issue>`** session browser — Foundry-like list of PRs/SHAs; larger scope.
  - **Unify all human prompts in one app** — best UX continuity; highest build cost.
- **Probe:** After triage Textual ships, do operators still hit stdin prompts often enough to justify phase 2 within one sprint?
- **Status:** open

### Naming mismatch: “TUI” vs REPL

*Operator signal (implicit from choosing Foundry attach as the target experience and from product docs referring to interactive TUI.)*

- **Expected:** `review interactive` feels like the Foundry attach run view: scroll + actions + theme.
- **Observed:** [README](../../../README.md) and [multi-pr orchestration progress](../multi-pr-reviewer-integration/orchestration-progress.md) record P5 “`review interactive` TUI” as complete; implementation is [`run_interactive_triage`](../../../review_ticket/interactive_triage.py) command loop. [`review_preview_markdown`](../../../review_ticket/reports.py) documents file triage “without the interactive TUI.”
- **Friction cost:** Trust gap—documentation promises a class of UI the binary does not provide; operators may not invest in learning commands.
- **Touchpoints:** Docs above; tests in [`test_interactive_triage.py`](../../../tests/test_interactive_triage.py) (REPL-oriented).
- **Interpretation:** Either deliver Textual and keep the name, or rename CLI/docs to “interactive (terminal)” until shipped—operator preference is clearly **deliver the UI**.
- **Options and tradeoffs:** Ship Textual behind optional extra vs rename now to “review triage” subcommand.
- **Probe:** On Windows terminal (PowerShell), does `textual` run clean in the operator’s default environment without breaking non-interactive pytest?
- **Status:** open

### Integrating “information, questions, PR feedback” (original ask)

*Operator signal (from session start): use a Foundry-like surface as the way to present “information, questions, PR feedback, etc.”*

- **Expected:** One terminal experience carries **context** (issue, PR, checks, narrative) and **human input** (decisions, answers, edits)—not scattered across markdown files, JSON, and ad hoc prompts.
- **Observed:** review-pilot already centralizes machine output in `findings.json`, human state in `human-review.json`, narrative in `reviewer-report.md` / `review-preview.md`, and headless reviewer context in `review/context/`. Foundry maps “information” to operator-history markdown and “questions” to `user_input` wait with `TextArea` per question ([Foundry action panel](file:///c:/repos/burtlo/foundry/.cursor/foundry/cli/foundry_cli/tui/app.py)).
- **Friction cost:** Without a unified presenter, “questions” during review remain either agent-side (Cursor chat) or file edits—disconnected from publish workflow.
- **Touchpoints:** [`reviewer_prompt`](../../../review_ticket/reports.py); future human-added findings (`human-review.json` `added`); GitHub publish in [`publish_review`](../../../review_ticket/workflow.py).
- **Interpretation:** v1 should not invent a new Q&A protocol; it should **render existing finding fields** and optional summary/event edits. “Questions” in the Foundry sense (clarifying Q&A) may appear later if review-ticket adds structured asks—UI pattern is already proven in Foundry as markdown + text areas + submit.
- **Options and tradeoffs:**
  - **Markdown-in-scroll only** — matches PR feedback reading.
  - **Inline edit explanation in `TextArea`** — matches Foundry clarifying answers; persists via existing `explanation` override in human review.
  - **Chat-style thread** — not in Foundry attach; would be new product scope.
- **Probe:** For the operator’s typical PR, what percentage of triage time is read vs toggle vs edit explanation?
- **Status:** open

## Cross-cutting design opportunities

1. **Document-first triage shell** — Foundry’s `#run-scroll` + `#action-panel` pattern applied to `TriageState`: header (issue, PR, SHA, publish preview), scroll (report + finding), actions (Accept, Reject, Must-fix, Edit, Save, Quit). Implement in `review_ticket/tui/` with optional `pip install review-ticket[tui]`; keep REPL fallback.

2. **Single domain core, two views** — Extend testing strategy: unit tests stay on `process_triage_command` / `human_document_from_state`; add headless Textual tests for layout/bindings (Foundry’s [`test_tui.py`](file:///c:/repos/burtlo/foundry/.cursor/foundry/cli/tests/unit/test_tui.py) as a pattern reference, not a dependency).

3. **Honest docs** — When Textual ships, align README, `review-preview.md` footer, and multi-pr guide with what “interactive” means; until then, retro records operator intent so implementation does not re-debate scope.

4. **Diff-aware scroll (review-pilot-specific)** — Foundry does not show PR hunks; adding a collapsible diff snippet in the scroll pane may outperform copying attach verbatim for PR feedback.

**Suggested build order (hypothesis):** optional Textual extra → triage screen wired to `load_triage_state` / save via `human_document_from_state` → header counts + accept/reject buttons → explanation `TextArea` → REPL fallback unchanged → docs → (optional) testing-notes / authorize screens.

## Evidence index

| Kind | Reference |
| --- | --- |
| Operator intent | Chat session 2026-10-17 — Foundry path `c:\repos\burtlo\foundry`; borrow-not-depend; buttons + scroll; exclude full Foundry workflow; exclude kps-dev-tools after clarification |
| External UI reference | [foundry-tui.md](file:///c:/repos/burtlo/foundry/docs/features/foundry-tui.md), `foundry_cli/tui/app.py` (`#run-scroll`, `#action-panel`, `Button`, `Markdown`) |
| review-pilot triage | [`review_ticket/interactive_triage.py`](../../../review_ticket/interactive_triage.py) |
| CLI entry | [`review_ticket/cli.py`](../../../review_ticket/cli.py) (`review interactive`) |
| Preview / naming | [`review_ticket/reports.py`](../../../review_ticket/reports.py) (`review_preview_markdown`) |
| Prior plan tension | [multi-pr-reviewer-integration/implementation.md](../multi-pr-reviewer-integration/implementation.md) (rich vs textual) |
| Tests | [`tests/test_interactive_triage.py`](../../../tests/test_interactive_triage.py) |
| Run evaluation | Not requested; no `run_path` |

**Uncertainty:** Exact Textual version and Windows terminal behavior not verified in this session; Foundry CSS tokens (`$primary-darken-2`, `variant="primary"`) are reference only until copied into review-pilot theme.
