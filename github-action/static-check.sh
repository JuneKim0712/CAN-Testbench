#!/usr/bin/env bash
# ==============================================================================
# CalSol Fast-Fail Cloud Static Analysis & Code Quality Gate
# Runs clang-format and cppcheck before physical hardware flashing.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=================================================="
echo " CalSol Pre-Hardware Static Analysis & Lint Gate"
echo " Target Root: ${REPO_ROOT}"
echo "=================================================="

# 1. Verify Tools
MISSING_TOOLS=""
if ! command -v cppcheck >/dev/null 2>&1; then
    MISSING_TOOLS="${MISSING_TOOLS} cppcheck"
fi
if ! command -v clang-format >/dev/null 2>&1; then
    MISSING_TOOLS="${MISSING_TOOLS} clang-format"
fi

if [ -n "$MISSING_TOOLS" ]; then
    echo "[-] Error: Missing required static analysis tools:${MISSING_TOOLS}"
    echo "    Install via: sudo apt-get update && sudo apt-get install -y cppcheck clang-format"
    exit 1
fi

REPORT_FILE="${SCRIPT_DIR}/.logs/static_analysis.log"
mkdir -p "$(dirname "$REPORT_FILE")"
rm -f "$REPORT_FILE"

HAS_FORMAT_ERRORS=0
HAS_CPPCHECK_ERRORS=0

# 2. Clang-Format Style Check
echo -n "[*] Running clang-format code style verification... "
FORMAT_UNFORMATTED_FILES=()

while IFS= read -r file; do
    # Skip build, components/managed, and hidden files
    if [[ "$file" =~ (\.git|build|managed_components|\.logs) ]]; then
        continue
    fi
    if ! clang-format --dry-run --Werror "$file" 2>/dev/null; then
        FORMAT_UNFORMATTED_FILES+=("$file")
        HAS_FORMAT_ERRORS=1
    fi
done < <(find "${REPO_ROOT}" -maxdepth 4 -type f \( -name "*.c" -o -name "*.h" \))

if [ $HAS_FORMAT_ERRORS -eq 0 ]; then
    echo "PASSED (Clean)"
else
    echo "WARNING"
    echo "    The following files do not match repository .clang-format style:"
    for f in "${FORMAT_UNFORMATTED_FILES[@]}"; do
        rel_f="${f#$REPO_ROOT/}"
        echo "      - ${rel_f} (Auto-fix with: clang-format -i ${rel_f})"
    done
fi

# 3. Cppcheck Static Analysis (Null pointers, buffer overflows, uninit vars, leaks)
echo -n "[*] Running cppcheck deep static analysis... "

CPPCHECK_TARGETS=()
for dir in "${REPO_ROOT}"/*/; do
    dir_name="$(basename "$dir")"
    if [[ "$dir_name" =~ ^(\.git|\.github|\.logs|build|managed_components|Slack_Bot)$ ]]; then
        continue
    fi
    if [ -d "$dir" ]; then
        CPPCHECK_TARGETS+=("$dir")
    fi
done

if [ ${#CPPCHECK_TARGETS[@]} -eq 0 ]; then
    CPPCHECK_TARGETS=("${REPO_ROOT}")
fi

if cppcheck --enable=warning,performance,portability \
            --inline-suppr \
            --suppress=missingIncludeSystem \
            --suppress=unmatchedSuppression \
            --error-exitcode=1 \
            --template="[{file}:{line}]: ({severity}) {message}" \
            "${CPPCHECK_TARGETS[@]}" > "$REPORT_FILE" 2>&1; then
    echo "PASSED (0 defects detected)"
else
    echo "FAILED"
    HAS_CPPCHECK_ERRORS=1
    echo "=== Cppcheck Diagnostics ==="
    cat "$REPORT_FILE"
fi

# 4. Write GitHub Actions Step Summary if in CI
if [ -n "$GITHUB_STEP_SUMMARY" ]; then
    {
        echo "### 🛡️ Pre-Hardware Code Quality & Static Analysis"
        echo ""
        if [ $HAS_CPPCHECK_ERRORS -eq 0 ]; then
            echo "✅ **Cppcheck Static Analysis:** Passed (0 logic bugs / memory safety defects)"
        else
            echo "❌ **Cppcheck Static Analysis:** Failed — logic defects detected"
            echo '```text'
            cat "$REPORT_FILE"
            echo '```'
        fi
        echo ""
        if [ $HAS_FORMAT_ERRORS -eq 0 ]; then
            echo "✅ **Clang-Format Style:** All files match repository style"
        else
            echo "⚠️ **Clang-Format Style:** Formatting adjustments recommended:"
            for f in "${FORMAT_UNFORMATTED_FILES[@]}"; do
                rel_f="${f#$REPO_ROOT/}"
                echo "- \`${rel_f}\` (run \`clang-format -i ${rel_f}\`)"
            done
        fi
        echo ""
    } >> "$GITHUB_STEP_SUMMARY"
fi

if [ $HAS_CPPCHECK_ERRORS -ne 0 ]; then
    exit 1
fi

echo "=================================================="
echo " Static Analysis Complete: All Quality Gates Passed"
echo "=================================================="
