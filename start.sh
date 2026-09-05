#!/bin/sh
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUNTIME_DIR=${AI_LAB_RUNTIME_DIR:-"$ROOT/.runtime"}
BACKEND_PORT=${AI_LAB_BACKEND_PORT:-8000}
FRONTEND_PORT=${AI_LAB_FRONTEND_PORT:-5173}
OLLAMA_PORT=${AI_LAB_OLLAMA_PORT:-11434}
OLLAMA_URL=${OLLAMA_URL:-"http://127.0.0.1:$OLLAMA_PORT"}
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
FRONTEND_LISTENER_FILE="$RUNTIME_DIR/frontend-listener.pid"
OLLAMA_PID_FILE="$RUNTIME_DIR/ollama.pid"
LOCK_DIR="$RUNTIME_DIR/start.lock"

# shellcheck source=scripts/process_helpers.sh
. "$ROOT/scripts/process_helpers.sh"

started_backend=""
started_frontend=""
started_ollama=""

release_lock() {
    rmdir "$LOCK_DIR" 2>/dev/null || true
}

clean_failed_start() {
    release_lock
    if [ -n "$started_frontend" ]; then
        failed_listener=$(port_pid "$FRONTEND_PORT")
        if [ -n "$failed_listener" ] && is_descendant_of "$failed_listener" "$started_frontend"; then
            terminate_pid "$failed_listener"
        fi
    fi
    [ -n "$started_frontend" ] && terminate_pid "$started_frontend"
    [ -n "$started_backend" ] && terminate_pid "$started_backend"
    [ -n "$started_ollama" ] && terminate_pid "$started_ollama"
    [ -n "$started_frontend" ] && rm -f "$FRONTEND_PID_FILE" "$FRONTEND_LISTENER_FILE"
    [ -n "$started_backend" ] && rm -f "$BACKEND_PID_FILE"
    [ -n "$started_ollama" ] && rm -f "$OLLAMA_PID_FILE"
}

fail() {
    printf 'AI Lab: %s\n' "$1" >&2
    clean_failed_start
    exit 1
}

mkdir -p "$RUNTIME_DIR" || { printf 'AI Lab: cannot create %s\n' "$RUNTIME_DIR" >&2; exit 1; }
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    printf 'AI Lab: another start is already in progress. If it is not, remove %s\n' "$LOCK_DIR" >&2
    exit 1
fi
trap 'release_lock' EXIT
trap 'release_lock; exit 130' HUP INT TERM

# Remove state whose PID has exited or been reused. Never signal it here.
for stale_file in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE" "$FRONTEND_LISTENER_FILE" "$OLLAMA_PID_FILE"; do
    if [ -f "$stale_file" ] && ! pid_matches_file "$stale_file"; then
        rm -f "$stale_file"
    fi
done

[ -x "$ROOT/.venv/bin/python" ] || fail ".venv is missing. Run: /opt/homebrew/bin/python3.12 -m venv .venv"
[ -x "$ROOT/.venv/bin/uvicorn" ] || fail "backend dependencies are missing. Run: .venv/bin/pip install -r backend/requirements.lock.txt"
"$ROOT/.venv/bin/python" -c 'import platform, sys; raise SystemExit(0 if platform.machine() == "arm64" and sys.version_info[:2] == (3, 12) else 1)' \
    || fail ".venv must use arm64 Python 3.12. Recreate it with /opt/homebrew/bin/python3.12 -m venv .venv"
command -v curl >/dev/null 2>&1 || fail "curl is required but was not found."
command -v lsof >/dev/null 2>&1 || fail "lsof is required but was not found."
command -v npm >/dev/null 2>&1 || fail "npm is missing. Install Node.js, then run: npm --prefix frontend ci"
[ -x "$ROOT/frontend/node_modules/.bin/vite" ] || fail "frontend dependencies are missing. Run: npm --prefix frontend ci"
command -v ollama >/dev/null 2>&1 || fail "Ollama is missing. Install it from https://ollama.com/download"

printf 'AI Lab: checking Ollama…\n'
if curl -fsS --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    if pid_matches_file "$OLLAMA_PID_FILE"; then
        printf '  Ollama already running under AI Lab ownership.\n'
    else
        printf '  Ollama already running; leaving it under its current owner.\n'
        rm -f "$OLLAMA_PID_FILE"
    fi
elif [ -n "$(port_pid "$OLLAMA_PORT")" ]; then
    fail "port $OLLAMA_PORT is occupied by a service that is not responding as Ollama."
