"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { describeTab } = require("../lib/query-capture.js");
const { fetchSnapshotIfAllowlisted, planSnapshotRequest } = require("../lib/snapshot-request.js");
const { panelFromPlan, renderPanelHtml } = require("../lib/panel-model.js");

const TOKEN = "s3cret-token";

function countedFetch() {
  const calls = [];
  return {
    calls: calls,
    fetchImpl: async function (url, init) {
      calls.push({ url: url, init: init });
      return {
        ok: true,
        status: 200,
        json: async function () {
          return {
            issue: "RP-9",
            pr: "owner/repo#4",
            owner: "owner",
            repo: "repo",
            number: 4,
            sha: "reviewed-sha",
            findings: [
              {
                id: "f1",
                title: "Latch the relay",
                path: "src/app.py",
                line: 10,
                start_line: null,
                side: "RIGHT",
                on_diff: true,
                body: TOKEN,
                scan_text: TOKEN,
                token: TOKEN,
              },
              {
                id: "f2",
                title: "Missing limit",
                path: null,
                line: null,
                side: "RIGHT",
                on_diff: false,
                body: TOKEN,
                scan_text: TOKEN,
              },
            ],
            summary_block: TOKEN,
            token: TOKEN,
          };
        },
      };
    },
  };
}

async function load(href, settings, fetchImpl, stored) {
  const described = describeTab(stored || null, href);
  return fetchSnapshotIfAllowlisted({
    captured: described.captured,
    repo: described.repo,
    settings: settings,
    fetchImpl: fetchImpl,
  });
}

test("a non-matching repo does not call fetch", async () => {
  const seen = countedFetch();
  const href =
    "https://github.com/other/repo/pull/4/files?review_pilot_issue=RP-1&review_pilot_sha=abc";
  const result = await load(
    href,
    { allowlist: "owner/*", token: TOKEN, port: 8765 },
    seen.fetchImpl
  );
  assert.equal(seen.calls.length, 0);
  assert.equal(result.called, false);
  assert.equal(result.reason, "not-allowlisted");
  assert.equal(JSON.stringify(result).includes(TOKEN), false);
  const html = renderPanelHtml(panelFromPlan({ plan: result, snapshot: null }));
  assert.match(html, /data-state="idle"/);
  assert.match(html, /other\/repo is not on the allowlist/);
  assert.equal(html.includes(TOKEN), false);
  assert.equal(html.includes("Bearer"), false);
});

test("an empty allowlist does not call fetch", async () => {
  const seen = countedFetch();
  const result = await load(
    "https://github.com/owner/repo/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc",
    { allowlist: "", token: TOKEN, port: 8765 },
    seen.fetchImpl
  );
  assert.equal(seen.calls.length, 0);
  assert.equal(result.called, false);
  assert.equal(result.reason, "not-allowlisted");
  assert.equal(JSON.stringify(result).includes(TOKEN), false);
});

test("*/* is allowlisted and owner/* matches only that owner", async () => {
  const anyRepo = countedFetch();
  const anyResult = await load(
    "https://github.com/other/repo/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc",
    { allowlist: "*/*", token: TOKEN },
    anyRepo.fetchImpl
  );
  assert.equal(anyResult.ok, true);
  assert.equal(anyRepo.calls.length, 1);

  const oneOwner = countedFetch();
  const matched = await load(
    "https://github.com/owner/widget/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc",
    { allowlist: "owner/*", token: TOKEN, port: 8765 },
    oneOwner.fetchImpl
  );
  assert.equal(matched.ok, true);
  assert.equal(oneOwner.calls.length, 1);
  const missed = await load(
    "https://github.com/other/widget/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc",
    { allowlist: "owner/*", token: TOKEN, port: 8765 },
    oneOwner.fetchImpl
  );
  assert.equal(missed.called, false);
  assert.equal(oneOwner.calls.length, 1);
});

