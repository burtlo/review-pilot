# Inline reviewer browser overlay — implementation map

Status: **ready for orchestration** — companion to [spec.md](spec.md). Canonical map for implementer assignment and verifier checklists. Refresh with `/spec-implementation-map @spec.md` after material spec or code changes.

## Spec alignment

### Strengths (spec)

- D1–D15, AC 1–11, and the placement and preflight tables are closed enough to staff packages. Publish stays on `review-ticket` (D15). The extension never submits (D10).
- Deep-link names are fixed: `review_pilot_issue`, `review_pilot_sha`, PR identity from the URL. No finding id and no secret in the query.
- Inline versus summary uses the same rule as publish: `(path, line, side)` in the diff index, `render_finding_body` when inline, `_general_section` when not (D8).
- Revisit behavior is a status machine (`not_placed`, `draft`, `draft_modified`, `published`, `published_modified`, `blocked`) with four preflight outcomes. A second finding on the same line stays inline (D13).
- [github-files-changed.md](github-files-changed.md) records the controls automation must use and the ones it must not click.

### Strengths (repository)

- Automated findings and the diff index already live at `reviews/<issue>/prs/<slug>/commits/<sha>/review/findings.json` and `diff-lines.json`. [_stored_diff_index](../../../review_ticket/workflow.py) prefers `diff-lines.json` and falls back to `diff.patch` through [parse_unified_diff](../../../review_ticket/textutil.py).
- [render_finding_body](../../../review_ticket/findings.py), [suggestion_ok](../../../review_ticket/findings.py), and [_general_section](../../../review_ticket/findings.py) are the publish body builders. [build_review_payload](../../../review_ticket/findings.py) is the inline predicate: path and integer line, side in `{RIGHT, LEFT}`, and the tuple present in the index. A suggestion fence is added only when `_inline` is set. [test_inline_and_general_findings_are_split](../../../tests/test_policy_and_findings.py) locks that split.
- Reviewed SHAs are `session.json` `pr_shas`, keyed `owner/repo#number`. [pr_url_for_ref](../../../review_ticket/status_projection.py) and [_pr_url_for_ref](../../../review_ticket/workflow.py) already build `https://github.com/{owner}/{repo}/pull/{n}` for the status document and the CLI session render. Those are the only two call sites.
- The CLI is a single argparse tree in [cli.py](../../../review_ticket/cli.py) with entry point `review-ticket`. Tests are pytest, `pythonpath = ["."]`. There is no extension, no `manifest.json`, and no HTTP server.

### Gaps and clarifications before build

