"use strict";

importScripts(
  "../lib/allowlist.js",
  "../lib/query-capture.js",
  "../lib/snapshot-request.js",
  "../lib/placement.js",
  "../lib/sha-gate.js",
  "../lib/panel-model.js",
  "../lib/messages.js",
  "../lib/debug.js"
);

const SETTINGS_KEY = "settings";
const confirmedByTab = new Map();

function captureKey(tabId) {
  return "capture:" + tabId;
}

function configureSidePanel() {
  if (!chrome.sidePanel) return;
  if (chrome.sidePanel.setOptions) {
    Promise.resolve(
      chrome.sidePanel.setOptions({
        path: "sidepanel/panel.html",
        enabled: true,
      })
    ).catch(function () {});
  }
  if (chrome.sidePanel.setPanelBehavior) {
    Promise.resolve(
      chrome.sidePanel.setPanelBehavior({
        openPanelOnActionClick: true,
      })
    ).catch(function () {});
  }
}

configureSidePanel();
chrome.runtime.onInstalled.addListener(configureSidePanel);
chrome.runtime.onStartup.addListener(configureSidePanel);

function extensionSenderUrl() {
  return chrome.runtime.getURL("/");
}

async function readSettings() {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  return ReviewPilotSnapshot.normalizeSettings(stored[SETTINGS_KEY]);
}

async function readCapture(tabId) {
  const key = captureKey(tabId);
  const stored = await chrome.storage.session.get(key);
  return stored[key] || null;
}

async function writeCapture(tabId, incoming) {
  const key = captureKey(tabId);
  const stored = await chrome.storage.session.get(key);
  const merged = ReviewPilotQuery.mergeCapture(stored[key], incoming);
  if (!merged) {
    await chrome.storage.session.remove(key);
    return null;
  }
  await chrome.storage.session.set({ [key]: merged });
  return merged;
}

function confirmedSet(tabId) {
  let bag = confirmedByTab.get(tabId);
  if (!bag) {
    bag = new Set();
    confirmedByTab.set(tabId, bag);
  }
  return bag;
}

function replaceModifiedDrafts(scanOptions, settings) {
  if (scanOptions && typeof scanOptions.replaceModifiedDrafts === "boolean") {
    return scanOptions.replaceModifiedDrafts;
  }
  return settings.replaceModifiedDrafts === true;
}

let packagedSelectors = null;

function loadPackagedSelectors() {
  if (!packagedSelectors) {
    packagedSelectors = fetch(chrome.runtime.getURL("selectors.json")).then(function (response) {
      if (!response || !response.ok) throw new Error("selectors");
      return response.json();
    });
    packagedSelectors.then(
      function () {},
      function () {
        packagedSelectors = null;
      }
    );
  }
  return packagedSelectors;
}

async function readSelectorOverrides() {
  try {
    const stored = await chrome.storage.local.get(ReviewPilotDebug.STORAGE_KEY);
    return ReviewPilotDebug.readOverrides(stored);
  } catch (err) {
    return {};
  }
}

async function loadSelectors() {
  const defaults = await loadPackagedSelectors();
  if (!globalThis.ReviewPilotDebug) return defaults;
  return ReviewPilotDebug.mergeSelectors(defaults, await readSelectorOverrides());
}

async function registryState() {
  try {
    const defaults = await loadPackagedSelectors();
    const overrides = await readSelectorOverrides();
    return {
      ids: Object.keys(defaults || {}),
      overrides: overrides,
    };
  } catch (err) {
    return { ids: [], overrides: {} };
  }
}

function requestRangeReading(tabId, selectors) {
  return new Promise(function (resolve) {
    try {
      chrome.tabs.sendMessage(
        tabId,
        {
          type: "read-range-gate",
          selectors: selectors,
          timeoutMs: ReviewPilotShaGate.HYDRATION_TIMEOUT_MS,
        },
        function (response) {
          if (chrome.runtime.lastError || !response) {
            resolve(null);
            return;
          }
          resolve(response.reading || null);
        }
      );
    } catch (err) {
      resolve(null);
    }
  });
}

