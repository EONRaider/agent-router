import pytest
from agent_router import config as config_module
from agent_router.config import Config, ConfigError, load, load_defaults, load_or_defaults


def make(overlay=None):
    return Config(load_defaults(), overlay)


def test_shipped_tiers_resolve_to_plugin_agents():
    config = make()
    resolution = config.resolve("agent-router:scout")
    assert (resolution.kind, resolution.tier.name) == ("tier", "scout")
    assert config.tiers["judge"].agent_type == "agent-router:judge"


def test_builtins_are_aliases_and_no_type_means_worker():
    config = make()
    assert config.resolve("Explore").tier.name == "scout"
    assert config.resolve("Plan").tier.name == "analyst"
    assert config.resolve("").tier.name == "worker"
    assert config.resolve(None).kind == "alias"


def test_other_plugins_and_listed_types_are_exempt():
    config = make({"version": 1, "exempt": ["vendored-agent"]})
    assert config.resolve("solid-coding:solid-reviewer").kind == "exempt"
    assert config.resolve("vendored-agent").kind == "exempt"
    assert config.resolve("claude-code-guide").kind == "exempt"


def test_unmapped_custom_agent_is_unknown():
    assert make().resolve("my-db-agent").kind == "unknown"
    mapped = make({"version": 1, "aliases": {"my-db-agent": "worker"}})
    assert mapped.resolve("my-db-agent").tier.name == "worker"


def test_remapped_tier_points_at_a_project_agent():
    config = make({"version": 1, "tiers": {"worker": {"model": "opus", "effort": "high"}}})
    worker = config.tiers["worker"]
    assert (worker.model, worker.effort, worker.remapped) == ("opus", "high", True)
    assert worker.agent_type == "router-worker"
    assert config.resolve("router-worker").tier is worker
    assert config.tiers["scout"].agent_type == "agent-router:scout"


def test_added_tier_ranks_like_the_tier_it_names():
    overlay = {"tiers": {"migrator": {"model": "sonnet", "effort": "high", "like": "worker"}}}
    config = make(overlay)
    assert config.resolve("router-migrator").tier.name == "migrator"
    assert config.tier_rank("migrator") == config.tier_rank("worker")


def test_vendored_project_remaps_every_shipped_tier():
    config = make({"version": 1, "vendored": True})
    assert all(tier.agent_type == f"router-{name}" for name, tier in config.tiers.items())


def test_model_rank_reads_aliases_and_full_ids():
    config = make()
    assert config.model_rank("haiku") < config.model_rank("sonnet") < config.model_rank("opus")
    assert config.model_rank("claude-opus-5-5") == config.model_rank("opus")
    assert config.model_rank("claude-fable-5-1") > config.model_rank("opus")
    assert config.model_rank("mystery") is None
    assert config.model_rank(None) is None
    assert make({"model_ranks": {"mystery": 5}}).model_rank("mystery-2") == 5


def test_review_rule_warns_until_the_project_opts_in():
    assert make().review_mode == "warn"
    assert make({"version": 1}).review_mode == "deny"
    assert make({"review_language": {"mode": "warn"}}).review_mode == "warn"


def test_review_phrases_can_be_added_and_removed():
    config = make({"review_language": {"add": ["Pentest"], "remove": ["audit"]}})
    assert "pentest" in config.review_phrases
    assert "audit" not in config.review_phrases


def test_logging_needs_an_overlay_and_can_be_switched_off():
    assert make().log_enabled is False
    assert make({"version": 1}).log_enabled is True
    assert make({"log": {"enabled": False}}).log_enabled is False


def test_missing_overlay_means_not_initialised(tmp_path):
    assert load(tmp_path).initialised is False


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"surprise": 1}',
        '{"strict": "yes"}',
        '{"version": 2}',
        '{"tiers": {"x y": {"model": "opus", "effort": "high"}}}',
        '{"tiers": {"extra": {"model": "opus"}}}',
        '{"tiers": {"worker": {"effort": "extreme"}}}',
        '{"tiers": {"extra": {"model": "opus", "effort": "high", "like": "nope"}}}',
        '{"review_language": {"mode": "sometimes"}}',
    ],
)
def test_unusable_overlay_falls_back_to_defaults_with_a_warning(write_overlay, project_dir, text):
    (project_dir / ".claude" / "agent-router.json").write_text(text, encoding="utf-8")
    with pytest.raises((ConfigError, KeyError)):
        load(project_dir)
    config, warning = load_or_defaults(project_dir)
    assert config.initialised is False
    assert warning.startswith("agent-router: overlay ignored")


def test_defaults_file_is_consistent():
    defaults = load_defaults()
    assert set(defaults["tier_order"]) == set(defaults["tiers"])
    assert set(defaults["prices_per_mtok"]) == set(defaults["model_ranks"])
    assert set(defaults["model_ladder"]) <= set(defaults["model_ranks"])
    assert config_module.DEFAULTS_PATH.name == "defaults.json"
