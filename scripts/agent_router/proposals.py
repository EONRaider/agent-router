"""Proposal rules: patterns in a project's log turned into suggested overlay edits.

Nothing here changes configuration. Each proposal carries the counts behind it, a few
example spawns, an estimate of the change in spend and the exact overlay edit; a person
accepts or rejects it.

Only real tier agents are counted. Built-in aliases run on models this plugin does not set,
so their record says nothing about how a tier is sized.
"""

import hashlib
import json
import statistics

from . import outcomes

MTOK = 1_000_000


def propose(records, config, decisions=()):
    """Proposals for a project, after applying what the user already decided.

    An accepted proposal resets the evidence for its tier. A rejected one returns only when
    the records since the rejection would, on their own, raise it again.
    """
    analysis = outcomes.analyse(records, config)
    last_record = max((r.get("ts") or "" for r in records), default="")
    accepted_at = {}
    latest = {}
    for decision in decisions:
        latest[decision.get("id")] = decision
        if decision.get("decision") == "accepted" and decision.get("tier"):
            tier = decision["tier"]
            accepted_at[tier] = max(accepted_at.get(tier, ""), decision.get("ts") or "")

    def run(after=""):
        spawns = [
            s
            for s in analysis.spawns
            if s.get("resolution") == "tier"
            and s.get("tier") in config.tiers
            and (s.get("ts") or "") > max(after, accepted_at.get(s.get("tier"), ""))
        ]
        rejects = [r for r in analysis.rejects if r.get("enforced") and (r.get("ts") or "") > after]
        return _rules(spawns, rejects, config, last_record)

    result = []
    for proposal in run():
        decision = latest.get(proposal["id"])
        if decision is None:
            result.append(proposal)
            continue
        since = {p["id"]: p for p in run(after=decision.get("ts") or "")}
        if proposal["id"] in since:
            result.append(since[proposal["id"]])
    return result


def _rules(spawns, rejects, config, last_record):
    limits = config.thresholds
    found = []
    by_tier = {}
    for spawn in spawns:
        by_tier.setdefault(spawn["tier"], []).append(spawn)
    trials = {trial.get("tier"): trial for trial in config.trials if isinstance(trial, dict)}

    for name, tier_spawns in by_tier.items():
        tier = config.tiers[name]
        if name in trials:
            found += _trial(tier, tier_spawns, trials[name], config)
            continue
        if len(tier_spawns) < limits["min_sample"]:
            continue
        found += _upgrade(tier, tier_spawns, config)
        found += _judge_contradicted(tier, tier_spawns, config)
        found += _downgrade(tier, tier_spawns, config, last_record)
        found += _recurring_override(tier, tier_spawns, config)
        found += _shared_preamble(tier, tier_spawns, config)
    found += _repeated_rejection(rejects, config)
    return found


# --- rules -------------------------------------------------------------------------------


def _meets_upgrade(spawns, config):
    incidents = [s for s in spawns if outcomes.is_incident(s)]
    rate = len(incidents) / len(spawns) if spawns else 0.0
    limits = config.thresholds
    meets = len(incidents) >= limits["upgrade_incidents"] and rate >= limits["upgrade_rate"]
    return meets, incidents, rate


def _upgrade(tier, spawns, config):
    meets, incidents, rate = _meets_upgrade(spawns, config)
    if not meets:
        return []
    efforts = config.effort_order
    position = efforts.index(tier.effort)
    next_model = _next_model(tier.model, config)
    if position < efforts.index("high"):
        field, value = "effort", efforts[position + 1]
    elif next_model:
        field, value = "model", next_model
    elif position + 1 < len(efforts):
        field, value = "effort", efforts[position + 1]
    else:
        return []
    spend = (
        _model_spend(spawns, value, config)
        if field == "model"
        else {"direction": "up", "amount": None}
    )
    return [
        _proposal(
            "upgrade",
            tier.name,
            f"Raise {tier.name} {field} from {getattr(tier, field)} to {value}: "
            f"{len(incidents)} of {len(spawns)} spawns were redone, escalated or failed review",
            {"spawns": len(spawns), "incidents": len(incidents), "rate": round(rate, 2)},
            _examples(incidents, config),
            spend,
            [{"op": "set", "path": ["tiers", tier.name, field], "value": value}],
        )
    ]


