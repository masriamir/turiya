#!/bin/bash
# =============================================================================
# lib/common.sh — shared config loading, Keychain, and dependency helpers
# =============================================================================
# Sourced by backup.sh, restore.sh, status.sh, and query.sh. Not meant to be
# executed directly — it has no effect on its own.
# =============================================================================

load_config() {
    local script_dir="$1"
    CONFIG_FILE="${TURIYA_CONFIG:-$script_dir/backup.conf}"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "ERROR: config file not found at $CONFIG_FILE" >&2
        exit 1
    fi

    # shellcheck source=backup.conf
    source "$CONFIG_FILE"
}

check_dependencies() {
    local cmd
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            echo "ERROR: '$cmd' not found in PATH. Is Homebrew on your PATH?" >&2
            exit 1
        fi
    done
}

get_restic_password() {
    if [[ -n "${RESTIC_PASSWORD:-}" ]]; then
        export RESTIC_PASSWORD
        return 0
    fi

    local password
    password=$(security find-generic-password \
        -a "$KEYCHAIN_ACCOUNT" \
        -s "$KEYCHAIN_SERVICE" \
        -w 2>/dev/null) || {
        echo "ERROR: Could not retrieve password from Keychain." >&2
        echo "       Run install.sh to set it up, or check account/service names in backup.conf." >&2
        exit 1
    }
    RESTIC_PASSWORD="$password"
    export RESTIC_PASSWORD
}

resolve_repo() {
    local filter="$1"
    local repo

    if [[ ${#REPOS[@]} -eq 0 ]]; then
        echo "ERROR: REPOS is empty in backup.conf. Configure at least one repo." >&2
        exit 1
    fi

    if [[ -n "$filter" ]]; then
        for repo in "${REPOS[@]}"; do
            if [[ "$repo" == *"$filter"* ]]; then
                echo "$repo"
                return 0
            fi
        done
        echo "ERROR: No repo matching '$filter' found in backup.conf." >&2
        exit 1
    fi
    echo "${REPOS[0]}"
}
