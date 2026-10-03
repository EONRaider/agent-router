#!/usr/bin/env python3
"""Hook entry point for agent-router.

Usage: hook.py <event>, with the hook payload as JSON on stdin.

This script makes no model calls and no network calls, and it fails open: whatever goes
wrong, it exits 0 without blocking the session.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv, stdin, stdout, env):
    from agent_router.events import HANDLERS

    handler = HANDLERS.get(argv[1] if len(argv) > 1 else "")
    if handler is None:
        return
    result = handler(json.load(stdin), env)
    if not result:
        return
    if result.get("stdout"):
        stdout.write(result["stdout"] + "\n")
    if result.get("json"):
        stdout.write(json.dumps(result["json"]))


if __name__ == "__main__":
    try:
        main(sys.argv, sys.stdin, sys.stdout, os.environ)
    except Exception as error:  # noqa: BLE001 - a plugin bug must never block a session
        sys.stderr.write(f"agent-router: hook error ignored: {error!r}\n")
    sys.exit(0)
