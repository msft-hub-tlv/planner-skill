"""MSAL device-code auth for the planner skill.

Uses the well-known Microsoft Azure PowerShell public client id, which has the
required `user_impersonation` consent for any Dataverse environment the signed-in
user can reach. No custom app registration required.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import msal  # type: ignore

# Azure CLI public client id — broadly allow-listed by Conditional Access in
# Microsoft corp tenants. Falls back via PLANNER_CLIENT_ID env var if needed.
CLIENT_ID = os.environ.get("PLANNER_CLIENT_ID", "04b07795-8ddb-461a-bbee-02f9e1bf7b46")

CACHE_DIR = Path(os.environ.get("PLANNER_CACHE_DIR", Path.home() / ".copilot" / "m-skills" / "planner" / ".cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(tenant: str) -> Path:
    return CACHE_DIR / f"msal_{tenant}.bin"


def _load_cache(tenant: str) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    p = _cache_path(tenant)
    if p.exists():
        try:
            cache.deserialize(p.read_text())
        except Exception:
            pass
    return cache


def _save_cache(tenant: str, cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _cache_path(tenant).write_text(cache.serialize())


def _app(tenant: str, cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache,
    )


def acquire_token(env_url: str, tenant: str = "common", interactive: bool = True) -> str:
    """Return an access token for the given Dataverse environment URL.

    Tries silent first; falls back to device code flow.
    """
    scope = [f"{env_url.rstrip('/')}/.default"]
    cache = _load_cache(tenant)
    app = _app(tenant, cache)

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scope, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(tenant, cache)
            return result["access_token"]

    if not interactive:
        raise RuntimeError(
            "no cached token and interactive=False — run `planner auth` to sign in"
        )

    # Microsoft corp tenant blocks device-code flow via Conditional Access
    # (AADSTS53003). Use interactive browser auth — opens local browser and
    # uses authorization_code + PKCE, which CA permits on compliant devices.
    # Set PLANNER_FORCE_DEVICE_CODE=1 to force the legacy flow (e.g. for
    # headless/SSH use in tenants that allow it).
    if os.environ.get("PLANNER_FORCE_DEVICE_CODE"):
        flow = app.initiate_device_flow(scopes=scope)
        if "user_code" not in flow:
            raise RuntimeError(f"device flow failed to start: {json.dumps(flow, indent=2)}")
        print(flow["message"], file=sys.stderr, flush=True)
        result = app.acquire_token_by_device_flow(flow)
    else:
        print(
            "Opening browser to sign in... (set PLANNER_FORCE_DEVICE_CODE=1 to use device-code instead)",
            file=sys.stderr,
            flush=True,
        )
        result = app.acquire_token_interactive(
            scopes=scope,
            prompt="select_account",
        )

    _save_cache(tenant, cache)

    if "access_token" not in result:
        raise RuntimeError(
            f"device flow failed: {result.get('error')} — {result.get('error_description')}"
        )
    return result["access_token"]


def acquire_token_for_bap(tenant: str = "common", interactive: bool = True) -> str:
    """Token for Dataverse Global Discovery Service (env enumeration).

    Name kept for backward compat — earlier versions used the BAP admin API,
    which only returned envs you administer (too narrow for Planner Premium).
    """
    return acquire_token("https://globaldisco.crm.dynamics.com", tenant, interactive)


def check(tenant: str = "common") -> bool:
    """Return True iff a cached token exists and silent refresh works."""
    cache = _load_cache(tenant)
    app = _app(tenant, cache)
    accounts = app.get_accounts()
    if not accounts:
        return False
    # Try a benign scope — any cached refresh token will satisfy this.
    result = app.acquire_token_silent(
        ["https://globaldisco.crm.dynamics.com/.default"], account=accounts[0]
    )
    _save_cache(tenant, cache)
    return bool(result and "access_token" in result)


def clear(tenant: Optional[str] = None) -> int:
    """Delete cached tokens. Returns count removed."""
    n = 0
    for p in CACHE_DIR.glob("msal_*.bin"):
        if tenant is None or p.name == f"msal_{tenant}.bin":
            p.unlink()
            n += 1
    return n
