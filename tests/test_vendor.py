import json
import subprocess
import sys
from pathlib import Path

import pytest
from agent_router import config as config_module
from agent_router import log, sync, vendor

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
VERSION = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]


def do_vendor(project_dir):
    version = vendor.vendor(project_dir, config_module.read_overlay(project_dir))
    updated = config_module.load(project_dir)
    sync.sync(project_dir, updated)
    return version


def test_vendor_copies_a_runnable_plugin_into_the_project(project_dir):
    assert do_vendor(project_dir) == VERSION
    target = project_dir / ".claude/agent-router/vendor"
    for name in ("hook.py", "mark.py", "router.py", "agent_router/policy.py", "agents/judge.md"):
        assert (target / name).is_file(), name
    assert (target / "VERSION").read_text().strip() == VERSION
    assert not list(target.rglob("__pycache__"))
    assert json.loads((project_dir / ".claude/agent-router.json").read_text())["vendored"] is True
    agents = sorted(p.stem for p in (project_dir / ".claude/agents").glob("router-*.md"))
    assert agents == ["router-analyst", "router-judge", "router-scout", "router-worker"]
    attributes = (project_dir / ".gitattributes").read_text()
    assert ".claude/agent-router/vendor/** linguist-generated" in attributes


def test_settings_are_merged_not_replaced_and_rerun_changes_nothing(project_dir):
    settings = project_dir / ".claude/settings.json"
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./mine.sh"}]}
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PreToolUse": [mine]}}),
        encoding="utf-8",
    )
    do_vendor(project_dir)
    first = settings.read_text()
    data = json.loads(first)
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert data["hooks"]["PreToolUse"][0] == mine and len(data["hooks"]["PreToolUse"]) == 2
    assert set(data["hooks"]) == set(vendor.EVENTS)
    assert data["hooks"]["PreToolUse"][1]["matcher"] == "Agent"
    assert "matcher" not in data["hooks"]["SubagentStop"][0]
    do_vendor(project_dir)
    assert settings.read_text() == first


def test_broken_settings_file_is_left_alone(project_dir):
    settings = project_dir / ".claude/settings.json"
    settings.write_text("{oops", encoding="utf-8")
    with pytest.raises(vendor.VendorError):
        do_vendor(project_dir)
    assert settings.read_text() == "{oops"


def run_shell(command, cwd, stdin, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    env.update(env_extra or {})
    return subprocess.run(
        ["sh", "-c", command], cwd=cwd, input=stdin, capture_output=True, text=True, env=env
    )


def test_vendored_hook_runs_without_the_plugin_and_enforces(project_dir, tmp_path):
    do_vendor(project_dir)
    subprocess.run(["git", "init", "-q", str(project_dir)], check=True)
    payload = json.loads((FIXTURES / "post_foreground.json").read_text())
    payload.pop("tool_response")
    payload.update(hook_event_name="PreToolUse", cwd=str(project_dir / "sub"))
    payload["scratchpad_dir"] = str(tmp_path / "scratchpad")
    payload["tool_input"].update(subagent_type="router-worker", model="haiku")
    result = run_shell(vendor.hook_command("pre"), project_dir / "sub", json.dumps(payload))
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert [r["kind"] for r in log.read_records(project_dir)] == ["reject"]


def test_vendored_command_is_a_silent_no_op_when_nothing_is_vendored(tmp_path):
    result = run_shell(vendor.hook_command("pre"), tmp_path, "{}")
    assert (result.returncode, result.stdout) == (0, "")


def test_vendored_command_is_a_silent_no_op_without_python(project_dir, tmp_path):
    do_vendor(project_dir)
    empty = tmp_path / "bin"
    empty.mkdir()
    command = vendor.hook_command("pre")
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=project_dir,
        input="{}",
        capture_output=True,
        text=True,
        env={"PATH": str(empty), "CLAUDE_PROJECT_DIR": str(project_dir)},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_vendored_copy_can_generate_agents_itself(project_dir):
    do_vendor(project_dir)
    for path in (project_dir / ".claude/agents").glob("router-*.md"):
        path.unlink()
    router = project_dir / ".claude/agent-router/vendor/router.py"
    result = subprocess.run(
        [sys.executable, str(router), "sync", "--root", str(project_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(list((project_dir / ".claude/agents").glob("router-*.md"))) == 4


def test_stale_vendored_copy_is_noted(project_dir):
    do_vendor(project_dir)
    assert vendor.stale_note(project_dir) is None
    (project_dir / ".claude/agent-router/vendor/VERSION").write_text("0.0.1\n")
    assert "0.0.1" in vendor.stale_note(project_dir) and VERSION in vendor.stale_note(project_dir)
