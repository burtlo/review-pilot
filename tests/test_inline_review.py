"""Files changed deep links for status rows and CLI pr: lines."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from review_ticket.inline_review import files_changed_url, is_full_sha
from review_ticket.models import Outcome, StepResult
from review_ticket.status_projection import pr_url_for_ref
from review_ticket.storage import Store, read_json, write_json
from review_ticket.workflow import _pr_url_for_ref, _render
from tests.support import ISSUE, SHA1, make_app

REF = "acme/widgets#87"
CONVERSATION = "https://github.com/acme/widgets/pull/87"
SHORT_SHA = "a1b2c3d"


def test_full_sha_opens_files_changed_with_exact_query():
    url = files_changed_url("acme", "widgets", 87, ISSUE, SHA1)
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.netloc == "github.com"
    assert parts.path == "/acme/widgets/pull/87/changes"
    assert parts.fragment == ""
    assert [key for key, _value in parse_qsl(parts.query)] == [
        "review_pilot_issue",
        "review_pilot_sha",
    ]
    assert dict(parse_qsl(parts.query)) == {
        "review_pilot_issue": ISSUE,
        "review_pilot_sha": SHA1,
    }
    assert "review_pilot_finding" not in parts.query
    assert url == f"{CONVERSATION}/changes?review_pilot_issue={ISSUE}&review_pilot_sha={SHA1}"


def test_missing_or_short_sha_stays_conversation_url():
    assert files_changed_url("acme", "widgets", 87, ISSUE, "") == CONVERSATION
    assert files_changed_url("acme", "widgets", 87, ISSUE, SHORT_SHA) == CONVERSATION
    assert files_changed_url("acme", "widgets", 87, ISSUE, "g" * 40) == CONVERSATION
    assert files_changed_url("acme", "widgets", 87, ISSUE, SHA1[:39]) == CONVERSATION
    assert not is_full_sha(SHORT_SHA)
    assert is_full_sha(SHA1)


def test_url_helper_does_not_change_pr_json(tmp_path):
    store = Store(tmp_path / "reviews")
    pr_path = store.pr_dir(ISSUE, "acme", "widgets", 87) / "pr.json"
    write_json(pr_path, {"url": CONVERSATION, "number": 87})
    write_json(
        store.issue_dir(ISSUE) / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF,
            "active_sha": SHA1,
            "active_prs": [REF],
            "pr_shas": {REF: SHA1},
        },
    )
    before = pr_path.read_bytes()
    assert pr_url_for_ref(store, ISSUE, REF) == files_changed_url("acme", "widgets", 87, ISSUE, SHA1)
    assert pr_path.read_bytes() == before
    assert read_json(pr_path)["url"] == CONVERSATION


def test_missing_sha_keeps_stored_conversation_url(tmp_path):
    store = Store(tmp_path / "reviews")
    pr_path = store.pr_dir(ISSUE, "acme", "widgets", 87) / "pr.json"
    write_json(pr_path, {"url": CONVERSATION})
    write_json(
        store.issue_dir(ISSUE) / "session.json",
        {"issue": ISSUE, "active_pr": REF, "active_prs": [REF], "pr_shas": {REF: SHORT_SHA}},
    )
    before = pr_path.read_bytes()
    assert pr_url_for_ref(store, ISSUE, REF) == CONVERSATION
    assert files_changed_url("acme", "widgets", 87, ISSUE, "") == CONVERSATION
    assert pr_path.read_bytes() == before


def test_cli_single_pr_line_uses_files_changed_url(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    session = {
        "issue": ISSUE,
        "active_pr": REF,
        "active_sha": SHA1,
        "active_prs": [REF],
        "pr_shas": {},
    }
    _render(
        app,
        session,
        StepResult(step="human-review", outcome=Outcome.READY, summary="Stored session."),
    )
    expected = files_changed_url("acme", "widgets", 87, ISSUE, SHA1)
    assert f"pr: {REF} @ {SHA1[:12]}  {expected}" in app.stdout.getvalue()


def test_cli_pr_line_uses_files_changed_url(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    pr_path = app.store.pr_dir(ISSUE, "acme", "widgets", 87) / "pr.json"
    write_json(pr_path, {"url": CONVERSATION})
    before = pr_path.read_bytes()
    session = {
        "issue": ISSUE,
        "active_pr": REF,
        "active_sha": SHA1,
        "active_prs": [REF, "acme/gadgets#12"],
        "pr_shas": {REF: SHA1, "acme/gadgets#12": "b" * 40},
    }
    _render(
        app,
        session,
        StepResult(step="human-review", outcome=Outcome.READY, summary="Stored session."),
    )
    expected = files_changed_url("acme", "widgets", 87, ISSUE, SHA1)
    output = app.stdout.getvalue()
    assert f"pr: {REF} @ {SHA1[:12]}  {expected}" in output
    other = files_changed_url("acme", "gadgets", 12, ISSUE, "b" * 40)
    assert f"pr: acme/gadgets#12 @ {'b' * 12}  {other}" in output
    assert _pr_url_for_ref(app, ISSUE, REF, "") == CONVERSATION
    assert pr_path.read_bytes() == before
