"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const placement = require("../lib/placement.js");
const prepare = require("../lib/prepare.js");
const shaGate = require("../lib/sha-gate.js");
const { panelFromPlan, renderPanelHtml, applyPrepareResult } = require("../lib/panel-model.js");
const { createPage, selectors } = require("./dom-stub.js");

const root = path.join(__dirname, "..");
const HEAD = "a".repeat(40);

function body(id, prose) {
  return prose + "\n\nreview-pilot finding " + id + "\n<!-- review-pilot:finding:" + id + " -->\n";
}

function onDiff(id, extra) {
  return Object.assign(
    {
      id: id,
      title: id,
      path: "src/Example.cs",
      line: 17,
      side: "RIGHT",
      on_diff: true,
      body: body(id, "Body " + id),
    },
    extra || {}
  );
}

function offDiff(id, prose) {
  return {
    id: id,
    title: id,
    path: "src/Example.cs",
    line: 10,
    side: "RIGHT",
    on_diff: false,
    body: body(id, prose || "Outside " + id),
  };
}

function passGate() {
  return { status: "pass", message: "SHA gate passed." };
}

function blockedGate() {
  return { status: "blocked", message: "Prepare is blocked." };
}

function clicksNamed(result, name) {
  return result.actions.filter(function (action) {
    return action.type === "click" && action.name === name;
  });
}

test("the selector registry names the stage control and the summary dialog", () => {
  const packed = selectors();
  assert.equal(packed["stage-review-button"], "Start a review");
  assert.equal(packed["composer-comment"], "Comment");
  assert.equal(packed["dialog-submit-review"], "Submit review control enter");
  assert.equal(packed["toolbar-submit-review"], "Submit review");
  assert.equal(packed["finish-review-dialog"], "Finish your review");
  assert.equal(packed["cancel-review"], "Cancel");
  assert.equal(packed["single-file-mode"], "Switch to single file mode");
  assert.match(packed["line-number"], /data-diff-side/);
  assert.match(packed["line-number"], /data-line-number/);
  const source = fs.readFileSync(path.join(root, "lib", "prepare.js"), "utf8");
  assert.equal(source.includes("clipboard"), false);
  assert.equal(source.includes("execCommand"), false);
  assert.equal(source.includes("ctrlKey"), false);
  assert.equal(source.includes("publish-review"), false);
});

test("prepare targets data-diff-side and does not submit or change the review event", async () => {
  const finding = onDiff("F001");
  const page = createPage({ findings: [finding] });
  const result = await shaGate.prepare(passGate(), page.request());
  assert.equal(result.status, "pass");
  assert.equal(result.acted, true);
  assert.equal(result.inserts, 1);
  assert.equal(result.summaryWrites, 0);
  const lineClicks = result.actions.filter(function (action) {
    return action.type === "click" && action.line;
  });
  assert.equal(lineClicks.length, 1);
  assert.equal(lineClicks[0].side, "right");
  assert.equal(lineClicks[0].line, "17");
  assert.equal(lineClicks[0].role, "number");
  assert.equal(lineClicks[0].shiftKey, false);
  assert.equal(clicksNamed(result, "Start a review").length, 0);
  assert.equal(clicksNamed(result, "Comment").length, 0);
  assert.equal(clicksNamed(result, "Submit review control enter").length, 0);
  assert.equal(clicksNamed(result, "Add review comment").length, 0);
  assert.equal(clicksNamed(result, "Viewed").length, 0);
  assert.equal(clicksNamed(result, "Abandon review").length, 0);
  assert.equal(clicksNamed(result, "Discard review").length, 0);
  assert.equal(page.forbiddenClicks(), 0);
  assert.equal(page.directClicks(), 0);
  assert.equal(page.radios.comment.checked, true);
  assert.equal(page.radios.approve.checked, false);
  assert.equal(page.radios.request.checked, false);
  assert.equal(page.radios.comment.checkedWrites(), 0);
  assert.equal(page.radios.approve.checkedWrites(), 0);
  assert.equal(page.radios.request.checkedWrites(), 0);
  assert.equal(page.radios.approve.value, "approve");
  assert.equal(page.radios.request.value, "request changes");
  assert.equal(page.radios.approve.valueWrites(), 0);
  assert.equal(page.radios.request.valueWrites(), 0);
  assert.equal(page.openComposers(), 1);
  assert.equal(page.composerAreas()[0].value, finding.body);
  assert.equal(page.summary.value, "");
  assert.equal(page.summary.valueWrites(), 0);
  assert.equal(page.panelArea.value, "panel note");
  assert.equal(page.panelArea.valueWrites(), 0);
  assert.equal(page.neighborArea.value, "do not edit");
  assert.equal(page.neighbor.textContent.includes("Already noted on this line."), true);
  assert.match(result.log.join("\n"), /preflight F001 fill/);
  assert.match(result.log.join("\n"), /not pending until Start a review is clicked/);
  assert.equal(result.findings[0].pending, false);
  assert.equal(result.actions.some(function (action) { return action.key === "Enter" || action.ctrlKey; }), false);
});

