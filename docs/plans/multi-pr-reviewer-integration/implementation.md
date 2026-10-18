# Multi-PR reviewer integration — implementation map

Status: **ready for orchestration** — companion to [spec.md](spec.md). Canonical map for implementer assignment and verifier checklists. Refresh with `/spec-implementation-map @spec.md` after material spec or code changes.

## Spec alignment

### Strengths (spec)

- Clear integration boundary: `findings.json` → `human-review.json` → `proposed-review.json` → `publish-review` (matches existing workflow).
- Phased triage (B now, C later) avoids blocking on patch-picker UX.
- `checkout_command` + org clones is a realistic Windows mitigation without mandating OS long-path policy.
- AC and verification plan name DOTNETIOT-2550 smoke, routing, multi-PR loop, and regression targets.
- Decisions D1–D8 are testable and map cleanly to config, adapter, CLI, and docs surfaces.

### Strengths (repository)

- **`run-review` / `import-review` pipeline** is implemented: context bundle, external reviewer, normalization, `reviewer-report.md`, and advance to human-review ([`workflow.py`](../../../review_ticket/workflow.py) `_execute_reviewer`, `run_review`, `import_review`).
- **`checkout_command`** is wired in [`checkout.py`](../../../review_ticket/checkout.py) `ensure_checkout` with `{owner}`, `{repo}`, `{sha}`, `{dest}`, `{repository}` and post-checkout SHA verification.
- **`review apply`** and `_human_from_flags` in [`cli.py`](../../../review_ticket/cli.py) define the canonical `human-review.json` shape; [`apply_review`](../../../review_ticket/workflow.py) builds `proposed-review.json` via `build_review_payload`.
- **Publish path** enforces live HEAD match, inline-only-on-diff via `diff_index`, fingerprint dedup ([`publish_review`](../../../review_ticket/workflow.py), [`build_review_payload`](../../../review_ticket/findings.py)).
- **Multi-PR session model** exists: `active_pr`, `pr select` / `pr select-all`, per-PR artifact trees ([`select_pr`](../../../review_ticket/workflow.py), [README](../../../README.md)).
- **Reviewer contract** documented in README + [`reviewer_prompt`](../../../review_ticket/reports.py); context files written by [`_write_context`](../../../review_ticket/workflow.py).
- **JSON artifacts** already pretty-printed via [`write_json`](../../../review_ticket/storage.py) (`indent=2`).
- **Acceptance tests** cover `run-review` → `publish-review`, stale SHA, repeat publication ([`tests/test_acceptance.py`](../../../tests/test_acceptance.py)).

### Gaps and clarifications before build

| Topic | Present state | Spec requirement | Suggested resolution |
|-------|---------------|------------------|----------------------|
| Placeholder `reviewer_command` | [`.review-ticket.yaml`](../../../.review-ticket.yaml) and README example set `reviewer {context} {output}`; falsy-only handoff in `_execute_reviewer` | D8, AC8: unset or **real** script only | Remove commented placeholder from samples; document unset + `REVIEWER_COMMAND`; optional in-repo stub that exits 0 with handoff message only if needed |
| `reviewer_by_repository` | Not in [`Config`](../../../review_ticket/config.py) | D5, AC4: ui-admin for `KT.IoT.UI.Admin` | Add YAML map + resolver; pass agent/skill id into adapter mapping (new placeholders or env) |
| Headless adapter | No `bin/` reviewer script; no JSON peer-review skill in [`.cursor/skills/`](../../../.cursor/skills/) | D1, D3, D7, AC1, AC3 | Ship `scripts/` or `bin/` wrapper invoking Cursor agent/SDK; co-locate skill + agent defs |
| `checkout_command` docs | Config field exists; **not** in README sample | D2, AC1, AC2 | Document tokens + kwik-trip `C:\repos\...` template in README + bundle operator guide |
| Windows long path | Default path still `reviews/.../commits/<sha>/checkout` + worktree | AC2: succeed with org `checkout_command` | Operator config only for v1; optional: detect `ToolError` “filename too long” → link to bundle doc (spec deferred product fix) |
| Interactive triage | Only `review apply` flags / `--file` | D4, AC5: `review interactive` (name negotiable) | New subcommand + TUI module; reuse `_human_from_flags` shape / `apply_review` |
| Post–`run-review` next step | Points to `review apply --accept-all` | AC3, AC7: interactive triage in chain | Update `StepResult.next_command` in `_execute_reviewer` and `step_publication` when interactive exists |
| READY handoff screen | `_render` shows issue, pr, step, summary, next, report | AC7: active PR, **context path**, reviewer configured?, full chain | Extend `_render` and/or `step_automated_review` summary; optional `issue-report` appendix |
| Multi-PR loop docs | README mentions `pr select`; no Zuul→KT→UI.Admin checklist | AC6 | Bundle operator doc or README section with explicit `pr select` commands |
| Readable interim without TUI | `reviewer-report.md` after run-review; `proposed-review.json` is JSON | AC9 | Add `review-preview.md` generator (inline vs summary counts) on apply / run-review; document `reviewer-report.md` as interim reader |
| Tests | Mock `reviewer` only; no `checkout_command`, import handoff, interactive, routing | Verification plan | Add unit tests in `test_checkout.py`, acceptance for handoff + apply parity |

