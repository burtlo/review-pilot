from review_ticket.util import merge_json_documents, parse_json_documents, parse_json_output


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