test("prepare clicks Add comment on the diff table for that file", async () => {
  const filePath = "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs";
  const finding = onDiff("F002", { path: filePath, line: 126 });
  const decoy = onDiff("F001", {
    path: "KT.IoT.UI.Admin.E2E.Tests/ThingComboBoxScrollTestHelpers.cs",
    line: 126,
  });
  const page = createPage({
    findings: [decoy, finding],
    pathOnAria: true,
    commentLabel: "Add comment",
  });
  const result = await shaGate.prepare(passGate(), page.request({ findingId: "F002", findings: [finding] }));
  assert.equal(result.status, "pass");
  assert.equal(result.inserts, 1);
  assert.equal(page.fired("Add comment", "click"), 1);
  const lineClick = result.actions.filter(function (action) {
    return action.type === "click" && action.line === "126";
  })[0];
  assert.equal(lineClick.side, "right");
});

test("Prepare all clicks Start a review and per-finding prepare does not", async () => {
  const finding = onDiff("F001");
  const one = createPage({ findings: [finding], mode: "finding" });
  const single = await prepare.run(passGate(), one.request());
  assert.equal(single.inserts, 1);
  assert.equal(one.fired("Start a review", "click"), 0);
  assert.equal(one.openComposers(), 1);

  const all = createPage({ findings: [finding], mode: "all" });
  const staged = await prepare.run(passGate(), all.request());
  assert.equal(staged.status, "pass");
  assert.equal(staged.inserts, 1);
  assert.equal(all.fired("Start a review", "click"), 1);
  assert.equal(all.fired("Comment", "click"), 0);
  assert.equal(all.openComposers(), 0);
  assert.equal(all.pendingTexts().length, 1);
  assert.match(all.pendingTexts()[0], /review-pilot finding F001/);
  assert.match(staged.log.join("\n"), /stage control clicked/);
  assert.equal(staged.findings[0].pending, true);
  assert.equal(staged.findings[0].status, "draft");
});

