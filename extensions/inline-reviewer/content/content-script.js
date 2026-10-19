"use strict";

(function () {
  const captured = globalThis.ReviewPilotQuery.captureAtDocumentStart(location);

  chrome.runtime.sendMessage(
    {
      type: "deep-link-captured",
      captured: captured,
    },
    function () {
      if (chrome.runtime.lastError) return;
    }
  );

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || typeof message.type !== "string") return;
    if (message.type === "report-capture") {
      sendResponse({ captured: captured });
      return;
    }
    if (message.type === "collect-scan" && globalThis.ReviewPilotPlacement) {
      sendResponse({
        comments: globalThis.ReviewPilotPlacement.collectComments(),
        readOnly: true,
      });
      return;
    }
    if (message.type === "probe" && globalThis.ReviewPilotDebug) {
      Promise.resolve(globalThis.ReviewPilotDebug.probe(message)).then(sendResponse, function () {
        sendResponse({ status: "failed", reason: "line_off_screen", log: [], readOnly: true, acted: false });
      });
      return true;
    }
    if (message.type === "arm-picker" && globalThis.ReviewPilotDebug) {
      globalThis.ReviewPilotDebug.armPicker({ selectorId: message.selectorId }).then(sendResponse, function () {
        sendResponse({ ok: false, selectorId: message.selectorId || "", query: "" });
      });
      return true;
    }
    if (
      (message.type === "read-range-gate" || message.type === "prepare" || message.type === "dry-run") &&
      globalThis.ReviewPilotShaGate
    ) {
      const gateApi = globalThis.ReviewPilotShaGate;
      gateApi.observePage(message).then(
        function (reading) {
          if (message.type === "read-range-gate") {
            sendResponse({ reading: reading, readOnly: true });
            return;
          }
          const gate = gateApi.evaluate(reading, {
            expectedSha: message.expectedSha,
            issue: message.issue,
            pr: message.pr,
          });
          Promise.resolve(
            gateApi.prepare(gate, {
              selectors: message.selectors,
              findings: message.findings,
              mode: message.mode,
              findingId: message.findingId,
              summaryBlock: message.summaryBlock,
              replaceModifiedDrafts: message.replaceModifiedDrafts,
              confirmedIds: message.confirmedIds,
              dryRun: message.type === "dry-run" || message.dryRun === true,
            })
          ).then(sendResponse, function () {
            sendResponse(gateApi.prepare(null));
          });
        },
        function () {
          if (message.type === "read-range-gate") {
            sendResponse({ reading: null, readOnly: true });
            return;
          }
          sendResponse(gateApi.prepare(null));
        }
      );
      return true;
    }
  });
})();
