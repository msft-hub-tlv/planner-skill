# DEPRECATED — moved to hub-skills monorepo

**This standalone repository is no longer maintained.**

`planner` now lives in the `hub-skills` monorepo:

➡️ **https://github.com/msft-hub-tlv/hub-skills/tree/main/skills/planner**

## How to install

```bash
git clone https://github.com/msft-hub-tlv/hub-skills
cd hub-skills
bash install/install.sh --only planner
```

The installer creates the `~/.copilot/bin/planner` launcher, installs the
Playwright Edge channel, and registers `/planner` with Clawpilot
automatically — same as this repo's standalone `install.sh`.

## Why deprecated

Per the 2026-04-28 skills-repo consolidation, all hub skills are now
maintained in one monorepo so we can:

- Share a single installer + auto-update mechanism.
- Bump versions atomically.
- Avoid the "8 standalone repos all drifting" problem.

## Last standalone version

`v0.3.0` — same content as `skills/planner/` v0.3.0 in the monorepo.
