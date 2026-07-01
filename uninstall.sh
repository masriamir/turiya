#!/bin/bash
# =============================================================================
# uninstall.sh — Remove restic-backup launchd job and optionally clean up
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup.conf"
PLIST_DEST="$HOME/Library/LaunchAgents/com.amir.restic-backup.plist"

# shellcheck source=backup.conf
source "$CONFIG_FILE"

info()    { echo "[uninstall] $*"; }
success() { echo "[uninstall] ✓ $*"; }
warn()    { echo "[uninstall] ⚠ $*"; }

# ── 1. Unload launchd job ─────────────────────────────────────────────────────
info "Unloading launchd job..."
if [[ -f "$PLIST_DEST" ]]; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    success "launchd job removed."
else
    warn "Plist not found at $PLIST_DEST — already removed?"
fi

# ── 2. pmset ──────────────────────────────────────────────────────────────────
info "Removing pmset wake schedule..."
info "(Requires sudo)"
sudo pmset repeat cancel 2>/dev/null || true
success "pmset schedule cleared."

# ── 3. Optional: remove Keychain entry ───────────────────────────────────────
echo ""
read -r -p "Remove restic password from Keychain? [y/N] " REMOVE_PW
if [[ "$REMOVE_PW" =~ ^[Yy]$ ]]; then
    if security delete-generic-password \
        -a "$KEYCHAIN_ACCOUNT" \
        -s "$KEYCHAIN_SERVICE" 2>/dev/null; then
        success "Keychain entry removed."
    else
        warn "Keychain entry not found."
    fi
else
    info "Keychain entry kept."
fi

# ── 4. Optional: remove logs ─────────────────────────────────────────────────
echo ""
read -r -p "Remove log directory ($LOG_DIR)? [y/N] " REMOVE_LOGS
if [[ "$REMOVE_LOGS" =~ ^[Yy]$ ]]; then
    rm -rf "$LOG_DIR"
    success "Logs removed."
else
    info "Logs kept at $LOG_DIR."
fi

echo ""
echo "Uninstall complete."
echo "Restic repos on your cloud providers are untouched."
echo "Run install.sh to set everything up again."
