#!/usr/bin/env python3
"""
CalSol Sticky PR Reporter Bot
Aggregates Static Analysis results, HIL Unity test outcomes, Memory Footprints,
and Crash Backtraces into a single unified sticky comment on GitHub Pull Requests.
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
    size_reports = []
    test_reports = []
    crash_reports = []

    if not artifacts_dir or not os.path.exists(artifacts_dir):
        return size_reports, test_reports, crash_reports

    for root, _, files in os.walk(artifacts_dir):
        for f in files:
            path = os.path.join(root, f)
            if f.endswith("_size_summary.json") or f == "size_summary.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        size_reports.append(json.load(jf))
                except Exception:
                    pass
            elif f.endswith("_test_results.json") or f == "test_results.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        test_reports.append(json.load(jf))
                except Exception:
                    pass
            elif f.endswith("_crash_report.json") or f == "crash_report.json":
                try:
                    with open(path, "r", encoding="utf-8") as jf:
                        crash_reports.append(json.load(jf))
                except Exception:
                    pass

    return size_reports, test_reports, crash_reports

def build_pr_comment(repo, run_id, commit_sha, jobs, size_reports, test_reports, crash_reports):
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    md = []
    md.append(IDENTIFIER_TAG)
    md.append("## 🏎️ CalSol Testbench Status Dashboard\n")
    md.append(f"**Commit:** `{short_sha}` | **Workflow Run:** [#{run_id}]({run_url})\n")

    # 1. Static Analysis Summary
    lint_job = next((j for j in jobs if "Lint" in j.get("name", "") or "Static" in j.get("name", "")), None)
    if lint_job:
        lint_conclusion = lint_job.get("conclusion")
        if lint_conclusion == "success":
            md.append("### 🛡️ Pre-Hardware Quality Gate: 🟢 Passed\n- Static Analysis & Code Style verified cleanly in cloud container.\n")
        elif lint_conclusion == "failure":
            md.append("### 🛡️ Pre-Hardware Quality Gate: 🔴 Failed\n- Critical memory or syntax defects detected by cppcheck. Hardware dispatch blocked.\n")
        else:
            md.append(f"### 🛡️ Pre-Hardware Quality Gate: ⚪ {lint_conclusion or 'Pending'}\n")

    # 2. Hardware Tests Summary
    md.append("### 🧪 On-Target Hardware In-The-Loop (HIL) Tests\n")
    hw_jobs = [j for j in jobs if j.get("name", "").startswith("Test ")]
    if hw_jobs:
        md.append("| Subsystem | Port / Device | Status | Duration |")
        md.append("| :--- | :---: | :---: | :---: |")
        for j in hw_jobs:
            name = j.get("name", "").replace("Test ", "")
            conclusion = j.get("conclusion", "in_progress")
            badge = "🟢 Passed" if conclusion == "success" else ("🔴 Failed" if conclusion == "failure" else f"⚪ {conclusion}")
            duration = "N/A"
            if j.get("started_at") and j.get("completed_at"):
                # Rough duration calculation if present
                duration = "Completed"
            md.append(f"| `{name}` | `Physical HW` | {badge} | {duration} |")
        md.append("")
    else:
        md.append("*No hardware tests executed (e.g. documentation-only changes).*\n")

    # 3. Memory Footprint Table
    if size_reports:
        md.append("### 📊 Memory & Footprint Utilization\n")
        md.append("| Subsystem | DRAM (Data / BSS RAM) | IRAM | Flash (Code + Data) | Status |")
        md.append("| :--- | :---: | :---: | :---: | :---: |")
        for s in size_reports:
            sub = s.get("subsystem", "unknown")
            dram = f"{s.get('dram_used', 0) / 1024:.1f} KB / {s.get('dram_total', 0) / 1024:.1f} KB ({s.get('dram_pct', 0)}%)"
            iram = f"{s.get('iram_used', 0) / 1024:.1f} KB / {s.get('iram_total', 0) / 1024:.1f} KB ({s.get('iram_pct', 0)}%)"
            flash = f"{s.get('flash_used', 0) / 1024:.1f} KB ({s.get('flash_pct', 0)}%)"
            stat = "🟢 Safe" if s.get("overall_status") == "OK" else ("🟡 Warning" if s.get("overall_status") == "WARNING" else "🔴 Critical")
            md.append(f"| `{sub}` | `{dram}` | `{iram}` | `{flash}` | {stat} |")
        md.append("")

    # 4. Crash Reports if any
    for cr in crash_reports:
        if cr.get("has_crashed"):
            md.append("### 💥 Decoded Crash Backtrace Detected\n")
            reason = cr.get("crash_reason", "Unhandled Hardware Panic")
            md.append(f"> ⚠️ **Reason:** `{reason}`\n")
            frames = cr.get("frames", [])
            if frames:
                md.append("| Frame | PC Address | Function Name | Source File & Line |")
                md.append("| :---: | :---: | :--- | :--- |")
                for f in frames:
                    md.append(f"| **{f.get('frame')}** | `{f.get('address')}` | `{f.get('function')}` | `{f.get('location')}` |")
                md.append("")

    md.append("\n---\n*Automated report generated by CalSol CAN Testbench Engine.*")
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
    parser = argparse.ArgumentParser(description="CalSol Sticky PR Reporter Bot")
    parser.add_argument("--artifacts-dir", default=".", help="Directory containing downloaded matrix reports")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    pr_number = os.environ.get("PR_NUMBER")
    repo = os.environ.get("REPO")
    run_id = os.environ.get("RUN_ID")
    commit_sha = os.environ.get("COMMIT_SHA")

    if not token or not pr_number or not repo or not run_id:
        print("[-] Missing required environment variables (GITHUB_TOKEN, PR_NUMBER, REPO, RUN_ID). Exiting.")
        sys.exit(0)

    print(f"[*] Aggregating reports for PR #{pr_number} in {repo} (Run #{run_id})...")

    # Fetch jobs for this run
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    jobs_data = github_api_request(jobs_url, token)
    jobs = jobs_data.get("jobs", []) if jobs_data else []

    # Parse reports
    size_reports, test_reports, crash_reports = find_reports(args.artifacts_dir)
    print(f"[*] Found {len(size_reports)} size reports, {len(test_reports)} test reports, {len(crash_reports)} crash reports.")

    comment_body = build_pr_comment(repo, run_id, commit_sha, jobs, size_reports, test_reports, crash_reports)
    post_or_update_pr_comment(repo, pr_number, token, comment_body)

if __name__ == "__main__":
    main()
