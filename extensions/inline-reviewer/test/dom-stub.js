"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");

function selectors() {
  return JSON.parse(fs.readFileSync(path.join(root, "selectors.json"), "utf8"));
}

function splitCommas(selector) {
  return String(selector || "")
    .split(",")
    .map(function (part) {
      return part.trim();
    })
    .filter(Boolean);
}

function parseAttr(body) {
  const eq = body.indexOf("=");
  if (eq < 0) return { kind: "attr", name: body.trim().toLowerCase(), op: "present", value: "" };
  const name = body.slice(0, eq).trim().toLowerCase();
  let raw = body.slice(eq + 1).trim();
  const op = body.slice(eq).startsWith("*=") ? "*=" : body.slice(eq).startsWith("^=") ? "^=" : "=";
  if (op !== "=") raw = body.slice(eq + op.length).trim();
  if (
    (raw.charAt(0) === "'" && raw.charAt(raw.length - 1) === "'") ||
    (raw.charAt(0) === '"' && raw.charAt(raw.length - 1) === '"')
  ) {
    raw = raw.slice(1, -1);
  }
  return { kind: "attr", name: name, op: op, value: raw };
}

function parseCompound(source) {
  const tokens = [];
  let i = 0;
  const text = String(source || "").trim();
  while (i < text.length) {
    const ch = text.charAt(i);
    if (/\s/.test(ch)) return null;
    if (ch === "#") {
      const match = /^#([A-Za-z0-9_-]+)/.exec(text.slice(i));
      if (!match) return null;
      tokens.push({ kind: "id", value: match[1] });
      i += match[0].length;
      continue;
    }
    if (ch === ".") {
      const match = /^\.([A-Za-z0-9_-]+)/.exec(text.slice(i));
      if (!match) return null;
      tokens.push({ kind: "class", value: match[1] });
      i += match[0].length;
      continue;
    }
    if (ch === "[") {
      const end = text.indexOf("]", i);
      if (end < 0) return null;
      tokens.push(parseAttr(text.slice(i + 1, end)));
      i = end + 1;
      continue;
    }
    const match = /^[A-Za-z][A-Za-z0-9-]*/.exec(text.slice(i));
    if (!match) return null;
    tokens.push({ kind: "tag", value: match[0].toLowerCase() });
    i += match[0].length;
  }
  return tokens.length ? tokens : null;
}

function classHas(el, name) {
  const value = (el.getAttribute && el.getAttribute("class")) || "";
  return value.split(/\s+/).indexOf(name) !== -1;
}

function matches(el, selector) {
  const parts = splitCommas(selector);
  for (let i = 0; i < parts.length; i += 1) {
    const tokens = parseCompound(parts[i]);
    if (!tokens) continue;
    let ok = true;
    for (let t = 0; t < tokens.length; t += 1) {
      const token = tokens[t];
      if (token.kind === "tag" && String(el.tagName || "").toLowerCase() !== token.value) ok = false;
      if (token.kind === "id" && (el.getAttribute("id") || "") !== token.value) ok = false;
      if (token.kind === "class" && !classHas(el, token.value)) ok = false;
      if (token.kind === "attr") {
        const value = el.getAttribute(token.name);
        if (value == null) ok = false;
        else if (token.op === "=" && value !== token.value) ok = false;
        else if (token.op === "*=" && String(value).indexOf(token.value) === -1) ok = false;
        else if (token.op === "^=" && String(value).indexOf(token.value) !== 0) ok = false;
      }
      if (!ok) break;
    }
    if (ok) return true;
  }
  return false;
}

function watchProperty(el, key, initial) {
  let current = initial;
  let writes = 0;
  Object.defineProperty(el, key, {
    configurable: true,
    get: function () {
      return current;
    },
    set: function (value) {
      writes += 1;
      current = value;
    },
  });
  el[key + "Writes"] = function () {
    return writes;
  };
}

