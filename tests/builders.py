"""Small builders for log records, so rule tests read as scenarios."""

import datetime
import itertools

_counter = itertools.count(1)
EPOCH = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)


def stamp(minutes):
    return (EPOCH + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def spawn(tier="worker", minute=None, **fields):
    n = next(_counter)
    minute = n if minute is None else minute
    record = {
        "v": 1,
        "kind": "spawn",
        "ts": stamp(minute),
        "session": "s1",
        "prompt_id": f"p{n}",
        "tool_use_id": f"toolu_{n}",
        "agent_id": f"agent{n}",
        "parent_agent_id": None,
        "type": f"agent-router:{tier}",
        "resolution": "tier",
        "tier": tier,
        "requested_model": None,
        "resolved_model": {"scout": "claude-haiku-4-5", "judge": "claude-opus-5-5"}.get(
            tier, "claude-sonnet-5"
        ),
        "effort": {"scout": "low", "worker": "medium"}.get(tier, "high"),
        "status": "completed",
        "background": False,
        "partial": False,
        "empty": False,
        "summary": f"task {n}",
        "context_tokens": 9000,
        "duration_ms": 10_000,
        "tool_uses": 2,
        "tokens": {"input": 100, "output": 1000, "cache_read": 10_000, "cache_write": 2000},
        "prompt_len": 80,
        "prompt_hash": f"hash{n}",
        "prefix_hashes": {},
        "reviews": None,
        "verdict": None,
    }
    record.update(fields)
    return record


def finish(agent_id, minute, **fields):
    record = {"v": 1, "kind": "finish", "ts": stamp(minute), "session": "s1", "agent_id": agent_id}
    record.update({"tokens": None, "duration_ms": None, "tool_uses": None, "verdict": None})
    record.update(fields)
    return record


def reject(tier="worker", minute=None, rule="review-language", phrase="review", **fields):
    n = next(_counter)
    record = {
        "v": 1,
        "kind": "reject",
        "ts": stamp(n if minute is None else minute),
        "session": "s1",
        "prompt_id": f"p{n}",
        "tool_use_id": f"toolu_{n}",
        "type": f"agent-router:{tier}",
        "resolution": "tier",
        "tier": tier,
        "requested_model": None,
        "rule": rule,
        "phrase": phrase,
        "enforced": True,
        "summary": f"rejected {n}",
        "prompt_hash": f"hash{n}",
    }
    record.update(fields)
    return record


def mark(agent_id, outcome, minute=10_000):
    return {
        "v": 1,
        "kind": "mark",
        "ts": stamp(minute),
        "session": "s1",
        "agent_id": agent_id,
        "outcome": outcome,
    }


def fail(tier="worker", minute=None):
    n = next(_counter)
    return {
        "v": 1,
        "kind": "fail",
        "ts": stamp(n if minute is None else minute),
        "session": "s1",
        "prompt_id": f"p{n}",
        "tool_use_id": f"toolu_{n}",
        "type": f"agent-router:{tier}",
        "resolution": "tier",
        "tier": tier,
        "summary": f"failed {n}",
    }


def clean(tier, count, **fields):
    return [spawn(tier, **fields) for _ in range(count)]
