#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

default_python=python3
if command -v python3.12 >/dev/null 2>&1; then
  default_python=python3.12
fi
python_bin="${PYTHON_BIN:-$default_python}"
venv_dir="${SHABSANJ_VENV:-.venv}"
if ! "$venv_dir/bin/python" -m pip --version >/dev/null 2>&1; then
  "$python_bin" -m venv "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -q -r backend/requirements.txt
case "${1:-serve}" in
  refresh)
    shift
    exec "$venv_dir/bin/python" -m backend.crawl "$@"
    ;;
  refresh-tours)
    shift
    exec "$venv_dir/bin/python" -m backend.crawl_tours "$@"
    ;;
  refresh-tickets)
    shift
    exec "$venv_dir/bin/python" -m backend.crawl_tickets "$@"
    ;;
  schedule-tickets)
    shift
    exec "$venv_dir/bin/python" -m backend.ticket_schedule "$@"
    ;;
  serve)
    if [[ ! -f frontend/node_modules/.package-lock.json || frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]]; then
      npm --prefix frontend ci --no-audit --no-fund
    fi
    npm --prefix frontend run build
    if [[ -z "${OPENROUTER_API_KEY:-}" && -n "${OPENROUTER_API_KEY_FILE:-}" ]]; then
      if [[ ! -r "$OPENROUTER_API_KEY_FILE" ]]; then
        echo "OPENROUTER_API_KEY_FILE is not readable." >&2
        exit 2
      fi
      IFS= read -r OPENROUTER_API_KEY < "$OPENROUTER_API_KEY_FILE" || [[ -n "$OPENROUTER_API_KEY" ]]
      export OPENROUTER_API_KEY
    fi
    exec "$venv_dir/bin/python" -m uvicorn backend.app:app --host 127.0.0.1 --port "${PORT:-8765}" --no-access-log
    ;;
  *)
    echo "Usage: ./run.sh [serve|refresh|refresh-tours|refresh-tickets|schedule-tickets]" >&2
    exit 2
    ;;
esac
