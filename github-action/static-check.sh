#!/usr/bin/env bash
# ==============================================================================
# CalSol Fast-Fail Cloud Static Analysis & Code Quality Gate
# Delegates execution to github-action/lib/static_check.py
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/lib/static_check.py"
