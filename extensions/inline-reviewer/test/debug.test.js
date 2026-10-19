"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const debug = require("../lib/debug.js");
const prepare = require("../lib/prepare.js");
const { createPage, selectors } = require("./dom-stub.js");

const root = path.join(__dirname, "..");
const NOW = Date.parse("2026-10-19T08:00:00.000Z");

function onDiff(extra) {
  return Object.assign(
    {
      id: "F001",
      title: "Latch",
      path: "src/Example.cs",
      line: 17,
      side: "RIGHT",
      on_diff: true,
      body: "Latch the gate.\n\nreview-pilot finding F001\n<!-- review-pilot:finding:F001 -->\n",
    },
    extra || {}
  );
}

function textareaWrites(page) {
  const areas = [page.summary, page.panelArea, page.neighborArea].concat(page.composerAreas());
  let writes = 0;
  for (let i = 0; i < areas.length; i += 1) {
    if (areas[i] && typeof areas[i].valueWrites === "function") writes += areas[i].valueWrites();
  }
  return writes;
}

function probeAt(page, extra) {
  return debug.probe(
    Object.assign(
      {
        document: page.document,
        selectors: selectors(),
        path: "src/Example.cs",
        line: 17,
        side: "RIGHT",
        now: function () {
          return NOW;
        },
      },
      extra || {}
    )
  );
}

test("probe highlights the row, range, and add control without changing a textarea", () => {
  const page = createPage({ findings: [onDiff({ start_line: 12 })] });
  const before = textareaWrites(page);
  const result = probeAt(page, { startLine: 12 });
  assert.equal(result.status, "highlighted");
  assert.equal(result.reason, "");
  assert.equal(result.highlighted, true);
  assert.equal(result.readOnly, true);
  assert.ok(result.highlights.row >= 1);
  assert.ok(result.highlights.range >= 2);
  assert.ok(result.highlights.add >= 1);
  assert.equal(page.document.querySelectorAll("[data-review-pilot-highlight='row']").length, result.highlights.row);
  assert.equal(textareaWrites(page), before);
  assert.equal(page.openComposers(), 0);
  assert.equal(page.forbiddenClicks(), 0);
  assert.equal(page.summary.value, "");
  assert.equal(page.neighborArea.value, "do not edit");
  const bundle = debug.copyDebugBundle(result.log);
  assert.match(bundle, /2026-10-19T08:00:00.000Z line-number matches [1-9]/);
  assert.match(bundle, /add-comment-button matches [1-9]/);
  assert.match(bundle, /probe highlighted/);
});

test("probe reports a collapsed file, an unloaded hunk, or an off-screen line", () => {
  const collapsed = createPage({ findings: [onDiff()], collapsed: true });
  const collapsedResult = probeAt(collapsed);
  assert.equal(collapsedResult.status, "failed");
  assert.equal(collapsedResult.reason, "collapsed_file");
  assert.match(collapsedResult.log.join("\n"), /reason collapsed_file/);
  assert.equal(collapsed.fired("Toggle diff contents", "click"), 0);
  assert.equal(textareaWrites(collapsed), 0);
  assert.equal(collapsed.openComposers(), 0);

  const hunk = createPage({ findings: [onDiff()], hunkCollapsed: true });
  const hunkResult = probeAt(hunk);
  assert.equal(hunkResult.reason, "hunk_not_loaded");
  assert.match(hunkResult.log.join("\n"), /reason hunk_not_loaded/);
  assert.equal(hunk.fired("Expand Down", "click"), 0);
  assert.equal(textareaWrites(hunk), 0);

  const offScreen = createPage({ findings: [onDiff()], unmounted: true });
  const offResult = probeAt(offScreen);
  assert.equal(offResult.reason, "line_off_screen");
  assert.match(offResult.log.join("\n"), /reason line_off_screen/);
  assert.match(debug.copyDebugBundle(offResult.log), /line-number matches 0/);
  assert.equal(textareaWrites(offScreen), 0);
});

test("picker stores an override that the next lookup uses, and clear restores the default", async () => {
  const defaults = selectors();
  const target = {
    nodeType: 1,
    tagName: "BUTTON",
    attrs: { "data-review-pilot-picked": "kept" },
    getAttribute: function (name) {
      const key = String(name || "").toLowerCase();
      return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null;
    },
  };
  const query = debug.queryForElement(target, "add-comment-button");
  assert.equal(query, "[data-review-pilot-picked='kept']");

  const doc = {
    listeners: [],
    addEventListener: function (_type, fn) {
      this.listeners.push(fn);
    },
    removeEventListener: function (_type, fn) {
      this.listeners = this.listeners.filter(function (item) {
        return item !== fn;
      });
    },
    querySelectorAll: function (selector) {
      return selector === query ? [target] : [];
    },
  };
  const pending = debug.armPicker({ document: doc, selectorId: "add-comment-button" });
  assert.equal(doc.listeners.length, 1);
  doc.listeners[0]({
    type: "click",
    target: target,
    preventDefault: function () {},
    stopPropagation: function () {},
  });
  const picked = await pending;
  assert.equal(picked.ok, true);
  assert.equal(picked.selectorId, "add-comment-button");
  assert.equal(picked.query, query);
  assert.equal(doc.listeners.length, 0);

  const stored = debug.writeOverride({}, picked.selectorId, picked.query);
  const merged = debug.mergeSelectors(defaults, stored);
  assert.equal(merged["add-comment-button"], query);
  assert.equal(debug.lookup(defaults, stored, "add-comment-button"), query);
  assert.notEqual(merged["add-comment-button"], defaults["add-comment-button"]);
  assert.equal(merged["line-number"], defaults["line-number"]);
  assert.equal(debug.matchCount(doc, merged["add-comment-button"]), 1);
  assert.equal(debug.matchCount(doc, defaults["add-comment-button"]), 0);

  const bad = debug.writeOverride(stored, "line-number", "[data-does-not-exist]");
  const broken = debug.mergeSelectors(defaults, bad);
  assert.equal(broken["line-number"], "[data-does-not-exist]");
  assert.equal(debug.matchCount(doc, broken["line-number"]), 0);

  const cleared = debug.clearOverrides(bad);
  assert.deepEqual(cleared, {});
  const restored = debug.mergeSelectors(defaults, cleared);
  assert.equal(restored["add-comment-button"], defaults["add-comment-button"]);
  assert.equal(restored["line-number"], defaults["line-number"]);
  const wrapped = debug.readOverrides({ [debug.STORAGE_KEY]: bad });
  assert.equal(debug.mergeSelectors(defaults, debug.clearOverrides(wrapped))["line-number"], defaults["line-number"]);
});

