# Review Ticket TUI — Comprehensive Design and Implementation Specification

**Status:** Design specification for implementation
**Application:** `review-ticket`
**Technology:** Python, Textual, Jira CLI (`acli`), GitHub CLI (`gh`)
**Primary objective:** Provide a consistent terminal interface for reviewing a Jira ticket and all associated pull requests, evaluating automated and human findings, conducting functional testing, publishing authorized feedback, and deciding the Jira ticket's disposition.

---

# 1. Product philosophy

The reviewer system coordinates a human-driven quality process. It does not replace the reviewer or automatically determine whether work should be accepted.

The operator must be able to:

1. Inspect the Jira issue and its testing notes.
2. Evaluate GitHub readiness checks and analyzer findings across all associated pull requests.
3. Generate and examine automated code reviews.
4. Conduct and record their own code reviews.
5. Run the application or services and record functional testing results.
6. Choose what feedback to publish to GitHub.
7. Approve or reject the overall ticket.
8. Authorize Jira comments and status transitions.

The interface must distinguish between:

- **Evidence:** What Jira, GitHub, automated tools, or the operator observed.
- **Review decisions:** What the human reviewer decided.
- **Publication:** What was actually submitted to GitHub or Jira.
- **Workflow state:** Which gates are complete, pending, blocked, or require attention.

These are separate concepts and must not be conflated.

## 1.1 Scope and identity

The hierarchy is:

```text
Jira Ticket
  |
  +-- Ticket-scoped testing notes review
  |
  +-- Pull Request #1
  |     HEAD SHA
  |       +-- Automated code review
  |       +-- Human code review
  |       +-- Human functional testing
  |
  +-- Pull Request #2
  |     HEAD SHA
  |       +-- Automated code review
  |       +-- Human code review
  |       +-- Human functional testing
  |
  +-- Pull Request #N
        HEAD SHA
          +-- Automated code review
          +-- Human code review
          +-- Human functional testing
  |
  +-- Overall ticket disposition
```

Testing notes are **ticket-scoped**.

All three pull-request review tracks are **PR/SHA-scoped**.

GitHub review publication is **PR/SHA-scoped**.

Jira feedback and transitions are **ticket-scoped**, although their content may cite particular PRs and SHAs.

A ticket can have one or many PRs. A PR can have many commits, but the current review targets its HEAD SHA. Earlier reviews must remain available as history.

---

# 2. Existing architecture and integration constraints

The existing application has:

- A CLI workflow that advances through sequential gates.
- A Textual TUI accessible through `review-ticket <ISSUE> attach`.
- A session state persisted in `reviews/<ISSUE>/session.json`.
- A Status screen.
- A Testing Notes screen.
- A PR review screen with finding triage.
- Local artifacts for GitHub checks, analyzer results, automated findings, human decisions, and publication receipts.

**Extend and refactor these components. Do not replace the existing workflow with a separate orchestration framework.**

The CLI remains the authoritative implementation of workflow steps and external operations. TUI actions should call the same underlying workflow operations rather than duplicate business logic.

The current read-only Status behavior and local PR review behavior should remain intact unless deliberately extended by this specification.

## 2.1 Main pipeline

```text
Jira issue
    |
    v
Testing notes decision
    |
    v
GitHub PR discovery and readiness
    |
    v
Analyzer findings / dispositions
    |
    v
Automated code review generation
    |
    v
Automated finding triage
    |
    v
Human code review
    |
    v
Virtualization / application setup
    |
    v
Human functional testing
    |
    v
GitHub review publication
    |
    v
Overall Jira ticket disposition
```

This is the normal successful path.

A confirmed blocking issue permits an **early return** without completing all subsequent stages.

In particular, a reviewer should not have to perform functional testing after discovering a confirmed blocking code defect that warrants returning the work.

The redesigned TUI may provide actions to invoke existing CLI operations. This is an intentional extension of the earlier CLI-only interaction boundary, not permission to automatically perform expensive or external operations.

---

# 3. Global TUI layout and interaction standards

## 3.1 Terminal-first layout

Target a normal terminal window, including approximately 80-column layouts.

Avoid requiring the reviewer to read two narrow columns of long-form prose.

Prefer horizontal sections stacked vertically:

```text
+----------------------------------------------------+
| Persistent context header                          |
+----------------------------------------------------+
| Summary / context panel                            |
+----------------------------------------------------+
| Main scrollable evidence                           |
|                                                    |
+----------------------------------------------------+
| Contextual decision / action panel                 |
+----------------------------------------------------+
| Keyboard shortcuts / status                        |
+----------------------------------------------------+
```

The context header and bottom action area should remain visible.

Evidence panels scroll independently of fixed controls.

A screen may use side-by-side selection and detail panes when appropriate for shorter content or sufficiently wide terminals, but long Jira descriptions and testing notes should use stacked full-width panels.

## 3.2 Context header

Display enough context to identify the material being reviewed:

- Jira issue key and title.
- Current workflow stage.
- Overall ticket outcome where appropriate.
- Active PR number, if applicable.
- Full SHA available, with shortened SHA for compact display.
- SHA freshness or stale warning.
- Current workflow recommendation or required action.

The reviewer must never accidentally mistake a historical PR review for the current HEAD.

## 3.3 Focus and navigation

Provide consistent keyboard navigation:

- `Tab` moves between relevant panes.
- Arrow keys navigate choices and scroll the focused area.
- `Enter` opens a selected item or activates an appropriate action.
- `Esc` closes expanded views or returns to the parent screen without discarding saved work.
- Named shortcuts may activate screen-specific decisions.
- A visible shortcut footer explains available actions.

Avoid overloading keyboard shortcuts in ways that cause destructive operations.

Focus and scroll positions should be preserved where practical when switching between review states.

## 3.4 Recommendation is not a decision

Pre-checks and automated findings may recommend accepting or rejecting.

Use that recommendation to visually emphasize the corresponding choice.

Do not make the reviewer's choice automatically.

Both options remain visible, occupy consistent positions, and have consistent dimensions.

**Changing a recommendation may change the highlighted button, but must never rearrange the buttons.**

---

# 4. Reusable decision panel

This is a shared interaction component for testing notes, PR readiness, automated review disposition, and overall ticket decisions.

It is a multi-state panel rather than a series of separate modal dialogs.

