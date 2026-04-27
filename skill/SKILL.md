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

```bash
planner update <taskId> --plan "<plan-url>" --name "..." --percent 75 --due 2026-05-15
```

For schedule fields (start, due, effort) the script routes through the schedule API. **Always pass `--plan`** so the browser fallback can open the right plan if Dataverse blocks the write (it usually does — see "Writes" below).

### 4. Complete a task

```bash
planner complete <taskId> --plan "<plan-url>"
```

### 5. Create a task

```bash
planner create --plan "<plan-url>" --name "..." [--bucket-name "Backlog"]
```

`--bucket` takes a bucket GUID for the Dataverse path; `--bucket-name` takes the visible label for the browser path. With `--via auto` (default) the skill picks whichever lands in the right place.

## Writes — Dataverse vs. browser

Project for the Web ships a **Dataverse plugin that rejects every direct write** to `msdyn_projecttask` (you'll see *"You cannot directly do 'Update'/'Create' operation"*). The sanctioned `msdyn_PssCreateV1` / `msdyn_PssUpdateV1` route also requires the `prvCreatemsdyn_operationset` privilege which delegated user tokens normally don't have.

So writes drive the **`planner.cloud.microsoft` UI** via Playwright + a persistent Edge profile.

### One-time setup

```bash
planner browser-login
```

Opens a visible Edge window with a dedicated profile at `~/.copilot/m-skills/planner/profile`. Sign in with the account that owns the plan, then close the window. The profile persists, so subsequent writes run **headless** with no prompts.

### `--via {auto, api, browser}`

Every write subcommand (`create`, `complete`, `update`) accepts:

- `auto` *(default)* — try Dataverse first, fall back to the browser UI when the plugin block is detected.
- `api` — force Dataverse (will fail today; useful to retry after an admin grants `prvCreatemsdyn_operationset`).
- `browser` — skip Dataverse, drive the UI directly. Recommended when you already know the API will fail, or when you only have the task **name** (browser mode looks up tasks by visible label).

Add `--show-browser` to debug — runs Edge with a visible window.

Failure screenshots land in `~/.copilot/m-skills/planner/.cache/screenshots/`.

## Privacy

Planner data is the user's private work data. The skill is read/write **only against the user's own delegated permissions** — never share task content with third parties or paste it into outbound messages without explicit confirmation.

## Failure modes & recovery

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401 Unauthorized` from Dataverse | token expired | run `planner auth --refresh` |
| `403` on a specific plan | user not a member of the plan's container group | ask user to confirm they can open the URL in a browser |
| `404 msdyn_projects(<id>)` | wrong env URL — multiple Dataverse envs | run `planner envs` and ask user which env contains the plan |
| `"You cannot directly do…"` | Project-for-the-Web plugin block on writes | expected — `--via auto` will fall back to the browser; if you forced `--via api`, drop the flag |
| Browser write times out / asks for sign-in | persistent profile not seeded | run `planner browser-login` |
| Browser can't find the task | task identifier doesn't match a row | pass the exact visible task **name** (case-insensitive substring match) |

## Repo + version

- Source: https://github.com/msft-hub-tlv/planner
- Local install: `~/.copilot/m-skills/planner/`
- Version pinned in `~/.copilot/m-skills/planner/VERSION`

If a future release ships an `auto_update.py` (like hub-radar), wire it in here. v0.1 has no auto-update — the user updates manually with `git pull && ./install/install.sh`.
