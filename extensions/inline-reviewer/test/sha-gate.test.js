"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const shaGate = require("../lib/sha-gate.js");
const placement = require("../lib/placement.js");
const prepare = require("../lib/prepare.js");
const { createPage } = require("./dom-stub.js");
const { panelFromPlan, renderPanelHtml } = require("../lib/panel-model.js");

const root = path.join(__dirname, "..");
const fixtures = path.join(root, "fixtures");
const HEAD = "a".repeat(40);
const OTHER = "b".repeat(40);
const DECOY = "c".repeat(40);
const SHORT = "194510c";
const PREFIXED = SHORT + "a".repeat(33);

function read(name) {
  return fs.readFileSync(path.join(fixtures, name), "utf8");
}

function selectors() {
  return JSON.parse(fs.readFileSync(path.join(root, "selectors.json"), "utf8"));
}

function clock() {
  return Date.UTC(2026, 9, 19, 12, 0, 0);
}

function ctx(sha, extra) {
  return Object.assign(
    {
      expectedSha: sha,
      issue: "RP-1",
      pr: "acme/widgets#3",
      now: clock,
    },
    extra || {}
  );
}

function gateFrom(name, sha) {
  const packed = selectors();
  return shaGate.evaluate(shaGate.readHtml(read(name), packed), ctx(sha || HEAD));
}

function panelHtml(gate) {
  return renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: {
        issue: "RP-1",
        pr: "acme/widgets#3",
        sha: HEAD,
        findings: [{ id: "F1", title: "Latch", path: "a.py", line: 4, side: "RIGHT", on_diff: true }],
      },
      placements: { F1: { status: "not_placed", outcome: "fill" } },
      gate: gate,
    })
  );
}

function page(label, hide, link, extra) {
  return (
    '<div data-file-list><div class="diff-line-row"></div></div>' +
    '<button type="button" data-commit-control>' +
    label +
    "</button>" +
    hide +
    (extra || "") +
    link
  );
}

const HIDE_OFF = '<input type="checkbox" data-hide-whitespace aria-label="Hide whitespace">';
const LINK = '<a data-commit="' + HEAD + '" href="/acme/widgets/pull/3/commits/' + HEAD + '">194510c</a>';

function gateHtml(html, sha) {
  return shaGate.evaluate(shaGate.readHtml(html, selectors()), ctx(sha || HEAD));
}

