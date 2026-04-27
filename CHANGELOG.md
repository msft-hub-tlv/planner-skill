# Changelog

All notable changes to this project will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.3.0] - 2026-04-27

### Added
- **Microsoft Graph path for basic Planner plans.** `scripts/graph.py` implements `GraphClient` with task/bucket/details/category-description endpoints, a `parse_plan_url` that recognises both `/webui/plan/...` (basic) and `/webui/premiumplan/...` (Premium) URLs, and `ensure_label_map` that lazily defines `categoryN` slots in plan details so tag names can be passed by string. Token reuses the existing MSAL cache (Azure CLI public client) — same sign-in covers Dataverse + Graph.
- **`planner bulk-create --csv FILE`** — CSV columns `Bucket, Task Name, Description, Tags`. On basic plans it auto-creates missing buckets, defines all referenced labels in one PATCH on plan details, then creates each task with `bucketId` + `appliedCategories`, followed by a details PATCH for `description`. On Premium plans it falls back to the v0.2 browser path.
- **`planner create --description ... --tags ...`** flags. Basic plans send these natively via Graph; Premium plans force `--via browser` automatically.
- Smart routing: `cmd_create` and `cmd_bulk_create` parse the plan URL and dispatch to Graph (basic) or Dataverse/browser (Premium) without any user-visible flag changes.

### Notes
- Planner caps named labels at 25 per plan (`category1`..`category25`); `ensure_label_map` raises a clear error if the CSV references more than that, and never overwrites existing label names.
- Basic Planner has no Sprint, Effort, or per-Bucket-list richness; description is a free-text field on `tasks/{id}/details`, and labels are boolean flags in `appliedCategories`.

### Verified
- 36-task CSV (`spyhub_skill_planner_v4.csv`) bulk-loaded into a basic plan in tenant 72f988bf in ~30s; spot-checked task has correct title, bucket, 4 labels, and description.

## [0.2.1] - 2026-04-27

### Fixed
- **Browser fallback no longer crashes with "cannot reuse already awaited coroutine."** `_run_browser` now accepts a coroutine *factory* (callable) instead of a pre-built coroutine, so the `RuntimeError` retry path can request a fresh coroutine. The previous wrapper masked real Playwright errors by re-raising as a coroutine-reuse error.
- **Planner grid now waits for actual UI controls before acting.** `_open_plan` previously waited only for an empty `role=grid` skeleton, which appeared seconds before the Add-task button was available, causing "Could not find an Add-task control" failures on slower loads. Wait now targets the Add-task button / inline textbox / first gridcell, with a 90 s ceiling and a brief post-load settle.

### Verified
- End-to-end create against a Premium plan in tenant 72f988bf (Microsoft corp) successfully created `Dummy task v0.2 test` via the browser fallback after the plugin block. Task confirmed via `planner list`.

## [0.2.0] - 2026-04-27

### Added
- **Browser automation for writes.** Project for the Web's Dataverse plugin rejects every direct create/update on `msdyn_projecttask`; the privileged `msdyn_PssCreateV1` / `msdyn_PssUpdateV1` route also requires `prvCreatemsdyn_operationset`, which delegated user tokens normally lack. Writes now drive `planner.cloud.microsoft` via Playwright + a persistent Edge profile.
- `scripts/browser.py` — async `BrowserPlanner` using `launch_persistent_context` (Edge channel, `~/.copilot/m-skills/planner/profile`).
- `planner browser-login` — one-time visible Edge launch to seed the profile; subsequent calls run headless.
- `--via {auto,api,browser}` flag on `create`, `complete`, `update`. Default `auto` tries Dataverse first and falls back to the UI on the known plugin block.
- `--show-browser` flag for debugging (visible window).
- `--bucket-name` on `create` for the browser path (vs. `--bucket` GUID for the Dataverse path).
- `--plan` arg added to `complete` and `update` so the browser fallback can open the right plan.
- `install.sh` runs `playwright install msedge` after pip install.

### Changed
- `requirements.txt`: added `playwright>=1.50`.
- `SKILL.md`: documents the Dataverse-write block, the browser fallback, `browser-login`, and the `--via` flag.

## [0.1.0] - 2026-04-27

### Added
- Initial skill: MSAL device-code auth, Dataverse env discovery, list/get/update/complete/create task commands.
- Resolves any `planner.cloud.microsoft/webui/premiumplan/...` URL to `(envUrl, planId)`.
- Schedule-affecting writes (start/end/duration/predecessor) routed through `msdyn_PssUpdateV1`; simple field writes use Dataverse PATCH.
- Cross-platform installers (`install.sh`, `install.ps1`) with Python ≥ 3.10 gate and venv isolation.
