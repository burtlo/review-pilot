"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const placement = require("../lib/placement.js");
require("../lib/diff-anchor.js");
const { panelFromPlan, renderPanelHtml } = require("../lib/panel-model.js");

const root = path.join(__dirname, "..");
const fixtures = path.join(root, "fixtures");
const goldenDir = path.join(__dirname, "../../../tests/fixtures/inline_review");

function readFixture(name) {
  return fs.readFileSync(path.join(fixtures, name), "utf8");
}

function golden(name) {
  return fs.readFileSync(path.join(goldenDir, name), "utf8").trim();
}

const SCAN_F001 = golden("scan_text_f001.golden.txt");
const SCAN_F002 = golden("scan_text_f002.golden.txt");
const SCAN_F005 =
  "Second finding (Suggestion, low) This line already has another comment. review-pilot finding F005";

function finding(row) {
  return Object.assign(
    {
      id: "F001",
      title: "Missing validation",
      path: "src/Example.cs",
      line: 142,
      side: "RIGHT",
      on_diff: true,
      scan_text: SCAN_F001,
    },
    row || {}
  );
}

function byId(result, id) {
  const row = result.findings.find(function (item) {
    return item.id === id;
  });
  assert.ok(row, id);
  return row;
}

test("matching rendered text is skip_match for draft and published", () => {
  const pendingFile = readFixture("pending-comment.html");
  const submittedFile = readFixture("submitted-comment.html");
  assert.match(pendingFile, /Unverified against a live pending review/);
  assert.match(pendingFile, /no production default/);

  const pending = placement.scanPlacement([finding()], pendingFile, {});
  assert.equal(pending.readOnly, true);
  assert.equal(pending.comments.length, 1);
  assert.equal(pending.comments[0].region, "pending");
  assert.equal(pending.comments[0].unverified, true);
  assert.equal(pending.comments[0].text.includes("review-pilot:finding"), false);
  const draft = byId(pending, "F001");
  assert.equal(draft.status, "draft");
  assert.equal(draft.outcome, "skip_match");
  assert.equal(draft.confirmRequired, false);
  assert.equal(draft.placement, "inline");

  const submitted = placement.scanPlacement([finding()], submittedFile, {});
  assert.equal(submitted.comments[0].region, "submitted");
  assert.equal(submitted.comments[0].unverified, false);
  assert.equal(submitted.comments[0].text.includes("review-pilot:finding"), false);
  const published = byId(submitted, "F001");
  assert.equal(published.status, "published");
  assert.equal(published.outcome, "skip_match");
  assert.equal(placement.collapseWhitespace(submitted.comments[0].text), SCAN_F001);
});

test("a different body is draft_modified or published_modified", () => {
  const pending = readFixture("pending-comment.html").replace(
    "This path permits an invalid state.",
    "Operator changed this sentence."
  );
  const submitted = readFixture("submitted-comment.html").replace(
    "This  path permits an invalid state.",
    "Operator changed this sentence."
  );
  const draft = byId(placement.scanPlacement([finding()], pending, {}), "F001");
  assert.equal(draft.status, "draft_modified");
  assert.equal(draft.outcome, "replace_draft");
  assert.equal(draft.confirmRequired, true);
  assert.equal(draft.target.region, "pending");

  const toggled = byId(
    placement.scanPlacement([finding()], pending, { replaceModifiedDrafts: true }),
    "F001"
  );
  assert.equal(toggled.outcome, "replace_draft");
  assert.equal(toggled.confirmRequired, false);

  const confirmed = byId(
    placement.scanPlacement([finding()], pending, { confirmedIds: ["F001"] }),
    "F001"
  );
  assert.equal(confirmed.confirmRequired, false);

  const published = byId(placement.scanPlacement([finding()], submitted, {}), "F001");
  assert.equal(published.status, "published_modified");
  assert.equal(published.outcome, "manual_only");
  assert.equal(published.confirmRequired, false);
  assert.equal(published.snapshotText, SCAN_F001);
  assert.match(published.observed, /Operator changed this sentence/);
});

test("a comment already on the line does not block the second finding", () => {
  const html = readFixture("occupied-line.html");
  const result = placement.scanPlacement(
    [
      finding(),
      finding({
        id: "F005",
        title: "Second finding",
        scan_text: SCAN_F005,
      }),
    ],
    html,
    {}
  );
  assert.equal(result.comments.length, 2);
  assert.equal(result.comments[0].line, 142);
  assert.equal(result.comments[1].line, 142);
  assert.equal(placement.markerIds(result.comments[0].text).includes("F005"), false);

  const first = byId(result, "F001");
  assert.equal(first.status, "published");
  assert.equal(first.outcome, "skip_match");

  const second = byId(result, "F005");
  assert.equal(second.status, "not_placed");
  assert.equal(second.outcome, "fill");
  assert.equal(second.placement, "inline");
  assert.equal(second.target, null);
});