async function readGateForSnapshot(tabId, context) {
  let selectors = null;
  if (Number.isInteger(tabId)) {
    try {
      selectors = await loadSelectors();
    } catch (err) {
      selectors = null;
    }
  }
  let reading = null;
  if (selectors) reading = await requestRangeReading(tabId, selectors);
  return ReviewPilotShaGate.evaluate(reading, context);
}

function requestPagePrepare(tabId, payload) {
  return new Promise(function (resolve) {
    try {
      chrome.tabs.sendMessage(tabId, payload, function (response) {
        if (chrome.runtime.lastError || !response) {
          resolve(null);
          return;
        }
        resolve(response);
      });
    } catch (err) {
      resolve(null);
    }
  });
}

async function prepareForTab(tabId, message) {
  const incoming = message && typeof message === "object" ? message : {};
  const scanOptions = {};
  if (typeof incoming.replaceModifiedDrafts === "boolean") {
    scanOptions.replaceModifiedDrafts = incoming.replaceModifiedDrafts;
  }
  const state = await panelState(tabId, scanOptions);
  const panel = state && state.panel;
  const gate = panel && panel.gate;
  if (ReviewPilotShaGate.blocksPrepare(gate)) {
    return Object.assign(ReviewPilotShaGate.prepare(gate), {
      ok: true,
      panel: panel || null,
      settings: state && state.settings,
    });
  }
  const snapshot = state && state.snapshot;
  let selectors = null;
  try {
    selectors = await loadSelectors();
  } catch (err) {
    selectors = null;
  }
  if (!Number.isInteger(tabId) || !selectors || !snapshot) {
    const failed = ReviewPilotShaGate.prepare(gate);
    failed.log = ["DOM failure. Prepare could not reach the page."];
    failed.status = "blocked";
    return Object.assign(failed, {
      ok: true,
      panel: panel || null,
      settings: state && state.settings,
    });
  }
  const dryRun = incoming.dryRun === true;
  let findings = snapshot.findings || [];
  let mode = incoming.mode === "all" ? "all" : "finding";
  let findingId = incoming.findingId == null ? "" : String(incoming.findingId);
  if (dryRun && !findingId && incoming.path) {
    const lineText = String(incoming.line == null ? "" : incoming.line).trim();
    const startText = String(incoming.startLine == null ? "" : incoming.startLine).trim();
    const synthetic = {
      id: "dry-run",
      title: "Dry-run",
      path: String(incoming.path),
      line: /^[0-9]+$/.test(lineText) ? Number(lineText) : null,
      side: incoming.side || "RIGHT",
      on_diff: true,
      body: "",
    };
    if (/^[0-9]+$/.test(startText)) synthetic.start_line = Number(startText);
    findings = [synthetic];
    mode = "finding";
    findingId = "dry-run";
  }
  const pageResult = await requestPagePrepare(tabId, {
    type: dryRun ? "dry-run" : "prepare",
    selectors: selectors,
    timeoutMs: ReviewPilotShaGate.HYDRATION_TIMEOUT_MS,
    expectedSha: snapshot.sha,
    issue: snapshot.issue,
    pr: snapshot.pr,
    findings: findings,
    mode: mode,
    findingId: findingId,
    summaryBlock: snapshot.summary_block || "",
    replaceModifiedDrafts: replaceModifiedDrafts(scanOptions, {
      replaceModifiedDrafts: state.settings && state.settings.replaceModifiedDrafts === true,
    }),
    confirmedIds: Array.from(confirmedSet(tabId)),
    dryRun: dryRun,
  });
  const after = await panelState(tabId, scanOptions);
  const view = ReviewPilotPanel.applyPrepareResult(after && after.panel ? after.panel : panel, pageResult || {
    status: "blocked",
    acted: false,
    readOnly: true,
    log: ["DOM failure. Prepare could not reach the page."],
    findings: [],
  });
  return Object.assign({}, pageResult || {
    status: "blocked",
    acted: false,
    readOnly: true,
    log: view.activity || [],
    inserts: 0,
    findings: [],
  }, {
    ok: true,
    panel: view,
    settings: after && after.settings,
    registry: after && after.registry,
  });
}

