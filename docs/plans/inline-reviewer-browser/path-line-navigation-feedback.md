# Path:line navigation feedback

Status: **parked** on 2026-10-19. In-panel clicks scroll to the **file** in GitHub’s diff viewer. Line-number navigation is disabled.

Checked on the signed-in Files changed page for [kwik-trip-iot/KT.IoT.UI.Admin#354](https://github.com/kwik-trip-iot/KT.IoT.UI.Admin/pull/354) at `8120fbe1c7e67f4b47d7827721e213986cad6b21` (DOTNETIOT-2550):

| Id | Path:line | Placement | What the click should have done |
|----|-----------|-----------|----------------------------------|
| F001 | `KT.IoT.UI.Admin.E2E.Tests/ThingComboBoxScrollTestHelpers.cs:141` | not on the current diff | Open the file. Line 141 is not in the diff. |
| F002 | `KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs:126` | inline | Open line 126. This never stayed on that line. |

The side panel still **shows** `path:line`. The link target is the file.

## What was tried

1. **GitHub line hash.** The panel link used `#diff-{sha256(path)}R{line}` (or `L` for the left side), the same fragment GitHub writes when a reviewer selects a line. Ctrl/Cmd+click opened that URL. A normal click was supposed to move the active pull-request tab without a reload.

2. **Stay in the tab, then fix the file tree.** Setting `location.hash`, or resolving the fragment with `getElementById`, selected the matching node in the left file tree instead of the diff. The next version limited lookup to the diff pane, called `history.replaceState` so the hash changed without a navigation, expanded the file, scrolled, and clicked the line-number cell the way GitHub’s own line links do.

3. **File-only hash for lines that are not in the diff.** F001’s line 141 does not exist on this diff, so a `#…R141` fragment cannot land. Off-diff findings were changed to `#diff-{sha256(path)}` with no line suffix. On-diff findings, including F002 line 126, kept the `R{line}` suffix.

4. **Stop using the hash and scroll the diff pane in JavaScript.** After F002, a manual scroll, F001, then F002 again, the second F002 click returned to the scroll position from the manual scroll. GitHub treats `#diff-…` as its own scroll memory for that file or line. The replacement found the row by `data-file-path` and `data-line-number` and set `scrollTop` on `#diff-comparison-viewer-container` from `getBoundingClientRect`. It did not click the line number and it removed an existing `#diff-` hash with `history.replaceState` so GitHub would not snap back.

## What failed

- **Line hashes fight the new Files changed UI.** On the signed-in `/changes` page the fragment is shared with the file tree and with GitHub’s diff scroll restoration. Repeating a finding returned the last place the reviewer had scrolled inside that anchor, not the finding’s line.

- **Measuring the line and setting `scrollTop` did not hold line 126.** F002 (`ThingComboBoxReadExecutor.cs:126`) still did not stay on that line. File scrolling on the same container did. Likely causes, not separately proven on this page: the line cell is inside a virtualized diff and is not the element whose position matches the viewer’s scroll origin, or GitHub moves `scrollTop` again after the extension sets it. The file header with `data-file-path` is stable enough to scroll to.

- **Off-diff line numbers must not be targets.** F001’s recorded line is not a row in the diff. A line fragment or a line-cell lookup cannot succeed there.

## Where this was left

Clicks from the findings table always scroll `#diff-comparison-viewer-container` so the file header (`data-file-path`, then `data-path`) sits at the top of that container. The finding’s line and `on_diff` flag are not used for navigation.

- The visible label is still `path:line`.
- The anchor and the Ctrl/Cmd+click URL are `#diff-{sha256(path)}` with no `R` or `L` line suffix.
- The link does not carry `data-finding-line`. Its title is “Go to file on this pull request”.
- `navigateToLine` in `extensions/inline-reviewer/lib/debug.js` only calls `revealFileTarget`. `revealLineCell` and the line-centering branch of `positionComparisonViewer` remain in that file and are not used for panel clicks.
- Placement is unchanged: the table still says **inline** or **not on the current diff**. Prepare and Dry-run still use the finding line when they stage a comment.

Reload the unpacked extension before rechecking. A click on F002 should show `ThingComboBoxReadExecutor.cs` at the top of the diff pane, not line 126.
