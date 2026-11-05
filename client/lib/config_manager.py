"""
CalSol Testbench Configuration Manager
"""

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "host": "stolerpi",
    "remote_user": os.getenv("USER", os.getenv("USERNAME", "developer")),
    "staging_dir": "~/calsol/staging",
    "server_bin_dir": "~/CAN_TestBench/server",
    "default_board": "steering",
    "baud_rate": 921600
}


def load_config(config_path: Path = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config.json"

    cfg = DEFAULT_CONFIG.copy()

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                # Ignore placeholder strings starting with '<'
                valid_entries = {k: v for k, v in user_cfg.items() if not str(v).startswith("<")}
                cfg.update(valid_entries)
        except Exception:
            pass

    return cfg
