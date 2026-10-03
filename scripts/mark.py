#!/usr/bin/env python3
"""Record what happened to a subagent's output.

Usage: mark.py --session SESSION_ID AGENT_ID OUTCOME

OUTCOME is one of:
  redone          the result was discarded and the task done again
  review-failed   a review found a serious problem in the result
  user-rejected   the user corrected or reverted the result

Appends one line to the project's spawn log. No model calls, no network.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_router import SCHEMA_VERSION, log, project  # noqa: E402
from agent_router import config as config_module  # noqa: E402
from agent_router.outcomes import MARK_OUTCOMES  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mark.py", description=__doc__.splitlines()[0])
    parser.add_argument("--session", required=True)
    parser.add_argument("--root", help="project root (default: found from the current directory)")
    parser.add_argument("agent_id")
    parser.add_argument("outcome", choices=MARK_OUTCOMES)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", args.agent_id):
        parser.error("AGENT_ID must be the id from the agent's result")

    root = args.root or project.find_root(os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR"))
    config, _ = config_module.load_or_defaults(root)
    if not config.log_enabled:
        print("agent-router: logging is off for this project; nothing recorded")
        return 0
    record = {
        "v": SCHEMA_VERSION,
        "kind": "mark",
        "ts": log.now(),
        "session": args.session,
        "agent_id": args.agent_id,
        "outcome": args.outcome,
    }
    log.append(log.log_path(root, args.session), record)
    print(f"agent-router: recorded {args.outcome} for {args.agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
