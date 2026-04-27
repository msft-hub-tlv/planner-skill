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

# Dataverse plugin block string emitted by Project for the Web for direct writes.
PLUGIN_BLOCK_MARKERS = (
    "You cannot directly do",
    "msdyn_projecttask",  # appears in the plugin error
    "Try editing it through the Resource editing UI",
    "prvCreatemsdyn_operationset",
)


def _is_plugin_block(exc: Exception) -> bool:
    msg = str(exc)
    return any(m in msg for m in PLUGIN_BLOCK_MARKERS)


def _run_browser(coro):
    import asyncio
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


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


def _do_api_update(dv: Dataverse, task_id: str, fields: dict) -> None:
    patchable, scheduling = split_fields(fields)
    if patchable:
        dv.patch(f"msdyn_projecttasks({task_id})", patchable)
    if scheduling:
        dv.schedule_update(task_id, scheduling)


def cmd_update(args: argparse.Namespace) -> int:
    fields: dict = {}
    if args.name is not None:
        fields["msdyn_subject"] = args.name
    if args.notes is not None:
        fields["msdyn_description"] = args.notes
    if args.priority is not None:
        mapping = {"low": 0, "medium": 100000000, "high": 100000001, "urgent": 100000002}
        fields["msdyn_priority"] = mapping[args.priority]
    if args.percent is not None:
        fields["msdyn_progress"] = max(0.0, min(1.0, args.percent / 100.0))
    if args.start is not None:
        fields["msdyn_start"] = f"{args.start}T00:00:00Z"
    if args.due is not None:
        fields["msdyn_finish"] = f"{args.due}T00:00:00Z"
    if args.effort is not None:
        fields["msdyn_effort"] = _parse_effort(args.effort)

    if not fields:
        raise SystemExit("no fields to update — pass --name / --percent / --due / --start / --effort / --priority / --notes")

    via = getattr(args, "via", "auto")

    api_error: Optional[Exception] = None
    if via in ("auto", "api"):
        try:
            env_url = args.env_url or os.environ.get("PLANNER_ENV_URL")
            if not env_url:
                raise SystemExit("--env-url required (or set PLANNER_ENV_URL); run `planner resolve <url>` first")
            dv = _dataverse(env_url, args.tenant)
            _do_api_update(dv, args.task, fields)
            print(json.dumps({"taskId": args.task, "updated": fields, "via": "api"}, indent=2))
            return 0
        except Exception as exc:
            api_error = exc
            if via == "api" or not _is_plugin_block(exc):
                raise
            print(f"⚠ Dataverse blocked the write — falling back to browser UI.", file=sys.stderr)

    # Browser path
    if not args.plan:
        raise SystemExit(
            "Browser fallback needs --plan <plan-url> so it can open the plan in Edge."
            + (f"\n(Dataverse error was: {api_error})" if api_error else "")
        )
    from browser import BrowserPlanner

    name = args.name
    percent = args.percent
    start = args.start
    due = args.due

    async def _run():
        async with BrowserPlanner(headless=not args.show_browser) as bp:
            return await bp.update_task(
                args.plan, args.task,
                name=name, percent=percent, start=start, due=due,
            )

    out = _run_browser(_run())
    print(json.dumps({**out, "via": "browser"}, indent=2))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    via = getattr(args, "via", "auto")

    if via in ("auto", "api"):
        try:
            env_url = args.env_url or os.environ.get("PLANNER_ENV_URL")
            if not env_url:
                raise SystemExit("--env-url required (or set PLANNER_ENV_URL); run `planner resolve <url>` first")
            dv = _dataverse(env_url, args.tenant)
            _do_api_update(dv, args.task, {"msdyn_progress": 1.0})
            print(json.dumps({"taskId": args.task, "completed": True, "via": "api"}, indent=2))
            return 0
        except Exception as exc:
            if via == "api" or not _is_plugin_block(exc):
                raise
            print("⚠ Dataverse blocked the write — falling back to browser UI.", file=sys.stderr)

    if not args.plan:
        raise SystemExit("Browser fallback needs --plan <plan-url>.")
    from browser import BrowserPlanner

    async def _run():
        async with BrowserPlanner(headless=not args.show_browser) as bp:
            return await bp.complete_task(args.plan, args.task)

    out = _run_browser(_run())
    print(json.dumps({**out, "via": "browser"}, indent=2))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    via = getattr(args, "via", "auto")

    if via in ("auto", "api"):
        try:
            env_url, plan_id, _ = _resolve_plan(args.plan, args.tenant)
            dv = _dataverse(env_url, args.tenant)
            body = {
                "msdyn_subject": args.name,
                "msdyn_project@odata.bind": f"/msdyn_projects({plan_id})",
            }
            if args.bucket:
                body["msdyn_projectbucket@odata.bind"] = f"/msdyn_projectbuckets({args.bucket})"
            out = dv.post("msdyn_projecttasks", body)
            print(json.dumps({**(out if isinstance(out, dict) else {"raw": out}), "via": "api"}, indent=2, default=str))
            return 0
        except Exception as exc:
            if via == "api" or not _is_plugin_block(exc):
                raise
            print("⚠ Dataverse blocked the write — falling back to browser UI.", file=sys.stderr)

    from browser import BrowserPlanner

    async def _run():
        async with BrowserPlanner(headless=not args.show_browser) as bp:
            return await bp.create_task(args.plan, args.name, bucket_name=args.bucket_name)

    out = _run_browser(_run())
    print(json.dumps({**out, "via": "browser"}, indent=2))
    return 0