| Topic | Present state | Spec requirement | Suggested resolution |
|-------|---------------|------------------|----------------------|
| Bridge command | No serve command. `attach` owns the terminal until the TUI exits. | A localhost bridge runs while the operator uses the extension. The spec leaves the command name to this map. | Add `review-ticket <issue> serve-inline-review`. Bind `127.0.0.1` only, default port **8765**, `--port` to override. Do not start it inside `attach`. |
| Shared secret | No token store. | Masked extension setting. Sent only from the service worker to `127.0.0.1`. Absent from the URL and the page DOM. | Bridge reads `REVIEW_PILOT_BRIDGE_TOKEN` and refuses to listen if it is empty. Compare with `hmac.compare_digest`. Extension sends `Authorization: Bearer`. No token flag on argv. |
| Which links change | Status markdown and CLI `pr:` lines use the conversation URL. [test_tui_status.py](../../../tests/test_tui_status.py) and [test_status_projection.py](../../../tests/test_status_projection.py) assert `https://github.com/acme/widgets/pull/87`. `pr.json` `url` and Jira comment builders are separate. | Review-workflow links open `/changes` with `review_pilot_issue` and `review_pilot_sha`. | Change only [pr_url_for_ref](../../../review_ticket/status_projection.py) and the CLI render helper. Leave stored `pr.json` URLs and Jira bodies on the conversation URL. |
| Snapshot path wording | Files are `{reviews_dir}/{issue}/prs/{slug}/commits/{sha}/review/`. | Verification plan says `reviews/…/commits/<sha>/review/`. | Bridge resolves through [Store](../../../review_ticket/storage.py). Tests use the real layout. |
| Body source of truth | [build_review_payload](../../../review_ticket/findings.py) drops `decision == "reject"`, folds in the reviewer summary, and can substitute “Peer review notes.” [assemble_publication_findings](../../../review_ticket/findings.py) also applies human triage. | D5: every automated finding in `findings.json`. D8: inline body matches `render_finding_body`; off-diff prose matches `_general_section`. No triage filter. | New module calls the inline predicate and those two renderers on the full findings list. Do not call `build_review_payload` or `assemble_publication_findings` for this snapshot. |
| Marker text | No marker. | One visible line per finding, outside any suggestion fence, stable for the finding id, readable from rendered text. An HTML comment is optional and is not the scan key. | Visible line `review-pilot finding {id}`. Optional trailing HTML comment `<!-- review-pilot:finding:{id} -->`. Both appended by the Python module. |
| Rendered body compare | GitHub’s rendered comment DOM has no raw markdown and drops HTML comments ([github-files-changed.md](github-files-changed.md)). “Normalized whitespace” against the markdown source will not match `**title**`. | `draft` / `published` require the marker and a body match. | Bridge returns `body` (markdown the composer receives) and `scan_text` (plain projection: emphasis markers removed, HTML comments removed, suggestion fence kept as its inner lines, whitespace collapsed). Preflight matches the marker line plus `scan_text` against rendered text. Golden-test the projection in pytest. |
| Signed-in head SHA | Logged-out commit anchors expose `data-commit` and `/commits/{40-hex}`. Signed-in **All commits** options showed a 7-character id and no full SHA. | Full head SHA from the commit link or equivalent. A 7-character prefix is not a match. Mismatch or unknown head blocks prepare. | Selector `head-commit-link`. Read `href` or `data-commit`. If the full id is missing, status `blocked` and the log says the full head SHA was not found. Do not scan the page for the first 40-hex string. |
| Second stage control | Not observed. A note in the UI file mentions GitHub’s docs phrase “Add review comment”, which is also the visually hidden legend inside **Finish your review**. | **Prepare all** clicks **Start a review** or the probed later stage control. It never clicks **Comment**. | Registry entry `stage-review-button` matches accessible name **Start a review** only, until a pending-review fixture records another name. If the only control is **Comment**, stop and log. Do not click a control named **Add review comment**. |
| Pending-review DOM | No pending review was opened. Submitted threads are in the comments panel and have no textarea. | `draft` is a pending comment; `published` is a submitted comment. | `pending-review-comment` is a registry id with no default until a fixture exists. Marker in the comments panel and not in that region is `published`. Synthetic draft fixtures must be labeled unverified. |
| Summary after Cancel | Not observed. | If a revisit cannot see a persisted summary, status stays `not_placed`. | Scan may open **Finish your review** read-only and close with **Cancel**. Empty summary leaves off-diff findings `not_placed`. |
| Allowlist syntax | No matcher. | `*` matches within one path segment. Empty allowlist matches nothing. | Case-insensitive `owner/repo` globs. `kwik-trip-iot/*` matches one repo segment. `*/*` matches any owner and repo. `*` does not cross `/`. |
| JS tests and CI | No `package.json`, no Node toolchain, no GitHub Actions workflow. | Extension unit tests and HTML fixtures. CI must not hit live GitHub. | Pure functions in the extension run under `node --test` (Node 20+). Pytest covers the Python contract. Live GitHub stays manual. Document both commands in the extension README. |
| Logged-out path | `/changes` 302s to `/files` when logged out, then page scripts strip `review_pilot_*`. | Content script captures the query at document start. Act on `/changes`; also observe `/files` when that redirect is still in use. | `document_start` content script on both paths. Logged-out pages have no **Start a review**. The SHA gate stays blocked there. The captured query still has to survive for AC 1. |

### Acceptance criteria traceability

