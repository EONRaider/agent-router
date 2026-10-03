"""Proposal rules and guardrails. Plain rule code: no Claude Code needed."""

from agent_router import proposals
from agent_router.config import Config, load_defaults
from builders import clean, mark, reject, spawn, stamp


def config(overlay=None):
    return Config(load_defaults(), overlay or {"version": 1})


def propose(records, overlay=None, decisions=()):
    return proposals.propose(records, config(overlay), list(decisions))


def only(result, rule):
    return [p for p in result if p["rule"] == rule]


def redone(tier, count):
    records = clean(tier, count)
    return records + [mark(r["agent_id"], "redone") for r in records]


# --- upgrades ----------------------------------------------------------------------------


def test_often_redone_tier_gets_an_effort_raise_first():
    (proposal,) = only(propose(clean("worker", 17) + redone("worker", 3)), "upgrade")
    assert proposal["tier"] == "worker"
    assert proposal["edit"] == [
        {"op": "set", "path": ["tiers", "worker", "effort"], "value": "high"}
    ]
    assert proposal["evidence"] == {"spawns": 20, "incidents": 3, "rate": 0.15}
    assert 1 <= len(proposal["examples"]) <= 4
    assert proposal["spend"]["direction"] == "up" and proposal["spend"]["amount"] is None


def test_a_tier_already_at_high_effort_gets_a_model_raise_with_a_spend_number():
    (proposal,) = only(propose(clean("analyst", 17) + redone("analyst", 3)), "upgrade")
    assert proposal["edit"] == [
        {"op": "set", "path": ["tiers", "analyst", "model"], "value": "opus"}
    ]
    assert proposal["spend"]["amount"] > 0


def test_a_tier_at_the_top_model_gets_more_effort():
    (proposal,) = only(propose(clean("judge", 17) + redone("judge", 3)), "upgrade")
    assert proposal["edit"][0]["path"] == ["tiers", "judge", "effort"]
    assert proposal["edit"][0]["value"] == "xhigh"


def test_no_upgrade_below_the_minimum_sample():
    assert only(propose(clean("worker", 10) + redone("worker", 9)), "upgrade") == []


def test_no_upgrade_below_the_incident_count_or_rate():
    assert only(propose(clean("worker", 18) + redone("worker", 2)), "upgrade") == []
    assert only(propose(clean("worker", 97) + redone("worker", 3)), "upgrade") == []


def test_aliases_and_exempt_agents_never_feed_proposals():
    records = clean("worker", 17, resolution="alias", type="general-purpose") + [
        dict(r, resolution="alias") for r in redone("worker", 3)
    ]
    assert propose(records) == []


def test_override_and_rejection_are_not_incidents():
    records = clean("worker", 30, requested_model="opus")
    assert only(propose(records), "upgrade") == []


# --- judge contradictions ----------------------------------------------------------------


def contradiction(n):
    work = spawn("worker", minute=n)
    turn = f"turn{n}"
    return [
        work,
        spawn("judge", minute=n + 1, verdict="pass", reviews=work["agent_id"], prompt_id=turn),
        spawn("judge", minute=n + 2, verdict="fail", reviews=work["agent_id"], prompt_id=turn),
    ]


def test_contradicted_judge_gets_max_effort():
    records = clean("judge", 20) + contradiction(1000) + contradiction(2000)
    (proposal,) = only(propose(records), "judge-contradicted")
    assert proposal["edit"] == [{"op": "set", "path": ["tiers", "judge", "effort"], "value": "max"}]
    assert proposal["evidence"]["contradictions"] == 2


def test_one_contradiction_is_not_enough():
    assert only(propose(clean("judge", 20) + contradiction(1000)), "judge-contradicted") == []


# --- downgrades and trials ---------------------------------------------------------------


def test_always_accepted_short_tasks_get_a_trial_downgrade():
    (proposal,) = only(propose(clean("worker", 50)), "downgrade")
    set_effort, add_trial = proposal["edit"]
    assert set_effort == {"op": "set", "path": ["tiers", "worker", "effort"], "value": "low"}
    assert add_trial["op"] == "append" and add_trial["path"] == ["trials"]
    assert add_trial["value"]["tier"] == "worker" and add_trial["value"]["from_effort"] == "medium"
    assert proposal["spend"]["direction"] == "down"


def test_downgrade_needs_far_more_evidence_than_an_upgrade():
    assert only(propose(clean("worker", 49)), "downgrade") == []


def test_a_single_incident_blocks_a_downgrade():
    records = clean("worker", 60) + redone("worker", 1)
    assert only(propose(records), "downgrade") == []


def test_long_tasks_block_a_downgrade():
    assert only(propose(clean("worker", 50, tool_uses=12)), "downgrade") == []


def test_locked_tiers_and_lowest_effort_are_never_downgraded():
    assert only(propose(clean("worker", 50), {"locked": ["worker"]}), "downgrade") == []
    assert only(propose(clean("scout", 50)), "downgrade") == []


def test_no_second_downgrade_while_a_trial_is_running():
    overlay = {
        "tiers": {"analyst": {"effort": "medium"}},
        "trials": [{"tier": "analyst", "since": stamp(0), "from_effort": "high"}],
    }
    records = clean("analyst", 50, type="router-analyst", effort="medium")
    assert only(propose(records, overlay), "downgrade") == []


