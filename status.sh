#!/bin/bash
# =============================================================================
# status.sh — Check snapshot status across all configured repos
# =============================================================================
# Usage:
#   bash status.sh                       — show latest snapshot per repo
#   bash status.sh --all                 — show all snapshots per repo
#   bash status.sh --check               — run restic check (integrity verification)
#   bash status.sh --include ~/Documents — only snapshots that include this exact source path
#   bash status.sh --pattern 'Doc*'      — only snapshots with a source path matching this pattern
#   bash status.sh --glob 'Documents'    — only snapshots whose source path's basename matches
#   bash status.sh --exclude Music       — drop snapshots whose source path matches
#
# Targeting flags filter *which snapshots are shown*, by matching against a
# snapshot's top-level configured source paths — they do not search file
# contents inside a snapshot. For file-level search, use query.sh.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

MODE="--latest"
INCLUDE_PATHS=()
PATTERN_ARGS=()
GLOB_ARGS=()
EXCLUDE_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)     MODE="--all"; shift ;;
        --check)   MODE="--check"; shift ;;
        --latest)  MODE="--latest"; shift ;;
        --include) INCLUDE_PATHS+=("$2"); shift 2 ;;
        --pattern) PATTERN_ARGS+=("$2"); shift 2 ;;
        --glob)    GLOB_ARGS+=("$2"); shift 2 ;;
        --exclude) EXCLUDE_ARGS+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging status
emit_event status "" info run_start

check_dependencies restic rclone security jq

get_restic_password

if [[ ${#REPOS[@]} -eq 0 ]]; then
    log_human "ERROR: REPOS is empty in backup.conf. Configure at least one repo."
    emit_event status "" error run_end --str status "failure"
    exit 1
fi

# Returns 0 (keep) or 1 (drop) for a snapshot given its paths array (JSON).
snapshot_matches_filters() {
    local paths_json="$1"
    local pattern p keep

    if [[ ${#PATTERN_ARGS[@]} -gt 0 || ${#GLOB_ARGS[@]} -gt 0 ]]; then
        keep=false
        if [[ ${#PATTERN_ARGS[@]} -gt 0 ]]; then
            for pattern in "${PATTERN_ARGS[@]}"; do
                while IFS= read -r p; do
                    [[ "$p" == *"$pattern"* ]] && keep=true
                done < <(jq -r '.[]' <<<"$paths_json")
            done
        fi
        if [[ ${#GLOB_ARGS[@]} -gt 0 ]]; then
            for pattern in "${GLOB_ARGS[@]}"; do
                while IFS= read -r p; do
                    [[ "$(basename "$p")" == $pattern ]] && keep=true
                done < <(jq -r '.[]' <<<"$paths_json")
            done
        fi
        $keep || return 1
    fi

    if [[ ${#EXCLUDE_ARGS[@]} -gt 0 ]]; then
        for pattern in "${EXCLUDE_ARGS[@]}"; do
            while IFS= read -r p; do
                if [[ "$p" == *"$pattern"* || "$(basename "$p")" == $pattern ]]; then
                    return 1
                fi
            done < <(jq -r '.[]' <<<"$paths_json")
        done
    fi

    return 0
}

for REPO in "${REPOS[@]}"; do
    echo ""
    echo "════════════════════════════════════════"
    echo "  Repo: $REPO"
    echo "════════════════════════════════════════"

    RESTIC_PATH_FLAGS=()
    if [[ ${#INCLUDE_PATHS[@]} -gt 0 ]]; then
        for p in "${INCLUDE_PATHS[@]}"; do
            RESTIC_PATH_FLAGS+=(--path "$p")
        done
    fi

    case "$MODE" in
        --check)
            log_human "Running integrity check on $REPO (this may take a while)..."
            if restic -r "$REPO" check --json 2>&1 | tee -a "$LOG_HUMAN"; then
                emit_event status "$REPO" info summary --str check "ok"
            else
                emit_event status "$REPO" error summary --str check "failed"
            fi
            ;;
        --all|--latest)
            SNAP_ARGS=(snapshots --json)
            if [[ ${#RESTIC_PATH_FLAGS[@]} -gt 0 ]]; then
                SNAP_ARGS+=("${RESTIC_PATH_FLAGS[@]}")
            fi
            [[ "$MODE" == "--latest" ]] && SNAP_ARGS+=(--latest 1)

            SNAPSHOTS_JSON=$(restic -r "$REPO" "${SNAP_ARGS[@]}")
            COUNT=$(jq 'length' <<<"$SNAPSHOTS_JSON")

            idx=0
            while [[ $idx -lt $COUNT ]]; do
                SNAP=$(jq -c ".[$idx]" <<<"$SNAPSHOTS_JSON")
                PATHS_JSON=$(jq -c '.paths' <<<"$SNAP")
                if snapshot_matches_filters "$PATHS_JSON"; then
                    SHORT_ID=$(jq -r '.short_id' <<<"$SNAP")
                    TIME=$(jq -r '.time' <<<"$SNAP")
                    PATHS=$(jq -r '.paths | join(", ")' <<<"$SNAP")
                    echo "  $SHORT_ID  $TIME  $PATHS"
                    emit_event status "$REPO" info summary --str snapshot_id "$SHORT_ID" --str time "$TIME"
                fi
                idx=$((idx+1))
            done
            ;;
    esac
done

emit_event status "" info run_end --str status "success"