### Acceptance criteria traceability

| AC | Present | Delta / work |
|----|---------|----------------|
| 1 | Partial: README covers `reviewer_command`; `checkout_command` undocumented; no routing | **P1**, **P2**, **P3**, **P4**, **P8** |
| 2 | Code supports `checkout_command`; default worktree still deep under `reviews/` | **P2** (operator template + doc); manual smoke on DOTNETIOT-2550 |
| 3 | `run-review` → `findings.json`, human-review step; next is `--accept-all` | **P4** (adapter), **P6** (next → interactive) |
| 4 | No per-repo reviewer routing | **P3**, **P4** |
| 5 | No interactive command | **P5** |
| 6 | `publish-review` + `pr select` work; no dedicated loop doc | **P8** |
| 7 | Partial terminal output; no reviewer_config / context_path lines | **P6** |
| 8 | Works when `reviewer_command` is `None`; broken when fake PATH name set | **P1** |
| 9 | Partial (`reviewer-report.md`, indented JSON) | **P7** |

---

## Repository layout

Single Python package `review_ticket` with CLI entry [`review_ticket/cli.py`](../../../review_ticket/cli.py) and [`bin/review-ticket`](../../../bin/review-ticket). Workflow orchestration lives in [`review_ticket/workflow.py`](../../../review_ticket/workflow.py). External tools via [`review_ticket/adapters.py`](../../../review_ticket/adapters.py) (`run_external`). Plan bundle under this directory.

| Path | Role |
|------|------|
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | Steps, `run_review`, `_execute_reviewer`, `apply_review`, `publish_review`, `resume`, `_render` |
| [review_ticket/cli.py](../../../review_ticket/cli.py) | Argparse, `review apply`, dispatch |
| [review_ticket/config.py](../../../review_ticket/config.py) | `.review-ticket.yaml` loading |
| [review_ticket/checkout.py](../../../review_ticket/checkout.py) | `ensure_checkout`, `checkout_command` |
| [review_ticket/findings.py](../../../review_ticket/findings.py) | `normalize_findings`, `build_review_payload` |
| [review_ticket/reports.py](../../../review_ticket/reports.py) | Markdown reports, `reviewer_prompt` |
| [review_ticket/storage.py](../../../review_ticket/storage.py) | Artifact paths, atomic writes |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) | End-to-end workflow tests |
| [tests/test_checkout.py](../../../tests/test_checkout.py) | Real git worktree only |
| [.review-ticket.yaml](../../../.review-ticket.yaml) | Operator config (placeholder reviewer today) |
| `reviews/DOTNETIOT-2550/` (local) | Smoke session (gitignored; evidence only) |

---

## Workstreams mapped to decisions

### D1 / D3 / D7 — In-repo headless `reviewer_command` adapter

**Present:** `_execute_reviewer` builds mapping `{context, output, checkout, repository, sha, issue}` and runs `reviewer_command`. Context dir includes `prompt.md`, `diff.patch`, etc. No repo-local script or agent.

**Required:** Wrapper configured in YAML; headless Cursor invocation; JSON at `{output}`.

| Resource | Role |
|----------|------|
| [workflow.py](../../../review_ticket/workflow.py) `_execute_reviewer` | Invocation contract (extend mapping if needed) |
| [adapters.py](../../../review_ticket/adapters.py) `run_external` | Shell-out |
| New `bin/` or `scripts/` | Adapter entry |
| New `.cursor/skills/…`, `.cursor/agents/…` | JSON-mode reviewer + ui-admin variant |

