"""TLS trust helpers for corporate proxies (e.g. ZScaler)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CERT_NAMES = ("zscaler-root.cer", "zscaler-root.pem", "zscaler-root.crt")


def default_zscaler_cert_path() -> Path | None:
    """In-repo CA under certs/ (see certs/zscaler-root.placeholder)."""
    for name in _DEFAULT_CERT_NAMES:
        path = _REPO_ROOT / "certs" / name
        if path.is_file():
            return path
    return None


def resolve_zscaler_cert_path() -> Path | None:
    raw = (os.environ.get("ZSCALER_CERT_PATH") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_file() else None
    return default_zscaler_cert_path()


def zscaler_tls_env() -> dict[str, str]:
    """Propagate ZScaler CA to Node (bridge) and Python TLS clients."""
    path = resolve_zscaler_cert_path()
    if path is None:
        return {}
    resolved = str(path.resolve())
    return {
        "NODE_EXTRA_CA_CERTS": resolved,
        "SSL_CERT_FILE": resolved,
        "REQUESTS_CA_BUNDLE": resolved,
    }


def apply_zscaler_tls_env() -> dict[str, str]:
    """Merge into os.environ; return the keys that were set."""
    extra = zscaler_tls_env()
    if extra:
        os.environ.update(extra)
    return extra
