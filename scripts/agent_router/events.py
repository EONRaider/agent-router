"""What each hook event does. Kept apart from the entry point so it can be tested."""

import time
from pathlib import Path

from . import config as config_module
from . import context, log, policy, project, vendor

# Claude Code reloads agent definitions when a session starts or is resumed.
RELOADING_SOURCES = ("startup", "resume")


def _setup(payload, env, refresh=False):
    root = project.session_state(payload, env, refresh)["root"]
    config, warning = config_module.load_or_defaults(root)
    return root, config, warning


def session_start(payload, env):
    """Resolve the project once and tell the session which agent types to use."""
    root, config, warning = _setup(payload, env, refresh=payload.get("source") in RELOADING_SOURCES)
    # SessionStart has no event id; a short time bucket keeps a second hook set quiet.
    bucket = int(time.time() // 5)
    if not project.claim(payload, f"start-{payload.get('source')}-{bucket}", env):
        return None
    script = Path(__file__).resolve().parent.parent / "mark.py"
    mark = context.mark_command(script, project.safe_id(payload.get("session_id")))
    notes = [n for n in (warning, vendor.stale_note(root) if config.vendored else None) if n]
    return {"stdout": context.session_context(config, "\n".join(notes) or None, mark)}


def pre_tool_use(payload, env):
    """Check a spawn against the routing rules; deny with one line naming the right call."""
    if payload.get("tool_name") != "Agent":
        return None
    root, config, _ = _setup(payload, env)
    loaded = project.session_state(payload, env)["agents"]
    decision = policy.decide(payload.get("tool_input") or {}, config, loaded)
    if decision.rule is None:
        return None
    if not project.claim(payload, f"pre-{payload.get('tool_use_id')}", env):
        return None
    if config.log_enabled:
        record = log.reject_record(payload, config, decision)
        log.append(log.log_path(root, payload.get("session_id")), record)
    if decision.allow:
        return None
    return {
        "json": {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.reason,
            }
        }
    }


def post_tool_use(payload, env):
    """Log a finished (or launched) Agent call."""
    if payload.get("tool_name") != "Agent":
        return None
    root, config, _ = _setup(payload, env)
    if not config.log_enabled or not project.claim(
        payload, f"post-{payload.get('tool_use_id')}", env
    ):
        return None
    log.append(log.log_path(root, payload.get("session_id")), log.spawn_record(payload, config))
    return None


def post_tool_use_failure(payload, env):
    """Log an Agent call that errored."""
    if payload.get("tool_name") != "Agent":
        return None
    root, config, _ = _setup(payload, env)
    if not config.log_enabled or not project.claim(
        payload, f"fail-{payload.get('tool_use_id')}", env
    ):
        return None
    log.append(log.log_path(root, payload.get("session_id")), log.fail_record(payload, config))
    return None


def subagent_stop(payload, env):
    """Log a subagent's totals when it stops; this is the only source for background spawns."""
    root, config, _ = _setup(payload, env)
    if not config.log_enabled or not project.claim(payload, f"stop-{payload.get('agent_id')}", env):
        return None
    log.append(log.log_path(root, payload.get("session_id")), log.finish_record(payload, config))
    return None


HANDLERS = {
    "session-start": session_start,
    "pre": pre_tool_use,
    "post": post_tool_use,
    "post-failure": post_tool_use_failure,
    "subagent-stop": subagent_stop,
}
