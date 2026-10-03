"""The short text a SessionStart hook adds to a session's context."""

INIT_HINT = (
    "agent-router: this project has not opted in, so spawns are not logged. "
    "Run /agent-router:init to enable the spawn log and per-project routing."
)


def tier_table(config):
    """One line per tier: the agent type to spawn and what it is sized at."""
    lines = []
    for name, tier in config.tiers.items():
        lines.append(f"- {name}: spawn `{tier.agent_type}` ({tier.model}, {tier.effort} effort)")
    return "\n".join(lines)


def mark_command(script, session_id):
    """The exact command a session runs to record an outcome for one of its agents."""
    return (
        "To record what happened to an agent's output (redone, review-failed, user-rejected), "
        f'run: python3 "{script}" --session {session_id} <agent-id> <outcome>'
    )


def session_context(config, warning=None, mark=None):
    """Context for an opted-in project: which agent type to spawn for each tier."""
    if not config.initialised:
        return "\n".join(part for part in (warning, INIT_HINT) if part)
    parts = [
        "agent-router is active in this project. When you spawn a subagent, pick a tier:",
        tier_table(config),
        "Lookups go to scout, checkable implementation to worker, research to analyst, and "
        "review, audit, security or design calls always go to judge. When unsure, go up a tier.",
    ]
    if mark and config.log_enabled:
        parts.append(mark)
    if warning:
        parts.insert(0, warning)
    return "\n".join(parts)
