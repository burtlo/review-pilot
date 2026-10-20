# review-ticket

A manual peer-review workflow. Give it a Jira issue id and it walks the readiness checks, keeps one artifact directory per commit, and stops whenever a person has to decide. It does not transition Jira or publish to GitHub unless that command is explicitly authorized.

The workflow shells out to the tools the team already runs and leaves their behavior alone. Headless reviewer skills and agents for `run-review` live under `.cursor/` in this repo; bug writer and virtualization remain external commands.

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

Leave `reviewer_command` unset until you are ready to run the in-repo headless adapter. Do not point it at a placeholder binary on PATH. Until it is set, `run-review` writes the context bundle and stops at the `import-review` handoff.

### Configure and run (headless reviewer)

This repository ships a **reviewer adapter** under `scripts/` that invokes a Cursor agent headlessly (via `cursor-sdk`) and writes schema-valid JSON to `{output}` for `run-review`.

**Prerequisites:** Python 3.11+, `python -m pip install cursor-sdk`, and `CURSOR_API_KEY` (PowerShell: `$env:CURSOR_API_KEY`; see [Cursor SDK auth](https://cursor.com/docs/sdk/python)). On **native Windows**, the adapter uses the SDK’s **async** bridge launcher (the sync `Agent.prompt` path fails with `WinError 10038` until cursor-sdk fixes pipe discovery). Override with `REVIEW_TICKET_REVIEWER_ASYNC=0|1`. Optional: attach to a running bridge via `CURSOR_SDK_BRIDGE_URL` and `CURSOR_SDK_BRIDGE_TOKEN`. Headless runs use the same **peer-review** stack as the IDE: `.cursor/skills/peer-review`, `.cursor/skills/peer-review-ui-admin`, and agents `reviewer` / `ui-admin-reviewer` under `.cursor/agents/`.

**1. Set `reviewer_command`** (from the review-pilot repo root; paths below are examples):

```yaml
reviewer_command: >
  python scripts/review_ticket_reviewer.py
  --context {context} --output {output} --checkout {checkout}
  --repository {repository} --sha {sha} --issue {issue} --agent {agent}
```

Windows PowerShell alternative:

```yaml
reviewer_command: >
  powershell -NoProfile -ExecutionPolicy Bypass
  -File scripts/review-ticket-reviewer.ps1
  -Context {context} -Output {output} -Checkout {checkout}
  -Repository {repository} -Sha {sha} -Issue {issue} -Agent {agent}
```

`REVIEWER_COMMAND` overrides the file. Placeholders match [Reviewer output](#reviewer-output): `{context}`, `{output}`, `{checkout}`, `{repository}`, `{sha}`, `{issue}`, and `{agent}` (defaults to `reviewer`).

**2. Optional per-repo agent** (`reviewer_by_repository`):

```yaml
reviewer_by_repository:
  kwik-trip-iot/KT.IoT.UI.Admin:
    agent: ui-admin-reviewer
```

**3. Run** (after gates are `READY`):

```bash
review-ticket DOTNETIOT-2550 run-review
```

On success, `reviews/.../review/findings.json` exists and the next step is human triage (`review-ticket <issue> attach` with a TTY, or `review apply` / `review apply --file` on disk). The same directory also gets **`reviewer-report.md`** (automated narrative) and **`review-preview.md`** (per-finding triage status plus inline vs summary-only publish counts). For a no-Cursor smoke test, set `REVIEW_TICKET_REVIEWER_STUB=1` or point `reviewer_command` at `scripts/review-ticket-reviewer-stub.py` (used in pytest).

To debug Cursor SDK / proxy issues outside review-ticket, run `python scripts/cursor_sdk_smoke.py` from the repo root (see `--help`; use `--skip-agent` to test HTTPS and bridge only).

**ZScaler (corporate TLS inspection):** Place your org root CA at **`certs/zscaler-root.cer`** (or `.pem` / `.crt`) in this repo — it is **gitignored** by default. review-ticket picks it up automatically and sets `NODE_EXTRA_CA_CERTS` (cursor-sdk-bridge) and `SSL_CERT_FILE` for Python. Override with `ZSCALER_CERT_PATH` if needed. Verify with `python scripts/cursor_sdk_smoke.py` from this repo root. Virtualization **Docker** images still need the CA baked or mounted separately (see `KT.IoT.Debug.CLI` docker pattern).

## Install

Python 3.11 or newer. For a live review you also need `acli` signed in to Jira, `gh` 2.99 or newer (the `--attach` flag), `git`, and Docker when you reach local testing.

Run install **from the review-pilot repo root** (`C:\repos\burtlo\review-pilot`), not other projects such as `KT.IoT.Debug.CLI` (that repo has no `pyproject.toml`).

**PowerShell (recommended):**

```powershell
cd C:\repos\burtlo\review-pilot
.\scripts\install-dev.ps1
```

**Manual:**

```powershell
cd C:\repos\burtlo\review-pilot
python -m pip install -e ".[dev,reviewer]"
```

`reviewer` pulls in `cursor-sdk` for headless `run-review`. Then:

```bash
review-ticket DOTNETIOT-1234
```

Without an install, run `python bin/review-ticket` (or `python -m review_ticket`) from the review-pilot repository root.

## Configuration

`.review-ticket.yaml` (or `.review-ticket.yml`) in the working directory is optional. Legacy `.review-ticket.json` is still read if no YAML file exists.

Stored tickets and reviews live under `reviews_dir`. When that key is omitted, review-ticket uses a `reviews` directory in the working directory where the command was started. `review-ticket serve-inline-review` scans that same directory for every issue; it does not take an issue argument.

```yaml
# Where tickets and reviews are stored. Default: ./reviews in the working directory.
# reviews_dir: reviews

# Single repo, or use github_org / github_user instead (see below).
github_repo: acme/widgets
# github_org: acme
# jira_site: https://your-org.atlassian.net  # optional; browse links when acli has no url

status:
  in_progress: In Progress
  ready_for_peer_review: Ready for Peer Review
  in_peer_review: Peer Review
  approved: Ready for QA

# optional: extra required check names beyond what GitHub marks on the PR
# required_checks:
#   - build
analyzer_checks:
  - Bugbot
  - CodeQL
require_analyzers: true

standards:
  - docs/standards.md
image: ghcr.io/acme/widgets:feature
ports:
  - "8080:8080"

# reviewer_command: >
#   python scripts/review_ticket_reviewer.py
#   --context {context} --output {output} --checkout {checkout}
#   --repository {repository} --sha {sha} --issue {issue} --agent {agent}
# reviewer_by_repository:
#   kwik-trip-iot/KT.IoT.UI.Admin:
#     agent: ui-admin-reviewer
bug_writer_command: "bug-writer {draft}"
```

Pull request discovery (in order): PR URLs in the Jira issue text; then `github_repo` (`owner/repo`) for a single repository; else `github_org` for `gh search prs` with an `org:` qualifier across that organization’s repos; else `github_user` for a personal account (`user:` qualifier); else global `gh search prs` on the issue key. Set only one of `github_org` and `github_user`. You can also run `review-ticket ISSUE pr select owner/repo#number`.

When several open pull requests reference the issue, every discovered PR is tracked automatically on each run. Readiness and analyzer gates run for each; the workflow stops on the worst outcome. To review only one repository, run `review-ticket ISSUE pr select owner/repo#number` (that sets single-PR scope until you run `pr select-all` again). Per-PR artifacts stay under `reviews/ISSUE/prs/...`; combined summaries are written to `reviews/ISSUE/readiness.md` and `analyzers.md` when more than one PR is tracked. Code review and publication still run against the primary PR (`active_pr`, the first tracked ref) unless you switch with `pr select`.

Readiness uses `gh pr checks --required` on each tracked pull request. Every check returned for the PR is listed in the report; only GitHub-required checks block the workflow (pending, failed, or absent from the run). Optional `required_checks` in the file adds names on top of GitHub’s list. `require_analyzers` defaults to true. An entry in `analyzer_checks` is enforced only when a **required** check on that PR matches that name (for example CodeQL). Bugbot triage still happens in the analyzer step from review threads, not from check names. Set `require_analyzers` to false when a repo does not use those tools.

`REVIEWER_COMMAND`, `BUG_WRITER_COMMAND`, `REVIEW_TICKET_REVIEWS_DIR`, and `REVIEW_TICKET_LOG_LEVEL` override the file. Set `log_level` to `info` or `debug` in `.review-ticket.yaml` for progress lines on stderr during long steps (`run-review`, checkout, headless reviewer). An empty or unset `reviewer_command` (and no `REVIEWER_COMMAND`) is the supported default: `run-review` prepares context and prints the `import-review` next step instead of executing a reviewer.

### Checkout command (optional)

By default, `run-review` clones into the tool cache and adds a detached worktree at `reviews/<issue>/prs/.../commits/<sha>/checkout`. On Windows, deep monorepos can fail that step with **Filename too long** because artifact paths are long even when the git object store is fine.

Set `checkout_command` to a shell one-liner (or script invocation) that prepares `{dest}` using your org layout—typically existing clones under `C:\repos\...`—instead of the built-in `gh repo clone` + worktree path. After your command runs, review-ticket verifies `git rev-parse HEAD` in `{dest}` matches `{sha}`.

| Placeholder | Meaning |
| --- | --- |
| `{owner}` | GitHub owner |
| `{repo}` | Repository name |
| `{sha}` | Reviewed commit |
| `{dest}` | Artifact checkout directory for this SHA |
| `{repository}` | `owner/repo` |

If the string contains no `{...}` tokens, `{repository}`, `{sha}`, and `{dest}` are appended as extra arguments (legacy).

Example for a multi-PR kwik-trip-iot issue (paths are placeholders; see the [checkout operator guide](docs/plans/multi-pr-reviewer-integration/checkout-operator.md)):

```yaml
github_org: kwik-trip-iot

# checkout_command: >
#   powershell -NoProfile -ExecutionPolicy Bypass
#   -File C:\repos\burtlo\review-pilot\scripts\<CHECKOUT_SCRIPT>.ps1
#   {owner} {repo} {sha} {dest}
```

Tracked repos for DOTNETIOT-2550-style triples usually map to `C:\repos\kwik-trip-iot\KT.IoT.Zuul`, `KT.IoT`, and `KT.IoT.UI.Admin`. Switch PRs with `pr select`; each `run-review` uses the active PR’s SHA. For the full **Zuul#156 → KT.IoT#144 → UI.Admin#354** checklist (`run-review` → `attach` → `publish-review` per PR), see the [multi-PR operator guide](docs/plans/multi-pr-reviewer-integration/operator-guide.md).

Set `cache_steps: true` to skip re-fetching Jira, pull request sync, checks, and analyzer threads when the tracked pull request SHAs are unchanged since the last successful pass. Pass `--refresh` on any command to force a full refresh (for example `review-ticket ISSUE --refresh` or `review-ticket ISSUE analyzers --accept-dispositions --refresh`).

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
review-ticket DOTNETIOT-1234 attach
review-ticket DOTNETIOT-1234 review apply --accept-all --event REQUEST_CHANGES
review-ticket DOTNETIOT-1234 review apply --file human-review.json
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

1. **Jira.** `acli jira workitem view` and `acli jira workitem comment list`. The issue must be in **ready for peer review** or **in peer review** (see `status` in `.review-ticket.yaml`). Each status value is a string or, for the two review queue columns, a list of equivalent names. Returns use `status.in_progress`; approval uses `status.approved` (often a QA handoff column, not Done). Legacy top-level `peer_review_status`, `in_progress_status`, and `approved_status` keys still work. Testing notes are taken from a testing-notes field, a Testing Notes section, or a comment. Empty notes recommend In Progress. Adequacy of notes that exist is the reviewer's decision. With a TTY, **`review-ticket <issue> attach`** opens the testing-notes gate: refresh the ticket, accept or reject, and on reject edit the return body, authorize the Jira comment, and authorize the transition back to In Progress in one session. Without a TTY, use `notes --reject`, then `jira comment --body-file return-comment.md --yes`, then `jira transition --status "In Progress" --yes`.
2. **Pull request and checks.** Open pull requests are discovered from issue text, then `github_repo`, `github_org`, or `github_user` as configured, else global search. The head SHA, base SHA, draft state, and `gh pr checks` output are stored for that SHA. GitHub’s required checks on the PR gate readiness; other checks are shown for context. Pending required checks stop as `WAITING`. Failed required checks recommend In Progress. A check service that cannot be read is `BLOCKED`.
3. **Bugbot and CodeQL.** Unresolved bot threads and open CodeQL alerts need a developer fix, explanation, false-positive note, or other disposition. An unaddressed finding recommends In Progress. When the Jira issue is still in **ready for peer review**, the next command is a Jira transition back to In Progress (after authorization). A resolved thread is not treated as proof the code is correct. The reviewer acknowledges dispositions before continuing, or overrides them with a note.
4. **Checkout and reviewer.** The SHA is fetched into `commits/<sha>/checkout` with `git worktree add --detach`. The reviewer context includes the Jira text, testing notes, full pull request diff, standards, analyzer dispositions, and findings from earlier SHAs. Re-review is not limited to the delta since the previous SHA.
5. **Human review and publication.** Accept, reject, reclassify, edit, or add findings. Use **`review-ticket <issue> attach`** when you have a TTY, or triage on disk: read **`review-preview.md`** (updated again after `review apply`), edit **`human-review.json`**, then `review apply --file human-review.json`. Publish with `--yes`. Inline comments are sent only for lines present in the diff. Everything else stays in the review summary. A suggestion fence is added only when the replacement text is valid for GitHub. The live head SHA must still match the snapshot. The same payload is not posted twice. Requesting changes recommends In Progress and still requires a separate transition command.
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
