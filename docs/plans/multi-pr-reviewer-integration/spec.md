# Multi-PR reviewer integration

Status: **approved specification** — from operator retro interview (2026-10-17).

## Source

- Bundle: [README](README.md)
- Retro: [retro.md](retro.md) — investigations: `run-review` vs manual checkout; three PRs / `active_pr`; peer-review markdown vs `findings.json`; placeholder `reviewer_command` / `import-review`; Windows checkout path length.

## Operator outcome

After cloning **review-pilot** and configuring `.review-ticket.yaml`, you can complete peer review for a multi-PR Jira issue (e.g. DOTNETIOT-2550) **without** a separate ad-hoc markdown → JSON conversion step: `run-review` runs a **headless** in-repo reviewer adapter, you **curate** findings in an interactive step (v1: list + toggle + edit text; later: diff-hunk / patch-picker UX), then **`publish-review`** posts inline comments to the **active** GitHub PR. Repeat for each PR via `pr select`. Existing org clones under `C:\repos\...` satisfy checkout via `checkout_command`.

## Problem statement

The CLI’s integration boundary is **`findings.json`** and the human-review → **`proposed-review.json`** → **`publish-review`** path. Your trusted workflow uses Cursor **peer-review** / **ui-admin-reviewer** skills that emit long-form markdown, while `run-review` expects a configured **`reviewer_command`** and (today) may fail on Windows when using deep paths under `reviews/.../checkout`. There is no cohesive “configure and go” story: which command replaces fetch/checkout, how to run the agent headlessly, how to triage before GitHub, and how to loop three PRs without publishing against the wrong repo.

## Scope

### In scope

- **In-repo reviewer adapter** wired as `reviewer_command` (clone, configure, run).
- **`checkout_command`** documented and configured for **existing local clones** (org convention); `{dest}` / verification behavior unchanged.
- **YAML agent routing** (`reviewer_by_repository` or equivalent) for default vs **ui-admin** reviewer on `KT.IoT.UI.Admin`.
- **Headless** agent invocation that writes reviewer JSON to `{output}` per README contract.
- **Human triage v1 (B):** new interactive command (TUI) to accept/reject per finding, edit summary/explanation (and `must_fix` where applicable), preview counts of what will publish, persist **`human-review.json`** and regenerate **`proposed-review.json`** — same semantics as `review apply`.
- **Multi-PR operator loop** documented: `active_pr` → full chain → `pr select` → repeat; handoff messaging after `READY` (context path, configured reviewer, next command).
- **Skills/agents in repo:** migrate or add Cursor skills/agents needed for JSON-producing review (most skills you rely on live in this repo).
- **Placeholder `reviewer_command`:** documented sentinel (unset vs real script path) so operators are not blocked by a fake `reviewer` on PATH; `import-review` remains escape hatch.
- **Human-readable artifacts** when triage is file-based (interim): pretty-printed `findings.json`, `proposed-review.json`, and/or a generated `review-preview.md` for reading without the TUI.

### Out of scope

- **Single command that reviews and publishes all PRs** without per-PR gates.
- **Jira transitions**, analyzer gates, or virtualization changes (assumed already working).
- **Mandatory OS-wide long-path policy** as the primary fix (org uses `checkout_command` instead); product may still add better errors later.
- **Fully rich patch-picker TUI (C)** in the first delivery — tracked as follow-up with explicit upgrade path from B.
- **evaluate-run** / steward audit of the retro session.

## Decisions

| ID | Decision | Rationale | Retro link |
|----|----------|-----------|------------|
| D1 | Primary integration is **`reviewer_command` wrapper** in this repo, not manual clone + markdown import. | Operator chose option A; one `run-review` step. | § Peer-review markdown vs `findings.json` |
| D2 | Checkout uses **`checkout_command`** into **`C:\repos\...`** clones. | Org convention; avoids Windows MAX_PATH under `reviews/.../checkout`. | § Windows checkout path length |
| D3 | **Headless** adapter; no requirement to keep a Cursor window open for `run-review` to finish. | Operator preference. | § Placeholder / handoff |
| D4 | Triage **v1 = B** (list, toggle, edit); **target C** (hunk-level / `git add -ip`-like); **A acceptable** only if on-disk JSON/preview is human-readable. | Phased UX without blocking publish. | Cross-cutting handoff |
| D5 | Agent selection via **YAML map in global config** (e.g. per `owner/repo`), not hard-coded heuristics. | UI.Admin needs ui-admin reviewer; explicit and testable. | § Three PRs |
| D6 | **One GitHub review per PR**; loop via `pr select` / `pr select-all`. | Matches GitHub model and session `active_pr`. | § Three PRs |
| D7 | **Skills/agents live in review-pilot** (personal tooling, repo-local). | Clone-configure-go. | Cross-cutting adapter config |
| D8 | Unset or real **`reviewer_command`** only — no non-existent default on PATH. | Avoid false execution vs handoff. | § Placeholder `reviewer_command` |

## Assumptions

- DOTNETIOT-2550 (or similar) has already reached **`READY`** / automated-review for each tracked PR before `run-review`.
- `gh` and `acli` are configured on the reviewer machine.
- Headless Cursor/agent CLI (or SDK) is available to the wrapper with credentials the operator already uses locally.
- Inline GitHub comments require valid `path` / `line` / `side` on the PR diff; findings off-diff stay in the review summary only (existing publish behavior).
- `review apply` flag/JSON API remains supported for automation and tests; the TUI is an additional front end to the same `human-review.json` shape.

