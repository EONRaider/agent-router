import io
import json
import subprocess
import sys
from pathlib import Path

from agent_router import events, log, setup

ROOT = Path(__file__).resolve().parent.parent


def at(payload, directory):
    return dict(payload, cwd=str(directory), scratchpad_dir=None)


def test_spawn_is_logged_once_even_when_two_hook_sets_fire(payload, project_dir, env):
    data = at(payload("post_foreground"), project_dir / "sub")
    events.post_tool_use(data, env)
    events.post_tool_use(data, env)
    records = log.read_records(project_dir)
    assert [r["kind"] for r in records] == ["spawn"]
    assert (project_dir / ".claude/agent-router/log" / f"{data['session_id']}.jsonl").is_file()


def test_nothing_is_written_to_a_project_that_has_not_opted_in(payload, tmp_path, env):
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    events.post_tool_use(at(payload("post_foreground"), repo), env)
    events.subagent_stop(at(payload("subagent_stop"), repo), env)
    assert not (repo / ".claude").exists()


def test_logging_can_be_switched_off(payload, write_overlay, env):
    root = write_overlay({"version": 1, "log": {"enabled": False}})
    events.post_tool_use(at(payload("post_foreground"), root), env)
    assert log.read_records(root) == []


def test_other_tools_are_ignored(payload, project_dir, env):
    data = dict(at(payload("post_foreground"), project_dir), tool_name="Bash")
    events.post_tool_use(data, env)
    assert log.read_records(project_dir) == []


def test_background_spawn_gets_a_finish_record(payload, project_dir, env):
    events.post_tool_use(at(payload("post_background"), project_dir), env)
    events.subagent_stop(at(payload("subagent_stop"), project_dir), env)
    assert [r["kind"] for r in log.read_records(project_dir)] == ["spawn", "finish"]


def test_failure_is_logged(payload, project_dir, env):
    data = at(payload("post_foreground"), project_dir)
    data.pop("tool_response")
    events.post_tool_use_failure(data, env)
    assert [r["kind"] for r in log.read_records(project_dir)] == ["fail"]


def test_session_start_points_an_unconfigured_project_at_init(tmp_path, env):
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    result = events.session_start({"session_id": "s", "cwd": str(repo), "source": "startup"}, env)
    assert "/agent-router:init" in result["stdout"]


def test_session_start_lists_the_projects_tiers(write_overlay, env):
    root = write_overlay({"tiers": {"worker": {"model": "opus", "effort": "high"}}})
    result = events.session_start({"session_id": "s", "cwd": str(root), "source": "startup"}, env)
    assert "`router-worker` (opus, high effort)" in result["stdout"]
    assert "`agent-router:scout` (haiku, low effort)" in result["stdout"]
    assert 'mark.py" --session s <agent-id> <outcome>' in result["stdout"]


def test_session_start_speaks_once_per_event(project_dir, env):
    data = {"session_id": "s", "cwd": str(project_dir), "source": "startup"}
    assert events.session_start(data, env) is not None
    assert events.session_start(data, env) is None


def test_init_creates_the_overlay_and_is_safe_to_repeat(tmp_path):
    (tmp_path / ".gitattributes").write_text("*.png binary", encoding="utf-8")
    first = setup.init(tmp_path)
    overlay = tmp_path / ".claude" / "agent-router.json"
    assert json.loads(overlay.read_text())["version"] == 1
    assert (tmp_path / ".claude" / "agents").is_dir()
    attributes = (tmp_path / ".gitattributes").read_text().splitlines()
    assert attributes == ["*.png binary", ".claude/agent-router/log/** linguist-generated"]
    overlay.write_text('{"version": 1, "strict": true}', encoding="utf-8")
    second = setup.init(tmp_path)
    assert json.loads(overlay.read_text())["strict"] is True
    assert len(first) == 3 and second == ["kept existing .claude/agent-router.json"]


def run_hook(event, stdin):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hook.py"), event],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_hook_script_fails_open_on_garbage():
    for event, stdin in (("post", "{not json"), ("nonsense", "{}"), ("post", "")):
        result = run_hook(event, stdin)
        assert result.returncode == 0 and result.stdout == ""


def test_hook_script_end_to_end(payload, project_dir, tmp_path):
    data = at(payload("post_foreground"), project_dir)
    scratch = tmp_path / "s" / "scratchpad"
    scratch.parent.mkdir()
    data["scratchpad_dir"] = str(scratch)
    result = run_hook("post", io.StringIO(json.dumps(data)).read())
    assert result.returncode == 0, result.stderr
    assert len(log.read_records(project_dir)) == 1


def pre_payload(payload, directory, **tool_input):
    data = at(payload("post_foreground"), directory)
    data.pop("tool_response")
    data["hook_event_name"] = "PreToolUse"
    data["tool_input"].update(tool_input)
    return data


def test_pre_hook_denies_with_the_documented_shape_and_logs_a_reject(payload, project_dir, env):
    data = pre_payload(payload, project_dir, subagent_type="agent-router:worker", model="haiku")
    output = events.pre_tool_use(data, env)["json"]["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and output["permissionDecision"] == "deny"
    assert "floor" in output["permissionDecisionReason"]
    (record,) = log.read_records(project_dir)
    assert (record["kind"], record["rule"], record["enforced"]) == ("reject", "model-floor", True)


def test_pre_hook_is_silent_for_an_allowed_spawn(payload, project_dir, env):
    assert events.pre_tool_use(pre_payload(payload, project_dir), env) is None
    assert log.read_records(project_dir) == []


def test_warn_mode_logs_but_does_not_deny(payload, write_overlay, env):
    root = write_overlay({"review_language": {"mode": "warn"}})
    data = pre_payload(payload, root, subagent_type="agent-router:worker", description="audit it")
    assert events.pre_tool_use(data, env) is None
    (record,) = log.read_records(root)
    assert (record["rule"], record["enforced"], record["phrase"]) == (
        "review-language",
        False,
        "audit",
    )


def test_second_hook_set_does_not_repeat_a_denial(payload, project_dir, env):
    data = pre_payload(payload, project_dir, subagent_type="agent-router:worker", model="haiku")
    assert events.pre_tool_use(data, env) is not None
    assert events.pre_tool_use(data, env) is None
    assert len(log.read_records(project_dir)) == 1


def test_remap_is_enforced_only_for_agents_present_at_session_start(payload, write_overlay, env):
    root = write_overlay({"tiers": {"worker": {"model": "opus", "effort": "high"}}})
    start = {
        "session_id": "11111111-2222-3333-4444-555555555555",
        "cwd": str(root),
        "source": "startup",
    }
    events.session_start(start, env)
    agents = root / ".claude" / "agents"
    agents.mkdir()
    (agents / "router-worker.md").write_text("x", encoding="utf-8")
    data = pre_payload(payload, root, subagent_type="agent-router:worker")
    assert events.pre_tool_use(data, env) is None  # created mid-session: cannot load yet

    fresh = dict(data, session_id="next-session", tool_use_id="toolu_next")
    events.session_start(dict(start, session_id="next-session"), env)
    denied = events.pre_tool_use(fresh, env)
    assert "router-worker" in denied["json"]["hookSpecificOutput"]["permissionDecisionReason"]


def test_denial_in_an_unconfigured_project_writes_nothing(payload, tmp_path, env):
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    data = pre_payload(payload, repo, subagent_type="agent-router:worker", model="haiku")
    assert events.pre_tool_use(data, env) is not None
    assert not (repo / ".claude").exists()
