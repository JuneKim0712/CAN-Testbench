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

    # Determine overall status
    static_job = next((j for j in jobs if "static-analysis" in j.get("name", "").lower() or "lint" in j.get("name", "").lower()), None)
    static_ok = (static_job.get("conclusion") == "success") if static_job else True
    
    hw_jobs = [j for j in jobs if j.get("name", "").startswith("Test ")]
    hw_all_passed = not any(j.get("conclusion") == "failure" for j in hw_jobs)

    total_tests_run = 0
    total_tests_passed = 0
    all_tests_flat = []

    for tr in test_reports:
        if not tr.get("passed", False):
            hw_all_passed = False
        total_tests_run += tr.get("total_assertions", 0)
        total_tests_passed += tr.get("passed_count", 0)
        sub_name = tr.get("subsystem", "ECU")
        for t in tr.get("tests", []):
            t_copy = dict(t)
            t_copy["subsystem"] = sub_name
            all_tests_flat.append(t_copy)

    has_crashes = any(cr.get("has_crashed") for cr in crash_reports)
    overall_success = static_ok and hw_all_passed and not has_crashes and (total_tests_run > 0)

    # Web Portal Links
    owner = repo.split('/')[0] if repo and '/' in repo else "JuneKim0712"
    repo_name = repo.split('/')[1] if repo and '/' in repo else "CAN-Testbench"
    web_portal_url = f"https://{owner}.github.io/{repo_name}/?run={run_id}" if run_id else f"https://{owner}.github.io/{repo_name}/"
    commit_url = f"https://github.com/{repo}/commit/{commit_sha}" if repo and commit_sha else ""

    md = []
    md.append(IDENTIFIER_TAG)

    # 1. Executive Unit Tests Header
    status_str = "PASSED" if overall_success else "FAILED"
    status_badge = "✅ Passed" if overall_success else "❌ Failed"
    md.append(f"## CalSol Hardware Unit Tests: {status_str} ({total_tests_passed} / {total_tests_run} Passed)\n")
    md.append(f"> 🌐 **Interactive Telemetry & Waveform Portal:** [{web_portal_url}]({web_portal_url})\n")
    md.append(f"> **Status:** {status_badge} | **Action Run:** [`#{run_id}`]({run_url}) | **Commit:** [`{short_sha}`]({commit_url}) | **Target:** `stolerpi (ARM64 HIL)`\n")

    # 2. Dedicated Unit Test Assertions Breakdown Table
    md.append("### Unit Test Assertions Breakdown\n")
    if all_tests_flat:
        md.append("| Status | Subsystem | Test Function | Location | Diagnostic Summary |")
        md.append("| :---: | :---: | :--- | :--- | :--- |")
        for t in all_tests_flat:
            st = t.get("status", "PASS")
            icon = "PASS" if st == "PASS" else "FAIL"
            loc = f"{t.get('file', '')}:{t.get('line', '')}" if t.get('file') else "—"
            details = t.get("details", "")
            md.append(f"| `{icon}` | `{t.get('subsystem', '')}` | `{t.get('name', '')}` | `{loc}` | `{details}` |")
        md.append("")
    else:
        md.append("*No unit test assertions recorded.*\n\n")

    # 3. Post-Mortem Diagnostics (Rendered only on test failures or crashes)
    failed_tests = [t for t in all_tests_flat if t.get("status") == "FAIL"]
    crashed_reports = [cr for cr in crash_reports if cr.get("has_crashed")]
    failed_build_jobs = [j.get("name", "") for j in hw_jobs if j.get("conclusion") == "failure"]

    if failed_tests or crashed_reports or failed_build_jobs or not overall_success:
        md.append("### Failed Unit Test Diagnostics\n")
        if failed_tests:
            md.append("| Subsystem | Failed Test Function | Location | Failure Details |")
            md.append("| :--- | :--- | :--- | :--- |")
            for t in failed_tests:
                loc = f"{t.get('file', '')}:{t.get('line', '')}" if t.get('file') else "—"
                md.append(f"| `{t.get('subsystem', '')}` | `{t.get('name')}` | `{loc}` | `{t.get('details')}` |")
            md.append("")
            first_sub = failed_tests[0].get('subsystem', 'pedals_fw')
            md.append(f"> **Local Bench Reproduction Command:**\n> ```bash\n> ./github-action/cal-test.sh {first_sub}/test /dev/esp32_johnathan\n> ```\n")

        if failed_build_jobs:
            md.append("#### Build & Silicon Flashing Errors\n")
            for jn in failed_build_jobs:
                md.append(f"> **`{jn}`** failed prior to test completion (compilation or flashing failure). Check step logs.\n")
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

    md.append("---\n*CalSol Hardware Testbench*")
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