## 4.1 Panel states

```text
REVIEW
  |
  +-- Approve
  |      |
  |      +-- Save local decision
  |      +-- Advance if allowed
  |
  +-- Reject
         |
         v
     EDIT FEEDBACK
         |
         v
     SAVE DRAFT
         |
         v
     AUTHORIZE COMMENT
         |
         v
     AUTHORIZE TRANSITION
         |
         v
     RECEIPT / COMPLETE
```

Internal panel states:

1. **Decision:** Approve / Reject.
2. **Editing:** Pre-filled rejection feedback, editable by the reviewer.
3. **Saved:** Show locally saved feedback.
4. **Post confirmation:** Ask whether to post the Jira comment.
5. **Transition confirmation:** Ask whether to move the ticket to In Progress.
6. **Receipt:** Show which operations occurred, were declined, or failed.

Each state replaces the controls in the same bottom panel.

Do not continually append additional controls below the visible page.

## 4.2 Dynamic panel sizing

The panel begins as a compact Approve / Reject dock.

When the reviewer selects Reject, it expands upward into an editor.

The editor's height depends on the complexity of the evidence.

- Testing notes: relatively small editor, suitable for a short rejection.
- Multi-PR readiness: larger editor, potentially approaching half the terminal.
- Detailed code review: larger editor with independent scrolling.
- Functional testing: larger editor to accommodate descriptions and reproduction notes.

The expansion reduces the evidence panel's height rather than creating a long, globally scrolling page.

Evidence must remain accessible while editing feedback.

## 4.3 Draft editing

Every rejection editor starts with a useful generated draft.

The reviewer can:

- Read the draft.
- Change or replace its contents.
- Save it locally.
- Return to editing.
- Leave without publishing.

**Saving locally never posts externally.**

A saved draft survives leaving and returning to the screen.

If the reviewer declines publication, the draft remains saved.

## 4.4 Authorization sequence

After saving:

**Step 1 — Jira comment**

Show a preview of the exact content to be posted.

Ask: `Post this comment to Jira?`

Options: `Yes` / `No`.

**Step 2 — Jira transition**

Show the ticket key and target status.

Ask: `Move this ticket to In Progress?`

Options: `Yes` / `No`.

These are independent authorizations.

Declining a comment must not silently authorize or execute a transition.

A reviewer may deliberately choose not to post or not to transition. Record that decision and show the resulting incomplete or partial disposition accurately.

**Step 3 — Receipt**

Example:

```text
Jira feedback
  Draft saved       YES
  Comment posted    YES
  Status moved      YES
  Current status    In Progress
```

External operations must have success receipts. A failed operation must remain retryable.

Use the existing `actions.jsonl` fingerprints to avoid duplicating successful external operations.

## 4.5 Generic authorization pattern

Reuse the preview / approve / deny / receipt interaction for:

- Jira comments.
- Jira transitions.
- GitHub review publication.
- Optional GitHub PR comments.
- Bug writer invocation, where implemented.

Do not confuse approval of an external action with approval of the code.

For posting and transitions, prefer `Yes / No` or `Post / Cancel`, rather than `Approve / Reject`.

---

# 5. Screen 1 — Jira issue and testing notes

## Purpose

Decide whether the ticket contains sufficient information for the reviewer to reproduce, test, and validate the requested change.

Existing functionality should be retained and the layout refined.

## Initial layout

```text
+----------------------------------------------------+
| DOTNETIOT-2550             PEER REVIEW    STEP 1/7 |
| Fix timezone handling in device history            |
+----------------------------------------------------+
| ISSUE DESCRIPTION                         [scroll]  |
|----------------------------------------------------|
|                                                    |
| Description and acceptance criteria                |
|                                                    |
+----------------------------------------------------+
| TESTING NOTES                             [scroll]  |
|----------------------------------------------------|
|                                                    |
| Extracted testing notes and relevant criteria      |
|                                                    |
|                                                    |
+----------------------------------------------------+
| Are the testing notes adequate?                    |
|                                                    |
| [       APPROVE       ] [       REJECT       ]     |
+----------------------------------------------------+
| Tab: Switch pane    Esc: Status                    |
+----------------------------------------------------+
```

The panes are **stacked vertically**, not side by side.

The testing notes should receive more available reading space than the issue description, approximately 60% of the evidence space when practical.

Both panels are independently scrollable.

The testing notes and acceptance criteria must remain accessible to the reviewer.

## 5.1 Automated pre-check

The application obtains the Jira issue and examines:

- Explicit testing notes.
- Jira testing-note fields or sections.
- Relevant issue comments.
- Acceptance criteria.
- Any existing assessment produced by the workflow.

The pre-check determines whether the information appears sufficient.

It may recommend:

- Accept.
- Reject.
- Needs human judgment.

If sufficient information exists, visually emphasize Approve.

If information is absent or obviously insufficient, emphasize Reject.

This is merely the default emphasis or focus. The reviewer retains full control.

Keep both buttons at equal width.

## 5.2 Approve behavior

When Approve is selected:

1. Store the ticket-scoped testing notes acceptance.
2. Preserve the relevant decision metadata.
3. Mark the gate complete.
4. Proceed to PR readiness when workflow state permits.

There is no SHA association and no GitHub action.

For implementations where the CLI must advance the session, invoke the existing workflow operation through an explicit TUI continuation action. Do not fabricate or bypass the authoritative session state.

## 5.3 Reject behavior

Selecting Reject changes the layout in place.

```text
+----------------------------------------------------+
| DOTNETIOT-2550             TESTING NOTES REJECTION  |
+----------------------------------------------------+
| ISSUE DESCRIPTION                       [collapsed] |
+----------------------------------------------------+
| TESTING NOTES                             [scroll]  |
|----------------------------------------------------|
|                                                    |
| Original testing notes remain visible              |
|                                                    |
+----------------------------------------------------+
| RETURN FEEDBACK                                    |
|----------------------------------------------------|
| There is insufficient testing information to       |
| validate this change. Please provide clear         |
| reproduction steps and expected results.           |
|                                                    |
|                                       [Save Draft] |
+----------------------------------------------------+
```

The issue description collapses to a small heading.

The testing notes **remain visible and scrollable**.

The Approve / Reject dock is replaced by a short editable text area.

After Save, the same area changes into:

