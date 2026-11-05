#!/usr/bin/env bash
# ==============================================================================
# CalSol CAN Testbench - Bash CLI Wrapper
# Forwards commands directly to the modular Python client CLI
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use python3 if available, else python
PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

exec "$PYTHON_BIN" "${SCRIPT_DIR}/calsol.py" "$@"
