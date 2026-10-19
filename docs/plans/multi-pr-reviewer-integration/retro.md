# Multi-PR `run-review` and peer-review skill gap

## Purpose and setting

The operator is peer-reviewing **DOTNETIOT-2550**, which spans three GitHub pull requests under `kwik-trip-iot`: KT.IoT.Zuul#156, KT.IoT#144, and KT.IoT.UI.Admin#354. Readiness and analyzer gates completed (`outcome: READY`, `step: automated-review`). The CLI recommended `review-ticket DOTNETIOT-2550 run-review`.

Session snapshot: `active_pr` is **Zuul#156** (first tracked ref); all three SHAs are in `pr_shas`. Artifacts live under `reviews/DOTNETIOT-2550/`.

## Experience in the operator's terms

After gates passed, the next command was `run-review`, but the operator’s mental model was a **per-repo manual loop**: open `C:\repos\kwik-trip-iot`, `git fetch`, checkout the PR branch, merge, then run Cursor **peer-review** (or **peer-review-ui-admin** for UI.Admin) with the `reviewer` / `ui-admin-reviewer` agents. Those skills produce long-form markdown reports suited to human reading, not the structured JSON that `review-ticket` uses to build inline GitHub review comments via `review apply` and `publish-review`.

The operator is considering a **new skill or script** (possibly Cursor API–driven) to close that format gap and is unsure what `run-review` actually expects versus their existing workflow.

## Feedback investigations

### What `run-review` expects (vs. manual repo checkout)

*Operator signal (paraphrased): For each PR I go to my local clone, fetch, checkout, and merge—then run peer-review. What is `run-review` asking me to do instead?*

- **Expected:** Either the tool would mirror the familiar three-repo checkout loop, or clearly say it replaces that step.
- **Observed:** Terminal output after `review-ticket DOTNETIOT-2550`: `Ready for the automated reviewer.` / `next: review-ticket DOTNETIOT-2550 run-review` (operator terminal). README step 4 states the SHA is fetched into `commits/<sha>/checkout` with `git worktree add --detach` and does not switch the caller’s working tree ([README.md](../../../README.md)).
- **Friction cost:** Duplicate mental models—manual git ritual vs. built-in worktree—plus uncertainty about whether local clones are still required for Cursor skills.
- **Touchpoints:** [`run_review`](../../../review_ticket/workflow.py) → [`_execute_reviewer`](../../../review_ticket/workflow.py) → [`_ensure_diff`](../../../review_ticket/workflow.py) / [`ensure_checkout`](../../../review_ticket/checkout.py); reviewer contract in [README “Reviewer output”](../../../README.md) and [`reviewer_prompt`](../../../review_ticket/reports.py).
- **Interpretation:** `run-review` is the **automated findings capture** step: prepare context (`review/context/`), run `reviewer_command` (or stop for `import-review`), normalize to `findings.json`, then advance to human triage (`review apply`). It is **not** asking for merge-to-main locally; it needs the **PR head SHA** and a **base…head diff**. Peer-review in a separate repo checkout is an optional human path, not what the CLI implements internally.
- **Options and tradeoffs:**
  - **Document “replace fetch/checkout”** in README for multi-repo org setups — low cost, leaves skill gap open.
  - **`checkout_command` pointing at existing clones** — reuses operator disk layout; still must satisfy `{dest}` verification in `ensure_checkout`.
  - **First-class “open in Cursor” handoff** — exports `prompt.md` + paths; operator runs skill manually, then `import-review`.
- **Probe:** After a successful `run-review` (or import), does `reviews/.../review/context/prompt.md` contain enough for peer-review without opening `C:\repos\kwik-trip-iot`?
- **Status:** open

### Three PRs, one `active_pr` at a time

*Operator signal (paraphrased): I have three pull requests—do I run the whole loop three times?*

- **Expected:** Either one command reviews all three PRs, or explicit guidance per PR.
- **Observed:** README: readiness/analyzers run for **each** tracked PR; **code review and publication** use `active_pr` (first tracked ref) unless switched with `pr select` ([README.md](../../../README.md)). Session has `active_pr: kwik-trip-iot/KT.IoT.Zuul#156` and three entries in `active_prs`.
- **Friction cost:** Risk of publishing a review against the wrong repo if the operator assumes “issue done” after one PR.
- **Touchpoints:** [`session.json`](../../../reviews/DOTNETIOT-2550/session.json) (local); `pr select` / `pr select-all` in [`review_ticket/workflow.py`](../../../review_ticket/workflow.py).
- **Interpretation:** For DOTNETIOT-2550 the intended loop is **three times**: `run-review` → `review apply` → `publish-review` (and later test/disposition) for **Zuul**, then `review-ticket DOTNETIOT-2550 pr select kwik-trip-iot/KT.IoT#144`, repeat, then `pr select kwik-trip-iot/KT.IoT.UI.Admin#354` (UI.Admin may use ui-admin reviewer in the adapter layer).
- **Options and tradeoffs:**
  - **CLI “review all PRs” batch** — fewer commands; harder human gates per repo.
  - **Checklist in issue-report** listing pending `active_pr` — cheap UX nudge.
  - **Keep single-PR scope** — matches GitHub’s one-review-per-PR publication model.
- **Probe:** After Zuul publication, does `review-ticket DOTNETIOT-2550` surface the next untracked-for-review PR automatically?
- **Status:** open

### Peer-review markdown vs. `findings.json` for GitHub

*Operator signal (paraphrased): Peer-review skills aren’t geared toward annotated PRs—I need something that outputs PR-integration format, maybe API + script.*

