#!/usr/bin/env python3
"""Standalone Cursor SDK smoke test (outside review-ticket).

Use this when run-review fails with "Network request failed" or similar —
often corporate proxies (e.g. ZScaler) block non-browser TLS or Cursor API hosts.

  python scripts/cursor_sdk_smoke.py
  python scripts/cursor_sdk_smoke.py --skip-agent    # HTTPS + bridge only
  python scripts/cursor_sdk_smoke.py --workspace C:\\repos\\burtlo\\review-pilot

Requires: pip install cursor-sdk
Env: CURSOR_API_KEY (required for --full agent prompt)
Optional: HTTPS_PROXY / https_proxy, NO_PROXY, REVIEW_TICKET_REVIEWER_MODEL
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Hosts the local bridge and IDE typically reach (not exhaustive).
HTTPS_PROBES: tuple[tuple[str, str], ...] = (
    ("https://cursor.com/", "cursor.com (TLS)"),
    ("https://api2.cursor.sh/", "api2.cursor.sh (API)"),
    ("https://www.cursor.com/", "www.cursor.com (TLS)"),
)


def _proxy_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        val = os.environ.get(key)
        if val:
            out[key] = val
    return out


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


def check_api_key() -> bool:
    key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        print("CURSOR_API_KEY: MISSING (set in this shell, e.g. $env:CURSOR_API_KEY)")
        return False
    print(f"CURSOR_API_KEY: set ({_mask_key(key)}, len={len(key)})")
    return True


def probe_https(url: str, label: str, timeout: float) -> bool:
    print(f"  GET {label} … ", end="", flush=True)
    started = time.monotonic()
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "review-pilot-smoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.getcode()
            elapsed = time.monotonic() - started
            print(f"OK HTTP {code} ({elapsed:.1f}s)")
            return True
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - started
        # 403/401 still means TCP+TLS worked.
        print(f"HTTP {exc.code} ({elapsed:.1f}s) — reachable, status not OK")
        return exc.code < 500
    except (urllib.error.URLError, ssl.SSLError, socket.timeout, TimeoutError, OSError) as exc:
        elapsed = time.monotonic() - started
        print(f"FAIL ({elapsed:.1f}s): {exc}")
        return False


async def probe_sdk_bridge(workspace: Path, timeout: float) -> bool:
    from cursor_sdk.asyncio import AsyncClient

    print(f"  launch_bridge workspace={workspace} timeout={timeout}s … ", end="", flush=True)
    started = time.monotonic()
    try:
        async with await AsyncClient.launch_bridge(
            workspace=str(workspace),
            timeout=timeout,
        ) as client:
            version = await client.get_version()
            elapsed = time.monotonic() - started
            bridge_ver = version.get("bridgeVersion") or version
            print(f"OK ({elapsed:.1f}s) bridgeVersion={bridge_ver}")
            ping = await client.ping()
            print(f"  ping: {ping}")
            return True
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"FAIL ({elapsed:.1f}s): {type(exc).__name__}: {exc}")
        return False


async def probe_sdk_agent(workspace: Path, model: str, timeout: float) -> bool:
    from cursor_sdk import AgentOptions, LocalAgentOptions
    from cursor_sdk.asyncio import AsyncAgent, AsyncClient

    api_key = os.environ["CURSOR_API_KEY"]
    local = LocalAgentOptions(cwd=str(workspace), setting_sources=["project", "user"])
    options = AgentOptions(api_key=api_key, model=model, local=local)
    prompt = (
        "Smoke test only. Reply with exactly one word: ok. "
        "Do not use tools or write files."
    )

    print(f"  AsyncAgent.prompt model={model} … ", end="", flush=True)
    started = time.monotonic()
    try:
        async with await AsyncClient.launch_bridge(
            workspace=str(workspace),
            timeout=timeout,
            local=local,
        ) as client:
            result = await AsyncAgent.prompt(prompt, options, client=client)
        elapsed = time.monotonic() - started
        text = (result.result or "").strip().replace("\n", " ")[:120]
        print(f"done ({elapsed:.1f}s) status={result.status} id={result.id}")
        print(f"  result excerpt: {text!r}")
        if result.status == "error":
            return False
        return True
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"FAIL ({elapsed:.1f}s): {type(exc).__name__}: {exc}")
        return False


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cursor SDK connectivity smoke test")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace passed to launch_bridge (default: cwd)",
    )
    parser.add_argument(
        "--https-timeout",
        type=float,
        default=15.0,
        help="Timeout per HTTPS probe (seconds)",
    )
    parser.add_argument(
        "--bridge-timeout",
        type=float,
        default=45.0,
        help="Bridge launch timeout (seconds)",
    )
    parser.add_argument(
        "--skip-bridge",
        action="store_true",
        help="Skip SDK bridge launch",
    )
    parser.add_argument(
        "--skip-agent",
        action="store_true",
        help="Skip full agent prompt (bridge + HTTPS only)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("REVIEW_TICKET_REVIEWER_MODEL", "composer-2.5"),
        help="Model for agent prompt",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Same repo package path as review_ticket_reviewer.py
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from review_ticket.tls_env import apply_zscaler_tls_env, resolve_zscaler_cert_path

    args = parse_args(argv)
    workspace = args.workspace.resolve()
    cert_env = apply_zscaler_tls_env()
    print("=== Cursor SDK smoke test ===")
    print(f"Python: {sys.version.split()[0]} on {sys.platform}")
    print(f"Workspace: {workspace}")
    resolved = resolve_zscaler_cert_path()
    if cert_env:
        source = "ZSCALER_CERT_PATH" if os.environ.get("ZSCALER_CERT_PATH", "").strip() else "certs/zscaler-root.*"
        print(f"ZScaler CA ({source}): {cert_env.get('NODE_EXTRA_CA_CERTS')} → NODE_EXTRA_CA_CERTS / SSL_CERT_FILE")
    elif resolved is None:
        print("ZScaler CA: not found (add certs/zscaler-root.cer or set ZSCALER_CERT_PATH)")
    else:
        print(f"ZScaler CA: {resolved} (missing or unreadable)")

    proxies = _proxy_env()
    if proxies:
        print("Proxy env:")
        for k, v in sorted(proxies.items()):
            print(f"  {k}={v}")
    else:
        print("Proxy env: (none set — Python urllib may still use system proxy)")

    print()
    print("=== CURSOR_API_KEY ===")
    has_key = check_api_key()

    print()
    print("=== HTTPS reachability (urllib) ===")
    https_ok = all(probe_https(url, label, args.https_timeout) for url, label in HTTPS_PROBES)

    bridge_ok = True
    agent_ok = True

    if args.skip_bridge:
        print()
        print("=== SDK bridge === skipped")
    else:
        print()
        print("=== SDK bridge (async launch_bridge) ===")
        try:
            import cursor_sdk  # noqa: F401
        except ImportError:
            print("cursor-sdk not installed. Run: python -m pip install cursor-sdk")
            return 2
        bridge_ok = asyncio.run(probe_sdk_bridge(workspace, args.bridge_timeout))

    if args.skip_agent:
        print()
        print("=== SDK agent prompt === skipped")
    else:
        print()
        print("=== SDK agent prompt (async; hits Cursor cloud) ===")
        if not has_key:
            print("Skipped — set CURSOR_API_KEY first.")
            agent_ok = False
        else:
            agent_ok = asyncio.run(probe_sdk_agent(workspace, args.model, args.bridge_timeout))

    print()
    print("=== Summary ===")
    print(f"  HTTPS probes: {'PASS' if https_ok else 'FAIL'}")
    if not args.skip_bridge:
        print(f"  SDK bridge:   {'PASS' if bridge_ok else 'FAIL'}")
    if not args.skip_agent:
        print(f"  SDK agent:    {'PASS' if agent_ok else 'FAIL'}")

    if not https_ok:
        print()
        print("ZScaler / corporate proxy hints:")
        print("  - Ask IT to allow *.cursor.com, *.cursor.sh, api2.cursor.sh")
        print("  - Or set HTTPS_PROXY to your corporate proxy for this shell:")
        print('      $env:HTTPS_PROXY = "http://proxy.company:port"')
        print("  - Some setups need NO_PROXY for localhost bridge traffic:")
        print('      $env:NO_PROXY = "127.0.0.1,localhost"')

    if https_ok and bridge_ok and not agent_ok:
        print()
        print("HTTPS and bridge work but agent failed — often API key, account, or")
        print("cloud API blocked while generic HTTPS is allowed.")

    ok = https_ok and bridge_ok and (agent_ok or args.skip_agent)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
