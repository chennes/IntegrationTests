#!/usr/bin/env python3
"""
TestPR.py

Checks out a FreeCAD pull request into a git worktree, builds it with pixi,
and runs the integration test suite against the resulting binary.

Usage:
  python Scripts/TestPR.py 29046
  python Scripts/TestPR.py 29046 --config debug --skip-build
  python Scripts/TestPR.py 29046 --filename PD_Cube.FCStd

Requires: gh (GitHub CLI), git, pixi
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

FREECAD_REPO = Path("G:/FreeCAD/FreeCAD")
WORKTREE_ROOT = FREECAD_REPO / "worktrees"
INTEGRATION_TESTS = Path("G:/FreeCAD/IntegrationTests")


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, streaming output unless capture is True."""
    merged_env = None
    if env:
        merged_env = {**os.environ, **env}
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture,
        text=True,
        env=merged_env,
    )


def get_pr_info(pr_number: int) -> dict[str, str]:
    """Use gh to get PR metadata."""
    result = run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            "FreeCAD/FreeCAD",
            "--json",
            "headRefName,headRepositoryOwner,title,state",
        ],
        capture=True,
    )
    data = json.loads(result.stdout)
    return {
        "branch": data["headRefName"],
        "owner": data["headRepositoryOwner"]["login"],
        "title": data["title"],
        "state": data["state"],
    }


def ensure_remote(owner: str) -> str:
    """Ensure a git remote exists for the PR author's fork. Returns remote name."""
    result = run(
        ["git", "remote"],
        cwd=FREECAD_REPO,
        capture=True,
    )
    remotes = result.stdout.strip().split("\n")

    if owner == "FreeCAD":
        remote = "origin"
    elif owner in remotes:
        remote = owner
    else:
        # Try both SSH and HTTPS patterns
        url = f"git@github.com:{owner}/FreeCAD"
        print(f"Adding remote '{owner}' -> {url}")
        run(["git", "remote", "add", owner, url], cwd=FREECAD_REPO)
        remote = owner

    print(f"Fetching from remote '{remote}'...")
    run(["git", "fetch", remote], cwd=FREECAD_REPO)
    return remote


def setup_worktree(pr_number: int, remote: str, branch: str) -> Path:
    """Create or reuse a worktree for the PR.

    The worktree gets a local branch ``pr-<number>`` that tracks the remote branch,
    so ``git pull`` and ``git log`` work naturally inside it.
    """
    worktree_path = WORKTREE_ROOT / f"pr-{pr_number}"
    local_branch = f"pr-{pr_number}"
    remote_ref = f"{remote}/{branch}"

    if worktree_path.exists():
        print(f"Worktree already exists at {worktree_path}")
        print("Updating to latest...")
        run(["git", "fetch", remote, branch], cwd=worktree_path)
        run(
            ["git", "checkout", "-B", local_branch, "--track", remote_ref],
            cwd=worktree_path,
        )
        run(["git", "submodule", "update", "--init", "--recursive"], cwd=worktree_path)
        return worktree_path

    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Creating worktree at {worktree_path} for {remote_ref}")
    run(
        ["git", "worktree", "add", "-B", local_branch, str(worktree_path), remote_ref],
        cwd=FREECAD_REPO,
    )
    run(["git", "submodule", "update", "--init", "--recursive"], cwd=worktree_path)
    return worktree_path


def find_freecad_cmd(worktree: Path, config: str) -> Path:
    """Locate the FreeCADCmd binary in a build tree."""
    # On Windows, binary is directly in build/<config>/bin/
    freecad_cmd = worktree / "build" / config / "bin" / "FreeCADCmd.exe"
    if not freecad_cmd.exists():
        # Fallback: try without .exe (Linux/macOS)
        freecad_cmd = worktree / "build" / config / "bin" / "FreeCADCmd"
    if not freecad_cmd.exists():
        print(f"ERROR: FreeCADCmd not found at expected path: {freecad_cmd}")
        print("Searching build directory...")
        for p in (worktree / "build").rglob("FreeCADCmd*"):
            print(f"  Found: {p}")
        sys.exit(3)
    return freecad_cmd


