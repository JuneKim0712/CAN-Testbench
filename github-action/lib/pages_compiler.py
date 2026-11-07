"""Compile only explicitly selected run artifacts into a historical snapshot."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone


def compile_run_record(repo_root, run_id=None, commit_sha=None, artifacts_dir=None):
    root = Path(repo_root)
    run_id = str(run_id or os.environ.get('GITHUB_RUN_ID', 'local'))
    artifacts = Path(artifacts_dir) if artifacts_dir else root / 'pr_artifacts'
    if not artifacts.is_dir():
        raise ValueError('Explicit current-run artifact directory is required')
    destination = root / 'web/data/history.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(destination.read_text()) if destination.exists() else {'runs': []}
    reports = {}
    for path in sorted(artifacts.rglob('*test_results.json')):
        report = json.loads(path.read_text())
        if str(report.get('run_id')) != run_id:
            continue
        name = report.get('subsystem')
        if not name or name in reports:
            raise ValueError(f'Missing or duplicate subsystem result: {path}')
        reports[name] = report
    static = {'status': 'unavailable', 'defects': None}
    for path in artifacts.rglob('static_check.json'):
        item = json.loads(path.read_text())
        if str(item.get('run_id')) == run_id:
            static = item
    new_runs = []
    for name, report in reports.items():
        tests = report.get('tests', [])
        completed = report.get('passed') is True and bool(tests)
        complete_status = completed and static.get('status') == 'passed'
        packets, identities = [], set()
        # Embedded capture is authoritative; JSONL is the lossless archive.
        for event in report.get('can_traffic', []):
            if event.get('source') != 'physical_bus' or event.get('direction', 'rx') != 'rx':
                continue
            identity = (event.get('session_id'), event.get('sequence'))
            if None in identity:
                raise ValueError('Physical event lacks capture identity')
            if identity in identities:
                continue
            identities.add(identity)
            packets.append({**event, 'raw': event.get('raw', event.get('data', '')),
                            't': event['timestamp'] - report.get('started_at', event['timestamp'])})
        failure = None if complete_status else report.get('summary', 'Incomplete verification')
        new_runs.append(dict(
            id=f'{run_id}-{name}', parent_run_id=run_id, subsystem=name, subsystems=[name],
            commit=commit_sha or os.environ.get('GITHUB_SHA', ''),
            branch=os.environ.get('GITHUB_REF_NAME', ''), author=os.environ.get('GITHUB_ACTOR', ''),
            timestamp=datetime.now(timezone.utc).isoformat(), message=report.get('summary', ''),
            status='passed' if complete_status else 'failed',
            failure_type=None if complete_status else ('verification_failure' if not completed else 'static_analysis_unavailable'),
            failure_details=None if complete_status else dict(title='Verification incomplete or failed',
                summary=failure, diff=failure, location=name, repro=f'./github-action/cal-test.sh {name}/test'),
            tests_pass=sum(t.get('status') == 'PASS' for t in tests), tests_total=len(tests), tests=tests,
            duration=f"{report.get('duration', 0)}s", lock_duration_sec=report.get('lock_duration_sec'),
            static_analysis=static, can_packets=packets, capture_error=report.get('capture_error')))
    # Missing reports are an infrastructure failure, never a fake subsystem result.
    if not new_runs:
        raise ValueError('No matching completed run artifacts were found')
    history['runs'] = (new_runs + [r for r in history.get('runs', [])
                                  if str(r.get('parent_run_id')) != run_id])[:50]
    history['generated_at'] = datetime.now(timezone.utc).isoformat()
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(history, indent=2), encoding='utf-8')
    temporary.replace(destination)
    return new_runs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', default='pr_artifacts')
    parser.add_argument('--repo-root', default='.')
    args = parser.parse_args()
    compile_run_record(args.repo_root, artifacts_dir=args.artifacts_dir)