**Risks:** Credentials and Cursor CLI/SDK availability on operator machine (spec assumption); adapter must not require open IDE (D3).

### D2 — `checkout_command` to org clones

**Present:** [`ensure_checkout`](../../../review_ticket/checkout.py) branches on `config.checkout_command`; verifies HEAD == `sha`.

**Required:** Documented PowerShell/cmd template syncing PR head into `{dest}` using `C:\repos\kwik-trip-iot\...` without using deep `reviews/.../checkout` as the git root for worktree add.

| Resource | Role |
|----------|------|
| [checkout.py](../../../review_ticket/checkout.py) | Unchanged behavior unless error messaging added |
| [config.py](../../../review_ticket/config.py) | Load `checkout_command` (done) |

**Risks:** Custom script must still leave `{dest}` at reviewed SHA; wrong script → `ToolError` at verification.

### D5 — YAML `reviewer_by_repository`

**Present:** Single global `reviewer_command`.

**Required:** Map `owner/repo` → reviewer profile (default vs ui-admin); adapter logs/shows which profile ran (AC4).

| Resource | Role |
|----------|------|
| [config.py](../../../review_ticket/config.py) | New field + parse |
| [workflow.py](../../../review_ticket/workflow.py) | Resolve from `identity` before `run_external` |

**Risks:** Key format (`KT.IoT.UI.Admin` vs full name); document exact keys matching `session["active_pr"]` repo segment.

### D4 — Triage v1 (B)

**Present:** `review apply` with flags; `step_publication` nudges `--accept-all`.

**Required:** Interactive TUI: list findings, accept/reject, edit summary/explanation/`must_fix`, preview inline vs summary-only counts, save → same files as `--file`.

| Resource | Role |
|----------|------|
| [cli.py](../../../review_ticket/cli.py) | `review interactive` subparser |
| [workflow.py](../../../review_ticket/workflow.py) `apply_review` | Persist (reuse) |
| [findings.py](../../../review_ticket/findings.py) `build_review_payload` | Preview counts |
| New e.g. `review_ticket/triage_tui.py` | UI (likely **rich** or **textual** — not in [pyproject.toml](../../../pyproject.toml) today) |

**Risks:** Non-TTY CI must keep `review apply`; TUI should refuse or no-op with clear error when not interactive.

### D6 — One review per PR; `pr select` loop

**Present:** Implemented; publication scoped to `active_pr` / `active_sha`.

**Required:** Operator documentation for three-PR sequence.

### D8 — No fake default reviewer

**Present:** Sample YAML and README encourage nonexistent `reviewer` binary.

**Required:** Unset default in samples; handoff to `import-review`.

### D4 / AC7 — Handoff messaging

**Present:** `step_automated_review` → `run-review`; after review → `--accept-all`; `_render` minimal.

**Required:** At READY / automated-review gate: context path, reviewer configured flag, chain `run-review` → `review interactive` → `publish-review`.

---

## Orchestration packages

| ID | Title | Surfaces | Depends on | Primary paths | Verify (AC / tests) |
|----|-------|----------|------------|---------------|---------------------|
| P1 | Sentinel config & import handoff | config, docs | — | `.review-ticket.yaml`, README, tests | AC8; new acceptance test |
| P2 | `checkout_command` operator docs + sample | docs, config | P1 | README, bundle doc, `.review-ticket.yaml` example | AC1, AC2; extend `test_checkout.py` |
| P3 | `reviewer_by_repository` config + wiring | code, config | P1 | `config.py`, `workflow.py` | AC4; unit test resolver |
| P4 | Headless reviewer adapter + repo skills/agents | code, tooling, docs | P2, P3 | `bin/` or `scripts/`, `.cursor/`, README | AC1, AC3; smoke + mock adapter test |
| P5 | Interactive triage (`review interactive`) | code, cli-ui | — | `cli.py`, new TUI module, `workflow.py` | AC5 |
| P6 | Handoff & next-command chain | code, cli-ui | P5 | `workflow.py` `_render`, `step_automated_review`, `_execute_reviewer` | AC3, AC7 |
| P7 | Readable `review-preview.md` (non-TUI) | code, docs | P5 optional | `reports.py` or `workflow.py` | AC9 |
| P8 | Multi-PR operator guide (DOTNETIOT-2550) | docs | P4, P6 | This bundle, README link | AC6 |
| P9 | Regression & acceptance expansion | code, ci | P1–P5 | `tests/` | Verification plan regression |