async function probeForTab(tabId, message) {
  const incoming = message && typeof message === "object" ? message : {};
  let selectors = null;
  try {
    selectors = await loadSelectors();
  } catch (err) {
    selectors = null;
  }
  const state = await panelState(tabId, {});
  if (!Number.isInteger(tabId) || !selectors) {
    return {
      ok: false,
      status: "failed",
      reason: "line_off_screen",
      log: ["Probe could not reach the page."],
      panel: state && state.panel,
      settings: state && state.settings,
      registry: state && state.registry,
    };
  }
  const pageResult = await requestPagePrepare(tabId, {
    type: "probe",
    selectors: selectors,
    path: incoming.path,
    line: incoming.line,
    startLine: incoming.startLine,
    side: incoming.side,
  });
  const after = await panelState(tabId, {});
  const view = ReviewPilotPanel.applyPrepareResult(
    after && after.panel ? after.panel : state && state.panel,
    pageResult || { log: ["Probe could not reach the page."] }
  );
  return {
    ok: Boolean(pageResult),
    status: pageResult && pageResult.status,
    reason: pageResult && pageResult.reason,
    log: (pageResult && pageResult.log) || [],
    panel: view,
    settings: after && after.settings,
    registry: after && after.registry,
  };
}

async function pickForTab(tabId, selectorId) {
  let defaults = null;
  try {
    defaults = await loadPackagedSelectors();
  } catch (err) {
    defaults = null;
  }
  const id = typeof selectorId === "string" ? selectorId.trim() : "";
  if (!Number.isInteger(tabId) || !defaults || !Object.prototype.hasOwnProperty.call(defaults, id)) {
    return { ok: false };
  }
  const picked = await requestPagePrepare(tabId, { type: "arm-picker", selectorId: id });
  if (!picked || typeof picked.query !== "string" || !picked.query.trim()) return { ok: false };
  const overrides = ReviewPilotDebug.writeOverride(await readSelectorOverrides(), id, picked.query);
  await chrome.storage.local.set({ [ReviewPilotDebug.STORAGE_KEY]: overrides });
  const merged = ReviewPilotDebug.mergeSelectors(defaults, overrides);
  return {
    ok: merged[id] === picked.query.trim(),
    selectorId: id,
    query: picked.query.trim(),
    resolved: merged[id],
    registry: await registryState(),
  };
}

async function clearSelectorOverrides() {
  await chrome.storage.local.remove(ReviewPilotDebug.STORAGE_KEY);
  return { ok: true, registry: await registryState() };
}

function collectFromTab(tabId) {
  return new Promise(function (resolve) {
    try {
      chrome.tabs.sendMessage(tabId, { type: "collect-scan" }, function (response) {
        if (chrome.runtime.lastError || !response || !Array.isArray(response.comments)) {
          resolve([]);
          return;
        }
        resolve(response.comments);
      });
    } catch (err) {
      resolve([]);
    }
  });
}

async function panelState(tabId, scanOptions) {
  const settings = await readSettings();
  const options = scanOptions || {};
  let liveUrl = "";
  if (Number.isInteger(tabId)) {
    try {
      const tab = await chrome.tabs.get(tabId);
      liveUrl = tab.url || "";
    } catch (err) {
      liveUrl = "";
    }
  }
  const stored = Number.isInteger(tabId) ? await readCapture(tabId) : null;
  const described = ReviewPilotQuery.describeTab(stored, liveUrl);
  const result = await ReviewPilotSnapshot.fetchSnapshotIfAllowlisted({
    captured: described.captured,
    repo: described.repo,
    settings: settings,
    fetchImpl: fetch,
  });
  const plan = result.ok
    ? { ok: true }
    : {
        ok: false,
        reason: result.reason,
        status: result.status,
        owner: result.owner,
        repo: result.repo,
      };
  let gate = null;
  if (result.ok && result.snapshot) {
    gate = await readGateForSnapshot(tabId, {
      expectedSha: result.snapshot.sha,
      issue: result.snapshot.issue,
      pr: result.snapshot.pr,
    });
  }
  let placements = {};
  if (result.ok && result.snapshot && Array.isArray(result.snapshot.findings) && Number.isInteger(tabId)) {
    const comments = await collectFromTab(tabId);
    const scanned = ReviewPilotPlacement.scanPlacement(result.snapshot.findings, comments, {
      replaceModifiedDrafts: replaceModifiedDrafts(options, settings),
      confirmedIds: confirmedSet(tabId),
      blocked: ReviewPilotShaGate.scanBlocked(gate, options.blocked === true),
    });
    placements = ReviewPilotPlacement.placementMap(scanned.findings);
  }
  return {
    ok: true,
    panel: ReviewPilotPanel.panelFromPlan({
      captured: described.captured,
      plan: plan,
      snapshot: result.snapshot || null,
      placements: placements,
      gate: gate,
    }),
    settings: {
      token: settings.token,
      allowlist: settings.allowlist,
      port: settings.port == null ? "" : String(settings.port),
      replaceModifiedDrafts: settings.replaceModifiedDrafts === true,
    },
    snapshot: result.snapshot || null,
    registry: await registryState(),
  };
}

