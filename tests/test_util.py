from pathlib import Path

import pytest

from review_ticket import textutil
from review_ticket.adapters import github_pr_search_query, search_prs
from review_ticket.config import config_from_mapping, load_config
from review_ticket.models import ToolError
from review_ticket.runner import ScriptedRunner
from review_ticket.util import merge_json_documents, parse_json_documents, parse_json_output

TESTING_NOTES_FIELD = {
    "type": "doc",
    "version": 1,
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Testing Notes"}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Ran review-ticket locally."}],
        },
    ],
}


def test_parse_json_output_merges_acli_comment_pages():
    stdout = """{
  "comments": [{"id": "1", "body": "note"}],
  "isLast": false,
  "total": 1
}
{
  "comments": [],
  "isLast": true,
  "total": 1
}
"""
    payload = parse_json_output(stdout)
    assert payload["isLast"] is True
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["id"] == "1"


def test_parse_json_documents_reads_multiple_values():
    text = '{"a": 1}{"b": 2}'
    assert parse_json_documents(text) == [{"a": 1}, {"b": 2}]


def test_merge_json_documents_concatenates_lists():
    assert merge_json_documents([[1], [2, 3]]) == [1, 2, 3]


def test_testing_notes_from_custom_field_adf():
    fields = {"customfield_10045": TESTING_NOTES_FIELD, "description": None}
    assert textutil.testing_notes_from_fields(fields, "") == "Ran review-ticket locally."


def test_github_pr_search_query_org_and_user():
    org = config_from_mapping({"github_org": "acme-corp"}, cwd=Path("."))
    assert github_pr_search_query(org, "HIV-1") == "HIV-1 org:acme-corp"
    user = config_from_mapping({"github_user": "lynnv"}, cwd=Path("."))
    assert github_pr_search_query(user, "HIV-1") == "HIV-1 user:lynnv"
    bare = config_from_mapping({}, cwd=Path("."))
    assert github_pr_search_query(bare, "HIV-1") == "HIV-1"


def test_github_pr_search_query_rejects_org_and_user_together():
    both = config_from_mapping({"github_org": "acme", "github_user": "lynnv"}, cwd=Path("."))
    with pytest.raises(ToolError):
        github_pr_search_query(both, "HIV-1")


def test_search_prs_falls_back_to_title_and_branch_match(tmp_path):
    runner = ScriptedRunner()
    runner.when(
        lambda argv: "pr" in argv and "list" in argv and "--search" in argv,
        lambda argv, cwd, data, env: __import__("review_ticket.runner", fromlist=["CommandResult"]).CommandResult(
            argv=list(argv), returncode=0, stdout="[]", stderr=""
        ),
    )
    runner.when(
        lambda argv: "pr" in argv and "list" in argv and "--search" not in argv,
        lambda argv, cwd, data, env: __import__("review_ticket.runner", fromlist=["CommandResult"]).CommandResult(
            argv=list(argv),
            returncode=0,
            stdout='[{"number": 1, "title": "HIV-1 fix", "headRefName": "lfrank/HIV-1", "state": "OPEN"}]',
            stderr="",
        ),
    )
    config = config_from_mapping({"github_repo": "acme/app"}, cwd=tmp_path)
    found = search_prs(runner, config, "HIV-1")
    assert len(found) == 1
    assert found[0]["number"] == 1


def test_search_prs_passes_org_qualifier_to_gh(tmp_path):
    runner = ScriptedRunner()
    runner.respond("search", "prs", stdout="[]")
    config = config_from_mapping({"github_org": "my-org"}, cwd=tmp_path)
    search_prs(runner, config, "DOT-1")
    assert runner.calls[-1][runner.calls[-1].index("prs") + 1] == "DOT-1 org:my-org"


def test_status_config_accepts_review_queue_columns():
    single = config_from_mapping(
        {
            "status": {
                "ready_for_peer_review": "Ready for Peer Review",
                "in_peer_review": "Peer Review",
            }
        },
        cwd=Path("."),
    )
    assert single.accepts_peer_review_status("ready for peer review")
    assert single.accepts_peer_review_status("Peer Review")
    assert not single.accepts_peer_review_status("In Progress")
    assert single.in_progress_status == "In Progress"
    assert single.approved_status == "Done"


def test_load_config_from_yaml_with_comments(tmp_path):
    (tmp_path / ".review-ticket.yaml").write_text(
        """
# Jira columns
status:
  in_progress: Dev
github_org: acme-corp
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.status.in_progress == "Dev"
    assert config.github_org == "acme-corp"


def test_yaml_config_takes_precedence_over_json(tmp_path):
    (tmp_path / ".review-ticket.json").write_text('{"github_org": "from-json"}', encoding="utf-8")
    (tmp_path / ".review-ticket.yaml").write_text("github_org: from-yaml\n", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.github_org == "from-yaml"


def test_status_config_legacy_top_level_keys():
    legacy = config_from_mapping(
        {
            "peer_review_status": "Ready for Peer Review",
            "in_progress_status": "Dev",
            "approved_status": "QA",
        },
        cwd=Path("."),
    )
    assert legacy.accepts_peer_review_status("Ready for Peer Review")
    assert legacy.in_progress_status == "Dev"
    assert legacy.approved_status == "QA"