def cmd_browser_login(args: argparse.Namespace) -> int:
    """Open Edge with our persistent profile so the user can sign in once."""
    from browser import BrowserPlanner, PROFILE_DIR

    print(f"Opening Edge with persistent profile at {PROFILE_DIR}", flush=True)

    async def _run():
        async with BrowserPlanner(headless=False, slow_mo_ms=20) as bp:
            await bp.login()

    _run_browser(_run())
    print("✅ profile seeded — future writes will run headless.")
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
    up.add_argument("task", help="task GUID (or, for --via browser, the visible task name)")
    up.add_argument("--env-url", help="env URL (or set PLANNER_ENV_URL)")
    up.add_argument("--plan", help="plan URL — required for browser fallback")
    up.add_argument("--via", choices=["auto", "api", "browser"], default="auto",
                    help="auto (default) tries Dataverse then UI; api forces Dataverse; browser forces UI")
    up.add_argument("--show-browser", action="store_true", help="show Edge window instead of headless")
    up.add_argument("--name")
    up.add_argument("--notes")
    up.add_argument("--priority", choices=["low", "medium", "high", "urgent"])
    up.add_argument("--percent", type=int, help="0–100")
    up.add_argument("--start", help="YYYY-MM-DD")
    up.add_argument("--due", help="YYYY-MM-DD")
    up.add_argument("--effort", help="e.g. '8h', '2d', '90m'")
    up.set_defaults(func=cmd_update)

    co = sub.add_parser("complete", help="mark a task 100%% complete")
    co.add_argument("task", help="task GUID (or visible name when --via browser)")
    co.add_argument("--env-url")
    co.add_argument("--plan", help="plan URL — required for browser fallback")
    co.add_argument("--via", choices=["auto", "api", "browser"], default="auto")
    co.add_argument("--show-browser", action="store_true")
    co.set_defaults(func=cmd_complete)

    cr = sub.add_parser("create", help="create a new task in a plan")
    cr.add_argument("--plan", required=True, help="plan URL or plan-id")
    cr.add_argument("--bucket", help="bucket id (Dataverse path)")
    cr.add_argument("--bucket-name", help="bucket display name (browser path)")
    cr.add_argument("--name", required=True)
    cr.add_argument("--via", choices=["auto", "api", "browser"], default="auto")
    cr.add_argument("--show-browser", action="store_true")
    cr.set_defaults(func=cmd_create)

    bl = sub.add_parser("browser-login", help="open Edge once to seed the persistent SSO profile")
    bl.set_defaults(func=cmd_browser_login)

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