test("summary writes go to the Finish your review textarea", async () => {
  const first = offDiff("F002", "Outside helper");
  const second = offDiff("F003", "Also outside");
  const block =
    "## Findings outside the diff\n\n" + first.body.trim() + "\n\n" + second.body.trim() + "\n";
  const page = createPage({
    findings: [first, second],
    mode: "all",
    summaryBlock: block,
    summaryValue: "Ship it.\n\nThanks.\n",
  });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.summaryWrites, 1);
  assert.equal(result.inserts, 0);
  assert.equal(page.fired("Submit review", "click"), 1);
  assert.equal(page.fired("Cancel", "click"), 1);
  assert.equal(page.fired("Submit review control enter", "click"), 0);
  assert.equal(page.fired("Close", "click"), 0);
  assert.equal(page.dialog.getAttribute("data-open"), "false");
  assert.match(page.summary.value, /Ship it\./);
  assert.match(page.summary.value, /Thanks\./);
  assert.match(page.summary.value, /## Findings outside the diff/);
  assert.match(page.summary.value, /review-pilot finding F002/);
  assert.match(page.summary.value, /review-pilot finding F003/);
  assert.equal(page.panelArea.value, "panel note");
  assert.equal(page.radios.comment.checked, true);
  assert.equal(page.radios.approve.checked, false);
  assert.equal(page.radios.request.checked, false);
  assert.equal(page.radios.approve.valueWrites(), 0);
  assert.equal((page.summary.value.match(/## Findings outside the diff/g) || []).length, 1);
});

test("a later prepare replaces only the marked summary segment", async () => {
  const kept = "### F003 Other\n\nStay put.\n\nreview-pilot finding F003\n<!-- review-pilot:finding:F003 -->";
  const old = "### F002 Old\n\nOLD SEGMENT\n\nreview-pilot finding F002\n<!-- review-pilot:finding:F002 -->";
  const existing = "Ship it.\n\n## Findings outside the diff\n\n" + old + "\n\n" + kept + "\n\nThanks.\n";
  const finding = offDiff("F002", "### F002 New\n\nReplaced segment");
  const page = createPage({
    findings: [finding],
    mode: "finding",
    findingId: "F002",
    summaryValue: existing,
  });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.summaryWrites, 1);
  assert.match(page.summary.value, /Replaced segment/);
  assert.equal(page.summary.value.includes("OLD SEGMENT"), false);
  assert.match(page.summary.value, /Stay put\./);
  assert.match(page.summary.value, /review-pilot finding F003/);
  assert.match(page.summary.value, /Ship it\./);
  assert.match(page.summary.value, /Thanks\./);
  assert.equal(page.panelArea.value, "panel note");
  assert.equal(page.fired("Submit review control enter", "click"), 0);
});

test("two findings on one line produce two insert calls and leave the other comment", async () => {
  const findings = [onDiff("F001", { body: body("F001", "First") }), onDiff("F005", { body: body("F005", "Second") })];
  const page = createPage({ findings: findings, mode: "all" });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.inserts, 2);
  assert.equal(page.fired("Start a review", "click"), 2);
  assert.equal(page.fired("+", "click"), 2);
  assert.equal(page.pendingTexts().length, 2);
  assert.match(page.pendingTexts()[0], /review-pilot finding F001/);
  assert.match(page.pendingTexts()[1], /review-pilot finding F005/);
  assert.match(page.neighbor.textContent, /Already noted on this line/);
  assert.equal(page.neighborArea.value, "do not edit");
  assert.equal(page.neighborArea.valueWrites(), 0);
  assert.equal(page.forbiddenClicks(), 0);
  const stagedBeforeSecond = result.actions.findIndex(function (action) {
    return action.name === "Start a review";
  });
  const secondPlus = result.actions.findIndex(function (action, index) {
    return index > stagedBeforeSecond && action.name === "+";
  });
  assert.ok(stagedBeforeSecond >= 0);
  assert.ok(secondPlus > stagedBeforeSecond);
});

test("a blocked gate performs zero insert and click actions", async () => {
  const page = createPage({
    findings: [onDiff("F001"), offDiff("F002")],
    mode: "all",
    summaryBlock: "## Findings outside the diff\n\n" + body("F002", "Outside"),
    filter: "other.py",
  });
  page.resetQueries();
  const result = shaGate.prepare(blockedGate(), page.request());
  assert.equal(result.status, "blocked");
  assert.equal(result.acted, false);
  assert.equal(result.readOnly, true);
  assert.equal(result.inserts, 0);
  assert.equal(typeof result.then, "undefined");
  assert.equal(page.queries(), 0);
  assert.equal(page.clicks(), 0);
  assert.equal(page.filter.value, "other.py");
  assert.equal(page.summary.value, "");
  assert.equal(page.composerAreas().length, 0);
  assert.equal(page.forbiddenClicks(), 0);
  const direct = await prepare.run(blockedGate(), page.request());
  assert.equal(direct.acted, false);
  assert.equal(direct.readOnly, true);
  assert.equal(page.queries(), 0);
  assert.equal(page.clicks(), 0);
});

test("skip_match, manual_only, and unconfirmed replace_draft do not write", async () => {
  const skip = onDiff("F001", { scan_text: "Already placed review-pilot finding F001" });
  const skipPage = createPage({
    findings: [skip],
    comments: [
      {
        attrs: {
          class: "markdown-body",
          "data-review-pilot-comment": "pending",
          "data-unverified": "true",
        },
        text: "Already placed review-pilot finding F001",
        textarea: "Already placed review-pilot finding F001",
      },
    ],
  });
  const skipped = await prepare.run(passGate(), skipPage.request());
  assert.equal(skipped.acted, false);
  assert.equal(skipped.inserts, 0);
  assert.match(skipped.log.join("\n"), /already placed/);
  assert.equal(skipPage.fired("+", "click"), 0);

  const manual = onDiff("F007", { scan_text: "Snapshot review-pilot finding F007" });
  const manualPage = createPage({
    findings: [manual],
    comments: [
      {
        attrs: { class: "markdown-body", "data-review-pilot-comment": "submitted" },
        text: "Changed on GitHub review-pilot finding F007",
        textarea: "Changed on GitHub",
      },
    ],
  });
  const manualResult = await prepare.run(passGate(), manualPage.request());
  assert.equal(manualResult.inserts, 0);
  assert.equal(manualResult.acted, false);
  assert.match(manualResult.log.join("\n"), /manual_only/);
  const manualArea = manualPage.document.querySelector("textarea");
  assert.equal(manual.scan_text.includes("Snapshot"), true);
  assert.equal(manualResult.findings[0].outcome, "manual_only");

  const draft = onDiff("F006", { scan_text: "Snapshot review-pilot finding F006", body: body("F006", "Snapshot") });
  const draftPage = createPage({
    findings: [draft],
    comments: [
      {
        attrs: {
          class: "pending-review-comment",
          "data-review-pilot-comment": "pending",
          "data-unverified": "true",
        },
        text: "Edited draft review-pilot finding F006",
        textarea: "Edited draft",
      },
    ],
  });
  const held = await prepare.run(passGate(), draftPage.request());
  assert.equal(held.acted, false);
  assert.equal(held.inserts, 0);
  assert.match(held.log.join("\n"), /needs confirm/);
  assert.equal(draftPage.fired("+", "click"), 0);

  const allowed = createPage({
    findings: [draft],
    replaceModifiedDrafts: true,
    comments: [
      {
        attrs: {
          class: "pending-review-comment",
          "data-review-pilot-comment": "pending",
          "data-unverified": "true",
        },
        text: "Edited draft review-pilot finding F006",
        textarea: "Edited draft",
      },
    ],
  });
  const replaced = await prepare.run(passGate(), allowed.request());
  assert.equal(replaced.inserts, 0);
  assert.equal(replaced.acted, true);
  assert.equal(allowed.fired("+", "click"), 0);
  assert.equal(allowed.fired("Start a review", "click"), 0);
  const areas = allowed.document.querySelectorAll("textarea");
  let edited = "";
  for (let i = 0; i < areas.length; i += 1) {
    if (areas[i].value && String(areas[i].value).indexOf("review-pilot finding F006") !== -1) edited = areas[i].value;
  }
  assert.match(edited, /Snapshot/);
  assert.equal(manualArea == null, false);
  assert.equal(placement.hasMarker("Edited draft review-pilot finding F006", "F006"), true);
});

test("a missing row is blocked and the panel mentions Switch to single file mode", async () => {
  const finding = onDiff("F001");
  const page = createPage({ findings: [finding], unmounted: true, scrollAttempts: 3 });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.status, "blocked");
  assert.equal(result.inserts, 0);
  assert.equal(page.fired("+", "click"), 0);
  assert.equal(page.fired("Viewed", "click"), 0);
  assert.match(result.log.join("\n"), /Switch to single file mode/);
  assert.match(result.findings[0].note, /Switch to single file mode/);
  const panel = applyPrepareResult(
    panelFromPlan({
      plan: { ok: true },
      snapshot: { issue: "RP-1", pr: "acme/widgets#3", sha: HEAD, findings: [finding] },
      gate: passGate(),
      placements: { F001: { status: "not_placed", outcome: "fill" } },
    }),
    result
  );
  const html = renderPanelHtml(panel);
  assert.match(html, /Switch to single file mode/);
  assert.match(html, /data-status="blocked"/);
  assert.match(html, /class="activity-log"/);
  assert.match(html, /data-prepare-finding="F001"/);
});

