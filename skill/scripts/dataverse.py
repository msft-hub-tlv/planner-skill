"""Thin Dataverse Web API + Project Scheduling Service wrappers.

Spec references:
  - Web API:           https://learn.microsoft.com/power-apps/developer/data-platform/webapi/perform-operations-web-api
  - Schedule API:      https://learn.microsoft.com/dynamics365/project-operations/project-management/schedule-api-preview
  - Project tables:    msdyn_projects, msdyn_projecttasks, msdyn_projectbuckets
  - Premium plans:     plan id from Planner URL == msdyn_projectid
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import requests

API_VERSION = "v9.2"
SCHEDULE_BATCH_TIMEOUT_SEC = 60

# Scheduling fields that MUST go through msdyn_PssUpdateV1, never PATCH.
SCHEDULING_FIELDS = {
    "msdyn_start",
    "msdyn_finish",
    "msdyn_scheduledstart",
    "msdyn_scheduledend",
    "msdyn_effortcompleted",
    "msdyn_effort",
    "msdyn_duration",
    "msdyn_progress",
}


@dataclass
class Env:
    name: str           # display name
    url: str            # https://orgXXXX.crm.dynamics.com
    org_id: str         # dataverse org guid
    tenant_id: str


# ── URL parsing ───────────────────────────────────────────────────────────

_PLAN_URL_RE = re.compile(
    r"planner\.cloud\.microsoft/webui/premiumplan/"
    r"(?P<plan>[0-9a-f-]{36})/org/(?P<org>[0-9a-f-]{36})"
    r"(?:/[^?]*)?(?:\?[^#]*tid=(?P<tid>[0-9a-f-]{36}))?",
    re.I,
)


def parse_plan_url(url: str) -> dict:
    m = _PLAN_URL_RE.search(url)
    if not m:
        raise ValueError(
            f"not a recognised Planner Premium URL — expected planner.cloud.microsoft/webui/premiumplan/<plan-id>/org/<org-id>/...\nGot: {url}"
        )
    return {
        "planId": m.group("plan"),
        "orgId": m.group("org"),
        "tenantId": m.group("tid"),
    }


# ── Env discovery via BAP ────────────────────────────────────────────────


def list_environments(bap_token: str) -> list[Env]:
    """Enumerate Dataverse environments the signed-in user can reach.

    Uses Global Discovery Service (every Dataverse instance the user has any
    role in, including hidden ones like the Project for the Web /
    Planner-Premium default env). The BAP admin endpoint only returns envs
    you administer — too narrow.

    `bap_token` here is actually a globaldisco-scoped token despite the name
    (kept for backward compat with the function signature).
    """
    resp = requests.get(
        "https://globaldisco.crm.dynamics.com/api/discovery/v2.0/Instances",
        headers={"Authorization": f"Bearer {bap_token}", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    out: list[Env] = []
    for inst in resp.json().get("value", []):
        url = inst.get("ApiUrl") or inst.get("Url")
        org_id = inst.get("Id")
        if not url or not org_id:
            continue
        out.append(
            Env(
                name=inst.get("FriendlyName") or inst.get("UniqueName") or "<unnamed>",
                url=url.rstrip("/"),
                org_id=org_id,
                tenant_id=inst.get("TenantId") or "",
            )
        )
    return out


def env_for_org(envs: Iterable[Env], org_id: str) -> Env:
    org_id = org_id.lower()
    for e in envs:
        if e.org_id.lower() == org_id:
            return e
    raise LookupError(
        f"no Dataverse env in your reachable list matches org id {org_id} — "
        "you may need to be added to the environment, or sign in with a different account"
    )


# ── Web API helpers ──────────────────────────────────────────────────────


class Dataverse:
    def __init__(self, env_url: str, token: str):
        self.base = f"{env_url.rstrip('/')}/api/data/{API_VERSION}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Prefer": "odata.include-annotations=*",
        }

    # ---- generic ----

    def get(self, path: str, **params: Any) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        r = requests.get(url, headers=self.headers, params=params, timeout=30)
        if not r.ok:
            raise _api_error(r)
        return r.json()

    def patch(self, path: str, body: dict) -> None:
        url = f"{self.base}/{path.lstrip('/')}"
        h = {**self.headers, "Content-Type": "application/json", "If-Match": "*"}
        r = requests.patch(url, headers=h, data=json.dumps(body), timeout=30)
        if not r.ok:
            raise _api_error(r)

    def post(self, path: str, body: dict) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        h = {**self.headers, "Content-Type": "application/json"}
        r = requests.post(url, headers=h, data=json.dumps(body), timeout=30)
        if not r.ok:
            raise _api_error(r)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    # ---- domain ----

    def get_plan(self, plan_id: str) -> dict:
        return self.get(
            f"msdyn_projects({plan_id})",
            **{"$select": "msdyn_projectid,msdyn_subject,msdyn_taskearlieststart,msdyn_finish"},
        )

    def list_buckets(self, plan_id: str) -> list[dict]:
        r = self.get(
            "msdyn_projectbuckets",
            **{
                "$filter": f"_msdyn_project_value eq {plan_id}",
                "$select": "msdyn_projectbucketid,msdyn_name",
                "$orderby": "msdyn_name asc",
            },
        )
        return r.get("value", [])

    def list_tasks(self, plan_id: str, top: int = 5000) -> list[dict]:
        r = self.get(
            "msdyn_projecttasks",
            **{
                "$filter": f"_msdyn_project_value eq {plan_id}",
                "$select": ",".join([
                    "msdyn_projecttaskid",
                    "msdyn_subject",
                    "msdyn_progress",
                    "msdyn_start",
                    "msdyn_finish",
                    "msdyn_priority",
                    "msdyn_description",
                    "_msdyn_projectbucket_value",
                ]),
                "$orderby": "msdyn_start asc",
                "$top": top,
            },
        )
        return r.get("value", [])

    def get_task(self, task_id: str) -> dict:
        return self.get(f"msdyn_projecttasks({task_id})")

    # ---- Scheduling API ----

    def schedule_update(self, task_id: str, fields: dict) -> dict:
        """Update via msdyn_PssUpdateV1 inside a fresh OperationSet."""
        op_set = self.post(
            "msdyn_CreateOperationSetV1",
            {"Description": f"planner-skill update {task_id}"},
        )
        op_set_id = op_set.get("OperationSetId") or op_set.get("operationSetId")
        if not op_set_id:
            raise RuntimeError(f"CreateOperationSetV1 returned no id: {op_set}")

        entity = {
            "@@odata.type": "Microsoft.Dynamics.CRM.msdyn_projecttask",
            "msdyn_projecttaskid": task_id,
            **fields,
        }
        self.post(
            "msdyn_PssUpdateV1",
            {"Entity": entity, "OperationSetId": op_set_id},
        )
        return self.post(
            "msdyn_ExecuteOperationSetV1",
            {"OperationSetId": op_set_id},
        )


# ── error formatting ─────────────────────────────────────────────────────


def _api_error(r: requests.Response) -> RuntimeError:
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return RuntimeError(
        f"Dataverse {r.request.method} {urlparse(r.url).path} → {r.status_code}\n"
        + json.dumps(body, indent=2)[:1500]
    )


def split_fields(fields: dict) -> tuple[dict, dict]:
    """Partition a dict of column → value into (patchable, scheduling)."""
    patch: dict = {}
    sched: dict = {}
    for k, v in fields.items():
        (sched if k in SCHEDULING_FIELDS else patch)[k] = v
    return patch, sched
