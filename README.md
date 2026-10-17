# review-ticket

A manual peer-review workflow. Give it a Jira issue id and it walks the readiness checks, keeps one artifact directory per commit, and stops whenever a person has to decide. It does not transition Jira or publish to GitHub unless that command is explicitly authorized.

This repository did not contain an existing reviewer skill, bug writer, virtualization profile, or Jira wrapper. The workflow shells out to the tools the team already runs and leaves their behavior alone.

## What it reuses

| Tool | Role |
| --- | --- |
| `acli` | Read a work item, list comments, add a comment, transition status |
| `gh` | Find the pull request, read checks, read review threads and CodeQL alerts, publish a review, comment with attachments |
| `git` | Fetch the reviewed SHA into a detached worktree so the current checkout is left alone |
| `docker` / `docker compose` | Pull a pinned image and start the profile for that issue |
| Reviewer command | Optional. Reads the context directory and writes findings JSON |
| Bug writer command | Optional. Receives a saved defect draft |
| Virtualization commands | Optional replacements for the built-in profile, image pull, and launch |

Set the optional commands in `.review-ticket.yaml` when the real skill or script is available. Until then, `run-review` writes the context bundle and waits for `import-review`.

## Install

Python 3.11 or newer. For a live review you also need `acli` signed in to Jira, `gh` 2.99 or newer (the `--attach` flag), `git`, and Docker when you reach local testing.

```bash
python -m pip install -e .
review-ticket DOTNETIOT-1234
```

Without an install, run `python bin/review-ticket` (or `python -m review_ticket`) from the repository root.

## Configuration

`.review-ticket.yaml` (or `.review-ticket.yml`) in the working directory is optional. Legacy `.review-ticket.json` is still read if no YAML file exists.

```yaml
# Single repo, or use github_org / github_user instead (see below).
github_repo: acme/widgets
# github_org: acme

status:
  in_progress: In Progress
  ready_for_peer_review: Ready for Peer Review
  in_peer_review: Peer Review
  approved: Ready for QA

required_checks:
  - build
analyzer_checks:
  - Bugbot
  - CodeQL
require_analyzers: true

standards:
  - docs/standards.md
image: ghcr.io/acme/widgets:feature
ports:
  - "8080:8080"

reviewer_command: "reviewer {context} {output}"
bug_writer_command: "bug-writer {draft}"
```

Pull request discovery (in order): PR URLs in the Jira issue text; then `github_repo` (`owner/repo`) for a single repository; else `github_org` for `gh search prs` with an `org:` qualifier across that organization’s repos; else `github_user` for a personal account (`user:` qualifier); else global `gh search prs` on the issue key. Set only one of `github_org` and `github_user`. You can also run `review-ticket ISSUE pr select owner/repo#number`.

`require_analyzers` defaults to true. A repository that does not run Bugbot or CodeQL should set `require_analyzers` to false or clear `analyzer_checks`. Missing analyzer checks stop for a reviewer decision. They do not by themselves send the issue back to the developer.

`REVIEWER_COMMAND`, `BUG_WRITER_COMMAND`, and `REVIEW_TICKET_REVIEWS_DIR` override the file.

## Command

`review-ticket DOTNETIOT-1234` creates or resumes the session, refreshes Jira and GitHub, and stops at the next human gate. The last lines report the outcome and the next command. Run the same command again later to refresh pending checks. A new pull request HEAD creates a new commit directory and leaves the previous one in place.

| Outcome | Meaning |
| --- | --- |
| `WAITING` | A required check is still running. Jira is not changed. |
| `ACTION_REQUIRED` | Developer work or a disposition is missing. The usual recommendation is In Progress, and it is not applied for you. |
| `REVIEW_DECISION` | Accept, reject, or edit a proposed result. |
| `READY` | The next command can run. |
| `BLOCKED` | A tool, permission, or test environment failed. The change is not treated as defective. |
| `COMPLETE` | This pass is recorded. A later SHA starts again. |

```bash
review-ticket DOTNETIOT-1234 status
review-ticket DOTNETIOT-1234 assess
review-ticket DOTNETIOT-1234 notes --accept
review-ticket DOTNETIOT-1234 notes --reject --notes "No environment or result was recorded."
review-ticket DOTNETIOT-1234 analyzers --return
review-ticket DOTNETIOT-1234 analyzers --accept-dispositions
review-ticket DOTNETIOT-1234 analyzers --override --notes "The remaining alert is in unchanged generated code."
review-ticket DOTNETIOT-1234 run-review
review-ticket DOTNETIOT-1234 import-review --file findings.json
review-ticket DOTNETIOT-1234 review apply --accept-all --event REQUEST_CHANGES
review-ticket DOTNETIOT-1234 publish-review --yes
review-ticket DOTNETIOT-1234 test prepare
review-ticket DOTNETIOT-1234 test fetch
review-ticket DOTNETIOT-1234 test launch
review-ticket DOTNETIOT-1234 test record --result pass --notes "Rejected a negative quantity."
review-ticket DOTNETIOT-1234 pr comment --body-file comment.md --attach shot.png --attach walk.webm --yes
review-ticket DOTNETIOT-1234 jira comment --body-file return-comment.md --yes
review-ticket DOTNETIOT-1234 jira transition --status "In Progress" --yes
review-ticket DOTNETIOT-1234 bug --summary "Negative quantity persists after reload" --body "Steps..."
review-ticket DOTNETIOT-1234 disposition --choice approve
```