def _judge_contradicted(tier, spawns, config):
    if (tier.like or tier.name) != "judge" or tier.effort == config.effort_order[-1]:
        return []
    contradicted = [s for s in spawns if "contradicted" in s["signals"]]
    if len(contradicted) < config.thresholds["judge_contradictions"]:
        return []
    top = config.effort_order[-1]
    return [
        _proposal(
            "judge-contradicted",
            tier.name,
            f"Raise {tier.name} effort from {tier.effort} to {top}: {len(contradicted)} verdicts "
            "were contradicted by another review of the same work",
            {"spawns": len(spawns), "contradictions": len(contradicted)},
            _examples(contradicted, config),
            {"direction": "up", "amount": None},
            [{"op": "set", "path": ["tiers", tier.name, "effort"], "value": top}],
        )
    ]


def _downgrade(tier, spawns, config, last_record):
    limits = config.thresholds
    efforts = config.effort_order
    position = efforts.index(tier.effort)
    if tier.name in config.locked or position == 0 or len(spawns) < limits["downgrade_sample"]:
        return []
    if any(outcomes.is_incident(s) for s in spawns):
        return []
    tool_uses = [s["tool_uses"] for s in spawns if s.get("tool_uses") is not None]
    if not tool_uses or statistics.median(tool_uses) > limits["downgrade_median_tool_uses"]:
        return []
    lower = efforts[position - 1]
    trial = {"tier": tier.name, "since": last_record, "from_effort": tier.effort}
    return [
        _proposal(
            "downgrade",
            tier.name,
            f"Lower {tier.name} effort from {tier.effort} to {lower}, on trial: all "
            f"{len(spawns)} spawns were accepted and the tasks were short",
            {
                "spawns": len(spawns),
                "incidents": 0,
                "median_tool_uses": statistics.median(tool_uses),
            },
            _examples(spawns, config),
            {"direction": "down", "amount": None},
            [
                {"op": "set", "path": ["tiers", tier.name, "effort"], "value": lower},
                {"op": "append", "path": ["trials"], "value": trial},
            ],
        )
    ]


def _trial(tier, spawns, trial, config):
    """Judge a running trial downgrade once it has a minimum sample of its own."""
    during = [s for s in spawns if (s.get("ts") or "") > (trial.get("since") or "")]
    if len(during) < config.thresholds["min_sample"]:
        return []
    meets, incidents, rate = _meets_upgrade(during, config)
    evidence = {"spawns": len(during), "incidents": len(incidents), "rate": round(rate, 2)}
    remove = {"op": "remove_trial", "tier": tier.name}
    if not meets:
        return [
            _proposal(
                "trial-passed",
                tier.name,
                f"Keep {tier.name} at {tier.effort} effort and close the trial: "
                f"{len(incidents)} of {len(during)} spawns since it started had problems",
                evidence,
                _examples(during, config),
                {"direction": "none", "amount": None},
                [remove],
            )
        ]
    restored = trial.get("from_effort")
    return [
        _proposal(
            "trial-revert",
            tier.name,
            f"Revert the trial: put {tier.name} effort back to {restored}. "
            f"{len(incidents)} of {len(during)} spawns since it started were redone, escalated "
            "or failed review",
            evidence,
            _examples(incidents, config),
            {"direction": "up", "amount": None},
            [{"op": "set", "path": ["tiers", tier.name, "effort"], "value": restored}, remove],
        )
    ]


def _recurring_override(tier, spawns, config):
    groups = {}
    for spawn in spawns:
        requested = spawn.get("requested_model")
        if requested:
            family = config.model_family(requested) or requested.lower()
            groups.setdefault(family, []).append(spawn)
    found = []
    for family, group in sorted(groups.items()):
        name = f"{tier.name}-{family}"
        if len(group) < config.thresholds["override_repeats"] or name in config.tiers:
            continue
        if family == config.model_family(tier.model):
            continue
        value = {"model": family, "effort": tier.effort, "like": tier.like or tier.name}
        found.append(
            _proposal(
                "recurring-override",
                tier.name,
                f"Add a project tier `{name}` ({family}, {tier.effort} effort): {tier.name} was "
                f"overridden to {family} {len(group)} times",
                {"spawns": len(spawns), "overrides": len(group)},
                _examples(group, config),
                {"direction": "none", "amount": None},
                [{"op": "set", "path": ["tiers", name], "value": value}],
            )
        )
    return found