| AC | Present | Delta / work |
|----|---------|----------------|
| 1 | No extension. | **P3** — unpacked MV3, `document_start` capture, allowlist idle, no bridge call off-list. |
| 2 | Status and CLI links are conversation URLs. Findings are on disk, not served. | **P1** links, **P2** snapshot, **P3** panel fields. |
| 3 | Publish can build an inline body. Nothing selects a diff line or clicks **Start a review**. | **P2** body, **P5** marker, **P6** line composer and stage click. |
| 4 | No page gate. | **P4** — All commits, whitespace off, full head SHA. Fail closed. |
| 5 | No dialog automation. | **P6** — summary fill, **Cancel** to close, **Comment** radio left alone. |
| 6 | Off-diff text exists only inside the publish payload. | **P2** `on_diff: false` and summary block, **P5** sidebar copy, **P6** summary field only. |
| 7 | No scan. | **P5** classification on fixtures, **P6** honors `skip_match` and `manual_only`. |
| 8 | API publish emits one comment per inline finding. No DOM placement. | **P5** fixture with a comment already on the line, **P6** second composer. |
| 9 | No listener and no extension storage. | **P2** bind and bearer check, **P3** service-worker fetch. |
| 10 | No probe. | **P7**. |
| 11 | No package to side-load. | **P3** one unpacked directory. Manual Edge and Chrome smoke. |

---

## Repository layout

Python package `review_ticket`. Operator links are the status-document markdown URL and the CLI `pr:` line. Snapshot files are under the reviews directory from config. The extension is a new top-level tree so setuptools (`include = ["review_ticket*"]`) does not install it as a library module.

| Path | Role |
|------|------|
| [review_ticket/cli.py](../../../review_ticket/cli.py) | Subcommands. Add `serve-inline-review` here. |
| [review_ticket/status_projection.py](../../../review_ticket/status_projection.py) | `pr_url_for_ref` feeds the status screen. |
| [review_ticket/tui/status_format.py](../../../review_ticket/tui/status_format.py) | Markdown link `[owner/repo#n](url)`. |
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | CLI render via `_pr_url_for_ref`. Diff index helpers stay private; the bridge calls `parse_unified_diff` or reads `diff-lines.json` itself. |
| [review_ticket/findings.py](../../../review_ticket/findings.py) | `render_finding_body`, `suggestion_ok`, `_general_section`. |
| [review_ticket/textutil.py](../../../review_ticket/textutil.py) | `parse_unified_diff` → `(path, line, side)`. |
| [review_ticket/storage.py](../../../review_ticket/storage.py) | `issue_dir`, `pr_dir`, `commit_dir`. |
| [tests/test_policy_and_findings.py](../../../tests/test_policy_and_findings.py) | Inline versus general body fixture. |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | Exact conversation URL assertion to update. |
| [docs/plans/inline-reviewer-browser/github-files-changed.md](github-files-changed.md) | DOM notes for selectors. Not a requirement file. |

New paths this map assigns:

| Path | Role |
|------|------|
| `review_ticket/inline_review.py` | URL builder, marker, `scan_text`, snapshot document. |
| `extensions/inline-reviewer/` | MV3 extension: manifest, service worker, content script, side panel, selector registry, fixtures, `node --test`. |

---

## Workstreams mapped to decisions

### D1 — Separate bundle

**Present:** This directory has an approved spec and UI notes.

**Required:** Work stays in this bundle. No edits to `tui-review-flow` specs or to publish behavior.

| Resource | Role |
|----------|------|
| [spec.md](spec.md) | Normative |

**Risks:** None beyond keeping D15 out of every package.

### D2, D14 — Allowlist before any bridge call

**Present:** Content scripts do not exist. The sample repo in [.review-ticket.yaml](../../../.review-ticket.yaml) is `burtlo/review-pilot`. `kwik-trip-iot` appears only as a fixture URL in tests.

**Required:** The content script may load on `https://github.com/*`. The service worker calls `127.0.0.1` only after the page `owner/repo` matches the stored allowlist. An empty allowlist matches nothing.

| Resource | Role |
|----------|------|
| New `extensions/inline-reviewer/` | Settings and matcher |

**Risks:** A matcher that treats `*` as “any string” would call the bridge for `owner/repo/extra`. Segment globs only.

### D3, AC 11 — One unpacked build

