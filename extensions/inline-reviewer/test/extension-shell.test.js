"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const { senderMayReadSettings, senderMayStoreCapture } = require("../lib/messages.js");

const root = path.join(__dirname, "..");

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "test" || entry.name === "node_modules") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.name.endsWith(".js")) out.push(full);
  }
  return out;
}

function rel(file) {
  return path.relative(root, file).split(path.sep).join("/");
}

function filesMatching(pattern) {
  return walk(root)
    .filter(function (file) {
      return pattern.test(fs.readFileSync(file, "utf8"));
    })
    .map(rel)
    .sort();
}

test("manifest is one unpacked MV3 side panel", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.side_panel.default_path, "sidepanel/panel.html");
  assert.deepEqual(manifest.host_permissions, ["https://github.com/*", "http://127.0.0.1/*"]);
  assert.deepEqual(manifest.permissions, ["storage", "sidePanel"]);
  assert.equal(manifest.content_scripts.length, 1);
  const script = manifest.content_scripts[0];
  assert.equal(script.run_at, "document_start");
  assert.equal(script.all_frames, false);
  assert.notEqual(script.world, "MAIN");
  assert.deepEqual(script.js, [
    "lib/query-capture.js",
    "lib/placement.js",
    "lib/sha-gate.js",
    "lib/prepare.js",
    "lib/debug.js",
    "content/content-script.js",
  ]);
  assert.deepEqual(script.matches, [
    "https://github.com/*/*/pull/*/changes",
    "https://github.com/*/*/pull/*/changes/",
    "https://github.com/*/*/pull/*/files",
    "https://github.com/*/*/pull/*/files/",
  ]);
  assert.equal(JSON.stringify(manifest).includes("Bearer"), false);
  assert.equal(manifest.background.service_worker, "background/service-worker.js");
  assert.equal(manifest.background.type, undefined);
});

test("the service worker is the only bridge caller", () => {
  assert.deepEqual(filesMatching(/\bfetch\b/), [
    "background/service-worker.js",
    "lib/snapshot-request.js",
  ]);
  assert.deepEqual(filesMatching(/\bAuthorization\b/), ["lib/snapshot-request.js"]);
  assert.deepEqual(filesMatching(/\bBearer\b/), ["lib/snapshot-request.js"]);
  assert.deepEqual(filesMatching(/127\.0\.0\.1/), ["lib/snapshot-request.js"]);

  const definition = /function\s+fetchSnapshotIfAllowlisted\b/g;
  const call = /\bfetchSnapshotIfAllowlisted\s*\(/;
  const callers = walk(root)
    .filter(function (file) {
      const source = fs.readFileSync(file, "utf8").replace(definition, "");
      return call.test(source);
    })
    .map(rel)
    .sort();
  assert.deepEqual(callers, ["background/service-worker.js"]);

  const worker = fs.readFileSync(path.join(root, "background", "service-worker.js"), "utf8");
  assert.match(worker, /senderMayReadSettings/);
  assert.match(worker, /fetchImpl:\s*fetch/);
});

test("the content script does not touch the page DOM or the bridge", () => {
  const content = fs.readFileSync(path.join(root, "content", "content-script.js"), "utf8");
  assert.equal((content.match(/captureAtDocumentStart/g) || []).length, 1);
  assert.doesNotMatch(content, /\bdocument\b/);
  assert.doesNotMatch(content, /\bchrome\.storage\b/);
  assert.doesNotMatch(content, /\binnerHTML\b/);
  assert.doesNotMatch(content, /location\s*\.\s*(href|search)\s*=/);
  assert.doesNotMatch(content, /\b(fetch|Authorization|Bearer)\b/);
  assert.doesNotMatch(content, /127\.0\.0\.1/);
});

test("settings stay in the extension page and out of a GitHub sender", () => {
  const extensionUrl = "chrome-extension://abc/";
  assert.equal(
    senderMayReadSettings(
      { url: "chrome-extension://abc/sidepanel/panel.html" },
      extensionUrl
    ),
    true
  );
  assert.equal(
    senderMayReadSettings(
      {
        tab: { id: 7 },
        url: "https://github.com/acme/widgets/pull/7/changes?review_pilot_issue=RP-1&review_pilot_sha=abc",
      },
      extensionUrl
    ),
    false
  );
  assert.equal(
    senderMayStoreCapture({
      tab: { id: 7 },
      url: "https://github.com/acme/widgets/pull/7/changes?review_pilot_issue=RP-1",
    }),
    true
  );
  assert.equal(senderMayStoreCapture({ tab: { id: 7 } }), true);
  assert.equal(
    senderMayStoreCapture({ tab: { id: 7 }, url: "https://evil.example/pull/1/changes" }),
    false
  );
  assert.equal(
    senderMayStoreCapture({ url: "chrome-extension://abc/sidepanel/panel.html" }),
    false
  );

  const html = fs.readFileSync(path.join(root, "sidepanel", "panel.html"), "utf8");
  assert.doesNotMatch(html, /<form\b/i);
  assert.doesNotMatch(html, /\son[a-z]+=/i);
  assert.match(html, /type="password"/);
  assert.match(html, /id="allowlist"/);
  assert.match(html, /id="port"/);
  assert.match(html, /value="8765"/);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)/i);
  assert.equal(html.includes("s3cret"), false);
});
