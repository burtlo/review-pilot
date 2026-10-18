# Orchestration progress — tui-review-flow

Status: **complete**

| Package | Implement | Verify | Notes |
|---------|-----------|--------|-------|
| P1 | completed | pass | Shared header and decision panel. |
| P2 | completed | pass | Testing notes on the shared panel. Approve opens readiness after P3. |
| P3 | completed | pass | Readiness gate. CLI `--return` text unchanged. |
| P4 | completed | pass | Three tracks. Resume reaches testing without a publication receipt. |
| P14 | completed | pass | SHA move keeps old artifacts historical. Refresh is the only network path. |
| P13 | completed | pass | Status shows three tracks per PR from disk. |
| P5 | completed | pass | PR review hub with ticket disposition dock (P12). |
| P6 | completed | pass | Automated review preparation (Scenario D). |
| P7 | completed | pass | Automated finding triage (Scenario E). |
| P8 | completed | pass | Human code review track (§10). |
| P9 | completed | pass | GitHub publication (§13). Repair: COMMENT gated on manual; hub label tests. |
| P10 | completed | pass | Test environment view (§11). Repair: BLOCKED outcomes. |
| P11 | completed | pass | Functional testing (§12). Repair: digest must match environment for pass. |
| P12 | completed | pass | Ticket disposition (§15). Hub Approve/Reject dock. |

## Package P10

### Implementer (repair)
Status: completed. `environment_projection` sets `environment_outcome` to `BLOCKED` when the profile or SHA-matched digest is missing; transient errors still use `with_blocked_message`. Added `test_profile_without_digest_renders_blocked_on_mount`, `test_launch_compose_failure_renders_blocked` (`docker_compose_code=1`), and mount assertion for missing profile.

Tests: `python -m pytest tests/test_tui_environment.py -q --tb=short` — pass (8).

### Verifier
Verdict: **pass**. Findings: none.

Missing profile and missing digest show `Outcome: BLOCKED` on mount (digest uncertainty copy unchanged). Launch `ToolError` shows `Outcome: BLOCKED` and error text in detail. Other-SHA digest is not evidence and outcome is `BLOCKED`. Buttons invoke prepare/fetch/launch only on press; mount does not call Docker.

Commands: `python -m pytest tests/test_tui_environment.py -q --tb=short` pass (8).

## Package P1

### Implementer
Status: completed. Added `review_ticket/tui/shared_chrome.py` and `tests/test_decision_panel.py`. One dock replaces Approve/Reject, editing, saved preview, independent Yes/No comment and transition, and a receipt. Recommendation changes emphasis only. Save does not call Jira or GitHub. A failed post leaves the draft. `testing_notes_screen.py` was not changed.

Tests: `python -m pytest tests/test_decision_panel.py tests/test_tui_testing_notes.py -q --tb=line` — pass.

### Verifier
Verdict: **pass**. Findings: none.

Approve and Reject keep the same order, positions, and widths when emphasis changes. Save, No, and Esc stay local. Comment Yes/No and transition Yes/No are separate. A failed post or transition leaves the draft retryable. Header shows issue key, title, stage, active PR, short SHA, full SHA, stale or historical freshness, and recommendation.

Commands: `python -m pytest tests/test_decision_panel.py -q --tb=short` pass; `python -m pytest tests/test_tui_testing_notes.py -q --tb=line` pass.

## Package P2

### Implementer
Status: completed. Testing notes use the shared decision panel. Description and notes are stacked; notes take about 60% of the evidence height. Reject collapses the description and keeps notes visible. Save calls `decide_notes` with `draft_body` and does not post. Comment and transition are separate Yes/No steps. Approve pops to status because the readiness screen does not exist yet. `restore_rejection` was added on the shared panel.

Files: `review_ticket/tui/testing_notes_screen.py`, `review_ticket/tui/shared_chrome.py`, `tests/test_tui_testing_notes.py`.

Tests: `python -m pytest tests/test_tui_testing_notes.py tests/test_decision_panel.py -q --tb=line` — pass.

### Verifier
Verdict: **pass**. Findings: none.

Scenario A stores acceptance and does not write `actions.jsonl`. Scenario B keeps notes visible, posts only after Yes, transitions only after a second Yes, and a failed post leaves the transition hidden. Re-opening shows the saved draft. Deny does not add a successful action. CLI template regression still passes. Decision-panel tests still pass (17).