def _shared_preamble(tier, spawns, config):
    groups = {}
    for spawn in spawns:
        prefix = (spawn.get("prefix_hashes") or {}).get("500")
        if prefix:
            groups.setdefault(prefix, {})[spawn.get("prompt_hash")] = spawn
    found = []
    for prefix, briefs in sorted(groups.items()):
        if len(briefs) < config.thresholds["preamble_repeats"]:
            continue
        group = list(briefs.values())
        found.append(
            _proposal(
                "shared-preamble",
                tier.name,
                f"Add a specialised agent type for {tier.name}: {len(group)} different briefs "
                "began with the same 500 characters",
                {"spawns": len(spawns), "spawns_sharing": len(group), "prefix": prefix},
                _examples(group, config),
                {"direction": "down", "amount": None},
                None,
                manual=(
                    "The log does not store prompts, so this edit cannot be written for you. "
                    "Create a project agent in .claude/agents/ whose body holds the shared "
                    f'preamble, then map it in the overlay: "aliases": {{"<its-name>": '
                    f'"{tier.name}"}}.'
                ),
            )
        )
    return found


def _repeated_rejection(rejects, config):
    groups = {}
    for record in rejects:
        if record.get("rule") == "review-language" and record.get("phrase"):
            groups.setdefault(record["phrase"], []).append(record)
    found = []
    for phrase, group in sorted(groups.items()):
        if len(group) < config.thresholds["reject_repeats"]:
            continue
        found.append(
            _proposal(
                "repeated-rejection",
                None,
                f"Stop treating '{phrase}' as review language: the hook rejected {len(group)} "
                "briefs for it. Accept only if those briefs were not review work; otherwise "
                "consider adding a tier for them",
                {"rejections": len(group), "phrase": phrase},
                _examples(group, config),
                {"direction": "down", "amount": None},
                [{"op": "append", "path": ["review_language", "remove"], "value": phrase}],
            )
        )
    return found


# --- helpers -----------------------------------------------------------------------------


def _next_model(model, config):
    """The next model up the tier ladder, or None when `model` is at the top of it.

    Proposals stay on the ladder the shipped tiers use; a model above it can still be chosen
    by hand in the overlay.
    """
    family = config.model_family(model)
    ladder = config.model_ladder
    if family not in ladder or ladder.index(family) + 1 >= len(ladder):
        return None
    return ladder[ladder.index(family) + 1]


def cost(spawn, family, config):
    """Estimated cost in dollars of a spawn's logged tokens at a family's list prices."""
    tokens = spawn.get("tokens")
    prices = config.prices.get(family)
    if not tokens or not prices:
        return None
    return sum((tokens.get(kind) or 0) * prices[kind] for kind in prices) / MTOK


def spawn_family(spawn, config):
    tier = config.tiers.get(spawn.get("tier"))
    return config.model_family(spawn.get("resolved_model")) or (
        config.model_family(tier.model) if tier else None
    )


def _model_spend(spawns, new_family, config):
    delta = 0.0
    counted = 0
    for spawn in spawns:
        before = cost(spawn, spawn_family(spawn, config), config)
        after = cost(spawn, new_family, config)
        if before is None or after is None:
            continue
        delta += after - before
        counted += 1
    if not counted:
        return {"direction": "up", "amount": None}
    direction = "up" if delta > 0 else "down"
    return {"direction": direction, "amount": round(delta, 2), "over_spawns": counted}


def _examples(spawns, config):
    limit = config.thresholds["examples"]
    return [
        {
            "ts": s.get("ts"),
            "type": s.get("type"),
            "summary": s.get("summary"),
            "signals": sorted(s.get("signals", ())),
        }
        for s in spawns[-limit:]
    ]


def _proposal(rule, tier, title, evidence, examples, spend, edit, manual=None):
    identity = [rule, tier, _stable(edit), evidence.get("prefix"), evidence.get("phrase")]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "id": digest[:12],
        "rule": rule,
        "tier": tier,
        "title": title,
        "evidence": evidence,
        "examples": examples,
        "spend": spend,
        "edit": edit,
        "manual": manual,
    }


def _stable(edit):
    """An edit with the parts that change from run to run removed, for the proposal id."""
    if edit is None:
        return None
    stable = []
    for op in edit:
        value = op.get("value")
        if isinstance(value, dict) and "since" in value:
            value = {k: v for k, v in value.items() if k != "since"}
        stable.append(dict(op, value=value))
    return stable
