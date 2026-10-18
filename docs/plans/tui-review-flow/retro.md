# TUI review session — DOTNETIOT-2550 automated review

## Purpose and setting

The operator is peer-reviewing **DOTNETIOT-2550** in the review-ticket Textual attach UI (`review-ticket DOTNETIOT-2550 attach`), after accepting testing notes and moving through PR readiness into the review hub. Artifacts live under `reviews/DOTNETIOT-2550/`. No Foundry run directory was supplied.

**evaluate-run not run—engine verdict omitted.**

Earlier in the same session (summarized; not the primary record): on the readiness screen, **Approve** stayed disabled while KT.IoT.UI.Admin#354 had two Bugbot findings with developer attention and no stored analyzer decision. The operator expected Approve to mean `analyzers --accept-dispositions` and Reject to return the ticket (comment and optional Jira transition to In Progress). The implementation treats those as different decisions: Approve only records the readiness gate when every PR is already satisfiable; Reject records an analyzer `return` and can post/transition. They then ran `review-ticket DOTNETIOT-2550 analyzers --accept-dispositions` from the terminal and re-attached. The notes below are the operator's account of what happened next.

## Operator notes (verbatim)

Captured from the operator's message in this session, unchanged:

> I returned to the terminal and ran `review-ticket DOTNETIOT-2550 analyzers --accept-dispositions`. Now I returned to the ticket via attach. I open the review hub. I press the "Generated automated review" and it takes no action.
>
> This seems like a bug that it takes no action. I can press it a bunch of times.
>
> I select the first pull request  #156 KT.IoT.Zuul `b0c7a267e7b5` and then click on "Automated review: not started" I enter the PR automated review screen. It shows all the PRs that could be automatically generated and not just the one.
>
> This screen seems like the right place to start the automated review. I don't need the button that does not work on the other screen if I'm intended to come to this screen to generate the reviews.
>
> I press "Generate". At the bottom it says "Running automated review" and then I leave the screen to review the review hub again. When I return to this automated review page the message at the bottom is gone and the the review never appears.
>
> leaving with the ESC key appears to have canceled the automated review generation. Bug, I assumed it would continue.
>
> I press "Generate" At the bottom it says "Running automated review" and then I wait for the results and get this error message:
>
> ```
> Generation failed: Command failed (128): git worktree add --detach C:\repos\burtlo\review-pilot\reviews\DOTNETIOT-2550\prs\kwik-trip-iot-KT.IoT.Zuul-pr-156\commits\b0c7a267e7b574b00c59ebbd6ac52b7d00a759cf\checkout b0c7a267e7b574b00c59ebbd6ac52b7d00a759cf
> Preparing worktree (detached HEAD b0c7a26)
> fatal: 'C:/repos/burtlo/review-pilot/reviews/DOTNETIOT-2550/prs/kwik-trip-iot-KT.IoT.Zuul-pr-156/commits/b0c7a267e7b574b00c59ebbd6ac52b7d00a759cf/checkout' is a missing but already registered worktree;
> use 'add -f' to override, or 'prune' or 'remove' to clear
> Select Generate to retry.
> ```
>
> I try generating second review for "#144 kwik-trip-iot/KT.IoT 6bbbf1214e22  Missing" This one completes after some time and I am able to access the review
>
> The interface to select what to include and exclude works and I save the changes.
>
> I return to the previous screen. This time I click on the third PR. #354 kwik-trip-iot/KT.IoT.UI.Admin. The interface says at the bottom that it is generating a review
>
> It seems clicking on the each of ther pull request entries causes a review to generate similar to pressing the "Generate" button. Because of that I have likely started and stopped many different reviews. The logs start to appear and overwrite over the TUI. Some work needs to be done to make the flow provide them on another panel that the user can switch to review what is happening.
>
> The layout of the automated code review screen is split left and right when I want it to split top and bottom. The findings above. The details below. The findings correctly displays everything wrapped except for the the finding title and the suggested changes.
>
> Unattaching from the run and then re-attaching to the run shows me a completely different view than previously shown. There isn't the screen with the above review information and the pull reqests at the bottom with the checklist of status of the different automated review, manual code review, and manual testing. ITs showing the page with the analyzers and the prs at the bottom.
>
> Opening up the links for each PRs that do have reviews shows an interface with the automated review issues at the top, automated review notes in the center, and disposition in the bottom. This screen is split into thirds when really the buttons panel, the third one could be smaller and close to the bottom. The middle summary could be widened. With those changes that would actually be the more desirable interface for the automated results.

