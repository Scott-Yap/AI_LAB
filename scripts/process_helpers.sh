#!/bin/sh
# Shared lifecycle helpers. This file is sourced by start.sh and stop.sh.

process_alive() {
    kill -0 "$1" 2>/dev/null
}

process_command() {
    ps -p "$1" -o command= 2>/dev/null || true
}

process_started_at() {
    ps -p "$1" -o lstart= 2>/dev/null | sed 's/^ *//;s/ *$//'
}

pid_listens_on() {
    listener_pid=$(lsof -nP -iTCP:"$2" -sTCP:LISTEN -t 2>/dev/null | head -n 1)
    [ "$listener_pid" = "$1" ]
}

is_descendant_of() {
    child_pid=$1
    ancestor_pid=$2
    while [ "$child_pid" -gt 1 ] 2>/dev/null; do
        [ "$child_pid" = "$ancestor_pid" ] && return 0
        child_pid=$(ps -p "$child_pid" -o ppid= 2>/dev/null | tr -d ' ') || return 1
        [ -n "$child_pid" ] || return 1
    done
    return 1
}

wait_for_url() {
    wait_url=$1
    wait_label=$2
    wait_pid=${3:-}
    wait_attempt=0
    while [ "$wait_attempt" -lt "${AI_LAB_WAIT_ATTEMPTS:-60}" ]; do
        if curl -fsS --max-time 2 "$wait_url" >/dev/null 2>&1; then
            return 0
        fi
        if [ -n "$wait_pid" ] && ! process_alive "$wait_pid"; then
            return 1
        fi
        wait_attempt=$((wait_attempt + 1))
        sleep "${AI_LAB_WAIT_INTERVAL:-0.5}"
    done
    printf 'Timed out waiting for %s.\n' "$wait_label" >&2
    return 1
}

read_owned_pid() {
    owned_file=$1
    [ -f "$owned_file" ] || return 1
    IFS='|' read -r owned_pid owned_started owned_marker < "$owned_file" || return 1
    case "$owned_pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -n "$owned_started" ] && [ -n "$owned_marker" ] || return 1
    printf '%s|%s|%s\n' "$owned_pid" "$owned_started" "$owned_marker"
}

pid_matches_file() {
    match_file=$1
    match_record=$(read_owned_pid "$match_file") || return 1
    match_pid=${match_record%%|*}
    match_rest=${match_record#*|}
    match_started=${match_rest%%|*}
    match_marker=${match_rest#*|}
    process_alive "$match_pid" || return 1
    [ "$(process_started_at "$match_pid")" = "$match_started" ] || return 1
    case "$(process_command "$match_pid")" in
        *"$match_marker"*) return 0 ;;
        *) return 1 ;;
    esac
}

write_pid_file() {
    pid_tmp="$1.tmp.$$"
    pid_started=$(process_started_at "$2")
    [ -n "$pid_started" ] || return 1
    printf '%s|%s|%s\n' "$2" "$pid_started" "$3" > "$pid_tmp"
    mv "$pid_tmp" "$1"
}

port_pid() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1
}

terminate_pid() {
    terminate_pid_value=$1
    terminate_wait=0
    kill -TERM "$terminate_pid_value" 2>/dev/null || return 0
    while process_alive "$terminate_pid_value" && [ "$terminate_wait" -lt 30 ]; do
        sleep 0.1
        terminate_wait=$((terminate_wait + 1))
    done
    if process_alive "$terminate_pid_value"; then
        kill -KILL "$terminate_pid_value" 2>/dev/null || true
    fi
}
