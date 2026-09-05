#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ai-lab-lifecycle.XXXXXX")
TEST_BIN="$TEST_ROOT/bin"
mkdir -p "$TEST_BIN"

cleanup() {
    [ -n "${PREEXISTING_OLLAMA_PID:-}" ] && kill "$PREEXISTING_OLLAMA_PID" 2>/dev/null || true
    [ -n "${UNRELATED_PID:-}" ] && kill "$UNRELATED_PID" 2>/dev/null || true
    [ -n "${OCCUPANT_PID:-}" ] && kill "$OCCUPANT_PID" 2>/dev/null || true
    AI_LAB_RUNTIME_DIR="$TEST_ROOT/runtime" AI_LAB_BACKEND_PORT="$BACKEND_PORT" \
        AI_LAB_FRONTEND_PORT="$FRONTEND_PORT" AI_LAB_OLLAMA_PORT="$OLLAMA_PORT" \
        "$ROOT/stop.sh" >/dev/null 2>&1 || true
    rm -r "$TEST_ROOT"
}
trap cleanup EXIT HUP INT TERM

free_port() {
    "$ROOT/.venv/bin/python" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

BACKEND_PORT=$(free_port)
FRONTEND_PORT=$(free_port)
OLLAMA_PORT=$(free_port)
export AI_LAB_OLLAMA_PORT="$OLLAMA_PORT"

ln -s "$ROOT/tests/fake_ollama.py" "$TEST_BIN/ollama"

run_start() {
    PATH="$TEST_BIN:$PATH" AI_LAB_RUNTIME_DIR="$TEST_ROOT/runtime" \
        AI_LAB_BACKEND_PORT="$BACKEND_PORT" AI_LAB_FRONTEND_PORT="$FRONTEND_PORT" \
        AI_LAB_OLLAMA_PORT="$OLLAMA_PORT" OLLAMA_URL="http://127.0.0.1:$OLLAMA_PORT" \
        AI_LAB_NO_OPEN=1 "$ROOT/start.sh"
}

run_stop() {
    AI_LAB_RUNTIME_DIR="$TEST_ROOT/runtime" AI_LAB_BACKEND_PORT="$BACKEND_PORT" \
        AI_LAB_FRONTEND_PORT="$FRONTEND_PORT" AI_LAB_OLLAMA_PORT="$OLLAMA_PORT" "$ROOT/stop.sh"
}

assert_alive() { kill -0 "$1" 2>/dev/null || { echo "expected PID $1 to be alive" >&2; exit 1; }; }
assert_dead() { ! kill -0 "$1" 2>/dev/null || { echo "expected PID $1 to be stopped" >&2; exit 1; }; }
pid_from() { cut -d '|' -f 1 "$1"; }

echo "1. clean start with AI-Lab-owned Ollama"
run_start >/dev/null
owned_ollama=$(pid_from "$TEST_ROOT/runtime/ollama.pid")
owned_backend=$(pid_from "$TEST_ROOT/runtime/backend.pid")
owned_frontend=$(pid_from "$TEST_ROOT/runtime/frontend-listener.pid")
assert_alive "$owned_ollama"; assert_alive "$owned_backend"; assert_alive "$owned_frontend"

echo "5. repeated start does not duplicate processes"
before=$(cat "$TEST_ROOT/runtime/backend.pid" "$TEST_ROOT/runtime/frontend-listener.pid" "$TEST_ROOT/runtime/ollama.pid")
run_start >/dev/null
after=$(cat "$TEST_ROOT/runtime/backend.pid" "$TEST_ROOT/runtime/frontend-listener.pid" "$TEST_ROOT/runtime/ollama.pid")
[ "$before" = "$after" ]

echo "2. clean stop stops AI-Lab-owned Ollama"
run_stop >/dev/null
assert_dead "$owned_ollama"; assert_dead "$owned_backend"; assert_dead "$owned_frontend"

echo "6. repeated stop is clean"
run_stop >/dev/null

echo "3–4. pre-existing Ollama is reused and survives stop"
PATH="$TEST_BIN:$PATH" ollama serve >"$TEST_ROOT/preexisting.log" 2>&1 &
PREEXISTING_OLLAMA_PID=$!
i=0; until curl -fsS "http://127.0.0.1:$OLLAMA_PORT/api/tags" >/dev/null 2>&1; do i=$((i+1)); [ "$i" -lt 50 ] || exit 1; sleep 0.1; done
run_start >/dev/null
[ ! -f "$TEST_ROOT/runtime/ollama.pid" ]
run_stop >/dev/null
assert_alive "$PREEXISTING_OLLAMA_PID"

echo "7. stale PID files are removed without signaling"
mkdir -p "$TEST_ROOT/runtime"
printf '999999|Mon Jan  1 00:00:00 2000|uvicorn\n' > "$TEST_ROOT/runtime/backend.pid"
run_start >/dev/null
[ "$(pid_from "$TEST_ROOT/runtime/backend.pid")" != 999999 ]
run_stop >/dev/null

echo "8. unrelated processes are not killed"
sleep 120 & UNRELATED_PID=$!
started=$(ps -p "$UNRELATED_PID" -o lstart= | sed 's/^ *//;s/ *$//')
printf '%s|%s|definitely-not-this-command\n' "$UNRELATED_PID" "$started" > "$TEST_ROOT/runtime/backend.pid"
run_stop >/dev/null
assert_alive "$UNRELATED_PID"

# A wrong service on the backend port must fail without being killed.
"$ROOT/.venv/bin/python" -m http.server "$BACKEND_PORT" --bind 127.0.0.1 >"$TEST_ROOT/occupant.log" 2>&1 &
OCCUPANT_PID=$!
i=0; until curl -fsS "http://127.0.0.1:$BACKEND_PORT" >/dev/null 2>&1; do i=$((i+1)); [ "$i" -lt 50 ] || exit 1; sleep 0.1; done
if run_start >/dev/null 2>&1; then
    echo "start unexpectedly accepted an unrelated backend port occupant" >&2
    exit 1
fi
assert_alive "$OCCUPANT_PID"

echo "Lifecycle checks passed."
