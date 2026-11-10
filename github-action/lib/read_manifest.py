"""Validated manifest values for the shell runner; one value per line."""
import sys
import json
from pathlib import Path
from auto_discover import load_subsystem_config

path = Path(sys.argv[1]).resolve()
data = json.loads(path.read_text())
root = path.parent if (path.parent / data.get('target', 'test') / 'CMakeLists.txt').is_file() else path.parent.parent
folder = 'root' if root == path.parent else path.parent.name
config = load_subsystem_config(str(root), folder, str(path))
for key in ('port', 'timeout', 'baud', 'name'):
    print(config[key])
