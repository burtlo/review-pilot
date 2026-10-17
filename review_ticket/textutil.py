"""Text extraction for Jira documents, Markdown sections, and unified diffs."""

from __future__ import annotations

import re
from typing import Any


def adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (adf_to_text(item) for item in node) if part)
    if not isinstance(node, dict):
        return str(node)
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text") or "")
    children = node.get("content") or []
    inner = "".join(adf_to_text(child) if isinstance(child, dict) and child.get("type") == "text" else adf_to_text(child) for child in children)
    if node_type in {"paragraph", "heading", "listItem", "codeBlock", "blockquote"}:
        return inner.strip("\n") + "\n"
    if node_type in {"bulletList", "orderedList"}:
        return inner
    if node_type == "hardBreak":
        return "\n"
    return inner


_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_PLAIN_HEADING = re.compile(r"^([A-Z][A-Za-z0-9 /_-]{2,60}):?\s*$")


def extract_section(text: str, heading: str) -> str:
    """Return the body under a Markdown heading or a plain 'Heading:' label."""

    if not text:
        return ""
    lines = text.splitlines()
    target = heading.casefold()
    start: int | None = None
    start_level: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = _HEADING.match(stripped)
        if match and match.group(2).strip().casefold() == target:
            start = index + 1
            start_level = len(match.group(1))
            break
        plain = _PLAIN_HEADING.match(stripped)
        if plain and plain.group(1).strip().casefold() == target:
            inline = stripped.split(":", 1)
            if len(inline) == 2 and inline[1].strip() and stripped.casefold().startswith(target):
                # "Testing Notes: did the thing" on one line, plus following lines.
                rest = [inline[1].strip()]
                for follow in lines[index + 1 :]:
                    if _HEADING.match(follow.strip()) or (
                        _PLAIN_HEADING.match(follow.strip()) and follow.strip().endswith(":")
                    ):
                        break
                    rest.append(follow)
                return "\n".join(rest).strip()
            start = index + 1
            start_level = 0
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        match = _HEADING.match(stripped)
        if match and start_level and len(match.group(1)) <= start_level:
            break
        if start_level == 0 and (_HEADING.match(stripped) or (_PLAIN_HEADING.match(stripped) and stripped.endswith(":"))):
            break
        body.append(line)
    return "\n".join(body).strip()


def testing_notes_from_fields(fields: dict[str, Any], description: str) -> str:
    if isinstance(fields.get("testing_notes"), str) and fields["testing_notes"].strip():
        return adf_to_text(fields["testing_notes"]).strip()
    for key, value in fields.items():
        if "test" in key.casefold() and "note" in key.casefold() and isinstance(value, (str, dict)):
            text = adf_to_text(value).strip()
            if text:
                return text
    names = fields.get("names")
    if isinstance(names, dict):
        for field_id, label in names.items():
            if isinstance(label, str) and "testing note" in label.casefold():
                text = adf_to_text(fields.get(field_id)).strip()
                if text:
                    return text
    for heading in ("Testing Notes", "Test Notes", "Testing"):
        section = extract_section(description, heading)
        if section:
            return section
    skip_keys = {
        "comment",
        "description",
        "names",
        "schema",
        "attachment",
        "issuelinks",
        "subtasks",
        "worklog",
    }
    for key, value in fields.items():
        if key in skip_keys or key.startswith("aggregate"):
            continue
        if not isinstance(value, (str, dict)):
            continue
        text = adf_to_text(value).strip()
        if not text:
            continue
        for heading in ("Testing Notes", "Test Notes", "Testing"):
            section = extract_section(text, heading)
            if section:
                return section
    return ""


def normalize_comments(payload: Any) -> list[dict[str, str]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("comments", "values", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            if "body" in payload:
                payload = [payload]
            else:
                return []
    if not isinstance(payload, list):
        return []
    comments: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if isinstance(author, dict):
            author_name = str(author.get("displayName") or author.get("name") or author.get("login") or "")
        else:
            author_name = str(author or item.get("authorName") or "")
        body = item.get("body") if "body" in item else item.get("comment")
        comments.append(
            {
                "author": author_name,
                "body": adf_to_text(body).strip(),
                "created": str(item.get("created") or item.get("createdAt") or ""),
            }
        )
    return comments


def parse_unified_diff(diff: str) -> set[tuple[str, int, str]]:
    """Return file lines that GitHub can attach a review comment to."""

    locations: set[tuple[str, int, str]] = set()
    path: str | None = None
    old_line = 0
    new_line = 0
    hunk = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = None
            continue
        if line.startswith("+++ "):
            raw = line[4:].strip()
            path = None if raw == "/dev/null" else raw[2:] if raw.startswith("b/") else raw
            continue
        if line.startswith("--- ") or line.startswith("index ") or line.startswith("new file") or line.startswith("deleted file"):
            continue
        match = hunk.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            continue
        if path is None:
            continue
        if line.startswith("+"):
            locations.add((path, new_line, "RIGHT"))
            new_line += 1
        elif line.startswith("-"):
            locations.add((path, old_line, "LEFT"))
            old_line += 1
        elif line.startswith("\\"):
            continue
        else:
            # Context lines are part of the hunk and accept comments.
            if line.startswith(" "):
                locations.add((path, new_line, "RIGHT"))
                locations.add((path, old_line, "LEFT"))
                new_line += 1
                old_line += 1
    return locations
