"""Finding the project a session belongs to, and a small per-session cache."""

import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

from . import OVERLAY_RELPATH, PROJECT_AGENT_PREFIX

SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


def safe_id(value):
    """A hook-supplied id made safe to use as a file name."""
    return SAFE_ID.sub("_", str(value or "unknown"))[:120]


def find_root(start, fallback=None):
    """The project root for a session that started in `start`.

    The nearest ancestor holding an overlay wins, then the nearest holding `.git`, then
    `fallback` (the directory Claude Code reports as the project), then `start` itself.
    """
    start = Path(start).resolve()
    candidates = [start, *start.parents]
    for directory in candidates:
        if (directory / OVERLAY_RELPATH).is_file():
            return directory
    for directory in candidates:
        if (directory / ".git").exists():
            return directory
    return Path(fallback).resolve() if fallback else start


def cache_dir(payload, env=None):
    """A directory private to this session, shared by every hook process in it."""
    env = os.environ if env is None else env
    session = safe_id(payload.get("session_id"))
    scratchpad = payload.get("scratchpad_dir")
    if scratchpad and Path(scratchpad).parent.is_dir():
        base = Path(scratchpad) / "agent-router"
    elif env.get("CLAUDE_PLUGIN_DATA"):
        base = Path(env["CLAUDE_PLUGIN_DATA"]) / "sessions" / session
    else:
        base = Path(tempfile.gettempdir()) / f"agent-router-{os.getuid()}" / session
    base.mkdir(parents=True, exist_ok=True)
    return base


def project_agents(root):
    """Names of the generated project agents present on disk."""
    directory = Path(root) / ".claude" / "agents"
    return sorted(path.stem for path in directory.glob(f"{PROJECT_AGENT_PREFIX}*.md"))


def session_state(payload, env=None, refresh=False):
    """The project root and the project agents this session can load.

    Resolved once, at session start, and then read from the cache: later `cwd` changes do not
    move the root, and an agent file created mid-session is not counted, because Claude Code
    cannot load it until the next session.
    """
    env = os.environ if env is None else env
    cache = cache_dir(payload, env) / "session.json"
    if not refresh:
        try:
            state = json.loads(cache.read_text(encoding="utf-8"))
            return {"root": Path(state["root"]), "agents": set(state["agents"])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    start = payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    root = find_root(start, env.get("CLAUDE_PROJECT_DIR"))
    agents = project_agents(root)
    with contextlib.suppress(OSError):
        cache.write_text(json.dumps({"root": str(root), "agents": agents}), encoding="utf-8")
    return {"root": root, "agents": set(agents)}


def session_root(payload, env=None):
    """The project root for this session."""
    return session_state(payload, env)["root"]


def claim(payload, key, env=None):
    """True for the first process in this session to claim `key`, False for any later one.

    A project can have both the plugin's hooks and a vendored copy registered. Whichever
    runs first handles the event; the other sees the marker and does nothing.
    """
    marker = cache_dir(payload, env) / f"claim-{safe_id(key)}"
    try:
        os.close(os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    except OSError:
        return True
    return True
