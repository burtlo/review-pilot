(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotPanel = api;
})(globalThis, function () {
  "use strict";

  const REASONS = {
    "missing-pr": "Open a GitHub pull request Files changed page.",
    "missing-sha": "This link has no review_pilot_sha. Open the pull request from review-ticket.",
    "missing-token": "Enter the bridge shared secret in Settings.",
    "bad-port": "Port must be an integer from 1 to 65535.",
    "bridge-unreachable":
      "Could not reach the local bridge. Start review-ticket serve-inline-review with REVIEW_PILOT_BRIDGE_TOKEN set in that process.",
    unauthorized: "The bridge rejected the shared secret.",
    "not-found": "The bridge has no snapshot for this pull request and reviewed SHA.",
    "bad-json": "The bridge returned a response that was not a snapshot.",
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function repoLabel(captured) {
    if (!captured || typeof captured.owner !== "string" || typeof captured.repo !== "string") {
      return "This repository";
    }
    if (!captured.owner || !captured.repo || captured.owner.includes("/") || captured.repo.includes("/")) {
      return "This repository";
    }
    return captured.owner + "/" + captured.repo;
  }

  function idleMessage(captured) {
    return (
      repoLabel(captured) +
      " is not on the allowlist. Review Pilot is idle and did not contact the bridge."
    );
  }

  function messageForReason(reason, status) {
    if (reason === "bridge-error" && Number.isInteger(status) && status > 0) {
      return "The bridge returned HTTP " + status + ".";
    }
    return REASONS[reason] || "The snapshot could not be loaded.";
  }

  function presentFinding(finding, placement) {
    if (!finding || typeof finding !== "object") return null;
    const placed = placement && typeof placement === "object" ? placement : {};
    const outcome = placed.outcome == null ? "" : String(placed.outcome);
    return {
      id: finding.id == null ? "" : String(finding.id),
      title: finding.title == null ? "" : String(finding.title),
      path: finding.path == null ? "" : String(finding.path),
      line: typeof finding.line === "number" ? finding.line : null,
      side: finding.side == null ? "" : String(finding.side),
      on_diff: Boolean(finding.on_diff),
      status: placed.status ? String(placed.status) : "not_placed",
      outcome: outcome,
      confirmRequired: Boolean(placed.confirmRequired),
      observed: outcome === "manual_only" && placed.observed ? String(placed.observed) : "",
      snapshotText: outcome === "manual_only" && placed.snapshotText ? String(placed.snapshotText) : "",
      note: placed.note ? String(placed.note) : "",
    };
  }

  function pathLine(finding) {
    if (!finding.path) return "";
    if (typeof finding.line === "number") return finding.path + ":" + finding.line;
    return finding.path;
  }

  function placementLabel(finding) {
    return finding.on_diff ? "inline" : "not on the current diff";
  }

  function panelFromPlan(input) {
    const source = input || {};
    const plan = source.plan || { ok: false, reason: "missing-pr" };
    const captured = source.captured;
    if (!plan.ok && plan.reason === "not-allowlisted") {
      const owner = typeof plan.owner === "string" ? plan.owner : captured && captured.owner;
      const repo = typeof plan.repo === "string" ? plan.repo : captured && captured.repo;
      return {
        mode: "idle",
        message: idleMessage({ owner: owner, repo: repo }),
        issue: "",
        pr: "",
        sha: "",
        findings: [],
      };
    }
    if (!plan.ok || !source.snapshot) {
      return {
        mode: "blocked",
        message: messageForReason(plan.ok ? "bad-json" : plan.reason, plan.status),
        issue: "",
        pr: "",
        sha: "",
        findings: [],
      };
    }
    const snapshot = source.snapshot;
    const placements = source.placements && typeof source.placements === "object" ? source.placements : {};
    const findings = Array.isArray(snapshot.findings)
      ? snapshot.findings
          .map(function (finding) {
            const id = finding && finding.id == null ? "" : String(finding.id);
            return presentFinding(finding, placements[id]);
          })
          .filter(Boolean)
      : [];
    return {
      mode: "snapshot",
      message: "",
      issue: snapshot.issue == null ? "" : String(snapshot.issue),
      pr: snapshot.pr == null ? "" : String(snapshot.pr),
      sha: snapshot.sha == null ? "" : String(snapshot.sha),
      findings: findings,
      gate: source.gate && typeof source.gate === "object" ? source.gate : null,
      activity: Array.isArray(source.activity)
        ? source.activity.map(function (line) {
            return String(line);
          })
        : [],
    };
  }

  function activityList(gate, activity) {
    const lines = [];
    if (gate) {
      const message = gate.message == null ? "" : String(gate.message);
      const log = gate.log == null || gate.log === "" ? message : String(gate.log);
      if (log) lines.push(log);
    }
    const extra = Array.isArray(activity) ? activity : [];
    for (let i = 0; i < extra.length; i += 1) {
      if (extra[i]) lines.push(String(extra[i]));
    }
    if (!lines.length) return "";
    return (
      '<ol class="activity-log">' +
      lines
        .map(function (line) {
          return "<li>" + escapeHtml(line) + "</li>";
        })
        .join("") +
      "</ol>"
    );
  }

  function renderGate(gate, activity) {
    const status = gate.status === "pass" ? "pass" : "blocked";
    const message = gate.message == null ? "" : String(gate.message);
    const head = gate.observedHead ? String(gate.observedHead) : "full head SHA not found";
    return (
      '<p class="banner gate" data-gate="' +
      status +
      '">' +
      escapeHtml(message) +
      "</p>" +
      '<dl class="gate-facts">' +
      "<dt>Expected SHA</dt><dd class=\"sha expected-sha\">" +
      escapeHtml(gate.expectedSha || "") +
      "</dd>" +
      "<dt>Observed range</dt><dd class=\"observed-range\">" +
      escapeHtml(gate.observedRange || "") +
      "</dd>" +
      "<dt>Observed head</dt><dd class=\"sha observed-head\">" +
      escapeHtml(head) +
      "</dd></dl>" +
      activityList(gate, activity)
    );
  }

  function applyPrepareResult(panel, result) {
    const model = panel && typeof panel === "object" ? panel : { findings: [] };
    const page = result && typeof result === "object" ? result : {};
    const rows = Array.isArray(page.findings) ? page.findings : [];
    const byId = {};
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i] && rows[i].id) byId[String(rows[i].id)] = rows[i];
    }
    const findings = (Array.isArray(model.findings) ? model.findings : []).map(function (finding) {
      const row = byId[String(finding.id)];
      if (!row) return finding;
      const next = Object.assign({}, finding);
      if (row.status) next.status = String(row.status);
      if (row.note) next.note = String(row.note);
      if (row.outcome) next.outcome = String(row.outcome);
      return next;
    });
    return Object.assign({}, model, {
      findings: findings,
      activity: Array.isArray(page.log)
        ? page.log.map(function (line) {
            return String(line);
          })
        : model.activity || [],
    });
  }

  function renderPanelHtml(panel) {
    const model = panel || { mode: "blocked", message: "" };
    if (model.mode !== "snapshot") {
      const state = model.mode === "idle" ? "idle" : "blocked";
      return '<p class="banner" data-state="' + state + '">' + escapeHtml(model.message || "") + "</p>";
    }
    const findings = Array.isArray(model.findings) ? model.findings : [];
    const items = findings
      .map(function (finding) {
        const prepareButton =
          '<button type="button" class="prepare-finding" data-prepare-finding="' +
          escapeHtml(finding.id) +
          '">Prepare</button>' +
          '<button type="button" class="dry-run-finding" data-dry-run-finding="' +
          escapeHtml(finding.id) +
          '">Dry-run</button>';
        const note = finding.note
          ? '<p class="prepare-note">' + escapeHtml(finding.note) + "</p>"
          : "";
        const confirm = finding.confirmRequired
          ? '<button type="button" class="confirm-replace" data-confirm-replace="' +
            escapeHtml(finding.id) +
            '">Confirm replace</button>'
          : "";
        const manual =
          finding.outcome === "manual_only"
            ? '<tr class="manual-detail"><td colspan="5"><p>No overwrite. Edit this comment on GitHub.</p><p class="snapshot-text">' +
              escapeHtml(finding.snapshotText) +
              '</p><p class="observed-text">' +
              escapeHtml(finding.observed) +
              "</p></td></tr>"
            : "";
        return (
          '<tr class="finding" data-finding-id="' +
          escapeHtml(finding.id) +
          '" data-status="' +
          escapeHtml(finding.status) +
          '" data-outcome="' +
          escapeHtml(finding.outcome) +
          '"><td class="finding-id">' +
          escapeHtml(finding.id) +
          '</td><td class="finding-title">' +
          escapeHtml(finding.title) +
          '</td><td class="finding-place">' +
          escapeHtml(pathLine(finding)) +
          '</td><td class="finding-kind">' +
          escapeHtml(placementLabel(finding)) +
          '</td><td class="finding-status">' +
          escapeHtml(finding.status) +
          prepareButton +
          note +
          confirm +
          "</td></tr>" +
          manual
        );
      })
      .join("");
    const list = findings.length
      ? '<table class="findings"><thead><tr><th>Id</th><th>Title</th><th>Path:line</th><th>Placement</th><th>Status</th></tr></thead><tbody>' +
        items +
        "</tbody></table>"
      : '<p class="empty-findings">The snapshot has no findings.</p>';
    const gateHtml = model.gate ? renderGate(model.gate, model.activity) : activityList(null, model.activity);
    const gateAttr = model.gate
      ? ' data-gate="' + (model.gate.status === "pass" ? "pass" : "blocked") + '"'
      : "";
    return (
      '<div data-state="snapshot"' +
      gateAttr +
      ">" +
      gateHtml +
      "<dl>" +
      "<dt>Issue</dt><dd>" +
      escapeHtml(model.issue) +
      "</dd>" +
      "<dt>PR</dt><dd>" +
      escapeHtml(model.pr) +
      "</dd>" +
      '<dt>Reviewed SHA</dt><dd class="sha">' +
      escapeHtml(model.sha) +
      "</dd></dl><h2>Findings</h2>" +
      list +
      "</div>"
    );
  }

  return {
    idleMessage: idleMessage,
    panelFromPlan: panelFromPlan,
    renderPanelHtml: renderPanelHtml,
    applyPrepareResult: applyPrepareResult,
    escapeHtml: escapeHtml,
  };
});
