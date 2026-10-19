# Inline reviewer browser overlay

Status: **approved** — 2026-10-19. From operator retro interview (2026-10-18); revised 2026-10-19 (review-draft flow, revisit/idempotency, DOM tooling, Files changed pass). Mapped in [implementation.md](implementation.md).

## Source

- Bundle: [README](README.md)
- Retro: [tui-review-flow/retro.md](../tui-review-flow/retro.md) — investigations: **Findings layout**, **Triage chrome**, cross-cutting **Triage reading layout**; motivation: connect automated findings to **real diff lines** and **suggested changes**
- UI notes: [github-files-changed.md](github-files-changed.md) — logged-out page, signed-in Files changed, pull-request author, and non-author reviewer (2026-10-19). Element names and DOM details live there. This spec states the requirements those sessions imply.

## Operator outcome

From a link in the review workflow, open the pull request **Files changed** tab on `github.com` (signed-in path `…/pull/{n}/changes`; the tab label is **Files changed**). After the **commit range and head SHA** are verified against the reviewed snapshot, assist placing **all automated findings** into GitHub’s **pending review**: inline comments as **draft line comments** (including markdown **suggestion** fences where applicable) and off-diff findings in the summary field of the **Finish your review** dialog. The human **reviews, edits, and submits** on GitHub. The extension does not call GitHub APIs to publish.

**Start a review** is the button on a line or file composer after the body is filled. It stages that comment. It is not a page-level mode switch, and the page has no summary box at the top of the diff. The toolbar **Submit review** button opens **Finish your review**, which is the summary field and the submit dialog together. The extension may open that dialog to fill the summary. It never clicks **Submit review** inside the dialog, never sends Ctrl+Enter there, and never changes the review-event radios.

## Problem statement

The Textual triage UI cannot show proposed code in the same surface as the PR diff; titles and suggested changes are hard to read and do not align visually with GitHub’s line anchors ([retro](../tui-review-flow/retro.md)). Operators already use GitHub for final comments; the gap is **assistive placement and formatting** in GitHub’s **draft review** before submit, with a **hard SHA gate** so comments are not prepared against the wrong commit.

## Scope

### In scope

- Chromium **Manifest V3** extension, **side-loaded** on **Microsoft Edge and Google Chrome** (one build).
- Content scripts may load on `https://github.com/*`. The extension acts only when the page’s `owner/repo` matches the operator’s allowlist (wildcards allowed, for example `kwik-trip-iot/*` or `*/*`). Every other GitHub page stays idle and does not call the bridge.
- **Settings panel:** a masked text field for the bridge shared secret, stored in extension storage, and the repo allowlist. The secret is never put in a GitHub URL or in the page DOM.
- **Deep links** from review-ticket to `https://github.com/{owner}/{repo}/pull/{n}/changes?…` with query parameters identifying the review snapshot (issue key, PR, **reviewed SHA**). There is no finding-id parameter. The bridge secret is not in the URL. GitHub removes unknown query parameters after load, so the content script reads them at document start and stores them for the tab. `?panel=comments` is GitHub’s own parameter and may appear later.
- **Local bridge** (localhost HTTP on `127.0.0.1`, token-authenticated) serving snapshot data from existing artifacts: `findings.json`, stored diff / `diff_index` semantics aligned with `build_review_payload` in `review_ticket/findings.py`. The extension service worker calls the bridge, and only for an allowlisted repo. Page scripts on `github.com` do not receive the token.
- On load (and before any UI automation), after the file list and **All commits** control have hydrated (bounded wait; timeout is `blocked`):
  - Resolve snapshot from the stored link parameters.
  - Read **reviewed SHA** from snapshot / `session.json` `pr_shas`.
  - Compare to the Files changed view the operator is on. Prepare runs only when all of these hold: the commit control is **All commits** (the cumulative range, not one commit and not **Changes since your last review**); the head commit of that range equals the reviewed SHA (full SHA; the menu shows 7 characters, so the full id comes from the commit link or equivalent, not from the first 40-character hex string in the page); **Hide whitespace** is off. The extension does not toggle whitespace or unified/split for the operator.
  - **Mismatch → block automation**; show extension panel message (and optional detail log): expected SHA, observed range, observed head SHA, issue/PR.