`status` reads the local session and does not call Jira or GitHub. `assess` refreshes checks. `--accept-missing-checks` and `--accept-missing-analyzers` record that the reviewer accepts a gap in the reported checks.

Pass `--revise` to replace a stored human decision. A rerun without it keeps the earlier choice.

## Steps

1. **Jira.** `acli jira workitem view` and `acli jira workitem comment list`. The issue must be in **ready for peer review** or **in peer review** (see `status` in `.review-ticket.yaml`). Each status value is a string or, for the two review queue columns, a list of equivalent names. Returns use `status.in_progress`; approval uses `status.approved` (often a QA handoff column, not Done). Legacy top-level `peer_review_status`, `in_progress_status`, and `approved_status` keys still work. Testing notes are taken from a testing-notes field, a Testing Notes section, or a comment. Empty notes recommend In Progress. Adequacy of notes that exist is the reviewer's decision.
2. **Pull request and checks.** Open pull requests are discovered from issue text, then `github_repo`, `github_org`, or `github_user` as configured, else global search. The head SHA, base SHA, draft state, and required checks are stored for that SHA. Pending required checks stop as `WAITING`. Failed required checks recommend In Progress. A check service that cannot be read is `BLOCKED`.
3. **Bugbot and CodeQL.** Unresolved bot threads and open CodeQL alerts need a developer fix, explanation, false-positive note, or other disposition. An unaddressed finding recommends In Progress. A resolved thread is not treated as proof the code is correct. The reviewer acknowledges dispositions before continuing, or overrides them with a note.
4. **Checkout and reviewer.** The SHA is fetched into `commits/<sha>/checkout` with `git worktree add --detach`. The reviewer context includes the Jira text, testing notes, full pull request diff, standards, analyzer dispositions, and findings from earlier SHAs. Re-review is not limited to the delta since the previous SHA.
5. **Human review and publication.** Accept, reject, reclassify, edit, or add findings. Publish with `--yes`. Inline comments are sent only for lines present in the diff. Everything else stays in the review summary. A suggestion fence is added only when the replacement text is valid for GitHub. The live head SHA must still match the snapshot. The same payload is not posted twice. Requesting changes recommends In Progress and still requires a separate transition command.
6. **Virtualization.** `test prepare` writes `testing/profile/profile.json` and `docker-compose.yml`. Preparing again reuses that profile when the issue, pull request, branch, image, and ports match, and it does not stop other Docker projects. `test fetch` records the image digest. `test launch` refuses to start until this SHA has a fetched digest, so an old profile cannot silently test an old image.
7. **Functional testing.** Record pass, an implementation failure, or an environment block. Evidence files are copied under `testing/evidence/`. `pr comment` and `test comment` publish Markdown through `gh pr comment --body-file ... --attach ...`. `bug` writes a defect draft and, when `bug_writer_command` is set, runs it only after `--yes`.
8. **Disposition.** The checklist compares the SHA, checks, analyzer dispositions, must-fix findings, human review, test result, and image digest. `disposition` records the choice locally. Advancing or returning the issue is `jira transition`.

Jira comments, Jira transitions, pull request comments, and GitHub reviews are shared commands. Each one previews the action, requires `--yes` (or an interactive confirmation), writes a receipt, and skips a retry that would repeat the same successful call. A failed transition does not publish the GitHub review again.

## Reviewer output

The reviewer command must write `{output}` as JSON, or print that JSON. Context files are under `review/context/`, including `prompt.md`.

```json
{
  "summary": "Quantity is not validated on every path.",
  "approval_recommendation": "request_changes",
  "findings": [
    {
      "id": "F001",
      "priority": "high",
      "must_fix": true,
      "path": "src/Example.cs",
      "line": 142,
      "side": "RIGHT",
      "title": "Missing validation",
      "explanation": "This path permits an invalid state.",
      "suggested_change": "if (item.Quantity < 0) throw new InvalidOperationException();",
      "reconciles": "F001",
      "reconciliation_status": "partially_resolved"
    }
  ]
}
```

`priority` is `high`, `medium`, or `low`. `side` is `RIGHT` or `LEFT`. Leave `path` or `line` empty for a finding that is not on the diff. `reconciliation_status` is `resolved`, `still_present`, `partially_resolved`, `no_longer_applicable`, or `requires_additional_verification`. Findings from an earlier SHA that the reviewer does not mention stay `requires_additional_verification`.

Previous human decisions and test results are not reused as evidence for a new SHA.

## Artifacts

```text
reviews/
  DOTNETIOT-1234/
    issue.json
    issue-report.md
    reviewer-notes.md
    session.json
    actions.jsonl
    prs/
      acme-widgets-pr-87/
        pr.json
        commits/
          <sha>/
            snapshot.json
            readiness.md
            github-checks.json
            bugbot-findings.json
            codeql-findings.json
            actions.jsonl
            review/
            testing/
```

`reviews/` is gitignored. It holds issue text, check output, and local screenshots, so it should stay on the reviewer's machine.

Session state is a small manifest (`issue`, `active_pr`, `active_sha`, `current_step`, `outcome`, `last_completed_step`). Decisions are stored beside it and are not replaced unless the underlying notes changed or `--revise` is passed. Files are replaced atomically. An interrupted run keeps the previous file.

## Tests

The critical branches use scripted `acli`, `gh`, `git`, and `docker` responses. One test uses a real local git worktree.

```bash
python -m pip install -e '.[dev]'
python -m pytest
```