test("the service worker request uses 127.0.0.1 and a bearer header", async () => {
  const seen = countedFetch();
  const href =
    "https://github.com/owner/repo/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=from-link";
  const result = await load(href, { allowlist: "owner/*", token: TOKEN, port: "" }, seen.fetchImpl);
  assert.equal(seen.calls.length, 1);
  const url = new URL(seen.calls[0].url);
  assert.equal(url.protocol, "http:");
  assert.equal(url.hostname, "127.0.0.1");
  assert.equal(url.port, "8765");
  assert.equal(url.pathname, "/snapshot");
  assert.equal(url.searchParams.get("owner"), "owner");
  assert.equal(url.searchParams.get("repo"), "repo");
  assert.equal(url.searchParams.get("number"), "4");
  assert.equal(url.searchParams.get("sha"), "from-link");
  assert.equal(url.searchParams.get("token"), null);
  assert.equal(seen.calls[0].url.includes(TOKEN), false);
  assert.equal(seen.calls[0].url.includes("github.com"), false);
  assert.deepEqual(Object.keys(seen.calls[0].init.headers), ["Authorization"]);
  assert.equal(seen.calls[0].init.headers.Authorization, "Bearer " + TOKEN);
  assert.equal(seen.calls[0].init.method, "GET");
  assert.equal(seen.calls[0].init.credentials, "omit");
  assert.equal(seen.calls[0].init.redirect, "error");

  const html = renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: result.snapshot,
      token: TOKEN,
    })
  );
  assert.match(html, /data-state="snapshot"/);
  assert.match(html, /RP-9/);
  assert.match(html, /owner\/repo#4/);
  assert.match(html, /reviewed-sha/);
  assert.match(html, /Latch the relay/);
  assert.match(html, /Missing limit/);
  assert.match(html, /not on the current diff/);
  assert.equal(html.includes(TOKEN), false);
  assert.equal(html.includes("Bearer"), false);
  assert.equal(html.includes("from-link"), false);
});

test("a custom port is used and a refused plan has no bearer header", () => {
  const allowed = planSnapshotRequest({
    captured: {
      owner: "owner",
      repo: "repo",
      number: 4,
      view: "changes",
      issue: "RP-1",
      sha: "abc",
    },
    settings: { allowlist: "*/*", token: TOKEN, port: 9000 },
  });
  assert.equal(new URL(allowed.url).port, "9000");
  assert.equal(allowed.url.includes(TOKEN), false);

  const refused = planSnapshotRequest({
    captured: {
      owner: "other",
      repo: "repo",
      number: 4,
      view: "changes",
      issue: "RP-1",
      sha: "abc",
      token: TOKEN,
    },
    settings: { allowlist: "owner/*", token: TOKEN, port: 8765 },
  });
  assert.equal(refused.ok, false);
  assert.equal(refused.reason, "not-allowlisted");
  assert.equal(Object.hasOwn(refused, "headers"), false);
  assert.equal(JSON.stringify(refused).includes(TOKEN), false);
});

test("leaving Files changed does not call fetch", async () => {
  const seen = countedFetch();
  const stored = describeTab(
    null,
    "https://github.com/owner/repo/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc"
  ).captured;
  const result = await load(
    "https://github.com/owner/repo/pull/4",
    { allowlist: "*/*", token: TOKEN, port: 8765 },
    seen.fetchImpl,
    stored
  );
  assert.equal(seen.calls.length, 0);
  assert.equal(result.called, false);
  assert.equal(result.reason, "missing-pr");
});

test("a non-allowlisted GitHub page stays idle without a request", async () => {
  const seen = countedFetch();
  const result = await load(
    "https://github.com/other/repo",
    { allowlist: "owner/*", token: TOKEN, port: 8765 },
    seen.fetchImpl
  );
  assert.equal(seen.calls.length, 0);
  assert.equal(result.reason, "not-allowlisted");
  const html = renderPanelHtml(panelFromPlan({ plan: result }));
  assert.match(html, /data-state="idle"/);
  assert.equal(html.includes(TOKEN), false);
});

test("snapshot markup ignores a token planted on the model", () => {
  const html = renderPanelHtml({
    mode: "snapshot",
    issue: "RP-1",
    pr: "owner/repo#1",
    sha: "abc",
    findings: [],
    token: TOKEN,
  });
  assert.equal(html.includes(TOKEN), false);
  const escaped = renderPanelHtml(
    panelFromPlan({
      plan: { ok: true },
      snapshot: {
        issue: "RP-1",
        pr: "owner/repo#1",
        sha: "abc",
        findings: [{ id: "1", title: "<img src=x onerror=alert(1)>", path: "a.py", line: 2, side: "RIGHT", on_diff: true }],
      },
    })
  );
  assert.equal(escaped.includes("<img"), false);
  assert.match(escaped, /&lt;img/);
});
