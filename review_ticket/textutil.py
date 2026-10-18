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


def _adf_apply_marks(text: str, marks: Any) -> str:
    if not text or not marks:
        return text
    if not isinstance(marks, list):
        return text
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mtype = mark.get("type")
        if mtype == "strong":
            text = f"**{text}**"
        elif mtype == "em":
            text = f"*{text}*"
        elif mtype == "code":
            text = f"`{text}`"
        elif mtype == "strike":
            text = f"~~{text}~~"
        elif mtype == "link":
            href = str((mark.get("attrs") or {}).get("href") or "")
            text = f"[{text}]({href})" if href else text
    return text


def _adf_inline(children: list[Any]) -> str:
    parts: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            parts.append(adf_to_markdown(child))
            continue
        if child.get("type") == "text":
            parts.append(_adf_apply_marks(str(child.get("text") or ""), child.get("marks")))
        else:
            parts.append(adf_to_markdown(child))
    return "".join(parts)


def adf_to_markdown(node: Any) -> str:
    """Convert Atlassian Document Format to Markdown for display."""

    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_markdown(item) for item in node)
    if not isinstance(node, dict):
        return str(node)
    node_type = node.get("type")
    if node_type == "text":
        return _adf_apply_marks(str(node.get("text") or ""), node.get("marks"))
    children = node.get("content") or []
    if node_type == "paragraph":
        inner = _adf_inline(children).strip()
        return f"{inner}\n\n" if inner else ""
    if node_type == "heading":
        level = int((node.get("attrs") or {}).get("level") or 1)
        level = min(max(level, 1), 6)
        inner = _adf_inline(children).strip()
        return f"{'#' * level} {inner}\n\n" if inner else ""
    if node_type == "bulletList":
        lines: list[str] = []
        for child in children:
            if isinstance(child, dict) and child.get("type") == "listItem":
                item = _adf_list_item_markdown(child).strip()
                if item:
                    lines.append(f"- {item}")
        return "\n".join(lines) + ("\n\n" if lines else "")
    if node_type == "orderedList":
        lines = []
        index = 1
        for child in children:
            if isinstance(child, dict) and child.get("type") == "listItem":
                item = _adf_list_item_markdown(child).strip()
                if item:
                    lines.append(f"{index}. {item}")
                    index += 1
        return "\n".join(lines) + ("\n\n" if lines else "")
    if node_type == "listItem":
        return _adf_list_item_markdown(node)
    if node_type == "codeBlock":
        inner = _adf_inline(children).rstrip("\n")
        return f"```\n{inner}\n```\n\n" if inner else ""
    if node_type == "blockquote":
        inner = adf_to_markdown(children).strip()
        if not inner:
            return ""
        quoted = "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
        return f"{quoted}\n\n"
    if node_type == "hardBreak":
        return "  \n"
    if node_type == "rule":
        return "---\n\n"
    inner = _adf_inline(children) if children else adf_to_markdown(children)
    return inner


def _adf_list_item_markdown(node: dict[str, Any]) -> str:
    children = node.get("content") or []
    chunks: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "paragraph":
            chunks.append(_adf_inline(child.get("content") or []).strip())
        else:
            chunks.append(adf_to_markdown(child).strip())
    return " ".join(part for part in chunks if part)


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


def format_jira_body_markdown(text: str) -> str:
    """Normalize Jira issue text for Textual Markdown (headings, paragraphs, wrap-friendly blocks)."""

    body = str(text or "").strip()
    if not body:
        return ""
    if re.search(r"^#{1,6}\s", body, re.MULTILINE):
        return re.sub(r"\n{3,}", "\n\n", body).rstrip() + "\n"
    out_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        if _HEADING.match(stripped):
            out_lines.append(stripped)
            continue
        plain = _PLAIN_HEADING.match(stripped)
        if plain:
            title = plain.group(1).strip()
            if stripped == title or stripped == f"{title}:":
                out_lines.append(f"## {title}")
                continue
            if stripped.startswith(f"{title}:"):
                rest = stripped.split(":", 1)[1].strip()
                out_lines.append(f"## {title}")
                if rest:
                    out_lines.append(rest)
                continue
        if stripped.startswith(("• ", "· ")):
            out_lines.append("- " + stripped[2:].lstrip())
            continue
        out_lines.append(stripped)
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in out_lines:
        if not line:
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
            continue
        if line.startswith("##") or re.match(r"^[-*]\s", line) or re.match(r"^\d+\.\s", line):
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
            paragraphs.append(line)
        else:
            buf.append(line)
    if buf:
        paragraphs.append("\n".join(buf))
    return "\n\n".join(paragraphs).rstrip() + "\n"


def issue_section_markdown(title: str, body: str, *, empty_placeholder: str) -> str:
    formatted = format_jira_body_markdown(body)
    if not formatted.strip():
        return f"## {title}\n\n{empty_placeholder}\n"
    return f"## {title}\n\n{formatted.strip()}\n"


def testing_notes_from_fields(fields: dict[str, Any], description: str) -> str:
    if isinstance(fields.get("testing_notes"), str) and fields["testing_notes"].strip():
        return adf_to_text(fields["testing_notes"]).strip()
    for key, value in fields.items():
        if "test" in key.casefold() and "note" in key.casefold() and isinstance(value, (str, dict)):
            text = adf_to_markdown(value).strip()
            if text:
                return text
    names = fields.get("names")
    if isinstance(names, dict):
        for field_id, label in names.items():
            if isinstance(label, str) and "testing note" in label.casefold():
                text = adf_to_markdown(fields.get(field_id)).strip()
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
        text = adf_to_markdown(value).strip()
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


def unified_diff_excerpt(
    diff: str,
    path: str,
    line: int,
    *,
    side: str = "RIGHT",
    context: int = 3,
) -> str | None:
    """Return numbered diff lines around ``line`` in ``path``, or None if not found."""

    if not diff.strip() or not path or not isinstance(line, int):
        return None
    side = side or "RIGHT"
    hunk = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    current_path: str | None = None
    old_line = 0
    new_line = 0
    rows: list[tuple[int, str]] = []
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            current_path = None
            rows = []
            continue
        if raw.startswith("+++ "):
            header = raw[4:].strip()
            current_path = None if header == "/dev/null" else header[2:] if header.startswith("b/") else header
            rows = []
            continue
        if (
            raw.startswith("--- ")
            or raw.startswith("index ")
            or raw.startswith("new file")
            or raw.startswith("deleted file")
        ):
            continue
        match = hunk.match(raw)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            continue
        if current_path != path:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            number = new_line if side == "RIGHT" else old_line
            rows.append((number, f"+{raw[1:]}"))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            number = old_line if side == "LEFT" else new_line
            rows.append((number, f"-{raw[1:]}"))
            old_line += 1
        elif raw.startswith(" "):
            rows.append((new_line if side == "RIGHT" else old_line, f" {raw[1:]}"))
            new_line += 1
            old_line += 1
    if not rows:
        return None
    numbers = [item[0] for item in rows]
    if line not in numbers:
        return None
    index = numbers.index(line)
    start = max(0, index - context)
    end = min(len(rows), index + context + 1)
    return "\n".join(f"{num:>4} {text}" for num, text in rows[start:end])
