# Review Pilot inline reviewer

Unpacked Manifest V3 extension for Microsoft Edge and Google Chrome. It reads a review-ticket deep link on a GitHub pull request **Files changed** page (`/changes`, or `/files` if GitHub redirected there) and shows the snapshot from the local bridge. When the SHA gate passes, Prepare can stage comments into GitHub’s pending review. It does not submit a review.

Load the directory that contains `manifest.json`: `extensions/inline-reviewer`.

## Side-load in Microsoft Edge

1. Open `edge://extensions`.
2. Turn on **Developer mode**.
3. Choose **Load unpacked**.
4. Select `extensions/inline-reviewer`.
5. Pin **Review Pilot Inline Reviewer** and click its toolbar button to open the side panel.

## Side-load in Google Chrome

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Choose **Load unpacked**.
4. Select the same `extensions/inline-reviewer` directory.
5. Pin the extension and click its toolbar button to open the side panel.

There is no store listing. Edge and Chrome use this one unpacked directory.

## Bridge secret

Set `REVIEW_PILOT_BRIDGE_TOKEN` on the **review-ticket process** that serves snapshots. Do not put the secret in a GitHub URL, a page script, or the pull request DOM.

One process serves every automated review on disk. It does not take a Jira issue, and `review-ticket ISSUE serve-inline-review` is not a command.

PowerShell, from the directory that contains `.review-ticket.yaml` (or the directory whose `reviews` folder you want to scan):

```powershell
$env:REVIEW_PILOT_BRIDGE_TOKEN = "replace-with-a-long-random-secret"
review-ticket serve-inline-review
```

bash:

```bash
export REVIEW_PILOT_BRIDGE_TOKEN="replace-with-a-long-random-secret"
review-ticket serve-inline-review
```

The process prints `http://127.0.0.1:8765/snapshot` and the reviews directory it is scanning. `--port` must match the port in Settings.

Enter that same secret in the side panel’s masked **Bridge shared secret** field. The service worker is the only caller. It sends `Authorization: Bearer` to `http://127.0.0.1`.

## Where reviews are read

`serve-inline-review` uses the same `reviews_dir` as every other review-ticket command.

- Set `reviews_dir` in `.review-ticket.yaml` (a relative path is resolved from the working directory where you started the command).
- `REVIEW_TICKET_REVIEWS_DIR` overrides the file.
- When neither is set, the relay looks in a `reviews` directory next to that working directory. Starting the command in `c:\repos\burtlo\review-pilot` scans `c:\repos\burtlo\review-pilot\reviews`.

Each request looks up `owner`, `repo`, and pull request `number` under every issue folder in that directory. A deep link can also send `issue` and `sha`. When more than one stored review matches, the relay serves the newest (`findings.json`, or `reviewer-report.md` when that file is newer) and the panel warns that other candidates exist. Open the ticket’s Files changed link to pin the issue and SHA.

## Allowlist

One `owner/repo` pattern per line. Matching is case-insensitive. `*` matches inside a single path segment and does not cross `/`.

- `kwik-trip-iot/*` matches one repository under that owner.
- `*/*` matches any owner and repository.
- An empty allowlist matches nothing. The panel stays idle and does not call the bridge.

A repository that is not listed shows idle copy and does not send the secret.

## Deep link

review-ticket opens `https://github.com/{owner}/{repo}/pull/{n}/changes` with query parameters `review_pilot_issue` and `review_pilot_sha`. The content script reads them at document start, before GitHub removes unknown query parameters from the address bar. The pull request number comes from the URL path. There is no finding-id parameter.

On an allowlisted repository the panel requests a snapshot even when GitHub has already dropped `review_pilot_sha` from the address bar. After the snapshot loads, the panel shows the issue, PR, reviewed SHA, and finding list. When `candidate_count` is greater than one, a warning under that summary names the issue and short SHA being shown.

## SHA and range gate

The side panel and the service worker look across normal browser windows for a pull request **Changes** or **Files** tab. Reload snapshot reads that page directly, including when the side panel is open in another window.

GitHub’s page console cannot call `chrome.runtime`. Those APIs exist only inside the extension. After this extension is updated, open `chrome://extensions` or `edge://extensions`, click **Reload** on Review Pilot, and accept the scripting permission. Then hard-refresh the pull request tab.

Prepare stays off until the open Files changed view is the reviewed snapshot. After the file list and the commit control appear, the extension reads the commit-control label, the **Hide whitespace** check state, and the full head SHA from the `head-commit-link` selector (`href` or `data-commit`). All three must hold: the label is **All commits**, **Hide whitespace** is off, and that full SHA equals the reviewed SHA. Anything else blocks prepare, including **Changes since your last review**, a single commit, **Changes from all commits**, a 7-character id, and a missing head link. The panel shows the expected SHA, the observed range, and the observed head, or that the full head SHA was not found. The extension does not toggle whitespace or unified/split.

When the gate passes, **Prepare** on a finding writes that snapshot body into the line composer, or into the **Finish your review** summary for an off-diff finding, and leaves the composer open. **Prepare all** stages each on-diff comment with **Start a review**, waits until it is pending, then writes the off-diff summary once. It never clicks **Comment**, never clicks **Submit review** inside the dialog, never changes the review event, and does not mark a file **Viewed**.

## Updating selector defaults

GitHub changes the Files changed markup without notice. `selectors.json` is the packaged default for every named control (`line-number`, `add-comment-button`, `markdown-textarea`, `stage-review-button`, and the rest). The side panel can override one entry at a time. A stored override wins over the file until you clear it, so a bad experiment cannot leave Prepare stuck.

1. Open the pull request **Files changed** page and this side panel.
2. Enter the file path and line, and a start line when the comment is a range. **Probe** highlights the row, the range, and **+**. It does not paste. If the row cannot be resolved, the log records a structured failure: the file is collapsed, the line is off-screen, or the hunk is not loaded.
3. Read the activity log. Each debug line has a timestamp, the selector id, how many nodes matched, and a short snippet of the element (truncated outer HTML, or its accessible name). **Copy debug bundle** copies that log.
4. When a control has moved, choose its registry entry and **Pick element**. The next click on the page stores a CSS or data-attribute query for that entry in `chrome.storage`. The next lookup uses the override.
5. **Dry-run** uses the same navigation as Prepare through the open composer and stops before the textarea write. The textarea stays empty. Per-finding **Dry-run** does this for that snapshot finding. The debug **Dry-run** uses the path and line you entered.
6. **Clear selector overrides** deletes the stored JSON and the packaged defaults apply again.
7. When a query is right, copy it into `selectors.json`, reload the unpacked extension, and clear the stored override so the file is the source of truth.

## Local checks

From this directory, with Node.js 20 or newer:

```bash
node --test
```

No install step. The tests do not contact `github.com`.

The Python bridge is checked with pytest, for example:

```bash
pytest tests/test_inline_review.py
```

That suite must not be pointed at live GitHub either.
