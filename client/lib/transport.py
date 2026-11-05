"""
Remote SSH & SCP Transport Helpers for CalSol Testbench
"""

import subprocess
import sys


def run_ssh(host: str, remote_cmd: str, pty: bool = False, check: bool = True) -> int:
    cmd = ["ssh"]
    if pty:
        cmd.append("-t")
    cmd.extend([host, remote_cmd])

    res = subprocess.run(cmd)
    if check and res.returncode != 0:
        sys.exit(res.returncode)
    return res.returncode


def copy_file_to_host(local_path: str, host: str, remote_path: str) -> None:
    # Ensure remote directory exists
    remote_dir = "/".join(remote_path.split("/")[:-1])
    subprocess.run(["ssh", host, f"mkdir -p {remote_dir}"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # SCP the file
    res = subprocess.run(["scp", str(local_path), f"{host}:{remote_path}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"[-] SCP transfer failed:\n{res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
