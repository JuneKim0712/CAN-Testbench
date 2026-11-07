#!/usr/bin/env python3
"""
CalSol Hardware Testbench: Pages Telemetry Ingestion & Compiler
Merges recent CI test results (*test_results*.json, *can_trace*.jsonl, static_check.json)
into web/data/history.json for the GitHub Pages interactive dashboard.
"""

import os
import sys
import json
import glob
import time
from datetime import datetime, timezone

def compile_run_record(repo_root, run_id=None, commit_sha=None):
    web_data_dir = os.path.join(repo_root, "web", "data")
    os.makedirs(web_data_dir, exist_ok=True)
    history_file = os.path.join(web_data_dir, "history.json")

    # Load existing history if available
    history = {"generated_at": datetime.now(timezone.utc).isoformat(), "runs": []}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            print(f"[-] Warning: Failed to parse existing history.json: {e}")

    # Resolve Git metadata
    run_id = run_id or os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    commit_sha = commit_sha or os.environ.get("GITHUB_SHA", "head")[:7]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    author = os.environ.get("GITHUB_ACTOR", "engineer")
    commit_msg = os.environ.get("GITHUB_COMMIT_MESSAGE", "Automated Hardware Verification")

    # Aggregate all subsystem test reports
    total_tests_pass = 0
    total_tests_count = 0
    subsystems_tested = []
    all_tests = []
    seen_tests = set()
    max_duration = 0.0

    # Search for all test result files (*test_results*.json) across repo and pr_artifacts
    report_pattern = os.path.join(repo_root, "**", "*test_results*.json")
    for r_path in glob.glob(report_pattern, recursive=True):
        if "web" in r_path:
            continue
        try:
            with open(r_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                sub_name = data.get("subsystem", "")
                if not sub_name:
                    base = os.path.basename(r_path)
                    sub_name = base.replace("_test_results.json", "").replace("test_results.json", "")
                if not sub_name:
                    sub_name = os.path.basename(os.path.dirname(r_path))

                if sub_name and sub_name not in subsystems_tested:
                    subsystems_tested.append(sub_name)

                duration = data.get("duration", 0.0)

                if duration > max_duration:
                    max_duration = duration

                for t in data.get("tests", []):
                    t_name = t.get("name", "unknown")
                    key = (sub_name, t_name)
                    if key not in seen_tests:
                        seen_tests.add(key)
                        all_tests.append({
                            "subsystem": sub_name,
                            "name": t_name,
                            "file": t.get("file", "./main/test_main.c"),
                            "line": t.get("line", 196),
                            "status": t.get("status", "PASS"),
                            "details": t.get("details", "")
                        })
        except Exception as e:
            print(f"[-] Error reading {r_path}: {e}")

    # Derive accurate pass/total counts from parsed test assertions
    if all_tests:
        total_tests_pass = sum(1 for t in all_tests if t.get("status") == "PASS")
        total_tests_count = len(all_tests)

    # Fallback if no sub-reports found (e.g. direct invocation)
    if not subsystems_tested:
        subsystems_tested = ["pedals_fw"]

    # Ingest CAN traces
    can_packets = []
    trace_pattern = os.path.join(repo_root, "**", "*can_trace*.jsonl")
    for t_path in glob.glob(trace_pattern, recursive=True):
        if "web" in t_path:
            continue
        try:
            with open(t_path, "r", encoding="utf-8") as f:
                first_ts = None
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    ts = item.get("timestamp", 0.0)
                    if first_ts is None:
                        first_ts = ts
                    rel_t = round(ts - first_ts, 2)
                    can_packets.append({
                        "t": rel_t,
                        "id": item.get("id", "0x000"),
                        "name": item.get("name", "UNKNOWN"),
                        "dlc": item.get("dlc", 0),
                        "raw": item.get("data", ""),
                        "decoded": item.get("decoded", "Raw Payload")
                    })
        except Exception as e:
            print(f"[-] Error reading CAN trace {t_path}: {e}")

    # Deduplicate can_packets
    if len(can_packets) > 30:
        can_packets = can_packets[:30]

    # Static analysis
    static_status = "passed"
    static_defects = 0
    static_report_path = os.path.join(repo_root, "static_check.json")
    if os.path.exists(static_report_path):
        try:
            with open(static_report_path, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                static_defects = s_data.get("defects", 0)
                if static_defects > 0:
                    static_status = "failed"
        except Exception:
            pass

    overall_status = "passed" if (total_tests_pass == total_tests_count and total_tests_count > 0 and static_status == "passed") else "failed"

    failure_type = None
    failure_details = None
    if overall_status == "failed":
        failed_test = next((t for t in all_tests if t.get("status") == "FAIL"), None)
        if failed_test:
            failure_type = "assertion_failure"
            failure_details = {
                "title": "Silicon Unit Test Assertion Failure Detected",
                "exit_code": "1 (Hardware Verification Failed)",
                "location": f"{failed_test.get('subsystem')} -> {failed_test.get('file')}:{failed_test.get('line')} ({failed_test.get('name')})",
                "diff": failed_test.get("details", ""),
                "repro": f"./github-action/cal-test.sh {failed_test.get('subsystem')}/test /dev/esp32_johnathan",
                "summary": "Flashing and executing this isolated test will acquire the bench mutex and stream serial assertions directly to your terminal."
            }
        elif static_status == "failed":
            failure_type = "static_analysis_failure"
            failure_details = {
                "title": "Cloud Quality Gate (cppcheck) Defect Detected",
                "exit_code": "1 (Static Analysis Gate Failed)",
                "location": "Subsystem source code",
                "diff": f"Static analysis identified {static_defects} defect(s).",
                "repro": "./github-action/static-check.sh",
                "summary": "Cloud static analysis detected defects in source files. Check cppcheck output."
            }
        elif total_tests_count == 0:
            failure_type = "build_failure"
            failure_details = {
                "title": "Firmware Compilation Failure",
                "exit_code": "2 (Compilation Failed)",
                "location": f"{subsystems_tested[0] if subsystems_tested else 'firmware'}",
                "diff": "Build step exited with non-zero status prior to test dispatch.",
                "repro": f"idf.py -C {subsystems_tested[0] if subsystems_tested else 'pedals_fw'}/test build",
                "summary": "ESP-IDF build failed. Check compiler output in workflow logs."
            }

    # Assemble separate run records for each subsystem file
    new_runs = []
    for sub_name in subsystems_tested:
        sub_tests = [t for t in all_tests if t.get("subsystem") == sub_name]
        sub_pass = sum(1 for t in sub_tests if t.get("status") == "PASS")
        sub_total = len(sub_tests)
        
        # Subsystem-specific CAN packets
        if sub_name == "lights_fw":
            sub_can = [p for p in can_packets if p.get("id") in ["0x021", "0x001"]]
        else:
            sub_can = [p for p in can_packets if p.get("id") in ["0x011", "0x001"]]
            if not sub_can:
                sub_can = can_packets

        sub_status = "passed" if (sub_pass == sub_total and sub_total > 0 and static_status == "passed") else "failed"

        sub_failed_test = next((t for t in sub_tests if t.get("status") == "FAIL"), None)
        sub_failure_type = None
        sub_failure_details = None
        if sub_failed_test:
            sub_failure_type = "assertion_failure"
            sub_failure_details = {
                "title": f"Silicon Unit Test Assertion Failure: {sub_name}",
                "exit_code": "1 (Hardware Verification Failed)",
                "location": f"{sub_failed_test.get('file', 'test_main.c')}:{sub_failed_test.get('line', 0)} ({sub_failed_test.get('name', 'test')})",
                "diff": sub_failed_test.get("details", ""),
                "repro": f"./github-action/cal-test.sh {sub_name}/test",
                "summary": "Flashing and executing this isolated test will acquire the bench mutex and stream serial assertions directly to your terminal."
            }
        elif sub_total == 0:
            sub_failure_type = "build_failure"
            sub_failure_details = {
                "title": f"Firmware Compilation Failure: {sub_name}",
                "exit_code": "2 (Compilation Failed)",
                "location": sub_name,
                "diff": "Build step exited with non-zero status prior to test dispatch.",
                "repro": f"idf.py -C {sub_name}/test build",
                "summary": "ESP-IDF build failed. Check compiler output in workflow logs."
            }
        elif static_status == "failed":
            sub_failure_type = "static_analysis_failure"
            sub_failure_details = {
                "title": "Cloud Quality Gate Defect Detected",
                "exit_code": "1 (Static Analysis Gate Failed)",
                "location": sub_name,
                "diff": f"Static analysis identified {static_defects} defect(s).",
                "repro": "./github-action/static-check.sh",
                "summary": "Cloud static analysis detected defects in source files."
            }

        duration_sec = round(max_duration, 1) if max_duration > 0 else 0.0

        sub_run = {
            "id": f"{run_id}-{sub_name.replace('_fw', '')}",
            "parent_run_id": str(run_id),
            "subsystem": sub_name,
            "subsystems": [sub_name],
            "commit": str(commit_sha)[:7],
            "branch": branch,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": author,
            "message": f"[{sub_name}] {commit_msg}",
            "status": sub_status,
            "failure_type": sub_failure_type,
            "failure_details": sub_failure_details,
            "duration": f"{duration_sec}s",
            "lock_duration_sec": duration_sec,
            "tests_pass": sub_pass,
            "tests_total": sub_total,
            "tests": sub_tests,
            "can_packets": sub_can,
            "static_analysis": {
                "status": static_status,
                "defects": static_defects
            }
        }
        new_runs.append(sub_run)

    # Prepend and limit history with automated stale in_progress sanitization
    now_utc = datetime.now(timezone.utc)
    sanitized_existing = []
    for r in history.get("runs", []):
        if str(r.get("id")).startswith(str(run_id)):
            continue
        if r.get("status") == "in_progress":
            ts_str = r.get("timestamp")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
                age_sec = (now_utc - ts).total_seconds() if ts else 999999
            except Exception:
                age_sec = 999999
            if age_sec > 1800:
                r["status"] = "failed"
                r["failure_type"] = "lock_timeout"
                r["failure_details"] = {
                    "title": "Hardware Execution Lock Timeout",
                    "exit_code": "124 (Workflow Timeout)",
                    "location": r.get("subsystem", "ECU"),
                    "diff": "Runner job exceeded maximum execution window. Process aborted.",
                    "repro": f"./github-action/cal-test.sh {r.get('subsystem', 'pedals_fw')}/test /dev/esp32_johnathan",
                    "summary": "Execution timed out while waiting for hardware mutex or serial assertions."
                }
                r["duration"] = "Timed Out (>30m)"
        sanitized_existing.append(r)
    history["runs"] = new_runs + sanitized_existing[:48]
    history["generated_at"] = datetime.now(timezone.utc).isoformat()

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"[+] Updated {history_file} with {len(new_runs)} separate subsystem runs ({len(history['runs'])} total stored)")

if __name__ == "__main__":
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    compile_run_record(repo_root)
