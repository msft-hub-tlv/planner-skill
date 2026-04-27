#!/usr/bin/env python3
"""planner — CLI for reading and updating Microsoft Planner Premium plans."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Local imports — script is invoked from anywhere via launcher.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import auth  # noqa: E402
from dataverse import (  # noqa: E402
    Dataverse,
    env_for_org,
    list_environments,
    parse_plan_url,
    split_fields,
)


CONFIG_DIR = Path.home() / ".copilot" / "m-skills" / "planner"
ENV_CACHE = CONFIG_DIR / ".cache" / "envs.json"


# ── helpers ───────────────────────────────────────────────────────────────


def _resolve_plan(arg: str, tenant: str) -> tuple[str, str, str]:
    """Return (envUrl, planId, tenantId) for either a URL or a bare plan id.

    Bare plan id requires a previously-cached env mapping or env URL via env var.
    """
    if arg.lower().startswith("http"):
        parsed = parse_plan_url(arg)
        plan_id, org_id, tid = parsed["planId"], parsed["orgId"], parsed["tenantId"] or tenant
        env_url = _env_url_for_org(org_id, tid)
        return env_url, plan_id, tid

    # bare guid — need PLANNER_ENV_URL hint
    env_url = os.environ.get("PLANNER_ENV_URL")
    if not env_url:
        raise SystemExit(
            "bare plan id supplied but no PLANNER_ENV_URL env var set — "
            "pass the full planner.cloud.microsoft URL instead, or `export PLANNER_ENV_URL=https://orgXXXX.crm.dynamics.com`"
        )
    return env_url.rstrip("/"), arg, tenant


def _env_url_for_org(org_id: str, tenant: str) -> str:
    """Look up an env URL for a Dataverse org id, with on-disk caching."""
    cache = _load_env_cache()
    if org_id in cache:
        return cache[org_id]

    bap_token = auth.acquire_token_for_bap(tenant)
    envs = list_environments(bap_token)
    for e in envs:
        cache[e.org_id.lower()] = e.url
    _save_env_cache(cache)

    env = env_for_org(envs, org_id)
    return env.url


def _load_env_cache() -> dict:
    if ENV_CACHE.exists():
        try:
            return json.loads(ENV_CACHE.read_text())
        except Exception:
            return {}
    return {}


def _save_env_cache(cache: dict) -> None:
    ENV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ENV_CACHE.write_text(json.dumps(cache, indent=2))


def _dataverse(env_url: str, tenant: str) -> Dataverse:
    token = auth.acquire_token(env_url, tenant)
    return Dataverse(env_url, token)


def _parse_effort(s: str) -> int:
    """Convert '8h', '2d', '90m' → minutes (Dataverse msdyn_effort is in minutes)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|h|d|w)?\s*", s, re.I)
    if not m:
        raise ValueError(f"unrecognised effort: {s!r} — try '8h', '2d', '90m'")
    n = float(m.group(1))
    unit = (m.group(2) or "h").lower()
    return int(n * {"m": 1, "h": 60, "d": 60 * 8, "w": 60 * 8 * 5}[unit])


def _print(rows: list[dict] | dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
        return
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        print("(no rows)")
        return
    cols = ["msdyn_projecttaskid", "msdyn_subject", "msdyn_progress", "msdyn_start", "msdyn_finish"]
    widths = {c: max(len(c), max(len(str(r.get(c, "") or "")) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print(line)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "") or "").ljust(widths[c]) for c in cols))


# ── command handlers ─────────────────────────────────────────────────────


def cmd_auth(args: argparse.Namespace) -> int:
    if args.check:
        ok = auth.check(args.tenant)
        print("authenticated" if ok else "not authenticated")
        return 0 if ok else 1
    if args.clear:
        n = auth.clear(args.tenant if args.tenant != "common" else None)
        print(f"cleared {n} cache files")
        return 0
    # default: trigger a login by acquiring a BAP token
    auth.acquire_token_for_bap(args.tenant, interactive=True)
    print("✅ signed in")
    return 0


