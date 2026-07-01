#!/bin/bash
# =============================================================================
# query.sh — Search restic snapshots by date, file path, or file history
# =============================================================================
# Usage:
#   bash query.sh --since 2026-01-01 --until 2026-06-01     — snapshots in a date range
#   bash query.sh --find ~/Documents/taxes/2025.pdf         — which snapshot(s) contain this file
#   bash query.sh --find '*.pdf'                            — which snapshot(s) contain files matching this glob
#   bash query.sh --versions ~/Documents/notes.md           — every version of this file across snapshots
#   bash query.sh --repo dropbox --versions '*.pdf'         — restrict to one repo
#   bash query.sh --find notes.md --json                    — raw JSON output
#
# Exactly one of --since/--until, --find, or --versions must be given.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

REPO_FILTER=""
SINCE=""
UNTIL=""
FIND_TARGET=""
VERSIONS_TARGET=""
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_FILTER="$2"; shift 2 ;;
        --since)    SINCE="$2"; shift 2 ;;
        --until)    UNTIL="$2"; shift 2 ;;
        --find)     FIND_TARGET="$2"; shift 2 ;;
        --versions) VERSIONS_TARGET="$2"; shift 2 ;;
        --json)     JSON_OUTPUT=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

MODE_COUNT=0
[[ -n "$SINCE$UNTIL" ]] && MODE_COUNT=$((MODE_COUNT+1))
[[ -n "$FIND_TARGET" ]] && MODE_COUNT=$((MODE_COUNT+1))
[[ -n "$VERSIONS_TARGET" ]] && MODE_COUNT=$((MODE_COUNT+1))

if [[ "$MODE_COUNT" -ne 1 ]]; then
    echo "ERROR: specify exactly one of --since/--until, --find, or --versions." >&2
    exit 1
fi

init_logging query
emit_event query "" info run_start

check_dependencies restic rclone security jq

get_restic_password

REPOS_TO_QUERY=()
if [[ -n "$REPO_FILTER" ]]; then
    REPOS_TO_QUERY+=("$(resolve_repo "$REPO_FILTER")")
else
    if [[ ${#REPOS[@]} -eq 0 ]]; then
        echo "ERROR: REPOS is empty in backup.conf. Configure at least one repo." >&2
        emit_event query "" error run_end --str status "failure"
        exit 1
    fi
    REPOS_TO_QUERY=("${REPOS[@]}")
fi

for REPO in "${REPOS_TO_QUERY[@]}"; do
    if [[ -n "$SINCE$UNTIL" ]]; then
        SNAPSHOTS_JSON=$(restic -r "$REPO" snapshots --json)
        FILTER='.[]'
        [[ -n "$SINCE" ]] && FILTER="$FILTER | select(.time >= \"$SINCE\")"
        [[ -n "$UNTIL" ]] && FILTER="$FILTER | select(.time <= \"$UNTIL\")"
        RESULT=$(jq -c "[$FILTER]" <<<"$SNAPSHOTS_JSON")

        emit_event query "$REPO" info summary --str mode "date_range" --num match_count "$(jq 'length' <<<"$RESULT")"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        else
            echo ""
            echo "--- $REPO ---"
            jq -r '.[] | "\(.short_id)  \(.time)  \(.paths | join(", "))"' <<<"$RESULT"
        fi

    elif [[ -n "$FIND_TARGET" ]]; then
        if ! RESULT=$(restic -r "$REPO" find --json "$FIND_TARGET" 2>&1); then
            ERR_MSG=$(jq -r '.message // "unknown error"' <<<"$RESULT" 2>/dev/null || echo "$RESULT")
            emit_event query "$REPO" error error --str message "$ERR_MSG"
            echo "ERROR: query on $REPO failed: $ERR_MSG" >&2
            RESULT="[]"
        fi
        MATCH_COUNT=$(jq '[.[].matches[]] | length' <<<"$RESULT")

        emit_event query "$REPO" info summary --str mode "find" --str target "$FIND_TARGET" --num match_count "$MATCH_COUNT"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        elif [[ "$MATCH_COUNT" -gt 0 ]]; then
            echo ""
            echo "--- $REPO ---"
            jq -r '.[] | .snapshot as $s | .matches[] | "\($s)  \(.path)  \(.size) bytes  \(.mtime)"' <<<"$RESULT"
        fi

    elif [[ -n "$VERSIONS_TARGET" ]]; then
        if ! RESULT=$(restic -r "$REPO" find --json "$VERSIONS_TARGET" --reverse 2>&1); then
            ERR_MSG=$(jq -r '.message // "unknown error"' <<<"$RESULT" 2>/dev/null || echo "$RESULT")
            emit_event query "$REPO" error error --str message "$ERR_MSG"
            echo "ERROR: query on $REPO failed: $ERR_MSG" >&2
            RESULT="[]"
        fi
        MATCH_COUNT=$(jq '[.[].matches[]] | length' <<<"$RESULT")

        emit_event query "$REPO" info summary --str mode "versions" --str target "$VERSIONS_TARGET" --num version_count "$MATCH_COUNT"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        elif [[ "$MATCH_COUNT" -gt 0 ]]; then
            echo ""
            echo "--- $REPO: versions of $VERSIONS_TARGET (oldest first) ---"
            jq -r '.[] | .snapshot as $s | .matches[] | "\($s)  \(.mtime)  \(.size) bytes  \(.path)"' <<<"$RESULT"
        fi
    fi
done

emit_event query "" info run_end --str status "success"
