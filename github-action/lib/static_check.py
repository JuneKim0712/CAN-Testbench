#!/usr/bin/env python3
"""
CalSol Pre-Hardware Cloud Quality Gate & Static Analysis
Runs cppcheck to catch memory safety defects and logic bugs
before physical microcontrollers on the bench are flashed.
"""

import os
import sys
import subprocess
import shutil
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def find_c_targets(repo_root):
    c_files = []
    target_dirs = set()
    ignored = {".git", "build", "managed_components", ".logs", "Slack_Bot", "web", "docs", "pr_artifacts", ".system_generated"}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ignored]
        has_c = False
        for f in files:
            if f.endswith((".c", ".h")):
                c_files.append(os.path.join(root, f))
                has_c = True
        if has_c:
            target_dirs.add(root)
    return c_files, sorted(target_dirs)

def run_cppcheck(target_dirs):
    if not shutil.which("cppcheck"):
        return None, "cppcheck not found in PATH"

    if not target_dirs:
        return [], None

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
        if res.returncode != 0:
            return None, f"cppcheck invocation failed ({res.returncode}): {res.stderr}"
        combined_output = (res.stdout + "\n" + res.stderr).strip()
        lines = [line.strip() for line in combined_output.splitlines() if line.strip()]
        return lines, None
    except Exception as e:
        return None, str(e)

def main():
    repo_root = os.path.abspath(os.environ.get('CALSOL_REPO_ROOT', os.getcwd()))
    print("==================================================")
    print(" CalSol Pre-Hardware Static Analysis Gate")
    print(f" Target Root: {repo_root}")
    print("==================================================")

    c_files, target_dirs = find_c_targets(repo_root)
    print(f"[*] Found {len(c_files)} C/C++ source & header files across {len(target_dirs)} target directories.")

    # Cppcheck
    cppcheck_lines, cpp_err = run_cppcheck(target_dirs)
    critical_errors = []
    notices = []

    if cpp_err:
        save_report(repo_root, 'unavailable', 0, cpp_err)
        print(f"[-] Quality gate unavailable: {cpp_err}.")
        sys.exit(1)
    elif cppcheck_lines is not None:
        for line in cppcheck_lines:
            if ": (error)" in line:
                critical_errors.append(line)
            elif any(tag in line for tag in [": (warning)", ": (performance)", ": (portability)", ": (style)"]):
                notices.append(line)

        print(f"[*] Cppcheck results: {len(critical_errors)} critical errors, {len(notices)} notices.")
        for err in critical_errors:
            print(f"    [FAIL] {err}")

    # GitHub Actions Step Summary disabled to keep summary dedicated to unit tests

    if critical_errors:
        save_report(repo_root, 'failed', len(critical_errors), critical_errors)
        print("\n[-] Quality Gate FAILED: Critical defects detected. Aborting physical hardware runner.")
        sys.exit(1)

    save_report(repo_root, 'passed', 0, notices)
    print("\n[+] Quality Gate PASSED: All pre-hardware checks successful.")
    sys.exit(0)

def save_report(root, status, defects, details):
    with open(os.path.join(root, 'static_check.json'), 'w', encoding='utf-8') as output:
        json.dump(dict(status=status, defects=defects, details=details,
                       run_id=os.environ.get('GITHUB_RUN_ID')), output, indent=2)


if __name__ == "__main__":
    main()
