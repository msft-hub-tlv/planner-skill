# Changelog

All notable changes to this project will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.1.0] - 2026-04-27

### Added
- Initial skill: MSAL device-code auth, Dataverse env discovery, list/get/update/complete/create task commands.
- Resolves any `planner.cloud.microsoft/webui/premiumplan/...` URL to `(envUrl, planId)`.
- Schedule-affecting writes (start/end/duration/predecessor) routed through `msdyn_PssUpdateV1`; simple field writes use Dataverse PATCH.
- Cross-platform installers (`install.sh`, `install.ps1`) with Python ≥ 3.10 gate and venv isolation.
