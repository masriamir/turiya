#!/bin/bash
# =============================================================================
# backup.sh — Restic backup runner
# =============================================================================
# Reads all config from backup.conf. Do not hardcode anything here.
#
# Usage:
#   bash backup.sh                                  — back up all configured SOURCES
#   bash backup.sh --dry-run                        — dry run, no changes
#   bash backup.sh --include ~/Documents/taxes      — back up only this path
#   bash backup.sh --pattern 'Documents/*/invoices' — back up paths matching this pattern
#   bash backup.sh --glob '*.pdf'                   — back up only files matching this filename glob
#   bash backup.sh --exclude '*.iso'                — add an extra exclude pattern for this run
#
# --include/--pattern/--glob are repeatable and may be combined; their
# resolved paths are unioned to REPLACE this run's source list (SOURCES from
# backup.conf is not used when any of these are given). --exclude is
# repeatable and adds to backup.conf's EXCLUDES for this run only.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

# ── Parse arguments ───────────────────────────────────────────────────────────
DRY_RUN=false
INCLUDE_PATHS=()
PATTERN_ARGS=()
GLOB_ARGS=()
EXTRA_EXCLUDES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --include) INCLUDE_PATHS+=("$2"); shift 2 ;;
        --pattern) PATTERN_ARGS+=("$2"); shift 2 ;;
        --glob)    GLOB_ARGS+=("$2"); shift 2 ;;
        --exclude) EXTRA_EXCLUDES+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging backup
emit_event backup "" info run_start

check_dependencies restic rclone security jq

get_restic_password

if [[ ${#REPOS[@]} -eq 0 ]]; then
    log_human "ERROR: REPOS is empty in backup.conf. Configure at least one repo."
    emit_event backup "" error run_end --str status "failure"
    exit 1
fi

# ── Resolve target paths (--include/--pattern/--glob) ────────────────────────
TARGET_PATHS=()

if [[ ${#INCLUDE_PATHS[@]} -gt 0 ]]; then
    for path in "${INCLUDE_PATHS[@]}"; do
        if [[ ! -e "$path" ]]; then
            log_human "ERROR: --include path does not exist: $path"
            emit_event backup "" error run_end --str status "failure"
            exit 1
        fi
        TARGET_PATHS+=("$path")
    done
fi

if [[ ${#PATTERN_ARGS[@]} -gt 0 ]]; then
    for pattern in "${PATTERN_ARGS[@]}"; do
        MATCHES=()
        for source in "${SOURCES[@]}"; do
            while IFS= read -r match; do
                MATCHES+=("$match")
            done < <(find "$source" -path "*${pattern}*" 2>/dev/null)
        done
        if [[ ${#MATCHES[@]} -eq 0 ]]; then
            log_human "ERROR: --pattern '$pattern' matched no files under configured SOURCES."
            emit_event backup "" error run_end --str status "failure"
            exit 1
        fi
        TARGET_PATHS+=("${MATCHES[@]}")
    done
fi

if [[ ${#GLOB_ARGS[@]} -gt 0 ]]; then
    for glob in "${GLOB_ARGS[@]}"; do
        MATCHES=()
        for source in "${SOURCES[@]}"; do
            while IFS= read -r match; do
                MATCHES+=("$match")
            done < <(find "$source" -name "$glob" 2>/dev/null)
        done
        if [[ ${#MATCHES[@]} -eq 0 ]]; then
            log_human "ERROR: --glob '$glob' matched no files under configured SOURCES."
            emit_event backup "" error run_end --str status "failure"
            exit 1
        fi
        TARGET_PATHS+=("${MATCHES[@]}")
    done
fi

if [[ ${#TARGET_PATHS[@]} -eq 0 ]]; then
    TARGET_PATHS=("${SOURCES[@]}")
fi

# ── Build exclude flags ───────────────────────────────────────────────────────
EXCLUDE_FLAGS=()
if [[ ${#EXCLUDES[@]} -gt 0 ]]; then
    for pattern in "${EXCLUDES[@]}"; do
        EXCLUDE_FLAGS+=("--exclude=${pattern}")
    done
fi
if [[ ${#EXTRA_EXCLUDES[@]} -gt 0 ]]; then
    for pattern in "${EXTRA_EXCLUDES[@]}"; do
        EXCLUDE_FLAGS+=("--exclude=${pattern}")
    done
fi

# ── Build retention flags ─────────────────────────────────────────────────────
RETENTION_FLAGS=(
    --keep-daily   "$RETENTION_KEEP_DAILY"
    --keep-weekly  "$RETENTION_KEEP_WEEKLY"
    --keep-monthly "$RETENTION_KEEP_MONTHLY"
    --keep-yearly  "$RETENTION_KEEP_YEARLY"
)

if $DRY_RUN; then
    log_human "=== DRY RUN MODE — no changes will be made ==="
fi

log_human "=========================================="
log_human "Restic backup started"
log_human "Targets: ${TARGET_PATHS[*]}"
log_human "Repos:   ${REPOS[*]}"
log_human "=========================================="

OVERALL_SUCCESS=true

for REPO in "${REPOS[@]}"; do
    log_human ""
    log_human "--- Repository: $REPO ---"

    BACKUP_CMD=(
        restic -r "$REPO" backup
        "${TARGET_PATHS[@]}"
    )
    if [[ ${#EXCLUDE_FLAGS[@]} -gt 0 ]]; then
        BACKUP_CMD+=("${EXCLUDE_FLAGS[@]}")
    fi
    BACKUP_CMD+=(--json --verbose=2)

    if $DRY_RUN; then
        BACKUP_CMD+=(--dry-run)
    fi

    if "${BACKUP_CMD[@]}" 2>&1 | process_restic_json_stream backup "$REPO"; then
        log_human "Backup to $REPO: SUCCESS"

        if ! $DRY_RUN; then
            log_human "Running forget/prune on $REPO..."
            FORGET_JSON=$(restic -r "$REPO" forget "${RETENTION_FLAGS[@]}" --prune --json 2>&1) && {
                REMOVED_COUNT=$(jq '[.[].remove // [] | length] | add // 0' <<<"$FORGET_JSON" 2>/dev/null || echo 0)
                emit_event backup "$REPO" info prune --num removed_count "$REMOVED_COUNT"
                log_human "Prune on $REPO: SUCCESS (removed $REMOVED_COUNT snapshot(s))"
            } || {
                emit_event backup "$REPO" warn prune --str message "prune failed"
                log_human "WARNING: Prune on $REPO failed. Backup data is safe; run manually to clean up."
            }
        fi
    else
        emit_event backup "$REPO" error error --str message "backup command failed"
        log_human "ERROR: Backup to $REPO FAILED."
        OVERALL_SUCCESS=false
    fi
done

log_human ""
log_human "=========================================="
if $OVERALL_SUCCESS; then
    log_human "All backups completed successfully."
else
    log_human "One or more backups FAILED. Check log above."
fi
log_human "Finished at $(date)"
log_human "=========================================="

if $OVERALL_SUCCESS; then
    emit_event backup "" info run_end --str status "success"
else
    emit_event backup "" error run_end --str status "failure"
fi

$OVERALL_SUCCESS  # exit 0 if all succeeded, 1 otherwise