test("off-diff rows stay not_placed when the summary was not persisted", () => {
  const html = readFixture("revisit-no-summary.html");
  const result = placement.scanPlacement(
    [
      finding({
        id: "F002",
        title: "Unrelated helper",
        path: "src/Example.cs",
        line: 10,
        on_diff: false,
        scan_text: SCAN_F002,
      }),
    ],
    html,
    {}
  );
  const row = byId(result, "F002");
  assert.equal(row.status, "not_placed");
  assert.equal(row.outcome, null);
  assert.equal(row.placement, "not-on-diff");
});

test("a summary segment matches as a draft and a missing segment can be filled", () => {
  const html = readFixture("summary-segment.html");
  assert.match(html, /Unverified against a live pending review/);
  const result = placement.scanPlacement(
    [
      finding({
        id: "F002",
        title: "Unrelated helper",
        path: "src/Example.cs",
        line: 10,
        on_diff: false,
        scan_text: SCAN_F002,
      }),
      finding({
        id: "F009",
        title: "Also off the diff",
        path: "",
        line: null,
        on_diff: false,
        scan_text: "Also off the diff. review-pilot finding F009",
      }),
    ],
    html,
    {}
  );
  assert.equal(result.comments[0].region, "summary");
  assert.equal(result.comments[0].unverified, true);
  const placed = byId(result, "F002");
  assert.equal(placed.status, "draft");
  assert.equal(placed.outcome, "skip_match");
  assert.equal(placed.placement, "not-on-diff");
  const missing = byId(result, "F009");
  assert.equal(missing.status, "not_placed");
  assert.equal(missing.outcome, "fill");
});

test("the visible marker is the scan key and a blocked flag is not a commit gate", () => {
  const hidden = placement.scanPlacement(
    [finding()],
    '<div data-review-pilot-comment="submitted"><!-- review-pilot finding F001 --><p>No visible marker.</p></div>',
    {}
  );
  assert.equal(byId(hidden, "F001").status, "not_placed");
  assert.equal(byId(hidden, "F001").outcome, "fill");
  assert.equal(hidden.comments[0].text.includes("review-pilot finding"), false);

  const prefix = placement.scanPlacement(
    [finding()],
    '<div data-review-pilot-comment="submitted"><p>review-pilot finding F0010</p></div>',
    {}
  );
  assert.equal(byId(prefix, "F001").outcome, "fill");

  const host = placement.scanPlacement(
    [finding()],
    '<div class="markdown-body"><p>' +
      SCAN_F001.replace(/</g, "&lt;") +
      "</p></div>",
    {}
  );
  assert.equal(host.comments[0].region, "submitted");
  assert.equal(host.comments[0].unverified, false);
  assert.equal(byId(host, "F001").outcome, "skip_match");

  const synthetic = placement.scanPlacement(
    [finding()],
    '<div class="pending-review-comment markdown-body"><p>' +
      SCAN_F001.replace(/</g, "&lt;") +
      "</p></div>",
    {}
  );
  assert.equal(synthetic.comments[0].unverified, true);
  assert.equal(byId(synthetic, "F001").status, "draft");

  const blocked = placement.scanPlacement([finding()], readFixture("submitted-comment.html"), {
    blocked: true,
  });
  assert.equal(byId(blocked, "F001").status, "blocked");
  assert.equal(byId(blocked, "F001").outcome, null);

  const source = fs.readFileSync(path.join(root, "lib", "placement.js"), "utf8");
  assert.equal(source.includes("All commits"), false);
  assert.equal(source.includes("Hide whitespace"), false);
  assert.equal(source.includes("Start a review"), false);
  assert.doesNotMatch(source, /\.click\s*\(/);
});

test("refresh scan reruns the read-only pass", () => {
  const rows = [finding()];
  const first = placement.refreshScan(rows, readFixture("submitted-comment.html"), {});
  const again = placement.refreshScan(rows, readFixture("submitted-comment.html"), {});
  assert.equal(again.findings[0].status, first.findings[0].status);
  assert.equal(again.readOnly, true);
  const edited = readFixture("submitted-comment.html").replace(
    "This  path permits an invalid state.",
    "Changed since the last scan."
  );
  const second = placement.refreshScan(rows, edited, {});
  assert.equal(first.findings[0].status, "published");
  assert.equal(second.findings[0].status, "published_modified");
  assert.equal(second.findings[0].outcome, "manual_only");
});

test("the sidebar lists id, title, path:line, inline or not on the current diff, and status", () => {
  const html = renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: {
        issue: "RP-1",
        pr: "acme/widgets#87",
        sha: "abc",
        findings: [
          finding(),
          finding({
            id: "F002",
            title: "Unrelated helper",
            path: "src/Example.cs",
            line: 10,
            on_diff: false,
            scan_text: SCAN_F002,
          }),
          finding({
            id: "F006",
            title: "Edited draft",
            scan_text: SCAN_F001,
          }),
        ],
      },
      placements: {
        F001: { status: "published", outcome: "skip_match" },
        F002: { status: "not_placed", outcome: null },
        F006: {
          status: "draft_modified",
          outcome: "replace_draft",
          confirmRequired: true,
        },
        F007: {
          status: "published_modified",
          outcome: "manual_only",
          confirmRequired: false,
          observed: "Observed body",
          snapshotText: "Snapshot body",
        },
      },
    })
  );
  assert.match(html, /<th>Id<\/th>/);
  assert.match(html, /<th>Title<\/th>/);
  assert.match(html, /<th>Path:line<\/th>/);
  assert.match(html, /<th>Placement<\/th>/);
  assert.match(html, /<th>Status<\/th>/);
  assert.match(html, /src\/Example\.cs:142/);
  assert.match(html, /data-diff-anchor="diff-[0-9a-f]{64}" data-on-diff="false"/);
  assert.doesNotMatch(html, /data-finding-line=/);
  assert.doesNotMatch(html, /data-diff-anchor="diff-[0-9a-f]{64}[RL]/);
  assert.match(html, /title="Go to file on this pull request"/);
  assert.doesNotMatch(html, /Go to line/);
  const f002Row = html.match(/<tr class="finding" data-finding-id="F002"[\s\S]*?<\/tr>/);
  assert.ok(f002Row);
  assert.match(f002Row[0], /data-diff-anchor="diff-[0-9a-f]{64}" data-on-diff="false"/);
  assert.doesNotMatch(f002Row[0], /data-diff-anchor="diff-[0-9a-f]{64}R/);
  assert.match(html, /data-fallback-href="https:\/\/github\.com\/acme\/widgets\/pull\/87\/changes/);
  assert.match(html, />inline</);
  assert.match(html, /not on the current diff/);
  assert.match(html, /published/);
  assert.match(html, /not_placed/);
  assert.match(html, /data-confirm-replace="F006"/);
  assert.match(html, /Confirm replace/);
  assert.equal(html.includes(SCAN_F001), false);

  const manual = renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: {
        issue: "RP-1",
        pr: "acme/widgets#87",
        sha: "abc",
        findings: [finding({ id: "F007", title: "Edited on GitHub" })],
      },
      placements: {
        F007: {
          status: "published_modified",
          outcome: "manual_only",
          observed: "Observed body",
          snapshotText: "Snapshot body",
        },
      },
    })
  );
  assert.match(manual, /Observed body/);
  assert.match(manual, /Snapshot body/);
  assert.match(manual, /manual_only/);
  assert.equal(manual.includes("Confirm replace"), false);

  const replaced = renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: {
        issue: "RP-1",
        pr: "acme/widgets#87",
        sha: "abc",
        findings: [finding({ id: "F006", title: "Edited draft" })],
      },
      placements: {
        F006: { status: "draft_modified", outcome: "replace_draft", confirmRequired: false },
      },
    })
  );
  assert.equal(replaced.includes("Confirm replace"), false);
  assert.match(replaced, /draft_modified/);
});

