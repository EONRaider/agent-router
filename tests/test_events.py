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
