"""Opting a project in: the files `/agent-router:init` creates."""

import json
from pathlib import Path

from . import OVERLAY_RELPATH, STATE_RELPATH

STARTER_OVERLAY = {
    "version": 1,
    "strict": False,
    "locked": [],
    "log": {"enabled": True, "summary": True},
}
GITATTRIBUTES_LINES = (f"{STATE_RELPATH}/log/** linguist-generated",)


def ensure_gitattributes(root, lines=GITATTRIBUTES_LINES):
    """Add the lines that collapse generated files in diffs. Returns the lines added."""
    path = Path(root) / ".gitattributes"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    missing = [line for line in lines if line not in existing.splitlines()]
    if missing:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        path.write_text(existing + separator + "\n".join(missing) + "\n", encoding="utf-8")
    return missing


def init(root):
    """Create the overlay and supporting files. Never overwrites an existing overlay."""
    root = Path(root)
    done = []
    overlay = root / OVERLAY_RELPATH
    if overlay.exists():
        done.append(f"kept existing {OVERLAY_RELPATH}")
    else:
        overlay.parent.mkdir(parents=True, exist_ok=True)
        overlay.write_text(json.dumps(STARTER_OVERLAY, indent=2) + "\n", encoding="utf-8")
        done.append(f"created {OVERLAY_RELPATH}")
    # Claude Code only notices agents in a directory that existed when the session started.
    agents = root / ".claude" / "agents"
    if not agents.is_dir():
        agents.mkdir(parents=True)
        done.append("created .claude/agents/")
    (root / STATE_RELPATH / "log").mkdir(parents=True, exist_ok=True)
    for line in ensure_gitattributes(root):
        done.append(f"added to .gitattributes: {line}")
    return done
