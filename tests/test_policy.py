"""Enforcement rules. Plain rule code: no Claude Code needed."""

import pytest
from agent_router import policy
from agent_router.config import Config, load_defaults


def config(overlay=None):
    return Config(load_defaults(), {"version": 1} if overlay is None else overlay)


def decide(subagent_type, description="do a thing", prompt="Do the thing.", overlay=None, **kw):
    tool_input = {"subagent_type": subagent_type, "description": description, "prompt": prompt}
    tool_input.update({k: v for k, v in kw.items() if k == "model"})
    return policy.decide(tool_input, config(overlay), kw.get("loaded", set()))


# --- allowed -----------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["scout", "worker", "analyst", "judge"])
def test_plain_spawn_of_each_tier_is_allowed(tier):
    assert decide(f"agent-router:{tier}").allow


def test_exempt_and_other_plugin_agents_are_never_checked():
    assert decide(
        "solid-coding:solid-reviewer", description="review the module", model="haiku"
    ).allow
    assert decide("claude-code-guide", description="audit my hooks").allow


def test_judge_accepts_any_brief():
    assert decide("agent-router:judge", description="review the auth diff").allow
    assert decide("agent-router:analyst", description="audit dependency usage").allow


# --- rule 1: untiered --------------------------------------------------------------------


def test_unknown_agent_passes_by_default():
    decision = decide("my-db-agent")
    assert decision.allow and decision.rule is None


def test_unknown_agent_is_rejected_in_strict_mode():
    decision = decide("my-db-agent", overlay={"strict": True})
    assert not decision.allow and decision.rule == "untiered"
    assert "agent-router:worker" in decision.reason and "\n" not in decision.reason


def test_strict_mode_still_allows_aliases_and_exemptions():
    overlay = {"strict": True, "aliases": {"my-db-agent": "worker"}}
    assert decide("my-db-agent", overlay=overlay).allow
    assert decide("Explore", overlay=overlay).allow
    assert decide("solid-coding:solid-verifier", overlay=overlay).allow


# --- rule 2: remapped --------------------------------------------------------------------

REMAP = {"tiers": {"worker": {"model": "opus", "effort": "high"}}}


def test_remapped_tier_redirects_to_the_project_agent_once_it_is_loaded():
    decision = decide("agent-router:worker", overlay=REMAP, loaded={"router-worker"})
    assert not decision.allow and decision.rule == "remapped"
    assert "`router-worker`" in decision.reason


def test_remapped_tier_is_still_allowed_while_the_project_agent_cannot_load():
    assert decide("agent-router:worker", overlay=REMAP, loaded=set()).allow


def test_project_agent_and_untouched_tiers_are_allowed():
    assert decide("router-worker", overlay=REMAP, loaded={"router-worker"}).allow
    assert decide("agent-router:scout", overlay=REMAP, loaded={"router-worker"}).allow


# --- rule 3: review language -------------------------------------------------------------


@pytest.mark.parametrize(
    "description,prompt",
    [
        ("review the auth diff", "Look at it."),
        ("check changes", "Audit the payment module for problems. Then list them."),
        ("Security review of login", "Go."),
        ("look at design", "Critique this design and sign off on it."),
        ("auditing deps", "List them."),
        ("threat model for API", "Go."),
    ],
)
@pytest.mark.parametrize("agent", ["agent-router:scout", "agent-router:worker", "Explore", ""])
def test_review_language_to_a_low_tier_is_rejected(agent, description, prompt):
    decision = decide(agent, description, prompt)
    assert not decision.allow and decision.rule == "review-language"
    assert "`agent-router:judge`" in decision.reason and decision.phrase


