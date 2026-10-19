(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotPrepare = api;
})(globalThis, function () {
  "use strict";

  const HEADER = "## Findings outside the diff";
  const DEFAULTS = {
    "file-block": "[data-file-path]",
    "file-filter": "[data-file-filter], [aria-label='File filter']",
    "expand-file": "[data-expand-file], [aria-label='Toggle diff contents']",
    "expand-hunk": "[data-expand-hunk], [aria-label='Expand Down'], [aria-label='Expand Up']",
    "line-number": "[data-diff-side][data-line-number]",
    "add-comment-button": "[data-add-comment], [aria-label='+']",
    "markdown-textarea": "textarea[aria-label='Markdown value'], textarea",
    "stage-review-button": "Start a review",
    "composer-comment": "Comment",
    "dialog-submit-review": "Submit review control enter",
    "toolbar-submit-review": "Submit review",
    "finish-review-dialog": "Finish your review",
    "cancel-review": "Cancel",
    "dialog-close": "Close",
    "review-event": "[name='reviewEvent']",
    "viewed-control": "[aria-label='Viewed'], [aria-label='Not Viewed']",
    "comments-panel": "[data-panel='comments']",
    "file-list": "[data-file-list], .diff-line-row, #files",
    "single-file-mode": "Switch to single file mode",
  };
  const FORBIDDEN = {
    comment: true,
    "submit review control enter": true,
    "add review comment": true,
    approve: true,
    "request changes": true,
    "abandon review": true,
    "discard review": true,
    viewed: true,
    "not viewed": true,
    "comment on this file": true,
  };

  function clean(value) {
    return String(value == null ? "" : value)
      .replace(/\s+/g, " ")
      .trim();
  }

  function selectorsFrom(request) {
    const packed = request && request.selectors && typeof request.selectors === "object" ? request.selectors : {};
    return Object.assign({}, DEFAULTS, packed);
  }

  function pageDocument(request) {
    if (request && request.document && typeof request.document.querySelectorAll === "function") {
      return request.document;
    }
    const doc = globalThis.document;
    if (!doc || typeof doc.querySelectorAll !== "function") return null;
    return doc;
  }

  function queryAll(doc, selector) {
    if (!doc || !selector || typeof doc.querySelectorAll !== "function") return [];
    try {
      const found = doc.querySelectorAll(selector);
      const list = [];
      if (!found || typeof found.length !== "number") return list;
      for (let i = 0; i < found.length; i += 1) list.push(found[i]);
      return list;
    } catch (err) {
      return [];
    }
  }

  function attr(el, name) {
    if (!el || typeof el.getAttribute !== "function") return "";
    const value = el.getAttribute(name);
    return value == null ? "" : String(value);
  }

  function textOf(el) {
    if (!el) return "";
    if (el.textContent != null) return String(el.textContent);
    return "";
  }

  function accessibleName(el) {
    const aria = clean(attr(el, "aria-label"));
    if (aria) return aria;
    const labelled = clean(attr(el, "aria-labelledby"));
    if (labelled && el.ownerDocument && typeof el.ownerDocument.getElementById === "function") {
      const label = el.ownerDocument.getElementById(labelled);
      const labelText = clean(textOf(label));
      if (labelText) return labelText;
    }
    return clean(textOf(el));
  }

  function containsNode(parent, child) {
    let cur = child;
    while (cur) {
      if (cur === parent) return true;
      cur = cur.parentNode || cur.parentElement || null;
    }
    return false;
  }

  function ancestor(el, pred) {
    let cur = el;
    while (cur) {
      if (pred(cur)) return cur;
      cur = cur.parentNode || cur.parentElement || null;
    }
    return null;
  }

  function stamp(now) {
    let value;
    try {
      value = now();
    } catch (err) {
      value = Date.now();
    }
    try {
      return new Date(value).toISOString() + " ";
    } catch (err2) {
      return "";
    }
  }

  function diffSide(side) {
    const value = String(side || "RIGHT").toUpperCase();
    if (value === "LEFT") return "left";
    if (value === "RIGHT") return "right";
    return value.toLowerCase();
  }

  function markerToken(id) {
    return "review-pilot finding " + id;
  }

  function commentToken(id) {
    return "<!-- review-pilot:finding:" + id + " -->";
  }

  function normalizeNewlines(value) {
    return String(value == null ? "" : value).replace(/\r\n/g, "\n");
  }

  function indexOfWholeMarker(text, id) {
    const needle = markerToken(id);
    let from = 0;
    while (from <= text.length) {
      const at = text.indexOf(needle, from);
      if (at < 0) return -1;
      const beforeOk = at === 0 || /[\s>]/.test(text.charAt(at - 1));
      const afterAt = at + needle.length;
      const afterOk = afterAt >= text.length || /[\s<]/.test(text.charAt(afterAt));
      if (beforeOk && afterOk) return at;
      from = at + needle.length;
    }
    return -1;
  }

  function segmentEnd(text, id, markerAt) {
    const comment = commentToken(id);
    const commentAt = text.indexOf(comment, markerAt);
    if (commentAt >= 0) return commentAt + comment.length;
    return markerAt + markerToken(id).length;
  }

  function endOfMarkedRegion(text) {
    const start = text.indexOf(HEADER);
    if (start < 0) return text.length;
    let end = start + HEADER.length;
    const re = /<!--\s*review-pilot:finding:[^\s>]+\s*-->|review-pilot finding [^\s<]+/g;
    re.lastIndex = start;
    let match;
    while ((match = re.exec(text))) end = match.index + match[0].length;
    return end;
  }

  function joinParts(parts) {
    const kept = [];
    for (let i = 0; i < parts.length; i += 1) {
      const part = String(parts[i] || "").trim();
      if (part) kept.push(part);
    }
    if (!kept.length) return "";
    return kept.join("\n\n") + "\n";
  }

  function segmentStart(text, markerAt) {
    const headerAt = text.lastIndexOf(HEADER, markerAt);
    let start = headerAt >= 0 ? headerAt + HEADER.length : 0;
    const re = /review-pilot finding [^\s<]+/g;
    let match;
    while ((match = re.exec(text))) {
      if (match.index >= markerAt) break;
      const id = match[0].slice("review-pilot finding ".length);
      const end = segmentEnd(text, id, match.index);
      if (end <= markerAt) start = Math.max(start, end);
    }
    return start;
  }

  function replaceMarkedSegment(existing, id, segment) {
    const text = normalizeNewlines(existing);
    const piece = normalizeNewlines(segment).trim();
    const findingId = String(id == null ? "" : id);
    if (!findingId || !piece) return text;
    const at = indexOfWholeMarker(text, findingId);
    if (at >= 0) {
      const start = segmentStart(text, at);
      const end = segmentEnd(text, findingId, at);
      return joinParts([text.slice(0, start), piece, text.slice(end)]);
    }
    if (!text.trim()) return joinParts([HEADER, piece]);
    if (text.indexOf(HEADER) < 0) return joinParts([text, HEADER + "\n\n" + piece]);
    const blockEnd = endOfMarkedRegion(text);
    return joinParts([text.slice(0, blockEnd), piece, text.slice(blockEnd)]);
  }

  function replaceSummaryBlock(existing, block) {
    const text = normalizeNewlines(existing);
    const piece = normalizeNewlines(block).trim();
    if (!piece) return text;
    const start = text.indexOf(HEADER);
    if (start < 0) {
      if (!text.trim()) return piece + "\n";
      return joinParts([text, piece]);
    }
    const end = endOfMarkedRegion(text);
    return joinParts([text.slice(0, start), piece, text.slice(end)]);
  }

  function blockFromFindings(findings) {
    const parts = [];
    for (let i = 0; i < findings.length; i += 1) {
      const body = normalizeNewlines(findings[i] && findings[i].body).trim();
      if (body) parts.push(body);
    }
    if (!parts.length) return "";
    return HEADER + "\n\n" + parts.join("\n\n") + "\n";
  }

  function isDisabled(el) {
    if (!el) return true;
    if (el.disabled === true) return true;
    return clean(attr(el, "aria-disabled")).toLowerCase() === "true";
  }

  function nameKey(el) {
    return accessibleName(el).toLowerCase();
  }

  function dialogName(selectors) {
    return clean(selectors["finish-review-dialog"] || DEFAULTS["finish-review-dialog"]);
  }

  function findDialog(doc, selectors) {
    const name = dialogName(selectors);
    const dialogs = queryAll(doc, "[role='dialog']");
    for (let i = 0; i < dialogs.length; i += 1) {
      if (accessibleName(dialogs[i]) === name) return dialogs[i];
    }
    return null;
  }

  function insideDialog(el, doc, selectors) {
    const dialog = findDialog(doc, selectors);
    return Boolean(dialog && el && containsNode(dialog, el));
  }

  function insideComments(el, doc, selectors) {
    const panels = queryAll(doc, selectors["comments-panel"] || DEFAULTS["comments-panel"]);
    for (let i = 0; i < panels.length; i += 1) {
      if (containsNode(panels[i], el)) return true;
    }
    return Boolean(
      ancestor(el, function (node) {
        return clean(attr(node, "data-panel")) === "comments";
      })
    );
  }

  function insideOpenComposer(el) {
    return Boolean(
      ancestor(el, function (node) {
        return attr(node, "data-composer") === "open";
      })
    );
  }

  function refuse(el, doc, selectors) {
    const name = nameKey(el);
    if (!name) return false;
    if (FORBIDDEN[name]) return true;
    if (insideDialog(el, doc, selectors) && name.indexOf("submit review") === 0) return true;
    return false;
  }

  function describe(el, event) {
    return {
      type: event.type,
      shiftKey: Boolean(event.shiftKey),
      name: accessibleName(el),
      side: attr(el, "data-diff-side"),
      line: attr(el, "data-line-number"),
      role: attr(el, "data-line-role"),
    };
  }

  function nativeEvent(type, shiftKey) {
    try {
      if (typeof MouseEvent === "function") {
        return new MouseEvent(type, { bubbles: true, cancelable: true, shiftKey: Boolean(shiftKey) });
      }
    } catch (err) {
      return null;
    }
    return null;
  }

  function dispatch(el, type, shiftKey) {
    const event = nativeEvent(type, shiftKey) || { type: type, shiftKey: Boolean(shiftKey), bubbles: true };
    if (typeof el.dispatchEvent === "function") el.dispatchEvent(event);
  }

  function setValue(el, value) {
    const proto = el && Object.getPrototypeOf(el);
    const desc = proto && Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && typeof desc.set === "function") {
      desc.set.call(el, value);
      return;
    }
    el.value = value;
  }

  function dispatchInput(el) {
    let event = { type: "input", bubbles: true };
    try {
      if (typeof Event === "function") event = new Event("input", { bubbles: true });
    } catch (err) {
      event = { type: "input", bubbles: true };
    }
    if (typeof el.dispatchEvent === "function") el.dispatchEvent(event);
  }

  function filePathOf(el) {
    let cur = el;
    while (cur) {
      const path = attr(cur, "data-file-path") || attr(cur, "data-path");
      if (path) return path;
      cur = cur.parentNode || cur.parentElement || null;
    }
    return "";
  }

  function preferNumberCell(list, line) {
    const wanted = String(line);
    for (let i = 0; i < list.length; i += 1) {
      if (clean(textOf(list[i])) === wanted) return list[i];
    }
    for (let i = 0; i < list.length; i += 1) {
      if (attr(list[i], "data-line-role") === "number") return list[i];
      if (attr(list[i], "class").indexOf("line-number") !== -1) return list[i];
    }
    return list[0] || null;
  }

  function findLine(doc, finding, selectors, lineNumber) {
    const side = diffSide(finding.side);
    const line = String(lineNumber);
    const nodes = queryAll(doc, selectors["line-number"] || DEFAULTS["line-number"]);
    const matches = [];
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i];
      if (attr(el, "data-diff-side").toLowerCase() !== side) continue;
      if (String(attr(el, "data-line-number")) !== line) continue;
      const path = filePathOf(el);
      if (finding.path && path && path !== String(finding.path)) continue;
      matches.push(el);
    }
    return preferNumberCell(matches, line);
  }

  function findFile(doc, finding, selectors) {
    const path = finding.path ? String(finding.path) : "";
    if (!path) return null;
    const files = queryAll(doc, selectors["file-block"] || DEFAULTS["file-block"]);
    for (let i = 0; i < files.length; i += 1) {
      if (attr(files[i], "data-file-path") === path) return files[i];
    }
    return null;
  }

  function isCollapsed(file) {
    if (!file) return false;
    if (attr(file, "data-collapsed") === "true") return true;
    if (attr(file, "aria-expanded") === "false") return true;
    return false;
  }

  function buttonsNamed(doc, name) {
    const wanted = clean(name);
    const buttons = queryAll(doc, "button, [role='button']");
    const found = [];
    for (let i = 0; i < buttons.length; i += 1) {
      if (accessibleName(buttons[i]) === wanted) found.push(buttons[i]);
    }
    return found;
  }

  function placementApi() {
    return globalThis.ReviewPilotPlacement || null;
  }

  function scanFindings(doc, findings, request) {
    const api = placementApi();
    const list = Array.isArray(findings) ? findings : [];
    if (!api || typeof api.scanPlacement !== "function") {
      return list.map(function (finding) {
        return {
          id: finding && finding.id == null ? "" : String(finding.id),
          status: "not_placed",
          outcome: "fill",
          confirmRequired: false,
        };
      });
    }
    const comments = doc && typeof api.collectComments === "function" ? api.collectComments(doc) : [];
    return api.scanPlacement(list, comments, {
      replaceModifiedDrafts: request.replaceModifiedDrafts === true,
      confirmedIds: request.confirmedIds || [],
      blocked: false,
    }).findings;
  }

  function plannedOutcome(finding, row) {
    if (!row) return "fill";
    if (!finding.on_diff && row.outcome == null && row.status === "not_placed") return "fill";
    return row.outcome || null;
  }

  function canWrite(outcome, row) {
    if (outcome === "fill") return true;
    if (outcome === "replace_draft" && row && row.confirmRequired !== true) return true;
    return false;
  }

  function isPending(doc, finding) {
    const api = placementApi();
    if (!api || typeof api.collectComments !== "function" || typeof api.hasMarker !== "function") return false;
    const comments = api.collectComments(doc);
    for (let i = 0; i < comments.length; i += 1) {
      const comment = comments[i];
      if (!comment) continue;
      if (comment.region !== "pending" && comment.region !== "summary") continue;
      if (api.hasMarker(comment.text, finding.id)) return true;
    }
    return false;
  }

  function waitPending(doc, finding, request) {
    const timeout = request.pendingTimeoutMs == null ? 1500 : Number(request.pendingTimeoutMs);
    const interval = request.pendingIntervalMs == null ? 20 : Number(request.pendingIntervalMs);
    const schedule = typeof request.schedule === "function"
      ? request.schedule
      : function (fn, ms) { setTimeout(fn, ms); };
    const now = typeof request.now === "function" ? request.now : function () { return Date.now(); };
    return new Promise(function (resolve) {
      const start = now();
      function tick() {
        let ready = false;
        try {
          ready = isPending(doc, finding);
        } catch (err) {
          ready = false;
        }
        if (ready) {
          resolve(true);
          return;
        }
        if (!(timeout > 0) || now() - start >= timeout) {
          resolve(false);
          return;
        }
        schedule(tick, interval);
      }
      tick();
    });
  }

  function emptyResult(status, log) {
    return {
      status: status,
      acted: false,
      readOnly: true,
      log: log || [],
      actions: [],
      inserts: 0,
      summaryWrites: 0,
      findings: [],
      stopped: status === "blocked",
    };
  }

  async function run(gate, request) {
    if (!gate || gate.status !== "pass") return emptyResult("blocked");
    const req = request || {};
    const doc = pageDocument(req);
    const selectors = selectorsFrom(req);
    const now = typeof req.now === "function" ? req.now : function () { return Date.now(); };
    const log = [];
    const actions = [];
    const mode = req.mode === "all" ? "all" : "finding";
    let acted = false;
    let inserts = 0;
    let summaryWrites = 0;
    let stopped = false;
    const outcomes = [];

    if (!doc) return emptyResult("pass");

    const sourceFindings = Array.isArray(req.findings) ? req.findings : [];
    const chosen = mode === "all"
      ? sourceFindings
      : sourceFindings.filter(function (finding) {
          return String(finding && finding.id) === String(req.findingId == null ? "" : req.findingId);
        });
    let scanned = [];
    try {
      scanned = scanFindings(doc, chosen, req);
    } catch (err) {
      log.push(stamp(now) + "DOM failure. Placement scan failed.");
      return {
        status: "blocked",
        acted: false,
        readOnly: true,
        log: log,
        actions: actions,
        inserts: 0,
        summaryWrites: 0,
        findings: [],
        stopped: true,
      };
    }
    const byId = {};
    for (let i = 0; i < scanned.length; i += 1) {
      if (scanned[i] && scanned[i].id) byId[scanned[i].id] = scanned[i];
    }

    function pushAction(el, type, shiftKey) {
      actions.push(describe(el, { type: type, shiftKey: Boolean(shiftKey) }));
    }

    function activate(el, detail) {
      if (!el || isDisabled(el) || refuse(el, doc, selectors)) return false;
      const hover = Boolean(detail && detail.hover);
      const shiftKey = Boolean(detail && detail.shiftKey);
      const type = hover ? "mouseover" : "click";
      pushAction(el, type, shiftKey);
      try {
        dispatch(el, type, shiftKey);
        if (hover) dispatch(el, "pointerenter", false);
      } catch (err) {
        log.push(stamp(now) + "DOM failure. Could not activate " + (accessibleName(el) || "a control") + ".");
        return false;
      }
      acted = true;
      return true;
    }

    function record(finding, row, outcome, extra) {
      const item = extra || {};
      outcomes.push({
        id: finding.id == null ? "" : String(finding.id),
        status: item.status || (row && row.status) || "not_placed",
        outcome: outcome || "",
        pending: item.pending === true,
        note: item.note || "",
      });
    }

    function expandFile(finding) {
      const file = findFile(doc, finding, selectors);
      if (!file || !isCollapsed(file)) return;
      const buttons = queryAll(doc, selectors["expand-file"]).filter(function (el) {
        return containsNode(file, el) && !refuse(el, doc, selectors);
      });
      if (!buttons.length) {
        log.push(stamp(now) + "DOM failure. Collapsed file had no expand control.");
        return;
      }
      if (activate(buttons[0])) log.push(stamp(now) + "Expanded the file.");
    }

    function clearFilter(finding) {
      const filters = queryAll(doc, selectors["file-filter"]);
      const path = finding.path ? String(finding.path).toLowerCase() : "";
      for (let i = 0; i < filters.length; i += 1) {
        const filter = filters[i];
        const value = filter.value == null ? "" : String(filter.value).trim();
        if (!value) continue;
        if (path && path.indexOf(value.toLowerCase()) !== -1) continue;
        setValue(filter, "");
        dispatchInput(filter);
        acted = true;
        log.push(stamp(now) + "Cleared the file filter.");
      }
    }

    function expandHunks(finding) {
      const file = findFile(doc, finding, selectors);
      const buttons = queryAll(doc, selectors["expand-hunk"]).filter(function (el) {
        return (!file || containsNode(file, el)) && !refuse(el, doc, selectors);
      });
      if (!buttons.length) return;
      if (activate(buttons[0])) log.push(stamp(now) + "Expanded the hunk.");
    }

    function scrollOnce() {
      const target = queryAll(doc, selectors["file-list"])[0];
      if (target && typeof target.scrollBy === "function") target.scrollBy(0, 800);
      if (typeof doc.reviewPilotAfterScroll === "function") doc.reviewPilotAfterScroll();
      acted = true;
    }

    function reveal(finding, lineNumber) {
      let cell = findLine(doc, finding, selectors, lineNumber);
      if (cell) return cell;
      expandFile(finding);
      cell = findLine(doc, finding, selectors, lineNumber);
      if (cell) return cell;
      clearFilter(finding);
      cell = findLine(doc, finding, selectors, lineNumber);
      if (cell) return cell;
      expandHunks(finding);
      cell = findLine(doc, finding, selectors, lineNumber);
      if (cell) return cell;
      const attempts = req.scrollAttempts == null ? 8 : Number(req.scrollAttempts);
      const limit = Number.isFinite(attempts) && attempts > 0 ? attempts : 0;
      for (let i = 0; i < limit; i += 1) {
        scrollOnce();
        cell = findLine(doc, finding, selectors, lineNumber);
        if (cell) return cell;
      }
      return null;
    }

    function findAddButton() {
      const found = queryAll(doc, selectors["add-comment-button"]);
      if (found.length) return found[found.length - 1];
      const named = buttonsNamed(doc, "+");
      return named.length ? named[named.length - 1] : null;
    }

    function findComposerTextarea() {
      const areas = queryAll(doc, selectors["markdown-textarea"]);
      const open = [];
      for (let i = 0; i < areas.length; i += 1) {
        const el = areas[i];
        if (insideComments(el, doc, selectors) || insideDialog(el, doc, selectors)) continue;
        if (!insideOpenComposer(el)) continue;
        if (clean(accessibleName(el)) && clean(accessibleName(el)) !== "Markdown value") continue;
        open.push(el);
      }
      return open.length ? open[open.length - 1] : null;
    }

    function findDraftTextarea(finding) {
      const marker = markerToken(finding.id);
      const areas = queryAll(doc, "textarea");
      for (let i = 0; i < areas.length; i += 1) {
        const el = areas[i];
        const host = ancestor(el, function (node) {
          const kind = attr(node, "data-review-pilot-comment").toLowerCase();
          return kind === "pending" || kind === "draft";
        });
        if (!host) continue;
        const blob = textOf(host) + "\n" + (el.value == null ? "" : String(el.value));
        if (blob.indexOf(marker) === -1) continue;
        return el;
      }
      return null;
    }

    function debugTrace(ids) {
      const api = globalThis.ReviewPilotDebug;
      if (!api || typeof api.matchLine !== "function") return;
      for (let i = 0; i < ids.length; i += 1) {
        try {
          log.push(api.matchLine(doc, ids[i], selectors[ids[i]], now));
        } catch (err) {
          log.push(stamp(now) + ids[i] + " matches 0.");
        }
      }
    }

    function writeComposer(el, body) {
      if (req.dryRun === true) {
        debugTrace(["line-number", "add-comment-button", "markdown-textarea"]);
        log.push(stamp(now) + "dry-run stopped before the textarea write.");
        return false;
      }
      setValue(el, body == null ? "" : String(body));
      dispatchInput(el);
      acted = true;
      return true;
    }

    function blockedFinding(finding, row, outcome, sentence) {
      log.push(stamp(now) + sentence);
      record(finding, row, outcome, { status: "blocked", pending: false, note: sentence });
      stopped = true;
    }

    function fillInline(finding, row) {
      const line = finding.line;
      const cell = reveal(finding, line);
      if (!cell) {
        const sentence = "DOM failure. The row did not mount. " + clean(selectors["single-file-mode"]) + ".";
        blockedFinding(finding, row, "fill", sentence);
        return;
      }
      activate(cell);
      const start = finding.start_line;
      if (typeof start === "number" && start !== line) {
        const other = reveal(finding, start);
        if (!other) {
          const sentence = "DOM failure. The row did not mount. " + clean(selectors["single-file-mode"]) + ".";
          blockedFinding(finding, row, "fill", sentence);
          return;
        }
        activate(other, { shiftKey: true });
      }
      activate(cell, { hover: true });
      const plus = findAddButton();
      if (!plus || !activate(plus)) {
        blockedFinding(finding, row, "fill", "DOM failure. The add comment control was not found.");
        return;
      }
      const textarea = findComposerTextarea();
      if (!textarea) {
        blockedFinding(finding, row, "fill", "DOM failure. The Markdown value textarea was not found.");
        return;
      }
      if (!writeComposer(textarea, finding.body)) {
        record(finding, row, "fill", {
          status: "not_placed",
          pending: false,
          note: "Dry-run stopped before the textarea write.",
        });
        return;
      }
      inserts += 1;
      if (mode === "all") return stageComposer(finding, row, "fill");
      const sentence = "The comment is not pending until " + clean(selectors["stage-review-button"]) + " is clicked.";
      log.push(stamp(now) + "stage control was not used. " + sentence);
      record(finding, row, "fill", { status: "not_placed", pending: false, note: sentence });
    }

    function replaceDraft(finding, row) {
      const textarea = findDraftTextarea(finding);
      if (!textarea) {
        blockedFinding(finding, row, "replace_draft", "DOM failure. The pending comment editor was not found.");
        return;
      }
      if (!writeComposer(textarea, finding.body)) {
        record(finding, row, "replace_draft", {
          status: "draft_modified",
          pending: false,
          note: "Dry-run stopped before the textarea write.",
        });
        return;
      }
      if (mode === "all") return stageComposer(finding, row, "replace_draft");
      const sentence = "The comment is not pending until " + clean(selectors["stage-review-button"]) + " is clicked.";
      log.push(stamp(now) + "stage control was not used. " + sentence);
      record(finding, row, "replace_draft", { status: "draft_modified", pending: false, note: sentence });
    }

    function stageComposer(finding, row, outcome) {
      const stageName = clean(selectors["stage-review-button"]);
      const matches = buttonsNamed(doc, stageName).filter(function (el) {
        return !insideDialog(el, doc, selectors);
      });
      const inComposer = matches.filter(insideOpenComposer);
      const chosenButton = (inComposer.length ? inComposer : matches)[0] || null;
      if (!chosenButton) {
        const commentName = clean(selectors["composer-comment"] || "Comment");
        const commentButtons = buttonsNamed(doc, commentName);
        if (commentButtons.length) {
          blockedFinding(finding, row, outcome, "DOM failure. The stage control is Comment. Stopped.");
          return;
        }
        blockedFinding(finding, row, outcome, "DOM failure. The stage control was not found. Stopped.");
        return;
      }
      if (isDisabled(chosenButton)) {
        blockedFinding(finding, row, outcome, "DOM failure. Stage control stayed disabled.");
        return;
      }
      if (!activate(chosenButton)) {
        blockedFinding(finding, row, outcome, "DOM failure. The stage control was not clicked.");
        return;
      }
      return waitPending(doc, finding, req).then(function (ready) {
        if (!ready) {
          blockedFinding(finding, row, outcome, "DOM failure. The comment did not become pending. Stopped.");
          return;
        }
        log.push(stamp(now) + "stage control clicked. " + finding.id + " is pending.");
        record(finding, row, outcome, { status: "draft", pending: true, note: "" });
      });
    }

    function dialogOpen(dialog) {
      if (!dialog) return false;
      if (attr(dialog, "hidden") !== "" && attr(dialog, "hidden") !== "false" && attr(dialog, "hidden")) return false;
      if (attr(dialog, "data-open") === "false") return false;
      return true;
    }

    function summaryTextarea(dialog) {
      if (!dialog) return null;
      const areas = queryAll(doc, selectors["markdown-textarea"]).filter(function (el) {
        return containsNode(dialog, el) && !insideComments(el, doc, selectors);
      });
      for (let i = 0; i < areas.length; i += 1) {
        if (accessibleName(areas[i]) === "Markdown value") return areas[i];
      }
      return areas[0] || null;
    }

    function openSummary() {
      let dialog = findDialog(doc, selectors);
      if (dialog && dialogOpen(dialog)) return dialog;
      const toolbarName = clean(selectors["toolbar-submit-review"]);
      const buttons = buttonsNamed(doc, toolbarName).filter(function (el) {
        return !insideDialog(el, doc, selectors) && !refuse(el, doc, selectors);
      });
      if (!buttons.length) {
        log.push(stamp(now) + "DOM failure. Toolbar Submit review was not found.");
        return null;
      }
      if (!activate(buttons[0])) return null;
      dialog = findDialog(doc, selectors);
      if (!dialog || !dialogOpen(dialog)) {
        log.push(stamp(now) + "DOM failure. Finish your review did not open.");
        return null;
      }
      return dialog;
    }

    function closeSummary(dialog) {
      const cancelName = clean(selectors["cancel-review"]);
      const closeName = clean(selectors["dialog-close"]);
      const buttons = queryAll(doc, "button, [role='button']").filter(function (el) {
        return containsNode(dialog, el);
      });
      let chosen = null;
      for (let i = 0; i < buttons.length; i += 1) {
        const name = accessibleName(buttons[i]);
        if (name === cancelName || name === closeName) {
          chosen = buttons[i];
          break;
        }
      }
      if (!chosen) {
        log.push(stamp(now) + "DOM failure. Cancel was not found.");
        return;
      }
      activate(chosen);
    }

    const onDiff = [];
    const offDiff = [];
    for (let i = 0; i < chosen.length; i += 1) {
      const finding = chosen[i];
      if (!finding || typeof finding !== "object") continue;
      if (finding.on_diff) onDiff.push(finding);
      else offDiff.push(finding);
    }

    for (let i = 0; i < onDiff.length; i += 1) {
      if (stopped) break;
      const finding = onDiff[i];
      const row = byId[String(finding.id)] || null;
      const outcome = plannedOutcome(finding, row);
      log.push(stamp(now) + "preflight " + finding.id + " " + (outcome || "none") + ".");
      if (outcome === "skip_match") {
        log.push(stamp(now) + "skip " + finding.id + " already placed.");
        record(finding, row, outcome, { pending: true });
        continue;
      }
      if (outcome === "manual_only") {
        log.push(stamp(now) + "skip " + finding.id + " manual_only.");
        record(finding, row, outcome, {});
        continue;
      }
      if (outcome === "replace_draft" && row && row.confirmRequired) {
        log.push(stamp(now) + "skip " + finding.id + " replace_draft needs confirm.");
        record(finding, row, outcome, {});
        continue;
      }
      if (outcome === "replace_draft") {
        const replaced = replaceDraft(finding, row);
        if (replaced && typeof replaced.then === "function") await replaced;
        continue;
      }
      if (outcome !== "fill") {
        log.push(stamp(now) + "skip " + finding.id + " no insert.");
        record(finding, row, outcome, {});
        continue;
      }
      const filled = fillInline(finding, row);
      if (filled && typeof filled.then === "function") await filled;
    }

    if (!stopped && offDiff.length) {
      const plans = offDiff.map(function (finding) {
        const row = byId[String(finding.id)] || null;
        const outcome = plannedOutcome(finding, row);
        log.push(stamp(now) + "preflight " + finding.id + " " + (outcome || "none") + ".");
        return { finding: finding, row: row, outcome: outcome };
      });
      plans.forEach(function (item) {
        if (item.outcome === "skip_match") log.push(stamp(now) + "skip " + item.finding.id + " already placed.");
        else if (item.outcome === "manual_only") log.push(stamp(now) + "skip " + item.finding.id + " manual_only.");
        else if (item.outcome === "replace_draft" && item.row && item.row.confirmRequired) {
          log.push(stamp(now) + "skip " + item.finding.id + " replace_draft needs confirm.");
        }
      });
      const writes = plans.filter(function (item) {
        return canWrite(item.outcome, item.row);
      });
      if (writes.length && mode === "finding") {
        const item = writes[0];
        const dialog = openSummary();
        const area = summaryTextarea(dialog);
        if (!dialog || !area) {
          blockedFinding(item.finding, item.row, item.outcome, "DOM failure. The summary textarea was not found.");
        } else {
          const next = replaceMarkedSegment(area.value, item.finding.id, item.finding.body);
          if (!writeComposer(area, next)) {
            record(item.finding, item.row, item.outcome, {
              pending: false,
              note: "Dry-run stopped before the textarea write.",
            });
          } else {
            summaryWrites += 1;
            log.push(stamp(now) + "summary segment written for " + item.finding.id + ".");
            closeSummary(dialog);
            record(item.finding, item.row, item.outcome, { status: "draft", pending: true, note: "" });
          }
        }
      } else if (writes.length && mode === "all") {
        const unsafe = plans.some(function (item) {
          return item.outcome === "manual_only" || (item.outcome === "replace_draft" && item.row && item.row.confirmRequired);
        });
        const dialog = openSummary();
        const area = summaryTextarea(dialog);
        if (!dialog || !area) {
          blockedFinding(writes[0].finding, writes[0].row, writes[0].outcome, "DOM failure. The summary textarea was not found.");
        } else {
          let next;
          if (!unsafe) {
            const block = req.summaryBlock ? String(req.summaryBlock) : blockFromFindings(offDiff);
            next = replaceSummaryBlock(area.value, block);
          } else {
            next = area.value == null ? "" : String(area.value);
            for (let w = 0; w < writes.length; w += 1) {
              next = replaceMarkedSegment(next, writes[w].finding.id, writes[w].finding.body);
            }
          }
          if (!writeComposer(area, next)) {
            for (let w = 0; w < writes.length; w += 1) {
              record(writes[w].finding, writes[w].row, writes[w].outcome, {
                pending: false,
                note: "Dry-run stopped before the textarea write.",
              });
            }
          } else {
            summaryWrites += 1;
            log.push(stamp(now) + "summary block written.");
            closeSummary(dialog);
            for (let w = 0; w < writes.length; w += 1) {
              record(writes[w].finding, writes[w].row, writes[w].outcome, { status: "draft", pending: true, note: "" });
            }
          }
        }
      }
      plans.forEach(function (item) {
        if (canWrite(item.outcome, item.row)) return;
        const already = outcomes.some(function (row) {
          return row.id === String(item.finding.id);
        });
        if (!already) record(item.finding, item.row, item.outcome, {});
      });
    }

    return {
      status: stopped ? "blocked" : "pass",
      acted: acted,
      readOnly: !acted,
      log: log,
      actions: actions,
      inserts: inserts,
      summaryWrites: summaryWrites,
      findings: outcomes,
      stopped: stopped,
    };
  }

  return {
    run: run,
    replaceMarkedSegment: replaceMarkedSegment,
    replaceSummaryBlock: replaceSummaryBlock,
    HEADER: HEADER,
    noteFor: function (selectors) {
      const packed = selectorsFrom({ selectors: selectors });
      return "The comment is not pending until " + clean(packed["stage-review-button"]) + " is clicked.";
    },
  };
});