- **Expected:** Running the same reviewer agent they trust should directly feed `publish-review` with inline comments on diff lines.
- **Observed:** `.review-ticket.yaml` sets `reviewer_command: "reviewer {context} {output}"` (placeholder). Peer-review skill returns verbatim markdown from `# Summary` through `# Merge Recommendation` ([peer-review SKILL](file:///C:/Users/lf10102100/.cursor/skills/peer-review/SKILL.md)), not JSON. Contract requires `summary`, `approval_recommendation`, and `findings[]` with `path`, `line`, `side`, etc. ([README](../../../README.md)); [`normalize_findings`](../../../review_ticket/findings.py) enforces shape.
- **Friction cost:** Building a one-off converter from markdown findings to JSON; risk of wrong line numbers → comments dropped at publish (inline only on diff lines).
- **Touchpoints:** [`_execute_reviewer`](../../../review_ticket/workflow.py), [`build_review_payload`](../../../review_ticket/reports.py) / publish path in [`publish_review`](../../../review_ticket/workflow.py); [`import-review`](../../../review_ticket/cli.py) as escape hatch.
- **Interpretation:** The product already defines the **integration boundary** (`findings.json`). Missing piece is a **reviewer adapter**: executable referenced by `reviewer_command` or a post-skill step that (1) loads `context/prompt.md` + diff, (2) invokes reviewer or ui-admin-reviewer with JSON-only output instructions, (3) writes `{output}`. Cursor SDK/API is one implementation; a Cursor skill that writes JSON to a path is another—no new GitHub concept required.
- **Options and tradeoffs:**
  - **`reviewer_command` wrapper script** — single `run-review` invocation; must be maintained and credentialed.
  - **`import-review --file`** after manual skill — no script in repo; operator copies JSON.
  - **Extend peer-review skill** with optional `--json-out` mode — couples IDE skill to review-ticket schema versioning.
- **Probe:** Can one agent pass produce valid line numbers for 90% of must-fix items when given `diff.patch` + `diff-lines.json` from context?
- **Status:** open

### Placeholder `reviewer_command` and `import-review` handoff

- **Expected:** `run-review` either runs a real reviewer or tells me exactly how to proceed without a failing shell command.
- **Observed:** Config includes a non-empty `reviewer_command` that likely does not exist on PATH; README says when the real command is unavailable, context is written and workflow waits for `import-review` ([README.md](../../../README.md))—but a **set placeholder** may attempt execution and block instead of handoff (code path when `reviewer_command` is falsy only).
- **Touchpoints:** [`.review-ticket.yaml`](../../../.review-ticket.yaml); [`_execute_reviewer`](../../../review_ticket/workflow.py) lines ~1984–1993.
- **Interpretation:** Operators need a **sentinel** (unset command, or documented stub) for “human/skill in the loop” until an adapter exists.
- **Options and tradeoffs:** Unset `reviewer_command` vs. ship `bin/review-ticket-reviewer-stub`; env override `REVIEWER_COMMAND`.
- **Probe:** With `reviewer_command` removed, does `run-review` on this issue reach `import-review` without calling `reviewer`?
- **Status:** open

### Windows checkout path length (`Filename too long`)

- **Expected:** `run-review` completes checkout on Windows like on Linux/macOS.
- **Observed:** Agent-run `review-ticket DOTNETIOT-2550 run-review` failed: `git worktree add` into `reviews\DOTNETIOT-2550\prs\kwik-trip-iot-KT.IoT.Zuul-pr-156\commits\<sha>\checkout` with `error: unable to create file ... Filename too long` (terminal reproduction, 2026-10-17).
- **Friction cost:** Blocks automated path entirely; reinforces operator belief that **only** `C:\repos\kwik-trip-iot` clones work—partially true for depth, but root cause is **dest path + nested repo paths**, not absence of local clones.
- **Touchpoints:** [`ensure_checkout`](../../../review_ticket/checkout.py), [`_ensure_diff`](../../../review_ticket/workflow.py); Windows long-path policy / `core.longpaths`.
- **Interpretation:** Multi-segment artifact paths under `reviews/` may exceed MAX_PATH for deep monorepo test filenames unless long paths enabled or checkout `dest` is shortened (e.g. under `cache_dir` or `C:\rt\worktrees\{sha}`).
- **Options and tradeoffs:** Enable OS + Git long paths (operator machine) vs. product change default checkout location to shorter root vs. `checkout_command` writing to short `{dest}`.
- **Probe:** Same SHA with `dest` under `C:\rt\wt\<short-sha>` succeeds on this machine?
- **Status:** open (reproduced)

## Cross-cutting design opportunities

1. **Single “review handoff” story** — From `READY` / automated-review: one screen listing `active_pr`, context path, whether `reviewer_command` is configured, and exact next command (`import-review` vs. `review apply`).
2. **Reviewer adapter as first-class config** — Document `reviewer_command` examples for: stub handoff, local script, UI.Admin variant keyed by repo name pattern.
3. **Windows-first checkout** — Short worktree roots or long-path detection with actionable error linking to docs.

Priority: **unblock checkout on Windows** before investing in API automation; otherwise adapters cannot be tested on this issue.

## Evidence index

| Item | Location |
| --- | --- |
| Session / next command | `reviews/DOTNETIOT-2550/session.json` |
| Terminal READY → run-review | Operator terminal (~2026-10-17) |
| run-review failure | `ToolError` from `git worktree add`, filename too long (agent shell) |
| PR list | Zuul#156, KT.IoT#144, UI.Admin#354 (terminal + session) |
| Config placeholder | `.review-ticket.yaml` `reviewer_command` |
| evaluate-run | **evaluate-run not run—engine verdict omitted.** |