1. Saved comment preview.
2. Post comment authorization.
3. Jira transition authorization.
4. Final receipt.

Do not open a separate screen for each stage.

If the operator wants to edit the saved draft, allow returning to the editor.

---

# 6. Screen 2 — PR discovery, checks, and analyzer findings

## Purpose

Show the readiness of every PR associated with the ticket before an automated code review is generated.

There may be one PR or many.

The screen initially uses locally captured reports and GitHub check artifacts.

A compact summary remains visible above the detailed, scrollable markdown.

## Layout

```text
+----------------------------------------------------+
| DOTNETIOT-2550              PR READINESS   STEP 2  |
+----------------------------------------------------+
| Overall: ACTION REQUIRED                           |
|                                                    |
| PR #428  abc1234    Checks PASS    Analyzers PASS   |
| PR #429  def5678    Checks PASS    Bugbot 1 OPEN    |
| PR #430  987abcd    Checks PASS    Analyzers PASS   |
+----------------------------------------------------+
| READINESS / ANALYZER REPORT               [scroll] |
|----------------------------------------------------|
|                                                    |
| #428                                                |
|   Build succeeded                                  |
|   Unit tests succeeded                             |
|   CodeQL complete                                  |
|                                                    |
| #429                                                |
|   Build succeeded                                  |
|   Bugbot: potential null reference                 |
|   src/Foo.cs:134                                   |
|                                                    |
| #430                                                |
|   All configured checks complete                   |
|                                                    |
+----------------------------------------------------+
| Ticket readiness decision                          |
|                                                    |
| [       APPROVE       ] [       REJECT       ]     |
+----------------------------------------------------+
```

Use clearly distinguished statuses for:

- Pending checks.
- Failed checks.
- Missing required checks.
- Missing expected analyzer checks.
- Analyzer findings needing disposition.
- Accepted findings or justified overrides.
- Ready.
- Blocked by environment/tooling.

## 6.1 Multiple PR aggregation

Readiness is a ticket-level gate composed from all associated PRs.

If any required PR fails an enforced gate, the ticket cannot pass that gate.

Do not let two clean PRs hide a blocking issue in the third.

A reviewer should still be able to inspect each PR's evidence independently.

Every summary row must show the PR identity and current HEAD SHA.

## 6.2 Analyzer findings

The detailed report may include:

- GitHub Actions checks.
- Build results.
- Unit and integration tests.
- CodeQL findings.
- Bugbot threads.
- Responses from the developer.
- Resolved versus unresolved items.
- Reviewer dispositions.

An analyzer check successfully completing does **not** mean its findings were addressed.

A Bugbot comment is not automatically a must-fix item.

The reviewer decides whether an unresolved issue is genuinely blocking, needs a developer response, or has been adequately addressed.

Support existing operations for accepting dispositions, returning work, and overriding with an explanation.

## 6.3 Approve

Approve is available only when the readiness gate is satisfiable.

A reviewer may explicitly acknowledge missing expected checks or analyzers where the existing policy permits it.

Record these exceptions.

Approve means:

> The PRs have passed the readiness and analyzer disposition gate and may proceed to automated code review.

It does **not** approve the PR on GitHub.

## 6.4 Reject

Reject uses the reusable decision panel.

Collapse the summary if needed, preserve the detailed report, and expand the feedback editor upward.

The default draft must include **only the PRs and findings requiring attention**.

Example:

```text
Requesting that this ticket return to In Progress.

PR #429 — SHA def5678
- Bugbot identified a potential null reference in
  src/Foo.cs:134.
- Please address the finding or explain why it
  does not apply.

The ticket can be reviewed again after the
blocking findings are resolved.
```

Do not list all successful checks or unrelated clean PRs.

The reviewer can freely edit the draft.

Then:

1. Save locally.
2. Authorize Jira comment.
3. Authorize Jira transition.
4. Show receipt.

## 6.5 Incomplete readiness

For checks still running, show `WAITING`, rather than asking the reviewer to approve or reject an unfinished gate.

Provide an explicit Refresh or Resume option.

For no PR discovered, provide a PR selection/manual reference action.

For failed checks, allow the reviewer to follow the configured return process.

Do not synthesize a successful readiness decision from incomplete evidence.

---

# 7. Screen 3 — Pull request review hub

This becomes the central workspace after readiness passes.

It manages the three review tracks for each PR/SHA.

**Every pull request has:**

1. Automated code review.
2. Reviewer-administered code review.
3. Reviewer-administered functional testing.

The ticket-level hub summarizes their states.

## Layout

```text
+----------------------------------------------------+
| DOTNETIOT-2550                 CODE REVIEW HUB      |
+----------------------------------------------------+
| PR #428  HEAD abc1234                              |
|                                                    |
|  [1] Automated review     Complete                 |
|  [2] Manual code review   Complete                 |
|  [3] Functional testing   Pending                  |
|                                                    |
|  GitHub review: Not published                      |
+----------------------------------------------------+
| PR #429  HEAD def5678                              |
|                                                    |
|  [1] Automated review     Complete                 |
|  [2] Manual code review   Changes requested        |
|  [3] Functional testing   Not required (returned)  |
|                                                    |
|  GitHub review: REQUEST CHANGES                    |
+----------------------------------------------------+
| PR #430  HEAD 987abcd                              |
|                                                    |
|  [1] Automated review     Not generated            |
|  [2] Manual code review   Not started              |
|  [3] Functional testing   Not started              |
|                                                    |
|  GitHub review: Not published                      |
+----------------------------------------------------+
| [Enter] Open track       [G] Generate reviews      |
+----------------------------------------------------+
| Ticket disposition                                 |
|                                                    |
| [       APPROVE       ] [       REJECT       ]     |
+----------------------------------------------------+
```

The example contains a blocking issue, so ticket approval would be disabled.

The hub should show actionable and unambiguous state.

## 7.1 Required per-PR information

For every PR display:

- PR number and descriptive title.
- Repository and current HEAD SHA.
- Automated review generation and triage status.
- Manual code review status.
- Functional testing status.
- Published GitHub review outcome, if any.
- Whether the decisions apply to the current SHA.
- Next available action.

The user can select any PR and enter any eligible review track.

## 7.2 Track completion versus GitHub publication

Do not treat a completed track as a published GitHub review.

For example:

```text
Automated review:   Complete
Manual code review: Complete
Functional testing: Pending
GitHub publication: Not published
```

This is a valid intermediate state.

Track results and publication receipts are distinct.

## 7.3 Ticket-level disposition

The bottom Approve / Reject panel applies to the **entire Jira ticket**, not an individual PR.

Approving the ticket requires that every included PR has completed the required gates for its current SHA, has no outstanding blocking disposition, and has the necessary GitHub review publication recorded.

A Request Changes result on any included PR blocks ticket approval.

If the reviewer rejects the overall ticket, reuse the Jira feedback editor and authorization sequence.

Do not require all PRs to fail before the ticket can be returned.

---

# 8. Screen 4 — Automated code review preparation

## Purpose

Allow the reviewer to explicitly generate automated reviews for PRs that lack a current review, or open existing reviews.

**Do not automatically generate reviews simply because the readiness gate was approved.**

Generation may consume time, model usage, and external resources.

## Layout

```text
+----------------------------------------------------+
| DOTNETIOT-2550          AUTOMATED CODE REVIEWS      |
+----------------------------------------------------+
| PR       HEAD       REVIEW STATUS        ACTION    |
|----------------------------------------------------|
| #428     abc1234    Current              [View]    |
| #429     def5678    Missing              [Generate]|
| #430     987abcd    Stale                [Generate]|
+----------------------------------------------------+
| Selected: PR #429                                  |
| No automated review found for HEAD def5678.        |
|                                                    |
| [Generate Selected]    [Generate All Missing]      |
+----------------------------------------------------+
| Esc: Return to PR hub                              |
+----------------------------------------------------+
```

## 8.1 Generation rules

For each PR:

- Look for an existing automated review associated with its HEAD SHA.
- If present and valid, show View.
- If absent, show Generate.
- If there is only an old review for another SHA, show Stale and offer regeneration.
- If generation failed, show a retryable failure with available error details.

Allow generating one selected PR or all missing/outdated reviews.

Reuse the existing `run-review` functionality.

Generation should occur only through explicit user action.

Display execution status while a review runs. Keep the interface responsive where feasible.

If no reviewer command is configured, expose the existing context-bundle/import workflow rather than pretending generation succeeded.

## 8.2 Navigation

Selecting View opens the automated finding triage for that specific PR and SHA.

After saving the finding selections, return to this preparation screen or the central hub with updated status.

The parent screen must visibly distinguish generated, triaged, and published reviews.

---

# 9. Screen 5 — Automated review findings

## Purpose

Allow the human reviewer to examine each finding generated by the coding agent and decide what feedback should be included in a future GitHub review.

This is **finding curation**, not a binary ticket approval.

## Layout

```text
+----------------------------------------------------+
| PR #429    SHA def5678     AUTOMATED CODE REVIEW    |
+----------------------------------------------------+
| FINDINGS                                           |
|----------------------------------------------------|
| [x] 1. Potential null reference                    |
| [x] 2. Incorrect timezone conversion               |
| [ ] 3. Suggested naming improvement                |
+----------------------------------------------------+
| SELECTED FINDING #1                       [scroll]  |
|----------------------------------------------------|
| File: src/Foo.cs                                   |
| Line: 134                                          |
|                                                    |
| 132  var item = lookup(id);                        |
| 133                                               |
| 134  return item.Value;                            |
|                                                    |
| Potential null reference if lookup returns null.   |
|                                                    |
| Proposed GitHub inline comment:                    |
| "This path may throw when lookup fails. Please     |
|  handle the missing result."                       |
+----------------------------------------------------+
| [Space] Include/Exclude   [E] Edit   [S] Save      |
| [Enter] Inspect context   [Esc] Back               |
+----------------------------------------------------+
```

For wider terminals, an index/detail split may be useful, as in the existing PR review screen.

For narrow terminals, prioritize legible code and comments rather than forcing two narrow columns.

## 9.1 Finding-level decisions

Support:

- Include finding.
- Exclude finding.
- Inspect code context.
- Inspect original agent explanation.
- Edit proposed inline comment.
- Mark finding as blocking/must-fix.
- Add or modify explanatory notes.
- Save local finding selections.

The default may include agent findings initially, but they remain human-editable.

Excluded findings are not published.

Preserve excluded findings in local history.

## 9.2 Automated review results

Saving the selections produces a local reviewed artifact for the current SHA.

This completes or advances the automated-review curation track.

It does **not** automatically post a GitHub review.

The reviewer may also record a provisional automated-track disposition:

- Approve / no blocking findings.
- Comment / non-blocking feedback.
- Request Changes / blocking findings.

These are local decisions until explicitly published.

## 9.3 Early blocking path

If the reviewer confirms a serious issue while examining automated findings:

1. Permit an early Request Changes action.
2. Show the selected comments and general feedback in a GitHub publication preview.
3. Require explicit human confirmation of the blocking issue.
4. Authorize publishing Request Changes to GitHub.
5. Return to the PR hub.
6. Enable overall ticket rejection and the Jira feedback workflow.

Do not require a complete manual code review or functional test after a human-confirmed blocker, just to return obviously defective work.

However, an agent flag alone is not sufficient to automatically request changes.

---

# 10. Screen 6 — Reviewer-administered code review

## Purpose

Provide a separate, explicit human review of the PR's code.

The automated review supports this process but cannot substitute for it.

The reviewer examines the code and can record observations that the agent missed.

## Suggested layout

```text
+----------------------------------------------------+
| PR #428   SHA abc1234       HUMAN CODE REVIEW      |
+----------------------------------------------------+
| Files changed / selected file                      |
|----------------------------------------------------|
| src/DeviceHistoryService.cs                        |
| src/HistoryMapper.cs                               |
+----------------------------------------------------+
| DIFF / CODE CONTEXT                       [scroll] |
|----------------------------------------------------|
|                                                    |
| Code under examination                             |
|                                                    |
|                                                    |
+----------------------------------------------------+
| REVIEWER NOTES                                     |
|----------------------------------------------------|
| Editable notes and manually discovered findings.   |
|                                                    |
+----------------------------------------------------+
| [Save]  [Complete Review]  [Request Changes]       |
+----------------------------------------------------+
```

## 10.1 Human review record

Capture:

- PR identity and SHA.
- Whether the reviewer completed manual code inspection.
- General reviewer notes.
- Manually identified findings.
- File and line location when applicable.
- Whether each finding is blocking.
- A human disposition: Approve, Comment, or Request Changes.
- Timestamp of the completed review.

Allow manual findings to be incorporated into the GitHub publication payload, alongside selected automated findings.

Do not publish duplicate inline comments when automated and manual findings describe the same issue.

## 10.2 Approval constraint

The automated review cannot satisfy the human review requirement.

**A GitHub Approve submission is not permitted merely because the agent found no problems.**

A GitHub Comment submission also requires the reviewer to complete manual code review, unless it is a separate explicitly authorized informational comment that does not claim review completion.

A confirmed blocker may be published early as Request Changes.

## 10.3 Relation to functional testing

Completing manual code review does not mean the entire PR has been validated.

It means the code inspection stage is finished.

If the human finds no blockers, proceed to functional testing.

If the human finds a blocker, the reviewer can request changes and return the ticket before testing.

---

# 11. Screen 7 — Test environment / virtualization readiness

## Purpose

Bridge from code review into actually running the application or services.

The user's virtualization setup is managed through an external project and YAML configuration.

**The TUI should not become a complete virtualization configuration editor.**

The TUI needs only to communicate environment readiness and launch-related status.

## Suggested layout

```text
+----------------------------------------------------+
| PR #428   SHA abc1234        TEST ENVIRONMENT      |
+----------------------------------------------------+
| Code review: Complete                              |
|                                                    |
| Test profile:        Available                     |
| Docker image:        SHA-matched                   |
| Image digest:        sha256:...                    |
| Environment:         Not launched                 |
|                                                    |
| Config: testing/profile/docker-compose.yml         |
+----------------------------------------------------+
| Next action:                                       |
|                                                    |
| [Prepare]   [Fetch Image]   [Launch]               |
|                                                    |
| Or run the displayed CLI command externally.       |
+----------------------------------------------------+
```

## 11.1 Responsibilities

The system should track:

- Test profile existence.
- Docker image identity.
- Relationship between image and PR SHA.
- Actual image digest.
- Environment readiness.
- Whether launch has occurred.
- Errors that prevent testing.

Reuse the existing `test prepare`, `test fetch`, and `test launch` operations.

Do not assume an image corresponds to a SHA merely because it has a similar label.

Where the workflow cannot establish provenance, explicitly display the uncertainty.

The operator can continue to edit the virtualization YAML outside the TUI.

## 11.2 Environment failure

A tooling, Docker, image, or environment failure is not automatically a code defect.

Represent it as `BLOCKED` or an equivalent environment state, not automatically Request Changes.

The reviewer can record the blocker and decide whether it warrants a Jira return.

---

# 12. Screen 8 — Reviewer-administered functional testing

## Purpose

Capture the human reviewer's actual experience running and exercising the product.

This is a separate review track for the PR and tested SHA.

Functional testing is where issues that are not apparent from code inspection may be discovered.

Examples:

- Incorrect CSS or layout.
- Broken user interactions.
- Unexpected application behavior.
- Incorrect service responses.
- Reproduction failures.
- Acceptance criteria not satisfied.

## Layout

```text
+----------------------------------------------------+
| PR #428   SHA abc1234       FUNCTIONAL TESTING     |
+----------------------------------------------------+
| ENVIRONMENT                                        |
|----------------------------------------------------|
| Image: sha256:...                                  |
| State: Running                                     |
|                                                    |
| Test plan: Available                               |
+----------------------------------------------------+
| TEST NOTES                               [scroll]  |
|----------------------------------------------------|
|                                                    |
| What was tested                                    |
| Steps taken                                        |
| Actual observations                                |
| Expected behavior                                  |
| Evidence references                                |
|                                                    |
+----------------------------------------------------+
| TEST RESULT                                        |
|----------------------------------------------------|
| [Pass]        [Fail]        [Blocked]              |
|                                                    |
| Reviewer disposition:                              |
| [Approve]     [Comment]     [Request Changes]      |
|                                                    |
| [Save Testing Review]                              |
+----------------------------------------------------+
```

## 12.1 Capture data

Record:

- PR number and SHA.
- Docker image digest / environment used.
- Test plan or acceptance criteria tested.
- Test steps.
- Observed results.
- Expected results.
- Freeform notes.
- Supporting evidence references.
- Operational test result: Pass, Fail, or Blocked.
- Reviewer disposition: Approve, Comment, or Request Changes.
- Time of testing.

The operational test result and review disposition are different data.

For example:

- Tests passed, with minor usability comments.
- Tests failed due to a reproducible defect.
- Tests blocked because virtualization could not launch.

Do not automatically map an environment failure to a code rejection.

## 12.2 Functional testing dispositions

**Approve:** Testing completed successfully, with no blocking findings.

**Comment:** Testing completed and produced non-blocking feedback.

**Request Changes:** Testing revealed a defect requiring developer action.

The reviewer controls the disposition.

Testing comments may eventually be included in the general GitHub review comment or submitted as separately authorized feedback, with evidence attachments where the existing tooling supports them.

## 12.3 Early return

If functional testing reveals a blocker:

1. Record the test failure and evidence.
2. Save the local testing review.
3. Offer Request Changes on the PR.
4. Preview and authorize GitHub publication.
5. Return to the parent PR hub.
6. Enable the ticket-level Jira rejection sequence.

Other PRs do not need to be rejected individually unless they contain their own problems.

The ticket as a whole can still be returned because one required PR failed.

---

# 13. GitHub review composition and publication

This is an important exception to the reusable binary Approve / Reject panel.

**GitHub reviews have three publication outcomes:**

1. Approve.
2. Comment.
3. Request Changes.

These are GitHub review submission outcomes, not Jira ticket decisions.

## 13.1 Review composition

A GitHub review may contain:

- Selected automated inline findings.
- Selected manual code review findings.
- Relevant functional testing feedback.
- An optional general comment.
- One GitHub review outcome.

The default should be to prepare a consolidated PR review rather than posting one review automatically for each internal review track.

**Three review tracks do not imply three GitHub submissions.**

## 13.2 Composition screen

