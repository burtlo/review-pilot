# Operator guide — DOTNETIOT-2550 (three-PR loop)

Clone **review-pilot**, configure `.review-ticket.yaml`, then complete **one GitHub review per pull request**. Publication always targets **`active_pr`** and the snapshotted **`active_sha`** — switch PRs with `pr select` before each new chain.

Companion docs: [checkout-operator.md](checkout-operator.md) (Windows `checkout_command`), [README](../../../README.md) (adapter + config), [spec.md](spec.md) AC6.

## Tracked pull requests

| Order | `pr select` ref | Repository | PR |
| --- | --- | --- | --- |
| 1 | *(default `active_pr`)* | `kwik-trip-iot/KT.IoT.Zuul` | #156 |
| 2 | `kwik-trip-iot/KT.IoT#144` | `kwik-trip-iot/KT.IoT` | #144 |
| 3 | `kwik-trip-iot/KT.IoT.UI.Admin#354` | `kwik-trip-iot/KT.IoT.UI.Admin` | #354 |

Typical org clones: `C:\repos\kwik-trip-iot\KT.IoT.Zuul`, `KT.IoT`, `KT.IoT.UI.Admin`.

## One-time setup

1. Install review-ticket (`python -m pip install -e .`) and sign in to `acli` + `gh`.
2. Copy or merge settings into `.review-ticket.yaml`:
   - `github_org: kwik-trip-iot`
   - **`reviewer_command`** → in-repo adapter ([README § Configure and run](../../../README.md))
   - **`checkout_command`** on Windows → [checkout-operator.md](checkout-operator.md)
   - **`reviewer_by_repository`** for UI.Admin → `agent: ui-admin-reviewer` on `kwik-trip-iot/KT.IoT.UI.Admin`
3. Start the session and reach **`READY`** / `step: automated-review` for all three PRs:

```bash
review-ticket DOTNETIOT-2550
```

Confirm terminal output lists each tracked PR and SHA. If only one PR is in scope, run `review-ticket DOTNETIOT-2550 pr select-all`.

## Per-PR review chain

Repeat the block below for **Zuul #156**, then **KT.IoT #144**, then **UI.Admin #354**. After `publish-review`, switch PR before starting `run-review` again.

| Step | Command | Success signal |
| --- | --- | --- |
| A | `review-ticket DOTNETIOT-2550 run-review` | `reviews/.../review/findings.json`; `next` → `attach` (or `import-review` if `reviewer_command` unset) |
| B | `review-ticket DOTNETIOT-2550 attach` | Saves `human-review.json` + `proposed-review.json` (same semantics as `review apply --file`) |
| C | `review-ticket DOTNETIOT-2550 publish-review --yes` | GitHub review on **current** `active_pr` @ `active_sha` |

**File-based triage (no TTY):** use `review apply` with flags or `--file` instead of step B; optional `review-preview.md` / `reviewer-report.md` under the commit’s `review/` directory.

**Escape hatch:** with `reviewer_command` unset, step A stops at `import-review`; paste normalized JSON, then continue from step B.

At READY, the CLI should show **context** (`.../review/context/prompt.md`), **reviewer_command: configured|unset**, and the **chain** hint when multiple PRs are tracked.

## Checklist — PR 1: Zuul #156

- [ ] `active_pr` is `kwik-trip-iot/KT.IoT.Zuul#156` (first tracked ref after `pr select-all`)
- [ ] `review-ticket DOTNETIOT-2550 run-review` completes (checkout via `checkout_command` on Windows if needed)
- [ ] Triage findings → `attach` (or `review apply`)
- [ ] `publish-review --yes` posts to **Zuul #156** only
- [ ] Receipt / GitHub UI shows review on Zuul at the session SHA

## Checklist — PR 2: KT.IoT #144

- [ ] `review-ticket DOTNETIOT-2550 pr select kwik-trip-iot/KT.IoT#144`
- [ ] `review-ticket DOTNETIOT-2550` shows `active_pr` KT.IoT#144 and new `active_sha`
- [ ] Repeat chain: `run-review` → `attach` → `publish-review --yes`
- [ ] Publication targets **KT.IoT #144** only (not Zuul or UI.Admin)

## Checklist — PR 3: UI.Admin #354

- [ ] `review-ticket DOTNETIOT-2550 pr select kwik-trip-iot/KT.IoT.UI.Admin#354`
- [ ] `run-review` receipt or log shows **ui-admin** agent from `reviewer_by_repository`
- [ ] Repeat chain: `run-review` → `attach` → `publish-review --yes`
- [ ] Publication targets **UI.Admin #354** only

## After all three reviews

Continue the workflow for the **active** PR (testing, disposition, Jira) per [README § Steps](../../../README.md). There is **no** single command that reviews all PRs without per-PR gates.

## Verification (AC6)

- Doc lists Zuul → KT.IoT → UI.Admin with explicit `pr select` commands (this page).
- README links here from the multi-PR / checkout section.
- Smoke: one full chain on Zuul#156 with subset of findings published; routing check on UI.Admin#354 adapter profile.

## Related

- [retro.md](retro.md) — operator session that motivated this bundle
- [implementation.md](implementation.md) — package P8
