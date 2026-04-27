---
name: "planner"
description: "Read and update Microsoft Planner Premium plans (Project for the Web). Use when the user shares a planner.cloud.microsoft URL, asks about tasks in a premium plan, wants to mark tasks complete, change due dates, assign owners, or create tasks. Do NOT use for basic Planner plans — those use Microsoft Graph /planner endpoints directly."
---

# /planner — Microsoft Planner Premium task management

This skill talks to **Dataverse** (where Planner Premium / Project for the Web plans actually live) via the Project schedule APIs. Microsoft Graph's `/planner` endpoints **do not work** for premium plans.

## ⚠️ FIRST STEP — verify install + auth

```bash
PLANNER=~/.copilot/bin/planner
[[ -x "$PLANNER" ]] || { echo "❌ planner skill not installed — run install/install.sh from https://github.com/msft-hub-tlv/planner"; exit 1; }
"$PLANNER" auth --check || "$PLANNER" auth
```

If `auth --check` fails, run `planner auth` and surface the device-code prompt to the user verbatim.

## Recognising a request

Trigger this skill when the user:
- Pastes a URL matching `planner.cloud.microsoft/webui/premiumplan/<guid>/org/<guid>/...`
- Asks to "list / show / update / complete / assign tasks" in a plan they've previously referenced
- Mentions "Project for the Web" or "Planner Premium"

Do **not** trigger for:
- `tasks.office.com` URLs (basic Planner — use `m365_*` Graph tools instead)
- Microsoft To Do (`to-do.office.com`) — out of scope

## Core workflow

### 1. Resolve the URL once

```bash
planner resolve "<full-url>" --json
# → { "envUrl": "https://orgXXXX.crm.dynamics.com", "planId": "<guid>", "tenantId": "<guid>" }
```

Cache the result in the conversation — every subsequent call needs `envUrl` and `planId`.

### 2. List tasks

```bash
planner list "<plan-id-or-url>" --format json
```

Returns an array of `{ id, name, bucket, percentComplete, start, due, assignees, priority, notes }`. Render as a markdown table for the user; never dump raw JSON unless they ask.

### 3. Update a task

For simple fields (name, %complete, priority, notes):

```bash
planner update <taskId> --name "..." --percent 75 --priority high --notes "..."
```

For schedule fields (start, due, effort) — the script automatically routes through the schedule API:

```bash
planner update <taskId> --start 2026-05-01 --due 2026-05-15 --effort 16h
```

Always echo the diff back to the user before confirming success.

### 4. Complete a task

```bash
planner complete <taskId>
```

### 5. Create a task

```bash
planner create --plan <planId> --bucket <bucketId> --name "..." [--assignee user@domain.com]
```

If no bucketId supplied, list buckets first with `planner buckets <planId>` and ask the user to pick one.

## Privacy

Planner data is the user's private work data. The skill is read/write **only against the user's own delegated permissions** — never share task content with third parties or paste it into outbound messages without explicit confirmation.

## Failure modes & recovery

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401 Unauthorized` from Dataverse | token expired | run `planner auth --refresh` |
| `403` on a specific plan | user not a member of the plan's container group | ask user to confirm they can open the URL in a browser |
| `404 msdyn_projects(<id>)` | wrong env URL — user has multiple Dataverse envs | run `planner envs` and ask user which env contains the plan |
| `msdyn_PssUpdateV1` 400 | invalid date/effort format | dates must be ISO `YYYY-MM-DD`, effort like `8h` or `2d` |

## Repo + version

- Source: https://github.com/msft-hub-tlv/planner
- Local install: `~/.copilot/m-skills/planner/`
- Version pinned in `~/.copilot/m-skills/planner/VERSION`

If a future release ships an `auto_update.py` (like hub-radar), wire it in here. v0.1 has no auto-update — the user updates manually with `git pull && ./install/install.sh`.