**Present:** No manifest.

**Required:** One Manifest V3 directory, side-loaded on current Edge and Chrome. No store listing.

| Resource | Role |
|----------|------|
| `extensions/inline-reviewer/manifest.json` | `github.com` and `http://127.0.0.1/*` host permissions, side panel, `document_start` content script |

**Risks:** Manual smoke only. No CI browser matrix.

### D4, D10 — Pending review, human submits

**Present:** [publish_review](../../../review_ticket/workflow.py) posts via GitHub. The extension has no click path.

**Required:** **Prepare all** stages with **Start a review**. Per-finding prepare leaves the composer open. Nothing clicks composer **Comment**, dialog **Submit review**, or Ctrl+Enter, and nothing changes `reviewEvent`.

| Resource | Role |
|----------|------|
| [github-files-changed.md](github-files-changed.md) | Composer and dialog labels |

**Risks:** The second-comment stage name is unprobed. Fail closed until a fixture names it.

### D5, D8 — All findings, publish wording

**Present:** `findings.json` stores every normalized finding. Publish filters with human decisions.

**Required:** The snapshot lists every finding. Inline bodies match `render_finding_body`. Off-diff text matches `_general_section`, with a marker on each finding’s segment.

| Resource | Role |
|----------|------|
| [review_ticket/findings.py](../../../review_ticket/findings.py) | Renderers to call |
| [review_ticket/inline_review.py](../../../review_ticket/inline_review.py) | New snapshot builder |

**Risks:** Reusing `build_review_payload` would drop rejected findings and mix the reviewer summary into **Finish your review**.

### D6, AC 4 — SHA gate

**Present:** Publish compares live HEAD to the stored SHA on the server side. The Files changed page is not checked.

**Required:** Prepare runs only when the commit control is **All commits**, **Hide whitespace** is off, and the full head SHA equals the reviewed SHA. Otherwise no line, **+**, or insert runs. The panel shows expected SHA, observed range, and observed head.

| Resource | Role |
|----------|------|
| [github-files-changed.md](github-files-changed.md) | Signed-in menu has no full SHA in the observed session |

**Risks:** Fail closed when the full id cannot be read. A prefix compare would prepare against the wrong commit.

### D7 — Per finding and Prepare all

**Present:** No panel actions.

**Required:** Per-finding prepare fills one composer and stops. **Prepare all** stages each on-diff finding, waits until it shows as pending, then writes the off-diff block once.

| Resource | Role |
|----------|------|
| Side panel | The two actions |

**Risks:** An unstaged composer is lost when the next line opens. **Prepare all** must stage before advancing.

### D9, AC 9 — Localhost bridge

**Present:** No HTTP listener. Reviews stay on disk.

**Required:** Service worker fetches the snapshot. Page scripts never see the token. Non-local origins get no snapshot.

| Resource | Role |
|----------|------|
| `review_ticket/inline_review.py` | `GET /snapshot` |
| [review_ticket/storage.py](../../../review_ticket/storage.py) | Path resolution |

**Risks:** Binding `0.0.0.0` or reflecting `Access-Control-Allow-Origin: *` would expose snapshots beyond the extension.

### D11, D13 — Marker and two comments on one line

**Present:** No marker. Publish already emits two API comments when two findings share a line and both are on the diff.

**Required:** Each finding gets its own inline comment. Preflight keys off that finding’s marker. Another comment on the line does not move this finding to the summary and is not edited.

| Resource | Role |
|----------|------|
| Placement module in the extension | Preflight outcomes |

**Risks:** Treating “any comment on this line” as `skip_match` would drop the second finding.

### D12, AC 10 — Selector registry and debug modes

**Present:** UI notes name accessible names and a few attributes (`data-diff-side`, `data-line-number`, `data-line-anchor`). They are not a registry.

**Required:** Packaged defaults, `chrome.storage` JSON overrides, probe, picker, dry-run, structured log, copy debug bundle.

| Resource | Role |
|----------|------|
| `extensions/inline-reviewer/selectors.json` | Defaults |
| [github-files-changed.md](github-files-changed.md) | Seed for names |

