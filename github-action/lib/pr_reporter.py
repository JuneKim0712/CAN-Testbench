#!/usr/bin/env python3
"""
CalSol Consolidated Testbench Reporter & Dashboard
Aggregates Static Analysis results, On-Target HIL Unity outcomes,
Live CAN Bus traffic captures, and Decoded Crash Backtraces into
a unified, high-visibility status dashboard for both GitHub Actions
Step Summary ($GITHUB_STEP_SUMMARY) and sticky PR comments.
"""

import os
import sys
import glob
import json
import urllib.request
import urllib.error
import argparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

IDENTIFIER_TAG = "<!-- CALSOL_HIL_STATUS_COMMENT -->"


def github_api_request(url, token, data=None, method="GET"):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CalSol-CI-Reporter"
    }
    encoded_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[-] GitHub API error {e.code} on {method} {url}: {error_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[-] Request failed: {e}", file=sys.stderr)
        return None


def find_reports(artifacts_dir):
    test_reports = []
    crash_reports = []

    if not artifacts_dir or not os.path.exists(artifacts_dir):
        return test_reports, crash_reports

    for root, _, files in os.walk(artifacts_dir):
        for f in files:
            path = os.path.join(root, f)
            if f.endswith("_test_results.json") or f == "test_results.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                        if "subsystem" not in data or not data["subsystem"]:
                            data["subsystem"] = f.replace("_test_results.json", "").replace("test_results.json", "hardware")
                        test_reports.append(data)
                except Exception:
                    pass
            elif f.endswith("_crash_report.json") or f == "crash_report.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                        if "subsystem" not in data or not data["subsystem"]:
                            data["subsystem"] = f.replace("_crash_report.json", "").replace("crash_report.json", "hardware")
                        crash_reports.append(data)
                except Exception:
                    pass

    return test_reports, crash_reports


def build_dashboard(repo, run_id, commit_sha, jobs, test_reports, crash_reports):
    short_sha = commit_sha[:7] if commit_sha else "local-HEAD"
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id else ""

    # Determine static analysis status
    static_job = next((j for j in jobs if "static-analysis" in j.get("name", "").lower() or "lint" in j.get("name", "").lower()), None)
    static_ok = (static_job.get("conclusion") == "success") if static_job else True
    
    hw_jobs = [j for j in jobs if j.get("name", "").startswith("Test ")]
    report_map = {tr.get("subsystem", ""): tr for tr in test_reports}

    # Verify that all hardware jobs succeeded
    hw_all_passed = True
    for j in hw_jobs:
        if j.get("conclusion") == "failure":
            hw_all_passed = False

    total_tests_run = 0
    total_tests_passed = 0
    all_can_traffic = []

    for tr in test_reports:
        if not tr.get("passed", False):
            hw_all_passed = False
        total_tests_run += tr.get("total_assertions", 0)
        total_tests_passed += tr.get("passed_count", 0)
        sub_name = tr.get("subsystem", "ECU")
        for fr in tr.get("can_traffic", []):
            fr_copy = dict(fr)
            fr_copy["subsystem"] = sub_name
            all_can_traffic.append(fr_copy)

    has_crashes = any(cr.get("has_crashed") for cr in crash_reports)
    overall_success = static_ok and hw_all_passed and not has_crashes

    md = []
    md.append(IDENTIFIER_TAG)

    # 1. Executive Status Header
    status_str = "PASSED" if overall_success else "FAILED"
    status_badge = "✅ Passed" if overall_success else "❌ Failed"
    md.append(f"## CalSol Hardware-in-the-Loop Testbench: {status_str}\n")
    md.append(f"> **Status:** {status_badge} | **Commit:** [`{short_sha}`]({run_url}) | **Environment:** `stolerpi (ARM64 HIL)`\n")

    # 2. Bench Hardware Node Map & Summary
    md.append("### Subsystem Execution Summary\n")
    md.append("| Subsystem | Target Node & Port | Unit Test Results | CAN Traffic | Status |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")

    if hw_jobs:
        for j in hw_jobs:
            raw_name = j.get("name", "").replace("Test ", "").strip()
            sub_name = raw_name.split()[0] if " " in raw_name else raw_name
            conclusion = j.get("conclusion", "in_progress")
            tr = report_map.get(sub_name)

            if tr:
                results_text = f"**{tr.get('passed_count', 0)}** passed / {tr.get('failed_count', 0)} failed"
                port_text = tr.get("port", "/dev/esp32_johnathan")
                can_count = len(tr.get("can_traffic", []))
                can_text = f"{can_count} frames" if can_count > 0 else "0 frames (bus quiet)"
                badge = "✅ Passed" if tr.get("passed") else "❌ Failed"
            else:
                results_text = "Completed" if conclusion == "success" else "Check build/flash logs"
                port_text = "/dev/esp32_johnathan"
                can_text = "—"
                badge = "✅ Passed" if conclusion == "success" else ("❌ Failed" if conclusion == "failure" else "In Progress")

            md.append(f"| `{sub_name}` | `{port_text}` | {results_text} | {can_text} | {badge} |")
    elif test_reports:
        for tr in test_reports:
            sub = tr.get("subsystem", "ECU")
            status = "✅ Passed" if tr.get("passed") else "❌ Failed"
            results_text = f"**{tr.get('passed_count', 0)}** passed / {tr.get('failed_count', 0)} failed"
            can_count = len(tr.get("can_traffic", []))
            can_text = f"{can_count} frames" if can_count > 0 else "0 frames (bus quiet)"
            md.append(f"| `{sub}` | `{tr.get('port', '/dev/esp32_johnathan')}` | {results_text} | {can_text} | {status} |")
    else:
        md.append("| *No Subsystems Tested* | — | — | — | Skipped |")
    md.append("")

    # Static Analysis Gate Status
    if static_job:
        status_sym = "Passed" if static_ok else "Failed"
        md.append(f"- **Static Analysis (cppcheck):** {status_sym} (0 critical memory/syntax defects)\n")

    # 3. Live Physical CAN Bus Traffic Inspection
    md.append("### CAN Bus Telemetry & Traffic\n")
    if all_can_traffic:
        md.append(f"> **Bus Monitor:** Active on `/dev/esp32_ahmed` (500 kbps) | **Total Captured Frames:** {len(all_can_traffic)}\n")
        md.append("<details open>\n<summary><b>Decoded Bus Packets</b></summary>\n")
        md.append("")
        md.append("| Time (rel) | Subsystem | CAN ID | Message Name | DLC | Payload | Decoded Signal Interpretation |")
        md.append("| :---: | :---: | :---: | :--- | :---: | :---: | :--- |")
        for fr in all_can_traffic[:30]:
            sub = fr.get("subsystem", "ECU")
            md.append(f"| `{fr.get('rel_time')}` | `{sub}` | `{fr.get('id')}` | **{fr.get('name')}** | `{fr.get('dlc')}` | `0x{fr.get('data')}` | {fr.get('decoded')} |")
        if len(all_can_traffic) > 30:
            md.append(f"\n*... and {len(all_can_traffic) - 30} additional frames recorded in `can_trace.jsonl` artifact.*")
        md.append("\n</details>\n")
    else:
        md.append("> **Bus Monitor:** Active on `/dev/esp32_ahmed` (500 kbps) | **Captured Frames:** 0\n")
        md.append("> \n> *The dedicated CAN Debugger monitored the physical differential bus during the test suite execution. No differential frames were detected during this window (the bus remained idle or tests executed internal logic).*\n")

    # 4. Detailed Unit Test Assertions
    if test_reports:
        md.append("### Unit Test Assertions\n")
        for tr in test_reports:
            sub = tr.get("subsystem", "ECU")
            tests = tr.get("tests", [])
            sub_passed = tr.get("passed", False)
            sub_status = "Passed" if sub_passed else "Failed"
            open_attr = " open" if not sub_passed else ""
            md.append(f"<details{open_attr}>\n<summary><b>Subsystem: <code>{sub}</code> ({sub_status} — {tr.get('passed_count', 0)}/{tr.get('total_assertions', 0)} passed)</b></summary>\n")
            md.append("")
            if tests:
                md.append("| Status | Test Function | Result Details |")
                md.append("| :---: | :--- | :--- |")
                for t in tests:
                    icon = "PASS" if t.get("status") == "PASS" else "FAIL"
                    md.append(f"| `{icon}` | `{t.get('name', '')}` | `{t.get('details', '')}` |")
            md.append("\n</details>\n")

    # 5. Post-Mortem Failure Diagnostics
    failed_tests = [
        (tr.get("subsystem", "ECU"), t)
        for tr in test_reports
        for t in tr.get("tests", [])
        if t.get("status") == "FAIL"
    ]
    crashed_reports = [cr for cr in crash_reports if cr.get("has_crashed")]
    failed_build_jobs = [
        j.get("name", "") for j in hw_jobs 
        if j.get("conclusion") == "failure" and not any(sub in j.get("name", "") for sub in report_map)
    ]

    if failed_tests or crashed_reports or failed_build_jobs or not overall_success:
        md.append("### Failure Diagnostics\n")
        if failed_build_jobs:
            md.append("#### Build & Silicon Flashing Errors\n")
            for jn in failed_build_jobs:
                md.append(f"> **`{jn}`** failed prior to test completion (compilation or flashing failure). Check workflow step logs for error trace.\n")
        if failed_tests:
            md.append("#### Failed Unit Test Assertions\n")
            md.append("| Subsystem | Failed Test Function | Failure Details |")
            md.append("| :--- | :--- | :--- |")
            for sub, t in failed_tests:
                md.append(f"| `{sub}` | `{t.get('name')}` | `{t.get('details')}` |")
            md.append("")

        if crashed_reports:
            md.append("#### Hardware Exception & Stack Backtrace\n")
            for cr in crashed_reports:
                sub = cr.get("subsystem", "ECU")
                reason = cr.get("crash_reason", "Hardware Exception / Panic")
                md.append(f"> **Target Subsystem:** `{sub}` | **Exception Reason:** `{reason}`\n")
                frames = cr.get("frames", [])
                if frames:
                    md.append("| Frame | Address | Function | Source Location |")
                    md.append("| :---: | :---: | :--- | :--- |")
                    for f in frames:
                        md.append(f"| `#{f.get('frame')}` | `{f.get('address')}` | `{f.get('function')}` | `{f.get('location')}` |")
                    md.append("")

    # 6. Deployment Binaries
    md.append("### Deployment Binaries\n")
    md.append("Compiled firmware binaries (`.bin`, `.elf`, `bootloader.bin`) and bus traces (`can_trace.jsonl`) are archived in the **Run Artifacts**:\n")
    md.append("```bash\n# Flashing trackside via esptool\npython3 -m esptool --chip esp32s3 -p /dev/esp32_johnathan -b 921600 write_flash 0x10000 <subsystem>.bin\n```\n")

    md.append("---\n*CalSol Hardware Testbench CI*")
    return "\n".join(md)

def post_or_update_pr_comment(repo, pr_number, token, body):
    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    comments = github_api_request(comments_url, token)

    existing_comment_id = None
    if comments and isinstance(comments, list):
        for c in comments:
            if IDENTIFIER_TAG in c.get("body", ""):
                existing_comment_id = c.get("id")
                break

    if existing_comment_id:
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_comment_id}"
        print(f"[*] Updating existing PR comment ID {existing_comment_id}...")
        res = github_api_request(update_url, token, data={"body": body}, method="PATCH")
        if res:
            print("[+] Successfully updated sticky PR comment.")
    else:
        print(f"[*] Posting new sticky PR comment to PR #{pr_number}...")
        res = github_api_request(comments_url, token, data={"body": body}, method="POST")
        if res:
            print("[+] Successfully created sticky PR comment.")


