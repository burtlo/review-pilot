# GitHub Files changed — observed UI

Status: **notes** from a browser pass on 2026-10-19. These are observations, not requirements. The requirements that follow from them are in [spec.md](spec.md).

Sessions:

| Session | Who | Page |
|---------|-----|------|
| Logged out | no GitHub session | [cli/cli#12000](https://github.com/cli/cli/pull/12000) Files changed |
| Author | `burtlo`, pull request author | [burtlo/review-pilot#2](https://github.com/burtlo/review-pilot/pull/2) (submitted line comments) and [#3](https://github.com/burtlo/review-pilot/pull/3) (no review) |
| Reviewer | a different account, not the author | [burtlo/review-pilot#3](https://github.com/burtlo/review-pilot/pull/3) |

Nothing in these sessions clicked **Comment**, **Start a review**, **Submit review** inside the dialog, **Approve**, or **Request changes**. Dialogs that were opened were closed with **Cancel**.

## Not observed

- A pending review. **Start a review** was visible on composers and was not clicked, so the button label on the second staged comment was not seen. GitHub’s docs call that later control **Add review comment**. Treat that name as unverified on this UI until a pending review is probed.
- The **+** control’s DOM. Selecting lines does not insert a comment button into the row. The operator reports that the **+** appears on hover after the range is selected. The range composer itself was on screen.
- Whether the summary text survives closing **Finish your review** without submitting.
- A left-side (deletion) comment title. Every opened composer used the `R` prefix.
- Split diff columns. **Unified** was the active view.
- The classic Files changed opt-out. The signed-in pages were the current Files changed experience.

## URLs

The tab label is **Files changed** in every session.

Logged out, `https://github.com/cli/cli/pull/12000/files` stays on `/files`. `…/pull/12000/changes` ends on `/files`. HTTP confirms the redirect: `/changes?review_pilot_issue=…&review_pilot_sha=…` returns **302** to `/files` with that query intact, and `/files?…` returns **200** with the query intact. After the page’s own scripts run, the address bar is `/files` with those parameters removed.

Signed in, on this account, `…/pull/2/files` and `…/pull/3/files` both land on `…/pull/{n}/changes`.

A line selection writes a hash. One line: `#diff-{filehash}R1`. A range: `#diff-{filehash}R19-R24`. `R` matches `data-diff-side="right"` on those rows.

Opening the comments panel sets `?panel=comments`. That parameter stays. The `review_pilot_*` parameters did not.

The page HTML contains many 40-character hex strings that are not the head commit the operator is viewing.

## Logged-out page

`cli/cli#12000` rendered the diff, the file tree, **Changes from all commits**, **File filter**, **Conversations**, and a gear whose menu lists **Unified**, **Split**, and **Hide whitespace**. Hunks expose **Expand Up** and **Expand Down**. File headers expose **Toggle diff contents**.

The header was **Sign in** / **Sign up**. File actions were disabled with “You must be signed in and have push access to make changes.” There was no line-comment control, no **Start a review**, and no **Submit review**.

The commit menu item that was present is an anchor with `data-commit="14c939560ab7dca8e29c7728e30297dc51c6b797"` and `href="/cli/cli/pull/12000/commits/14c939560ab7dca8e29c7728e30297dc51c6b797"`. Diffs load through `turbo-frame` and `include-fragment`. Some fragments showed “There was an error while loading.”

The logged-out toolbar label **Changes from all commits** is a different string from the signed-in label **All commits**.

## Signed-in toolbar

On pull requests 2 and 3, author and non-author, the Files changed toolbar is the same when no review is pending:

- **All commits**
- **Submit review** (green). The control’s accessible name is **Submit review**. The DOM also carries a short label **Review** (`submitTextShort`), which is what shows when the comments panel narrows the toolbar.
- **Open diff view settings**
- **Open overview panel**
- **Open comments panel** (badge is the comment count; with the panel open the accessible name collapsed to the count, e.g. `3 (3)`)
- **Open Copilot panel**
- viewed progress, e.g. `0 / 58 viewed`, `0 / 117 viewed`

The button class on **Submit review** was `prc-Button-ButtonBase-9n-Xk ReviewMenuButton__9e8CKv`.

There is no page-level **Start a review** control. Submitted comments on pull request 2 did not change the toolbar into a different mode. Pull request 3, with no review, showed the same **Submit review** button.

Per file header: **Collapse file**, **Not Viewed** / **Viewed**, **Comment on this file**, **More options**, **Ask about this diff**, and on some files **Display the source diff** / **Display the rich diff**. The file tree is collapsed behind **Expand file tree** and names files that already have comments, e.g. `cli.py has 1 comment`.

Pull request 3 (117 files) shows a banner: “This page has been optimized for large pull requests. Some browser features (like Find on Page or Select All) may not work as expected.” with **Switch to single file mode**. The first file’s line rows were still present in the accessibility tree.

## Commit picker

**All commits** opens a listbox. On pull request 3 the entries were:

- **All commits** — selected, described as “10 commits”. This is the cumulative range. It is not a SHA.
- **Changes since your last review** — on pull request 3, “No previous review found”.
- One row per commit. The visible id is a 7-character SHA, e.g. `Composer 2.5 impl 1` / `194510c`. The option elements had no `data-commit` and no full SHA.

Head of that list was `194510c`. Comparing the reviewed snapshot to “a SHA somewhere on the page” is not this control.

## Diff view settings

Gear menu on pull request 3:

| Control | State when opened |
|---------|-------------------|
| **Unified** | checked |
| **Split** | unchecked |
| **Minimize comments** | checked |
| **Hide whitespace** | unchecked |
| **Compact line height** | unchecked |

**Minimize comments** hides inline threads on the diff. The comments panel still showed full bodies on pull request 2. **Hide whitespace** changes which lines exist relative to a stored diff.

## Finish your review

Clicking the toolbar **Submit review** opens a dialog titled **Finish your review**. It opened with an empty summary and no pending-comment list, on both the author session (pull request 2, whose line comments were already submitted) and the non-author session (pull request 3, no review).

Contents:

- Write / Preview tabs and the markdown toolbar.
- Textarea accessible name **Markdown value**, placeholder **Leave a comment**.
- A visually hidden legend, **Add review comment** (`legend` with classes including `sr-only`).
- Radio group `reviewEvent`:

| Value | Label | Author (`burtlo` on their own PR) | Non-author |
|-------|-------|-----------------------------------|------------|
| `comment` | **Comment** — “Submit general feedback without explicit approval.” | checked, enabled | checked, enabled |
| `approve` | **Approve** — “Submit feedback and approve merging these changes.” | disabled — “Pull request authors can't approve their own pull requests.” | enabled |
| `request changes` | **Request changes** — “Submit feedback suggesting changes.” | disabled — “Pull request authors can't request changes on their own pull requests.” | enabled |

- **Cancel**
- **Submit review**, accessible name **Submit review control enter**. Disabled while the summary textarea is empty. The shortcut is Ctrl+Enter.

This dialog is the summary field and the submit surface. It is not a box sitting at the top of the diff. The author session could not approve or request changes; the reviewer session could, so those radios are live controls for the operator this extension is for.

## Comment composers

### File

**Comment on this file** opens a composer titled **Add a comment on file**. Buttons: **Cancel**, **Comment**, **Start a review**. The textarea is **Markdown value** / **Leave a comment**. With the box empty, those buttons looked muted and were not `disabled` in the DOM.

**Comment** on this composer publishes that note immediately. **Start a review** is the control that begins a pending review, and it is on the composer after the text is written.

### Lines

Clicking a line-number cell selects that line, highlights the row, and sets `#diff-{hash}R{n}`. It does not open a composer, and the row’s HTML has no comment button at that point.

The operator’s range gesture: click a line number, hold Shift, click another line number. The **+** then appears on hover for that range. Opening it produced:

- one line: title **Add a comment on line R17**
- a range: title **Add a comment on lines R19 to R24**, hash `#diff-{hash}R19-R24`

The range composer’s buttons are the same trio: **Cancel**, **Comment**, **Start a review**. The selected rows carried `data-diff-side="right"` and `data-line-number` 19 through 24.

`R` in the title is the right-hand side. A left-hand comment title was not opened.

## Line row markup

A unified-view addition row:

```html
<tr class="diff-line-row">
  <td class="focusable-grid-cell new-diff-line-number empty-diff-line left-side"></td>
  <td class="focusable-grid-cell new-diff-line-number left-side"
      data-diff-side="right"
      data-diff-line-key="b:1-l:null-r:1"
      data-line-number="1">1</td>
  <td class="diff-text-cell focusable-grid-cell left-side"
      data-diff-side="right"
      data-diff-line-key="b:1-l:null-r:1"
      data-line-number="1"
      data-line-anchor="diff-{filehash}R1">…</td>
</tr>
```

`data-diff-side` is the side (`right` here). The CSS class `left-side` is the column in the unified grid, not the diff side. `data-diff-line-key` encodes blob, left, and right line numbers (`b:1-l:null-r:1` is a right-side line with no left number). The anchor suffix `R1` matches the comment-box title prefix.

## Comments panel

**Open comments panel** navigates to `…/changes?panel=comments`. The panel lists submitted threads: file path, line, a small diff excerpt, author, rendered markdown, and **Write a reply**. Filters: **All**, **Unresolved**, **Mine**. Order: **Code order**.

On pull request 2 the panel showed three submitted comments (`cli.py` line 279, `hub_projection.py` line 209, `policy.py` line 232), including the rendered sentence “Drafted via Pat Before I Merge.” The comment container had no `textarea` and no HTML comment nodes. The raw markdown is not in the rendered DOM. The actions control is named like “Actions for burtlo's comment, 10:00 PM yesterday”. **Write a reply** is a reply on that thread, not the review summary.

Pull request 2’s conversation tab shows the same threads with **Resolve conversation** and **View reviewed changes**. Those are submitted reviews. The Files changed toolbar still offered a fresh **Finish your review** with an empty summary.

## Author chrome that a reviewer does not get

On the author session the conversation page included **Edit title**, **Merge pull request**, repository **Settings**, and **Close pull request**. On the non-author session those were absent, the reviewers sidebar said **No reviews**, and the repo nav had no **Settings**. The Files changed review dialog is the part that changes with role: **Approve** and **Request changes** are enabled only for the non-author.
