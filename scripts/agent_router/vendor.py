"""Vendor mode: a copy of the hooks and agents inside the project, for cloud sessions.

Plugins do not load in cloud sessions, but a cloud session does read the repository's
`.claude/settings.json` and `.claude/agents/`. Vendoring puts everything a session needs
there. It is opt-in and writes only under the project's `.claude/` directory.
"""

import json
import shutil
from pathlib import Path

from . import STATE_RELPATH
from .decisions import write_overlay
from .setup import ensure_gitattributes

VENDOR_RELPATH = f"{STATE_RELPATH}/vendor"
HOOK_RELPATH = f"{VENDOR_RELPATH}/hook.py"
SETTINGS_RELPATH = ".claude/settings.json"
GITATTRIBUTES_LINE = f"{VENDOR_RELPATH}/** linguist-generated"

# Event name -> (matcher or None, argument for hook.py)
EVENTS = {
    "SessionStart": ("startup|resume|clear|compact", "session-start"),
    "PreToolUse": ("Agent", "pre"),
    "PostToolUse": ("Agent", "post"),
    "PostToolUseFailure": ("Agent", "post-failure"),
    "SubagentStop": (None, "subagent-stop"),
}


class VendorError(RuntimeError):
    pass


def hook_command(event_argument):
    """The shell command a vendored hook runs.

    It binds everyone who clones the repository, so it does nothing, successfully, when
    python3 or the vendored script is missing.
    """
    return (
        'r=$(git rev-parse --show-toplevel 2>/dev/null) || r="${CLAUDE_PROJECT_DIR:-.}"; '
        f'f="$r/{HOOK_RELPATH}"; '
        '[ -f "$f" ] && command -v python3 >/dev/null 2>&1 && '
        f'exec python3 "$f" {event_argument}; exit 0'
    )


def source_layout():
    """Where the running copy keeps its scripts, agents and version."""
    package = Path(__file__).resolve().parent
    scripts = package.parent
    if (scripts / "VERSION").is_file():  # already a vendored copy
        return scripts, scripts / "agents", (scripts / "VERSION").read_text().strip()
    plugin = scripts.parent
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return scripts, plugin / "agents", manifest["version"]


def running_version():
    try:
        return source_layout()[2]
    except (OSError, ValueError, KeyError):
        return None


def vendored_version(root):
    path = Path(root) / VENDOR_RELPATH / "VERSION"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def copy_scripts(root):
    scripts, agents, version = source_layout()
    target = Path(root) / VENDOR_RELPATH
    if target.resolve() == scripts.resolve():
        raise VendorError("run this from the installed plugin, not from the vendored copy")
    if target.exists():
        shutil.rmtree(target)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    target.mkdir(parents=True)
    for name in ("hook.py", "router.py", "mark.py"):
        shutil.copy2(scripts / name, target / name)
    shutil.copytree(scripts / "agent_router", target / "agent_router", ignore=ignore)
    shutil.copytree(agents, target / "agents", ignore=ignore)
    (target / "VERSION").write_text(version + "\n", encoding="utf-8")
    return version


def merge_settings(root):
    """Register the vendored hooks in `.claude/settings.json`, keeping everything else.

    Running it again replaces the vendored entries and changes nothing else.
    """
    path = Path(root) / SETTINGS_RELPATH
    settings = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise VendorError(f"{SETTINGS_RELPATH} is not valid JSON: {error}") from error
        if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
            raise VendorError(f"{SETTINGS_RELPATH} has an unexpected shape; not touching it")
    hooks = settings.setdefault("hooks", {})
    for event, (matcher, argument) in EVENTS.items():
        groups = [g for g in hooks.get(event, []) if not _is_vendored(g)]
        group = {"hooks": [{"type": "command", "command": hook_command(argument), "timeout": 5}]}
        if matcher:
            group = dict(matcher=matcher, **group)
        hooks[event] = groups + [group]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _is_vendored(group):
    handlers = group.get("hooks", []) if isinstance(group, dict) else []
    return any(HOOK_RELPATH in str(h.get("command", "")) for h in handlers if isinstance(h, dict))


def vendor(root, overlay):
    """Copy the scripts, register the hooks and mark the overlay as vendored."""
    version = copy_scripts(root)
    merge_settings(root)
    if not overlay.get("vendored"):
        write_overlay(root, dict(overlay, vendored=True))
    ensure_gitattributes(root, (GITATTRIBUTES_LINE,))
    return version


def stale_note(root):
    """One line for the session when the project's vendored copy is behind the plugin."""
    vendored, running = vendored_version(root), running_version()
    if not vendored or not running or vendored == running:
        return None
    return (
        f"agent-router: this project's vendored copy is {vendored} and the installed plugin is "
        f"{running}. Run /agent-router:init again to update the vendored copy."
    )