### Package briefs (for implementer agents)

#### P1 — Sentinel config & import handoff

- **Goal:** Operators without an adapter see `import-review` handoff, never a failing `reviewer` spawn.
- **Deliverables:** Remove or comment placeholder from committed `.review-ticket.yaml`; README states unset `reviewer_command` / `REVIEWER_COMMAND`; acceptance test with `reviewer_command=None` through `run-review`.
- **Out of scope:** Implementing real adapter (P4).
- **Touchpoints:** `.review-ticket.yaml`, README, `tests/test_acceptance.py`, `tests/support.py` default.

#### P2 — `checkout_command` operator docs + sample

- **Goal:** Windows operators point checkout at short `C:\repos\...` paths.
- **Deliverables:** README section (placeholders); example block for kwik-trip triple; optional commented lines in `.review-ticket.yaml`; unit test invoking `ensure_checkout` with scripted `checkout_command`.
- **Out of scope:** Changing default dest path in code (spec out of scope for mandatory long-path policy).
- **Touchpoints:** README, bundle operator doc, `tests/test_checkout.py`.

#### P3 — `reviewer_by_repository`

- **Goal:** `KT.IoT.UI.Admin` uses ui-admin reviewer entry from YAML.
- **Deliverables:** Config schema (e.g. `reviewer_by_repository: { "kwik-trip-iot/KT.IoT.UI.Admin": { command: ... } }` or `agent:` key); merge with global `reviewer_command`; receipt/log line in run output.
- **Out of scope:** Adapter internals (P4).
- **Touchpoints:** `config.py`, `workflow.py`, tests.

#### P4 — Headless reviewer adapter + skills

- **Goal:** One configured `reviewer_command` runs in-repo script that invokes Cursor headlessly and writes schema-valid JSON.
- **Deliverables:** Cross-platform entry (PowerShell + sh); skill(s) for JSON output; agent definitions; README “Configure and run”; wire sample `reviewer_command` to script path.
- **Out of scope:** TUI (P5); markdown peer-review conversion.
- **Touchpoints:** `bin/` or `scripts/`, `.cursor/skills/`, `.cursor/agents/`, README.

#### P5 — Interactive triage

- **Goal:** `review-ticket ISSUE review interactive` mirrors `review apply --file` semantics with UX from spec.
- **Deliverables:** Subcommand; TUI listing findings from `findings.json`; toggle accept/reject; edit summary, explanation, must_fix; show inline vs summary-only counts from `diff-lines.json`; save → `apply_review`.
- **Out of scope:** Hunk picker (deferred C).
- **Touchpoints:** `cli.py`, new module, dependency in `pyproject.toml` if needed.

#### P6 — Handoff & next-command chain

- **Goal:** Terminal output at READY and after `run-review` matches AC7.
- **Deliverables:** `next_command` → `review interactive`; `_render` lines for `context: ...`, `reviewer_command: configured|unset`; multi-step hint when `len(active_prs) > 1`.
- **Out of scope:** Auto `pr select` after publish (retro probe / deferred).
- **Touchpoints:** `workflow.py`.

#### P7 — `review-preview.md`

- **Goal:** File-based triage without TUI (AC9 / D4-A).
- **Deliverables:** Generate markdown summary of findings + publish preview after `run-review` and/or `apply_review`; document in README.
- **Out of scope:** Replacing `reviewer-report.md` entirely.
- **Touchpoints:** `reports.py`, `workflow.py`.

#### P8 — Multi-PR operator guide

