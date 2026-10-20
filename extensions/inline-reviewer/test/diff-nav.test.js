"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

require("../lib/debug.js");
const diffNav = require("../lib/diff-nav.js");

function element(attrs, rect, parent) {
  return {
    parentNode: parent || null,
    textContent: attrs["data-line-number"] || "",
    getAttribute: function (name) {
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
    getBoundingClientRect: function () {
      return rect;
    },
  };
}

function page(location, viewer, nodes) {
  return {
    location: location,
    document: {
      getElementById: function (id) {
        return id === "diff-comparison-viewer-container" ? viewer : null;
      },
      querySelector: function () {
        return null;
      },
      querySelectorAll: function (selector) {
        const text = String(selector);
        return nodes.filter(function (node) {
          if (text.indexOf("data-line-number") !== -1) return node.getAttribute("data-line-number") != null;
          if (text.indexOf("data-file-path") !== -1) return node.getAttribute("data-file-path") != null;
          return false;
        });
      },
    },
  };
}

test("on-diff navigation scrolls the file header and ignores the line number", () => {
  const location = {
    pathname: "/kwik-trip-iot/KT.IoT.UI.Admin/pull/354/changes",
    search: "",
    hash: "#diff-abcR126",
  };
  const viewer = {
    scrollTop: 400,
    clientHeight: 600,
    getBoundingClientRect: function () {
      return { top: 100, bottom: 700, left: 0, right: 800 };
    },
  };
  const file = element(
    { "data-file-path": "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs" },
    { top: 880, bottom: 1400, left: 0, right: 800 }
  );
  const built = page(location, viewer, [file]);
  let replaced = "";
  const priorHistory = globalThis.history;
  globalThis.history = {
    state: null,
    replaceState: function (_state, _title, url) {
      replaced = String(url);
      const hashIndex = replaced.indexOf("#");
      location.hash = hashIndex >= 0 ? replaced.slice(hashIndex) : "";
    },
  };
  try {
    const result = diffNav.navigateToAnchor("diff-abc", {
      location: built.location,
      document: built.document,
      path: "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs",
      line: "126",
      side: "RIGHT",
      on_diff: true,
    });
    assert.equal(result.ok, true);
    assert.equal(result.fileOnly, true);
    assert.equal(viewer.scrollTop, 1180);
    assert.equal(replaced, "/kwik-trip-iot/KT.IoT.UI.Admin/pull/354/changes");
    assert.equal(location.hash, "");
  } finally {
    globalThis.history = priorHistory;
  }
});

test("a second visit uses the current file position, not the previous scroll offset", () => {
  const location = {
    pathname: "/kwik-trip-iot/KT.IoT.UI.Admin/pull/354/changes",
    search: "?w=1",
    hash: "",
  };
  let fileTop = 500;
  const viewer = {
    scrollTop: 0,
    clientHeight: 600,
    getBoundingClientRect: function () {
      return { top: 0, bottom: 600, left: 0, right: 800 };
    },
  };
  const file = element(
    { "data-file-path": "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs" },
    { top: 0, bottom: 400, left: 0, right: 800 }
  );
  file.getBoundingClientRect = function () {
    return { top: fileTop, bottom: fileTop + 400, left: 0, right: 800 };
  };
  const built = page(location, viewer, [file]);
  const priorHistory = globalThis.history;
  globalThis.history = { state: null, replaceState: function () {} };
  try {
    const first = diffNav.navigateToAnchor("diff-abc", {
      location: location,
      document: built.document,
      path: "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs",
      line: "126",
      side: "RIGHT",
      on_diff: true,
    });
    assert.equal(first.ok, true);
    const afterFirst = viewer.scrollTop;
    fileTop = 40;
    viewer.scrollTop = 2500;
    const second = diffNav.navigateToAnchor("diff-abc", {
      location: location,
      document: built.document,
      path: "KT.IoT.UI.Admin/Helpers/ThingComboBoxReadExecutor.cs",
      line: "126",
      side: "RIGHT",
      on_diff: true,
    });
    assert.equal(second.ok, true);
    assert.equal(afterFirst, 500);
    assert.notEqual(viewer.scrollTop, 2500);
    assert.equal(viewer.scrollTop, 2540);
  } finally {
    globalThis.history = priorHistory;
  }
});

test("off-diff navigation scrolls the file to the top of the comparison viewer", () => {
  const location = {
    pathname: "/kwik-trip-iot/KT.IoT.UI.Admin/pull/354/changes",
    search: "",
    hash: "",
  };
  const viewer = {
    scrollTop: 120,
    clientHeight: 600,
    getBoundingClientRect: function () {
      return { top: 80, bottom: 680, left: 0, right: 800 };
    },
  };
  const file = element(
    { "data-file-path": "KT.IoT.UI.Admin.E2E.Tests/ThingComboBoxScrollTestHelpers.cs" },
    { top: 640, bottom: 900, left: 0, right: 800 }
  );
  const built = page(location, viewer, [file]);
  const priorHistory = globalThis.history;
  globalThis.history = { state: null, replaceState: function () {} };
  try {
    const result = diffNav.navigateToAnchor("diff-file", {
      location: location,
      document: built.document,
      path: "KT.IoT.UI.Admin.E2E.Tests/ThingComboBoxScrollTestHelpers.cs",
      line: "141",
      side: "RIGHT",
      on_diff: false,
    });
    assert.equal(result.ok, true);
    assert.equal(result.fileOnly, true);
    assert.equal(viewer.scrollTop, 680);
  } finally {
    globalThis.history = priorHistory;
  }
});

test("navigateToAnchor refuses off pull request diff pages", () => {
  const result = diffNav.navigateToAnchor("diff-abcR1", {
    location: { pathname: "/kwik-trip-iot/KT.IoT.UI.Admin/pull/354", hash: "" },
    document: {},
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, "wrong_page");
});
