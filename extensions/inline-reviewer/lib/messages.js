(function (root, factory) {
  "use strict";

  if (typeof module === "object" && module.exports && !root.ReviewPilotQuery) {
    require("./query-capture.js");
  }
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotMessages = api;
})(globalThis, function () {
  "use strict";

  function senderMayReadSettings(sender, extensionUrl) {
    if (!sender || !sender.url || sender.tab) return false;
    try {
      return new URL(sender.url).origin === new URL(extensionUrl).origin;
    } catch (err) {
      return false;
    }
  }

  function senderMayStoreCapture(sender) {
    if (!sender || !sender.tab || sender.tab.id == null) return false;
    if (!sender.url) return true;
    try {
      const url = new URL(sender.url);
      return url.protocol === "https:" && url.hostname === "github.com";
    } catch (err) {
      return false;
    }
  }

  function contentScriptMessage(captured) {
    return {
      type: "deep-link-captured",
      captured: globalThis.ReviewPilotQuery.sanitizeCapture(captured),
    };
  }

  return {
    senderMayReadSettings: senderMayReadSettings,
    senderMayStoreCapture: senderMayStoreCapture,
    contentScriptMessage: contentScriptMessage,
  };
});