- **Goal:** Clone-configure-go for DOTNETIOT-2550 three-PR loop.
- **Deliverables:** Bundle doc (checklist: Zuul#156 → KT.IoT#144 → UI.Admin#354 with `pr select`); link from README; update bundle README + plans index status.
- **Out of scope:** `review all` batch command.
- **Touchpoints:** `docs/plans/multi-pr-reviewer-integration/`.

#### P9 — Regression & acceptance expansion

- **Goal:** Lock handoff, routing, interactive parity, publish fingerprint.
- **Deliverables:** Tests for P1, P3, P5 (apply parity), ensure existing publish tests unchanged.
- **Out of scope:** Live `gh` / Cursor in CI.
- **Touchpoints:** `tests/`.

### Verifier briefs

#### P1 — verification

- **Must prove:** `reviewer_command` unset → `run-review` → `REVIEW_DECISION`, no `reviewer` in runner calls, `next` includes `import-review`.
- **Commands / probes:** `pytest tests/test_acceptance.py -k handoff` (new); config `reviewer_command=None`.
- **Regression watch:** Existing `test_reviewer_places_must_fix_inline...` still passes with explicit mock command.

#### P2 — verification

- **Must prove:** `ensure_checkout` calls custom template with `{dest}` and verifies SHA.
- **Commands / probes:** `pytest tests/test_checkout.py`; manual Windows note in verifier report optional.
- **Regression watch:** Default gh clone + worktree path in acceptance tests.

#### P3 — verification

- **Must prove:** Resolver picks ui-admin mapping for `kwik-trip-iot/KT.IoT.UI.Admin`.
- **Commands / probes:** Unit test; optional log assertion in integration test with fake adapter echoing argv.
- **Regression watch:** Repos not in map use default command.

#### P4 — verification

- **Must prove:** Adapter writes JSON; `normalize_findings` succeeds; session reaches human-review.
- **Commands / probes:** Scripted adapter in test; operator smoke checklist in spec verification plan.
- **Regression watch:** `import-review` path unchanged.

#### P5 — verification

- **Must prove:** Interactive save produces byte-equivalent semantics to `review apply --file` for same decisions (summary, findings map, proposed payload).
- **Commands / probes:** Automated test driving TUI API or extracted controller without full terminal; manual smoke for counts.
- **Regression watch:** All `review apply` flag tests.

#### P6 — verification

- **Must prove:** After analyzers READY, output includes context path and reviewer status; post `run-review`, `next` is `review interactive`.
- **Commands / probes:** Acceptance test on stdout from `_run`.
- **Regression watch:** `status` / `resume` still valid.

#### P7 — verification

- **Must prove:** `review-preview.md` exists and lists findings human-readably; inline count matches `build_review_payload`.
- **Commands / probes:** Unit test on fixture findings + diff index.
- **Regression watch:** `write_json` format unchanged.

#### P8 — verification

- **Must prove:** Doc lists three PRs and commands; README links bundle.
- **Commands / probes:** Doc review checklist AC6.
- **Regression watch:** —

#### P9 — verification

- **Must prove:** Full `pytest` green.
- **Commands / probes:** `python -m pytest`.
- **Regression watch:** Publish fingerprint, stale SHA, repeat publication tests.

---

## Suggested implementation order

**Canonical package sequence:** P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9

### Build order rationale

1. **P1** unblocks operators and CI handoff immediately (D8) without waiting on adapter.
2. **P2** before **P4** so adapter development and DOTNETIOT smoke are not blocked by Windows checkout failures (retro priority).
3. **P3** before **P4** so the adapter script receives correct routing on first integrated run.
4. **P5** before **P6** so `next_command` targets a real command.
5. **P7** can ship in parallel with **P6** after **P5** if staffed separately.
6. **P8** last so docs reflect final command names and config blocks.
7. **P9** continuous but must gate merge of P1–P5.

---

## Test and fixture resources

| Asset | Use |
|-------|-----|
| [tests/support.py](../../../tests/support.py) `ScriptedRunner`, `World.reviewer_output` | Mock `reviewer` / gh / git |
| [tests/test_acceptance.py](../../../tests/test_acceptance.py) | Primary workflow regression |
| [tests/test_checkout.py](../../../tests/test_checkout.py) | Extend for `checkout_command` |
| `reviews/DOTNETIOT-2550/` (local) | Manual smoke only; not in CI |
| DIFF fixture in support | Diff index / inline comment tests |

**CI:** No live Jira/GitHub/Cursor; adapter and routing via scripted commands. Interactive TUI tests should use extracted logic or `interactive=False` guards.

---

## Cross-cutting risks summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| Headless Cursor unavailable or differs by install | High | Document prerequisites; keep `import-review` |
| `checkout_command` script wrong SHA | High | Built-in verification in `ensure_checkout` |
| TUI dependency weight on minimal package | Medium | Prefer small `rich` prompt UI vs full textual |
| Placeholder config in repo misleads new clones | Medium | P1 |
| Multi-PR wrong target repo | Medium | P8 checklist + existing `active_pr` in `_render` |
| Line numbers off-diff → dropped inline comments | Medium | TUI preview counts; existing publish behavior |

---

## Related artifacts

- [spec.md](spec.md)
- [retro.md](retro.md)
- [README.md](../../../README.md)
