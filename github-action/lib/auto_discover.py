#!/usr/bin/env python3
"""
CalSol Hardware Testbench: Subsystem Auto-Discovery & Change Resolver
Detects all firmware subsystems in a repository, resolves their designated
hardware testbench.json configurations, and filters by git changes.
"""

import os
import sys
import json
import glob
import subprocess
import argparse

def get_git_diff_files(repo_root):
    """
    Determine files changed in the current commit or pull request.
    Returns list of modified file paths relative to repo root, or None if undetermined.
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    
    # Check if a custom changed files list was passed via env
    if os.environ.get("FILTER_CHANGES"):
        try:
            return json.loads(os.environ["FILTER_CHANGES"])
        except Exception:
            pass

    # Try Git diff
    try:
        # Check if running in GitHub Actions PR
        base_ref = os.environ.get("GITHUB_BASE_REF")
        if base_ref:
            # PR against target branch
            cmd = ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"]
            res = subprocess.run(cmd, cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            files = [line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()]
            return files

        # Check commit range
        cmd = ["git", "diff", "--name-only", "HEAD~1", "HEAD"]
        res = subprocess.run(cmd, cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        files = [line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()]
        return files
    except Exception as e:
        print(f"[-] Note: Could not determine git diff automatically ({e}). Falling back to full scan.")
        return None

def find_all_subsystems(repo_root):
    """
    Scans the repository to locate all testable subsystems.
    Identified by:
      1. Presence of testbench.json
      2. Presence of a test/CMakeLists.txt subdirectory
    """
    subsystems = {}

    # 1. Look for testbench.json
    for tb in glob.glob(os.path.join(repo_root, "**/testbench.json"), recursive=True):
        rel = os.path.relpath(tb, repo_root).replace("\\", "/")
        # Ignore files inside hidden or build directories
        if any(part.startswith(".") or part in ["build", "managed_components"] for part in rel.split("/")):
            continue
        folder = rel.split("/")[0]
        subsystems[folder] = tb

    # 2. Look for */test/CMakeLists.txt
    for cm in glob.glob(os.path.join(repo_root, "**/test/CMakeLists.txt"), recursive=True):
        rel = os.path.relpath(cm, repo_root).replace("\\", "/")
        if any(part.startswith(".") or part in ["build", "managed_components"] for part in rel.split("/")):
            continue
        parts = rel.split("/")
        if len(parts) >= 3 and parts[-2] == "test":
            folder = parts[0]
            if folder not in subsystems:
                subsystems[folder] = None

    # 3. Look for single root project test/CMakeLists.txt
    if os.path.isfile(os.path.join(repo_root, "test", "CMakeLists.txt")) and not subsystems:
        subsystems["test"] = None

    return subsystems

def load_subsystem_config(repo_root, folder, config_path, port_override=None):
    """
    Loads testbench.json configuration or infers sensible defaults.
    """
    cfg = {}
    resolved_cfg_file = None

    if config_path and os.path.isfile(config_path):
        resolved_cfg_file = config_path
    else:
        candidates = [
            os.path.join(repo_root, folder, "testbench.json"),
            os.path.join(repo_root, folder, "test", "testbench.json"),
            os.path.join(repo_root, "testbench.json")
        ]
        for c in candidates:
            if os.path.isfile(c):
                resolved_cfg_file = c
                break

    if resolved_cfg_file:
        try:
            with open(resolved_cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[-] Warning: Error parsing {resolved_cfg_file}: {e}")

    # Resolve target directory
    default_target = f"{folder}/test" if os.path.isdir(os.path.join(repo_root, folder, "test")) else folder
    target = cfg.get("target", default_target).replace("\\", "/")
    name = cfg.get("name", folder)
    port = port_override if port_override else cfg.get("port", "")
    baud = cfg.get("baud", 921600)
    timeout = cfg.get("timeout", 12)
    desc = cfg.get("description", "")

    return {
        "name": name,
        "folder": folder,
        "target": target,
        "port": port,
        "baud": baud,
        "timeout": timeout,
        "description": desc,
        "config_found": bool(resolved_cfg_file)
    }

def main():
    parser = argparse.ArgumentParser(description="CalSol Subsystem Auto-Discovery & Change Resolver")
    parser.add_argument("--repo-root", default=".", help="Root of the repository to inspect")
    parser.add_argument("--target", default="auto", help="Target subsystem ('auto', 'all', or specific path)")
    parser.add_argument("--port", default="", help="Serial port override")
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    target_mode = os.environ.get("INPUT_TARGET", args.target).strip()
    port_override = os.environ.get("PORT_OVERRIDE", args.port).strip()

    if not target_mode:
        target_mode = "auto"

    print(f"[*] CalSol Auto-Discovery Engine running in: {repo_root}")
    print(f"[*] Target mode: {target_mode}")

    # Discover all candidate subsystems in repo
    all_subsystems = find_all_subsystems(repo_root)
    print(f"[*] Discovered {len(all_subsystems)} total subsystems: {list(all_subsystems.keys())}")

    active_subsystems = []
    skipped_subsystems = []

    if target_mode in ["all", ""]:
        # Run all discovered subsystems
        for folder, cfg_file in all_subsystems.items():
            cfg = load_subsystem_config(repo_root, folder, cfg_file, port_override)
            active_subsystems.append(cfg)
    elif target_mode != "auto":
        # Specific target requested by user/workflow input
        matched = False
        for folder, cfg_file in all_subsystems.items():
            cfg = load_subsystem_config(repo_root, folder, cfg_file, port_override)
            if target_mode in [folder, cfg["target"], f"{folder}/test"]:
                active_subsystems.append(cfg)
                matched = True
        if not matched:
            # Custom unlisted target path
            active_subsystems.append({
                "name": os.path.basename(target_mode.rstrip("/")),
                "folder": target_mode.split("/")[0],
                "target": target_mode,
                "port": port_override,
                "baud": 921600,
                "timeout": 12,
                "description": "Manual target",
                "config_found": False
            })
    else:
        # Automatic change detection
        changed_files = get_git_diff_files(repo_root)
        if changed_files is None:
            # If diff could not be computed, run all
            print("[*] Running all subsystems as git diff was inconclusive.")
            for folder, cfg_file in all_subsystems.items():
                active_subsystems.append(load_subsystem_config(repo_root, folder, cfg_file, port_override))
        else:
            # Check for shared changes that affect all subsystems
            shared_triggers = ["components/", "lib/", "common/", ".github/", "CMakeLists.txt"]
            has_shared_change = any(any(f.startswith(trig) or f == trig for trig in shared_triggers) for f in changed_files)
            
            # Exclude purely documentation changes (.md files) from triggering all
            code_changes = [f for f in changed_files if not f.endswith(".md") and not f.startswith(".")]

            if not code_changes and not has_shared_change:
                print("[*] Only non-code/documentation changes detected. No hardware tests required.")
            elif has_shared_change:
                print("[*] Changes detected in shared components or core workflows. Scheduling all subsystems.")
                for folder, cfg_file in all_subsystems.items():
                    active_subsystems.append(load_subsystem_config(repo_root, folder, cfg_file, port_override))
            else:
                for folder, cfg_file in all_subsystems.items():
                    cfg = load_subsystem_config(repo_root, folder, cfg_file, port_override)
                    # Check if any changed file belongs to this subsystem folder
                    folder_prefix = f"{folder}/"
                    folder_touched = any(f.startswith(folder_prefix) for f in code_changes)
                    if folder_touched:
                        active_subsystems.append(cfg)
                    else:
                        skipped_subsystems.append(cfg)

    has_changes = "true" if len(active_subsystems) > 0 else "false"
    matrix_json = json.dumps(active_subsystems)

    print("\n================ Detection Summary ================")
    print(f" Active Targets:  {len(active_subsystems)}")
    for item in active_subsystems:
        print(f"  - {item['name']:<15} -> Target: {item['target']:<20} Port: {item['port'] or 'auto'}")
    print(f" Skipped Targets: {len(skipped_subsystems)}")
    print(f" has_changes:     {has_changes}")
    print("===================================================\n")

    # Output to GitHub Actions environment
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"matrix={matrix_json}\n")
            f.write(f"has_changes={has_changes}\n")
            f.write(f"count={len(active_subsystems)}\n")

    # Output to GitHub Actions Step Summary
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as f:
            f.write("### 🔍 CalSol Testbench Subsystem Discovery\n\n")
            if active_subsystems:
                f.write("| Subsystem | Target Directory | Assigned Board | Timeout | Status |\n")
                f.write("| :--- | :--- | :--- | :---: | :---: |\n")
                for s in active_subsystems:
                    port_disp = f"`{s['port']}`" if s['port'] else "*auto-detect*"
                    f.write(f"| **{s['name']}** | `{s['target']}` | {port_disp} | {s['timeout']}s | 🚀 **Scheduled** |\n")
                for s in skipped_subsystems:
                    port_disp = f"`{s['port']}`" if s['port'] else "*auto-detect*"
                    f.write(f"| {s['name']} | `{s['target']}` | {port_disp} | {s['timeout']}s | ⏭️ *Skipped (Unchanged)* |\n")
            else:
                f.write("ℹ️ *No modified firmware subsystems detected. Hardware tests skipped.*\n")
            f.write("\n")

if __name__ == "__main__":
    main()