```text
+----------------------------------------------------+
| PR #428  SHA abc1234      GITHUB REVIEW SUBMISSION |
+----------------------------------------------------+
| INLINE COMMENTS                                    |
|----------------------------------------------------|
| [x] Automated: null handling                       |
| [x] Manual: incorrect fallback                     |
| [ ] Automated: naming suggestion                   |
|                                                    |
| Selected for publication: 2                       |
+----------------------------------------------------+
| GENERAL REVIEW COMMENT                            |
|----------------------------------------------------|
|                                                    |
| Editable summary of reviewer feedback              |
|                                                    |
+----------------------------------------------------+
| REVIEW OUTCOME                                     |
|----------------------------------------------------|
| [ APPROVE ] [ COMMENT ] [ REQUEST CHANGES ]        |
|                                                    |
| [Preview GitHub Review]                            |
+----------------------------------------------------+
```

The three outcomes should occupy equal-width, stable positions.

Only one publication outcome can be selected.

The general comment remains editable.

## 13.3 Publication preview

Before submission show:

- Repository and PR.
- HEAD SHA being reviewed.
- Selected review outcome.
- Full general comment.
- Number of selected inline comments.
- Inline comment bodies and code locations.
- Any omitted findings, clearly distinguished from selected findings.

The reviewer must explicitly authorize publishing.

Nothing posts merely because a local draft was saved.

## 13.4 Publication eligibility

**Approve**

Requires completed manual code review and completed successful functional testing for the current SHA.

Do not publish an early GitHub approval based only on automated analysis or code inspection.

**Comment**

May be published after manual code review is complete, even if functional testing has not yet happened, provided it does not imply final approval.

If published early, clearly treat it as interim feedback and keep functional testing pending.

The default workflow should favor consolidating comments until the reviewer is ready, unless timely feedback is useful.

**Request Changes**

Can be published as soon as the reviewer has personally confirmed a blocking problem.

This does not require completing later stages.

The human confirmation must be explicit.

## 13.5 Multiple publication events

Prefer a single composed review per PR/SHA when practical.

However, an early Comment followed by a later final decision may require additional GitHub events.

Store each authorized publication and its receipt separately.

Never silently replace, duplicate, or reinterpret an earlier submission.

Show the latest published outcome and publication history.

## 13.6 Freshness validation

Immediately before publication:

- Recheck the PR's current HEAD.
- Compare it with the reviewed SHA.
- Validate inline comment locations.
- Block publishing if the relevant review snapshot is stale or comment locations are invalid.
- Require the reviewer to reassess or regenerate where needed.

Store successful publication receipts with the PR and SHA.

Do not submit an old draft against a different revision without revalidation.

---

# 14. Return to the PR hub after review publication

After a GitHub review is published, return to the parent screen.

Update the individual PR's status.

Example:

```text
PR #428     SHA abc1234
  Automated code review   Complete
  Human code review       Complete
  Functional testing      Complete
  GitHub review           APPROVED / Published

PR #429     SHA def5678
  Automated code review   Complete
  Human code review       Blocking issue
  Functional testing      Not performed
  GitHub review           CHANGES REQUESTED / Published

PR #430     SHA 987abcd
  Automated code review   Complete
  Human code review       Complete
  Functional testing      Complete
  GitHub review           COMMENTED / Published
```

A published Comment must not be mistaken for an approval.

A locally selected outcome must not be displayed as published until a successful GitHub receipt exists.

The hub should distinguish:

- Not reviewed.
- In progress.
- Completed locally.
- Publication pending.
- Published.
- Stale.
- Blocked.
- Returned.

---

# 15. Overall ticket disposition

At the bottom of the PR hub, reuse the established binary decision panel.

```text
+----------------------------------------------------+
| OVERALL TICKET DECISION                            |
|----------------------------------------------------|
|                                                    |
| [       APPROVE       ] [       REJECT       ]     |
|                                                    |
+----------------------------------------------------+
```

This decision applies to the Jira ticket and all associated PRs.

## 15.1 Approve ticket

Permit approval only if:

- Testing notes were accepted.
- Required PRs are known.
- GitHub readiness and analyzer gates passed or were explicitly dispositioned.
- Required automated and human reviews are complete.
- Required functional testing is complete.
- Each PR's relevant results apply to the current SHA.
- No PR has outstanding blocking findings.
- Required GitHub review publication has occurred.
- Any organization-specific final approval policy is satisfied.

A published GitHub Comment is not itself an approval. If the project's policy requires an actual GitHub Approve review, the TUI must enforce that separately rather than interpreting Comment as equivalent.

When approved, proceed to the normal final disposition and authorized Jira transition to the configured approved state.

Approval must not silently mutate Jira.

## 15.2 Reject ticket

Rejecting the ticket reuses the expandable editor.

Generate a default Jira return comment from:

- PRs with confirmed blocking findings.
- Published Request Changes outcomes.
- Outstanding problems that the reviewer explicitly marked blocking.
- Relevant functional testing failures.

Include PR numbers and SHAs.

Avoid repeating successful findings or clean PRs.

Example:

```text
Returning this ticket to In Progress.

PR #429 — SHA def5678
Code review:
- src/Foo.cs:134 may dereference a null value.
- Changes requested on GitHub.

PR #430 — SHA 987abcd
Functional testing:
- The settings panel overlaps the Save button.
- Reproduced in the tested Docker image.

Please address the blocking issues before returning
the ticket to Peer Review.
```

This is an editable draft, not a mandatory message.

After editing:

1. Save local Jira comment.
2. Preview and authorize posting.
3. Preview and authorize transition to In Progress.
4. Show receipt.
5. Return to ticket status.

The decision and its external effects must remain distinguishable.

---

# 16. SHA validity and revision rules

The SHA is critical to correctness.

Every PR's three review tracks are scoped to the exact code revision being evaluated.

## 16.1 When a new HEAD SHA appears

For the affected PR:

- Retain old automated findings.
- Retain old human code review notes.
- Retain old functional test results.
- Retain GitHub publication receipts.
- Mark prior SHA-scoped decisions as historical or stale for the new HEAD.
- Reevaluate readiness and analyzers.
- Regenerate or reassess automated findings as necessary.
- Require renewed human review of the changed revision.
- Revalidate or repeat functional testing as appropriate.
- Reestablish the current GitHub review/publication state.

Do not silently copy an old approval onto a new SHA.

Other PRs that did not change should retain their valid review states, unless cross-PR dependencies invalidate their evidence.

Ticket-scoped testing notes acceptance does not automatically become stale merely because a PR SHA changes.

