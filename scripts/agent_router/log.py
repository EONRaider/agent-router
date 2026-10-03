"""Spawn log records and the append-only writer.

One JSON object per line, one file per session. The raw prompt is never stored: a record
holds the Agent tool's short `description`, the prompt's length and hashes of it.
"""

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

from . import SCHEMA_VERSION, STATE_RELPATH
from .project import safe_id

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

SUMMARY_MAX = 80
PREFIX_LENGTHS = (200, 500, 1000)
PARTIAL_MARKER = re.compile(r"^NOTE: this agent stopped at its \d+-turn limit")
VERDICT = re.compile(r"^VERDICT:\s*(pass|concerns|fail)\s*$", re.MULTILINE | re.IGNORECASE)
REVIEWS = re.compile(r"^Reviews:\s*([A-Za-z0-9_-]+)\s*$", re.MULTILINE)


def log_path(root, session_id):
    return Path(root) / STATE_RELPATH / "log" / f"{safe_id(session_id)}.jsonl"


def append(path, record):
    """Append one record as a single write, under an advisory lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise(text):
    return " ".join((text or "").split())


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def prompt_fingerprint(prompt):
    """Length and hashes of a prompt: enough to spot repeats, not to recover the text."""
    text = normalise(prompt)
    prefixes = {str(n): digest(text[:n]) for n in PREFIX_LENGTHS if len(text) >= n}
    return {"prompt_len": len(text), "prompt_hash": digest(text), "prefix_hashes": prefixes}


def summary(tool_input, config):
    if not config.log_summary:
        return None
    return normalise(tool_input.get("description"))[:SUMMARY_MAX] or None


def response_text(tool_response):
    content = tool_response.get("content") if isinstance(tool_response, dict) else None
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))


def parse_verdict(text):
    matches = VERDICT.findall(text or "")
    return matches[-1].lower() if matches else None


def parse_reviews(prompt):
    match = REVIEWS.search(prompt or "")
    return match.group(1) if match else None


def transcript_totals(path):
    """Cumulative tokens, duration and tool uses of a subagent, read from its transcript.

    A transcript repeats each assistant message once per content block, with the usage
    growing; the last line for a message id carries that message's final usage.
    """
    usage_by_message = {}
    tool_uses = 0
    first = last = None
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                stamp = entry.get("timestamp")
                if stamp:
                    first = first or stamp
                    last = stamp
                message = entry.get("message")
                if entry.get("type") != "assistant" or not isinstance(message, dict):
                    continue
                if message.get("usage"):
                    usage_by_message[message.get("id")] = message["usage"]
                content = message.get("content")
                if isinstance(content, list):
                    tool_uses += sum(1 for b in content if b.get("type") == "tool_use")
    except OSError:
        return None
    if not usage_by_message:
        return None
    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for usage in usage_by_message.values():
        tokens["input"] += usage.get("input_tokens") or 0
        tokens["output"] += usage.get("output_tokens") or 0
        tokens["cache_read"] += usage.get("cache_read_input_tokens") or 0
        tokens["cache_write"] += usage.get("cache_creation_input_tokens") or 0
    return {"tokens": tokens, "tool_uses": tool_uses, "duration_ms": _elapsed_ms(first, last)}


def _elapsed_ms(first, last):
    try:
        start = datetime.datetime.strptime(first, "%Y-%m-%dT%H:%M:%S.%fZ")
        end = datetime.datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError):
        return None
    return int((end - start).total_seconds() * 1000)


def subagent_transcript_path(payload, agent_id):
    """Where Claude Code keeps a subagent's transcript, derived from the session's own."""
    transcript = payload.get("transcript_path")
    if not transcript or not agent_id:
        return None
    session_dir = Path(transcript).with_suffix("")
    return session_dir / "subagents" / f"agent-{safe_id(agent_id)}.jsonl"


def _base(kind, payload):
    return {
        "v": SCHEMA_VERSION,
        "kind": kind,
        "ts": now(),
        "session": payload.get("session_id"),
        "prompt_id": payload.get("prompt_id"),
    }


def _routing_fields(tool_input, config):
    subagent_type = tool_input.get("subagent_type") or ""
    resolution = config.resolve(subagent_type)
    tier = resolution.tier
    return {
        "type": subagent_type or "general-purpose",
        "resolution": resolution.kind,
        "tier": tier.name if tier else None,
        "requested_model": tool_input.get("model"),
        # Aliases and exempt agents run at an effort this plugin does not set.
        "effort": tier.effort if tier and resolution.kind == "tier" else "unknown",
    }


def spawn_record(payload, config):
    """The record written when an Agent call returns."""
    tool_input = payload.get("tool_input") or {}
    response = payload.get("tool_response")
    response = response if isinstance(response, dict) else {}
    text = response_text(response)
    background = bool(response.get("isAsync")) or response.get("status") == "async_launched"
    agent_id = response.get("agentId")

    record = _base("spawn", payload)
    record.update(_routing_fields(tool_input, config))
    record.update(prompt_fingerprint(tool_input.get("prompt")))
    record.update(
        {
            "tool_use_id": payload.get("tool_use_id"),
            "agent_id": agent_id,
            "parent_agent_id": payload.get("agent_id"),
            "resolved_model": response.get("resolvedModel"),
            "status": response.get("status"),
            "background": background,
            "partial": bool(PARTIAL_MARKER.match(text)),
            "empty": not background and not text.strip(),
            "summary": summary(tool_input, config),
            "context_tokens": response.get("totalTokens"),
            "duration_ms": response.get("totalDurationMs"),
            "tool_uses": response.get("totalToolUseCount"),
            "tokens": None,
            "reviews": parse_reviews(tool_input.get("prompt")),
            "verdict": parse_verdict(text) if record["tier"] == "judge" else None,
        }
    )
    if not background:
        totals = transcript_totals(subagent_transcript_path(payload, agent_id) or "")
        if totals:
            record["tokens"] = totals["tokens"]
    return record


def finish_record(payload, config):
    """The record written when a subagent stops. Background spawns get their totals here."""
    agent_type = payload.get("agent_type") or ""
    resolution = config.resolve(agent_type)
    totals = transcript_totals(payload.get("agent_transcript_path") or "") or {}
    record = _base("finish", payload)
    record.update(
        {
            "agent_id": payload.get("agent_id"),
            "type": agent_type,
            "tier": resolution.tier.name if resolution.tier else None,
            "tokens": totals.get("tokens"),
            "duration_ms": totals.get("duration_ms"),
            "tool_uses": totals.get("tool_uses"),
            "verdict": parse_verdict(payload.get("last_assistant_message"))
            if resolution.tier and resolution.tier.name == "judge"
            else None,
        }
    )
    return record


def fail_record(payload, config):
    """The record written when an Agent call errors out."""
    tool_input = payload.get("tool_input") or {}
    record = _base("fail", payload)
    record.update(_routing_fields(tool_input, config))
    record.update(
        {
            "tool_use_id": payload.get("tool_use_id"),
            "summary": summary(tool_input, config),
            "interrupted": bool(payload.get("is_interrupt")),
        }
    )
    return record


def read_records(root):
    """Every record in a project's log, oldest file first, skipping unreadable lines."""
    directory = Path(root) / STATE_RELPATH / "log"
    records = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("v") == SCHEMA_VERSION:
                records.append(record)
    return records
