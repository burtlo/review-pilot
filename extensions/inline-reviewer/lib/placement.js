(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotPlacement = api;
})(globalThis, function () {
  "use strict";

  const BLOCK = {
    address: 1,
    article: 1,
    blockquote: 1,
    br: 1,
    div: 1,
    h1: 1,
    h2: 1,
    h3: 1,
    h4: 1,
    h5: 1,
    h6: 1,
    li: 1,
    ol: 1,
    p: 1,
    pre: 1,
    section: 1,
    table: 1,
    tr: 1,
    ul: 1,
  };
  const VOID = { area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1, input: 1, link: 1, meta: 1, source: 1, track: 1, wbr: 1 };
  const SUMMARY_HEADER = "## Findings outside the diff";
  const HOST_CLASS = /(?:^|\s)(?:markdown-body|comment-body|pending-review-comment)(?:\s|$)/;

  function collapseWhitespace(value) {
    return String(value == null ? "" : value)
      .replace(/\s+/g, " ")
      .trim();
  }

  function stripHtmlComments(value) {
    return String(value == null ? "" : value).replace(/<!--[\s\S]*?-->/g, " ");
  }

  function decodeEntities(value) {
    return String(value)
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&");
  }

  function findingMarkerLine(id) {
    return "review-pilot finding " + String(id == null ? "" : id);
  }

  function markerIndex(collapsed, id) {
    if (!id) return -1;
    const needle = findingMarkerLine(id);
    let from = 0;
    while (from <= collapsed.length) {
      const at = collapsed.indexOf(needle, from);
      if (at < 0) return -1;
      const beforeOk = at === 0 || /\s/.test(collapsed.charAt(at - 1));
      const afterAt = at + needle.length;
      const afterOk = afterAt === collapsed.length || /\s/.test(collapsed.charAt(afterAt));
      if (beforeOk && afterOk) return at;
      from = at + 1;
    }
    return -1;
  }

  function hasMarker(text, id) {
    return markerIndex(collapseWhitespace(stripHtmlComments(text)), id) >= 0;
  }

  function markerIds(text) {
    const collapsed = collapseWhitespace(stripHtmlComments(text));
    const ids = [];
    const re = /(?:^|\s)review-pilot finding ([^\s]+)/g;
    let match;
    while ((match = re.exec(collapsed))) ids.push(match[1]);
    return ids;
  }

  function expectedRendered(finding) {
    const id = finding && finding.id == null ? "" : String(finding.id);
    const scan = collapseWhitespace(stripHtmlComments(finding && finding.scan_text));
    if (!id) return scan;
    if (hasMarker(scan, id)) return scan;
    return collapseWhitespace(scan + " " + findingMarkerLine(id));
  }

  function segmentEndingAtMarker(collapsed, id) {
    const at = markerIndex(collapsed, id);
    if (at < 0) return null;
    const end = at + findingMarkerLine(id).length;
    const prior = collapsed.lastIndexOf("review-pilot finding ", at - 1);
    let start = 0;
    if (prior >= 0) {
      let idEnd = prior + "review-pilot finding ".length;
      while (idEnd < collapsed.length && !/\s/.test(collapsed.charAt(idEnd))) idEnd += 1;
      start = Math.min(end, idEnd + 1);
    }
    return collapsed.slice(start, end).trim();
  }

  function matchesScan(rendered, finding) {
    const expected = expectedRendered(finding);
    if (!expected) return false;
    const id = finding && finding.id == null ? "" : String(finding.id);
    const collapsed = collapseWhitespace(stripHtmlComments(rendered));
    if (collapsed === expected) return true;
    const segment = segmentEndingAtMarker(collapsed, id);
    if (segment == null) return false;
    if (segment === expected) return true;
    return segment === SUMMARY_HEADER + " " + expected;
  }

  function parseAttrs(raw) {
    const attrs = {};
    const re = /([^\s=/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"']+)))?/g;
    let match;
    while ((match = re.exec(raw || ""))) {
      const value = match[2] != null ? match[2] : match[3] != null ? match[3] : match[4] != null ? match[4] : "";
      attrs[match[1].toLowerCase()] = decodeEntities(value);
    }
    return attrs;
  }

  function parseHtml(html) {
    const root = { type: "element", name: "root", attrs: {}, children: [] };
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z0-9]+)\s*>|<([a-zA-Z0-9]+)([^>]*?)(\/?)>|([^<]+)/g;
    let match;
    while ((match = re.exec(String(html || "")))) {
      if (match[0].startsWith("<!--")) continue;
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
      if (match[5]) stack[stack.length - 1].children.push({ type: "text", value: decodeEntities(match[5]) });
    }
    return root;
  }

  function textFromTree(el) {
    if (!el || el.type !== "element") return "";
    if (el.name === "script" || el.name === "style") return "";
    let out = "";
    const children = el.children || [];
    for (let i = 0; i < children.length; i += 1) {
      const child = children[i];
      if (child.type === "text") out += child.value;
      else if (child.type === "element") out += textFromTree(child);
    }
    if (BLOCK[el.name]) out += "\n";
    return out;
  }

  function treeContains(parent, child) {
    const children = (parent && parent.children) || [];
    for (let i = 0; i < children.length; i += 1) {
      const kid = children[i];
      if (kid === child) return true;
      if (kid.type === "element" && treeContains(kid, child)) return true;
    }
    return false;
  }

  function allElements(node, out) {
    if (!node || node.type !== "element") return out;
    if (node.name !== "root") out.push(node);
    const children = node.children || [];
    for (let i = 0; i < children.length; i += 1) allElements(children[i], out);
    return out;
  }

  function classNameOf(el) {
    if (!el) return "";
    if (typeof el.getAttribute === "function") return el.getAttribute("class") || "";
    return (el.attrs && el.attrs.class) || "";
  }

  function kindOf(el) {
    if (!el) return "";
    if (typeof el.getAttribute === "function") return (el.getAttribute("data-review-pilot-comment") || "").toLowerCase();
    return ((el.attrs && el.attrs["data-review-pilot-comment"]) || "").toLowerCase();
  }

  function attrOf(el, name) {
    if (!el) return "";
    if (typeof el.getAttribute === "function") return el.getAttribute(name) || "";
    return (el.attrs && el.attrs[name]) || "";
  }

  function isHostClass(el) {
    return HOST_CLASS.test(classNameOf(el));
  }

  function regionFor(el) {
    const kind = kindOf(el);
    if (kind === "pending" || kind === "draft") return "pending";
    if (kind === "summary") return "summary";
    if (kind === "submitted" || kind === "comments-panel" || kind === "published") return "submitted";
    if (/(?:^|\s)pending-review-comment(?:\s|$)/.test(classNameOf(el))) return "pending";
    return "submitted";
  }

  function lineOf(el) {
    const text = attrOf(el, "data-line");
    return /^-?\d+$/.test(text) ? Number(text) : null;
  }

  function textOf(el) {
    if (!el) return "";
    if (el.type === "element") return textFromTree(el);
    return textFromDom(el);
  }

  function textFromDom(node) {
    if (!node) return "";
    const type = node.nodeType;
    if (type === 3) return node.nodeValue || "";
    if (type === 8) return "";
    if (type !== 1) return "";
    const name = String(node.tagName || "").toLowerCase();
    if (name === "script" || name === "style") return "";
    let out = "";
    const children = node.childNodes || [];
    for (let i = 0; i < children.length; i += 1) out += textFromDom(children[i]);
    if (BLOCK[name]) out += "\n";
    return out;
  }

  function toComment(el) {
    const region = regionFor(el);
    const path = attrOf(el, "data-path");
    const side = attrOf(el, "data-side");
    return {
      region: region,
      path: path || null,
      line: lineOf(el),
      side: side || null,
      text: textOf(el),
      unverified: region === "pending" || region === "summary" || attrOf(el, "data-unverified") === "true",
    };
  }

  function innermostHosts(elements, contains) {
    const hosts = elements.filter(function (el) {
      return !kindOf(el) && isHostClass(el) && markerIds(textOf(el)).length > 0;
    });
    return hosts.filter(function (el) {
      return !hosts.some(function (other) {
        return other !== el && contains(el, other);
      });
    });
  }

  function commentsFromElements(elements, contains) {
    const explicit = elements.filter(function (el) {
      return kindOf(el);
    });
    const chosen = explicit.length ? explicit : innermostHosts(elements, contains);
    return chosen.map(toComment);
  }

  function collectFromTree(rootNode) {
    return commentsFromElements(allElements(rootNode, []), treeContains);
  }

  function collectFromDom(doc) {
    if (!doc || typeof doc.querySelectorAll !== "function") return [];
    const nodes = doc.querySelectorAll(
      "[data-review-pilot-comment], .markdown-body, .comment-body, .pending-review-comment"
    );
    const list = [];
    for (let i = 0; i < nodes.length; i += 1) list.push(nodes[i]);
    return commentsFromElements(list, function (parent, child) {
      return typeof parent.contains === "function" && parent.contains(child);
    });
  }

  function collectComments(root) {
    const doc = root || (typeof document === "undefined" ? null : document);
    if (!doc) return [];
    if (typeof doc.querySelectorAll === "function") return collectFromDom(doc);
    if (doc.type === "element") return collectFromTree(doc);
    return [];
  }

  function readCommentsFromHtml(html) {
    return collectFromTree(parseHtml(html));
  }

  function isConfirmed(options, id) {
    const bag = options && options.confirmedIds;
    if (!bag || !id) return false;
    if (typeof bag.has === "function") return bag.has(id);
    if (Array.isArray(bag)) return bag.indexOf(id) !== -1;
    return false;
  }

  function summaryAvailable(comments) {
    return comments.some(function (comment) {
      return comment && comment.region === "summary";
    });
  }

  function targetOf(comment) {
    return {
      region: comment.region,
      path: comment.path,
      line: comment.line,
      side: comment.side,
    };
  }

  function classifyFinding(finding, comments, options) {
    const source = finding && typeof finding === "object" ? finding : {};
    const opts = options || {};
    const id = source.id == null ? "" : String(source.id);
    const onDiff = Boolean(source.on_diff);
    const row = {
      id: id,
      placement: onDiff ? "inline" : "not-on-diff",
      onDiff: onDiff,
      confirmRequired: false,
      observed: "",
      snapshotText: "",
      target: null,
    };
    if (opts.blocked === true || source.blocked === true) {
      row.status = "blocked";
      row.outcome = null;
      return row;
    }
    const hits = [];
    for (let i = 0; i < comments.length; i += 1) {
      if (hasMarker(comments[i].text, id)) hits.push(comments[i]);
    }
    const pending = hits.filter(function (comment) {
      return comment.region === "pending" || comment.region === "summary";
    });
    const submitted = hits.filter(function (comment) {
      return comment.region !== "pending" && comment.region !== "summary";
    });
    const hit = pending[0] || submitted[0] || null;
    if (!hit) {
      const available = onDiff || summaryAvailable(comments);
      row.status = "not_placed";
      row.outcome = available ? "fill" : null;
      return row;
    }
    const matched = matchesScan(hit.text, source);
    const observed = collapseWhitespace(stripHtmlComments(hit.text));
    row.observed = observed;
    row.target = targetOf(hit);
    if (pending.length) {
      if (matched) {
        row.status = "draft";
        row.outcome = "skip_match";
        return row;
      }
      row.status = "draft_modified";
      row.outcome = "replace_draft";
      row.confirmRequired = !(opts.replaceModifiedDrafts === true || isConfirmed(opts, id));
      return row;
    }
    if (matched) {
      row.status = "published";
      row.outcome = "skip_match";
      return row;
    }
    row.status = "published_modified";
    row.outcome = "manual_only";
    row.snapshotText = expectedRendered(source);
    return row;
  }

  function scanPlacement(findings, source, options) {
    const comments = Array.isArray(source)
      ? source
      : readCommentsFromHtml(typeof source === "string" ? source : "");
    const list = Array.isArray(findings) ? findings : [];
    return {
      readOnly: true,
      comments: comments,
      findings: list.map(function (finding) {
        return classifyFinding(finding, comments, options);
      }),
    };
  }

  function refreshScan(findings, source, options) {
    return scanPlacement(findings, source, options);
  }

  function placementMap(rows) {
    const map = {};
    const list = Array.isArray(rows) ? rows : [];
    for (let i = 0; i < list.length; i += 1) {
      if (list[i] && list[i].id) map[list[i].id] = list[i];
    }
    return map;
  }

  return {
    collapseWhitespace: collapseWhitespace,
    findingMarkerLine: findingMarkerLine,
    markerIds: markerIds,
    hasMarker: hasMarker,
    matchesScan: matchesScan,
    expectedRendered: expectedRendered,
    readCommentsFromHtml: readCommentsFromHtml,
    collectComments: collectComments,
    scanPlacement: scanPlacement,
    refreshScan: refreshScan,
    placementMap: placementMap,
  };
});
