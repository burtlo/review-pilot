---
name: peer-review
description: >-
  Pre-merge peer review via the reviewer subagent. Use for /peer-review,
  review-ticket run-review (headless JSON), or a full production-minded branch
  review without a parent-agent summary.
disable-model-invocation: true
---

# Peer review

Use when the user runs `/peer-review` or when **review-ticket** invokes the headless adapter (`scripts/review_ticket_reviewer.py`).

## Headless review-ticket (run-review)

When the adapter prompt names a review context directory, checkout path, and output JSON path:

- You **are** the `reviewer` agent. Follow `.cursor/agents/reviewer.md` (headless section + review principles).
- Do **not** call Task or Subagent.
- The checkout path is the repository under review; the context directory holds PR/Jira/diff inputs.

## Interactive `/peer-review`

Use when the user runs `/peer-review`.

The user’s scope hint is whatever they typed **after** `/peer-review` on the same message (for example `this branch`, a Jira key, a branch name, or a PR URL). If they only sent `/peer-review`, treat the hint as **Review the current branch.**

## Do not nest

If this run **is** the `reviewer` subagent (you were started with `subagent_type: reviewer`), perform the review yourself per `.cursor/agents/reviewer.md`. Do **not** call Task or Subagent.

## Delegate once

Otherwise launch exactly one `reviewer` subagent:

- `run_in_background: false` unless the user explicitly asks for background
- `description: "Peer review"`
- `subagent_type: "reviewer"`

Set **Full Repository Path** to the absolute path of the git repository that contains the changes to review. It may be a subfolder of the workspace. Do not change the workspace root or call `move_agent_to_root` when the repo is already reachable.

If the user’s hint names a **specific PR, branch, or ticket branch**, ensure that branch is checked out locally before delegating:

- Resolve the hint to a local branch name when possible.
- If another branch is checked out, switch to the target branch.
- If Git blocks checkout (dirty tree, conflicts), explain and ask whether to stash; stash only after confirmation, then retry.
- Delegate only after the intended branch is checked out.

Use this prompt shape:

```text
Perform a rigorous pre-merge review of the currently checked-out branch.

Full Repository Path: <absolute repository path>
User context: <user hint from the slash command>
```

Append a `Custom Instructions:` line only when the user gave extra review focus (for example “auth only” or “migrations only”).

Do not compute or summarize the diff in the parent before delegating. The reviewer establishes scope, runs validation when feasible, and writes the full report.

## Return verbatim

When the subagent finishes, return its report **verbatim** from `# Summary` through `# Merge Recommendation` (include every section the subagent produced: Findings, Missing Tests, Production and Rollout Risks, and so on). **No** lead-in, **no** recap, **no** severity table substitute, **no** “here’s what the reviewer found,” and **no** offers to fix code unless the subagent’s text already includes them.

If the subagent fails before a report:

- Fix incorrect invocation (missing path, wrong subagent type) and retry **once**.
- For other failures, retry **once** with the same prompt.
- If it still fails, state briefly that peer review could not complete and include the error text. Do not invent findings.

Do not fix findings or rerun review unless the user explicitly asks.