**Risks:** Defaults will drift when GitHub ships UI changes. Overrides and probe are the maintenance path. CI cannot prove them against production DOM.

### D15 — Publish unchanged

**Present:** `publish-review` posts the GitHub review API payload.

**Required:** This bundle does not teach publish to refuse a marker already on the PR.

| Resource | Role |
|----------|------|
| [review_ticket/workflow.py](../../../review_ticket/workflow.py) | Leave `publish_review` as it is |

**Risks:** The same finding can be prepared in the browser and later published by the CLI. Accepted until a later change.

---

## Orchestration packages

| ID | Title | Surfaces | Depends on | Primary paths | Verify (AC / tests) |
|----|-------|----------|------------|---------------|---------------------|
| P1 | Files changed deep links | code, cli-ui | — | `review_ticket/inline_review.py`, `status_projection.py`, `workflow.py` | AC 2 link half; `tests/test_inline_review.py`, `tests/test_tui_status.py`, `tests/test_status_projection.py` |
| P2 | Snapshot bridge | code, cli | P1 | `review_ticket/inline_review.py`, `review_ticket/cli.py` | AC 2 data, AC 9 server half; pytest snapshot and auth |
| P3 | Extension shell | host-ui, config, docs | P2 | `extensions/inline-reviewer/` | AC 1, AC 9 client half, AC 11; `node --test` allowlist and query capture |
| P4 | SHA and range gate | host-ui | P3 | content script, `selectors.json` | AC 4; fixture HTML for the commit control; fail-closed unit |
| P5 | Marker, scan text, preflight | code, host-ui | P2, P3 | `inline_review.py`, extension placement module, HTML fixtures | AC 6 list copy, AC 7, AC 8 classification |
| P6 | Prepare on the diff and in the summary | host-ui | P4, P5 | content script prepare actions | AC 3, AC 5, AC 6 placement, AC 8; manual smoke |
| P7 | Probe, picker, dry-run, debug bundle | host-ui, docs | P3, P6 | panel debug tools, selector overrides | AC 10; manual probe and dry-run |

### Package briefs (for implementer agents)

#### P1 — Files changed deep links

- **Goal:** The status document and the CLI session render open Files changed with the reviewed issue and SHA.
- **Deliverables:** `files_changed_url(owner, repo, number, issue, sha)` producing `https://github.com/{owner}/{repo}/pull/{n}/changes?review_pilot_issue=…&review_pilot_sha=…`. Status rows and CLI `pr:` lines use it when a full SHA is stored. Missing SHA keeps today’s conversation URL. Update the two exact URL assertions.
- **Out of scope:** Bridge, extension, `pr.json`, Jira comments, publish.
- **Touchpoints:** [status_projection.py](../../../review_ticket/status_projection.py) `pr_url_for_ref`; [workflow.py](../../../review_ticket/workflow.py) `_pr_url_for_ref` / `_render`; [status_format.py](../../../review_ticket/tui/status_format.py) already prints `row.url`.

#### P2 — Snapshot bridge

- **Goal:** A loopback HTTP server returns one PR snapshot for the extension.
- **Deliverables:** `review-ticket <issue> serve-inline-review` with optional `--pr owner/repo#n` (default active PR) and `--sha` (default `pr_shas` for that PR). `GET /snapshot?owner&repo&number&sha` on `127.0.0.1`. Bearer token required. JSON includes issue, PR, reviewed SHA, and every finding: id, title, path, line, start_line, side, `on_diff`, `body`, `scan_text`. One `summary_block` from `_general_section` of the off-diff findings, each segment carrying that finding’s marker. `on_diff` follows the publish tuple check, including `start_line` only when that line is in the index too. 404 when the review directory is missing. Reject non-loopback binds. No `Access-Control-Allow-Origin: *`.
- **Out of scope:** Filtering by `human-review.json`. Calling `build_review_payload`. Any GitHub traffic. Extension UI.
- **Touchpoints:** [findings.py](../../../review_ticket/findings.py), [textutil.py](../../../review_ticket/textutil.py), [storage.py](../../../review_ticket/storage.py), [cli.py](../../../review_ticket/cli.py).

