# Changelog

All notable changes to this project will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

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
