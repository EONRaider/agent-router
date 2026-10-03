from agent_router import sync
from agent_router.config import Config, load_defaults

OVERLAY = {
    "tiers": {
        "worker": {"model": "opus", "effort": "high"},
        "migrator": {"model": "sonnet", "effort": "high", "like": "worker"},
    }
}


def config(overlay):
    return Config(load_defaults(), overlay)


def test_only_remapped_and_added_tiers_are_generated(tmp_path):
    changes = sync.sync(tmp_path, config(OVERLAY))
    names = sorted(p.name for p in (tmp_path / ".claude" / "agents").iterdir())
    assert names == ["router-migrator.md", "router-worker.md"]
    assert len(changes) == 2


def test_generated_agent_pins_the_overlay_sizing_and_keeps_the_shipped_body(tmp_path):
    sync.sync(tmp_path, config(OVERLAY))
    fields, body = sync.parse_agent((tmp_path / ".claude/agents/router-worker.md").read_text())
    assert (fields["name"], fields["model"], fields["effort"]) == ("router-worker", "opus", "high")
    assert fields["disallowedTools"] == "Agent"
    assert "(opus, high effort)" in fields["description"]
    assert "You are a worker" in body and sync.MARKER in body


def test_sync_is_idempotent(tmp_path):
    sync.sync(tmp_path, config(OVERLAY))
    assert sync.sync(tmp_path, config(OVERLAY)) == []


def test_stale_generated_agents_are_removed_but_hand_written_ones_are_kept(tmp_path):
    sync.sync(tmp_path, config(OVERLAY))
    mine = tmp_path / ".claude" / "agents" / "router-custom.md"
    mine.write_text("---\nname: router-custom\n---\nmine\n", encoding="utf-8")
    changes = sync.sync(tmp_path, config({"version": 1}))
    assert sorted(changes) == [
        "removed .claude/agents/router-migrator.md",
        "removed .claude/agents/router-worker.md",
    ]
    assert mine.is_file()


def test_a_hand_written_file_with_a_tier_name_is_not_overwritten(tmp_path):
    path = tmp_path / ".claude" / "agents" / "router-worker.md"
    path.parent.mkdir(parents=True)
    path.write_text("mine", encoding="utf-8")
    changes = sync.sync(tmp_path, config(OVERLAY))
    assert path.read_text() == "mine"
    assert any(change.startswith("skipped") for change in changes)


def test_vendored_project_generates_all_shipped_tiers(tmp_path):
    sync.sync(tmp_path, config({"vendored": True}))
    names = sorted(p.stem for p in (tmp_path / ".claude" / "agents").iterdir())
    assert names == ["router-analyst", "router-judge", "router-scout", "router-worker"]
    judge = (tmp_path / ".claude/agents/router-judge.md").read_text()
    assert "VERDICT: pass" in judge and "model: opus" in judge


def test_project_can_describe_its_own_tier(tmp_path):
    overlay = {"tiers": {"migrator": dict(OVERLAY["tiers"]["migrator"], description="DB work.")}}
    sync.sync(tmp_path, config(overlay), config(overlay).tier_descriptions)
    fields, _ = sync.parse_agent((tmp_path / ".claude/agents/router-migrator.md").read_text())
    assert fields["description"] == "DB work."