@pytest.mark.parametrize(
    "description,prompt",
    [
        ("address review comments", "Apply the review comments in PR 12."),
        ("add audit log table", "Create the audit log migration."),
        ("implement parser", "Write the parser. When done, review your diff before reporting."),
        ("implement preview", "Add a preview pane."),
        ("find reviewer config", "Where is the reviewers list configured?"),
        ("fix code", "```\n# review this later\n```\nFix the bug above."),
    ],
)
def test_ordinary_briefs_are_not_mistaken_for_review(description, prompt):
    assert decide("agent-router:worker", description, prompt).allow


def test_review_rule_can_be_set_to_warn_or_off():
    warn = decide(
        "agent-router:worker", "review the diff", overlay={"review_language": {"mode": "warn"}}
    )
    assert warn.allow and warn.rule == "review-language" and warn.phrase == "review"
    off = decide(
        "agent-router:worker", "review the diff", overlay={"review_language": {"mode": "off"}}
    )
    assert off.allow and off.rule is None


def test_review_rule_only_warns_before_the_project_opts_in():
    decision = policy.decide(
        {"subagent_type": "agent-router:worker", "description": "review the diff", "prompt": "x"},
        Config(load_defaults()),
        set(),
    )
    assert decision.allow and decision.rule == "review-language"


def test_project_phrases_are_honoured():
    overlay = {"review_language": {"add": ["pentest"], "remove": ["audit"]}}
    assert not decide("agent-router:worker", "pentest the API", overlay=overlay).allow
    assert decide("agent-router:worker", "audit the API", overlay=overlay).allow


def test_added_tier_inherits_the_review_rule_of_the_tier_it_is_like():
    overlay = {"tiers": {"migrator": {"model": "sonnet", "effort": "high", "like": "worker"}}}
    assert not decide("router-migrator", "review the migration", overlay=overlay).allow


# --- rule 4: model floor -----------------------------------------------------------------


def test_override_below_the_tier_floor_is_rejected():
    decision = decide("agent-router:worker", model="haiku")
    assert not decision.allow and decision.rule == "model-floor"
    assert "sonnet" in decision.reason
    assert not decide("agent-router:judge", model="claude-sonnet-5").allow
    assert not decide("general-purpose", model="haiku").allow


def test_override_at_or_above_the_floor_is_allowed():
    assert decide("agent-router:worker", model="sonnet").allow
    assert decide("agent-router:worker", model="opus").allow
    assert decide("agent-router:scout", model="claude-opus-5-5").allow


def test_unknown_model_is_allowed_and_noted():
    decision = decide("agent-router:worker", model="mystery")
    assert decision.allow and "mystery" in decision.note
    assert decide("agent-router:judge", model="fable").allow


def test_tier_floor_can_be_lowered_by_the_project():
    overlay = {"tiers": {"worker": {"model": "sonnet", "effort": "medium", "floor": "haiku"}}}
    assert decide("router-worker", model="haiku", overlay=overlay).allow


# --- rule 5: project floor ---------------------------------------------------------------


def test_project_floor_rejects_tiers_below_it():
    decision = decide("agent-router:scout", overlay={"floor": "sonnet"})
    assert not decision.allow and decision.rule == "project-floor"
    assert decide("agent-router:worker", overlay={"floor": "sonnet"}).allow
    assert decide("agent-router:scout", model="sonnet", overlay={"floor": "sonnet"}).allow


def test_project_floor_does_not_guess_at_aliases():
    assert decide("Explore", overlay={"floor": "sonnet"}).allow


# --- shape -------------------------------------------------------------------------------


def test_missing_fields_do_not_raise():
    assert policy.decide({}, config(), set()).allow
    assert policy.decide({"subagent_type": None, "prompt": None}, config(), set()).allow


def test_every_denial_is_one_line():
    cases = [
        decide("my-db-agent", overlay={"strict": True}),
        decide("agent-router:worker", "review the diff"),
        decide("agent-router:worker", model="haiku"),
        decide("agent-router:scout", overlay={"floor": "opus"}),
    ]
    for decision in cases:
        assert not decision.allow and "\n" not in decision.reason and len(decision.reason) < 300
