#!/bin/bash
# =============================================================================
# lib/logging.sh — structured JSONL + human-readable logging
# =============================================================================
# Sourced by backup.sh, restore.sh, status.sh, and query.sh, after
# lib/common.sh and load_config. Requires LOG_DIR, LOG_MAX_BYTES, and
# LOG_JSON_PER_FILE (from backup.conf) plus jq on PATH.
# =============================================================================

rotate_log_file() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local size
        size=$(stat -f%z "$file" 2>/dev/null || echo 0)
        if (( size > LOG_MAX_BYTES )); then
            mv "$file" "${file}.$(date +%Y%m%d%H%M%S).bak"
        fi
    fi
}

init_logging() {
    local op="$1"
    mkdir -p "$LOG_DIR"
    LOG_HUMAN="$LOG_DIR/${op}.log"
    LOG_JSONL="$LOG_DIR/${op}.jsonl"
    LOG_COMBINED_JSONL="$LOG_DIR/ops.jsonl"
    rotate_log_file "$LOG_HUMAN"
    rotate_log_file "$LOG_JSONL"
    rotate_log_file "$LOG_COMBINED_JSONL"
}

log_human() {
    local msg
    msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_HUMAN"
}

emit_event() {
    # Usage: emit_event <op> <repo> <level> <event> [--str key value]... [--num key value]...
    local op="$1" repo="$2" level="$3" event="$4"
    shift 4
    local jq_args=(-nc --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
                       --arg op "$op" --arg repo "$repo" \
                       --arg level "$level" --arg event "$event")
    # $ts/$op/$repo/$level/$event below are jq --arg names, not bash variables; single quotes are intentional.
    # shellcheck disable=SC2016
    local filter='{ts:$ts, op:$op, repo:(if $repo == "" then null else $repo end), level:$level, event:$event}'
    local n=0 kind key value argname
    while [[ $# -gt 0 ]]; do
        kind="$1"; key="$2"; value="$3"
        shift 3
        n=$((n+1))
        argname="f${n}"
        if [[ "$kind" == "--num" ]]; then
            jq_args+=(--argjson "$argname" "$value")
        else
            jq_args+=(--arg "$argname" "$value")
        fi
        filter="${filter} + {\"${key}\": \$${argname}}"
    done
    local line
    line=$(jq "${jq_args[@]}" "$filter")
    echo "$line" >> "$LOG_JSONL"
    echo "$line" >> "$LOG_COMBINED_JSONL"
}

emit_summary() {
    local op="$1" repo="$2" raw_json="$3"
    local out
    out=$(jq -nc --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" --arg op "$op" --arg repo "$repo" \
        --argjson restic "$raw_json" \
        '{ts:$ts, op:$op, repo:$repo, level:"info", event:"summary"} + $restic')
    echo "$out" >> "$LOG_JSONL"
    echo "$out" >> "$LOG_COMBINED_JSONL"
}

process_restic_json_stream() {
    # Usage: restic ... --json --verbose=2 | process_restic_json_stream <op> <repo>
    local op="$1" repo="$2"
    local line msg_type
    while IFS= read -r line; do
        msg_type=$(jq -r '.message_type // empty' <<<"$line" 2>/dev/null) || continue
        case "$msg_type" in
            verbose_status)
                local action item size
                action=$(jq -r '.action // "unknown"' <<<"$line")
                [[ "$action" == "scan_finished" ]] && continue
                item=$(jq -r '.item // .path // ""' <<<"$line")
                size=$(jq -r '.data_size // .size // 0' <<<"$line")
                if [[ "${LOG_JSON_PER_FILE:-true}" == "true" ]]; then
                    emit_event "$op" "$repo" info file --str action "$action" --str path "$item" --num size "$size"
                fi
                log_human "[$op] $repo: $action $item"
                ;;
            summary)
                local raw
                raw=$(jq -c '.' <<<"$line")
                emit_summary "$op" "$repo" "$raw"
                log_human "[$op] $repo: summary $(jq -r 'to_entries | map("\(.key)=\(.value)") | join(" ")' <<<"$raw")"
                ;;
            error|exit_error)
                local err_msg
                err_msg=$(jq -r '.message // (.error.message // "unknown error")' <<<"$line")
                emit_event "$op" "$repo" error error --str message "$err_msg"
                log_human "[$op] $repo: ERROR $err_msg"
                ;;
            *)
                :
                ;;
        esac
    done
}