else
    ollama_marker="ollama serve"
    OLLAMA_HOST="127.0.0.1:$OLLAMA_PORT" nohup ollama serve >>"$RUNTIME_DIR/ollama.log" 2>&1 &
    started_ollama=$!
    write_pid_file "$OLLAMA_PID_FILE" "$started_ollama" "$ollama_marker" \
        || fail "could not record Ollama ownership."
    wait_for_url "$OLLAMA_URL/api/tags" "Ollama" "$started_ollama" \
        || fail "Ollama did not start. See $RUNTIME_DIR/ollama.log"
    printf '  Ollama started by AI Lab (PID %s).\n' "$started_ollama"
fi

if ! "$ROOT/.venv/bin/python" - "$OLLAMA_URL" <<'PY'
import json, sys, urllib.request
url = sys.argv[1] + "/api/tags"
with urllib.request.urlopen(url, timeout=5) as response:
    names = {item["name"] for item in json.load(response).get("models", [])}
required = {"qwen3.5:9b", "nomic-embed-text:v1.5"}
missing = sorted(required - names)
if missing:
    print("Missing Ollama model(s): " + ", ".join(missing), file=sys.stderr)
    print("Install with: " + " && ".join(f"ollama pull {name}" for name in missing), file=sys.stderr)
    raise SystemExit(1)
PY
then
    fail "required local models are unavailable."
fi
printf '  Required models available.\n'

if curl -fsS --max-time 2 "$BACKEND_URL/api/health" 2>/dev/null | grep -q '"model"'; then
    if pid_matches_file "$BACKEND_PID_FILE"; then
        printf '  Backend already running under AI Lab ownership.\n'
    else
        printf '  Backend already running; reusing it.\n'
        rm -f "$BACKEND_PID_FILE"
    fi
elif [ -n "$(port_pid "$BACKEND_PORT")" ]; then
    fail "port $BACKEND_PORT is already occupied by another service."
else
    backend_marker="uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $BACKEND_PORT"
    (
        cd "$ROOT" || exit 1
        exec .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT"
    ) >>"$RUNTIME_DIR/backend.log" 2>&1 &
    started_backend=$!
    write_pid_file "$BACKEND_PID_FILE" "$started_backend" "$backend_marker" \
        || fail "could not record backend ownership."
    wait_for_url "$BACKEND_URL/api/health" "backend" "$started_backend" \
        || fail "backend did not start. See $RUNTIME_DIR/backend.log"
    printf '  Backend started on %s.\n' "$BACKEND_URL"
fi

if curl -fsS --max-time 2 "$FRONTEND_URL" 2>/dev/null | grep -q 'AI Lab — AI Engineering Tutor'; then
    if pid_matches_file "$FRONTEND_PID_FILE" && pid_matches_file "$FRONTEND_LISTENER_FILE"; then
        printf '  Frontend already running under AI Lab ownership.\n'
    else
        printf '  Frontend already running; reusing it.\n'
        rm -f "$FRONTEND_PID_FILE" "$FRONTEND_LISTENER_FILE"
    fi
elif [ -n "$(port_pid "$FRONTEND_PORT")" ]; then
    fail "port $FRONTEND_PORT is already occupied by another service."
else
    # npm shortens its macOS process title to "npm run dev ..." after launch.
    frontend_marker="npm"
    (
        cd "$ROOT" || exit 1
        if [ "$FRONTEND_PORT" = 5173 ]; then
            exec npm --prefix frontend run dev
        else
            exec npm --prefix frontend run dev -- --port "$FRONTEND_PORT"
        fi
    ) >>"$RUNTIME_DIR/frontend.log" 2>&1 &
    started_frontend=$!
    write_pid_file "$FRONTEND_PID_FILE" "$started_frontend" "$frontend_marker" \
        || fail "could not record frontend ownership."
    wait_for_url "$FRONTEND_URL" "frontend" "$started_frontend" \
        || fail "frontend did not start. See $RUNTIME_DIR/frontend.log"
    frontend_listener=$(port_pid "$FRONTEND_PORT")
    [ -n "$frontend_listener" ] || fail "frontend is reachable but its listener PID could not be identified."
    write_pid_file "$FRONTEND_LISTENER_FILE" "$frontend_listener" "vite" \
        || fail "could not record the frontend listener."
    printf '  Frontend started on %s.\n' "$FRONTEND_URL"
fi

release_lock
trap - EXIT HUP INT TERM
if [ "${AI_LAB_NO_OPEN:-0}" != "1" ]; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || printf '  Could not open a browser; visit %s manually.\n' "$FRONTEND_URL"
fi
printf 'AI Lab is ready: %s\n' "$FRONTEND_URL"
