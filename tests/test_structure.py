"""The shipped tiers must stay pinned: a missing model or effort undoes the plugin."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# tier -> (model, effort)
SHIPPED_TIERS = {
    "scout": ("haiku", "low"),
    "worker": ("sonnet", "medium"),
    "analyst": ("sonnet", "high"),
    "judge": ("opus", "high"),
}
READ_ONLY_TIERS = ("scout", "judge")


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} has no frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_manifest_is_valid_json_with_required_fields():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "agent-router"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["license"] == "MIT"


@pytest.mark.parametrize("tier", sorted(SHIPPED_TIERS))
def test_tier_pins_model_and_effort(tier):
    fields = frontmatter(ROOT / "agents" / f"{tier}.md")
    assert fields["name"] == tier
    assert (fields["model"], fields["effort"]) == SHIPPED_TIERS[tier]
    assert fields["description"]


@pytest.mark.parametrize("tier", sorted(SHIPPED_TIERS))
def test_tier_cannot_spawn_agents(tier):
    fields = frontmatter(ROOT / "agents" / f"{tier}.md")
    assert "Agent" in fields["disallowedTools"].split(", ")


@pytest.mark.parametrize("tier", READ_ONLY_TIERS)
def test_read_only_tier_cannot_edit_files(tier):
    denied = frontmatter(ROOT / "agents" / f"{tier}.md")["disallowedTools"].split(", ")
    assert {"Write", "Edit", "NotebookEdit"} <= set(denied)


def test_judge_ends_with_a_verdict_line():
    body = (ROOT / "agents" / "judge.md").read_text(encoding="utf-8")
    assert "VERDICT: pass" in body and "Reviews: <agent-id>" in body


def test_no_agents_beyond_the_shipped_tiers():
    shipped = {path.stem for path in (ROOT / "agents").glob("*.md")}
    assert shipped == set(SHIPPED_TIERS)


def test_routing_skill_names_every_tier():
    skill = (ROOT / "skills" / "routing" / "SKILL.md").read_text(encoding="utf-8")
    assert frontmatter(ROOT / "skills" / "routing" / "SKILL.md")["name"] == "routing"
    for tier in SHIPPED_TIERS:
        assert f"agent-router:{tier}" in skill