#### P3 — Extension shell

- **Goal:** One unpacked extension that captures the deep link, stays idle off the allowlist, and shows snapshot fields.
- **Deliverables:** Manifest V3 side panel. Settings: masked secret, allowlist textarea, optional port (default 8765). Content script at `document_start` on `/pull/*/changes` and `/pull/*/files` stores `review_pilot_issue` and `review_pilot_sha` before GitHub strips them. Service worker calls the bridge only for an allowlisted `owner/repo`. Panel shows issue, PR, reviewed SHA, and the finding list once the snapshot loads. Idle copy when the repo is not allowlisted, and no request in that case. README with side-load steps for Edge and Chrome and the token env var.
- **Out of scope:** Clicking GitHub. SHA gate. Preflight. Probe.
- **Touchpoints:** New `extensions/inline-reviewer/`. Contract from P2.

#### P4 — SHA and range gate

- **Goal:** Prepare stays disabled unless the open Files changed view is the reviewed snapshot.
- **Deliverables:** After the file list and the commit control hydrate (bounded wait; timeout is `blocked`), read the commit control label, the **Hide whitespace** check state, and the full head SHA from `head-commit-link`. Pass only for label **All commits**, whitespace off, and exact full-SHA match. Panel shows expected SHA, observed range, and observed head. Log the result. Prepare actions no-op while the gate is blocked. Do not toggle whitespace or unified/split.
- **Out of scope:** Opening composers. Treating **Changes from all commits** (logged-out label) as a pass.
- **Touchpoints:** `selectors.json`, content script, panel.

#### P5 — Marker, scan text, preflight

- **Goal:** Each finding has one placement status from a read-only DOM scan, and prepare decisions follow the preflight table.
- **Deliverables:** Python marker and `scan_text` covered by golden tests. Extension module: allowlist already done in P3; here, marker parse, whitespace-collapsed compare, and outcome `fill` / `replace_draft` / `skip_match` / `manual_only`. HTML fixtures for a submitted comment with the marker, a synthetic pending comment, a second finding on a line that already has a different comment, and a summary segment. Sidebar columns: id, title, path:line, inline versus not-on-diff, status. **Refresh scan** reruns the read-only pass. **Replace modified drafts** is a panel toggle; otherwise `replace_draft` needs a per-finding confirm.
- **Out of scope:** Clicking **+** or **Start a review**. Changing publish.
- **Touchpoints:** `review_ticket/inline_review.py`, `extensions/inline-reviewer` placement module and fixtures.

#### P6 — Prepare on the diff and in the summary

- **Goal:** When the gate passes, prepare writes snapshot bodies into GitHub’s pending review and never submits.
- **Deliverables:** On-diff **fill** / **replace_draft**: expand a collapsed file, clear a hiding file filter, expand the hunk, scroll until the row mounts, select `data-diff-side` and `data-line-number` (LEFT → `left`, RIGHT → `right`), Shift-click when `start_line` differs, hover, activate **+**, set the **Markdown value** textarea, dispatch the input event that enables staging. Do not mark **Viewed**. Do not use the clipboard. Per-finding prepare stops with the composer open. **Prepare all** clicks `stage-review-button` and waits until that comment is pending before the next finding. Off-diff: open toolbar **Submit review**, edit only the summary textarea, leave `reviewEvent` on **Comment**, close with **Cancel**. **Prepare all** writes the marked summary block once; a later prepare replaces only the marked segment. If the row never mounts, status `blocked` and the panel mentions **Switch to single file mode**. If the stage control stays disabled, stop and log. Activity log records each preflight decision and DOM failure.
- **Out of scope:** Clicking composer **Comment**, dialog **Submit review**, **Abandon review**, **Discard review**, **Approve**, or **Request changes**. Editing a neighboring comment. `publish-review`.
- **Touchpoints:** Content script, selector registry, P5 outcomes, P4 gate.

#### P7 — Probe, picker, dry-run, debug bundle

