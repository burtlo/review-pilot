---
name: peer-review-ui-admin
description: >-
  Pre-merge Blazor admin UI review via ui-admin-reviewer. Use for
  /peer-review-ui-admin, review-ticket run-review on UI.Admin repos (headless
  JSON), or the full UI migration report without a parent-agent summary.
disable-model-invocation: true
---

# Peer review (UI admin)

Use when the user runs `/peer-review-ui-admin` or when **review-ticket** routes `ui-admin-reviewer` for a mapped repository.

## Headless review-ticket (run-review)

When the adapter prompt names context directory, checkout path, and output JSON path:

- You **are** the `ui-admin-reviewer` agent. Follow `.cursor/agents/ui-admin-reviewer.md` (headless section + UI review principles).
- Do **not** call Task or Subagent.
- Read `AGENTS.md` and migration skills under the **checkout** repository.

## Interactive `/peer-review-ui-admin`

Use when the user runs `/peer-review-ui-admin`.

The user’s scope hint is whatever they typed **after** `/peer-review-ui-admin` on the same message (for example `this branch`, a Jira key, or a PR URL). If they only sent `/peer-review-ui-admin`, treat the hint as **Review the current branch.**

## Do not nest

If this run **is** the `ui-admin-reviewer` subagent, perform the review yourself per `.cursor/agents/ui-admin-reviewer.md`. Do **not** call Task or Subagent.

## Delegate once

Otherwise launch exactly one `ui-admin-reviewer` subagent:

- `run_in_background: false` unless the user explicitly asks for background
- `description: "Peer review UI admin"`
- `subagent_type: "ui-admin-reviewer"`

Set **Full Repository Path** to the absolute path of the git repository for the admin webapp (often `KT.IoT.UI.Admin` or the solution root that contains it). Do not change the workspace root or call `move_agent_to_root` when the repo is already reachable.

If the user’s hint names a **specific PR, branch, or ticket branch**, ensure that branch is checked out locally before delegating (same checkout and stash rules as `/peer-review`).

Use this prompt shape:

```text
Perform a rigorous pre-merge UI admin review of the currently checked-out branch.

Full Repository Path: <absolute repository path>
User context: <user hint from the slash command>
```

Append `Custom Instructions:` only when the user gave extra focus (for example a single page or migration surface).

Do not pre-summarize the diff in the parent. The subagent reads `AGENTS.md`, migration skills when applicable, establishes scope, runs `dotnet` validation when feasible, and writes the full report.

## Return verbatim

When the subagent finishes, return its report **verbatim** from `# Summary` through `# Merge Recommendation` (include Findings, Missing Tests, Manual QA Script, Production and Rollout Risks, and any other sections the subagent produced). **No** lead-in, **no** recap, **no** condensed findings list, and **no** offers to fix code unless the subagent’s text already includes them.

If the subagent fails before a report:

- Fix incorrect invocation and retry **once**.
- For other failures, retry **once** with the same prompt.
- If it still fails, state briefly that UI peer review could not complete and include the error text.

Do not fix findings or rerun review unless the user explicitly asks.