async function saveSettings(raw) {
  const settings = ReviewPilotSnapshot.normalizeSettings(raw);
  if (settings.port == null) return { ok: false, reason: "bad-port" };
  await chrome.storage.local.set({ [SETTINGS_KEY]: settings });
  return { ok: true };
}

function integerTabId(value) {
  return Number.isInteger(value) && value >= 0 ? value : null;
}

chrome.tabs.onRemoved.addListener(function (tabId) {
  chrome.storage.session.remove(captureKey(tabId));
  confirmedByTab.delete(tabId);
});

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  if (!message || typeof message !== "object") return;
  const type = message.type;
  if (type === "deep-link-captured") {
    if (!ReviewPilotMessages.senderMayStoreCapture(sender)) {
      sendResponse({ ok: false });
      return;
    }
    writeCapture(sender.tab.id, message.captured).then(
      function () {
        sendResponse({ ok: true });
      },
      function () {
        sendResponse({ ok: false });
      }
    );
    return true;
  }
  if (!ReviewPilotMessages.senderMayReadSettings(sender, extensionSenderUrl())) {
    sendResponse({ ok: false });
    return;
  }
  if (type === "remember-capture") {
    const tabId = integerTabId(message.tabId);
    if (tabId == null) {
      sendResponse({ ok: false });
      return;
    }
    writeCapture(tabId, message.captured).then(
      function () {
        sendResponse({ ok: true });
      },
      function () {
        sendResponse({ ok: false });
      }
    );
    return true;
  }
  if (type === "save-settings") {
    saveSettings(message.settings).then(sendResponse, function () {
      sendResponse({ ok: false });
    });
    return true;
  }
  if (type === "prepare" || type === "dry-run") {
    prepareForTab(
      integerTabId(message.tabId),
      Object.assign({}, message, { dryRun: type === "dry-run" || message.dryRun === true })
    ).then(sendResponse, function () {
      sendResponse(ReviewPilotShaGate.prepare(null));
    });
    return true;
  }
  if (type === "probe") {
    probeForTab(integerTabId(message.tabId), message).then(sendResponse, function () {
      sendResponse({ ok: false, status: "failed", reason: "line_off_screen", log: [] });
    });
    return true;
  }
  if (type === "pick-selector") {
    pickForTab(integerTabId(message.tabId), message.selectorId).then(sendResponse, function () {
      sendResponse({ ok: false });
    });
    return true;
  }
  if (type === "clear-selector-overrides") {
    clearSelectorOverrides().then(sendResponse, function () {
      sendResponse({ ok: false });
    });
    return true;
  }
  if (type === "get-panel-state" || type === "refresh-scan" || type === "confirm-replace-draft") {
    const tabId = integerTabId(message.tabId);
    if (type === "confirm-replace-draft") {
      const findingId = message.findingId == null ? "" : String(message.findingId);
      if (tabId == null || !findingId) {
        sendResponse({ ok: false });
        return;
      }
      confirmedSet(tabId).add(findingId);
    }
    const scanOptions = { blocked: message.blocked === true };
    if (typeof message.replaceModifiedDrafts === "boolean") {
      scanOptions.replaceModifiedDrafts = message.replaceModifiedDrafts;
    }
    panelState(tabId, scanOptions).then(sendResponse, function () {
      sendResponse({ ok: false });
    });
    return true;
  }
  sendResponse({ ok: false });
});