TRIAL = {
    "tiers": {"worker": {"effort": "low"}},
    "trials": [{"tier": "worker", "since": stamp(500), "from_effort": "medium"}],
}


def test_trial_that_starts_getting_redone_is_proposed_for_revert():
    before = clean("worker", 50, minute=10)
    during = clean("worker", 17, minute=600) + redone("worker", 3)
    for record in during:
        record["ts"] = stamp(600) if record["kind"] == "spawn" else record["ts"]
    (proposal,) = only(propose(before + during, TRIAL), "trial-revert")
    assert proposal["edit"] == [
        {"op": "set", "path": ["tiers", "worker", "effort"], "value": "medium"},
        {"op": "remove_trial", "tier": "worker"},
    ]
    assert proposal["evidence"]["spawns"] == 20


def test_trial_is_not_judged_before_it_has_a_minimum_sample():
    during = clean("worker", 2, minute=600) + redone("worker", 3)
    for record in during:
        record["ts"] = stamp(600) if record["kind"] == "spawn" else record["ts"]
    result = propose(clean("worker", 50, minute=10) + during, TRIAL)
    assert only(result, "trial-revert") == [] and only(result, "trial-passed") == []


def test_clean_trial_is_proposed_for_closing():
    result = propose(clean("worker", 20, minute=600), TRIAL)
    (proposal,) = only(result, "trial-passed")
    assert proposal["edit"] == [{"op": "remove_trial", "tier": "worker"}]


# --- recurring override, preamble, rejections --------------------------------------------


def test_recurring_override_becomes_a_project_tier():
    records = clean("worker", 5, requested_model="opus", resolved_model="claude-opus-5-5")
    (proposal,) = only(propose(records + clean("worker", 15)), "recurring-override")
    (edit,) = proposal["edit"]
    assert edit["path"] == ["tiers", "worker-opus"]
    assert edit["value"] == {"model": "opus", "effort": "medium", "like": "worker"}


def test_four_overrides_are_not_a_pattern():
    records = clean("worker", 4, requested_model="opus") + clean("worker", 16)
    assert only(propose(records), "recurring-override") == []


def test_shared_long_preamble_suggests_a_specialised_type():
    records = clean("worker", 5, prefix_hashes={"200": "a", "500": "b"}) + clean("worker", 15)
    (proposal,) = only(propose(records), "shared-preamble")
    assert proposal["edit"] is None and proposal["manual"]
    assert proposal["evidence"]["spawns_sharing"] == 5


def test_the_same_brief_repeated_is_not_a_shared_preamble():
    records = clean("worker", 5, prefix_hashes={"500": "b"}, prompt_hash="same")
    assert only(propose(records + clean("worker", 15)), "shared-preamble") == []


def test_repeated_rejection_of_one_phrase_suggests_dropping_it():
    records = [reject("worker", phrase="audit") for _ in range(5)]
    (proposal,) = only(propose(records), "repeated-rejection")
    assert proposal["edit"] == [
        {"op": "append", "path": ["review_language", "remove"], "value": "audit"}
    ]


def test_warn_only_matches_do_not_count_as_rejections():
    records = [reject("worker", phrase="audit", enforced=False) for _ in range(9)]
    assert only(propose(records), "repeated-rejection") == []


# --- shape, decisions --------------------------------------------------------------------


def test_every_proposal_has_a_stable_id_and_the_documented_fields():
    records = clean("worker", 17) + redone("worker", 3)
    (first,) = only(propose(records), "upgrade")
    (second,) = only(propose(list(reversed(records))), "upgrade")
    assert first["id"] == second["id"] and len(first["id"]) == 12
    assert {"id", "rule", "tier", "title", "evidence", "examples", "spend", "edit"} <= set(first)
    assert all("prompt" not in example for example in first["examples"])


def decision(proposal, verdict, minute):
    return {
        "id": proposal["id"],
        "decision": verdict,
        "ts": stamp(minute),
        "tier": proposal["tier"],
    }


def test_rejected_proposal_stays_quiet_until_new_evidence_meets_the_threshold_again():
    old = clean("worker", 17, minute=10) + redone("worker", 3)
    for record in old:
        record["ts"] = stamp(10)
    (proposal,) = only(propose(old), "upgrade")
    rejected = [decision(proposal, "rejected", 100)]
    assert only(propose(old, decisions=rejected), "upgrade") == []

    a_little_more = old + clean("worker", 5, minute=200)
    assert only(propose(a_little_more, decisions=rejected), "upgrade") == []

    fresh = clean("worker", 17, minute=200) + redone("worker", 3)
    for record in fresh:
        record["ts"] = stamp(200)
    (again,) = only(propose(old + fresh, decisions=rejected), "upgrade")
    assert again["id"] == proposal["id"] and again["evidence"]["spawns"] == 20


def test_accepted_proposal_resets_the_evidence_for_its_tier():
    old = clean("worker", 17, minute=10) + redone("worker", 3)
    for record in old:
        record["ts"] = stamp(10)
    (proposal,) = only(propose(old), "upgrade")
    accepted = [decision(proposal, "accepted", 100)]
    overlay = {"tiers": {"worker": {"effort": "high"}}}
    assert propose(old, overlay, accepted) == []


def test_empty_log_gives_no_proposals():
    assert propose([]) == []