test("dry-run opens the composer and leaves the textarea empty", async () => {
  const finding = onDiff({ start_line: 12 });
  const page = createPage({ findings: [finding] });
  const result = await prepare.run({ status: "pass" }, page.request({ dryRun: true }));
  assert.equal(result.status, "pass");
  assert.equal(result.inserts, 0);
  assert.equal(result.summaryWrites, 0);
  assert.equal(page.openComposers(), 1);
  assert.equal(page.composerAreas()[0].value, "");
  assert.equal(page.composerAreas()[0].valueWrites(), 0);
  assert.equal(page.summary.valueWrites(), 0);
  assert.equal(page.panelArea.value, "panel note");
  assert.equal(page.neighborArea.value, "do not edit");
  assert.equal(page.forbiddenClicks(), 0);
  assert.equal(page.fired("Comment", "click"), 0);
  assert.equal(page.fired("Submit review control enter", "click"), 0);
  assert.equal(page.fired("Start a review", "click"), 0);
  assert.equal(page.fired("Add review comment", "click"), 0);
  assert.match(result.log.join("\n"), /preflight F001 fill/);
  assert.match(result.log.join("\n"), /dry-run stopped before the textarea write/);
  const bundle = debug.copyDebugBundle(result.log);
  assert.match(bundle, /line-number matches [0-9]+/);
  assert.match(bundle, /markdown-textarea matches [0-9]+/);
  assert.match(bundle, /add-comment-button matches [0-9]+/);

  const outside = {
    id: "F002",
    title: "F002",
    path: "src/Example.cs",
    line: 10,
    side: "RIGHT",
    on_diff: false,
    body: "Outside.\n\nreview-pilot finding F002\n<!-- review-pilot:finding:F002 -->\n",
  };
  const summaryPage = createPage({ findings: [outside], mode: "finding", findingId: "F002" });
  const summary = await prepare.run({ status: "pass" }, summaryPage.request({ dryRun: true }));
  assert.equal(summary.summaryWrites, 0);
  assert.equal(summaryPage.summary.value, "");
  assert.equal(summaryPage.summary.valueWrites(), 0);
  assert.match(summary.log.join("\n"), /dry-run stopped before the textarea write/);
  assert.equal(summaryPage.fired("Submit review control enter", "click"), 0);
  assert.equal(summaryPage.forbiddenClicks(), 0);
});

test("the panel copies the debug bundle and settings can clear overrides", () => {
  const html = fs.readFileSync(path.join(root, "sidepanel", "panel.html"), "utf8");
  const panel = fs.readFileSync(path.join(root, "sidepanel", "panel.js"), "utf8");
  const worker = fs.readFileSync(path.join(root, "background", "service-worker.js"), "utf8");
  const content = fs.readFileSync(path.join(root, "content", "content-script.js"), "utf8");
  const readme = fs.readFileSync(path.join(root, "README.md"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.match(html, /id="probe"/);
  assert.match(html, /id="dry-run"/);
  assert.match(html, /id="pick-selector"/);
  assert.match(html, /id="copy-debug"/);
  assert.match(html, /id="clear-overrides"/);
  assert.match(html, /id="probe-path"/);
  assert.match(html, /id="probe-start"/);
  assert.match(panel, /copyDebugBundle/);
  assert.match(panel, /clear-selector-overrides/);
  assert.match(panel, /pick-selector/);
  assert.match(worker, /mergeSelectors/);
  assert.match(worker, /clearSelectorOverrides/);
  assert.match(worker, /selectorOverrides|STORAGE_KEY/);
  assert.match(worker, /dryRun/);
  assert.match(content, /type === "probe"/);
  assert.match(content, /arm-picker/);
  assert.match(content, /dryRun/);
  assert.doesNotMatch(content, /\bdocument\b/);
  assert.doesNotMatch(content, /\bchrome\.storage\b/);
  assert.ok(manifest.content_scripts[0].js.includes("lib/debug.js"));
  assert.match(readme, /Updating selector defaults/);
  assert.match(readme, /Clear selector overrides/);
  assert.match(readme, /selectors\.json/);
});