test("a disabled stage control stops and a Comment-only composer is not clicked", async () => {
  const finding = onDiff("F001");
  const stuck = createPage({ findings: [finding], mode: "all", stage: "disabled" });
  const stopped = await prepare.run(passGate(), stuck.request());
  assert.equal(stopped.status, "blocked");
  assert.equal(stuck.fired("Start a review", "click"), 0);
  assert.equal(stuck.fired("Comment", "click"), 0);
  assert.match(stopped.log.join("\n"), /stayed disabled/);
  assert.equal(stopped.findings[0].status, "blocked");

  const commentOnly = createPage({ findings: [finding], mode: "all", stage: "comment" });
  const refused = await prepare.run(passGate(), commentOnly.request());
  assert.equal(refused.status, "blocked");
  assert.equal(commentOnly.fired("Comment", "click"), 0);
  assert.equal(commentOnly.fired("Start a review", "click"), 0);
  assert.match(refused.log.join("\n"), /stage control is Comment/);
});

test("prepare expands a file, clears a filter, expands a hunk, and scrolls until the row mounts", async () => {
  const finding = onDiff("F001");
  const collapsed = createPage({ findings: [finding], collapsed: true });
  const opened = await prepare.run(passGate(), collapsed.request());
  assert.equal(opened.inserts, 1);
  assert.equal(collapsed.fired("Toggle diff contents", "click"), 1);
  assert.equal(collapsed.fired("Viewed", "click"), 0);

  const filtered = createPage({ findings: [finding], filter: "other.py" });
  const cleared = await prepare.run(passGate(), filtered.request());
  assert.equal(cleared.inserts, 1);
  assert.equal(filtered.filter.value, "");

  const hunk = createPage({ findings: [finding], hunkCollapsed: true });
  const expanded = await prepare.run(passGate(), hunk.request());
  assert.equal(expanded.inserts, 1);
  assert.equal(hunk.fired("Expand Down", "click"), 1);

  const virtual = createPage({ findings: [finding], mountOnScroll: 2 });
  const scrolled = await prepare.run(passGate(), virtual.request());
  assert.equal(scrolled.inserts, 1);
  assert.equal(virtual.scrolls(), 2);
});

