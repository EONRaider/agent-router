#!/usr/bin/env python3
"""Command line for agent-router's skills.

Usage: router.py <command> [--root DIR]

Commands:
  init    opt the project in: write the overlay and supporting files
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_router import project, setup  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="router.py", description="agent-router commands")
    parser.add_argument("command", choices=["init"])
    parser.add_argument("--root", help="project root (default: found from the current directory)")
    args = parser.parse_args(argv)
    root = args.root or project.find_root(os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR"))

    if args.command == "init":
        print(f"agent-router: project root is {root}")
        for line in setup.init(root):
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