test("collectComments reads a DOM node without clicking", () => {
  function textNode(value) {
    return { nodeType: 3, nodeValue: value };
  }
  function element(tag, attrs, children) {
    return {
      nodeType: 1,
      tagName: tag.toUpperCase(),
      childNodes: children,
      getAttribute: function (name) {
        return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
      },
      contains: function (other) {
        return children.some(function (child) {
          return child === other || (child.contains && child.contains(other));
        });
      },
    };
  }
  const body = element("div", { class: "markdown-body", "data-review-pilot-comment": "submitted" }, [
    textNode(SCAN_F001),
  ]);
  const comments = placement.collectComments({
    querySelectorAll: function () {
      return [body];
    },
  });
  assert.equal(comments.length, 1);
  assert.equal(comments[0].region, "submitted");
  const scanned = placement.scanPlacement([finding()], comments, {});
  assert.equal(scanned.findings[0].outcome, "skip_match");
});

test("the panel wires refresh scan and does not prepare clicks", () => {
  const html = fs.readFileSync(path.join(root, "sidepanel", "panel.html"), "utf8");
  const panel = fs.readFileSync(path.join(root, "sidepanel", "panel.js"), "utf8");
  const content = fs.readFileSync(path.join(root, "content", "content-script.js"), "utf8");
  const worker = fs.readFileSync(path.join(root, "background", "service-worker.js"), "utf8");
  assert.match(html, /id="refresh-scan"/);
  assert.match(html, /Replace modified drafts/);
  assert.match(html, /id="replace-modified-drafts"/);
  assert.match(panel, /refresh-scan/);
  assert.match(panel, /rankPullTabs/);
  assert.match(panel, /confirm-replace-draft/);
  assert.match(panel, /replaceModifiedDrafts/);
  assert.match(content, /collect-scan/);
  assert.match(worker, /collect-scan/);
  for (const source of [panel, content, worker]) {
    assert.equal(source.includes("Start a review"), false);
    assert.doesNotMatch(source, /\.click\s*\(/);
  }
});