function createPage(options) {
  const opts = options || {};
  const packed = opts.selectors || selectors();
  const all = [];
  const events = [];
  let queries = 0;
  const findings = Array.isArray(opts.findings) && opts.findings.length ? opts.findings : [defaultFinding()];

  function makeElement(tag, attrs, children) {
    const el = {
      nodeType: 1,
      tagName: String(tag || "div").toUpperCase(),
      attrs: {},
      childNodes: [],
      parentNode: null,
      fired: [],
      directClicks: 0,
      disabled: false,
    };
    Object.keys(attrs || {}).forEach(function (key) {
      el.attrs[String(key).toLowerCase()] = String(attrs[key]);
    });
    el.getAttribute = function (name) {
      const key = String(name || "").toLowerCase();
      if (!Object.prototype.hasOwnProperty.call(el.attrs, key)) return null;
      return el.attrs[key];
    };
    el.setAttribute = function (name, value) {
      el.attrs[String(name).toLowerCase()] = String(value);
    };
    Object.defineProperty(el, "textContent", {
      configurable: true,
      get: function () {
        if (Object.prototype.hasOwnProperty.call(el, "_text")) return el._text;
        let out = "";
        for (let i = 0; i < el.childNodes.length; i += 1) {
          const child = el.childNodes[i];
          if (child.nodeType === 3) out += child.nodeValue || "";
          else if (child.nodeType === 1) out += child.textContent;
        }
        return out;
      },
      set: function (value) {
        el._text = String(value);
      },
    });
    el.dispatchEvent = function (event) {
      el.fired.push(event);
      events.push({ el: el, event: event });
      if (typeof el.onEvent === "function") el.onEvent(event);
    };
    el.click = function () {
      el.directClicks += 1;
      el.dispatchEvent({ type: "click", shiftKey: false, bubbles: true });
    };
    el.contains = function (other) {
      let cur = other;
      while (cur) {
        if (cur === el) return true;
        cur = cur.parentNode;
      }
      return false;
    };
    (children || []).forEach(function (child) {
      append(el, child);
    });
    return el;
  }

  function textNode(value) {
    return { nodeType: 3, nodeValue: String(value == null ? "" : value), parentNode: null };
  }

  function append(parent, child) {
    child.parentNode = parent;
    parent.childNodes.push(child);
    if (child.nodeType === 1 && all.indexOf(child) === -1) all.push(child);
  }

  function button(name, attrs) {
    const el = makeElement("button", Object.assign({ type: "button", "aria-label": name }, attrs || {}));
    append(el, textNode(name));
    return el;
  }

  function namedCount(name, type) {
    let count = 0;
    for (let i = 0; i < events.length; i += 1) {
      const event = events[i].event || {};
      if (type && event.type !== type) continue;
      const aria = events[i].el.getAttribute && events[i].el.getAttribute("aria-label");
      const label = aria || events[i].el.textContent || "";
      if (String(label).replace(/\s+/g, " ").trim() === name) count += 1;
    }
    return count;
  }

  const doc = makeElement("div", { id: "files" });
  doc.querySelectorAll = function (selector) {
    queries += 1;
    return all.filter(function (el) {
      return matches(el, selector);
    });
  };
  doc.querySelector = function (selector) {
    const found = doc.querySelectorAll(selector);
    return found[0] || null;
  };
  doc.reviewPilotAfterScroll = function () {};

  const fileList = makeElement("div", { "data-file-list": "" });
  let scrolls = 0;
  fileList.scrollBy = function () {
    scrolls += 1;
    if (typeof opts.onScroll === "function") opts.onScroll(scrolls, api);
  };
  append(doc, fileList);

  const filesByPath = {};
  function ensureFile(filePath) {
    const key = filePath || "src/Example.cs";
    if (filesByPath[key]) return filesByPath[key];
    const fileAttrs = { "data-collapsed": opts.collapsed ? "true" : "false" };
    if (!opts.pathOnAria) fileAttrs["data-file-path"] = key;
    const file = makeElement("div", fileAttrs);
    const table = opts.pathOnAria
      ? makeElement("table", { "aria-label": "Diff for: " + key, role: "grid" })
      : null;
    const expand = button("Toggle diff contents", { "data-expand-file": "" });
    const viewed = button("Viewed");
    expand.onEvent = function (event) {
      if (event.type !== "click") return;
      file.setAttribute("data-collapsed", "false");
      if (opts.hunkCollapsed) ensureHunk(file);
      else if (!filterHides()) mountLines(file);
    };
    append(file, expand);
    append(file, viewed);
    if (table) append(file, table);
    file.lineHost = table || file;
    file.reviewPath = key;
    append(fileList, file);
    filesByPath[key] = file;
    return file;
  }

  const filter = makeElement("input", { "data-file-filter": "", "aria-label": "File filter", type: "search" });
  watchProperty(filter, "value", opts.filter == null ? "" : String(opts.filter));
  filter.onEvent = function (event) {
    if (event.type !== "input") return;
    if (!filterHides() && !opts.collapsed && !opts.hunkCollapsed) mountLines();
  };
  append(fileList, filter);

  function filterHides() {
    const value = String(filter.value || "").trim();
    if (!value) return false;
    return findings.some(function (finding) {
      const filePath = finding && finding.path ? String(finding.path) : "";
      return filePath && filePath.toLowerCase().indexOf(value.toLowerCase()) === -1;
    });
  }

  const lineBag = [];
  function addLineSpec(filePath, side, line) {
    const id = String(filePath) + "\n" + side + "\n" + String(line);
    for (let i = 0; i < lineBag.length; i += 1) {
      const spec = lineBag[i];
      if (spec.path + "\n" + spec.side + "\n" + spec.line === id) return;
    }
    lineBag.push({ path: filePath, side: side, line: String(line), mounted: false });
  }

  function mountLines(onlyFile) {
    for (let i = 0; i < lineBag.length; i += 1) {
      const spec = lineBag[i];
      if (spec.mounted) continue;
      if (onlyFile && spec.path !== (onlyFile.getAttribute("data-file-path") || onlyFile.reviewPath)) continue;
      if (opts.collapsed && filesByPath[spec.path] && filesByPath[spec.path].getAttribute("data-collapsed") === "true") {
        continue;
      }
      if (filterHides()) continue;
      if (opts.hunkCollapsed && !spec.hunkOpen) continue;
      spec.mounted = true;
      const file = ensureFile(spec.path);
      const row = makeElement("tr", { class: "diff-line-row" });
      const numberCell = makeElement("td", {
        "data-diff-side": spec.side,
        "data-line-number": spec.line,
        "data-line-role": "number",
        class: "new-diff-line-number left-side",
      });
      append(numberCell, textNode(spec.line));
      numberCell.onEvent = function (event) {
        if (event.type === "mouseover" || event.type === "pointerenter") showPlus(row);
      };
      const codeCell = makeElement("td", {
        "data-diff-side": spec.side,
        "data-line-number": spec.line,
        "data-line-role": "text",
        class: "diff-text-cell left-side",
      });
      append(codeCell, textNode("return item;"));
      append(row, numberCell);
      append(row, codeCell);
      append(file.lineHost || file, row);
    }
  }

  function ensureHunk(file) {
    if (file.getAttribute("data-hunk") === "true") return;
    file.setAttribute("data-hunk", "true");
    const hunk = button("Expand Down", { "data-expand-hunk": "" });
    hunk.onEvent = function (event) {
      if (event.type !== "click") return;
      lineBag.forEach(function (spec) {
        if (spec.path === (file.getAttribute("data-file-path") || file.reviewPath)) spec.hunkOpen = true;
      });
      mountLines(file);
    };
    append(file, hunk);
  }

  const plusButtons = [];
  function showPlus(row) {
    if (row.getAttribute("data-plus") === "true") return;
    row.setAttribute("data-plus", "true");
    const label = opts.commentLabel || "+";
    const plus = label === "+"
      ? button("+", { "data-add-comment": "" })
      : button(label);
    plus.onEvent = function (event) {
      if (event.type !== "click") return;
      openComposer();
    };
    append(row, plus);
    plusButtons.push(plus);
  }

  const composers = [];
  const pendings = [];
  function openComposer() {
    const composer = makeElement("div", { "data-composer": "open" });
    const area = makeElement("textarea", { "aria-label": "Markdown value" });
    watchProperty(area, "value", "");
    const stage = button("Start a review");
    stage.disabled = opts.stage === "disabled" || opts.stage === "comment" ? true : true;
    if (opts.stage !== "comment") stage.disabled = true;
    area.onEvent = function (event) {
      if (event.type !== "input") return;
      if (opts.stage === "disabled") return;
      if (area.value) stage.disabled = false;
    };
    stage.onEvent = function (event) {
      if (event.type !== "click" || stage.disabled) return;
      composer.setAttribute("data-composer", "closed");
      const pending = makeElement("article", {
        class: "pending-review-comment",
        "data-review-pilot-comment": "pending",
        "data-unverified": "true",
      });
      append(pending, textNode(area.value));
      append(doc, pending);
      pendings.push(pending);
    };
    const comment = button("Comment");
    const cancel = button("Cancel");
    const addReview = button("Add review comment");
    if (opts.stage !== "comment") append(composer, stage);
    append(composer, area);
    append(composer, comment);
    append(composer, cancel);
    append(composer, addReview);
    append(doc, composer);
    composers.push(composer);
  }

  const toolbar = button("Submit review");
  const dialog = makeElement("div", {
    role: "dialog",
    "aria-label": "Finish your review",
    "data-open": "false",
  });
  const summary = makeElement("textarea", { "aria-label": "Markdown value" });
  watchProperty(summary, "value", opts.summaryValue == null ? "" : String(opts.summaryValue));
  const commentRadio = makeElement("input", { type: "radio", name: "reviewEvent", value: "comment" });
  const approveRadio = makeElement("input", { type: "radio", name: "reviewEvent", value: "approve" });
  const requestRadio = makeElement("input", { type: "radio", name: "reviewEvent", value: "request changes" });
  commentRadio.checked = true;
  approveRadio.checked = false;
  requestRadio.checked = false;
  watchProperty(commentRadio, "checked", true);
  watchProperty(approveRadio, "checked", false);
  watchProperty(requestRadio, "checked", false);
  watchProperty(commentRadio, "value", "comment");
  watchProperty(approveRadio, "value", "approve");
  watchProperty(requestRadio, "value", "request changes");
  const cancelReview = button("Cancel");
  const dialogSubmit = button("Submit review control enter");
  const dialogClose = button("Close", { "aria-label": "Close" });
  cancelReview.onEvent = function (event) {
    if (event.type === "click") dialog.setAttribute("data-open", "false");
  };
  dialogClose.onEvent = function (event) {
    if (event.type === "click") dialog.setAttribute("data-open", "false");
  };
  toolbar.onEvent = function (event) {
    if (event.type === "click") dialog.setAttribute("data-open", "true");
  };
  append(dialog, summary);
  append(dialog, commentRadio);
  append(dialog, approveRadio);
  append(dialog, requestRadio);
  append(dialog, cancelReview);
  append(dialog, dialogSubmit);
  append(dialog, dialogClose);
  append(doc, toolbar);
  append(doc, dialog);

  const commentsPanel = makeElement("div", { "data-panel": "comments", "aria-label": "Comments" });
  const panelArea = makeElement("textarea", { "aria-label": "Markdown value" });
  watchProperty(panelArea, "value", "panel note");
  append(commentsPanel, panelArea);
  append(doc, commentsPanel);

  const abandon = button("Abandon review");
  const discard = button("Discard review");
  const pageComment = button("Comment");
  append(doc, abandon);
  append(doc, discard);
  append(doc, pageComment);

  const neighbor = makeElement("div", {
    class: "markdown-body",
    "data-review-pilot-comment": "submitted",
    "data-path": findings[0].path || "src/Example.cs",
    "data-line": String(findings[0].line == null ? "" : findings[0].line),
    "data-side": findings[0].side || "RIGHT",
  });
  append(neighbor, textNode(opts.neighborText == null ? "Already noted on this line." : String(opts.neighborText)));
  const neighborArea = makeElement("textarea", { "aria-label": "Markdown value" });
  watchProperty(neighborArea, "value", "do not edit");
  append(neighbor, neighborArea);
  append(doc, neighbor);

  (opts.comments || []).forEach(function (comment) {
    const host = makeElement(comment.tag || "div", comment.attrs || {});
    append(host, textNode(comment.text || ""));
    if (comment.textarea != null) {
      const area = makeElement("textarea", { "aria-label": "Markdown value" });
      watchProperty(area, "value", comment.textarea);
      if (comment.composer) host.setAttribute("data-composer", "open");
      append(host, area);
      comment.area = area;
    }
    append(doc, host);
    comment.host = host;
  });

  const paths = {};
  findings.forEach(function (finding) {
    if (!finding || !finding.on_diff) return;
    const filePath = finding.path || "src/Example.cs";
    paths[filePath] = true;
    const side = String(finding.side || "RIGHT").toUpperCase() === "LEFT" ? "left" : "right";
    addLineSpec(filePath, side, finding.line);
    if (typeof finding.start_line === "number" && finding.start_line !== finding.line) {
      addLineSpec(filePath, side, finding.start_line);
    }
    if (opts.decoySide) addLineSpec(filePath, opts.decoySide, finding.line);
  });
  if (!Object.keys(paths).length) paths["src/Example.cs"] = true;
  Object.keys(paths).forEach(function (filePath) {
    const file = ensureFile(filePath);
    if (opts.hunkCollapsed && !opts.collapsed) ensureHunk(file);
  });
  if (opts.lines) {
    lineBag.length = 0;
    opts.lines.forEach(function (line) {
      lineBag.push({
        path: line.path,
        side: line.side,
        line: String(line.line),
        mounted: false,
        hunkOpen: line.hunkOpen === true,
      });
    });
  }
  if (!opts.collapsed && !opts.hunkCollapsed && !filterHides() && !opts.unmounted) {
    if (opts.mountOnScroll) {
      const original = fileList.scrollBy;
      fileList.scrollBy = function () {
        original();
        if (scrolls >= opts.mountOnScroll) mountLines();
      };
    } else mountLines();
  }

  const api = {
    document: doc,
    findings: findings,
    summary: summary,
    filter: filter,
    dialog: dialog,
    neighbor: neighbor,
    neighborArea: neighborArea,
    panelArea: panelArea,
    radios: { comment: commentRadio, approve: approveRadio, request: requestRadio },
    request: function (extra) {
      return Object.assign(
        {
          document: doc,
          selectors: packed,
          findings: findings,
          mode: opts.mode || "finding",
          findingId: opts.findingId || (findings[0] && findings[0].id) || "",
          summaryBlock: opts.summaryBlock || "",
          replaceModifiedDrafts: opts.replaceModifiedDrafts === true,
          confirmedIds: opts.confirmedIds || [],
          pendingTimeoutMs: Object.prototype.hasOwnProperty.call(opts, "pendingTimeoutMs") ? opts.pendingTimeoutMs : 0,
          scrollAttempts: opts.scrollAttempts,
        },
        extra || {}
      );
    },
    queries: function () {
      return queries;
    },
    resetQueries: function () {
      queries = 0;
    },
    clicks: function () {
      return events.length;
    },
    scrolls: function () {
      return scrolls;
    },
    fired: namedCount,
    forbiddenClicks: function () {
      const names = [
        "Comment",
        "Submit review control enter",
        "Add review comment",
        "Approve",
        "Request changes",
        "Abandon review",
        "Discard review",
        "Viewed",
        "Not Viewed",
        "Comment on this file",
      ];
      let count = 0;
      for (let i = 0; i < names.length; i += 1) count += namedCount(names[i], "click");
      return count;
    },
    directClicks: function () {
      let count = 0;
      for (let i = 0; i < all.length; i += 1) count += all[i].directClicks || 0;
      return count;
    },
    openComposers: function () {
      return composers.filter(function (composer) {
        return composer.getAttribute("data-composer") === "open";
      }).length;
    },
    pendingTexts: function () {
      return pendings.map(function (node) {
        return node.textContent;
      });
    },
    composerAreas: function () {
      return composers.map(function (composer) {
        const areas = composer.childNodes.filter(function (child) {
          return child.tagName === "TEXTAREA";
        });
        return areas[0] || null;
      });
    },
  };
  return api;
}

function defaultFinding() {
  return {
    id: "F001",
    title: "Latch",
    path: "src/Example.cs",
    line: 17,
    side: "RIGHT",
    on_diff: true,
    body: "Latch the gate.\n\nreview-pilot finding F001\n<!-- review-pilot:finding:F001 -->\n",
  };
}

module.exports = {
  createPage: createPage,
  selectors: selectors,
  defaultFinding: defaultFinding,
};