- **Goal:** Maintainers can see which selector matched without pasting a review.
- **Deliverables:** Probe: operator enters path, line, optional start line; highlight row, range, and **+**, or log a structured failure (collapsed file, off-screen, hunk not loaded). Picker: click a page element and store a CSS or data-attribute query on the registry entry being edited. Dry-run: preflight plus navigation through an open composer, no paste. Log lines: timestamp, selector id, match count, truncated outerHTML or accessible name. **Copy debug bundle** copies that log. Overrides in `chrome.storage` win over packaged defaults. README section for updating defaults after a GitHub UI change.
- **Out of scope:** A separate desktop app. Live GitHub in CI.
- **Touchpoints:** Panel, content script, `selectors.json`. Dry-run reuses P6 navigation and stops before the textarea write.

### Verifier briefs

#### P1 — verification

- **Must prove:** A stored SHA produces a `/changes` URL whose query is exactly `review_pilot_issue` and `review_pilot_sha`. The status markdown contains that URL once. A missing SHA stays a conversation URL. `pr.json` on disk is unchanged.
- **Commands / probes:** `pytest tests/test_inline_review.py tests/test_tui_status.py tests/test_status_projection.py`
- **Regression watch:** [test_acceptance.py](../../../tests/test_acceptance.py) still finds the bare PR URL as a substring. Jira comment fixtures must not grow `/changes`.

#### P2 — verification

- **Must prove:** With the token set, `/snapshot` returns every finding in `findings.json`, including a rejected one. An on-diff finding’s `body` contains the suggestion fence and the marker line outside the fence. An off-diff finding is absent from inline bodies and present in `summary_block`. Wrong token is rejected. A bind other than loopback is rejected. A second local process cannot read the body without the token.
- **Commands / probes:** `pytest` on the new bridge tests, using a tmp reviews tree shaped like `Store.commit_dir`.
- **Regression watch:** `tests/test_policy_and_findings.py` still describes publish filtering. This package must not change that behavior.

#### P3 — verification

- **Must prove:** Query params captured at document start remain available after a script deletes them from `location`. Allowlist cases: empty, `owner/*`, `*/*`, a non-matching repo. The non-matching case does not call fetch. The service worker is the only caller, and the request URL is `127.0.0.1` with the bearer header.
- **Commands / probes:** `node --test` in `extensions/inline-reviewer`. Manual: load unpacked on Edge and Chrome, open an allowlisted deep link, confirm the address bar loses `review_pilot_*` and the panel still shows them.
- **Regression watch:** None in the Python suite.

#### P4 — verification

- **Must prove:** Gate passes only for **All commits**, whitespace visible, and equal full SHAs. **Changes since your last review**, a single commit, hidden whitespace, a 7-character id, and a missing link all block. The blocked panel string includes expected SHA, observed range, and observed head (or an explicit “full head SHA not found”).
- **Commands / probes:** `node --test` with fixture snippets. No live GitHub.
- **Regression watch:** Prepare entry points from P6 stay unreachable when this flag is blocked.

#### P5 — verification

- **Must prove:** Matching rendered text yields `skip_match` for `draft` and `published`. A marker with different body yields `draft_modified` or `published_modified` / `manual_only`. A line that already has a comment without this finding’s marker is still `fill` for the second finding. Off-diff rows say they are not on the current diff. `scan_text` matches the Python golden file.
- **Commands / probes:** `pytest` golden file; `node --test` on fixtures under `extensions/inline-reviewer/fixtures/`.
- **Regression watch:** Publish payload tests still have no marker line.

#### P6 — verification

- **Must prove:** On a fixture, prepare targets `data-diff-side` and does not click a button whose accessible name is **Comment** or dialog **Submit review**, and does not set `reviewEvent` to `approve` or `request changes`. **Prepare all** invokes the stage control; per-finding prepare does not. Summary writes go to the **Finish your review** textarea. Two findings on one line produce two insert calls.
- **Commands / probes:** `node --test` with a stub DOM. Manual: one PR with an on-diff suggestion and one off-diff finding, matching SHA, **Prepare all**, then a human submit. Second visit shows `published` and does not duplicate. An edited draft shows `draft_modified` and waits for confirm.
- **Regression watch:** `publish-review` tests unchanged (D15).

#### P7 — verification