## Experience in the operator's terms

After the CLI analyzer acknowledgement, attach should have put them back in the review they had already started. The hub offered a control that looked like “start the automated review” and did nothing. The screen that actually starts generation lists every PR, treats a row click as Generate, and treats Escape as cancel. One cancelled Zuul checkout then blocked a retry with a stale git worktree registration; KT.IoT#144 succeeded and triage (include/exclude, save) worked. UI.Admin started generating because the row was clicked. Reviewer logs painted over the TUI. The findings screen is a left/right split with titles and suggested changes that do not wrap. Leaving attach and coming back lands on the status/analyzers page, not the hub.

## Feedback investigations

### Hub “Generate automated review” does nothing

*Operator signal: “I press the "Generated automated review" and it takes no action. This seems like a bug that it takes no action. I can press it a bunch of times.”*

- **Expected:** The hub control that names automated-review generation starts that work, or it is not presented as a pressable action.
- **Observed:** Operator account, hub after re-attach. In the current tree the hub button label is the block’s next action. When automated review has not started, that string is `Generate automated review` ([`_next_action`](../../../review_ticket/hub_projection.py)). [`ReviewHubScreen.on_button_pressed`](../../../review_ticket/tui/hub_screen.py) handles only “Publish GitHub review”, “Prepare test environment”, and “Complete functional testing”. A enabled “Generate automated review” press falls through with no navigation and no error. (The operator’s wording was “Generated”; the label in code is “Generate”.)
- **Friction cost:** Repeated clicks with no feedback. Trust that the hub is the place work starts is spent before they find the track row.
- **Touchpoints:** [`on_button_pressed`](../../../review_ticket/tui/hub_screen.py), [`_next_action`](../../../review_ticket/hub_projection.py). Opening the automated track does navigate: [`_open_track`](../../../review_ticket/tui/hub_screen.py) pushes [`AutomatedReviewPrepareScreen`](../../../review_ticket/tui/prepare_screen.py) and does not pass the selected PR.
- **Interpretation:** The next-action button is a partial dispatcher. Copy says the next step is generation; the handler does not implement that step. Fact: the fall-through is in the current handler. Hypothesis: the operator pressed that button (wording is one tense off from the label).
- **Options and tradeoffs:**
  - **Route that label to the prepare screen** (and pass the selected PR). Small fix; still two places that mean “generate” if the prepare screen also has Generate.
  - **Drop the hub button for steps the track list already opens.** Matches the operator: they do not need a dead button if the prepare screen is the generator. Downside: the hub loses a single “do the next thing” affordance unless every next action is either removed or implemented.
- **Probe:** With automated review not started, press the hub next-action button once. Does the UI change at all? If not, either wire it to the prepare screen for that PR or remove it until it has a handler.
- **Status:** open

### Prepare screen is ticket-wide, and row click generates

*Operator signal: “It shows all the PRs that could be automatically generated and not just the one.” And: “clicking on the each of ther pull request entries causes a review to generate similar to pressing the "Generate" button.”*

- **Expected:** Choosing Zuul#156’s “Automated review: not started” opens generation or triage for that pull request. A list click selects. Generate is an explicit button.
- **Observed:** Operator account. [`_open_track`](../../../review_ticket/tui/hub_screen.py) pushes `AutomatedReviewPrepareScreen` with no focus ref, and [`project_automated_review_prepare`](../../../review_ticket/prepare_projection.py) builds a row per in-scope PR. [`on_list_view_selected`](../../../review_ticket/tui/prepare_screen.py) calls `_row_action`, which calls `_start_generation` when `generate_enabled` is true (missing/stale/failed). The screen docstring says “Generation runs only on button press”; the list handler violates that. Busy copy is `Running automated review…` ([`_set_busy`](../../../review_ticket/tui/prepare_screen.py)). Buttons are “Generate Selected” and “Generate All Missing”; the operator said “Generate”.
- **Friction cost:** Accidental long reviewer runs, including overlapping starts and stops (see the next investigation). The operator also had to orient in a three-PR table after selecting one PR.
- **Touchpoints:** [`AutomatedReviewPrepareScreen`](../../../review_ticket/tui/prepare_screen.py), [`PreparePrRow.generate_enabled`](../../../review_ticket/prepare_projection.py).
- **Interpretation:** Selection and commit are the same gesture. That is why clicking #354 started a review without a separate Generate press. The all-PR table is intentional in the projection; the hub does not narrow it.
- **Options and tradeoffs:**
  - **Highlight-only on click; generate only from the button.** Stops accidental runs. Operators who wanted one click to start lose that.
  - **Open a single-PR prepare/triage screen from the hub track, and keep the all-PR table as a separate “generate missing” view.** Matches “I came here for this PR.” More screens to maintain.
