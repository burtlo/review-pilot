"""Small helpers with no workflow policy."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
PR_URL = re.compile(
    r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)"
)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_issue_key(issue: str) -> str:
    key = issue.strip()
    if not ISSUE_KEY.match(key):
        raise ValueError(
            f"Expected a Jira issue id such as DOTNETIOT-1234, received {issue!r}."
        )
    return key


def parse_json_documents(text: str) -> list[Any]:
    """Decode one or more concatenated JSON values (e.g. acli --paginate)."""

    stripped = text.strip()
    if not stripped:
        raise ValueError("Command returned empty JSON output.")
    decoder = json.JSONDecoder()
    documents: list[Any] = []
    index = 0
    while index < len(stripped):
        while index < len(stripped) and stripped[index].isspace():
            index += 1
        if index >= len(stripped):
            break
        document, end = decoder.raw_decode(stripped, index)
        documents.append(document)
        index = end
    if not documents:
        raise ValueError("Command returned empty JSON output.")
    return documents


def merge_json_documents(documents: list[Any]) -> Any:
    if len(documents) == 1:
        return documents[0]
    if all(isinstance(item, dict) and "comments" in item for item in documents):
        merged = dict(documents[-1])
        comments: list[Any] = []
        for page in documents:
            page_comments = page.get("comments")
            if isinstance(page_comments, list):
                comments.extend(page_comments)
        merged["comments"] = comments
        return merged
    if all(isinstance(item, list) for item in documents):
        merged: list[Any] = []
        for item in documents:
            merged.extend(item)
        return merged
    return documents


def parse_json_output(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise ValueError("Command returned empty JSON output.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        if not starts:
            raise
        return merge_json_documents(parse_json_documents(text[min(starts) :]))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def short_sha(sha: str, length: int = 12) -> str:
    if not sha:
        return ""
    return sha[:length]


def pr_slug(owner: str, repo: str, number: int) -> str:
    def clean(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")

    return f"{clean(owner)}-{clean(repo)}-pr-{number}"


def parse_pr_ref(value: str) -> tuple[str, str, int]:
    """Accept owner/repo#87 or a GitHub pull request URL."""

    url = PR_URL.search(value)
    if url:
        return url.group("owner"), url.group("repo"), int(url.group("number"))
    match = re.fullmatch(r"([^/\s]+)/([^#\s]+)#(\d+)", value.strip())
    if not match:
        raise ValueError("Expected owner/repo#number or a GitHub pull request URL.")
    return match.group(1), match.group(2), int(match.group(3))


def find_pr_urls(text: str) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str, int]] = set()
    for match in PR_URL.finditer(text or ""):
        item = (match.group("owner"), match.group("repo"), int(match.group("number")))
        if item not in seen:
            seen.add(item)
            found.append(item)
    return found