## 16.2 Image and environment validity

Functional testing must record the image actually tested.

The test environment must not report a successful current-SHA test when it used an image from an earlier code revision.

Store and validate image digest and available provenance.

## 16.3 Snapshot history

Preserve previous commit snapshots so the reviewer can inspect earlier findings and decisions.

Historical data should be read-only by default and visually marked as historical.

---

# 17. Workflow state and outcome rules

The existing session model remains authoritative.

Important outcomes:

| Outcome | UI meaning |
|---|---|
| `WAITING` | External process incomplete; provide refresh or retry |
| `ACTION_REQUIRED` | Some action is necessary before progression |
| `REVIEW_DECISION` | Human judgment or authorization required |
| `READY` | The next operation can be invoked |
| `BLOCKED` | Tooling, environment, or execution failure |
| `COMPLETE` | Current required work completed and recorded |

These are not interchangeable with review dispositions.

For example:

- `WAITING` is not rejection.
- `BLOCKED` is not automatically a code defect.
- `READY` does not mean approved.
- `COMPLETE` does not mean a new SHA inherits the old result.

## 17.1 Data precedence

Read `session.json` for workflow state and current instructions.

Use PR/SHA artifacts for detailed review status.

Use action receipts to establish whether external operations succeeded.

Do not infer publication merely from the existence of a draft or local decision.

## 17.2 Refresh model

The existing Status screen should continue to show locally persisted data without unexpected external calls.

Explicit refresh or workflow execution actions may invoke the existing CLI/service layer.

The reviewer must be able to tell when displayed data was last collected and whether it is current enough for an external mutation.

---

# 18. Local artifacts and persistence

Use existing artifact structures wherever possible.

Canonical session layout:

```text
reviews/<ISSUE>/
  session.json
  issue.json
  issue-report.md
  return-comment.md
  actions.jsonl

  readiness.md
  analyzers.md

  prs/<slug>/
    pr.json

    commits/<sha>/
      github-checks.json
      readiness.md
      analyzers.md

      bugbot-findings.json
      codeql-findings.json

      review/
        findings.json
        human-review.json
        proposed-review.json
        publication.json

      review-preview.md
      reviewer-report.md

      testing/
        profile/
        environment.json
        test-plan.md
        test-results.json
        test-results.md
        evidence/

      disposition.md
```

Adapt this to the actual current repository layout; do not migrate files merely to conform to this illustrative tree.

Additional state may be required for manual code review, functional test notes, per-track dispositions, and multiple GitHub publication events.

Prefer explicit artifacts and schema extensions over overloaded or ambiguous fields.

All persisted per-PR review records should include their SHA.

## 18.1 Persistence guarantees

- Saving a draft is idempotent.
- Saving a local decision does not cause publication.
- Publishing and Jira mutation require explicit authorization.
- Successful external actions produce receipts.
- Reopening the TUI restores completed local work.
- Partially completed authorization sequences can resume safely.
- SHA changes do not destroy historical data.
- A reviewer may revise saved decisions through an explicit revision path.
- Retrying after a failed mutation must not duplicate a previously successful operation.

---

# 19. Screen transition summary

```text
SESSION STATUS
    |
    v
JIRA TESTING NOTES
    |
    +-- Reject -> Edit -> Save -> Jira comment?
    |                              |
    |                           Jira move?
    |                              |
    |                           Receipt
    |
    +-- Approve
           |
           v
PR READINESS + ANALYZERS
    |
    +-- Waiting -> Refresh
    |
    +-- Reject -> Edit -> Save -> Jira comment?
    |                              |
    |                           Jira move?
    |                              |
    |                           Receipt
    |
    +-- Approve
           |
           v
PULL REQUEST REVIEW HUB
    |
    +-- PR #1
    |     |
    |     +-- Generate automated review if missing
    |     +-- Triage automated findings
    |     +-- Perform human code review
    |     +-- Prepare and launch test environment
    |     +-- Record functional testing
    |     +-- Compose / authorize GitHub review
    |     +-- Return to hub
    |
    +-- PR #2 ... PR #N
    |     |
    |     +-- Same three review tracks per SHA
    |
    +-- Early Request Changes
    |     |
    |     +-- Publish confirmed blocking feedback
    |     +-- Return to hub
    |     +-- Reject overall ticket
    |
    +-- All required reviews complete
           |
           v
OVERALL TICKET DISPOSITION
    |
    +-- Approve -> Authorized approved transition
    |
    +-- Reject -> Edit -> Save -> Jira comment?
                                   |
                                Jira move?
                                   |
                                Receipt
```

The operator may navigate among PRs and review tracks without invalidating work simply by changing screens.

Changing the code revision, revising a decision, or altering relevant evidence may invalidate an affected gate.

---

# 20. Screen and component inventory

## Existing screens to retain and improve

| Screen | Work |
|---|---|
| Status | Add clear multi-PR progress, current actions, and review state |
| Testing Notes | Stack evidence panes and refactor bottom decision workflow |
| PR Review | Preserve existing finding triage; extend for coordinated review tracks |

## Screens or views to add

| Screen or view | Purpose |
|---|---|
| PR readiness | Aggregated checks, analyzers, and ticket decision |
| PR review hub | Three review tracks per PR/SHA and overall ticket disposition |
| Automated review preparation | Generate/view automated review for each PR |
| Automated finding triage | Include/exclude/edit inline findings |
| Human code review | Record independent reviewer inspection and findings |
| Test environment | Display profile, image, digest, and launch readiness |
| Functional testing | Record actual testing and reviewer disposition |
| GitHub review composition | Combine selected feedback and select publication outcome |
| Publication preview | Authorize the exact GitHub payload |
| Shared authorization/receipt | Reusable Jira and GitHub mutation confirmation |

Where practical, these should be views or substates rather than entirely separate Textual screens.

The user should experience a coherent review workspace rather than a sequence of unrelated dialog boxes.

---

# 21. Non-negotiable interaction rules

