"""The enforcement rules for a subagent spawn.

`decide` is a pure function of the Agent tool's input, the project's config and the set of
project agents the session can load. It matches on rules only and never calls a model.

Moving up is always allowed: a higher tier accepts any brief, and a model override above a
tier's own model passes. A wrong rejection therefore costs money, never a deadlock.
"""

import re

FENCE = re.compile(r"```.*?```", re.DOTALL)
SENTENCE_END = re.compile(r"(?<=[.!?])\s|\n")
FIRST_SENTENCE_MAX = 300


class Decision:
    def __init__(self, allow, rule=None, reason=None, phrase=None, note=None):
        self.allow = allow
        self.rule = rule  # the rule that matched, also set for a warn-only match
        self.reason = reason  # one line for the session, naming the correct call
        self.phrase = phrase
        self.note = note


ALLOW = Decision(True)


def decide(tool_input, config, loaded_agents=frozenset()):
    """Allow or deny one Agent call."""
    subagent_type = tool_input.get("subagent_type") or ""
    resolution = config.resolve(subagent_type)
    tier = resolution.tier
    shown = subagent_type or "general-purpose"

    if resolution.kind == "exempt":
        return ALLOW

    if resolution.kind == "unknown":
        if not config.strict:
            return ALLOW
        choices = ", ".join(f"`{t.agent_type}`" for t in config.tiers.values())
        return Decision(
            False,
            "untiered",
            f"agent-router: `{shown}` has no tier in this project. Spawn one of {choices}, or "
            "ask the user to add it to `aliases` or `exempt` in .claude/agent-router.json.",
        )

    if resolution.via_shipped_agent and tier.remapped and tier.agent_type in loaded_agents:
        return Decision(
            False,
            "remapped",
            f"agent-router: the {tier.name} tier is remapped in this project. "
            f"Spawn `{tier.agent_type}` instead of `{shown}`.",
        )

    review = _review_language(tool_input, tier, config)
    if review is not None and not review.allow:
        return review

    requested = tool_input.get("model")
    note = None
    if requested:
        rank = config.model_rank(requested)
        floor_rank = config.model_rank(tier.floor)
        if rank is None:
            note = f"model `{requested}` has no known rank; allowed"
        elif floor_rank is not None and rank < floor_rank:
            return Decision(
                False,
                "model-floor",
                f"agent-router: model `{requested}` is below the {tier.name} tier's floor "
                f"({tier.floor}). Drop the `model` override, or spawn a lower tier if the task "
                "really is smaller.",
            )

    if config.floor:
        # An alias runs on a model this plugin does not set, so only an explicit model is judged.
        effective = requested or (tier.model if resolution.kind == "tier" else None)
        rank = config.model_rank(effective)
        project_rank = config.model_rank(config.floor)
        if rank is not None and project_rank is not None and rank < project_rank:
            return Decision(
                False,
                "project-floor",
                f"agent-router: this project's floor is {config.floor} and `{shown}` would run "
                f"on {effective}. Spawn a tier at or above the floor.",
            )

    if review is not None:
        return review
    return Decision(True, note=note) if note else ALLOW


def brief_surface(tool_input):
    """The part of a brief the review rule reads: the description and the first sentence.

    Reading the whole prompt would catch pasted code and closing instructions such as
    "review your diff before reporting".
    """
    prompt = FENCE.sub(" ", tool_input.get("prompt") or "").strip()
    first = SENTENCE_END.split(prompt, 1)[0][:FIRST_SENTENCE_MAX] if prompt else ""
    return f"{tool_input.get('description') or ''} . {first}".lower()


def find_review_phrase(text, config):
    """The first review phrase in `text`, ignoring the excluded expressions."""
    for exclusion in sorted(config.review_exclusions, key=len, reverse=True):
        text = text.replace(exclusion, " ")
    for phrase in sorted(config.review_phrases, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase) + r"(?:s|ed|ing)?\b", text):
            return phrase
    return None


def _review_language(tool_input, tier, config):
    if config.review_mode == "off":
        return None
    base = tier.like or tier.name
    if base not in config.review_tiers:
        return None
    phrase = find_review_phrase(brief_surface(tool_input), config)
    if phrase is None:
        return None
    judge = config.tiers["judge"].agent_type
    reason = (
        f"agent-router: the brief asks for review work ('{phrase}') but targets the {tier.name} "
        f"tier. Judgment work goes to `{judge}`. If this is not review work, reword the "
        "description."
    )
    return Decision(config.review_mode != "deny", "review-language", reason, phrase)
