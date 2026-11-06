#!/usr/bin/env python3
"""
CalSol Consolidated Testbench Reporter & Dashboard
Aggregates Static Analysis results, HIL Unity test outcomes,
and Crash Backtraces into a unified status dashboard for both
GitHub Actions Step Summary ($GITHUB_STEP_SUMMARY) and PR comments.
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
    hil_reports = []

    if not artifacts_dir or not os.path.exists(artifacts_dir):
        return test_reports, crash_reports, hil_reports

    for root, _, files in os.walk(artifacts_dir):
        for f in files:
            path = os.path.join(root, f)
            if f.endswith("_test_results.json") or f == "test_results.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                        if "subsystem" not in data or not data["subsystem"]:
                            # deduce from filename e.g. pedals_fw_test_results.json
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
            elif f.endswith("hil_report.json"):
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                        hil_reports.append(data)
                except Exception:
                    pass

    return test_reports, crash_reports, hil_reports

def build_dashboard(repo, run_id, commit_sha, jobs, test_reports, crash_reports, hil_reports=None):
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id else ""

    md = []
    md.append(IDENTIFIER_TAG)
    md.append("## CalSol Testbench Status Dashboard\n")
    if run_url:
        md.append(f"**Commit:** `{short_sha}` | **Workflow Run:** [#{run_id}]({run_url})\n")
    else:
        md.append(f"**Commit:** `{short_sha}`\n")

    # 1. Static Analysis Summary
    lint_job = next((j for j in jobs if "Lint" in j.get("name", "") or "Static" in j.get("name", "")), None)
    if lint_job:
        lint_conclusion = lint_job.get("conclusion")
        if lint_conclusion == "success":
            md.append("### Pre-Hardware Quality Gate: Passed\n- Cppcheck static analysis passed (0 critical defects detected).\n")
        elif lint_conclusion == "failure":
            md.append("### Pre-Hardware Quality Gate: Failed\n- Critical memory or syntax defects detected by cppcheck. Hardware dispatch blocked.\n")
        else:
            status_text = lint_conclusion.capitalize() if lint_conclusion else "In Progress"
            md.append(f"### Pre-Hardware Quality Gate: {status_text}\n")

    # 2. Hardware Tests Summary
    hw_jobs = [j for j in jobs if j.get("name", "").startswith("Test ")]
    
    # Map subsystem to test report
    report_map = {}
    for tr in test_reports:
        sub = tr.get("subsystem", "")
        if sub:
            report_map[sub] = tr

    overall_hw_passed = True
    if hw_jobs:
        md.append("### On-Target Hardware In-The-Loop (HIL) Tests\n")
        md.append("| Subsystem | Port / Device | Test Results | Status | Duration |")
        md.append("| :--- | :---: | :---: | :---: | :---: |")
        for j in hw_jobs:
            name = j.get("name", "").replace("Test ", "").strip()
            # If name has format: pedals_fw (/dev/esp32_ahmed)
            sub_name = name.split()[0] if " " in name else name
            conclusion = j.get("conclusion", "in_progress")
            if conclusion != "success":
                overall_hw_passed = False

            tr = report_map.get(sub_name)
            if tr:
                results_text = f"{tr.get('passed_count', 0)} Passed / {tr.get('failed_count', 0)} Failed"
                port_text = tr.get("port", "Physical HW")
            else:
                results_text = "Completed" if conclusion == "success" else "Check logs"
                port_text = "Physical HW"

            status_badge = "Passed" if conclusion == "success" else ("Failed" if conclusion == "failure" else conclusion.capitalize())
            duration = "Completed" if j.get("completed_at") else "Running"
            md.append(f"| `{sub_name}` | `{port_text}` | {results_text} | {status_badge} | {duration} |")
        md.append("")
    elif test_reports:
        md.append("### On-Target Hardware In-The-Loop (HIL) Tests\n")
        md.append("| Subsystem | Port / Device | Test Results | Status |")
        md.append("| :--- | :---: | :---: | :---: |")
        for tr in test_reports:
            sub = tr.get("subsystem", "hardware")
            status = "Passed" if tr.get("passed") else "Failed"
            if not tr.get("passed"):
                overall_hw_passed = False
            results_text = f"{tr.get('passed_count', 0)} Passed / {tr.get('failed_count', 0)} Failed"
            md.append(f"| `{sub}` | `{tr.get('port', 'HW')}` | {results_text} | {status} |")
        md.append("")
    else:
        md.append("### On-Target Hardware In-The-Loop (HIL) Tests: Skipped\n")
        md.append("*No hardware tests executed (e.g. documentation-only changes or clean skip).*\n")

    # 3. Detailed Unity Test Results
    if test_reports:
        md.append("### Detailed Test Suite Results\n")
        for tr in test_reports:
            sub = tr.get("subsystem", "hardware")
            tests = tr.get("tests", [])
            summary = tr.get("summary", "")
            sub_status = "Passed" if tr.get("passed") else "Failed"
            md.append(f"#### Subsystem: `{sub}` ({sub_status})\n")
            if summary:
                md.append(f"**Summary:** {summary}\n")
            if tests:
                md.append("| Status | Test Function | Details |")
                md.append("| :---: | :--- | :--- |")
                for t in tests:
                    md.append(f"| {t.get('status', 'INFO')} | `{t.get('name', '')}` | `{t.get('details', '')}` |")
                md.append("")

    # 4. Automated HIL Road Testing Suite
    if hil_reports:
        md.append("### Automated HIL Road Testing Suite\n")
        for hr in hil_reports:
            total_scenarios = hr.get("total_scenarios", 0)
            passed_scenarios = hr.get("passed_scenarios", 0)
            failed_scenarios = hr.get("failed_scenarios", 0)
            pass_rate = hr.get("pass_rate_percent", 0.0)
            km = hr.get("simulated_km", 0.0)
            frames = hr.get("total_frames_verified", 0)

            status = "Passed" if failed_scenarios == 0 else "Failed"
            md.append(f"- **Suite Status:** `{status}` ({passed_scenarios}/{total_scenarios} scenarios passed, {pass_rate:.1f}%)")
            md.append(f"- **Telemetry Checked:** {frames} CAN frames across {km:.1f} km simulated road testing.\n")

            failed_list = [s for s in hr.get("scenarios", []) if not s.get("passed")]
            if failed_list:
                md.append("#### Failed Road Scenarios\n")
                md.append("| Scenario ID | Scenario Name | Category | Error |")
                md.append("| :---: | :--- | :--- | :--- |")
                for fs in failed_list:
                    md.append(f"| `{fs.get('id')}` | {fs.get('name')} | {fs.get('category')} | `{fs.get('error')}` |")
                md.append("")

    # 5. Decoded Crash Reports if any
    crashed_count = sum(1 for cr in crash_reports if cr.get("has_crashed"))
    if crashed_count > 0:
        md.append("### Decoded Crash Backtrace\n")
        for cr in crash_reports:
            if cr.get("has_crashed"):
                sub = cr.get("subsystem", "hardware")
                reason = cr.get("crash_reason", "Unhandled Hardware Panic")
                md.append(f"#### Subsystem: `{sub}`\n")
                md.append(f"> **Reason:** `{reason}`\n")
                frames = cr.get("frames", [])
                if frames:
                    md.append("| Frame | Program Counter (PC) | Function Name | Source Location |")
                    md.append("| :---: | :---: | :--- | :--- |")
                    for f in frames:
                        md.append(f"| **{f.get('frame')}** | `{f.get('address')}` | `{f.get('function')}` | `{f.get('location')}` |")
                    md.append("")

    md.append("\n---\n*CalSol CAN Testbench Engine automated status report.*")
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
    test_reports, crash_reports, hil_reports = find_reports(args.artifacts_dir)
    print(f"[*] Found {len(test_reports)} test reports, {len(crash_reports)} crash reports, {len(hil_reports)} HIL road reports.")

    dashboard_body = build_dashboard(repo, run_id, commit_sha, jobs, test_reports, crash_reports, hil_reports)

    # 1. Always output to GITHUB_STEP_SUMMARY if available
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        try:
            with open(gh_summary, "a", encoding="utf-8") as f:
                f.write("\n" + dashboard_body + "\n")
            print("[+] Successfully wrote dashboard to GITHUB_STEP_SUMMARY.")
        except Exception as e:
            print(f"[-] Failed to write GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    # 2. If PR environment variables exist, update or post sticky PR comment
    if repo and pr_number and token:
        post_or_update_pr_comment(repo, pr_number, token, dashboard_body)

    print("[+] Dashboard generation complete.")

if __name__ == "__main__":
    main()
