"""Microsoft Graph client for basic Planner plans.

Basic Planner = `/me/planner` and `/planner/...` endpoints. Premium plans
live in Dataverse and need the dataverse.py + browser.py paths.

Plan-URL formats:
  Premium:  https://planner.cloud.microsoft/webui/premiumplan/{guid}/org/{guid}/...
  Basic:    https://planner.cloud.microsoft/webui/plan/{base64-id}/view/board?tid=...
            https://tasks.office.com/{tenant}/Home/PlanViews/{base64-id}

The basic plan id is a Graph plan id (URL-safe base64) — pass it straight to
`/planner/plans/{id}`.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

import requests

from auth import _load_cache, _app, _save_cache, CACHE_DIR  # noqa: F401

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


def acquire_graph_token(tenant: str = "common", interactive: bool = True) -> str:
    # Share the cache with the existing Dataverse auth — same client id +
    # tenant + signed-in account, just a different scope.
    cache = _load_cache(tenant)
    app = _app(tenant, cache)
    accounts = app.get_accounts()
    if accounts:
        res = app.acquire_token_silent(GRAPH_SCOPE, account=accounts[0])
        if res and "access_token" in res:
            _save_cache(tenant, cache)
            return res["access_token"]
    if not interactive:
        raise RuntimeError("no cached Graph token — run `planner auth` to sign in")
    print("Acquiring Graph token (browser may open)…", flush=True)
    if os.environ.get("PLANNER_FORCE_DEVICE_CODE"):
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPE)
        if "user_code" not in flow:
            raise RuntimeError(f"device flow failed to start: {json.dumps(flow, indent=2)}")
        print(flow["message"], flush=True)
        res = app.acquire_token_by_device_flow(flow)
    else:
        res = app.acquire_token_interactive(scopes=GRAPH_SCOPE, prompt="select_account")
    _save_cache(tenant, cache)
    if "access_token" not in res:
        raise RuntimeError(
            f"Graph auth failed: {res.get('error')} — {res.get('error_description')}"
        )
    return res["access_token"]


def parse_plan_url(url_or_id: str) -> Tuple[str, str, Optional[str]]:
    """Return (kind, plan_id, tenant) where kind ∈ {"basic", "premium"}.

    Accepts a planner.cloud.microsoft URL, a tasks.office.com URL, or a raw
    plan id. Premium ids are GUIDs; basic ids are 28-char URL-safe base64.
    """
    s = url_or_id.strip()
    if not s.startswith("http"):
        if re.fullmatch(r"[0-9a-fA-F-]{36}", s):
            return ("premium", s, None)
        return ("basic", s, None)
    parsed = urlparse(s)
    tenant = parse_qs(parsed.query).get("tid", [None])[0]
    parts = [p for p in parsed.path.split("/") if p]
    # /webui/premiumplan/{guid}/org/{guid}/view/...
    if "premiumplan" in parts:
        i = parts.index("premiumplan")
        return ("premium", parts[i + 1], tenant)
    # /webui/plan/{id}/view/...
    if "plan" in parts:
        i = parts.index("plan")
        return ("basic", parts[i + 1], tenant)
    # tasks.office.com/{tenant}/Home/PlanViews/{id}
    if "PlanViews" in parts:
        i = parts.index("PlanViews")
        return ("basic", parts[i + 1], tenant)
    raise ValueError(f"Could not extract a plan id from {url_or_id!r}")


class GraphClient:
    def __init__(self, token: str):
        self.token = token
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.s.headers["Content-Type"] = "application/json"

    def _url(self, path: str) -> str:
        return f"{GRAPH_BASE}{path}" if path.startswith("/") else f"{GRAPH_BASE}/{path}"

    def get(self, path: str, **params) -> dict:
        r = self.s.get(self._url(path), params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:
        r = self.s.post(self._url(path), json=body, timeout=30)
        if not r.ok:
            raise RuntimeError(f"POST {path} → {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    def patch(self, path: str, body: dict, etag: str) -> dict:
        headers = {"If-Match": etag, "Prefer": "return=representation"}
        r = self.s.patch(self._url(path), json=body, headers=headers, timeout=30)
        if not r.ok:
            raise RuntimeError(f"PATCH {path} → {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    def delete(self, path: str, etag: str) -> None:
        r = self.s.delete(self._url(path), headers={"If-Match": etag}, timeout=30)
        if r.status_code not in (204, 200):
            raise RuntimeError(f"DELETE {path} → {r.status_code}: {r.text}")

    # ── high-level Planner ops ────────────────────────────────────────

    def get_plan(self, plan_id: str) -> dict:
        return self.get(f"/planner/plans/{plan_id}")

    def get_plan_details(self, plan_id: str) -> dict:
        return self.get(f"/planner/plans/{plan_id}/details")

    def list_buckets(self, plan_id: str) -> list:
        return self.get(f"/planner/plans/{plan_id}/buckets").get("value", [])

    def create_bucket(self, plan_id: str, name: str, order_hint: str = " !") -> dict:
        return self.post("/planner/buckets", {
            "name": name, "planId": plan_id, "orderHint": order_hint,
        })

    def list_tasks(self, plan_id: str) -> list:
        return self.get(f"/planner/plans/{plan_id}/tasks").get("value", [])

    def create_task(self, plan_id: str, title: str, *, bucket_id: Optional[str] = None,
                    applied_categories: Optional[dict] = None,
                    priority: Optional[int] = None) -> dict:
        body = {"planId": plan_id, "title": title}
        if bucket_id:
            body["bucketId"] = bucket_id
        if applied_categories:
            body["appliedCategories"] = applied_categories
        if priority is not None:
            body["priority"] = priority
        return self.post("/planner/tasks", body)

    def set_task_description(self, task_id: str, description: str) -> dict:
        details = self.get(f"/planner/tasks/{task_id}/details")
        etag = details.get("@odata.etag")
        return self.patch(f"/planner/tasks/{task_id}/details",
                          {"description": description}, etag)

    def update_task(self, task_id: str, body: dict) -> dict:
        task = self.get(f"/planner/tasks/{task_id}")
        return self.patch(f"/planner/tasks/{task_id}", body, task["@odata.etag"])

    def complete_task(self, task_id: str) -> dict:
        return self.update_task(task_id, {"percentComplete": 100})

    # ── label ↔ category slot mapping ─────────────────────────────────

    def ensure_label_map(self, plan_id: str, label_names: list) -> dict:
        """Return {label_name: 'categoryN'} mapping. Defines new slots in plan
        details when needed. Plans support 25 named slots (category1..25).
        """
        details = self.get_plan_details(plan_id)
        etag = details["@odata.etag"]
        cats = dict(details.get("categoryDescriptions") or {})  # categoryN -> name|null

        # Existing name -> slot
        name_to_slot = {v: k for k, v in cats.items() if v}
        free_slots = [f"category{i}" for i in range(1, 26) if not cats.get(f"category{i}")]

        new_assignments: dict = {}
        for raw in label_names:
            name = (raw or "").strip()
            if not name or name in name_to_slot:
                continue
            if not free_slots:
                raise RuntimeError(
                    f"Plan has no free category slot for label {name!r} "
                    "(Planner caps at 25 named labels)."
                )
            slot = free_slots.pop(0)
            cats[slot] = name
            name_to_slot[name] = slot
            new_assignments[slot] = name

        if new_assignments:
            self.patch(f"/planner/plans/{plan_id}/details",
                       {"categoryDescriptions": cats}, etag)

        return name_to_slot
