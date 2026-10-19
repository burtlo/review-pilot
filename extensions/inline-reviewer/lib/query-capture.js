(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotQuery = api;
})(globalThis, function () {
  "use strict";

  const ISSUE_PARAM = "review_pilot_issue";
  const SHA_PARAM = "review_pilot_sha";
  const PULL_PATH = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/(changes|files)\/?$/;

  function stringField(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function sanitizeCapture(captured) {
    if (!captured || typeof captured !== "object") return null;
    const owner = stringField(captured.owner);
    const repo = stringField(captured.repo);
    const number = typeof captured.number === "number" ? captured.number : Number(captured.number);
    const view = captured.view === "files" || captured.view === "changes" ? captured.view : "";
    if (!owner || !repo || owner.includes("/") || repo.includes("/")) return null;
    if (!Number.isInteger(number) || number <= 0) return null;
    if (!view) return null;
    return {
      owner: owner,
      repo: repo,
      number: number,
      view: view,
      issue: stringField(captured.issue),
      sha: stringField(captured.sha),
    };
  }

  function parsePullUrl(href) {
    let url;
    try {
      url = new URL(href);
    } catch (err) {
      return null;
    }
    if (url.protocol !== "https:" || url.hostname !== "github.com") return null;
    const match = PULL_PATH.exec(url.pathname);
    if (!match) return null;
    return sanitizeCapture({
      owner: match[1],
      repo: match[2],
      number: Number(match[3]),
      view: match[4],
      issue: url.searchParams.get(ISSUE_PARAM) || "",
      sha: url.searchParams.get(SHA_PARAM) || "",
    });
  }

  function parseGitHubRepo(href) {
    let url;
    try {
      url = new URL(typeof href === "string" ? href : "");
    } catch (err) {
      return null;
    }
    if (url.protocol !== "https:" || url.hostname !== "github.com") return null;
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length < 2 || !parts[0] || !parts[1]) return null;
    if (parts[0].includes("/") || parts[1].includes("/")) return null;
    return { owner: parts[0], repo: parts[1] };
  }

  function captureAtDocumentStart(location) {
    const href = typeof location === "string" ? location : location && location.href;
    return parsePullUrl(href);
  }

  function mergeCapture(previous, next) {
    const incoming = sanitizeCapture(next);
    const prior = sanitizeCapture(previous);
    if (!incoming) return prior;
    if (!prior) return incoming;
    if (prior.owner !== incoming.owner || prior.repo !== incoming.repo || prior.number !== incoming.number) {
      return incoming;
    }
    return sanitizeCapture({
      owner: incoming.owner,
      repo: incoming.repo,
      number: incoming.number,
      view: incoming.view || prior.view,
      issue: incoming.issue || prior.issue,
      sha: incoming.sha || prior.sha,
    });
  }

  function resolveTabCapture(stored, liveHref) {
    const live = parsePullUrl(typeof liveHref === "string" ? liveHref : "");
    if (!live) return null;
    return mergeCapture(stored, live);
  }

  function describeTab(stored, liveHref) {
    const href = typeof liveHref === "string" ? liveHref : "";
    const captured = resolveTabCapture(stored, href);
    if (captured) {
      return { captured: captured, repo: { owner: captured.owner, repo: captured.repo } };
    }
    return { captured: null, repo: parseGitHubRepo(href) };
  }

  function pageUrl(captured) {
    const clean = sanitizeCapture(captured);
    if (!clean) return "";
    return (
      "https://github.com/" +
      clean.owner +
      "/" +
      clean.repo +
      "/pull/" +
      clean.number +
      "/" +
      clean.view
    );
  }

  return {
    ISSUE_PARAM: ISSUE_PARAM,
    SHA_PARAM: SHA_PARAM,
    sanitizeCapture: sanitizeCapture,
    parsePullUrl: parsePullUrl,
    captureAtDocumentStart: captureAtDocumentStart,
    mergeCapture: mergeCapture,
    resolveTabCapture: resolveTabCapture,
    describeTab: describeTab,
    pageUrl: pageUrl,
  };
});