def build_freecad(worktree: Path, config: str) -> Path:
    """Configure and build FreeCAD using pixi. Returns path to FreeCADCmd."""
    print(f"\n{'='*60}")
    print(f"Building FreeCAD ({config}) in {worktree}")
    print(f"{'='*60}\n")

    # pixi needs to be run from the worktree where pixi.toml lives
    run(["pixi", "run", f"configure-{config}"], cwd=worktree)
    run(["pixi", "run", f"build-{config}"], cwd=worktree)

    freecad_cmd = find_freecad_cmd(worktree, config)
    print(f"\nFreeCADCmd found at: {freecad_cmd}")
    return freecad_cmd


def run_tests(
    freecad_cmd: Path,
    worktree: Path,
    *,
    filename: str | None = None,
    strict: bool = False,
) -> int:
    """Run the integration test suite via pixi so FreeCADCmd finds its libraries.

    Returns the exit code.
    """
    print(f"\n{'='*60}")
    print("Running integration tests")
    print(f"{'='*60}\n")

    # Run via 'pixi run' so FreeCADCmd inherits the pixi conda environment
    # (DLLs, Python paths, etc.).  We invoke python directly rather than going
    # through 'bash -c' so that pixi faithfully forwards the exit code.
    cmd = [
        "pixi",
        "run",
        sys.executable,
        str(INTEGRATION_TESTS / "Scripts" / "RunIntegrationTests.py"),
        "--freecad",
        str(freecad_cmd),
        "--script",
        str(INTEGRATION_TESTS / "Scripts" / "EvaluateFile.FCMacro"),
        "--fcstd-dir",
        str(INTEGRATION_TESTS / "Data" / "CADFiles"),
        "--baseline-dir",
        str(INTEGRATION_TESTS / "Data" / "BaselineResults"),
        "--exceptions-dir",
        str(INTEGRATION_TESTS / "Data" / "Exceptions"),
        "--known-failures-dir",
        str(INTEGRATION_TESTS / "Data" / "KnownFailures"),
        "--verbose",
    ]
    if filename:
        cmd.extend(["--filename", filename])
    if strict:
        cmd.append("--strict")

    result = run(cmd, cwd=worktree, check=False)
    return result.returncode


def remove_worktree(pr_number: int) -> None:
    """Remove the worktree for a PR."""
    worktree_path = WORKTREE_ROOT / f"pr-{pr_number}"
    if worktree_path.exists():
        print(f"Removing worktree at {worktree_path}")
        run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=FREECAD_REPO)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test a FreeCAD PR against the integration test suite.",
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="GitHub PR number to test (from FreeCAD/FreeCAD).",
    )
    parser.add_argument(
        "--config",
        choices=["release", "debug"],
        default="release",
        help="Build configuration (default: release).",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip build step (reuse existing build in worktree).",
    )
    parser.add_argument(
        "--filename",
        help="Test only a single .FCStd file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Ignore all exceptions and known failures.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove the worktree after testing.",
    )
    args = parser.parse_args()

    # Step 1: Get PR info
    print(f"Fetching info for PR #{args.pr_number}...")
    pr_info = get_pr_info(args.pr_number)
    print(f"  Title:  {pr_info['title']}")
    print(f"  Branch: {pr_info['owner']}/{pr_info['branch']}")
    print(f"  State:  {pr_info['state']}")

    # Step 2: Ensure remote and fetch
    remote = ensure_remote(pr_info["owner"])

    # Step 3: Set up worktree
    worktree = setup_worktree(args.pr_number, remote, pr_info["branch"])

    # Step 4: Build
    if args.skip_build:
        freecad_cmd = find_freecad_cmd(worktree, args.config)
    else:
        freecad_cmd = build_freecad(worktree, args.config)

    # Step 5: Run tests
    exit_code = run_tests(freecad_cmd, worktree, filename=args.filename, strict=args.strict)

    # Step 6: Report
    print(f"\n{'='*60}")
    if exit_code == 0:
        print(f"PR #{args.pr_number}: ALL TESTS PASSED")
    elif exit_code == 2:
        print(f"PR #{args.pr_number}: MISMATCHES DETECTED")
    else:
        print(f"PR #{args.pr_number}: ERRORS OCCURRED (exit code {exit_code})")
    print(f"{'='*60}")

    # Step 7: Cleanup if requested
    if args.cleanup:
        remove_worktree(args.pr_number)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