- **Probe:** On a missing row, click the row once and do not touch Generate. Does `Running automated review…` appear? If yes, split select from generate before any other prepare-screen work.
- **Status:** open

### Escape cancels generation; logs paint over the TUI

*Operator signal: “leaving with the ESC key appears to have canceled the automated review generation. Bug, I assumed it would continue.” And: “The logs start to appear and overwrite over the TUI. Some work needs to be done to make the flow provide them on another panel that the user can switch to review what is happening.”*

- **Expected:** Leaving the prepare screen returns to the hub while generation continues. Progress and reviewer logs stay in a panel the operator can open, not in the Textual frame.
- **Observed:** Operator account: busy line present, Escape to the hub, return to prepare, busy line gone, no review for Zuul. Generation is [`@work(thread=True, exclusive=True)`](../../../review_ticket/tui/prepare_screen.py) on the screen. Textual cancels a screen’s workers when the screen is removed; `exclusive=True` also cancels the previous worker when another generate starts. Escape is bound to `action_go_back` → `pop_screen` with no “job continues” path. Reviewer progress is process logging (for example `run-review: automated reviewer` in [`workflow.py`](../../../review_ticket/workflow.py)), which shares the terminal with Textual.
- **Friction cost:** Lost reviewer time, uncertainty about whether a run is alive, and a corrupted view when several starts overlap. The operator inferred they had started and stopped many reviews.
- **Touchpoints:** [`_generate_worker`](../../../review_ticket/tui/prepare_screen.py), [`action_go_back`](../../../review_ticket/tui/prepare_screen.py), logging in [`run_review` / `_ensure_diff`](../../../review_ticket/workflow.py).
- **Interpretation:** The busy line is screen-local UI state, not a ticket-level job. Popping the screen drops the worker, so the assumption “Escape means back, not cancel” is false in this implementation. Fact: exclusive screen worker. Hypothesis: each PR click cancelled the prior worker, which matches “started and stopped many different reviews.”
- **Options and tradeoffs:**
  - **App-level worker (or a small job record on disk) that survives screen pop**, with the busy line read from that job. Escape becomes navigation. Downside: need cancel as its own action, and a rule for two PRs at once. An in-process worker still dies if the operator quits attach.
  - **Block Escape while busy and say the run is tied to this screen.** Honest, but traps the operator for several minutes and does not fix log painting. **Rejected** by the operator (see decision).
  - **Send reviewer stdout/stderr to a file and a switchable log panel.** Fixes overwrite even if generation stays on the screen. Does not by itself make Escape safe.
- **Decision (operator, 2026-10-18):** Leaving the prepare screen must keep generation running. Escape is back, not cancel. Cancel, if it exists, is a separate control. Quoted: “I would expect that it would keep the job running.”
- **Probe:** Still open for the process boundary. Inside one attach session, the job must outlive the prepare screen. Does it also have to keep running after the operator quits attach entirely?
- **Status:** open — direction chosen; not implemented

### Zuul checkout retry: worktree registered but missing

*Operator signal: the `git worktree add --detach` failure for KT.IoT.Zuul#156 at `b0c7a267e7b5`, “missing but already registered worktree”, then “Select Generate to retry.” KT.IoT#144 completed.*

- **Expected:** Retry after a cancelled or failed generate creates the checkout or clears the stale registration and continues.
- **Observed:** Operator pasted the git stderr. Destination is `reviews/DOTNETIOT-2550/prs/kwik-trip-iot-KT.IoT.Zuul-pr-156/commits/b0c7a267e7b574b00c59ebbd6ac52b7d00a759cf/checkout`. [`add_worktree`](../../../review_ticket/checkout.py) runs `git worktree add --detach` and does not prune or remove a registration whose directory is gone. [`ensure_checkout`](../../../review_ticket/checkout.py) only reuses `dest` when that path exists and `rev-parse` matches. [`.review-ticket.yaml`](../../../.review-ticket.yaml) leaves `checkout_command` commented, so this default path is what ran. The same deep `reviews/.../checkout` worktree pattern is already discussed in [checkout-operator.md](../multi-pr-reviewer-integration/checkout-operator.md).
- **Friction cost:** Zuul could not be reviewed until someone clears git’s worktree list by hand. A cancelled run (previous investigation) is a plausible way to register the worktree and then lose the directory. That causal link is a hypothesis; the git error text is observed.
- **Touchpoints:** [`ensure_checkout`](../../../review_ticket/checkout.py), [`_ensure_diff`](../../../review_ticket/workflow.py).
- **Interpretation:** Retry is not safe after a partial checkout. Git still believes the path is a worktree; the tool only knows how to add.
- **Options and tradeoffs:**
  - **On this specific git error, `worktree prune` (or `remove`) and add once.** Unblocks retry. Risk: prune can drop other stale registrations the operator still wanted.
  - **Stop using `reviews/.../checkout` as the worktree path** and use the short org-clone path in the checkout operator notes. Avoids Windows path pain and stray registrations inside the review tree. Requires the operator’s `checkout_command` (or a new default) and does not by itself fix Escape-cancel.
