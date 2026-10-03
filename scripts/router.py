#!/usr/bin/env python3
"""Command line for agent-router's skills.

Usage: router.py <command> [--root DIR]

Commands:
  init    opt the project in: write the overlay and supporting files
  sync    write .claude/agents/router-<tier>.md for tiers the overlay resizes or adds
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_router import config as config_module  # noqa: E402
from agent_router import project, setup, sync  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="router.py", description="agent-router commands")
    parser.add_argument("command", choices=["init", "sync"])
    parser.add_argument("--root", help="project root (default: found from the current directory)")
    args = parser.parse_args(argv)
    root = args.root or project.find_root(os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR"))

    if args.command == "init":
        print(f"agent-router: project root is {root}")
        for line in setup.init(root):
            print(f"- {line}")
    elif args.command == "sync":
        try:
            config = config_module.load(root)
        except (config_module.ConfigError, KeyError, TypeError) as error:
            print(f"agent-router: cannot use the overlay: {error}", file=sys.stderr)
            return 1
        changes = sync.sync(root, config, config.tier_descriptions)
        for line in changes or ["project agents already match the overlay"]:
            print(f"- {line}")
        if changes:
            print("New or changed agents load in the next session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
