#!/bin/bash
# =============================================================================
# backup.sh — Restic backup runner
# =============================================================================
# Reads all config from backup.conf. Do not hardcode anything here.
# Run manually:  bash backup.sh
# Run dry-run:   bash backup.sh --dry-run
# =============================================================================

set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup.conf"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: backup.conf not found at $CONFIG_FILE" >&2
    exit 1
fi

# shellcheck source=backup.conf
source "$CONFIG_FILE"

# ── Dry-run flag ──────────────────────────────────────────────────────────────
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"

rotate_log() {
    if [[ -f "$LOG_FILE" ]]; then
        local size
        size=$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
        if (( size > LOG_MAX_BYTES )); then
            mv "$LOG_FILE" "${LOG_FILE}.$(date +%Y%m%d%H%M%S).bak"
        fi
    fi
}

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

rotate_log

# ── Dependency checks ─────────────────────────────────────────────────────────
for cmd in restic rclone security; do
    if ! command -v "$cmd" &>/dev/null; then
        log "ERROR: '$cmd' not found in PATH. Is Homebrew on your PATH?"
        exit 1
    fi
done

# ── Retrieve password from Keychain ──────────────────────────────────────────
RESTIC_PASSWORD=$(security find-generic-password \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$KEYCHAIN_SERVICE" \
    -w 2>/dev/null) || {
    log "ERROR: Could not retrieve password from Keychain."
    log "       Run install.sh to set it up, or check account/service names in backup.conf."
    exit 1
}
export RESTIC_PASSWORD

# ── Build exclude flags ───────────────────────────────────────────────────────
EXCLUDE_FLAGS=()
for pattern in "${EXCLUDES[@]}"; do
    EXCLUDE_FLAGS+=("--exclude=${pattern}")
done

# ── Build retention flags ─────────────────────────────────────────────────────
RETENTION_FLAGS=(
    --keep-daily   "$RETENTION_KEEP_DAILY"
    --keep-weekly  "$RETENTION_KEEP_WEEKLY"
    --keep-monthly "$RETENTION_KEEP_MONTHLY"
    --keep-yearly  "$RETENTION_KEEP_YEARLY"
)

# ── Dry-run notice ────────────────────────────────────────────────────────────
if $DRY_RUN; then
    log "=== DRY RUN MODE — no changes will be made ==="
fi

# ── Main backup loop ──────────────────────────────────────────────────────────
log "=========================================="
log "Restic backup started"
log "Sources: ${SOURCES[*]}"
log "Repos:   ${REPOS[*]}"
log "=========================================="

OVERALL_SUCCESS=true

for REPO in "${REPOS[@]}"; do
    log ""
    log "--- Repository: $REPO ---"

    BACKUP_CMD=(
        restic -r "$REPO" backup
        "${SOURCES[@]}"
        "${EXCLUDE_FLAGS[@]}"
        --verbose
    )

    if $DRY_RUN; then
        BACKUP_CMD+=(--dry-run)
    fi

    if "${BACKUP_CMD[@]}" >> "$LOG_FILE" 2>&1; then
        log "Backup to $REPO: SUCCESS"

        if ! $DRY_RUN; then
            log "Running forget/prune on $REPO..."
            if restic -r "$REPO" forget "${RETENTION_FLAGS[@]}" --prune >> "$LOG_FILE" 2>&1; then
                log "Prune on $REPO: SUCCESS"
            else
                log "WARNING: Prune on $REPO failed. Backup data is safe; run manually to clean up."
            fi
        fi
    else
        log "ERROR: Backup to $REPO FAILED."
        OVERALL_SUCCESS=false
    fi
done

log ""
log "=========================================="
if $OVERALL_SUCCESS; then
    log "All backups completed successfully."
else
    log "One or more backups FAILED. Check log above."
fi
log "Finished at $(date)"
log "=========================================="

$OVERALL_SUCCESS  # exit 0 if all succeeded, 1 otherwise
