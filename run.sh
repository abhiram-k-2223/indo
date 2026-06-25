#!/usr/bin/env bash
# Indo — one-command runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-once}"
COMMODITY="${2:-}"

run_agent() {
    local args=()
    [[ -n "$COMMODITY" ]] && args+=(--commodity "$COMMODITY")
    case "$MODE" in
        once)     uv run python agent.py "${args[@]}" ;;
        telegram) uv run python agent.py --telegram "${args[@]}" ;;
        monitor)  uv run python agent.py --monitor 60 "${args[@]}" ;;
        schedule) uv run python agent.py --schedule 8 "${args[@]}" ;;
        paper)    uv run python agent.py --paper "${args[@]}" ;;
        paper-monitor) uv run python agent.py --monitor 60 --paper ;;
        paper-schedule) uv run python agent.py --schedule 8 --paper ;;
        backtest) uv run python backtester.py ${COMMODITY:+-c "$COMMODITY"} ;;
        bt-all)   uv run python backtester.py ;;
        bt-journal) uv run python backtester.py ${COMMODITY:+-c "$COMMODITY"} --journal ;;
        bt-plot)  uv run python backtester.py ${COMMODITY:+-c "$COMMODITY"} --plot ;;
        *)
            echo "Usage: $0 {once|telegram|monitor|schedule|paper|paper-monitor|paper-schedule|backtest|bt-all|bt-journal|bt-plot} [commodity]"
            exit 1
            ;;
    esac
}

# If using LLM, start llama.cpp server first
if [[ "${LLM_ENABLED:-false}" == "true" ]]; then
    MODEL="${LLM_MODEL:-models/LFM2.5-1.2B-Instruct-Q4_K_M.gguf}"
    if [[ ! -f "$MODEL" ]]; then
        echo "Model not found at $MODEL. Set LLM_MODEL or download one."
        exit 1
    fi
    echo "Starting llama.cpp server..."
    llama-server -m "$MODEL" --host 127.0.0.1 --port 8080 &
    LLAMA_PID=$!
    sleep 3
    trap "kill $LLAMA_PID 2>/dev/null" EXIT
fi

run_agent
