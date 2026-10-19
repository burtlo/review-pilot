(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotDebug = api;
})(globalThis, function () {
  "use strict";

  const STORAGE_KEY = "selectorOverrides";
  const SNIPPET_LIMIT = 180;
  const FAILURES = {
    collapsed_file: true,
    line_off_screen: true,
    hunk_not_loaded: true,
  };
  const ATTRIBUTE_HINTS = {
    "line-number": ["data-line-number", "data-diff-side"],
    "add-comment-button": ["data-add-comment"],
    "file-block": ["data-file-path", "data-path"],
    "expand-file": ["data-expand-file"],
    "expand-hunk": ["data-expand-hunk"],
    "file-list": ["data-file-list"],
    "file-filter": ["data-file-filter"],
    "head-commit-link": ["data-commit"],
    "hide-whitespace": ["data-hide-whitespace"],
    "commit-control": ["data-commit-control"],
    "comments-panel": ["data-panel"],
    "markdown-textarea": ["data-markdown"],
  };

  let detachPicker = null;

  function clean(value) {
    return String(value == null ? "" : value)
      .replace(/\s+/g, " ")
      .trim();
  }

  function stamp(now) {
    let value;
    try {
      value = typeof now === "function" ? now() : Date.now();
    } catch (err) {
      value = Date.now();
    }
    try {
      return new Date(value).toISOString() + " ";
    } catch (err2) {
      return "";
    }
  }

  function truncate(value, limit) {
    const text = String(value == null ? "" : value);
    const max = limit > 0 ? limit : SNIPPET_LIMIT;
    if (text.length <= max) return text;
    return text.slice(0, max);
  }

  function pageDocument(request) {
    if (request && request.document) return request.document;
    const doc = globalThis.document;
    if (!doc) return null;
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

  function matchCount(doc, selector) {
    return queryAll(doc, selector).length;
  }

  function attr(el, name) {
    if (!el || typeof el.getAttribute !== "function") return "";
    const value = el.getAttribute(name);
    return value == null ? "" : String(value);
  }

  function attributeNames(el) {
    if (!el) return [];
    if (el.attrs && typeof el.attrs === "object") return Object.keys(el.attrs);
    if (el.attributes && typeof el.attributes.length === "number") {
      const names = [];
      for (let i = 0; i < el.attributes.length; i += 1) {
        const item = el.attributes[i];
        const name = item && (item.name || item.nodeName);
        if (name) names.push(String(name).toLowerCase());
      }
      return names;
    }
    return [];
  }

  function textOf(el) {
    if (!el || el.textContent == null) return "";
    return String(el.textContent);
  }

  function accessibleName(el) {
    const aria = clean(attr(el, "aria-label"));
    if (aria) return aria;
    return clean(textOf(el)).slice(0, 80);
  }

  function containsNode(parent, child) {
    let cur = child;
    while (cur) {
      if (cur === parent) return true;
      cur = cur.parentNode || cur.parentElement || null;
    }
    return false;
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

  function diffSide(side) {
    const value = String(side || "RIGHT").toUpperCase();
    if (value === "LEFT") return "left";
    if (value === "RIGHT") return "right";
    return value.toLowerCase();
  }

  function parseLine(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    const text = String(value == null ? "" : value).trim();
    if (!/^[0-9]+$/.test(text)) return null;
    return Number(text);
  }

  function sanitizeOverrides(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const out = {};
    Object.keys(raw).forEach(function (key) {
      if (key === STORAGE_KEY) return;
      if (typeof raw[key] !== "string") return;
      const value = raw[key].trim();
      if (!value) return;
      out[key] = value;
    });
    return out;
  }

  function readOverrides(stored) {
    const bag = stored && typeof stored === "object" ? stored : {};
    if (Object.prototype.hasOwnProperty.call(bag, STORAGE_KEY)) return sanitizeOverrides(bag[STORAGE_KEY]);
    return sanitizeOverrides(bag);
  }

  function writeOverride(overrides, id, query) {
    const next = sanitizeOverrides(overrides);
    const key = typeof id === "string" ? id.trim() : "";
    const value = typeof query === "string" ? query.trim() : "";
    if (!key || !value) return next;
    next[key] = value;
    return next;
  }

  function clearOverrides() {
    return {};
  }

  function mergeSelectors(defaults, overrides) {
    const base = defaults && typeof defaults === "object" && !Array.isArray(defaults) ? defaults : {};
    const extra = sanitizeOverrides(overrides);
    const merged = {};
    Object.keys(base).forEach(function (key) {
      merged[key] = base[key];
    });
    Object.keys(extra).forEach(function (key) {
      merged[key] = extra[key];
    });
    return merged;
  }

  function lookup(defaults, overrides, id) {
    return mergeSelectors(defaults, overrides)[id];
  }

  function cssEscape(value) {
    return String(value == null ? "" : value)
      .replace(/\\/g, "\\\\")
      .replace(/'/g, "\\'");
  }

  function dataAttributeNames(el) {
    return attributeNames(el).filter(function (name) {
      return name.indexOf("data-") === 0;
    });
  }

  function preferAttribute(names, selectorId) {
    const hints = ATTRIBUTE_HINTS[selectorId] || [];
    for (let i = 0; i < hints.length; i += 1) {
      if (names.indexOf(hints[i]) !== -1) return hints[i];
    }
    return names[0] || "";
  }

  function attributeQuery(el, name) {
    if (!name) return "";
    const value = attr(el, name);
    if (!value || /^[0-9]+$/.test(value) || value.indexOf("/") !== -1 || value.length > 48) {
      return "[" + name + "]";
    }
    return "[" + name + "='" + cssEscape(value) + "']";
  }

  function cssPath(el) {
    const id = attr(el, "id");
    if (id && /^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) return "#" + id;
    const aria = attr(el, "aria-label");
    if (aria) return "[aria-label='" + cssEscape(aria) + "']";
    const parts = [];
    let cur = el;
    let depth = 0;
    while (cur && depth < 4) {
      const tag = String(cur.tagName || "").toLowerCase();
      if (!tag) break;
      let piece = tag;
      const className = attr(cur, "class").split(/\s+/).filter(Boolean)[0];
      if (className && /^[A-Za-z_-][A-Za-z0-9_-]*$/.test(className)) piece += "." + className;
      parts.unshift(piece);
      const parent = cur.parentNode || cur.parentElement || null;
      if (!parent || parent === cur) break;
      cur = parent;
      depth += 1;
    }
    return parts.join(" > ");
  }

  function queryForElement(el, selectorId) {
    if (!el) return "";
    const names = dataAttributeNames(el);
    if (names.length) return attributeQuery(el, preferAttribute(names, selectorId));
    return cssPath(el);
  }

  function eventElement(event) {
    const target = event && (event.target || event.srcElement);
    if (!target) return null;
    if (target.nodeType === 3) return target.parentElement || target.parentNode || null;
    return target;
  }

  function armPicker(options) {
    const opts = options || {};
    const doc = pageDocument(opts);
    const selectorId = typeof opts.selectorId === "string" ? opts.selectorId : "";
    if (typeof detachPicker === "function") detachPicker();
    detachPicker = null;
    if (!doc || typeof doc.addEventListener !== "function") {
      return Promise.resolve({ ok: false, selectorId: selectorId, query: "" });
    }
    return new Promise(function (resolve) {
      function detach() {
        if (typeof doc.removeEventListener === "function") doc.removeEventListener("click", finish, true);
        if (detachPicker === detach) detachPicker = null;
      }
      function finish(event) {
        detach();
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        if (event && typeof event.stopPropagation === "function") event.stopPropagation();
        const query = queryForElement(eventElement(event), selectorId);
        resolve({ ok: Boolean(query), selectorId: selectorId, query: query });
      }
      detachPicker = detach;
      doc.addEventListener("click", finish, true);
    });
  }

  function syntheticOpenTag(el) {
    const tag = String(el.tagName || "div").toLowerCase();
    const names = attributeNames(el).slice(0, 6);
    let attrs = "";
    for (let i = 0; i < names.length; i += 1) {
      const name = names[i];
      if (name === "class") continue;
      const value = attr(el, name);
      attrs += value ? " " + name + "=\"" + truncate(value, 40) + "\"" : " " + name;
    }
    const name = accessibleName(el);
    return "<" + tag + attrs + ">" + (name ? name : "");
  }

  function snippet(el) {
    if (!el) return "";
    let raw = "";
    if (typeof el.outerHTML === "string" && el.outerHTML.trim()) raw = el.outerHTML;
    else raw = syntheticOpenTag(el);
    const compact = raw.replace(/\s+/g, " ").trim();
    if (compact) return truncate(compact, SNIPPET_LIMIT);
    const name = accessibleName(el);
    return name ? "name " + truncate(name, SNIPPET_LIMIT) : "";
  }

  function matchLine(doc, selectorId, selector, now) {
    const found = queryAll(doc, selector);
    const detail = found.length ? snippet(found[0]) : "";
    const id = selectorId || "selector";
    return stamp(now) + id + " matches " + found.length + (detail ? ". " + detail : ".");
  }

  function formatDebugBundle(lines) {
    const list = Array.isArray(lines) ? lines : [];
    const kept = [];
    for (let i = 0; i < list.length; i += 1) {
      if (list[i]) kept.push(String(list[i]));
    }
    return kept.join("\n");
  }

  function copyDebugBundle(lines) {
    return formatDebugBundle(lines);
  }

  function isCollapsed(file) {
    if (!file) return false;
    if (attr(file, "data-collapsed") === "true") return true;
    if (attr(file, "aria-expanded") === "false") return true;
    return false;
  }

  function offScreen(el) {
    if (!el || typeof el.getBoundingClientRect !== "function") return false;
    let box;
    try {
      box = el.getBoundingClientRect();
    } catch (err) {
      return false;
    }
    if (!box) return false;
    const top = Number(box.top);
    const bottom = Number(box.bottom);
    const left = Number(box.left);
    const right = Number(box.right);
    if (![top, bottom, left, right].every(function (item) { return Number.isFinite(item); })) return false;
    const height = Number(globalThis.innerHeight) > 0 ? Number(globalThis.innerHeight) : 800;
    const width = Number(globalThis.innerWidth) > 0 ? Number(globalThis.innerWidth) : 1200;
    return bottom < 0 || top > height || right < 0 || left > width;
  }

  function findFile(doc, path, selectors) {
    const wanted = path ? String(path) : "";
    if (!wanted) return null;
    const files = queryAll(doc, selectors["file-block"]);
    for (let i = 0; i < files.length; i += 1) {
      if (attr(files[i], "data-file-path") === wanted || attr(files[i], "data-path") === wanted) return files[i];
    }
    return null;
  }

  function preferNumberCell(list, line) {
    const wanted = String(line);
    for (let i = 0; i < list.length; i += 1) {
      if (clean(textOf(list[i])) === wanted) return list[i];
    }
    for (let i = 0; i < list.length; i += 1) {
      if (attr(list[i], "data-line-role") === "number") return list[i];
    }
    return list[0] || null;
  }

  function findLine(doc, path, side, line, selectors) {
    if (line == null) return null;
    const nodes = queryAll(doc, selectors["line-number"]);
    const matches = [];
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i];
      if (attr(el, "data-diff-side").toLowerCase() !== side) continue;
      if (String(attr(el, "data-line-number")) !== String(line)) continue;
      const owner = filePathOf(el);
      if (path && owner && owner !== String(path)) continue;
      matches.push(el);
    }
    return preferNumberCell(matches, line);
  }

  function hunkPending(doc, file, selectors) {
    const buttons = queryAll(doc, selectors["expand-hunk"]);
    for (let i = 0; i < buttons.length; i += 1) {
      if (!file || containsNode(file, buttons[i])) return true;
    }
    return false;
  }

  function failureReason(doc, file, selectors, cell) {
    if (cell) return offScreen(cell) ? "line_off_screen" : "";
    if (file && isCollapsed(file)) return "collapsed_file";
    if (hunkPending(doc, file, selectors)) return "hunk_not_loaded";
    return "line_off_screen";
  }

  function rowOf(el) {
    let cur = el;
    while (cur) {
      if (String(cur.tagName || "").toLowerCase() === "tr") return cur;
      cur = cur.parentNode || cur.parentElement || null;
    }
    return el;
  }

  function highlight(el, kind) {
    if (!el || typeof el.setAttribute !== "function") return false;
    el.setAttribute("data-review-pilot-highlight", kind);
    return true;
  }

  function dispatch(el, type) {
    let event = { type: type, bubbles: true, target: el };
    try {
      if (typeof MouseEvent === "function") {
        event = new MouseEvent(type, { bubbles: true, cancelable: true });
      }
    } catch (err) {
      event = { type: type, bubbles: true, target: el };
    }
    if (typeof el.dispatchEvent === "function") el.dispatchEvent(event);
  }

  function ensureStyle(doc) {
    if (!doc || typeof doc.createElement !== "function" || typeof doc.querySelector !== "function") return;
    try {
      if (doc.querySelector("[data-review-pilot-style='highlight']")) return;
      const style = doc.createElement("style");
      if (!style || typeof style.setAttribute !== "function") return;
      style.setAttribute("data-review-pilot-style", "highlight");
      style.textContent = "[data-review-pilot-highlight]{outline:2px solid #0969da;outline-offset:1px}";
      const parent = doc.head || doc.documentElement || doc.body;
      if (parent && typeof parent.appendChild === "function") parent.appendChild(style);
    } catch (err) {
      return;
    }
  }

  function highlightCount(doc, kind) {
    return queryAll(doc, "[data-review-pilot-highlight='" + kind + "']").length;
  }

  function addButton(doc, row, selectors) {
    const found = queryAll(doc, selectors["add-comment-button"]);
    const inside = [];
    for (let i = 0; i < found.length; i += 1) {
      if (!row || containsNode(row, found[i])) inside.push(found[i]);
    }
    if (inside.length) return inside[inside.length - 1];
    return found.length ? found[found.length - 1] : null;
  }

  function selectorMap(request) {
    const packed = request && request.selectors && typeof request.selectors === "object" ? request.selectors : {};
    return packed;
  }

  function probe(request) {
    const req = request || {};
    const doc = pageDocument(req);
    const selectors = selectorMap(req);
    const now = req.now;
    const log = [];
    const path = req.path == null ? "" : String(req.path).trim();
    const line = parseLine(req.line);
    const start = parseLine(req.startLine != null ? req.startLine : req.start_line);
    const side = diffSide(req.side);
    const ids = ["file-block", "line-number", "expand-file", "expand-hunk", "add-comment-button"];
    for (let i = 0; i < ids.length; i += 1) {
      log.push(matchLine(doc, ids[i], selectors[ids[i]], now));
    }
    if (!doc || !path || line == null) {
      log.push(stamp(now) + "probe failed. reason line_off_screen.");
      return {
        status: "failed",
        reason: "line_off_screen",
        highlighted: false,
        highlights: { row: 0, range: 0, add: 0 },
        log: log,
        readOnly: true,
        acted: false,
      };
    }
    const file = findFile(doc, path, selectors);
    const cell = findLine(doc, path, side, line, selectors);
    const startCell = start != null && start !== line ? findLine(doc, path, side, start, selectors) : cell;
    let reason = failureReason(doc, file, selectors, cell);
    if (!reason && start != null && start !== line) reason = failureReason(doc, file, selectors, startCell);
    if (reason && FAILURES[reason]) {
      log.push(stamp(now) + "probe failed. reason " + reason + ".");
      return {
        status: "failed",
        reason: reason,
        highlighted: false,
        highlights: { row: 0, range: 0, add: 0 },
        log: log,
        readOnly: true,
        acted: false,
      };
    }
    ensureStyle(doc);
    const row = rowOf(cell);
    highlight(row, "row");
    highlight(cell, "range");
    if (startCell && startCell !== cell) highlight(startCell, "range");
    dispatch(cell, "mouseover");
    const plus = addButton(doc, row, selectors);
    if (plus) highlight(plus, "add");
    const highlights = {
      row: highlightCount(doc, "row"),
      range: highlightCount(doc, "range"),
      add: highlightCount(doc, "add"),
    };
    log.push(matchLine(doc, "add-comment-button", selectors["add-comment-button"], now));
    const marked = highlights.row > 0 && highlights.range > 0 && highlights.add > 0;
    if (!marked) {
      log.push(stamp(now) + "probe failed. reason line_off_screen.");
      return {
        status: "failed",
        reason: "line_off_screen",
        highlighted: false,
        highlights: highlights,
        log: log,
        readOnly: true,
        acted: false,
      };
    }
    log.push(
      stamp(now) +
        "probe highlighted. row " +
        highlights.row +
        ". range " +
        highlights.range +
        ". add " +
        highlights.add +
        "."
    );
    return {
      status: "highlighted",
      reason: "",
      highlighted: true,
      highlights: highlights,
      log: log,
      readOnly: true,
      acted: false,
    };
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    mergeSelectors: mergeSelectors,
    readOverrides: readOverrides,
    writeOverride: writeOverride,
    clearOverrides: clearOverrides,
    lookup: lookup,
    queryForElement: queryForElement,
    armPicker: armPicker,
    matchLine: matchLine,
    matchCount: matchCount,
    formatDebugBundle: formatDebugBundle,
    copyDebugBundle: copyDebugBundle,
    probe: probe,
  };
});
