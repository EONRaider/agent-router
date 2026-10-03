"""Outcome signals: what the log says happened to each spawn's output.

Every signal is derived by rule from the records. They are proxies: "not redone" is not
"good". A linked judge verdict is the strongest; a `mark` depends on the session having
recorded it.
"""

import datetime

# Signals that count as an incident against the tier that produced the output.
INCIDENT_SIGNALS = frozenset(
    {
        "partial",
        "empty",
        "failed",
        "retried",
        "escalated",
        "redone",
        "review-failed",
        "user-rejected",
        "review_failed",
    }
)
MARK_OUTCOMES = ("redone", "review-failed", "user-rejected")


class Analysis:
    def __init__(self, spawns, rejects, unlinked_verdicts):
        self.spawns = spawns  # one dict per spawn (or failed call), with a `signals` set
        self.rejects = rejects
        self.unlinked_verdicts = unlinked_verdicts


def is_incident(spawn):
    return bool(spawn["signals"] & INCIDENT_SIGNALS)


def parse_ts(value):
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return datetime.datetime.min


def _dedupe(records):
    """Drop records two hook sets both wrote for one event."""
    seen = set()
    unique = []
    for record in records:
        kind = record.get("kind")
        identity = record.get("agent_id") if kind == "finish" else record.get("tool_use_id")
        key = (kind, record.get("session"), identity, record.get("outcome"))
        if identity is not None and key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _window(spawn, finishes):
    """When a spawn started and ended, as far as the log can tell."""
    recorded = parse_ts(spawn.get("ts"))
    if spawn.get("background"):
        done = finishes.get((spawn.get("session"), spawn.get("agent_id")))
        return recorded, parse_ts(done["ts"]) if done else None
    duration = datetime.timedelta(milliseconds=spawn.get("duration_ms") or 0)
    return recorded - duration, recorded


def analyse(records, config):
    """Join the records and attach signals to every spawn."""
    records = sorted(_dedupe(records), key=lambda r: r.get("ts") or "")
    finishes = {(r.get("session"), r.get("agent_id")): r for r in records if r["kind"] == "finish"}
    rejects = [r for r in records if r["kind"] == "reject"]

    spawns = []
    for position, record in enumerate(records):
        if record["kind"] == "spawn":
            spawn = dict(record, signals=set(), position=position)
            done = finishes.get((record.get("session"), record.get("agent_id")))
            if done:
                for field in ("tokens", "duration_ms", "tool_uses", "verdict"):
                    if spawn.get(field) is None and done.get(field) is not None:
                        spawn[field] = done[field]
            elif record.get("background"):
                spawn["signals"].add("unfinished")
            spawns.append(spawn)
        elif record["kind"] == "fail":
            spawns.append(dict(record, signals={"failed"}, position=position, agent_id=None))

    by_agent = {(s.get("session"), s["agent_id"]): s for s in spawns if s.get("agent_id")}

    for spawn in spawns:
        if spawn["kind"] != "spawn":
            continue
        if spawn.get("partial"):
            spawn["signals"].add("partial")
        if spawn.get("empty"):
            spawn["signals"].add("empty")
        if spawn.get("requested_model"):
            spawn["signals"].add("override")

    _rejected_first(spawns, rejects)
    _retries(spawns, finishes, config)
    _marks(records, by_agent)
    unlinked = _verdicts(spawns, records, by_agent)
    return Analysis(spawns, rejects, unlinked)


def _rejected_first(spawns, rejects):
    blocked = {
        (r.get("session"), r.get("prompt_id"), r.get("prompt_hash")): r.get("ts") or ""
        for r in rejects
        if r.get("enforced")
    }
    for spawn in spawns:
        key = (spawn.get("session"), spawn.get("prompt_id"), spawn.get("prompt_hash"))
        if spawn["kind"] == "spawn" and key in blocked and blocked[key] <= (spawn.get("ts") or ""):
            spawn["signals"].add("rejected_first")


def _retries(spawns, finishes, config):
    """An identical brief sent again after the first run ended: a retry, or an escalation."""
    groups = {}
    for spawn in spawns:
        if spawn["kind"] == "spawn" and spawn.get("prompt_hash"):
            groups.setdefault((spawn.get("session"), spawn["prompt_hash"]), []).append(spawn)
    for group in groups.values():
        for index, earlier in enumerate(group):
            _, ended = _window(earlier, finishes)
            if ended is None:
                continue
            for later in group[index + 1 :]:
                started, _ = _window(later, finishes)
                if started < ended:
                    continue
                earlier_rank = config.tier_rank(earlier.get("tier"))
                later_rank = config.tier_rank(later.get("tier"))
                if earlier_rank is None or later_rank is None or later_rank < earlier_rank:
                    continue
                earlier["signals"].add("escalated" if later_rank > earlier_rank else "retried")
                break


def _marks(records, by_agent):
    for record in records:
        if record["kind"] != "mark" or record.get("outcome") not in MARK_OUTCOMES:
            continue
        spawn = by_agent.get((record.get("session"), record.get("agent_id")))
        if spawn is not None:
            spawn["signals"].add(record["outcome"])


def _verdicts(spawns, records, by_agent):
    """Attach failing verdicts to the spawn they review, and find contradicted judges."""
    unlinked = []
    reviews = {}
    for spawn in spawns:
        verdict = spawn.get("verdict")
        if spawn["kind"] != "spawn" or not verdict:
            continue
        target = by_agent.get((spawn.get("session"), spawn.get("reviews")))
        if target is None:
            if verdict == "fail":
                unlinked.append(spawn)
            continue
        if verdict == "fail":
            target["signals"].add("review_failed")
        key = (spawn.get("session"), spawn.get("reviews"), spawn.get("prompt_id"))
        reviews.setdefault(key, []).append(spawn)

    for group in reviews.values():
        for earlier, later in zip(group, group[1:]):
            if earlier["verdict"] == later["verdict"]:
                continue
            between = records[earlier["position"] + 1 : later["position"]]
            # A worker run or a mark in between means the work changed: not a contradiction.
            changed = any(
                r["kind"] == "mark" or (r["kind"] == "spawn" and r.get("tier") != "judge")
                for r in between
                if r.get("session") == earlier.get("session")
            )
            if not changed:
                earlier["signals"].add("contradicted")
    return unlinked