- **Staging** (when the SHA gate passes and the operator runs a prepare action). There is no separate bootstrap click.
  - If a pending review is already open, add to it and log that. Never click **Abandon review** or **Discard review**.
  - The control that stages the first comment is **Start a review** on that comment’s composer. A later composer’s stage control must be probed on a real pending review; it must not be **Comment**.
  - Never click the composer’s **Comment** button (that publishes the note immediately).
  - Never click **Submit review** in **Finish your review**, never send Ctrl+Enter in that dialog, and never change `reviewEvent`. **Comment** stays selected. For a non-author, **Approve** and **Request changes** are enabled; clicking them and submitting would publish that review event. For the pull request author those two radios are disabled.
- For each **automated finding** in the snapshot:
  - List in extension sidebar (id, title, path:line, inline vs not-on-diff, **placement status** — see [Finding placement status](#finding-placement-status)).
  - **Comment body format:** reuse **`render_finding_body`** rules — title, explanation, and ` ```suggestion ` block when `suggestion_ok(suggested_change)` and inline (same as publish preview). Bodies go into the composer textarea (accessible name **Markdown value**). The extension does not click GitHub’s suggestion toolbar and does not use a separate “proposed change” API. Insert so GitHub enables the stage control; do not write the operator’s clipboard. If the stage control stays disabled, stop and log.
  - **Finding marker:** append one visible line outside any ` ```suggestion ` fence, stable per finding id, recoverable from the **rendered** comment without clicking **Edit**. GitHub’s rendered comment DOM drops HTML comments, so `<!-- review-pilot:finding:{id} -->` alone is not the scan key. An HTML comment may also be appended for the raw body. Bridge may expose the same marker rules for golden tests.
  - On **“Prepare comment on GitHub”** (per finding):
    - Run **placement preflight** (pending review, the comments panel with resolved threads included, and the summary if the dialog is opened read-only). **Minimize comments** hides inline threads; the scan uses the comments panel or turns that filter off only for the scan and restores it.
    - Apply [Preflight outcomes](#preflight-outcomes). Open the **+** and insert text only for **fill** or **replace_draft**.
    - If on-diff per the same rules as publish (`path`, `line`, `side` in `diff_index`): if that file is already collapsed, expand it; clear a file filter that hides it; expand the hunk; scroll until the row is mounted (large-PR virtualized mode included; if the row never mounts, status `blocked` and tell the operator about **Switch to single file mode**). Prepare does not mark the file **Viewed**. Select the line-number cell for `line` on `side` (`data-diff-side`, not the `left-side` CSS column). When `start_line` differs, Shift-click the other line number so the range matches. The composer title is **Add a comment on line R{n}** or **Add a comment on lines R{start} to R{end}** for the right side (left side uses the title GitHub shows for that side). Hover the range and activate **+**. Replace the whole composer with the snapshot body. Do not click **Comment**. Another comment already on that line does not change this: GitHub allows multiple comments on one line, so the finding still gets its own inline comment and is not moved to the summary. Do not edit the other comment. A comment GitHub has collapsed is expanded before the scan reads it or before `replace_draft` edits it.
    - **Per-finding prepare** stops with the composer open and the body filled. The panel says the comment is not pending until **Start a review** (or the later stage control) is clicked.
    - **Prepare all** clicks that stage control and waits until the comment shows as pending before the next finding. Only one composer stays open; an unstaged composer is lost when the next line opens.
  - If **not on diff**: place text in the **Finish your review** summary (open the toolbar **Submit review**, edit only the summary textarea, leave `reviewEvent` on **Comment**, close with **Cancel** or the dialog close control — never the dialog’s **Submit review**). Prose matches **`_general_section`**. Several off-diff findings share one field: **Prepare all** writes that marked block once. A later prepare inserts or replaces only a marked segment and leaves unmarked operator prose. Do not paste into the **Comments** panel or **Comment on this file**; those are other surfaces. Sidebar explains that inline placement is impossible on this diff. If a revisit cannot see a persisted summary, status stays `not_placed`.
- **“Prepare all findings”** (optional primary action in the side panel): SHA gate, then each on-diff finding in snapshot order (preflight, fill or replace, stage, wait until it shows as pending), then one summary block in **Finish your review**. The operator edits and submits on GitHub. The extension UI is the browser side panel so it does not cover the file tree or GitHub’s Overview, Comments, or Copilot panels.
- Extension **activity log** in the panel: SHA check result, stage-control result, per-finding preflight decision, DOM step failures, skip reasons.
- **DOM maintenance tooling** (shipped with the extension, not a separate app): see [Selector and debug tooling](#selector-and-debug-tooling).

### Out of scope

- Submitting the PR review or calling GitHub REST/GraphQL **publish** APIs from the extension (authorized publish stays `review-ticket` / `authorize`).
- Changing `review-ticket publish`. Later, publish should refuse when a visible finding marker is already on that pull request, so the two paths do not place the same findings twice. That refusal is not part of this bundle.
- Choosing review event (**Approve** / **Request changes** / **Comment**) on behalf of the operator.
- Filtering findings by human triage (accept/reject/include) — **all** snapshot findings are listed; triage remains in attach TUI.
- `github.enterprise.com` or hosts other than `github.com`.
- Chrome Web Store / Edge Add-ons public listing (side-load / IT policy only).
- Fixing TUI generation, Escape-cancel, worktree, hub re-attach ([tui-review-flow retro](../tui-review-flow/retro.md)) — separate bundle.

## Finding placement status

Sidebar and log use one status per finding after each scan (on load, after prepare, on operator **Refresh scan**):

| Status | Meaning |
|--------|---------|
| `not_placed` | No marker match and no heuristic match on the target line / summary. |
| `draft` | Pending-review comment (or summary segment) contains this finding’s marker; body matches snapshot body (normalized whitespace). |
| `draft_modified` | Marker present but body differs from snapshot (operator or stale snapshot). |
| `published` | Submitted comment has this finding’s visible marker and the normalized body matches. |
| `published_modified` | Marker is on a submitted comment and the body differs. Preflight is `manual_only`. |
| `blocked` | SHA or range mismatch, row or **+** not resolved, virtualized row not mounted, or stage control stayed disabled. |

## Preflight outcomes

Before paste/automation for a finding:

| Outcome | When | Extension behavior |
|---------|------|-------------------|
| `fill` | `not_placed` and line/summary available | Automate open composer and paste snapshot body (incl. marker). |
| `replace_draft` | `draft_modified` | Replace that composer or marked summary segment after explicit per-finding confirm, or when **“Replace modified drafts”** is on. Edit the existing pending comment; opening **+** again would add a second comment. |
| `skip_match` | `draft` or `published` with matching body | Do not insert; focus the existing comment when possible; log “already placed”. |
| `manual_only` | `published_modified` | No overwrite; show snapshot and observed text in the panel. The operator edits on GitHub. |

**Revisit / second session:** Operator may close the tab and return days later. On load, extension runs a full **Refresh scan** (read-only DOM pass) and updates statuses. Prepare actions respect preflight; they never duplicate an unchanged `published` or `draft` finding unless operator confirms **replace**.

**Suggestion blocks:** If a line already has a draft containing a ` ```suggestion ` fence, **replace** (default) swaps the entire textarea contents with the snapshot body, including a new suggestion fence when `suggestion_ok` and inline. The extension does not merge two suggestion blocks into one composer.

## Selector and debug tooling

GitHub’s Changes DOM is **brittle**. The spec requires first-party tooling in the extension:

- **Structured log** (panel + optional “Copy debug bundle”): timestamped steps, selector id used, match count, truncated outerHTML or aria labels, screenshot optional in manual mode.
- **Selector registry:** named selectors (e.g. `line-row`, `add-comment-button`, `review-summary-textarea`, `start-review-button`) loaded from packaged defaults with **operator overrides** stored in `chrome.storage` (JSON), documented in repo for updates when GitHub ships UI changes.
- **Probe mode:** operator enters `path`, `line`, optional `start_line`; content script highlights the resolved row, range, and **+** control without pasting; reports failure reason (file collapsed, line off-screen, hunk not loaded).
- **Picker mode:** operator clicks an element on the page; extension records a CSS path / data-attribute query into the registry entry under edit (for maintainers).
- **Dry-run prepare:** run preflight + navigation through opening composer **without** paste, to validate selectors on a live PR.

Implementation may ship selector defaults in versioned files; overrides win at runtime. CI cannot rely on live GitHub; unit tests use recorded HTML fixtures where feasible.

## Decisions

| ID | Decision | Rationale | Retro link |
|----|----------|-----------|------------|
| D1 | New bundle `inline-reviewer-browser`, not an amendment to `tui-review-flow/spec.md` | Different delivery surface (browser + local bridge) | Cross-cutting layout |
| D2 | `github.com` for any owner and repo, idle unless the page matches the operator’s `owner/repo` allowlist | Avoids calling the bridge with the token on every GitHub page. `kwik-trip-iot` is one private org, not a hard-coded limit | Operator 2026-10-19 |
| D3 | One MV3 build, Edge + Chrome side-load | Operator request; shared Chromium stack | — |
| D4 | Stage into GitHub **pending review**; human submits | Edit all drafts and summary before post | Triage chrome |
| D5 | All automated findings in snapshot | Operator choice in interview | Findings layout |
| D6 | SHA mismatch blocks all prepare automation; extension reports mismatch | Operator choice in interview | Stale SHA (cf. review-interactive-ui D9) |
| D7 | Per-finding **Prepare** plus optional **Prepare all** | Batch for full review; single-finding for incremental work | — |
| D8 | Comment markdown matches `render_finding_body` / publish inline comments; general text matches `_general_section` | One source of truth for suggestion blocks | — |
| D9 | Localhost bridge required; extension does not read `reviews/` paths directly | Browser security model | — |
| D10 | Stage with **Start a review** on the composer; never submit, and never change the review event | **Submit review** opens **Finish your review**, where a non-author can approve or request changes. **Comment** on a composer publishes immediately | Files changed pass 2026-10-19 |
| D11 | Visible finding marker in the rendered comment; HTML comment is optional raw-body copy | Rendered comments on the Files changed page omit HTML comments, so a hidden marker is missed and prepare would duplicate | Files changed pass 2026-10-19 |
| D12 | Bundled selector registry + probe/picker/debug modes | DOM volatility; reduce maintenance cost | Operator feedback 2026-10-19 |
| D13 | Several findings on one line each get their own inline comment | GitHub allows multiple comments on a line. A second finding is not moved to the summary and does not edit the other comment | Operator 2026-10-19 |
| D14 | Shared secret is a masked settings field; repo allowlist gates bridge calls | Operator sets the secret in the extension. Unmatched pages stay idle | Operator 2026-10-19 |
| D15 | This bundle does not change `review-ticket publish` | Publish should later refuse when a visible marker is already on the pull request. That refusal is a separate change | Operator 2026-10-19 |

## Assumptions

- Operator runs a **local bridge** while using the extension (e.g. `review-ticket … serve-inline-review` or folded into `attach` — exact CLI name in implementation map).
- Operator is **logged into GitHub** as someone who can comment and who is not limited to the author dialog. Acceptance smoke uses a non-author, because **Approve** and **Request changes** are enabled for that role ([github-files-changed.md](github-files-changed.md)).
- GitHub’s Files changed DOM is automatable and brittle. Selectors are maintained via defaults, overrides, and debug tooling. Logged-out pages omit the review controls.
- Deep-link query parameter names are stable once shipped (`review_pilot_issue`, `review_pilot_sha`, and the PR is identified by the URL) and are captured before GitHub strips them. There is no `review_pilot_finding` parameter.
- The settings allowlist uses `owner/repo` patterns. `*` matches within a segment (`kwik-trip-iot/*`, `*/*`). An empty allowlist matches nothing, so the panel stays idle and the token is not sent.
- “All findings” includes those that will never inline; they appear in the sidebar with summary placement and skip messaging.
- Initial PR links in review-ticket use `/changes` plus those query params (small CLI/TUI delta in this feature).
- Pending-review detection is per logged-in user. Author and non-author dialogs differ as recorded in the UI notes. The second-comment stage button is still unprobed.

## Acceptance criteria

1. Side-loaded extension loads on `https://github.com/*/pull/*/changes` without store install. On an allowlisted repo, a deep link’s `review_pilot_*` parameters are still available to the panel after GitHub drops them from the address bar. On any other repo the panel stays idle and does not call the bridge.
2. Opening a review-ticket-generated link loads **Files changed** and the side panel shows issue, PR, **reviewed SHA**, the commit control’s range, and the full finding list from `findings.json` with placement status after scan.
3. When the SHA gate passes, preparing an on-diff finding selects the file line or Shift-clicked range on the correct `side` and opens **Add a comment on line…** / **Add a comment on lines…** with a body matching `render_finding_body` (suggestion fence when applicable) plus the visible finding marker. **Prepare all** then clicks **Start a review** (or the probed later stage control) and leaves a pending comment. It does not click **Comment**.
4. When the range is not **All commits**, whitespace is hidden, or the head SHA differs, no line, **+**, or insert automation runs. The panel shows expected SHA, observed range, and observed head SHA.
5. Prepare may open **Finish your review** to fill the summary and may click **Start a review** on a composer. It never clicks the dialog’s **Submit review**, never sends Ctrl+Enter there, and never moves the review event off **Comment**.
6. Off-diff findings are listed and prepared into that summary field, not into the comments panel and not as a fake inline comment. The log and sidebar say they are not on the current diff.
7. Revisit: a **published** or **draft** finding whose rendered text matches is not duplicated; the panel shows `skip_match`. A submitted comment whose body differs is `published_modified` / `manual_only`.
8. Two on-diff findings for the same line both become inline comments. Prepare does not edit the other comment and does not move either finding to the summary.
9. The shared secret is entered in the settings panel’s masked field and is sent only from the service worker to `127.0.0.1`. Non-local origins cannot read snapshots. A page outside the allowlist does not trigger that call.
10. Probe mode resolves at least path+line on a smoke PR or reports a structured failure in the log.
11. Same unpacked extension runs on current Edge and Chrome (manual smoke on one `github.com` pull request the operator can comment on). A repo that is not on the allowlist shows an idle panel.

## Verification plan

- **Fixture test (Python):** deep-link URL builder; bridge returns findings + `diff_index` for a fixture under `reviews/…/commits/<sha>/review/`.
- **Unit (extension):** map finding → comment body string (parity with `render_finding_body` fixtures or shared golden files); marker append; normalized body compare for preflight.
- **Fixture HTML (extension):** preflight classification for published, draft, and a second finding on a line that already has a comment, given saved GitHub DOM snippets.
- **Manual:** PR with 2+ findings (one on-diff with suggestion, one off-diff); match SHA → **Prepare all** → verify pending review, draft line bodies, summary section; submit manually on GitHub once.
- **Manual:** Repeat visit after submit → statuses `published`; prepare does not duplicate.
- **Manual:** Edit one draft body on GitHub → `draft_modified`; confirm panel shows diff and replace requires confirm.
- **Manual:** Two findings on one line → two inline comments; neither is placed in the summary. A collapsed comment can be expanded and its rendered text still matches the marker.
- **Manual:** Probe mode on on-diff finding; picker records override; dry-run opens composer without paste.
- **Manual:** Edge + Chrome side-load on Windows (operator environment).

## Implementation hints (optional)

- New package e.g. `inline_reviewer_browser/` or `extensions/inline-reviewer/` plus a thin `review_ticket` bridge module reusing `parse_unified_diff` / diff index from `review_ticket/textutil.py` and `render_finding_body` / `_general_section` from `findings.py`.
- Content script: observe `/changes` (and `/files` if a logged-out redirect is still on that path), capture query params at document start, fetch `GET /snapshot?...` from the service worker. Head SHA comes from the **All commits** menu’s latest commit link, not from an arbitrary hex string. Line identity uses `data-diff-side`, `data-line-number`, and `data-line-anchor`.
- Set the **Markdown value** textarea and dispatch the input event GitHub uses to enable **Start a review**. Do not use the clipboard.
- Preflight reads rendered comment text in the comments panel and in pending threads. The visible marker is the scan key. See [github-files-changed.md](github-files-changed.md).
- Optional follow-up: highlight finding row when hovering diff lines (read-only aid).

## Deferred / follow-up

- Filter findings by triage (accepted/included only).
- Auto-advance queue (“Prepare next”) after operator dismisses composer.
- Switch GitHub Changes view to reviewed commit when still reachable on the PR.
- GHE host allowlist configuration.
- Store distribution / enterprise force-install policy.
- TUI layout fixes (stacked findings, wrap) in parallel — still valuable without the extension.
- Fingerprint-based match without marker (legacy comments posted before marker shipped).
- Confirm the stage-button label on the second comment once a pending review exists (not observed on 2026-10-19).
- Confirm whether the **Finish your review** summary persists after **Cancel**.
