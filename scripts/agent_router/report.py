"""The per-project report: what the log shows, and the proposals that follow from it."""

import json

from . import outcomes, proposals
from .decisions import read_decisions
from .log import read_records


def build(root, config):
    """Everything the report shows, as plain data."""
    records = read_records(root)
    analysis = outcomes.analyse(records, config)
    tiers = {}
    others = {}
    for spawn in analysis.spawns:
        if spawn.get("resolution") == "tier" and spawn.get("tier") in config.tiers:
            row = tiers.setdefault(spawn["tier"], _row())
        else:
            row = others.setdefault(spawn.get("type") or "?", _row())
        row["spawns"] += 1
        row["incidents"] += 1 if outcomes.is_incident(spawn) else 0
        row["overrides"] += 1 if "override" in spawn["signals"] else 0
        row["unfinished"] += 1 if "unfinished" in spawn["signals"] else 0
        spent = proposals.cost(spawn, proposals.spawn_family(spawn, config), config)
        if spent is not None:
            row["spend"] += spent
            row["priced"] += 1
    rejections = {}
    for record in analysis.rejects:
        key = (record.get("rule"), record.get("phrase"), bool(record.get("enforced")))
        rejections[key] = rejections.get(key, 0) + 1
    return {
        "sessions": len({r.get("session") for r in records}),
        "records": len(records),
        "first": min((r.get("ts") or "" for r in records), default=None),
        "last": max((r.get("ts") or "" for r in records), default=None),
        "tiers": tiers,
        "other_agents": others,
        "rejections": [
            {"rule": rule, "phrase": phrase, "enforced": enforced, "count": count}
            for (rule, phrase, enforced), count in sorted(rejections.items(), key=str)
        ],
        "unlinked_verdicts": [
            {"ts": v.get("ts"), "summary": v.get("summary")} for v in analysis.unlinked_verdicts
        ],
        "trials": config.trials,
        "proposals": proposals.propose(records, config, read_decisions(root)),
        "min_sample": config.thresholds["min_sample"],
    }


def _row():
    return {"spawns": 0, "incidents": 0, "overrides": 0, "unfinished": 0, "spend": 0.0, "priced": 0}


def summaries(root, config):
    """Short task summaries behind overrides and rejections, for grouping similar briefs."""
    analysis = outcomes.analyse(read_records(root), config)
    return {
        "overrides": [
            {"tier": s.get("tier"), "model": s.get("requested_model"), "summary": s.get("summary")}
            for s in analysis.spawns
            if "override" in s["signals"]
        ],
        "rejections": [
            {"rule": r.get("rule"), "phrase": r.get("phrase"), "summary": r.get("summary")}
            for r in analysis.rejects
        ],
    }


def render(data, config):
    """The report as plain text."""
    if not data["records"]:
        return "agent-router: the spawn log is empty. Nothing to report yet."
    lines = [
        f"agent-router report: {data['records']} records from {data['sessions']} sessions, "
        f"{data['first']} to {data['last']}",
        "",
        "Tiers (only these feed proposals):",
    ]
    for name, tier in config.tiers.items():
        row = data["tiers"].get(name)
        if row is None:
            lines.append(f"- {name} ({tier.model}, {tier.effort}): no spawns")
            continue
        lines.append(f"- {name} ({tier.model}, {tier.effort}): {_describe(row)}")
    if data["other_agents"]:
        lines += ["", "Other agents (built-in aliases, exempt and unmapped types; not resized):"]
        lines += [
            f"- {name}: {_describe(row)}" for name, row in sorted(data["other_agents"].items())
        ]
    if data["rejections"]:
        lines += ["", "Hook matches:"]
        for item in data["rejections"]:
            what = f"{item['rule']}" + (f" ('{item['phrase']}')" if item["phrase"] else "")
            effect = "rejected" if item["enforced"] else "warned only"
            lines.append(f"- {what}: {item['count']} {effect}")
    if data["unlinked_verdicts"]:
        lines += [
            "",
            f"{len(data['unlinked_verdicts'])} failing judge verdicts had no `Reviews:` link, so "
            "they are not counted against any tier.",
        ]
    for trial in data["trials"]:
        lines.append(
            f"Trial running: {trial.get('tier')} lowered from {trial.get('from_effort')} effort "
            f"since {trial.get('since')}."
        )
    lines.append("")
    if not data["proposals"]:
        lines.append(
            "No proposals. A tier needs at least "
            f"{data['min_sample']} logged spawns before anything is proposed."
        )
        return "\n".join(lines)
    lines.append(f"Proposals ({len(data['proposals'])}):")
    for proposal in data["proposals"]:
        lines += ["", f"[{proposal['id']}] {proposal['title']}"]
        evidence = ", ".join(f"{k}={v}" for k, v in proposal["evidence"].items() if k != "prefix")
        lines.append(f"  Evidence: {evidence}")
        lines.append(f"  Spend: {_spend(proposal['spend'])}")
        for example in proposal["examples"]:
            signals = ", ".join(example["signals"]) or "no signals"
            lines.append(
                f"  e.g. {example['ts']} {example['summary'] or '(no summary)'} [{signals}]"
            )
        if proposal["edit"] is not None:
            lines.append(f"  Overlay edit: {json.dumps(proposal['edit'])}")
        if proposal.get("manual"):
            lines.append(f"  By hand: {proposal['manual']}")
    return "\n".join(lines)


def _describe(row):
    rate = row["incidents"] / row["spawns"] if row["spawns"] else 0
    parts = [
        f"{row['spawns']} spawns",
        f"{row['incidents']} with problems ({rate:.0%})",
        f"{row['overrides']} model overrides",
    ]
    if row["unfinished"]:
        parts.append(f"{row['unfinished']} still running or never finished")
    if row["priced"]:
        parts.append(f"about ${row['spend']:.2f} at list prices")
    return ", ".join(parts)


def _spend(spend):
    if spend.get("amount") is not None:
        sign = "+" if spend["amount"] >= 0 else "-"
        return (
            f"about {sign}${abs(spend['amount']):.2f} over the {spend['over_spawns']} logged "
            "spawns, at list prices"
        )
    words = {
        "up": "higher; the log cannot predict token use at another effort level",
        "down": "lower; the log cannot predict by how much",
        "none": "no change expected",
    }
    return words[spend["direction"]]
