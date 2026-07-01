#!/bin/bash
# =============================================================================
# restore.sh — Restore files from a restic snapshot
# =============================================================================
# Usage:
#   bash restore.sh                          — interactive guided restore
#   bash restore.sh --repo gdrive            — use specific remote (gdrive/dropbox/pcloud)
#   bash restore.sh --snapshot abc123        — restore a specific snapshot ID
#   bash restore.sh --include ~/Documents    — restore a specific path
#   bash restore.sh --target /tmp/restore    — restore to a custom location
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup.conf"

# shellcheck source=backup.conf
source "$CONFIG_FILE"

RESTIC_PASSWORD=$(security find-generic-password \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$KEYCHAIN_SERVICE" \
    -w 2>/dev/null) || {
    echo "ERROR: Could not retrieve password from Keychain. Run install.sh first." >&2
    exit 1
}
export RESTIC_PASSWORD

# ── Parse arguments ───────────────────────────────────────────────────────────
REPO_FILTER=""
SNAPSHOT="latest"
INCLUDE_PATH=""
TARGET_DIR="$HOME/restic-restore"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)       REPO_FILTER="$2"; shift 2 ;;
        --snapshot)   SNAPSHOT="$2";    shift 2 ;;
        --include)    INCLUDE_PATH="$2"; shift 2 ;;
        --target)     TARGET_DIR="$2";  shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Select repo ───────────────────────────────────────────────────────────────
SELECTED_REPO=""
if [[ -n "$REPO_FILTER" ]]; then
    for REPO in "${REPOS[@]}"; do
        if [[ "$REPO" == *"$REPO_FILTER"* ]]; then
            SELECTED_REPO="$REPO"
            break
        fi
    done
    if [[ -z "$SELECTED_REPO" ]]; then
        echo "ERROR: No repo matching '$REPO_FILTER' found in backup.conf."
        exit 1
    fi
else
    # Default to first repo
    SELECTED_REPO="${REPOS[0]}"
fi

echo ""
echo "Restore settings:"
echo "  Repo:     $SELECTED_REPO"
echo "  Snapshot: $SNAPSHOT"
echo "  Target:   $TARGET_DIR"
[[ -n "$INCLUDE_PATH" ]] && echo "  Include:  $INCLUDE_PATH"
echo ""

read -r -p "Proceed? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

mkdir -p "$TARGET_DIR"

RESTORE_CMD=(
    restic -r "$SELECTED_REPO"
    restore "$SNAPSHOT"
    --target "$TARGET_DIR"
    --verbose
)

if [[ -n "$INCLUDE_PATH" ]]; then
    RESTORE_CMD+=(--include "$INCLUDE_PATH")
fi

"${RESTORE_CMD[@]}"

echo ""
echo "Restore complete → $TARGET_DIR"