- **Probe:** After the failure, `git -C <cache repo> worktree list` — is that checkout path listed while the directory is absent? If yes, a single prune-and-retry in `ensure_checkout` is the local repair; the path policy is the larger one.
- **Status:** open

### Findings layout: left/right, titles and suggested changes do not wrap

*Operator signal: “The layout of the automated code review screen is split left and right when I want it to split top and bottom. The findings above. The details below. The findings correctly displays everything wrapped except for the the finding title and the suggested changes.”*

- **Expected:** Findings stacked above detail. Finding titles and suggested changes wrap like the rest of the finding text.
- **Observed:** Operator account, after a successful #144 review (include/exclude and save worked). [`PrReviewScreen`](../../../review_ticket/tui/pr_screen.py) lays `#review-body` out horizontally (`#finding-list` width `2fr`, `#detail-scroll` width `3fr`). A `stacked` class switches to vertical only when `app.size.width < 100`. Titles are plain `Static` text in [`_select_index`](../../../review_ticket/tui/pr_screen.py) (`#finding-meta`) and list labels from [`_finding_label`](../../../review_ticket/tui/pr_screen.py). Suggested change is `#suggested-change` `Static`, not a wrapping markdown/text area.
- **Friction cost:** Wide terminals keep the unwanted split. Long titles and suggested edits are unreadable without horizontal scrolling or truncation, which undercuts triage they otherwise completed.
- **Touchpoints:** [`PrReviewScreen` CSS and `_apply_layout_mode`](../../../review_ticket/tui/pr_screen.py).
- **Interpretation:** Stacked layout exists but is a narrow-terminal fallback, not the review layout. Wrapping was applied to some finding chrome and not to title or suggested change.
- **Options and tradeoffs:**
  - **Always stack: list on top, detail below, and render title and suggested change in a wrapping widget.** Matches this note directly. Costs horizontal space for people who liked the side-by-side list on a wide monitor.
  - **Keep side-by-side above a width threshold but wrap those two fields.** Smaller change; does not meet “findings above, details below.”
- **Probe:** On the operator’s usual terminal width, is the body horizontal? If yes, change the default to stacked and re-check a long title and a multi-line suggested change.
- **Status:** open

### Re-attach opens the status page, not the hub

*Operator signal: “Unattaching from the run and then re-attaching to the run shows me a completely different view… the page with the analyzers and the prs at the bottom,” not the hub with automated, manual, and testing tracks.*

- **Expected:** Attach resumes the workspace they were in: hub (or the PR review), with track status for each pull request.
- **Observed:** Operator account. [`ReviewTicketApp.on_mount`](../../../review_ticket/tui/app.py) pushes [`StatusScreen`](../../../review_ticket/tui/status_screen.py) and, when testing notes are still undecided, the testing-notes screen. It does not push the hub. The hub is opened later from status (`Open review hub` / `h`). Status is the analyzers/checks document plus a PR list.
- **Friction cost:** Every re-attach looks like a different product step. The operator has to rediscover the hub to see track checklists.
- **Touchpoints:** [`ReviewTicketApp.on_mount`](../../../review_ticket/tui/app.py), [`StatusScreen`](../../../review_ticket/tui/status_screen.py), [`ReviewHubScreen`](../../../review_ticket/tui/hub_screen.py).
- **Interpretation:** Attach has no memory of “I am in the hub” or “I am triaging this PR.” The status screen is the root. That is why the analyzers page replaces the hub after unattach.
- **Options and tradeoffs:**
  - **If readiness is already accepted, attach pushes the hub on top of status.** One-step resume. Downside: status is one Escape further away; a wrong gate check could skip a screen they still needed.
  - **Persist the last screen (hub vs prepare vs PR triage) on the session and restore it.** Closer to “same view as before.” More states to define when artifacts moved while they were away.
