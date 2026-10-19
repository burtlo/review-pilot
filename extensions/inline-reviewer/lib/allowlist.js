(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotAllowlist = api;
})(globalThis, function () {
  "use strict";

  function escapeRegExp(value) {
    return value.replace(/[\\^$+?.()|[\]{}]/g, "\\$&");
  }

  function allowlistPatterns(text) {
    if (typeof text !== "string") return [];
    return text
      .split(/\r?\n/)
      .map(function (line) {
        return line.trim();
      })
      .filter(function (line) {
        return line.length > 0;
      });
  }

  function segmentMatches(pattern, value) {
    if (typeof pattern !== "string" || typeof value !== "string") return false;
    if (!pattern || !value || value.includes("/")) return false;
    const expression = "^" + pattern.split("*").map(escapeRegExp).join("[^/]*") + "$";
    return new RegExp(expression, "i").test(value);
  }

  function patternMatches(pattern, owner, repo) {
    const parts = String(pattern)
      .split("/")
      .map(function (part) {
        return part.trim();
      });
    if (parts.length !== 2) return false;
    return segmentMatches(parts[0], owner) && segmentMatches(parts[1], repo);
  }

  function matchesAllowlist(allowlist, owner, repo) {
    const patterns = allowlistPatterns(allowlist);
    if (patterns.length === 0) return false;
    return patterns.some(function (pattern) {
      return patternMatches(pattern, owner, repo);
    });
  }

  return {
    allowlistPatterns: allowlistPatterns,
    matchesAllowlist: matchesAllowlist,
  };
});