def cmd_envs(args: argparse.Namespace) -> int:
    bap_token = auth.acquire_token_for_bap(args.tenant)
    envs = list_environments(bap_token)
    out = [
        {"name": e.name, "url": e.url, "orgId": e.org_id, "tenantId": e.tenant_id}
        for e in envs
    ]
    print(json.dumps(out, indent=2))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    parsed = parse_plan_url(args.url)
    plan_id, org_id, tid = parsed["planId"], parsed["orgId"], parsed["tenantId"] or args.tenant
    env_url = _env_url_for_org(org_id, tid)
    out = {"envUrl": env_url, "planId": plan_id, "orgId": org_id, "tenantId": tid}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for k, v in out.items():
            print(f"{k:10s} {v}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    env_url, plan_id, _ = _resolve_plan(args.plan, args.tenant)
    dv = _dataverse(env_url, args.tenant)
    tasks = dv.list_tasks(plan_id, top=args.top)
    _print(tasks, args.format)
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    env_url = os.environ.get("PLANNER_ENV_URL")
    if not env_url:
        raise SystemExit("set PLANNER_ENV_URL or use `planner resolve <url>` first")
    dv = _dataverse(env_url, args.tenant)
    print(json.dumps(dv.get_task(args.task), indent=2, default=str))
    return 0


def cmd_buckets(args: argparse.Namespace) -> int:
    env_url, plan_id, _ = _resolve_plan(args.plan, args.tenant)
    dv = _dataverse(env_url, args.tenant)
    print(json.dumps(dv.list_buckets(plan_id), indent=2, default=str))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    env_url = args.env_url or os.environ.get("PLANNER_ENV_URL")
    if not env_url:
        raise SystemExit("--env-url required, or set PLANNER_ENV_URL (use `planner resolve <url>` to find it)")
    dv = _dataverse(env_url, args.tenant)

    fields: dict = {}
    if args.name is not None:
        fields["msdyn_subject"] = args.name
    if args.notes is not None:
        fields["msdyn_description"] = args.notes
    if args.priority is not None:
        # 0=low, 100000000=medium (default), 100000001=high, 100000002=urgent
        mapping = {"low": 0, "medium": 100000000, "high": 100000001, "urgent": 100000002}
        fields["msdyn_priority"] = mapping[args.priority]
    if args.percent is not None:
        # msdyn_progress is 0.0–1.0 — must go through schedule API
        fields["msdyn_progress"] = max(0.0, min(1.0, args.percent / 100.0))
    if args.start is not None:
        fields["msdyn_start"] = f"{args.start}T00:00:00Z"
    if args.due is not None:
        fields["msdyn_finish"] = f"{args.due}T00:00:00Z"
    if args.effort is not None:
        fields["msdyn_effort"] = _parse_effort(args.effort)

    if not fields:
        raise SystemExit("no fields to update — pass --name / --percent / --due / --start / --effort / --priority / --notes")

    patchable, scheduling = split_fields(fields)

    if patchable:
        dv.patch(f"msdyn_projecttasks({args.task})", patchable)
    if scheduling:
        dv.schedule_update(args.task, scheduling)

    print(json.dumps({"taskId": args.task, "updated": fields}, indent=2))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    args.percent = 100
    args.name = args.notes = args.priority = args.start = args.due = args.effort = None
    return cmd_update(args)


def cmd_create(args: argparse.Namespace) -> int:
    env_url, plan_id, _ = _resolve_plan(args.plan, args.tenant)
    dv = _dataverse(env_url, args.tenant)
    body = {
        "msdyn_subject": args.name,
        "msdyn_project@odata.bind": f"/msdyn_projects({plan_id})",
    }
    if args.bucket:
        body["msdyn_projectbucket@odata.bind"] = f"/msdyn_projectbuckets({args.bucket})"
    out = dv.post("msdyn_projecttasks", body)
    print(json.dumps(out, indent=2, default=str))
    return 0


# ── arg parser ────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="planner", description=__doc__)
    p.add_argument("--tenant", default=os.environ.get("PLANNER_TENANT", "common"),
                   help="Entra tenant id or domain (default: common, or $PLANNER_TENANT)")

    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auth", help="sign in / check / clear cached tokens")
    a.add_argument("--check", action="store_true")
    a.add_argument("--clear", action="store_true")
    a.set_defaults(func=cmd_auth)

    e = sub.add_parser("envs", help="list reachable Dataverse environments")
    e.set_defaults(func=cmd_envs)

    r = sub.add_parser("resolve", help="parse a Planner URL → envUrl + planId")
    r.add_argument("url")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_resolve)

    li = sub.add_parser("list", help="list tasks in a plan")
    li.add_argument("plan", help="plan URL or plan-id")
    li.add_argument("--top", type=int, default=5000)
    li.add_argument("--format", choices=["json", "table"], default="table")
    li.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="fetch one task")
    g.add_argument("task", help="task GUID")
    g.set_defaults(func=cmd_get)

    bu = sub.add_parser("buckets", help="list buckets in a plan")
    bu.add_argument("plan", help="plan URL or plan-id")
    bu.set_defaults(func=cmd_buckets)

    up = sub.add_parser("update", help="update a task")
    up.add_argument("task", help="task GUID")
    up.add_argument("--env-url", help="env URL (or set PLANNER_ENV_URL)")
    up.add_argument("--name")
    up.add_argument("--notes")
    up.add_argument("--priority", choices=["low", "medium", "high", "urgent"])
    up.add_argument("--percent", type=int, help="0–100")
    up.add_argument("--start", help="YYYY-MM-DD")
    up.add_argument("--due", help="YYYY-MM-DD")
    up.add_argument("--effort", help="e.g. '8h', '2d', '90m'")
    up.set_defaults(func=cmd_update)

    co = sub.add_parser("complete", help="mark a task 100%% complete")
    co.add_argument("task", help="task GUID")
    co.add_argument("--env-url")
    co.set_defaults(func=cmd_complete)

    cr = sub.add_parser("create", help="create a new task in a plan")
    cr.add_argument("--plan", required=True, help="plan URL or plan-id")
    cr.add_argument("--bucket", help="bucket id (optional)")
    cr.add_argument("--name", required=True)
    cr.set_defaults(func=cmd_create)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
