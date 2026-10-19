(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotShaGate = api;
})(globalThis, function () {
  "use strict";

  const HYDRATION_TIMEOUT_MS = 8000;
  const SELECTOR_IDS = ["file-list", "commit-control", "hide-whitespace", "head-commit-link"];
  const FULL_SHA = /^[0-9a-f]{40}$/i;
  const HREF_SHA = /\/commits\/([0-9a-f]{40})(?![0-9a-f])/i;
  const VOID = {
    area: 1,
    base: 1,
    br: 1,
    col: 1,
    embed: 1,
    hr: 1,
    img: 1,
    input: 1,
    link: 1,
    meta: 1,
    source: 1,
    track: 1,
    wbr: 1,
  };

  function selectorsReady(selectors) {
    if (!selectors || typeof selectors !== "object") return false;
    for (let i = 0; i < SELECTOR_IDS.length; i += 1) {
      const value = selectors[SELECTOR_IDS[i]];
      if (typeof value !== "string" || !value.trim()) return false;
    }
    return true;
  }

  function cleanLabel(value) {
    return String(value == null ? "" : value)
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeFullSha(value) {
    const text = String(value == null ? "" : value).trim();
    return FULL_SHA.test(text) ? text.toLowerCase() : "";
  }

  function shaFromHref(href) {
    const match = HREF_SHA.exec(String(href == null ? "" : href));
    return match ? match[1].toLowerCase() : "";
  }

  function decode(value) {
    return String(value)
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&");
  }

  function emptyReading(timedOut) {
    return {
      hydrated: false,
      timedOut: Boolean(timedOut),
      fileListFound: false,
      commitControlFound: false,
      rangeLabel: "",
      whitespaceHidden: null,
      hideControlFound: false,
      headSha: "",
      headLinkFound: false,
      readOnly: true,
    };
  }

  function parseAttrs(raw) {
    const attrs = {};
    const re = /([^\s=/<>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let match;
    while ((match = re.exec(raw || ""))) {
      const value = match[2] != null ? match[2] : match[3] != null ? match[3] : match[4] != null ? match[4] : "";
      attrs[match[1].toLowerCase()] = decode(value);
    }
    return attrs;
  }

  function parseHtml(html) {
    const root = { type: "element", name: "root", attrs: {}, children: [] };
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z0-9]+)\s*>|<([a-zA-Z0-9]+)([^>]*?)(\/?)>|([^<]+)/g;
    let match;
    while ((match = re.exec(String(html || "")))) {
      if (match[0].indexOf("<!--") === 0) continue;
      if (match[1]) {
        const name = match[1].toLowerCase();
        for (let i = stack.length - 1; i > 0; i -= 1) {
          if (stack[i].name === name) {
            stack.length = i;
            break;
          }
        }
        continue;
      }
      if (match[2]) {
        const name = match[2].toLowerCase();
        const el = { type: "element", name: name, attrs: parseAttrs(match[3]), children: [] };
        stack[stack.length - 1].children.push(el);
        if (match[4] !== "/" && !VOID[name]) stack.push(el);
        continue;
      }
      if (match[5]) stack[stack.length - 1].children.push({ type: "text", value: decode(match[5]) });
    }
    return root;
  }

  function splitSelectorList(selector) {
    const parts = [];
    let current = "";
    let quote = "";
    const source = String(selector || "");
    for (let i = 0; i < source.length; i += 1) {
      const ch = source.charAt(i);
      if (quote) {
        current += ch;
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === "'" || ch === '"') {
        quote = ch;
        current += ch;
        continue;
      }
      if (ch === ",") {
        if (current.trim()) parts.push(current.trim());
        current = "";
        continue;
      }
      current += ch;
    }
    if (current.trim()) parts.push(current.trim());
    return parts;
  }

  function parseCompound(selector) {
    const source = String(selector || "").trim();
    if (!source) return null;
    const tokens = [];
    let i = 0;
    while (i < source.length) {
      const ch = source.charAt(i);
      if (/\s/.test(ch)) return null;
      if (ch === "#") {
        const match = /^#([A-Za-z0-9_-]+)/.exec(source.slice(i));
        if (!match) return null;
        tokens.push({ kind: "id", value: match[1] });
        i += match[0].length;
        continue;
      }
      if (ch === ".") {
        const match = /^\.([A-Za-z0-9_-]+)/.exec(source.slice(i));
        if (!match) return null;
        tokens.push({ kind: "class", value: match[1] });
        i += match[0].length;
        continue;
      }
      if (ch === "[") {
        const match = /^\[([A-Za-z0-9_-]+)(?:(\*=|\^=|=)(['"]?)([^'"\]]*?)\3)?\]/.exec(source.slice(i));
        if (!match) return null;
        tokens.push({
          kind: "attr",
          name: match[1].toLowerCase(),
          op: match[2] || "present",
          value: match[4] == null ? "" : match[4],
        });
        i += match[0].length;
        continue;
      }
      const match = /^[A-Za-z][A-Za-z0-9-]*/.exec(source.slice(i));
      if (!match) return null;
      tokens.push({ kind: "tag", value: match[0].toLowerCase() });
      i += match[0].length;
    }
    return tokens.length ? tokens : null;
  }

  function classHas(el, name) {
    const value = (el.attrs && el.attrs.class) || "";
    const parts = value.split(/\s+/);
    for (let i = 0; i < parts.length; i += 1) {
      if (parts[i] === name) return true;
    }
    return false;
  }

  function attrMatches(el, token) {
    if (!el.attrs || !Object.prototype.hasOwnProperty.call(el.attrs, token.name)) return false;
    const value = el.attrs[token.name];
    if (token.op === "present") return true;
    if (token.op === "=") return value === token.value;
    if (token.op === "*=") return String(value).indexOf(token.value) !== -1;
    if (token.op === "^=") return String(value).indexOf(token.value) === 0;
    return false;
  }

  function compoundMatches(el, tokens) {
    for (let i = 0; i < tokens.length; i += 1) {
      const token = tokens[i];
      if (token.kind === "tag" && el.name !== token.value) return false;
      if (token.kind === "id" && (el.attrs.id || "") !== token.value) return false;
      if (token.kind === "class" && !classHas(el, token.value)) return false;
      if (token.kind === "attr" && !attrMatches(el, token)) return false;
    }
    return true;
  }

  function elementMatches(el, selector) {
    const alternatives = splitSelectorList(selector);
    for (let i = 0; i < alternatives.length; i += 1) {
      const tokens = parseCompound(alternatives[i]);
      if (tokens && compoundMatches(el, tokens)) return true;
    }
    return false;
  }

  function walk(node, out) {
    if (!node || node.type !== "element") return;
    if (node.name !== "root") out.push(node);
    const children = node.children || [];
    for (let i = 0; i < children.length; i += 1) walk(children[i], out);
  }

  function firstMatch(rootNode, selector) {
    const list = [];
    walk(rootNode, list);
    for (let i = 0; i < list.length; i += 1) {
      if (elementMatches(list[i], selector)) return list[i];
    }
    return null;
  }

  function directParsedText(el) {
    let out = "";
    const children = (el && el.children) || [];
    for (let i = 0; i < children.length; i += 1) {
      if (children[i].type === "text") out += children[i].value;
    }
    return out;
  }

  function deepParsedText(el) {
    let out = "";
    const children = (el && el.children) || [];
    for (let i = 0; i < children.length; i += 1) {
      const child = children[i];
      if (child.type === "text") out += child.value;
      else if (child.type === "element") out += " " + deepParsedText(child) + " ";
    }
    return out;
  }

  function viewFromParsed(el) {
    return {
      tag: el.name,
      attr: function (name) {
        const key = String(name || "").toLowerCase();
        if (!el.attrs || !Object.prototype.hasOwnProperty.call(el.attrs, key)) return "";
        return el.attrs[key];
      },
      hasAttr: function (name) {
        const key = String(name || "").toLowerCase();
        return Boolean(el.attrs) && Object.prototype.hasOwnProperty.call(el.attrs, key);
      },
      directText: function () {
        return directParsedText(el);
      },
      deepText: function () {
        return deepParsedText(el);
      },
    };
  }

  function viewFromDom(el) {
    const liveChecked = el.checked;
    const checkedIsBoolean = typeof liveChecked === "boolean";
    return {
      tag: String(el.tagName || "").toLowerCase(),
      attr: function (name) {
        if (typeof el.getAttribute !== "function") return "";
        const value = el.getAttribute(name);
        return value == null ? "" : String(value);
      },
      hasAttr: function (name) {
        if (typeof el.hasAttribute === "function") return el.hasAttribute(name);
        if (typeof el.getAttribute !== "function") return false;
        return el.getAttribute(name) != null;
      },
      directText: function () {
        const nodes = el.childNodes || [];
        let out = "";
        for (let i = 0; i < nodes.length; i += 1) {
          if (nodes[i] && nodes[i].nodeType === 3) out += nodes[i].nodeValue || "";
        }
        return out;
      },
      deepText: function () {
        return el.textContent == null ? "" : String(el.textContent);
      },
      checked: checkedIsBoolean ? liveChecked : undefined,
    };
  }

  function asView(el) {
    if (!el) return null;
    if (el.type === "element") return viewFromParsed(el);
    return viewFromDom(el);
  }

  function elementLabel(view) {
    if (!view) return "";
    const aria = cleanLabel(view.attr("aria-label"));
    if (aria) return aria;
    const direct = cleanLabel(view.directText());
    if (direct) return direct;
    return cleanLabel(view.deepText());
  }

  function whitespaceHidden(view) {
    if (!view) return null;
    if (view.tag === "input" && typeof view.checked === "boolean") return view.checked;
    const aria = cleanLabel(view.attr("aria-checked")).toLowerCase();
    if (aria === "true") return true;
    if (aria === "false") return false;
    if (view.tag === "input") return view.hasAttr("checked");
    return null;
  }

  function headFromView(view) {
    if (!view) return { headLinkFound: false, headSha: "" };
    const data = normalizeFullSha(view.attr("data-commit"));
    const hrefSha = shaFromHref(view.attr("href"));
    if (data && hrefSha && data !== hrefSha) return { headLinkFound: true, headSha: "" };
    return { headLinkFound: true, headSha: data || hrefSha || "" };
  }

  function readingFromViews(fileView, commitView, hideView, headView) {
    const rangeLabel = elementLabel(commitView);
    const head = headFromView(headView);
    const hidden = whitespaceHidden(hideView);
    const fileListFound = Boolean(fileView);
    const commitControlFound = Boolean(commitView);
    return {
      hydrated: fileListFound && commitControlFound && rangeLabel !== "",
      timedOut: false,
      fileListFound: fileListFound,
      commitControlFound: commitControlFound,
      rangeLabel: rangeLabel,
      whitespaceHidden: hidden,
      hideControlFound: Boolean(hideView),
      headSha: head.headSha,
      headLinkFound: head.headLinkFound,
      readOnly: true,
    };
  }

  function readRoot(doc, selectors) {
    if (!doc || typeof doc.querySelector !== "function" || !selectorsReady(selectors)) {
      return emptyReading(!selectorsReady(selectors));
    }
    function one(key) {
      try {
        return asView(doc.querySelector(selectors[key]));
      } catch (err) {
        return null;
      }
    }
    return readingFromViews(one("file-list"), one("commit-control"), one("hide-whitespace"), one("head-commit-link"));
  }

  function readHtml(html, selectors) {
    try {
      if (!selectorsReady(selectors)) return emptyReading(true);
      const rootNode = parseHtml(html);
      function one(key) {
        return asView(firstMatch(rootNode, selectors[key]));
      }
      return readingFromViews(one("file-list"), one("commit-control"), one("hide-whitespace"), one("head-commit-link"));
    } catch (err) {
      return emptyReading(true);
    }
  }

  function normalizeTimeout(value) {
    if (value == null) return HYDRATION_TIMEOUT_MS;
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return HYDRATION_TIMEOUT_MS;
    return number;
  }

  function waitForRoot(doc, selectors, options) {
    const opts = options || {};
    const timeoutMs = normalizeTimeout(opts.timeoutMs);
    const intervalMs = Math.max(1, Number(opts.intervalMs) || 100);
    const now = typeof opts.now === "function" ? opts.now : function () { return Date.now(); };
    const schedule = typeof opts.schedule === "function"
      ? opts.schedule
      : function (fn, ms) { setTimeout(fn, ms); };
    const maxTicks = Math.max(1, Math.ceil(timeoutMs / intervalMs) + 1);
    return new Promise(function (resolve) {
      const start = now();
      let ticks = 0;
      function finish(reading, timedOut) {
        const result = Object.assign(emptyReading(false), reading || {});
        if (timedOut) {
          result.timedOut = true;
          result.hydrated = false;
        }
        result.readOnly = true;
        resolve(result);
      }
      function tick() {
        let reading;
        try {
          reading = readRoot(doc, selectors);
        } catch (err) {
          finish(emptyReading(false), true);
          return;
        }
        if (reading.hydrated) {
          finish(reading, false);
          return;
        }
        ticks += 1;
        if (ticks > maxTicks || now() - start >= timeoutMs) {
          finish(reading, true);
          return;
        }
        schedule(tick, intervalMs);
      }
      tick();
    });
  }

  function pageDocument() {
    const scope = globalThis;
    const doc = scope.document;
    if (!doc || typeof doc.querySelector !== "function") return null;
    return doc;
  }

  function observePage(options) {
    const opts = options || {};
    const doc = pageDocument();
    if (!doc || !selectorsReady(opts.selectors)) return Promise.resolve(emptyReading(true));
    return waitForRoot(doc, opts.selectors, opts);
  }

  function matchCounts(reading) {
    const source = reading || emptyReading(false);
    return (
      "file-list matches " + (source.fileListFound ? "1" : "0") +
      ". commit-control matches " + (source.commitControlFound ? "1" : "0") +
      ". hide-whitespace matches " + (source.hideControlFound ? "1" : "0") +
      ". head-commit-link matches " + (source.headLinkFound ? "1" : "0") +
      "."
    );
  }

  function logStamp(now) {
    const clock = typeof now === "function" ? now : function () { return Date.now(); };
    let value;
    try {
      value = clock();
    } catch (err) {
      value = Date.now();
    }
    try {
      return new Date(value).toISOString();
    } catch (err) {
      return "";
    }
  }

  function gateText(model) {
    const parts = [];
    if (model.issue) parts.push("issue " + model.issue + ".");
    if (model.pr) parts.push("PR " + model.pr + ".");
    parts.push("expected SHA " + (model.expectedSha || "(unavailable)") + ".");
    parts.push("observed range " + (model.observedRange || "(unavailable)") + ".");
    if (model.observedHead) parts.push("observed head " + model.observedHead + ".");
    else parts.push("observed head (unavailable). full head SHA not found.");
    if (model.whitespaceHidden === true) parts.push("Hide whitespace is on.");
    else if (model.whitespaceHidden == null && model.hydrated && !model.timedOut) {
      parts.push("Hide whitespace was not read.");
    }
    if (model.timedOut) parts.push("File list or commit control did not hydrate.");
    return (model.pass ? "SHA gate passed." : "Prepare is blocked.") + " " + parts.join(" ");
  }

  function evaluate(reading, context) {
    const source = reading && typeof reading === "object" ? reading : emptyReading(true);
    const ctx = context && typeof context === "object" ? context : {};
    const expectedSha = ctx.expectedSha == null ? "" : String(ctx.expectedSha).trim();
    const expectedNorm = normalizeFullSha(expectedSha);
    const observedHead = normalizeFullSha(source.headSha);
    const observedRange = source.rangeLabel == null ? "" : String(source.rangeLabel);
    const issue = ctx.issue == null ? "" : String(ctx.issue);
    const pr = ctx.pr == null ? "" : String(ctx.pr);
    const whitespaceHidden = source.whitespaceHidden === true ? true : source.whitespaceHidden === false ? false : null;
    const hydrated = source.hydrated === true && source.timedOut !== true;
    const pass =
      hydrated &&
      observedRange === "All commits" &&
      whitespaceHidden === false &&
      Boolean(expectedNorm) &&
      Boolean(observedHead) &&
      expectedNorm === observedHead;
    const message = gateText({
      pass: pass,
      expectedSha: expectedSha,
      observedRange: observedRange,
      observedHead: observedHead,
      whitespaceHidden: whitespaceHidden,
      hydrated: hydrated,
      timedOut: source.timedOut === true,
      issue: issue,
      pr: pr,
    });
    return {
      status: pass ? "pass" : "blocked",
      expectedSha: expectedSha,
      observedRange: observedRange,
      observedHead: observedHead,
      whitespaceHidden: whitespaceHidden,
      hydrated: hydrated,
      timedOut: source.timedOut === true,
      issue: issue,
      pr: pr,
      message: message,
      log: logStamp(ctx.now) + " " + matchCounts(source) + " " + message,
    };
  }

  function blocksPrepare(gate) {
    return !gate || gate.status !== "pass";
  }

  function scanBlocked(gate, requested) {
    return requested === true || blocksPrepare(gate);
  }

  function plainResult(status, log) {
    return {
      status: status,
      acted: false,
      readOnly: true,
      log: log || [],
      actions: [],
      inserts: 0,
      summaryWrites: 0,
      findings: [],
    };
  }

  // A blocked gate returns before any page write. A passing gate may act when
  // the caller supplies a prepare request; with no request there is nothing to write.
  function prepare(gate, request) {
    if (blocksPrepare(gate)) return plainResult("blocked");
    const runner = globalThis.ReviewPilotPrepare;
    if (!runner || typeof runner.run !== "function" || !request || typeof request !== "object") {
      return plainResult("pass");
    }
    try {
      return runner.run(gate, request);
    } catch (err) {
      return plainResult("blocked", ["DOM failure. Prepare stopped."]);
    }
  }

  return {
    HYDRATION_TIMEOUT_MS: HYDRATION_TIMEOUT_MS,
    SELECTOR_IDS: SELECTOR_IDS,
    selectorsReady: selectorsReady,
    readHtml: readHtml,
    readRoot: readRoot,
    waitForRoot: waitForRoot,
    observePage: observePage,
    evaluate: evaluate,
    prepare: prepare,
    blocksPrepare: blocksPrepare,
    scanBlocked: scanBlocked,
  };
});
