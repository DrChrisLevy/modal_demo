#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mode="${1:-check}"
if [ "$#" -gt 0 ]; then shift; fi
common=(--profile "${DEMO_MODAL_PROFILE:-drchrislevy}" --workspace "${DEMO_MODAL_WORKSPACE:-drchrislevy}"
        --environment main --repo "${DEMO_REPO:-DrChrisLevy/modal_demo}" --directory example)
checks='docker compose exec -T web uv run --frozen pytest -q && docker compose exec -T web uv run --frozen ruff check .'
case "$mode" in
  check) exec uv run --frozen python -m runner "${common[@]}" --command "$checks" "$@" ;;
  serve) exec uv run --frozen python -m runner "${common[@]}" --command "$checks" --hold "$@" ;;
  agent) exec uv run --frozen python -m runner "${common[@]}" --prompt demo/agent-task.md \
    --branch "demo/task-filters-$(date -u +%Y%m%d-%H%M%S)" --command "$checks" "$@" ;;
  *) echo 'Usage: ./demo.sh {check|serve|agent} [runner options]' >&2; exit 2 ;;
esac