test("packaged selectors include the head commit link", () => {
  const packed = selectors();
  assert.deepEqual(shaGate.SELECTOR_IDS, [
    "file-list",
    "commit-control",
    "hide-whitespace",
    "head-commit-link",
  ]);
  for (let i = 0; i < shaGate.SELECTOR_IDS.length; i += 1) {
    const key = shaGate.SELECTOR_IDS[i];
    assert.equal(typeof packed[key], "string");
    assert.ok(packed[key].trim());
  }
  assert.match(packed["head-commit-link"], /data-commit/);
  assert.match(packed["head-commit-link"], /\/commits\//);
  assert.equal(shaGate.selectorsReady(packed), true);
  assert.equal(HEAD.length, 40);
  assert.equal(PREFIXED.length, 40);
  assert.equal(PREFIXED.indexOf(SHORT), 0);
  assert.notEqual(PREFIXED, SHORT);
});

test("the gate passes only for All commits, visible whitespace, and the full SHA", async () => {
  const fixture = read("range-all-commits.html");
  assert.ok(fixture.includes(HEAD));
  assert.ok(fixture.includes(DECOY));
  assert.match(fixture, /Split/);
  assert.match(fixture, /Unified/);
  const gate = gateFrom("range-all-commits.html");
  assert.equal(gate.status, "pass");
  assert.equal(gate.observedRange, "All commits");
  assert.equal(gate.observedHead, HEAD);
  assert.equal(gate.whitespaceHidden, false);
  assert.equal(gate.hydrated, true);
  assert.match(gate.message, /SHA gate passed/);
  assert.match(gate.message, new RegExp("expected SHA " + HEAD));
  assert.match(gate.message, /observed range All commits/);
  assert.match(gate.message, new RegExp("observed head " + HEAD));
  assert.match(gate.message, /issue RP-1/);
  assert.match(gate.message, /PR acme\/widgets#3/);
  assert.doesNotMatch(gate.message, /Prepare is blocked/);
  assert.doesNotMatch(gate.message, /full head SHA not found/);
  assert.doesNotMatch(gate.message, new RegExp(DECOY));
  assert.match(gate.log, /file-list matches 1/);
  assert.match(gate.log, /commit-control matches 1/);
  assert.match(gate.log, /hide-whitespace matches 1/);
  assert.match(gate.log, /head-commit-link matches 1/);
  assert.match(gate.log, /SHA gate passed/);

  const html = panelHtml(gate);
  assert.match(html, /data-gate="pass"/);
  assert.match(html, /class="activity-log"/);
  assert.match(html, new RegExp("expected SHA " + HEAD));
  assert.match(html, /observed range All commits/);
  assert.match(html, new RegExp("observed head " + HEAD));
  assert.match(html, /RP-1/);
  assert.match(html, /acme\/widgets#3/);
  assert.match(html, />inline</);

  const opened = shaGate.prepare(gate);
  assert.equal(opened.status, "pass");
  assert.equal(opened.acted, false);
  assert.equal(opened.readOnly, true);
  assert.equal(typeof opened.then, "undefined");
  assert.equal(shaGate.blocksPrepare(gate), false);
  assert.equal(shaGate.scanBlocked(gate, false), false);

  const page = createPage();
  page.resetQueries();
  const acted = await shaGate.prepare(gate, page.request());
  assert.equal(acted.status, "pass");
  assert.equal(acted.acted, true);
  assert.equal(acted.readOnly, false);
  assert.equal(acted.inserts, 1);
  assert.equal(page.forbiddenClicks(), 0);
  assert.equal(page.fired("Start a review", "click"), 0);
  assert.equal(page.radios.approve.checked, false);
  assert.equal(page.radios.comment.checked, true);
  assert.equal(page.radios.approve.checkedWrites(), 0);
  assert.equal(page.radios.approve.valueWrites(), 0);
  const lineClicks = acted.actions.filter(function (action) {
    return action.type === "click" && action.line === "17";
  });
  assert.equal(lineClicks.length, 1);
  assert.equal(lineClicks[0].side, "right");
  assert.equal(lineClicks[0].role, "number");

  const blockedPage = createPage();
  blockedPage.resetQueries();
  const blockedPrepare = shaGate.prepare(gateFrom("range-logged-out.html"), blockedPage.request({ mode: "all" }));
  assert.equal(blockedPrepare.status, "blocked");
  assert.equal(blockedPrepare.acted, false);
  assert.equal(blockedPrepare.readOnly, true);
  assert.equal(typeof blockedPrepare.then, "undefined");
  assert.equal(blockedPage.queries(), 0);
  assert.equal(blockedPage.clicks(), 0);
  assert.equal(blockedPage.summary.value, "");
  assert.equal(prepare.run, globalThis.ReviewPilotPrepare.run);

  const upper = gateHtml(fixture, HEAD.toUpperCase());
  assert.equal(upper.status, "pass");
  assert.equal(upper.observedHead, HEAD);
});

test("Changes since your last review, a single commit, and the logged-out label block", () => {
  const since = gateFrom("range-since-last-review.html");
  assert.equal(since.status, "blocked");
  assert.equal(since.observedRange, "Changes since your last review");
  assert.equal(since.observedHead, HEAD);
  assert.equal(shaGate.prepare(since).status, "blocked");
  assert.equal(shaGate.prepare(since).acted, false);
  const sinceHtml = panelHtml(since);
  assert.match(sinceHtml, /data-gate="blocked"/);
  assert.match(sinceHtml, /Prepare is blocked/);
  assert.match(sinceHtml, new RegExp("expected SHA " + HEAD));
  assert.match(sinceHtml, /observed range Changes since your last review/);
  assert.match(sinceHtml, new RegExp("observed head " + HEAD));
  assert.match(sinceHtml, /RP-1/);
  assert.match(sinceHtml, /acme\/widgets#3/);

  const single = gateFrom("range-single-commit.html");
  assert.equal(single.status, "blocked");
  assert.equal(single.observedRange, "Composer 2.5 impl 1");
  assert.match(panelHtml(single), /observed range Composer 2\.5 impl 1/);
  assert.match(panelHtml(single), new RegExp("observed head " + HEAD));
  assert.equal(shaGate.prepare(single).acted, false);

  const loggedOut = gateFrom("range-logged-out.html");
  assert.equal(loggedOut.status, "blocked");
  assert.equal(loggedOut.observedRange, "Changes from all commits");
  assert.equal(loggedOut.observedHead, HEAD);
  assert.doesNotMatch(loggedOut.message, /SHA gate passed/);
  assert.doesNotMatch(loggedOut.message, /observed range All commits/);
  assert.match(panelHtml(loggedOut), /observed range Changes from all commits/);
  assert.match(panelHtml(loggedOut), new RegExp("expected SHA " + HEAD));
  assert.match(panelHtml(loggedOut), new RegExp("observed head " + HEAD));
  assert.equal(shaGate.blocksPrepare(loggedOut), true);
});

test("hidden whitespace, a short id, a missing link, and a different SHA block", () => {
  const hidden = gateFrom("range-whitespace-hidden.html");
  assert.equal(hidden.status, "blocked");
  assert.equal(hidden.whitespaceHidden, true);
  assert.equal(hidden.observedRange, "All commits");
  assert.equal(hidden.observedHead, HEAD);
  assert.match(hidden.message, /Hide whitespace is on/);
  assert.match(panelHtml(hidden), /expected SHA /);
  assert.match(panelHtml(hidden), /observed range All commits/);
  assert.match(panelHtml(hidden), new RegExp("observed head " + HEAD));
  assert.equal(shaGate.prepare(hidden).status, "blocked");
  assert.equal(shaGate.prepare(hidden).readOnly, true);

  const shortFile = read("range-short-sha.html");
  assert.ok(shortFile.includes(PREFIXED));
  assert.equal(shortFile.includes("/commits/" + PREFIXED), false);
  const short = gateFrom("range-short-sha.html", PREFIXED);
  assert.equal(short.status, "blocked");
  assert.equal(short.observedHead, "");
  assert.equal(short.observedRange, "All commits");
  assert.match(short.message, /full head SHA not found/);
  assert.match(short.log, /head-commit-link matches 1/);
  assert.doesNotMatch(short.message, /SHA gate passed/);
  const shortHtml = panelHtml(short);
  assert.match(shortHtml, /full head SHA not found/);
  assert.match(shortHtml, new RegExp("expected SHA " + PREFIXED));
  assert.match(shortHtml, /observed range All commits/);
  assert.equal(shortHtml.includes("observed head " + PREFIXED), false);
  assert.equal(shaGate.prepare(short).acted, false);

  const missingFile = read("range-missing-link.html");
  assert.ok(missingFile.includes(HEAD));
  const missing = gateFrom("range-missing-link.html");
  assert.equal(missing.status, "blocked");
  assert.equal(missing.observedHead, "");
  assert.match(missing.message, /full head SHA not found/);
  assert.match(missing.log, /head-commit-link matches 0/);
  assert.doesNotMatch(missing.message, new RegExp("observed head " + HEAD));
  const missingHtml = panelHtml(missing);
  assert.match(missingHtml, /full head SHA not found/);
  assert.match(missingHtml, new RegExp("expected SHA " + HEAD));
  assert.match(missingHtml, /observed range/);
  assert.equal(shaGate.prepare(missing).status, "blocked");

  const mismatch = gateFrom("range-sha-mismatch.html");
  assert.equal(mismatch.status, "blocked");
  assert.equal(mismatch.observedHead, OTHER);
  assert.equal(mismatch.observedRange, "All commits");
  assert.doesNotMatch(mismatch.message, /full head SHA not found/);
  assert.doesNotMatch(mismatch.message, /SHA gate passed/);
  const mismatchHtml = panelHtml(mismatch);
  assert.match(mismatchHtml, new RegExp("expected SHA " + HEAD));
  assert.match(mismatchHtml, /observed range All commits/);
  assert.match(mismatchHtml, new RegExp("observed head " + OTHER));
  assert.equal(shaGate.prepare(mismatch).acted, false);
});

test("the full id comes from the commit link, not the first 40-hex string", () => {
  const hrefOnly = gateFrom("range-href-sha.html");
  assert.equal(hrefOnly.status, "pass");
  assert.equal(hrefOnly.observedHead, HEAD);

  const fromHref = gateHtml(
    page(
      "All commits",
      HIDE_OFF,
      '<a data-commit="' + SHORT + '" href="/acme/widgets/pull/3/commits/' + HEAD + '?decoy=' + DECOY + '">' + SHORT + "</a>",
      "<p>" + DECOY + "</p>"
    )
  );
  assert.equal(fromHref.status, "pass");
  assert.equal(fromHref.observedHead, HEAD);

  const conflict = gateHtml(
    page(
      "All commits",
      HIDE_OFF,
      '<a data-commit="' + HEAD + '" href="/acme/widgets/pull/3/commits/' + OTHER + '">' + SHORT + "</a>"
    )
  );
  assert.equal(conflict.status, "blocked");
  assert.equal(conflict.observedHead, "");
  assert.match(conflict.message, /full head SHA not found/);

  const tooLong = HEAD + "a";
  const longId = gateHtml(
    page(
      "All commits",
      HIDE_OFF,
      '<a data-commit="' + tooLong + '" href="/commits/' + tooLong + '">x</a><p>' + HEAD + "</p>"
    )
  );
  assert.equal(longId.status, "blocked");
  assert.equal(longId.observedHead, "");
  assert.match(longId.message, /full head SHA not found/);
});

test("whitespace and range reads fail closed without toggling the view", () => {
  const checked = gateHtml(
    page(
      "All commits",
      '<div data-hide-whitespace role="menuitemcheckbox" aria-checked="true">Hide whitespace</div>',
      LINK
    )
  );
  assert.equal(checked.status, "blocked");
  assert.equal(checked.whitespaceHidden, true);

  const clear = gateHtml(
    page(
      "All commits",
      '<div data-hide-whitespace role="menuitemcheckbox" aria-checked="false">Hide whitespace</div>',
      LINK
    )
  );
  assert.equal(clear.status, "pass");

  const unread = gateHtml(page("All commits", "", LINK));
  assert.equal(unread.status, "blocked");
  assert.equal(unread.whitespaceHidden, null);
  assert.match(unread.message, /Hide whitespace was not read/);

  const longer = gateHtml(page("All commits today", HIDE_OFF, LINK));
  assert.equal(longer.status, "blocked");
  assert.equal(longer.observedRange, "All commits today");

  const shouted = gateHtml(page("ALL COMMITS", HIDE_OFF, LINK));
  assert.equal(shouted.status, "blocked");

  const named = gateHtml(
    page(
      "All commits",
      HIDE_OFF,
      LINK
    ).replace(
      "<button type=\"button\" data-commit-control>All commits</button>",
      '<button type="button" data-commit-control aria-label="Changes since your last review">All commits</button>'
    )
  );
  assert.equal(named.observedRange, "Changes since your last review");
  assert.equal(named.status, "blocked");

  const wrapped = gateHtml(
    page("ignored", HIDE_OFF, LINK).replace(
      "<button type=\"button\" data-commit-control>ignored</button>",
      "<button type=\"button\" data-commit-control><span>All commits</span></button>"
    )
  );
  assert.equal(wrapped.observedRange, "All commits");
  assert.equal(wrapped.status, "pass");
});

test("hydration waits for the file list and commit control, then times out blocked", async () => {
  const packed = selectors();
  let scheduled = 0;
  const ready = await shaGate.waitForRoot(passDocument(packed), packed, {
    timeoutMs: 8000,
    schedule: function () {
      scheduled += 1;
    },
  });
  assert.equal(ready.hydrated, true);
  assert.equal(ready.timedOut, false);
  assert.equal(scheduled, 0);
  assert.equal(shaGate.evaluate(ready, ctx(HEAD)).status, "pass");

  let t = 0;
  const appeared = await shaGate.waitForRoot(
    passDocument(packed, function () {
      return t >= 100;
    }),
    packed,
    {
      timeoutMs: 500,
      intervalMs: 50,
      now: function () {
        return t;
      },
      schedule: function (fn) {
        t += 50;
        fn();
      },
    }
  );
  assert.equal(appeared.hydrated, true);
  assert.equal(t >= 100, true);

  t = 0;
  const timedOut = await shaGate.waitForRoot(
    { querySelector: function () { return null; } },
    packed,
    {
      timeoutMs: 100,
      intervalMs: 50,
      now: function () {
        return t;
      },
      schedule: function (fn) {
        t += 50;
        fn();
      },
    }
  );
  assert.equal(timedOut.timedOut, true);
  assert.equal(timedOut.hydrated, false);
  const blocked = shaGate.evaluate(timedOut, ctx(HEAD));
  assert.equal(blocked.status, "blocked");
  assert.match(blocked.message, /full head SHA not found/);
  assert.match(blocked.message, new RegExp("expected SHA " + HEAD));
  assert.match(blocked.message, /observed range/);
  assert.match(blocked.message, /did not hydrate/);
  assert.match(panelHtml(blocked), /full head SHA not found/);
  assert.equal(shaGate.prepare(blocked).status, "blocked");
  assert.equal(shaGate.prepare(blocked).acted, false);

  const started = Date.now();
  const absent = await shaGate.observePage({ selectors: packed, timeoutMs: 8000 });
  assert.equal(absent.timedOut, true);
  assert.ok(Date.now() - started < 500);

  globalThis.document = passDocument(packed);
  try {
    const seen = await shaGate.observePage({ selectors: packed, timeoutMs: 0 });
    assert.equal(seen.hydrated, true);
    assert.equal(shaGate.evaluate(seen, ctx(HEAD)).status, "pass");
  } finally {
    delete globalThis.document;
  }
});

test("reading the page does not click or change Hide whitespace", () => {
  const packed = selectors();
  let clicks = 0;
  const nodes = passNodes();
  nodes.hide.checked = true;
  nodes.commit.click = function () {
    clicks += 1;
  };
  nodes.hide.click = function () {
    clicks += 1;
  };
  const before = nodes.hide.checked;
  const reading = shaGate.readRoot(passDocument(packed, null, nodes), packed);
  const gate = shaGate.evaluate(reading, ctx(HEAD));
  const result = shaGate.prepare(gate);
  assert.equal(gate.status, "blocked");
  assert.equal(result.status, "blocked");
  assert.equal(result.acted, false);
  assert.equal(result.readOnly, true);
  assert.equal(clicks, 0);
  assert.equal(nodes.hide.checked, before);

  nodes.hide.checked = false;
  const open = shaGate.evaluate(shaGate.readRoot(passDocument(packed, null, nodes), packed), ctx(HEAD));
  assert.equal(open.status, "pass");
  assert.equal(shaGate.prepare(open).acted, false);
  assert.equal(nodes.hide.checked, false);
  assert.equal(clicks, 0);
});

test("a blocked gate keeps placement blocked and a pass leaves the scan alone", () => {
  const pass = gateFrom("range-all-commits.html");
  const blocked = gateFrom("range-logged-out.html");
  const finding = { id: "F001", on_diff: true };
  const open = placement.scanPlacement([finding], [], {
    blocked: shaGate.scanBlocked(pass, false),
  });
  assert.equal(open.findings[0].status, "not_placed");
  assert.equal(open.findings[0].outcome, "fill");
  const held = placement.scanPlacement([finding], [], {
    blocked: shaGate.scanBlocked(blocked, false),
  });
  assert.equal(held.findings[0].status, "blocked");
  assert.equal(held.findings[0].outcome, null);
  assert.equal(shaGate.prepare(null).status, "blocked");
  assert.equal(shaGate.scanBlocked(null, false), true);
});

test("prepare stays read-only in the content script and the service worker", () => {
  const source = fs.readFileSync(path.join(root, "lib", "sha-gate.js"), "utf8");
  const content = fs.readFileSync(path.join(root, "content", "content-script.js"), "utf8");
  const worker = fs.readFileSync(path.join(root, "background", "service-worker.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.ok(manifest.content_scripts[0].js.includes("lib/sha-gate.js"));
  assert.match(content, /read-range-gate/);
  assert.match(content, /ReviewPilotShaGate/);
  assert.match(content, /type === "prepare"/);
  assert.doesNotMatch(content, /\bdocument\b/);
  assert.doesNotMatch(content, /\.click\s*\(/);
  assert.equal(content.includes("Start a review"), false);
  assert.equal(content.includes("Finish your review"), false);
  assert.match(worker, /read-range-gate/);
  assert.match(worker, /selectors\.json/);
  assert.match(worker, /expectedSha:\s*result\.snapshot\.sha/);
  assert.match(worker, /scanBlocked\(gate/);
  assert.match(worker, /type === "prepare"/);
  assert.match(worker, /ReviewPilotShaGate\.prepare/);
  assert.doesNotMatch(worker, /expectedSha:\s*message\.expectedSha/);
  assert.doesNotMatch(worker, /\.click\s*\(/);
  assert.equal(worker.includes("Start a review"), false);
  assert.equal(worker.includes("Finish your review"), false);
  assert.doesNotMatch(source, /\.click\s*\(/);
  assert.doesNotMatch(source, /\.checked\s*=[^=]/);
  assert.doesNotMatch(source, /setAttribute\s*\(/);
  assert.doesNotMatch(source, /innerHTML/);
  assert.equal(source.includes("Start a review"), false);
  assert.equal(source.includes("Finish your review"), false);
});

function textNode(value) {
  return { nodeType: 3, nodeValue: value };
}

function domEl(tag, attrs, options) {
  const opts = options || {};
  const children = opts.children || [];
  const el = {
    tagName: tag.toUpperCase(),
    childNodes: children,
    textContent: opts.textContent != null ? opts.textContent : "",
    getAttribute: function (name) {
      const key = String(name || "").toLowerCase();
      if (!Object.prototype.hasOwnProperty.call(attrs, key)) return null;
      return attrs[key];
    },
  };
  if (typeof opts.checked === "boolean") el.checked = opts.checked;
  return el;
}

function passNodes() {
  return {
    file: domEl("div", { "data-file-list": "" }),
    commit: domEl(
      "button",
      { "data-commit-control": "" },
      { children: [textNode("\n  All commits\n  "), { nodeType: 1, textContent: "10 commits" }] }
    ),
    hide: domEl(
      "input",
      { "data-hide-whitespace": "", "aria-label": "Hide whitespace" },
      { checked: false }
    ),
    head: domEl("a", {
      "data-commit": HEAD,
      href: "/acme/widgets/pull/3/commits/" + HEAD,
    }),
  };
}

function passDocument(packed, ready, nodes) {
  const found = nodes || passNodes();
  return {
    querySelector: function (selector) {
      if (ready && !ready()) return null;
      if (selector === packed["file-list"]) return found.file;
      if (selector === packed["commit-control"]) return found.commit;
      if (selector === packed["hide-whitespace"]) return found.hide;
      if (selector === packed["head-commit-link"]) return found.head;
      return null;
    },
  };
}