1. **Never auto-publish** a GitHub review or Jira comment as a side effect of saving a local decision.
2. **Never auto-approve** code based solely on an agent recommendation.
3. **Never publish GitHub Approve before manual code review and functional testing are completed.**
4. **Allow early Request Changes** when a human confirms a blocking issue.
5. **Allow early GitHub Comment only after the required human code inspection**, without treating that comment as final approval.
6. **Keep all three review tracks separate**, even when their feedback will be combined into one GitHub submission.
7. **Keep the three review tracks SHA-scoped.**
8. **Keep testing notes ticket-scoped.**
9. **Never approve the ticket while an included PR has an outstanding blocking result.**
10. **Do not conflate analyzer completion with disposition of analyzer findings.**
11. **Do not conflate a saved draft with an external publication.**
12. **Do not silently mutate Jira on GitHub Request Changes.** The ticket transition remains explicitly authorized.
13. **Do not automatically classify virtualization failures as source-code defects.**
14. **Do not force functional testing after an already-confirmed blocker solely to complete the workflow.**
15. **Do not discard previous decisions when a SHA changes.** Preserve them and mark them historical.
16. **Do not create separate GitHub submissions for each internal review track by default.**
17. **Never allow an old inline finding to publish against an incompatible new HEAD.**
18. **Keep the reviewer in control of what evidence, comments, and conclusions are published.**

---

# 22. Acceptance scenarios

Implementation should be verified against at least the following scenarios.

## Scenario A — Testing notes accepted

- Jira ticket contains adequate testing notes.
- Pre-check emphasizes Approve.
- Reviewer selects Approve.
- Decision saves locally.
- Application advances to PR readiness.
- No Jira comment or transition occurs.

## Scenario B — Testing notes rejected

- Pre-check emphasizes Reject.
- Reviewer selects Reject.
- Issue description collapses.
- Testing notes stay visible.
- Compact editor opens with default feedback.
- Reviewer edits and saves.
- Reviewer explicitly authorizes Jira comment.
- Reviewer explicitly authorizes Jira transition.
- Receipt accurately reports results.

## Scenario C — Three PRs, one analyzer blocker

- Two PRs have clean results.
- One PR has an unresolved Bugbot finding.
- Overall readiness does not pass automatically.
- Reviewer inspects evidence and rejects.
- Default Jira feedback cites only the affected PR and SHA.
- No unnecessary successful-check summary appears in the return comment.

## Scenario D — Automated review missing

- One PR already has current review findings.
- Another PR has none.
- A third has only findings from an old SHA.
- Preparation screen shows View / Generate / Stale correctly.
- Reviewer can explicitly generate only missing/outdated reviews.
- Nothing is generated merely by entering the screen.

## Scenario E — Automated findings curated

- Agent produces multiple findings.
- Reviewer excludes one, edits another, and keeps a third.
- Local selections persist.
- No GitHub submission occurs on Save.
- Published review eventually contains only explicitly selected findings.

## Scenario F — Early blocking code defect

- Human confirms a blocking automated or manually discovered code defect.
- Reviewer can submit Request Changes before functional testing.
- GitHub publication is explicitly authorized.
- Parent screen shows the published outcome.
- Overall ticket rejection produces an editable Jira feedback draft.
- Jira comment and transition require separate authorizations.

## Scenario G — Code clean, functional test fails

- Automated findings are dispositioned.
- Human code review completes without blockers.
- Reviewer launches/test-drives the product.
- Functional testing finds a serious UI issue.
- Reviewer records steps and evidence.
- Request Changes is available.
- Jira rejection draft includes the specific functional problem.

## Scenario H — All required reviews pass

- Every PR has completed automated, human code, and functional review.
- Every current SHA is valid.
- No blocking findings remain.
- Required GitHub reviews are published.
- Overall ticket approval becomes available.
- Approved Jira transition requires explicit authorization.

## Scenario I — SHA changes during review

- PR HEAD changes after automated review or functional testing.
- Previous findings and test results remain available.
- Current review is visibly stale.
- Old approval is not reused.
- Publication is blocked if its payload is incompatible with HEAD.
- Reviewer can repeat the affected operations on the new SHA.

## Scenario J — Publication or Jira operation fails

- Local review remains saved.
- Partial external success is recorded.
- TUI shows which action failed.
- Retry does not duplicate successful comments or reviews.
- Session can resume without rebuilding the draft.

---

# 23. Implementation guidance

Before modifying code:

1. Inspect the existing Textual screens and CSS.
2. Inspect the CLI workflow and persisted session schema.
3. Identify existing reusable components and underlying workflow operations.
4. Identify which described screens already have partial implementations.
5. Map new states onto existing artifacts.
6. Propose the smallest coherent changes needed to implement this design.

Favor shared components and explicit state transitions.

The principal reusable components should include:

- Persistent context header.
- Scrollable evidence pane.
- Collapsible context summary.
- Dynamic decision panel.
- Editable feedback draft.
- Saved draft preview.
- External authorization panel.
- Operation receipt.
- Per-PR/SHA review-status row.
- Finding selection/detail editor.
- GitHub review composition panel.

Follow existing Textual layout/CSS conventions where useful, but replace accidental or inconsistent layouts with the agreed design.

Avoid introducing a large generic workflow framework merely to support these screens.

Reuse CLI operations and tests instead of creating parallel TUI-only implementations.

Add unit and integration tests for:

- State transitions.
- Panel sizing/state changes.
- Persistence.
- Multi-PR aggregation.
- SHA invalidation.
- Review publication eligibility.
- External authorization.
- Idempotent external actions.
- Early blocking returns.
- Successful final disposition.

---

# 24. Core design summary

The reviewer system operates at three levels.

**Level 1 — Jira ticket**

Testing notes, overall readiness, and final ticket disposition. The ticket has a shared Approve / Reject interaction with editable Jira return feedback.

**Level 2 — Pull request / SHA**

Each PR has three distinct, independently recorded review tracks:

- Automated code review.
- Reviewer-administered code review.
- Reviewer-administered functional testing.

Each track captures evidence, reviewer disposition, and completion state for the specific revision.

**Level 3 — External publication**

The reviewer composes selected findings and notes into authorized GitHub review submissions, using Approve, Comment, or Request Changes.

A confirmed blocker permits early Request Changes and Jira return.

Without a blocker, final GitHub approval waits until manual code review and functional testing are complete.

**The governing principle is simple:**

The system gathers and organizes evidence, makes recommendations, and prepares actions. The reviewer decides what to accept, what to reject, what to publish, and when the ticket is ready to advance.

The TUI should make those decisions easy without taking control away from the reviewer.
