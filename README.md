# planner

> **Read & update Microsoft Planner Premium plans from Clawpilot.** Talks to Dataverse (where premium plans live) via the Project schedule APIs — works for any Planner Premium / Project for the Web plan you can open in `planner.cloud.microsoft`.

[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]() [![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](./VERSION) [![License: Internal](https://img.shields.io/badge/license-internal-lightgrey.svg)]()

---

## Why a skill (not just Graph)?

The Microsoft Graph `/planner` endpoints **do not work for premium plans** — the docs are explicit:

> *Premium plans and tasks aren't available on the Planner API in Microsoft Graph. Only basic plans may be accessed using this API.*

Premium plan data lives in **Dataverse** under the `msdyn_projects` / `msdyn_projecttasks` tables, and writes go through the **Project Scheduling Service** (`msdyn_PssUpdateV1` etc.). This skill wraps that.

## What it gives you

| Command | What it does |
| --- | --- |
| `planner auth`            | MSAL device-code sign-in. Caches a token per tenant. |
| `planner envs`            | List the Dataverse environments you can reach. |
| `planner resolve <url>`   | Parse a Planner Premium URL → `(envUrl, planId)`. |
| `planner list <plan>`     | Print all tasks in a plan (id, name, bucket, %complete, dates, assignees). JSON or table. |
| `planner get <task>`      | Dump a single task with all fields. |
| `planner update <task> --name "..." --percent 50 --due 2026-05-01` | Patch a task. Schedule fields routed through `msdyn_PssUpdateV1`. |
| `planner complete <task>` | Set `msdyn_progress = 1.0` (100 %). |
| `planner create --plan <id> --bucket <id> --name "..."` | Create a new task. |

All commands accept the full Planner Premium URL in place of a plan id.

## Install

```bash
git clone https://github.com/msft-hub-tlv/planner-skill.git
cd planner
./install/install.sh
```

Windows:

```powershell
git clone https://github.com/msft-hub-tlv/planner-skill.git
cd planner
./install/install.ps1
```

The installer:
1. Verifies Python ≥ 3.10
2. Creates a venv at `~/.copilot/m-skills/planner/.venv`
3. Installs `msal`, `requests`
4. Copies `skill/` → `~/.copilot/m-skills/planner/`
5. Symlinks `~/.copilot/bin/planner` → the Python launcher

After install, restart Clawpilot and the `/planner` skill becomes available.

## First run

```bash
planner auth                                    # device-code login
planner resolve "https://planner.cloud.microsoft/webui/premiumplan/<plan-id>/org/<org-id>/view/board?tid=<tenant>"
planner list <plan-url-or-id> --format table
```

## Auth notes

- Uses the well-known **Microsoft Azure PowerShell** public client id (`1950a258-227b-4e31-a9cf-717495945fc2`) — no app registration needed.
- Scope: `https://<environment>.crm.dynamics.com/.default`.
- Token cached at `~/.copilot/m-skills/planner/.cache/msal_<tenant>.bin` (encrypted via OS keyring when available).

## Repo layout

```
planner/
├── README.md            # this file
├── VERSION              # semver, bumped on every release
├── CHANGELOG.md
├── install/
│   ├── install.sh       # macOS/Linux installer
│   └── install.ps1      # Windows installer
└── skill/
    ├── SKILL.md         # what Clawpilot reads when /planner is invoked
    ├── requirements.txt
    └── scripts/
        ├── planner.py   # CLI entrypoint
        ├── auth.py      # MSAL helper
        └── dataverse.py # Web API + schedule API wrappers
```

## Limitations (v0.1)

- Read/write only. No bucket / dependency / resource-assignment management yet.
- No batching — one HTTP call per update. Fine for ≤ 50 tasks at a time.
- `planner list` paginates at 5 000 tasks (Dataverse default).
- No Power BI / reporting hooks.

PRs welcome.