Commands: `python -m pytest tests/test_tui_testing_notes.py -q --tb=short` pass; `python -m pytest tests/test_decision_panel.py -q --tb=short` pass.

## Package P3

### Implementer
Status: completed. New readiness screen projects stored PRs (identity, SHA, checks, analyzers) and renders stored reports. Approve records the gate only when every PR is ready or an existing exception covers it, and does not call GitHub. Reject drafts only non-ready PRs and unaddressed findings, then the Jira Yes/No sequence. WAITING shows Refresh and hides Approve/Reject. Testing-notes Approve opens this screen. CLI `analyzers --return` text unchanged.

Files: `review_ticket/reports.py`, `review_ticket/workflow.py`, `review_ticket/tui/shared_chrome.py`, `review_ticket/tui/readiness_screen.py`, `review_ticket/tui/testing_notes_screen.py`, `tests/test_tui_readiness.py`, `tests/test_tui_testing_notes.py`.

### Verifier
Verdict: **pass**. Findings: none.

Two ready PRs stay blocked while one Bugbot finding is unaddressed. The reject draft names only that PR and SHA and omits clean checks. WAITING has no Approve. Screen construction does not call the runner. `tests/test_acceptance.py` was not modified.

Commands: `python -m pytest tests/test_tui_readiness.py tests/test_tui_testing_notes.py tests/test_decision_panel.py tests/test_tui_status.py tests/test_acceptance.py -q --tb=line` pass.

## Package P4

### Implementer
Status: completed. Track helpers distinguish automated curation, manual review, functional results, and publication history (`publications.jsonl` plus latest `publication.json`). `resume` reaches virtualization without a publication receipt. Approve is rejected until a functional pass and a completed manual review. Optional identity and SHA arguments default to the active PR.

Files: `review_ticket/policy.py`, `review_ticket/workflow.py`, `tests/test_acceptance.py`, `tests/test_track_publication.py`.

### Verifier
Verdict: **pass**. Findings: none.

Resume reaches virtualization after automated findings without `publication.json`. `publish-review --event APPROVE` is rejected before a functional pass. A second PR is addressable without narrowing `pr_scope`. Old `human-review.json` still loads. Identical republish does not append a second history line.

Commands: `python -m pytest tests/test_acceptance.py tests/test_save_snapshot_review.py tests/test_track_publication.py -q --tb=line` pass (44).

## Package P14

### Implementer
Status: completed. When one pull request HEAD changes, the old commit directory stays, tracks and receipts are marked historical for the new HEAD, and the new SHA is not approved. Other pull requests and testing-notes acceptance stay as they were. Publication refuses inline locations that are not on the new diff. Refresh is the only readiness or status path that calls `resume`. The hub screen and the status-track rewrite were left for later packages.

Files: `review_ticket/workflow.py`, `review_ticket/status_projection.py`, `review_ticket/tui/status_format.py`, `review_ticket/tui/status_screen.py`, `review_ticket/tui/readiness_screen.py`, `review_ticket/tui/pr_screen.py`, `tests/support.py`, `tests/test_sha_change.py`, `tests/test_tui_pr.py`, `tests/test_tui_status.py`.

### Verifier
Verdict: **pass**. Findings: none. Verified by [Verify package P14](40fea4b1-e523-4b8a-ac2e-27a7cc3292fa).

Old findings, manual notes, test results, and the publication receipt stay readable and historical. The new SHA has no copied approval. The other pull request and testing-notes acceptance are unchanged. Publishing the old inline comments against the new diff is refused. Status and readiness paint and quit stay local.

Commands: `python -m pytest tests/test_sha_change.py tests/test_tui_pr.py tests/test_tui_status.py tests/test_tui_readiness.py -q --tb=line` pass (28).

## Package P13

### Implementer
Status: completed. Extended status projection and markdown: issue title from `issue.json`, `session.last_updated`, per-PR three-track labels via `classify_track_status`, publication from receipts only, artifact timestamps. Paint and quit stay local; Refresh still calls `resume` only on operator action.

Files: `review_ticket/status_projection.py`, `review_ticket/tui/status_format.py`, `tests/test_status_projection.py`, `tests/test_tui_status.py`.

### Verifier
Verdict: **pass**. Findings: none. Verified by [Verify package P13](c7e3e8a3-295f-43f5-ad24-3ad28d6606a2).

Paint and quit do not call the runner. Three PRs show track labels from disk. Quit does not modify `session.json`. Opening a PR does not write `active_pr`. Missing-session copy unchanged.

