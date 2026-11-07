#!/usr/bin/env python3
"""
CalSol Hardware Testbench: Subsystem Auto-Discovery & Change Resolver
Detects all firmware subsystems in a repository that explicitly contain a
testbench.json configuration, resolves their hardware settings, and filters
by git changes. Subsystems without testbench.json are NOT scheduled for testing.
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
    Scans the repository to locate all testable subsystems with pruned tree traversal.
    A subsystem is ONLY discovered if it explicitly contains a testbench.json file.
    Folders without testbench.json (even if they contain CMakeLists.txt) are excluded.
    """
    subsystems = {}
    ignored_dirs = {".git", "build", "managed_components", ".logs", "pr_artifacts", ".system_generated"}

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        if "testbench.json" in files:
            tb = os.path.join(root, "testbench.json")
            rel = os.path.relpath(tb, repo_root).replace("\\", "/")
            parts = rel.split("/")
            if len(parts) == 1:
                subsystems["root"] = tb
            else:
                subsystems[parts[0]] = tb

    return subsystems

def load_subsystem_config(repo_root, folder, config_path, port_override=None):
    """
    Loads testbench.json configuration for a subsystem.
    """
    cfg = {}
    resolved_cfg_file = config_path

    if resolved_cfg_file and os.path.isfile(resolved_cfg_file):
        try:
            with open(resolved_cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[-] Warning: Error parsing {resolved_cfg_file}: {e}")

    # Determine default target directory
    if folder == "root":
        default_target = "test" if os.path.isdir(os.path.join(repo_root, "test")) else "."
        name = cfg.get("name", os.path.basename(repo_root))
    else:
        default_target = f"{folder}/test" if os.path.isdir(os.path.join(repo_root, folder, "test")) else folder
        name = cfg.get("name", folder)

    target = cfg.get("target", default_target).replace("\\", "/")
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
    parser = argparse.ArgumentParser(description="CalSol Subsystem Auto-Discovery (Requires testbench.json)")
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
    print("[*] Filtering policy: Only subsystems with testbench.json are scheduled.")

    # Discover all candidate subsystems with testbench.json in repo
    all_subsystems = find_all_subsystems(repo_root)
    print(f"[*] Discovered {len(all_subsystems)} subsystems with testbench.json: {list(all_subsystems.keys())}")

    active_subsystems = []
    skipped_subsystems = []

    if target_mode in ["all", ""]:
        # Run all discovered subsystems that contain testbench.json
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
            # Check if specified target explicitly contains a testbench.json
            candidate_tb = os.path.join(repo_root, target_mode, "testbench.json")
            if not os.path.isfile(candidate_tb):
                candidate_tb = os.path.join(repo_root, os.path.dirname(target_mode), "testbench.json")
            if os.path.isfile(candidate_tb):
                cfg = load_subsystem_config(repo_root, target_mode.split("/")[0], candidate_tb, port_override)
                active_subsystems.append(cfg)
            else:
                print(f"[-] Target '{target_mode}' was requested but lacks a testbench.json. Skipping.")
    else:
        # Automatic change detection
        changed_files = get_git_diff_files(repo_root)
        if changed_files is None:
            # If diff could not be computed, run all subsystems that have testbench.json
            print("[*] Running all configured subsystems as git diff was inconclusive.")
            for folder, cfg_file in all_subsystems.items():
                active_subsystems.append(load_subsystem_config(repo_root, folder, cfg_file, port_override))
        else:
            # Check for shared changes that affect all subsystems
            shared_triggers = ["components/", "lib/", "common/", ".github/", "github-action/", "CMakeLists.txt"]
            has_shared_change = any(any(f.startswith(trig) or f == trig for trig in shared_triggers) for f in changed_files)
            
            # Exclude purely documentation changes (.md files) from triggering all
            code_changes = [f for f in changed_files if not f.endswith(".md") and not f.startswith(".") and not f.startswith("web/") and not f.startswith("docs/")]

            if not code_changes and not has_shared_change:
                print("[*] Only non-code/documentation changes detected. No hardware tests required.")
            elif has_shared_change:
                print("[*] Changes detected in shared components or core workflows. Scheduling all configured subsystems.")
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

    # Output to GitHub Actions Step Summary disabled to keep summary dedicated to unit tests

if __name__ == "__main__":
    main()