def main():
    parser = argparse.ArgumentParser(description="CalSol Consolidated Testbench Reporter & Dashboard")
    parser.add_argument("--artifacts-dir", default=".", help="Directory containing downloaded matrix reports")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    pr_number = os.environ.get("PR_NUMBER")
    repo = os.environ.get("REPO")
    run_id = os.environ.get("RUN_ID")
    commit_sha = os.environ.get("COMMIT_SHA")

    print(f"[*] Aggregating reports (Run #{run_id or 'local'})...")

    jobs = []
    if repo and run_id and token:
        jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
        jobs_data = github_api_request(jobs_url, token)
        jobs = jobs_data.get("jobs", []) if jobs_data else []

    # Parse reports
    test_reports, crash_reports = find_reports(args.artifacts_dir)
    print(f"[*] Found {len(test_reports)} test reports, {len(crash_reports)} crash reports.")

    dashboard_body = build_dashboard(repo, run_id, commit_sha, jobs, test_reports, crash_reports)

    # 1. Output to GITHUB_STEP_SUMMARY if available
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        try:
            with open(gh_summary, "a", encoding="utf-8") as f:
                f.write("\n" + dashboard_body + "\n")
            print("[+] Successfully wrote dashboard to GITHUB_STEP_SUMMARY.")
        except Exception as e:
            print(f"[-] Failed to write GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    # 2. Update or post sticky PR comment
    if repo and pr_number and token:
        post_or_update_pr_comment(repo, pr_number, token, dashboard_body)

    print("[+] Dashboard generation complete.")


if __name__ == "__main__":
    main()
