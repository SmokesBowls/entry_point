#!/usr/bin/env python3
"""
scan.py -- Read-only repository analysis

Generates reports/usage_index.json and reports/report_viewer.html.
This script NEVER imports or loads pruning/quarantine modules.
Safe to run on any codebase, any time, with zero side effects.

Usage:
    python3 scan.py /path/to/repo
    python3 scan.py /path/to/repo --target engine --k 5
    python3 scan.py /path/to/repo --no-trace --surfaces all
"""
import sys
import os

if os.environ.get("__RIE_TRACING__"):
    sys.exit(0)

from pathlib import Path
from main import build_arg_parser, run_scan


def main():
    parser = build_arg_parser(include_surgery=False)
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: Path {repo_root} does not exist.")
        return 1

    run_scan(repo_root, args)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
