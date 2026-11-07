"""Persist an actual infrastructure failure without inventing test assertions."""
import json
from pathlib import Path
import sys

destination, run_id, subsystem, phase, code = sys.argv[1:]
Path(destination).write_text(json.dumps(dict(run_id=run_id, subsystem=subsystem,
    passed=False, status=phase, exit_code=int(code), summary=f'{phase}: exit {code}',
    total_assertions=0, passed_count=0, failed_count=0, tests=[], can_traffic=[]), indent=2))
