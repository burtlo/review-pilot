(function (root, factory) {
  "use strict";

  if (typeof module === "object" && module.exports) {
    if (!root.ReviewPilotAllowlist) require("./allowlist.js");
    if (!root.ReviewPilotQuery) require("./query-capture.js");
  }
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotSnapshot = api;
})(globalThis, function () {
  "use strict";

  const LOOPBACK_HOST = "127.0.0.1";
  const DEFAULT_PORT = 8765;

  function normalizePort(value) {
    if (value === undefined || value === null || value === "") return DEFAULT_PORT;
    const text = String(value).trim();
    if (!/^[0-9]+$/.test(text)) return null;
    const port = Number(text);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
    return port;
  }

  function normalizeSettings(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const token = typeof source.token === "string" ? source.token.trim() : "";
    const allowlist = typeof source.allowlist === "string" ? source.allowlist : "";
    const portValue = Object.prototype.hasOwnProperty.call(source, "port") ? source.port : DEFAULT_PORT;
    return {
      token: token,
      allowlist: allowlist,
      port: normalizePort(portValue),
      replaceModifiedDrafts: source.replaceModifiedDrafts === true,
    };
  }

  function buildSnapshotUrl(parts) {
    const url = new URL("http://" + LOOPBACK_HOST + ":" + parts.port + "/snapshot");
    url.searchParams.set("owner", parts.owner);
    url.searchParams.set("repo", parts.repo);
    url.searchParams.set("number", String(parts.number));
    url.searchParams.set("sha", parts.sha);
    return url.toString();
  }

  function repoIdentity(captured, repo) {
    if (captured) return { owner: captured.owner, repo: captured.repo };
    if (!repo || typeof repo !== "object") return null;
    if (typeof repo.owner !== "string" || typeof repo.repo !== "string") return null;
    const owner = repo.owner.trim();
    const repoName = repo.repo.trim();
    if (!owner || !repoName || owner.includes("/") || repoName.includes("/")) return null;
    return { owner: owner, repo: repoName };
  }

  function planSnapshotRequest(input) {
    const source = input || {};
    const captured = globalThis.ReviewPilotQuery.sanitizeCapture(source.captured);
    const settings = normalizeSettings(source.settings);
    const repo = repoIdentity(captured, source.repo);
    if (repo && !globalThis.ReviewPilotAllowlist.matchesAllowlist(settings.allowlist, repo.owner, repo.repo)) {
      return { ok: false, reason: "not-allowlisted", owner: repo.owner, repo: repo.repo };
    }
    if (!captured) return { ok: false, reason: "missing-pr" };
    if (!captured.sha) return { ok: false, reason: "missing-sha" };
    if (!settings.token) return { ok: false, reason: "missing-token" };
    if (settings.port == null) return { ok: false, reason: "bad-port" };
    return {
      ok: true,
      url: buildSnapshotUrl({
        port: settings.port,
        owner: captured.owner,
        repo: captured.repo,
        number: captured.number,
        sha: captured.sha,
      }),
      headers: {
        Authorization: "Bearer " + settings.token,
      },
    };
  }

  function reasonForStatus(status) {
    if (status === 401) return "unauthorized";
    if (status === 404) return "not-found";
    return "bridge-error";
  }

  async function fetchSnapshotIfAllowlisted(input) {
    const source = input || {};
    const plan = planSnapshotRequest(source);
    if (!plan.ok) {
      return {
        ok: false,
        called: false,
        reason: plan.reason,
        owner: plan.owner,
        repo: plan.repo,
      };
    }
    const doFetch = source.fetchImpl || fetch;
    let response;
    try {
      response = await doFetch(plan.url, {
        method: "GET",
        headers: plan.headers,
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
    } catch (err) {
      return { ok: false, called: true, reason: "bridge-unreachable" };
    }
    if (!response || !response.ok) {
      const status = response && response.status;
      if (response && typeof response.text === "function") {
        try {
          await response.text();
        } catch (err) {
          // The body is discarded so it cannot be copied into the panel.
        }
      }
      return {
        ok: false,
        called: true,
        reason: reasonForStatus(status),
        status: typeof status === "number" ? status : 0,
      };
    }
    let snapshot;
    try {
      snapshot = await response.json();
    } catch (err) {
      return { ok: false, called: true, reason: "bad-json" };
    }
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      return { ok: false, called: true, reason: "bad-json" };
    }
    return { ok: true, called: true, snapshot: snapshot };
  }

  return {
    LOOPBACK_HOST: LOOPBACK_HOST,
    DEFAULT_PORT: DEFAULT_PORT,
    normalizePort: normalizePort,
    normalizeSettings: normalizeSettings,
    buildSnapshotUrl: buildSnapshotUrl,
    planSnapshotRequest: planSnapshotRequest,
    fetchSnapshotIfAllowlisted: fetchSnapshotIfAllowlisted,
  };
});