test("a left-side range shift-clicks the start line and ignores the other column", async () => {
  const finding = onDiff("F001", { side: "LEFT", line: 24, start_line: 19, body: body("F001", "Range") });
  const page = createPage({ findings: [finding], decoySide: "right" });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.inserts, 1);
  const clicks = result.actions.filter(function (action) {
    return action.type === "click" && action.line;
  });
  assert.equal(clicks.length, 2);
  assert.equal(clicks[0].side, "left");
  assert.equal(clicks[0].line, "24");
  assert.equal(clicks[0].shiftKey, false);
  assert.equal(clicks[0].role, "number");
  assert.equal(clicks[1].side, "left");
  assert.equal(clicks[1].line, "19");
  assert.equal(clicks[1].shiftKey, true);
  assert.equal(clicks.some(function (action) { return action.side === "right"; }), false);
});

test("Prepare all stages the inline finding before writing the summary once", async () => {
  const inline = onDiff("F001");
  const general = offDiff("F002", "Outside");
  const block = "## Findings outside the diff\n\n" + general.body.trim() + "\n";
  const page = createPage({
    findings: [inline, general],
    mode: "all",
    summaryBlock: block,
  });
  const result = await prepare.run(passGate(), page.request());
  assert.equal(result.inserts, 1);
  assert.equal(result.summaryWrites, 1);
  assert.equal(page.fired("Start a review", "click"), 1);
  const log = result.log.join("\n");
  assert.ok(log.indexOf("stage control clicked") < log.indexOf("summary block written"));
  assert.match(page.summary.value, /review-pilot finding F002/);
  assert.equal(page.panelArea.value, "panel note");
  const noted = applyPrepareResult(
    panelFromPlan({
      plan: { ok: true },
      snapshot: { issue: "RP-1", pr: "acme/widgets#3", sha: HEAD, findings: [inline] },
      placements: { F001: { status: "not_placed", outcome: "fill" } },
    }),
    {
      log: ["The comment is not pending until Start a review is clicked."],
      findings: [
        {
          id: "F001",
          status: "not_placed",
          note: "The comment is not pending until Start a review is clicked.",
        },
      ],
    }
  );
  assert.match(renderPanelHtml(noted), /not pending until Start a review is clicked/);
  assert.match(renderPanelHtml(noted), /not on the current diff|inline/);
});