- **Must prove:** Probe reports a highlight or a structured failure without changing the textarea. Picker writes an override that the next lookup uses. Dry-run opens the composer path and leaves the textarea empty. Copied bundle includes selector id and match count.
- **Commands / probes:** `node --test` for override precedence. Manual probe, picker, and dry-run on a PR the operator can comment on.
- **Regression watch:** A bad override must be resettable from settings so P6 is not stuck on a maintainer experiment.

---

## Suggested implementation order

**Canonical package sequence:** P1 → P2 → P3 → P5 → P4 → P6 → P7

### Build order rationale

The extension needs a URL (P1) and a snapshot document (P2) before the panel can show findings (P3). Preflight (P5) is pure and should land before click automation so AC 7 and AC 8 are proven on saved HTML. The SHA gate (P4) has to sit in front of prepare (P6); the spec forbids line and insert actions when the range or head does not match. Probe and picker (P7) reuse the composer navigation from P6, so dry-run comes after prepare exists. P4 and P5 may be implemented in parallel after P3 if two people split the work; P6 still waits for both.

1. P1 — deep links, and lock the URL tests.
2. P2 — bridge and snapshot golden bodies.
3. P3 — unpacked extension, settings, allowlist, captured query.
4. P5 — marker, `scan_text`, preflight fixtures.
5. P4 — SHA gate, fail closed without a full head id.
6. P6 — composers, stage click, summary dialog.
7. P7 — probe, picker, dry-run, debug bundle.

---

## Test and fixture resources

| Asset | Use |
|-------|-----|
| [tests/test_policy_and_findings.py](../../../tests/test_policy_and_findings.py) | Existing inline versus general split. Do not weaken it. Add a sibling test that the snapshot keeps rejected findings and adds the marker outside the fence. |
| [tests/support.py](../../../tests/support.py) | `DIFF` sample and PR URL helpers. |
| [tests/test_tui_status.py](../../../tests/test_tui_status.py) | Update the one exact conversation URL. |
| [tests/test_status_projection.py](../../../tests/test_status_projection.py) | Update `PrStatusRow.url` expectation. |
| New HTML fixtures beside the extension | Submitted comment, synthetic pending comment, second finding on an occupied line, **Finish your review** summary. Label synthetic pending DOM as unverified against a live pending review. |
| [github-files-changed.md](github-files-changed.md) | Selector seed. Not a fixture. |

**CI:** This repo has no Actions workflow. Pytest is the local Python check. `node --test` is the local extension check. Neither may call `github.com`. AC 11 and the prepare smoke are manual on Windows, Edge and Chrome, signed in as a non-author so **Approve** and **Request changes** are enabled and must stay unclicked.

---

## Cross-cutting risks summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| Full head SHA missing on the signed-in commit menu | High | Fail closed. Do not prefix-match. Record a fixture when a signed-in menu item actually exposes 40 hex characters. |
| Stage control after the first comment is unknown, and “Add review comment” names a dialog legend | High | Click only **Start a review** until a pending-review fixture names the later control. |
| Rendered DOM is not the markdown source | High | Compare `scan_text` plus the visible marker line. Keep the HTML comment optional. |
| `build_review_payload` drops rejects | Medium | Dedicated snapshot builder. Verifier checks a rejected id is still listed. |
| Prepare and a later `publish-review` can double-post | Medium | Accepted by D15. Do not sneak a publish guard into this bundle. |
| Token in the page or the URL | High | Service worker only. Env var on the bridge. Tests assert the page DOM and the deep link contain no token. |
| GitHub DOM drift | Medium | Named registry, overrides, probe, dry-run. Defaults are a starting point. |
| Summary text discarded on **Cancel** | Medium | Revisit that cannot see the segment stays `not_placed` and may write it again. |
| No CI browser | Medium | Fixture tests for classification and click-target names. Manual smoke called out on AC 3, 7, 10, and 11. |

---

## Related artifacts

- [spec.md](spec.md)
- [github-files-changed.md](github-files-changed.md)
- [tui-review-flow/retro.md](../tui-review-flow/retro.md)
- [README.md](README.md)
