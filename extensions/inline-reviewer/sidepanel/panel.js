"use strict";

(function () {
  const statusEl = document.getElementById("status");
  const tokenEl = document.getElementById("token");
  const allowlistEl = document.getElementById("allowlist");
  const portEl = document.getElementById("port");
  const replaceEl = document.getElementById("replace-modified-drafts");
  const saveStatus = document.getElementById("save-status");
  const debugStatus = document.getElementById("debug-status");
  const overrideCount = document.getElementById("override-count");
  const selectorEntry = document.getElementById("selector-entry");
  let sawSettings = false;
  let debugLog = [];

  function activeTab() {
    return chrome.windows.getAll({ populate: true, windowTypes: ["normal"] }).then(function (windows) {
      const tabs = [];
      (windows || []).forEach(function (win) {
        (win.tabs || []).forEach(function (tab) {
          tabs.push(Object.assign({}, tab, { focusedWindow: win.focused === true }));
        });
      });
      const ranked = globalThis.ReviewPilotQuery && ReviewPilotQuery.rankPullTabs(tabs, null);
      if (ranked) return ranked;
      return chrome.tabs.query({ active: true, lastFocusedWindow: true }).then(function (fallback) {
        return fallback[0] || null;
      });
    });
  }

  function send(message) {
    return chrome.runtime.sendMessage(message);
  }

  function reportFromTab(tabId) {
    return new Promise(function (resolve) {
      chrome.tabs.sendMessage(tabId, { type: "report-capture" }, function (response) {
        if (chrome.runtime.lastError || !response) {
          resolve(null);
          return;
        }
        resolve(response.captured || null);
      });
    });
  }

  function showPanel(panel) {
    statusEl.innerHTML = ReviewPilotPanel.renderPanelHtml(
      panel || {
        mode: "blocked",
        message: "Open a GitHub pull request Files changed page.",
      }
    );
  }

  function fillSettings(settings) {
    if (!settings) return;
    if (document.activeElement !== tokenEl) {
      tokenEl.value = typeof settings.token === "string" ? settings.token : "";
    }
    if (document.activeElement !== allowlistEl) {
      allowlistEl.value = typeof settings.allowlist === "string" ? settings.allowlist : "";
    }
    if (document.activeElement !== portEl) {
      portEl.value = settings.port == null || settings.port === "" ? "8765" : String(settings.port);
    }
    if (!sawSettings || document.activeElement !== replaceEl) {
      replaceEl.checked = settings.replaceModifiedDrafts === true;
    }
    sawSettings = true;
  }

  function fillRegistry(registry) {
    if (!registry || !selectorEntry || document.activeElement === selectorEntry) return;
    const ids = Array.isArray(registry.ids) ? registry.ids : [];
    const current = selectorEntry.value;
    while (selectorEntry.firstChild) selectorEntry.removeChild(selectorEntry.firstChild);
    for (let i = 0; i < ids.length; i += 1) {
      const option = document.createElement("option");
      option.value = ids[i];
      option.textContent = ids[i];
      selectorEntry.appendChild(option);
    }
    if (current && ids.indexOf(current) !== -1) selectorEntry.value = current;
    const overrides = registry.overrides && typeof registry.overrides === "object" ? registry.overrides : {};
    const count = Object.keys(overrides).length;
    if (overrideCount) {
      overrideCount.textContent = count
        ? count + " selector override" + (count === 1 ? "" : "s") + " stored. Clear them to use packaged defaults."
        : "No selector overrides stored. Packaged defaults are in use.";
    }
  }

  function rememberLog(state) {
    if (state && Array.isArray(state.log)) debugLog = state.log.slice();
  }

  function showState(state) {
    if (!state) return false;
    if (state.settings) fillSettings(state.settings);
    if (state.registry) fillRegistry(state.registry);
    if (state.panel) showPanel(state.panel);
    rememberLog(state);
    return Boolean(state.panel);
  }

  function scanFields() {
    if (!sawSettings) return {};
    return { replaceModifiedDrafts: replaceEl.checked };
  }

  function currentSettings() {
    return {
      token: tokenEl.value,
      allowlist: allowlistEl.value,
      port: portEl.value,
      replaceModifiedDrafts: replaceEl.checked,
    };
  }

  async function refresh() {
    const tab = await activeTab();
    if (tab && tab.id != null) {
      const captured = await reportFromTab(tab.id);
      if (captured) {
        await send({ type: "remember-capture", tabId: tab.id, captured: captured });
      }
      const state = await send(
        Object.assign({ type: "get-panel-state", tabId: tab.id }, scanFields())
      );
      if (state && state.ok) {
        showState(state);
        return;
      }
    }
    const state = await send(Object.assign({ type: "get-panel-state", tabId: null }, scanFields()));
    if (state && state.ok) {
      showState(state);
      return;
    }
    showPanel({
      mode: "blocked",
      message: "Open a GitHub pull request Files changed page.",
    });
  }

  document.getElementById("reload").addEventListener("click", function () {
    saveStatus.textContent = "";
    refresh();
  });

  document.getElementById("refresh-scan").addEventListener("click", async function () {
    saveStatus.textContent = "";
    const tab = await activeTab();
    if (tab && tab.id != null) {
      const captured = await reportFromTab(tab.id);
      if (captured) {
        await send({ type: "remember-capture", tabId: tab.id, captured: captured });
      }
    }
    const state = await send(
      Object.assign(
        { type: "refresh-scan", tabId: tab && tab.id != null ? tab.id : null },
        scanFields()
      )
    );
    if (state && state.ok) showState(state);
  });

  replaceEl.addEventListener("change", async function () {
    await send({ type: "save-settings", settings: currentSettings() });
    refresh();
  });

  async function runPrepare(fields) {
    saveStatus.textContent = "";
    const tab = await activeTab();
    if (tab && tab.id != null) {
      const captured = await reportFromTab(tab.id);
      if (captured) {
        await send({ type: "remember-capture", tabId: tab.id, captured: captured });
      }
    }
    const state = await send(
      Object.assign(
        {
          type: "prepare",
          tabId: tab && tab.id != null ? tab.id : null,
        },
        fields || {},
        scanFields()
      )
    );
    if (state && state.panel) {
      showState(state);
      return;
    }
    saveStatus.textContent = fields && fields.type === "dry-run" ? "Dry-run did not run." : "Prepare did not run.";
  }

  document.getElementById("prepare-all").addEventListener("click", function () {
    runPrepare({ mode: "all" }).catch(function () {
      saveStatus.textContent = "Prepare did not run.";
    });
  });

  function navigateFindingLink(link, openFallback) {
    const anchor = link.getAttribute("data-diff-anchor");
    if (!anchor) return Promise.resolve(false);
    return activeTab().then(function (tab) {
      if (!tab || tab.id == null) return false;
      return new Promise(function (resolve) {
        try {
          chrome.tabs.sendMessage(
            tab.id,
            {
              type: "navigate-to-anchor",
              anchor: anchor,
              path: link.getAttribute("data-finding-path") || "",
              line: link.getAttribute("data-finding-line") || "",
              side: link.getAttribute("data-finding-side") || "RIGHT",
              on_diff: link.getAttribute("data-on-diff") === "true",
            },
            function (response) {
              if (!chrome.runtime.lastError && response && response.ok) {
                resolve(true);
                return;
              }
              if (openFallback) {
                const href = link.getAttribute("data-fallback-href");
                if (href) chrome.tabs.update(tab.id, { url: href });
              }
              resolve(false);
            }
          );
        } catch (err) {
          resolve(false);
        }
      });
    });
  }

  statusEl.addEventListener("click", async function (event) {
    const lineLink = event.target && event.target.closest ? event.target.closest(".finding-line-link") : null;
    if (lineLink) {
      event.preventDefault();
      const openFallback = event.metaKey === true || event.ctrlKey === true || event.button === 1;
      if (openFallback) {
        const href = lineLink.getAttribute("data-fallback-href");
        if (href) chrome.tabs.create({ url: href });
        return;
      }
      await navigateFindingLink(lineLink, true);
      return;
    }
    const dryRunButton = event.target && event.target.closest ? event.target.closest("[data-dry-run-finding]") : null;
    if (dryRunButton) {
      runPrepare({
        type: "dry-run",
        mode: "finding",
        findingId: dryRunButton.getAttribute("data-dry-run-finding"),
      }).catch(function () {
        saveStatus.textContent = "Dry-run did not run.";
      });
      return;
    }
    const prepareButton = event.target && event.target.closest ? event.target.closest("[data-prepare-finding]") : null;
    if (prepareButton) {
      runPrepare({
        mode: "finding",
        findingId: prepareButton.getAttribute("data-prepare-finding"),
      }).catch(function () {
        saveStatus.textContent = "Prepare did not run.";
      });
      return;
    }
    const button = event.target && event.target.closest ? event.target.closest("[data-confirm-replace]") : null;
    if (!button) return;
    const tab = await activeTab();
    const state = await send(
      Object.assign(
        {
          type: "confirm-replace-draft",
          tabId: tab && tab.id != null ? tab.id : null,
          findingId: button.getAttribute("data-confirm-replace"),
        },
        scanFields()
      )
    );
    if (state && state.ok) showState(state);
  });

  function probeFields() {
    return {
      path: document.getElementById("probe-path").value,
      line: document.getElementById("probe-line").value,
      startLine: document.getElementById("probe-start").value,
    };
  }

  document.getElementById("probe").addEventListener("click", async function () {
    debugStatus.textContent = "";
    const tab = await activeTab();
    const state = await send(
      Object.assign({ type: "probe", tabId: tab && tab.id != null ? tab.id : null }, probeFields())
    );
    if (state && state.panel) showState(state);
    if (!state || !state.log || !state.log.length) {
      debugStatus.textContent = "Probe did not run.";
      return;
    }
    debugStatus.textContent = state.status === "highlighted"
      ? "Probe highlighted the row."
      : "Probe failed. reason " + (state.reason || "line_off_screen") + ".";
  });

  document.getElementById("dry-run").addEventListener("click", function () {
    runPrepare(Object.assign({ type: "dry-run" }, probeFields())).catch(function () {
      saveStatus.textContent = "Dry-run did not run.";
    });
  });

  document.getElementById("pick-selector").addEventListener("click", async function () {
    debugStatus.textContent = "Click a control on the pull request page.";
    const tab = await activeTab();
    const selectorId = selectorEntry ? selectorEntry.value : "";
    const picked = await send({
      type: "pick-selector",
      tabId: tab && tab.id != null ? tab.id : null,
      selectorId: selectorId,
    });
    if (!picked || !picked.ok) {
      debugStatus.textContent = "Picker did not store an override.";
      return;
    }
    if (picked.registry) fillRegistry(picked.registry);
    debugStatus.textContent = "Stored override for " + picked.selectorId + ".";
  });

  document.getElementById("copy-debug").addEventListener("click", async function () {
    const text = globalThis.ReviewPilotDebug
      ? ReviewPilotDebug.copyDebugBundle(debugLog)
      : debugLog.join("\n");
    if (!text) {
      debugStatus.textContent = "Debug bundle is empty.";
      return;
    }
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        debugStatus.textContent = "Debug bundle was not copied.";
        return;
      }
      await navigator.clipboard.writeText(text);
      debugStatus.textContent = "Debug bundle copied.";
    } catch (err) {
      debugStatus.textContent = "Debug bundle was not copied.";
    }
  });

  document.getElementById("clear-overrides").addEventListener("click", async function () {
    const cleared = await send({ type: "clear-selector-overrides" });
    if (!cleared || !cleared.ok) {
      debugStatus.textContent = "Selector overrides were not cleared.";
      return;
    }
    if (cleared.registry) fillRegistry(cleared.registry);
    debugStatus.textContent = "Selector overrides cleared. Packaged defaults are in use.";
  });

  document.getElementById("save-settings").addEventListener("click", async function () {
    const saved = await send({
      type: "save-settings",
      settings: currentSettings(),
    });
    if (!saved || !saved.ok) {
      saveStatus.textContent = "Port must be an integer from 1 to 65535.";
      return;
    }
    saveStatus.textContent = "Settings saved.";
    refresh();
  });

  chrome.tabs.onActivated.addListener(function () {
    refresh();
  });

  chrome.tabs.onUpdated.addListener(function (_tabId, info) {
    if (info.status === "complete") refresh();
  });

  refresh();
})();
