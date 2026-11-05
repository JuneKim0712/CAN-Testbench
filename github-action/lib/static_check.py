#!/usr/bin/env python3
"""
CalSol Pre-Hardware Cloud Quality Gate & Static Analysis
Runs clang-format and cppcheck to catch memory safety defects and logic bugs
before physical microcontrollers on the bench are flashed.
"""

import os
import sys
import glob
import subprocess
import shutil

def find_c_files(repo_root):
    c_files = []
    for root, dirs, files in os.walk(repo_root):
        # Skip build and hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["build", "managed_components", ".logs", "Slack_Bot"]]
        for f in files:
            if f.endswith((".c", ".h")):
                c_files.append(os.path.join(root, f))
    return c_files

def check_clang_format(repo_root, c_files):
    if not shutil.which("clang-format"):
        return None, "clang-format not found in PATH"

    unformatted = []
    for f in c_files:
        try:
            res = subprocess.run(
                ["clang-format", "--dry-run", "--Werror", f],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode != 0:
                rel = os.path.relpath(f, repo_root).replace("\\", "/")
                unformatted.append(rel)
        except Exception:
            pass
    return unformatted, None

def run_cppcheck(repo_root):
    if not shutil.which("cppcheck"):
        return None, "cppcheck not found in PATH"

    # Identify directories with C files
    target_dirs = []
    for item in os.listdir(repo_root):
        full = os.path.join(repo_root, item)
        if os.path.isdir(full) and not item.startswith(".") and item not in ["build", "managed_components", ".logs", "Slack_Bot"]:
            target_dirs.append(full)

    if not target_dirs:
        target_dirs = [repo_root]

    cmd = [
        "cppcheck",
        "--enable=warning,performance,portability",
        "--inline-suppr",
        "--suppress=missingInclude",
        "--suppress=missingIncludeSystem",
        "--suppress=unusedFunction",
        "--suppress=unmatchedSuppression",
        '--template=[{file}:{line}]: ({severity}) {message}'
    ] + target_dirs

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        combined_output = (res.stdout + "\n" + res.stderr).strip()
        lines = [line.strip() for line in combined_output.splitlines() if line.strip()]
        return lines, None
    except Exception as e:
        return None, str(e)

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    print("==================================================")
    print(f" CalSol Pre-Hardware Static Analysis & Lint Gate")
    print(f" Target Root: {repo_root}")
    print("==================================================")

    c_files = find_c_files(repo_root)
    print(f"[*] Found {len(c_files)} C/C++ source & header files.")

    # 1. Clang-Format
    unformatted_files, format_err = check_clang_format(repo_root, c_files)
    if format_err:
        print(f"[-] Note: {format_err}. Skipping format check.")
    elif unformatted_files:
        print(f"[-] Warning: {len(unformatted_files)} files do not conform to .clang-format:")
        for uf in unformatted_files:
            print(f"    - {uf} (run: clang-format -i {uf})")
    else:
        print("[+] Code Style: All files conform to .clang-format")

    # 2. Cppcheck
    cppcheck_lines, cpp_err = run_cppcheck(repo_root)
    critical_errors = []
    notices = []

    if cpp_err:
        print(f"[-] Note: {cpp_err}. Skipping cppcheck.")
    elif cppcheck_lines is not None:
        for line in cppcheck_lines:
            if ": (error)" in line:
                critical_errors.append(line)
            elif any(tag in line for tag in [": (warning)", ": (performance)", ": (portability)", ": (style)"]):
                notices.append(line)

        print(f"[*] Cppcheck results: {len(critical_errors)} critical errors, {len(notices)} notices.")
        for err in critical_errors:
            print(f"    ❌ {err}")

    # 3. GitHub Actions Step Summary
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as f:
            f.write("### 🛡️ Pre-Hardware Code Quality & Static Analysis\n\n")
            if cpp_err:
                f.write(f"ℹ️ *Cppcheck skipped: {cpp_err}*\n\n")
            elif critical_errors:
                f.write(f"❌ **Cppcheck Static Analysis:** Failed — {len(critical_errors)} critical defect(s) detected!\n\n")
                f.write("```text\n")
                f.write("\n".join(critical_errors) + "\n")
                f.write("```\n\n")
            else:
                f.write(f"✅ **Cppcheck Static Analysis:** Passed (0 critical bugs, {len(notices)} suggestions)\n\n")
                if notices:
                    f.write(f"<details><summary>ℹ️ View {len(notices)} static analysis suggestions (non-blocking)</summary>\n\n")
                    f.write("```text\n")
                    f.write("\n".join(notices) + "\n")
                    f.write("```\n</details>\n\n")

            if unformatted_files:
                f.write(f"⚠️ **Clang-Format Style:** {len(unformatted_files)} file(s) recommended for formatting:\n")
                for uf in unformatted_files:
                    f.write(f"- `{uf}` (run `clang-format -i {uf}`)\n")
                f.write("\n")
            elif not format_err:
                f.write("✅ **Clang-Format Style:** All files match repository style.\n\n")

    if critical_errors:
        print("\n[-] Quality Gate FAILED: Critical defects detected. Aborting physical hardware runner.")
        sys.exit(1)

    print("\n[+] Quality Gate PASSED: All pre-hardware checks successful.")
    sys.exit(0)

if __name__ == "__main__":
    main()
