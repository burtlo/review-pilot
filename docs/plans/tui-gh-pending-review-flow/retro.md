# Retro — GitHub pending review as the peer-review editing surface

## Purpose and setting

The operator is peer-reviewing **DOTNETIOT-2550** (three PRs: KT.IoT.Zuul#156, KT.IoT#144, KT.IoT.UI.Admin#354) using review-ticket attach, the review hub, and per-PR triage. They want to **revise the automated code review flow** so that staging comments on the **GitHub pull request** (pending review, edit on github.com, then submit) feels more natural than reviewing findings primarily in the Textual UI.

To validate the GitHub path, an assistant (outside review-ticket) manually posted **pending** reviews via `gh api` for all three PRs at stored SHAs, using artifacts under `reviews/DOTNETIOT-2550/`. That experiment exposed gaps in the product and clarified desired comment layout (markdown, suggestion semantics, separation of summary vs findings).

No Foundry run directory was supplied.

**evaluate-run not run—engine verdict omitted.**

## Experience in the operator's terms

The operator triages in the hub (Include/Exclude, Save) and expects those choices to drive what appears on GitHub. They discovered that **pending** reviews on GitHub—one summary-level pending review with inline line comments and room to edit before Submit—match how they want to work better than scrolling findings in the TUI alone. The browser extension approach (automate Files changed) is struggling with DOM stability; the **REST pending-review API** path worked for DOTNETIOT-2550 once payloads were built correctly.

After staging UI.Admin#354 at `8120fbe`, they confirmed: a **non–line-anchored** block and an **inline** comment on `file#line` both appeared. They also saw that **suggestion fences** and **comment bundling** do not match GitHub’s UX or author needs, and that the **review summary** reads like internal reviewer notes rather than a succinct message to the PR author.

## Feedback investigations

### Primary workflow: edit on GitHub pending review, not only in TUI

*Operator signal (paraphrased): Local TUI review of comments feels less intuitive than generating proposed review content, posting to the PR, and letting the human revise or remove comments there.*

- **Expected:** After automated review and light triage, the next step is **see comments on the real PR diff**, edit in GitHub’s pending review UI, then submit when ready.
- **Observed:** Product today centers **attach → hub → `PrReviewScreen` → Save** → `human-review.json` / `proposed-review.json`, then **`publish-review`** which **submits** immediately via [`create_review`](../../../review_ticket/adapters.py) with `event` set ([`build_review_payload`](../../../review_ticket/findings.py)). Pending staging was done manually: `gh api POST .../pulls/{n}/reviews` **without** `event`, plus `DELETE` of an existing pending review when GitHub returned 422. No `review-ticket` subcommand performed that sequence.
- **Friction cost:** High context switch (TUI ↔ mental model of PR layout); duplicate experimentation (extension vs CLI); risk that hub **Save** does not match disk (`session.json` lock caused `review apply --revise` to fail with WinError 5 while attach held the file).
- **Touchpoints:** [`PrReviewScreen`](../../../review_ticket/tui/pr_screen.py), [`save_snapshot_review`](../../../review_ticket/workflow.py) / [`_persist_human_review_files`](../../../review_ticket/workflow.py), [`publish_review`](../../../review_ticket/workflow.py), [inline-reviewer-browser spec](../inline-reviewer-browser/spec.md) (DOM staging, never submit).
- **Interpretation:** The operator wants **GitHub as the WYSIWYG editor** for review comments; TUI is better for **decisions and generation**, not for mimicking the PR comment thread. Fact: pending API staging worked in the experiment. Hypothesis: making pending staging a first-class command reduces pressure on the extension.
- **Options and tradeoffs:**
  - **`stage-github-review` (or `publish-review --pending`)** — Build from `proposed-review.json`, omit `event`, optional `--replace-pending`, write `staging.json` receipt. Small surface; still one pending review per user per PR (GitHub limit).
  - **Keep extension as primary** — Preserves SHA/range gate and marker preflight; high DOM maintenance (operator already hit selector pain).
  - **Workflow redesign** — Hub action “Stage on GitHub” after Save; TUI shows publish preview counts only. Downside: requires `gh` auth and network; offline triage still needs local preview.
- **Probe:** After Include + Save for UI.Admin#354, run one documented command. Does `proposed-review.json` match what appears on the PR without hand-editing JSON or calling private `_persist_human_review_files`?
- **Status:** open

### `suggestion` fences used for non-code prose

*Operator signal: “The inline comments should not use the suggestion code fence as the GitHub PR treats that as a proposed replacement for the commented line.”*

- **Expected:** ` ```suggestion ` appears only when the comment offers **applyable replacement source** for the anchored lines.
- **Observed:** F002 on UI.Admin#354 (`ThingComboBoxReadExecutor.cs:126`) was posted with a ` ```suggestion ` block containing **guidance text**, not C#. [`render_finding_body`](../../../review_ticket/findings.py) wraps any non-empty `suggested_change` that passes [`suggestion_ok`](../../../review_ticket/findings.py) (no nested fences) in ` ```suggestion ` when `_inline` is true. Prose passes `suggestion_ok` today.
- **Friction cost:** Author sees “Commit suggestion” for non-committable text; undermines trust in automated comments.
- **Touchpoints:** [`render_finding_body`](../../../review_ticket/findings.py), [`suggestion_ok`](../../../review_ticket/findings.py), reviewer JSON schema / agent prompts under `.cursor/`.
- **Interpretation:** The pipeline conflates “suggested_change field populated” with “GitHub suggestion block appropriate.”
- **Options and tradeoffs:**
  - **Stricter `suggestion_ok`** (heuristics, language tags, reviewer flag `suggestion_is_patch`) — Low scope; may drop valid patches if heuristic is wrong.
  - **Separate fields** — `explanation` vs `patch_suggestion` in findings schema — Clear contract; migration for existing `findings.json`.
  - **Render prose as bold/backtick markdown only** — Matches operator ask; no one-click apply for real fixes unless patch field set.
- **Probe:** For ten historical findings with `suggested_change`, classify manually: patch vs prose. What false positive/negative rate would a stricter rule have?
- **Status:** open

### Markdown formatting stripped or underused in published comments

*Operator signal (paraphrased): Markdown with bold and backticks would help legibility; formatting from the Cursor agent may be lost when translating to pending comments.*

- **Expected:** Published bodies resemble agent output: headings, **bold**, `identifiers`, lists.
- **Observed:** Default [`build_review_payload`](../../../review_ticket/findings.py) summary is a **long plain paragraph** from `findings.json` `summary` / `human-review.json`. One manual repost used a hand-authored markdown body; `proposed-review.json` output is mostly unstyled except `render_finding_body` title line. No dedicated “author markdown” vs “reviewer narrative” channel.
- **Friction cost:** Harder to scan on GitHub; operator re-formats by hand.
- **Touchpoints:** [`render_finding_body`](../../../review_ticket/findings.py), [`_general_section`](../../../review_ticket/findings.py), `reviewer-report.md` vs `proposed-review.json`.
- **Interpretation:** Translation layer optimizes for **publish payload parity**, not **GitHub rendering** or author readability.
- **Options and tradeoffs:**
  - **`render_finding_body` enrichment** — Always emit structured markdown (sections, backticks for paths). Cheap; may not fix summary bloat.
  - **`author_summary` vs `reviewer_notes`** in artifacts — Summary field for PR body; long narrative stays in `reviewer-report.md` only. Requires triage UI copy changes.
  - **Post-process markdown linter** before stage — Ensures consistent headers; does not fix content choice.
- **Probe:** Show operators side-by-side: current `proposed-review.json` body vs a 5-sentence author summary template. Which do they ship without edits?
- **Status:** open

### Browser extension vs GitHub API pending review

*Operator signal (paraphrased): Pending comment UI on GitHub is what we want; the extension struggles to find elements to drive Prepare.*

- **Expected:** Same outcome as extension spec (stage all findings, SHA gate, no submit) with less fragility.
- **Observed:** Extension spec requires DOM automation ([inline-reviewer-browser](../inline-reviewer-browser/spec.md)); operator reports difficulty finding controls. Pending API path succeeded for DOTNETIOT-2550 without DOM (assistant used `gh api`). Extension lists **all** snapshot findings; publish path respects **triage reject**.
- **Friction cost:** Engineering time on selectors vs maintaining API payload rules (line anchors, `diff_index`).
- **Touchpoints:** `extensions/inline-reviewer/`, [`serve-inline-review`](../../../review_ticket/inline_review.py), [`build_snapshot`](../../../review_ticket/inline_review.py).
- **Interpretation:** Two staging strategies (DOM vs API) need a **product default**; API pending may be the pragmatic primary for peer review, extension for operators who refuse API or need marker preflight on page.
- **Options and tradeoffs:**
  - **API-first staging in review-ticket** — Aligns with this retro; loses live SHA UI gate unless verified via `gh`/`get_head_sha`.
  - **Extension as devtool for selectors only** — Keeps DOM investment narrow.
  - **Playwright CLI** reusing `prepare.js` — Middle ground; not in product today.
- **Probe:** For one PR, time-to-stage: extension dry-run vs `stage-github-review`. Count steps and failure modes.
- **Status:** open

### Off-diff findings bundled into review `body` instead of separate comments

*Operator signal (paraphrased): Findings without file#line appeared in the same comment box as the review description; each off-diff finding should be its own comment. The overall summary should be separate—ideally pre-populated in “Finish your review,” or else a standalone formatted comment.*

- **Expected:** One **author-facing summary**; each finding its own visible thread (inline on diff, or **issue-style** / review comment if no line); not one megabody with `## Findings outside the diff`.
- **Observed:** [`build_review_payload`](../../../review_ticket/findings.py) appends [`_general_section`](../../../review_ticket/findings.py) to the **single** review `body`. GitHub **Create review** API accepts one `body` plus many inline `comments[]`; off-diff accepted findings are **not** separate top-level PR comments in that model—they are concatenated into review summary. Zuul#156 pending review demonstrated F002/F003 in summary while F001 was inline. UI.Admin F001 (off-diff at line 141 per `diff_index`) landed in the same pending `body` as the ticket summary.
- **Friction cost:** Authors receive a wall of text; hard to reply per finding; “Finish your review” summary mixes roles.
- **Touchpoints:** [`build_review_payload`](../../../review_ticket/findings.py), GitHub REST review object (pending review has one summary field + inline comments only on diff lines).
- **Interpretation:** Payload shape is **publish-review-shaped**, not **conversation-thread-shaped**. GitHub may require **multiple API calls** for off-diff: e.g. pending review with short `body` + inline comments, then **separate** `POST .../issues/comments` or additional review comments for general findings—or accept summary-only section in Finish dialog only for true summary.
- **Options and tradeoffs:**
  - **Short `body` + N inline + M issue comments** for off-diff — Better threading; more API calls; idempotency harder.
  - **One pending review, body = summary only; off-diff as inline on file-level** — Often impossible without line anchor.
  - **Keep bundling but separate markdown file per finding in body** — Still one box; marginal improvement.
- **Probe:** On a PR with two off-diff findings, prototype three layouts (bundled body vs issue comments vs summary-only in Finish). Operator picks readability winner.
- **Status:** open

### Review summary is reviewer-facing, not author-facing

*Operator signal (paraphrased): UI.Admin `8120fbe` pending summary has too much about what was tested, what was included, recommendations for the reviewer—details for the reviewer, not the PR author. Want a succinct author summary with better formatting.*

- **Expected:** PR review summary reads like a peer message to the author: scope, outcome, ask—not internal QA checklist or automation caveats.
- **Observed:** `findings.json` / `human-review.json` `summary` for UI.Admin is a long paragraph (Telerik feed, Bugbot, `dotnet test` not run, QA recommendations). That text became the pending review `body` prefix before off-diff sections. [`reviewer-report.md`](../../../reviews/DOTNETIOT-2550/prs/kwik-trip-iot-KT.IoT.UI.Admin-pr-354/commits/8120fbe1c7e67f4b47d7827721e213986cad6b21/review/reviewer-report.md) duplicates narrative detail.
- **Friction cost:** Author noise; reviewer must rewrite on GitHub before submit.
- **Touchpoints:** `findings.json` `summary`, triage Save summary field, [`build_review_payload`](../../../review_ticket/findings.py) `full_body`, hub disposition copy.
- **Interpretation:** Single `summary` field serves **automation log**, **reviewer notes**, and **GitHub review body** without separation.
- **Options and tradeoffs:**
  - **`author_review_summary` generated at publish stage** — Template or LLM compress from findings; keeps long narrative in report only.
  - **Operator-edited summary in triage** — Already partially supported via `human-review.json` `summary`; UI does not steer toward brevity.
  - **Default templates per repo/ticket** — Predictable; may feel generic.
- **Probe:** Draft a 3–5 sentence author summary for UI.Admin#354 from the same findings. Compare to current `proposed-review.json` `body` length and operator edit time on GitHub.
- **Status:** open

### Work performed outside review-ticket (gap inventory)

*Operator signal: Prior turn documented manual steps; this retro captures them for product closure.*

- **Expected:** All staging steps run through documented `review-ticket` commands with receipts.
- **Observed (assistant session, 2026-10-19):**
  - `gh pr view` / `gh api` GET reviews / DELETE pending / POST pending with `--input` JSON.
  - Ad hoc files: `pending-review.json`, `pending-review-update.json` (failed PUT) under each PR’s `review/` directory—not produced by workflow.
  - Regenerated triage via direct `_persist_human_review_files(..., revise=True)` when CLI `review apply` failed on `session.json` lock.
  - Python one-liner to strip `event` from `proposed-review.json`.
  - IDE browser open to `/changes` (not review-ticket).
- **Friction cost:** Non-reproducible runbook; artifacts not in `publication.json` / staging receipt.
- **Touchpoints:** [`publish_review`](../../../review_ticket/workflow.py) vs missing stage command; [`cli.py`](../../../review_ticket/cli.py) `review apply` session coupling.
- **Interpretation:** Experiment proved value; product lacks **stage** verb between **Save** and **publish-review**.
- **Options and tradeoffs:** Implement stage command vs document `gh` recipe in operator guide — doc-only leaves receipts and triage sync gaps.
- **Probe:** Same three PRs staged only via new command; zero manual `gh` or private Python.
- **Status:** open

## Cross-cutting design opportunities

1. **Three-layer comment model** — (a) **Author summary** → pending review `body` / Finish your review; (b) **Inline findings** → `comments[]` with markdown bodies, `suggestion` only for patches; (c) **Off-diff findings** → separate issue or review comments, not appended to (a). Unifies operator feedback on bundling, summary voice, and suggestion semantics.

2. **Hub outcome: “Stage on GitHub”** — After Include/Save, primary action posts pending review from `proposed-review.json`, opens `files_changed_url` ([`inline_review.files_changed_url`](../../../review_ticket/inline_review.py)). TUI becomes **triage + trigger**, GitHub becomes **edit + submit**. Reduces investment in extension DOM as default path.

3. **Triage sync and revise** — Save must update `human-review.json` reliably; `attach --revise` and clear errors when `session.json` is locked. Staging should refuse or warn when on-disk triage ≠ last Save.

4. **Payload artifacts** — Canonical `pending-review.json` (no `event`) emitted beside `proposed-review.json`; optional `github-staging.json` with review id and SHA.

Prioritize **stage command + suggestion/markdown/summary rules** before further extension selector work, unless enterprise policy forbids API staging.

## Spec non-goals (operator)

These are **not** desired product behavior for the GitHub pending-review flow. Do not carry them forward from the DOTNETIOT-2550 experiment into `spec.md` without an explicit new decision.

- **`pr select` before stage or publish** — Not required to post a pending review via the API (repo/PR/sha come from the per-commit artifact path or an explicit stage target). An assistant ran `pr select` only while trying `review apply --revise`; that attempt failed on `session.json` lock, but **`select_pr` still sets `pr_scope: "single"` and `active_prs` to one PR**, which made re-attach show only KT.IoT.UI.Admin. The intended flow keeps **multi-PR scope** (`pr select-all` / `pr_scope: "all"`) while staging each PR from hub context (e.g. stage for the PR you are viewing, without narrowing the ticket).
- **Private `_persist_human_review_files` / manual `gh`** — Workaround only; replace with a supported stage command keyed by issue + PR ref + sha.
- **Narrowing `active_prs` as a side effect of tooling** — Any new stage action must not silently call [`select_pr`](../../../review_ticket/workflow.py) unless the operator explicitly chooses single-PR mode.

## Evidence index

| Kind | Reference |
|------|-----------|
| Issue / PRs | DOTNETIOT-2550; `kwik-trip-iot/KT.IoT.Zuul#156` @ `b0c7a267…`, `KT.IoT#144` @ `6bbbf121…`, `KT.IoT.UI.Admin#354` @ `8120fbe1…` |
| Artifacts | `reviews/DOTNETIOT-2550/prs/*/commits/<sha>/review/{findings,human-review,proposed-review,pending-review}.json` |
| GitHub pending reviews created (experiment) | KT.IoT#144 `5574705876`; Zuul#156 `5574730831`; UI.Admin#354 `5574919930` (earlier pending IDs deleted) |
| Failed CLI | `review-ticket DOTNETIOT-2550 pr select …` + `review apply --accept-all --revise` → WinError 5 on `session.json` |
| Code | [`review_ticket/findings.py`](../../../review_ticket/findings.py), [`review_ticket/workflow.py`](../../../review_ticket/workflow.py), [`review_ticket/adapters.py`](../../../review_ticket/adapters.py), [`review_ticket/tui/pr_screen.py`](../../../review_ticket/tui/pr_screen.py), [`review_ticket/inline_review.py`](../../../review_ticket/inline_review.py) |
| Plans | [inline-reviewer-browser](../inline-reviewer-browser/), [tui-review-flow](../tui-review-flow/retro.md) |
| evaluate-run | **Not run—engine verdict omitted.** |

Uncertainty: GitHub API capabilities for multiple non-inline comments per pending review may require supplemental endpoints; confirm against current REST docs when spec’ing off-diff threading.