## Acceptance criteria

1. **Configure:** A new operator can follow README + bundle docs to set `reviewer_command`, `checkout_command`, and `reviewer_by_repository` (or documented equivalent) and run `review-ticket <ISSUE> run-review` for the **active** PR without editing Python.
2. **Checkout:** On Windows, with org `checkout_command`, `run-review` for Zuul#156 (DOTNETIOT-2550 SHA) completes checkout/diff preparation **without** “filename too long” under `reviews/.../checkout` as the checkout root.
3. **Headless review:** `run-review` invokes the adapter; on success, `reviews/.../review/findings.json` exists and passes `normalize_findings`; session advances to human-review with next command pointing at **interactive triage** (not only `--accept-all`).
4. **Routing:** When `active_pr` is `kwik-trip-iot/KT.IoT.UI.Admin#354`, the adapter uses the **ui-admin** entry from config; other tracked repos use the default reviewer entry.
5. **Triage v1:** `review-ticket <ISSUE> review interactive` (name negotiable in implementation) loads automated findings, lets the operator accept/reject each finding, edit summary and per-finding explanation, shows how many inline vs summary-only comments will publish, and on save writes `human-review.json` and `proposed-review.json` equivalent to `review apply --file`.
6. **Publish:** After triage, `review-ticket <ISSUE> publish-review --yes` posts to the PR matching `active_pr` and `active_sha`; operator documentation states the **three-PR loop** (Zuul → KT.IoT → UI.Admin) with explicit `pr select` commands.
7. **Handoff:** When gates are `READY`, terminal/issue-report output lists **active PR**, **context path** (`review/context/prompt.md`), whether **reviewer_command** is set, and the exact next commands (`run-review` → `review interactive` → `publish-review`).
8. **Escape hatch:** With `reviewer_command` unset, `run-review` reaches **import-review** handoff without executing a missing binary (existing behavior preserved and documented).
9. **Readable interim:** If TUI is not used, `findings.json` / `proposed-review.json` (and optional `review-preview.md`) are sufficient for a human to decide accept/reject without raw one-line JSON (formatting or generator documented).

## Verification plan

- **DOTNETIOT-2550 smoke:** On operator machine — `run-review` for Zuul#156 → interactive triage (accept subset, edit one explanation) → `publish-review --yes` (dry-run or real PR per operator choice); confirm inline comments only on diff lines.
- **Routing:** Switch to `KT.IoT.UI.Admin#354`, `run-review` logs or receipt shows ui-admin agent/skill from config.
- **Multi-PR:** After first publication, `review-ticket DOTNETIOT-2550` surfaces next PR or docs checklist matches remaining PRs.
- **Regression:** Existing pytest acceptance paths for `import-review`, `review apply --file`, and publish fingerprint unchanged.
- **Windows checkout:** Reproduce prior failure without `checkout_command`; confirm success with org `checkout_command` template.

### CLI-shaped flow (Given / When / Then)

```gherkin
Given issue DOTNETIOT-2550 is READY with three tracked PRs and active_pr is Zuul#156
When I run review-ticket DOTNETIOT-2550 run-review
Then findings.json exists and next step is human triage (interactive or documented file path)

Given I completed run-review for the active SHA
When I run review interactive and reject two findings and edit one explanation then save
Then human-review.json and proposed-review.json reflect those decisions

When I run publish-review --yes
Then GitHub receives a review on kwik-trip-iot/KT.IoT.Zuul#156 at the snapshotted SHA

When I run pr select kwik-trip-iot/KT.IoT#144 and repeat the chain
Then publication targets KT.IoT#144 only
```

## Implementation hints (optional)

- Adapter: `bin/` or `scripts/review-ticket-reviewer.ps1` + cross-platform entry if needed; placeholders `{context}`, `{output}`, `{checkout}`, `{repository}`, `{sha}`.
- Config: extend `.review-ticket.yaml` with `checkout_command`, `reviewer_by_repository`, example block for kwik-trip-iot triple.
- Co-locate `.cursor/skills/` (peer-review JSON mode or dedicated `review-ticket-reviewer` skill) and agent defs the wrapper invokes headlessly.
- TUI: Python `curses` / `rich` / `textual` — read `findings.json` + `diff-lines.json` + patch file from context; write same structure as `_human_from_flags` / `--file`.
- v2 (C): hunk navigation using `diff.patch` and diff index; highlight GitHub-eligible lines.
- Fix sample config: remove or replace `reviewer_command: "reviewer {context} {output}"` until the real script exists; document `REVIEWER_COMMAND` override.
- Issue-report / `resume` messaging in `workflow.py` for cross-cutting handoff screen.

## Deferred / follow-up

- **TUI v2 (C):** patch/hunk picker with side-by-side or inline diff preview.
- **Product:** shorter default worktree root or long-path detection with doc link (optional; not org primary).
- **`review all` batch** with per-PR stop gates (if ever needed).
- **Probe from retro:** auto-suggest next `pr select` after successful publish; `prompt.md` alone sufficient without opening `C:\repos` (validate after adapter lands).
