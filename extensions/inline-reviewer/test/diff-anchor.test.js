"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const anchor = require("../lib/diff-anchor.js");

test("off-diff findings link to the file anchor without a line suffix", () => {
  const finding = {
    path: "KT.IoT.UI.Admin.E2E.Tests/ThingComboBoxScrollTestHelpers.cs",
    line: 141,
    side: "RIGHT",
    on_diff: false,
  };
  const id = anchor.lineAnchorId(finding);
  assert.match(id, /^diff-[0-9a-f]{64}$/);
  assert.equal(id.indexOf("R141"), -1);
});

test("on-diff findings link to the file anchor without a line suffix", () => {
  const finding = {
    path: "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs",
    line: 126,
    side: "RIGHT",
    on_diff: true,
  };
  const id = anchor.lineAnchorId(finding);
  assert.match(id, /^diff-[0-9a-f]{64}$/);
  assert.equal(id.indexOf("R126"), -1);
});
