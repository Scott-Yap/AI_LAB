#!/bin/sh
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unload_models=0
case "${1:-}" in
    "") ;;
    --unload-models) unload_models=1 ;;
    *) printf 'Usage: ./stop.sh [--unload-models]\n' >&2; exit 2 ;;
esac
RUNTIME_DIR=${AI_LAB_RUNTIME_DIR:-"$ROOT/.runtime"}
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
FRONTEND_LISTENER_FILE="$RUNTIME_DIR/frontend-listener.pid"
OLLAMA_PID_FILE="$RUNTIME_DIR/ollama.pid"
OLLAMA_URL=${OLLAMA_URL:-"http://127.0.0.1:${AI_LAB_OLLAMA_PORT:-11434}"}

# shellcheck source=scripts/process_helpers.sh
. "$ROOT/scripts/process_helpers.sh"

stopped=""
already=""
skipped=""

stop_owned() {
    stop_name=$1
    stop_file=$2
    stop_port=${3:-}
    if [ ! -f "$stop_file" ]; then
        already="${already}${already:+, }$stop_name"
        return
    fi
    stop_record=$(read_owned_pid "$stop_file" 2>/dev/null || true)
    if [ -z "$stop_record" ] || ! pid_matches_file "$stop_file"; then
        skipped="${skipped}${skipped:+, }$stop_name (stale ownership record)"
        rm -f "$stop_file"
        return
    fi
    stop_pid=${stop_record%%|*}
    if [ -n "$stop_port" ] && ! pid_listens_on "$stop_pid" "$stop_port"; then
        skipped="${skipped}${skipped:+, }$stop_name (recorded PID is not its port listener)"
        rm -f "$stop_file"
        return
    fi
    terminate_pid "$stop_pid"
    rm -f "$stop_file"
    stopped="${stopped}${stopped:+, }$stop_name"
}

frontend_parent_owned=0
pid_matches_file "$FRONTEND_PID_FILE" && frontend_parent_owned=1
# Stop npm first, then validate and stop Vite if npm did not propagate the signal.
stop_owned "frontend" "$FRONTEND_PID_FILE"
if [ "$frontend_parent_owned" -eq 1 ] && ! pid_matches_file "$FRONTEND_LISTENER_FILE"; then
    # npm normally terminates Vite itself; its now-dead listener record is expected.
    rm -f "$FRONTEND_LISTENER_FILE"
else
    stop_owned "frontend listener" "$FRONTEND_LISTENER_FILE" "${AI_LAB_FRONTEND_PORT:-5173}"
fi
stop_owned "backend" "$BACKEND_PID_FILE" "${AI_LAB_BACKEND_PORT:-8000}"
stop_owned "Ollama" "$OLLAMA_PID_FILE" "${AI_LAB_OLLAMA_PORT:-11434}"
rmdir "$RUNTIME_DIR/start.lock" 2>/dev/null || true

[ -n "$stopped" ] && printf 'AI Lab stopped: %s.\n' "$stopped"
[ -n "$skipped" ] && printf 'AI Lab left untouched: %s.\n' "$skipped"
[ -n "$already" ] && printf 'Already stopped or externally managed: %s.\n' "$already"
if [ -z "$stopped$skipped" ]; then
    printf 'AI Lab had no owned processes to stop.\n'
fi

if [ "$unload_models" -eq 1 ]; then
    if command -v ollama >/dev/null 2>&1 && curl -fsS --max-time 2 "${OLLAMA_URL:-http://127.0.0.1:${AI_LAB_OLLAMA_PORT:-11434}}/api/tags" >/dev/null 2>&1; then
        ollama stop qwen3.5:9b >/dev/null 2>&1 || true
        ollama stop nomic-embed-text:v1.5 >/dev/null 2>&1 || true
        printf 'Requested unload: qwen3.5:9b, nomic-embed-text:v1.5. Ollama daemon was left running.\n'
    else
        printf 'Could not unload models: Ollama is not reachable.\n' >&2
        exit 1
    fi
else
    if curl -fsS --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        printf 'Ollama model memory is left warm while its daemon is externally managed; use ./stop.sh --unload-models to evict the Tutor models.\n'
    fi
fi
