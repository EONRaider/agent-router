#!/usr/bin/env python3
"""Command line for agent-router's skills.

Usage: router.py <command> [arguments] [--root DIR]

Commands:
  init    opt the project in: write the overlay and supporting files
  sync    write .claude/agents/router-<tier>.md for tiers the overlay resizes or adds
  report  print the project's report and proposals (--json for data, --summaries for
          the task summaries behind overrides and rejections)
  decide  record a decision on a proposal: decide <id> accept|reject
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_router import config as config_module  # noqa: E402
from agent_router import decisions, project, report, setup, sync  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="router.py", description="agent-router commands")
    parser.add_argument("command", choices=["init", "sync", "report", "decide"])
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--json", action="store_true", help="report: print data as JSON")
    parser.add_argument("--summaries", action="store_true", help="report: print task summaries")
    parser.add_argument("--root", help="project root (default: found from the current directory)")
    args = parser.parse_args(argv)
    root = args.root or project.find_root(os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR"))

    if args.command == "init":
        print(f"agent-router: project root is {root}")
        for line in setup.init(root):
            print(f"- {line}")
        return 0

    try:
        config = config_module.load(root)
    except (config_module.ConfigError, KeyError, TypeError) as error:
        print(f"agent-router: cannot use the overlay: {error}", file=sys.stderr)
        return 1
    if not config.initialised:
        print("agent-router: this project has not opted in. Run /agent-router:init first.")
        return 1

    if args.command == "sync":
        changes = sync.sync(root, config, config.tier_descriptions)
        for line in changes or ["project agents already match the overlay"]:
            print(f"- {line}")
        if changes:
            print("New or changed agents load in the next session.")
    elif args.command == "report":
        if args.summaries:
            print(json.dumps(report.summaries(root, config), indent=2))
        elif args.json:
            print(json.dumps(report.build(root, config), indent=2, default=sorted))
        else:
            print(report.render(report.build(root, config), config))
    elif args.command == "decide":
        return decide(root, config, args.arguments)
    return 0


def decide(root, config, arguments):
    """Accept or reject one proposal. Accepting edits the overlay; nothing is committed."""
    if len(arguments) != 2 or arguments[1] not in ("accept", "reject"):
        print("usage: router.py decide <proposal-id> accept|reject", file=sys.stderr)
        return 2
    wanted, choice = arguments
    current = {p["id"]: p for p in report.build(root, config)["proposals"]}
    proposal = current.get(wanted)
    if proposal is None:
        print(f"agent-router: no current proposal with id {wanted}", file=sys.stderr)
        return 1
    if choice == "reject":
        decisions.record_decision(root, proposal, "rejected")
        print(f"Rejected [{wanted}]. It will not return until new evidence meets the threshold.")
        return 0
    if proposal["edit"] is None:
        print(f"[{wanted}] has no automatic edit. {proposal['manual']}")
        return 1
    overlay = decisions.apply_edit(config_module.read_overlay(root), proposal["edit"])
    decisions.write_overlay(root, overlay)
    decisions.record_decision(root, proposal, "accepted")
    print(f"Accepted [{wanted}]: updated .claude/agent-router.json")
    updated = config_module.load(root)
    for line in sync.sync(root, updated, updated.tier_descriptions):
        print(f"- {line}")
    print("Nothing was committed. New or changed agents load in the next session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
