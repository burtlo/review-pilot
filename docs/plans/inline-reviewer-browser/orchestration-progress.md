# Orchestration progress — inline-reviewer-browser

Status: **complete**

Queue: P1 → P2 → P3 → P5 → P4 → P6 → P7 (`auto_continue`, repair limit 1). No repairs were required.

| Package | Implement | Verify | Notes |
|---------|-----------|--------|-------|
| P1 | completed | pass | Files changed URL when a full SHA is stored |
| P2 | completed | pass | Loopback snapshot bridge; publish filtering unchanged |
| P3 | completed | pass | Unpacked MV3 shell; manual Edge/Chrome smoke not run |
| P5 | completed | pass | Preflight classification and scan_text goldens; no prepare clicks |
| P4 | completed | pass | SHA gate fail-closed; blocked prepare is a no-op |
| P6 | completed | pass | Prepare writes drafts and never submits; manual PR smoke not run |
| P7 | completed | pass | Probe, picker, dry-run, override reset; live probe not run |

## Package P1

### Implementer

[P1 deep links](190a6b41-b5cd-4291-b8cf-1ab3373cb225) added `files_changed_url`. Status rows and CLI `pr:` lines open `/changes?review_pilot_issue&review_pilot_sha` when a 40-hex SHA is stored. A missing or shorter SHA stays the conversation URL. `pr.json` is not rewritten. `pytest` on the link tests exited 0.

### Verifier

[P1 verify](4d0af6c6-3320-43ee-b8bb-9ad8bf8fe8ab) **pass**. Re-ran the link tests (20) and `tests/test_acceptance.py` (31). Jira fixtures did not grow `/changes`.

## Package P2

### Implementer

[P2 bridge](b7527fe1-7057-43d6-95ca-efa40c06ee7a) added `review-ticket <issue> serve-inline-review` on `127.0.0.1` (default port 8765). `GET /snapshot` requires `Authorization: Bearer` from `REVIEW_PILOT_BRIDGE_TOKEN` and lists every finding, including rejected ones. Publish filtering was not changed.

### Verifier

[P2 verify](7a5eddff-10da-4ceb-9bf2-705fd28e8ded) **pass**. 31 pytest probes. Non-loopback binds and missing tokens are refused. `attach` does not start the bridge. `findings.py` and `tests/test_policy_and_findings.py` are unchanged versus HEAD.

## Package P3

### Implementer

[P3 shell](e555872b-ce1b-4b6b-8c6a-607c89e535a1) added the unpacked Manifest V3 tree `extensions/inline-reviewer/`. Document-start capture, allowlist gating, and a side panel. `node --test` exited 0 (24 tests).

### Verifier

[P3 verify](f4b8f0f9-5e70-4066-8276-8471bccd0625) **pass**. 24/24 tests. Non-matching repos do not fetch. The service worker is the caller to `127.0.0.1` with the bearer header. Manual Edge/Chrome side-load was not run.

## Package P5

### Implementer

[P5 preflight](a03da4d3-1f97-4af3-8597-6cc6e7c4fbf0) added golden `scan_text` tests and the extension placement module (`fill`, `replace_draft`, `skip_match`, `manual_only`). Refresh scan and the replace-modified-drafts toggle are in the panel. No prepare clicks.

### Verifier

[P5 verify](3b7abd7d-b22d-4c72-9180-b93864e458e5) **pass**. 27 pytest and 34 node tests. Publish payloads still have no marker line.

## Package P4

### Implementer

[P4 SHA gate](47d04e2d-368c-40e0-8dce-e40e2a3f0f4d) passes only for **All commits**, Hide whitespace off, and an exact full head SHA from `head-commit-link`. A blocked prepare does not write the page. `node --test` exited 0 (44 tests).

### Verifier

[P4 verify](cf7ab93e-5d9f-4bd1-b3ee-46ad982abd38) **pass**. Short ids, missing links, and **Changes from all commits** block. The head SHA is not scraped from the first 40-hex string on the page.

## Package P6

### Implementer

[P6 prepare](ac946166-9fc3-4c64-bb0d-fcf7f8292a4d) writes snapshot bodies when the gate passes. Per-finding prepare leaves the composer open. Prepare all clicks **Start a review**. Off-diff text goes to the Finish your review summary and closes with Cancel. `node --test` exited 0 (58 tests).

### Verifier

[P6 verify](cdefa763-c1e8-4cf3-8edb-3d342748c8dd) **pass**. Stub DOM proves no Comment, dialog Submit review, Approve, or Request changes clicks, and `reviewEvent` stays on Comment. Two findings on one line produce two inserts. A blocked gate does no DOM work. Publish files are unchanged. Manual PR smoke was not run.

## Package P7

### Implementer

[P7 debug](7ca7bbe1-74e1-464f-8df7-8e8449c19690) added probe, picker, dry-run, and Copy debug bundle. Overrides in storage beat `selectors.json` until Clear selector overrides. `node --test` exited 0 (63 tests).

### Verifier

[P7 verify](8cdb94d5-1f74-4ab8-b509-5a419b51f68e) **pass**. Probe and dry-run do not write the textarea. The debug bundle includes selector id and match count. Live PR probe was not run.
