#!/bin/bash
# =============================================================================
# restore.sh — Restore files from a restic snapshot
# =============================================================================
# Usage:
#   bash restore.sh                                    — interactive guided restore
#   bash restore.sh --repo gdrive                      — use specific remote (gdrive/dropbox/pcloud)
#   bash restore.sh --snapshot abc123                  — restore a specific snapshot ID
#   bash restore.sh --include ~/Documents/invoice.pdf  — restore a specific path
#   bash restore.sh --pattern 'Documents/*/invoices'   — restore paths matching this pattern
#   bash restore.sh --glob '*.pdf'                     — restore files matching this filename glob
#   bash restore.sh --exclude '*.tmp'                  — skip files matching this pattern
#   bash restore.sh --target /tmp/restore              — restore to a custom location
#
# --include/--pattern/--glob are repeatable and all map directly to restic's
# native --include restore flag (restic patterns are already path-aware when
# they contain "/", and match any depth when they don't — --pattern and
# --glob are just clearer names for the same underlying matcher).
# --exclude is repeatable and maps to restic's native --exclude.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

# ── Parse arguments ───────────────────────────────────────────────────────────
REPO_FILTER=""
SNAPSHOT="latest"
TARGET_DIR="$HOME/restic-restore"
INCLUDE_PATTERNS=()
EXCLUDE_PATTERNS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_FILTER="$2"; shift 2 ;;
        --snapshot) SNAPSHOT="$2"; shift 2 ;;
        --target)   TARGET_DIR="$2"; shift 2 ;;
        --include)  INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --pattern)  INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --glob)     INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --exclude)  EXCLUDE_PATTERNS+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging restore
emit_event restore "" info run_start

check_dependencies restic rclone security jq

get_restic_password

if ! SELECTED_REPO=$(resolve_repo "$REPO_FILTER" 2>&1); then
    emit_event restore "" error run_end --str status "failure"
    echo "$SELECTED_REPO" >&2
    exit 1
fi

echo ""
echo "Restore settings:"
echo "  Repo:     $SELECTED_REPO"
echo "  Snapshot: $SNAPSHOT"
echo "  Target:   $TARGET_DIR"
if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
    echo "  Include:  ${INCLUDE_PATTERNS[*]}"
fi
if [[ ${#EXCLUDE_PATTERNS[@]} -gt 0 ]]; then
    echo "  Exclude:  ${EXCLUDE_PATTERNS[*]}"
fi
echo ""

read -r -p "Proceed? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    emit_event restore "$SELECTED_REPO" info run_end --str status "aborted"
    exit 0
fi

mkdir -p "$TARGET_DIR"

RESTORE_CMD=(
    restic -r "$SELECTED_REPO"
    restore "$SNAPSHOT"
    --target "$TARGET_DIR"
    --json --verbose=2
)

if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
    for p in "${INCLUDE_PATTERNS[@]}"; do
        RESTORE_CMD+=(--include "$p")
    done
fi

if [[ ${#EXCLUDE_PATTERNS[@]} -gt 0 ]]; then
    for p in "${EXCLUDE_PATTERNS[@]}"; do
        RESTORE_CMD+=(--exclude "$p")
    done
fi

if "${RESTORE_CMD[@]}" 2>&1 | process_restic_json_stream restore "$SELECTED_REPO"; then
    echo ""
    echo "Restore complete → $TARGET_DIR"
    emit_event restore "$SELECTED_REPO" info run_end --str status "success"
else
    emit_event restore "$SELECTED_REPO" error run_end --str status "failure"
    echo "ERROR: Restore failed." >&2
    exit 1
fi
