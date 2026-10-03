"""Applying a proposal's overlay edit and remembering what the user decided."""

import copy
import json
from pathlib import Path

from . import OVERLAY_RELPATH, SCHEMA_VERSION, STATE_RELPATH
from .config import validate_overlay
from .log import append, now

DECISIONS_RELPATH = f"{STATE_RELPATH}/decisions.jsonl"


def apply_edit(overlay, edit):
    """A copy of `overlay` with a proposal's edit applied."""
    result = copy.deepcopy(overlay)
    for op in edit:
        if op["op"] == "remove_trial":
            result["trials"] = [t for t in result.get("trials", []) if t.get("tier") != op["tier"]]
            continue
        *parents, leaf = op["path"]
        target = result
        for key in parents:
            target = target.setdefault(key, {})
        if op["op"] == "set":
            target[leaf] = op["value"]
        elif op["op"] == "append":
            items = target.setdefault(leaf, [])
            if op["value"] not in items:
                items.append(op["value"])
        else:
            raise ValueError(f"unknown edit operation {op['op']!r}")
    validate_overlay(result)
    return result


def write_overlay(root, overlay):
    path = Path(root) / OVERLAY_RELPATH
    path.write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")


def read_decisions(root):
    path = Path(root) / DECISIONS_RELPATH
    decisions = []
    if not path.is_file():
        return decisions
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            decision = json.loads(line)
        except ValueError:
            continue
        if isinstance(decision, dict) and decision.get("id"):
            decisions.append(decision)
    return decisions


def record_decision(root, proposal, decision):
    """Append an accepted or rejected proposal, with the evidence it was decided on."""
    entry = {
        "v": SCHEMA_VERSION,
        "id": proposal["id"],
        "rule": proposal["rule"],
        "tier": proposal["tier"],
        "decision": decision,
        "ts": now(),
        "title": proposal["title"],
        "evidence": proposal["evidence"],
    }
    append(Path(root) / DECISIONS_RELPATH, entry)
    return entry
