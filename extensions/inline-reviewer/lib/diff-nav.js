(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotDiffNav = api;
})(globalThis, function () {
  "use strict";

  function isPullChangesPath(pathname) {
    const path = String(pathname == null ? "" : pathname);
    return /\/pull\/\d+\/(changes|files)\/?$/.test(path);
  }

  function navigateToAnchor(anchor, options) {
    const opts = options || {};
    const debugApi = globalThis.ReviewPilotDebug;
    if (!debugApi || typeof debugApi.navigateToLine !== "function") {
      return { ok: false, reason: "line_off_screen", readOnly: true };
    }
    return debugApi.navigateToLine({
      anchor: anchor,
      path: opts.path,
      line: opts.line,
      side: opts.side,
      on_diff: opts.on_diff,
      document: opts.document,
      location: opts.location,
    });
  }

  return {
    isPullChangesPath: isPullChangesPath,
    navigateToAnchor: navigateToAnchor,
  };
});