- **Probe:** After a hub visit, quit attach and run attach again. If the first screen is always status, decide whether “readiness already recorded ⇒ open hub” is enough or whether the last screen must be stored.
- **Status:** open

### Triage chrome: disposition and buttons take a third of the screen

*Operator signal: “the automated review issues at the top, automated review notes in the center, and disposition in the bottom. This screen is split into thirds when really the buttons panel, the third one could be smaller and close to the bottom. The middle summary could be widened.”*

- **Expected:** Notes/summary get most of the height. Disposition and include/exclude actions sit in a short bar at the bottom.
- **Observed:** Operator account on PRs that already have reviews. Same [`PrReviewScreen`](../../../review_ticket/tui/pr_screen.py): finding list, detail scroll (narrative, explanation, suggested change), then docked `#disposition-row`, `#message`, and `#action-buttons`. Those docks are `height: auto` with no cap, so a full disposition row plus the action row competes with the narrative. Include/exclude and save on #144 did work; this note is layout, not a failed save.
- **Friction cost:** The text they are judging is squeezed. They described the widened middle as the desirable automated-results layout.
- **Touchpoints:** [`PrReviewScreen` CSS](../../../review_ticket/tui/pr_screen.py) (`#disposition-row`, `#action-buttons`, `#detail-scroll`).
- **Interpretation:** “Thirds” is the visual result of an uncapped bottom dock plus a vertical or horizontal split, not a deliberate three-pane spec. The operator wants the decision chrome collapsed, not removed.
- **Options and tradeoffs:**
  - **Cap the bottom dock to one or two lines and give `#detail-scroll` the rest.** Directly widens the summary. Very small screens may clip button labels unless the bar scrolls or wraps.
  - **Put disposition in the bottom bar and drop the duplicate action row.** More room, but mixes “GitHub disposition” with “include this finding.”
- **Probe:** With one long reviewer narrative, how many terminal rows does the bottom chrome use versus the narrative? If the chrome is about a third, cap it and re-measure before changing which buttons exist.
- **Status:** open

## Cross-cutting design opportunities

1. **One obvious generator, and it keeps running.** The hub button, the prepare list, and Escape currently mean three different things (nothing, start, cancel). Pick the prepare screen as the only generator, make row click mean select, and let a generate job outlive the screen. The operator confirmed the last part: leaving that screen keeps the job running.
2. **Resume the workspace on attach.** Status-as-root fights the hub the operator is actually using once readiness is done.
3. **Reviewer output is a panel, not the terminal.** Logs overwriting Textual and a missing progress line after Escape are the same hole: progress is not a first-class view.
4. **Triage reading layout.** Stacked findings, wrapping titles and suggested changes, and a short bottom bar are one layout change on `PrReviewScreen`, separate from generation.

Priority by impact: accidental cancel and the dead hub button block the review; the worktree retry blocks Zuul after a cancel; layout and re-attach waste time but did not stop #144 triage.

## Evidence index

| Item | Source |
| --- | --- |
| Verbatim session notes | This file, operator message 2026-10-18 |
| Job survives leaving the prepare screen | Operator follow-up the same day: “I would expect that it would keep the job running.” |
| Prior readiness mismatch | Same chat, summarized above; `decisions.readiness` vs `analyzers --accept-dispositions` |
| Issue artifacts | `reviews/DOTNETIOT-2550/` (Zuul#156 `b0c7a267…`, KT.IoT#144 `6bbbf121…`, UI.Admin#354) |
| Dead hub next action | [`hub_screen.py`](../../../review_ticket/tui/hub_screen.py) `on_button_pressed`; label from [`hub_projection.py`](../../../review_ticket/hub_projection.py) |
| Generate on row select; busy string; exclusive worker | [`prepare_screen.py`](../../../review_ticket/tui/prepare_screen.py) |
| Worktree add | [`checkout.py`](../../../review_ticket/checkout.py); operator git stderr quoted above |
| Attach root screen | [`app.py`](../../../review_ticket/tui/app.py), [`status_screen.py`](../../../review_ticket/tui/status_screen.py) |
| Findings layout | [`pr_screen.py`](../../../review_ticket/tui/pr_screen.py) |
| Engine verdict | **evaluate-run not run—engine verdict omitted.** |

Code links are a snapshot of the tree when this retro was written. The operator’s button name “Generated automated review” / “Generate” may not match the on-screen label character for character (`Generate automated review`, `Generate Selected`).
