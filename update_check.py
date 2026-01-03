#!/usr/bin/env python3
"""
Copyright 2025-2026 CEMAXECUTER LLC.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
"""
Read-only update check for DragonSync.
"""

import os
import subprocess
from pathlib import Path


def update_check():
    repo_hint = os.environ.get("DRAGONSYNC_REPO")
    repo_path = Path(repo_hint).resolve() if repo_hint else Path(__file__).resolve().parent

    def run_git(args, timeout=4):
        return subprocess.run(
            ["git", "-C", str(repo_path)] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    try:
        root_res = run_git(["rev-parse", "--show-toplevel"], timeout=3)
    except Exception as e:
        return {"ok": False, "error": f"git failed: {e}"}
    if root_res.returncode != 0:
        return {"ok": False, "error": "not a git repo"}

    repo_root = root_res.stdout.strip()
    try:
        local_res = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception as e:
        return {"ok": False, "error": f"git failed: {e}"}
    if local_res.returncode != 0:
        return {"ok": False, "error": "local revision unavailable"}
    local_head = local_res.stdout.strip()

    branch_res = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"

    remote_head = None
    remote_error = None
    remote_args = ["ls-remote", "origin", branch] if branch and branch != "HEAD" else ["ls-remote", "origin", "HEAD"]
    try:
        remote_res = subprocess.run(
            ["git", "-C", repo_root] + remote_args,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if remote_res.returncode == 0 and remote_res.stdout:
            remote_head = remote_res.stdout.split()[0]
        else:
            remote_error = remote_res.stderr.strip() or "remote unavailable"
    except Exception as e:
        remote_error = str(e)

    update_available = None
    if remote_head:
        update_available = (remote_head != local_head)

    result = {
        "ok": True,
        "branch": branch,
        "local_head": local_head,
        "remote_head": remote_head,
        "update_available": update_available,
    }
    if remote_error:
        result["remote_error"] = remote_error
    return result