Commands: `python -m pytest tests/test_tui_status.py tests/test_status_projection.py -q --tb=line` pass (14).

## Package P8

### Implementer
Status: completed. `manual-review.json` writer (`save_manual_review`), duplicate suppression in `findings.py`, `ManualCodeReviewScreen` with diff excerpt, hub routes the manual track, `p9_handoff` flag on confirmed Request Changes (no publish).

Files: `review_ticket/workflow.py`, `review_ticket/findings.py`, `review_ticket/interactive_manual_review.py`, `review_ticket/tui/manual_review_screen.py`, `review_ticket/hub_projection.py`, `review_ticket/tui/hub_screen.py`, `tests/test_manual_review_payload.py`, `tests/test_tui_manual_review.py`.

Tests: `python -m pytest tests/test_manual_review_payload.py tests/test_tui_manual_review.py tests/test_save_snapshot_review.py -q --tb=short` — pass (10).

### Verifier
Verdict: **pass**. Verified by [Verify package P8](806cf60b-dff6-429d-aac7-1951b38e39d3).

## Package P9

### Implementer
Status: completed. `GitHubComposeScreen` with findings checklist, editable summary, stable Approve/Comment/Request Changes, preview + authorize via `publish_review(yes=True)`. `assemble_publication_findings`, `compose_projection`, `publication-draft.json`, hub publication track and next-action routing. Receipt on hub from `publication.json` only.

Files: `review_ticket/compose_projection.py`, `review_ticket/tui/compose_screen.py`, `review_ticket/findings.py`, `review_ticket/workflow.py`, `review_ticket/hub_projection.py`, `review_ticket/tui/hub_screen.py`, `tests/test_tui_compose.py`, `tests/test_track_publication.py`, `tests/test_acceptance.py`.

Tests: `python -m pytest tests/test_tui_compose.py tests/test_track_publication.py tests/test_acceptance.py::test_failed_github_review_keeps_draft_and_no_success_receipt -q --tb=line` — pass (14).

### Verifier
Verdict: **pass** (after repair). Findings: none. Verified by [Re-verify package P9](a96720bc-bea4-44c6-b9ff-317f4ad13428).

Repair closed gaps: `publication_event_allowed` gates COMMENT on completed manual review; headless compose disabled-button test; hub `Published (Comment)` vs `Published (Approve)` test.

Commands: `python -m pytest tests/test_tui_compose.py tests/test_track_publication.py tests/test_tui_hub.py` + acceptance publish subset — pass (24).

## Package P11

### Implementer
Status: completed. Extended `record_tests` / functional testing screen with operational result vs disposition, hub routing after environment. Repair: `functional_digest_matches` so a pass counts only when digest matches `environment.json`.

Tests: `python -m pytest tests/test_record_tests_workflow.py tests/test_tui_functional_testing.py tests/test_track_publication.py -q` — pass (21).

### Verifier
Verdict: **pass** (after repair). Verified by [Re-verify package P11](794e43db-8b8c-4182-8365-7eae67c64963).

## Package P12

### Implementer
Status: completed. Hub ticket Approve/Reject wired to `ticket_disposition` checklist across all `active_prs`; reject draft cites blocking PRs only; Jira sequence via shared panel; CLI `leave` and `--override` unchanged.

Files: `review_ticket/ticket_disposition.py`, `review_ticket/tui/hub_screen.py`, `tests/test_ticket_disposition.py`, `tests/test_tui_hub.py`.

### Verifier
Verdict: **pass**. Verified by [Verify package P12](0fc573f2-1151-4446-9297-9e3334d6731c).

Commands: `python -m pytest tests/test_ticket_disposition.py tests/test_tui_hub.py -q` — pass (12).

## Post-orchestration integration

After all packages passed, full `pytest` initially reported 4 failures (SHA-change fixtures vs digest gate, hub routing P11 vs environment test). Test-only fixes in `tests/test_sha_change.py`, `tests/test_tui_compose.py`, `tests/test_tui_environment.py` — **222 passed** full suite.

### Follow-up (operator authorized)

- `TestingNotesScreen.__test__ = False` — removes pytest collection warning.
- Acceptance: stale HEAD publish keeps `publication-draft.json`; failed GitHub review journals `github.review` failure in `actions.jsonl`.
- Functional record test: fail + Request Changes persists `--evidence` when file exists.
- `ReviewTicketApp` docstring updated; progress table P5 note corrected.
