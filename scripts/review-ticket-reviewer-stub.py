#!/usr/bin/env python3
"""Minimal reviewer_command adapter for tests and CI (no Cursor SDK)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkout", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--sha", default="")
    parser.add_argument("--issue", default="")
    parser.add_argument("--agent", default="")
    args = parser.parse_args(argv)

    context = Path(args.context)
    if not (context / "prompt.md").is_file():
        print(f"context missing prompt.md: {context}", file=sys.stderr)
        return 2

    payload = {
        "summary": "Automated stub review.",
        "approval_recommendation": "request_changes",
        "findings": [
            {
                "id": "F001",
                "priority": "high",
                "must_fix": True,
                "path": "src/Example.cs",
                "line": 142,
                "side": "RIGHT",
                "title": "Missing validation",
                "explanation": "Stub finding for adapter tests.",
            }
        ],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
