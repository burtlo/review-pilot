"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  ISSUE_PARAM,
  SHA_PARAM,
  captureAtDocumentStart,
  describeTab,
  mergeCapture,
  pageUrl,
  rankPullTabs,
} = require("../lib/query-capture.js");
const { contentScriptMessage } = require("../lib/messages.js");

const SHA = "a".repeat(40);

test("deep-link query names are review_pilot_issue and review_pilot_sha", () => {
  assert.equal(ISSUE_PARAM, "review_pilot_issue");
  assert.equal(SHA_PARAM, "review_pilot_sha");
});

test("query params captured at document start remain after a script deletes them from location", () => {
  const location = new URL(
    "https://github.com/acme/widgets/pull/7/changes?review_pilot_issue=RP-1&review_pilot_sha=" + SHA
  );
  const captured = captureAtDocumentStart(location);

  function stripDeepLink(pageLocation) {
    pageLocation.searchParams.delete("review_pilot_issue");
    pageLocation.searchParams.delete("review_pilot_sha");
    pageLocation.searchParams.delete("review_pilot_finding");
  }

  stripDeepLink(location);
  assert.equal(location.search, "");
  assert.equal(captured.issue, "RP-1");
  assert.equal(captured.sha, SHA);
  assert.equal(captured.owner, "acme");
  assert.equal(captured.repo, "widgets");
  assert.equal(captured.number, 7);
  assert.equal(captured.view, "changes");
  assert.equal(Object.hasOwn(captured, "review_pilot_finding"), false);

  const described = describeTab(captured, location.href);
  assert.equal(described.captured.issue, "RP-1");
  assert.equal(described.captured.sha, SHA);
});

test("a replaced location href does not erase the document-start capture", () => {
  const sha = "b".repeat(40);
  const location = {
    href:
      "https://github.com/acme/widgets/pull/8/files?review_pilot_sha=" +
      sha +
      "&review_pilot_issue=RP-2&review_pilot_finding=f1",
  };
  const captured = captureAtDocumentStart(location);
  const stripped = new URL(location.href);
  stripped.search = "";
  location.href = stripped.href;

  assert.equal(new URL(location.href).search, "");
  assert.equal(captured.issue, "RP-2");
  assert.equal(captured.sha, sha);
  assert.equal(captured.view, "files");
  assert.equal(JSON.stringify(captured).includes("f1"), false);
  assert.equal(mergeCapture(captured, captureAtDocumentStart(location.href)).sha, sha);
});

test("a later pull request does not keep the previous sha", () => {
  const stored = captureAtDocumentStart(
    "https://github.com/owner/repo/pull/7/changes?review_pilot_issue=RP-1&review_pilot_sha=aaa"
  );
  const resolved = describeTab(stored, "https://github.com/owner/repo/pull/8/changes");
  assert.equal(resolved.captured.number, 8);
  assert.equal(resolved.captured.sha, "");
  assert.equal(resolved.captured.issue, "");
});

test("the capture is not written back onto a GitHub URL", () => {
  const token = "s3cret-token";
  const captured = captureAtDocumentStart(
    "https://github.com/acme/widgets/pull/7/changes?review_pilot_issue=RP-1&review_pilot_sha=" +
      SHA +
      "&token=" +
      token
  );
  assert.equal(JSON.stringify(captured).includes(token), false);
  const message = contentScriptMessage(Object.assign({ token: token }, captured));
  assert.equal(JSON.stringify(message).includes(token), false);
  assert.equal(JSON.stringify(message).includes("Bearer"), false);
  const url = pageUrl(Object.assign({ token: token }, captured));
  assert.equal(url, "https://github.com/acme/widgets/pull/7/changes");
  assert.equal(new URL(url).search, "");
  assert.equal(url.includes(token), false);
});

test("conversation and non-GitHub pages do not keep a files capture", () => {
  const stored = captureAtDocumentStart(
    "https://github.com/owner/repo/pull/4/changes?review_pilot_issue=RP-1&review_pilot_sha=abc"
  );
  assert.equal(describeTab(stored, "https://github.com/owner/repo/pull/4").captured, null);
  assert.deepEqual(describeTab(stored, "https://github.com/owner/repo/pull/4").repo, {
    owner: "owner",
    repo: "repo",
  });
  assert.equal(describeTab(stored, "https://example.com/owner/repo/pull/4/changes").captured, null);
  assert.equal(describeTab(stored, "https://example.com/owner/repo/pull/4/changes").repo, null);
});

test("rankPullTabs prefers the requested pull request tab over another window", () => {
  const changes = "https://github.com/kwik-trip-iot/KT.IoT.UI.Admin/pull/354/changes?review_pilot_sha=abc";
  const ranked = rankPullTabs(
    [
      { id: 1, active: true, focusedWindow: true, url: "https://github.com/kwik-trip-iot/KT.IoT.UI.Admin" },
      { id: 2, active: true, focusedWindow: false, url: changes },
      { id: 3, active: true, focusedWindow: true, url: "https://example.com/" },
    ],
    2
  );
  assert.equal(ranked.id, 2);
  const fallback = rankPullTabs(
    [
      { id: 4, active: false, focusedWindow: false, url: changes },
      { id: 5, active: true, focusedWindow: true, url: "chrome://extensions/" },
    ],
    5
  );
  assert.equal(fallback.id, 4);
});
