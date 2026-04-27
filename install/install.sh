#!/usr/bin/env bash
#
# install.sh — install/update the planner Clawpilot skill (macOS / Linux).
#
# Modes:
#   ./install.sh                 # install/update from the cloned repo
#   ./install.sh --from-url URL  # clone (or pull) from a Git URL into a temp dir
#
# Idempotent. Safe to re-run.
#
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_DIR="$HOME/.copilot/m-skills/planner"
BIN_DIR="$HOME/.copilot/bin"
BACKUP_DIR="$HOME/.copilot/m-skills/_backups/planner-$(date +%Y%m%d-%H%M%S)"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

# ── args ─────────────────────────────────────────────────────────────────
FROM_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-url) FROM_URL="$2"; shift 2 ;;
    -h|--help)  sed -n '3,12p' "$0"; exit 0 ;;
    *) red "unknown arg: $1"; exit 2 ;;
  esac
done

if [[ -n "$FROM_URL" ]]; then
  WORK="$(mktemp -d)/planner"
  cyan "▶ Cloning $FROM_URL → $WORK"
  git clone --depth 1 "$FROM_URL" "$WORK"
  REPO_ROOT="$WORK"
fi

# ── python ───────────────────────────────────────────────────────────────
cyan "▶ Locating Python ≥ ${MIN_PY_MAJOR}.${MIN_PY_MINOR}"
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR,$MIN_PY_MINOR) else 1)"; then
      PY="$cand"; break
    fi
  fi
done
[[ -n "$PY" ]] || { red "Python ≥ ${MIN_PY_MAJOR}.${MIN_PY_MINOR} not found. Install via brew: brew install python@3.12"; exit 1; }
green "  using $($PY -V) at $(command -v $PY)"

# ── stage skill files ────────────────────────────────────────────────────
if [[ -d "$SKILL_DIR" ]]; then
  cyan "▶ Backing up existing skill → $BACKUP_DIR"
  mkdir -p "$(dirname "$BACKUP_DIR")"
  cp -R "$SKILL_DIR" "$BACKUP_DIR"
fi

cyan "▶ Installing skill → $SKILL_DIR"
mkdir -p "$SKILL_DIR"
rsync -a --delete --exclude='.venv' --exclude='.cache' \
  "$REPO_ROOT/skill/" "$SKILL_DIR/"
cp "$REPO_ROOT/VERSION" "$SKILL_DIR/VERSION"

# ── venv + deps ──────────────────────────────────────────────────────────
cyan "▶ Creating venv at $SKILL_DIR/.venv"
"$PY" -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$SKILL_DIR/.venv/bin/python" -m pip install --quiet -r "$SKILL_DIR/requirements.txt"

# ── launcher ─────────────────────────────────────────────────────────────
cyan "▶ Installing launcher → $BIN_DIR/planner"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/planner" <<EOF
#!/usr/bin/env bash
exec "$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/planner.py" "\$@"
EOF
chmod +x "$BIN_DIR/planner"

# ── done ─────────────────────────────────────────────────────────────────
green "✅ planner skill installed (v$(cat "$SKILL_DIR/VERSION"))"
cat <<EOF

Next steps:
  1. Add to PATH if not already:  export PATH="\$HOME/.copilot/bin:\$PATH"
  2. Sign in:                     planner auth
  3. Try:                         planner resolve "<your planner.cloud.microsoft URL>"
  4. Restart Clawpilot to pick up the new /planner skill.
EOF
