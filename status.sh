#!/bin/bash
# =============================================================================
# status.sh — Check snapshot status across all configured repos
# =============================================================================
# Usage:
#   bash status.sh            — show latest snapshot per repo
#   bash status.sh --all      — show all snapshots per repo
#   bash status.sh --check    — run restic check (integrity verification)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup.conf"

# shellcheck source=backup.conf
source "$CONFIG_FILE"

MODE="${1:---latest}"

RESTIC_PASSWORD=$(security find-generic-password \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$KEYCHAIN_SERVICE" \
    -w 2>/dev/null) || {
    echo "ERROR: Could not retrieve password from Keychain. Run install.sh first." >&2
    exit 1
}
export RESTIC_PASSWORD

for REPO in "${REPOS[@]}"; do
    echo ""
    echo "════════════════════════════════════════"
    echo "  Repo: $REPO"
    echo "════════════════════════════════════════"

    case "$MODE" in
        --all)
            restic -r "$REPO" snapshots
            ;;
        --check)
            echo "Running integrity check (this may take a while)..."
            restic -r "$REPO" check
            ;;
        *)
            restic -r "$REPO" snapshots --last
            ;;
    esac
done
