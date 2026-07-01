#!/bin/bash
# =============================================================================
# install.sh — One-time setup for restic-backup
# =============================================================================
# Safe to re-run: skips steps that are already done.
# Run as your normal user (not root). sudo is only used for pmset.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup.conf"
PLIST_TEMPLATE="$SCRIPT_DIR/com.amir.restic-backup.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/com.amir.restic-backup.plist"

# shellcheck source=backup.conf
source "$CONFIG_FILE"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo "[install] $*"; }
success() { echo "[install] ✓ $*"; }
warn()    { echo "[install] ⚠ $*"; }
error()   { echo "[install] ✗ $*" >&2; exit 1; }

# ── 1. Dependency check ───────────────────────────────────────────────────────
info "Checking dependencies..."
for cmd in restic rclone jq; do
    if ! command -v "$cmd" &>/dev/null; then
        error "'$cmd' not found. Run: brew install restic rclone jq"
    fi
done
success "restic, rclone, and jq found."

# ── 2. Keychain password ──────────────────────────────────────────────────────
info "Checking Keychain for restic password..."
if security find-generic-password \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$KEYCHAIN_SERVICE" \
    &>/dev/null; then
    success "Password already in Keychain — skipping."
else
    info "No password found. Enter your restic repository password."
    info "(This is the password that encrypts your backups. Store it somewhere safe.)"
    read -r -s -p "  Password: " RESTIC_PASS
    echo
    read -r -s -p "  Confirm:  " RESTIC_PASS_CONFIRM
    echo
    if [[ "$RESTIC_PASS" != "$RESTIC_PASS_CONFIRM" ]]; then
        error "Passwords do not match. Re-run install.sh."
    fi
    security add-generic-password \
        -a "$KEYCHAIN_ACCOUNT" \
        -s "$KEYCHAIN_SERVICE" \
        -w "$RESTIC_PASS"
    success "Password stored in Keychain."
fi

# ── 3. Rclone remote check ────────────────────────────────────────────────────
info "Checking rclone remotes..."
RCLONE_REMOTES=$(rclone listremotes 2>/dev/null || true)
ALL_REMOTES_OK=true

for REPO in "${REPOS[@]}"; do
    # Extract remote name from "rclone:<remote>:<path>"
    REMOTE="${REPO#rclone:}"
    REMOTE="${REMOTE%%:*}"
    if echo "$RCLONE_REMOTES" | grep -q "^${REMOTE}:$"; then
        success "rclone remote '$REMOTE' found."
    else
        warn "rclone remote '$REMOTE' not configured. Run: rclone config"
        ALL_REMOTES_OK=false
    fi
done

if ! $ALL_REMOTES_OK; then
    warn "Some rclone remotes are missing. Configure them before initialising repos."
    warn "Re-run install.sh after configuring rclone."
    exit 1
fi

# ── 4. Init restic repositories ───────────────────────────────────────────────
RESTIC_PASSWORD=$(security find-generic-password \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$KEYCHAIN_SERVICE" \
    -w)
export RESTIC_PASSWORD

info "Checking restic repositories..."
for REPO in "${REPOS[@]}"; do
    if restic -r "$REPO" snapshots &>/dev/null; then
        success "Repo '$REPO' already initialised — skipping."
    else
        info "Initialising repo: $REPO"
        if restic -r "$REPO" init; then
            success "Repo '$REPO' initialised."
        else
            error "Failed to initialise repo '$REPO'. Check rclone config and credentials."
        fi
    fi
done

# ── 5. Generate and install plist ─────────────────────────────────────────────
info "Generating launchd plist..."

# Calculate pmset wake time (backup time minus offset)
WAKE_HOUR=$BACKUP_HOUR
WAKE_MINUTE=$(( BACKUP_MINUTE - PMSET_WAKE_OFFSET_MINUTES ))
if (( WAKE_MINUTE < 0 )); then
    WAKE_MINUTE=$(( WAKE_MINUTE + 60 ))
    WAKE_HOUR=$(( WAKE_HOUR - 1 ))
fi
WAKE_TIME=$(printf "%02d:%02d:00" "$WAKE_HOUR" "$WAKE_MINUTE")

# Render the plist from the template
sed \
    -e "s|{{HOME}}|$HOME|g" \
    -e "s|{{SCRIPT_DIR}}|$SCRIPT_DIR|g" \
    -e "s|{{BACKUP_WEEKDAY}}|$BACKUP_WEEKDAY|g" \
    -e "s|{{BACKUP_HOUR}}|$BACKUP_HOUR|g" \
    -e "s|{{BACKUP_MINUTE}}|$BACKUP_MINUTE|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

success "Plist written to $PLIST_DEST."

# ── 6. Load launchd job ───────────────────────────────────────────────────────
info "Loading launchd job..."
# Unload first if already loaded (idempotent)
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"
success "launchd job loaded."

# ── 7. Configure pmset wake ───────────────────────────────────────────────────
info "Configuring pmset wake schedule ($WAKE_TIME daily)..."
info "(Requires sudo)"
sudo pmset repeat wakeorpoweron MTWRFSU "$WAKE_TIME"
success "pmset wake set to $WAKE_TIME every day."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " Install complete."
echo ""
echo " Backups will run every Sunday at:"
echo "   ${BACKUP_HOUR}:$(printf '%02d' $BACKUP_MINUTE) (backup)"
echo "   ${WAKE_HOUR}:$(printf '%02d' $WAKE_MINUTE) (wake)"
echo ""
echo " Test your setup:"
echo "   bash backup.sh --dry-run"
echo "   bash backup.sh"
echo ""
echo " Logs: $LOG_DIR"
echo "=========================================="
