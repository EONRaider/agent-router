import json
import subprocess
import sys
from pathlib import Path

import pytest
from agent_router import config as config_module
from agent_router import decisions, log, report
from builders import clean, mark, reject, spawn

ROOT = Path(__file__).resolve().parent.parent


def fill(project_dir, records):
    for record in records:
        log.append(log.log_path(project_dir, record["session"]), record)


def redone(tier, count):
    records = clean(tier, count)
    return records + [mark(r["agent_id"], "redone") for r in records]


def router(project_dir, *arguments):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "router.py"),
            *arguments,
            "--root",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_empty_log_says_so(project_dir):
    config = config_module.load(project_dir)
    assert "empty" in report.render(report.build(project_dir, config), config)


def test_report_separates_tiers_from_other_agents_and_prices_spend(project_dir):
    fill(
        project_dir,
        clean("worker", 3)
        + [spawn("scout", resolution="alias", type="Explore")]
        + [reject("worker", phrase="audit"), reject("worker", phrase="audit", enforced=False)],
    )
    config = config_module.load(project_dir)
    data = report.build(project_dir, config)
    assert data["tiers"]["worker"]["spawns"] == 3 and "scout" not in data["tiers"]
    assert data["other_agents"]["Explore"]["spawns"] == 1
    text = report.render(data, config)
    assert "worker (sonnet, medium): 3 spawns" in text
    assert "Explore: 1 spawns" in text
    assert "review-language ('audit'): 1 rejected" in text and "1 warned only" in text
    # 3 spawns x (100 in, 1000 out, 10k cache read, 2k cache write) at Sonnet list prices
    assert data["tiers"]["worker"]["spend"] == pytest.approx(3 * 0.0172)
    assert "No proposals" in text


def test_report_lists_proposals_with_evidence_and_edit(project_dir):
    fill(project_dir, clean("worker", 17) + redone("worker", 3))
    config = config_module.load(project_dir)
    text = report.render(report.build(project_dir, config), config)
    assert "Raise worker effort from medium to high" in text
    assert "Evidence: spawns=20, incidents=3, rate=0.15" in text
    assert '"path": ["tiers", "worker", "effort"]' in text


def test_accepting_edits_the_overlay_generates_the_agent_and_remembers(project_dir):
    fill(project_dir, clean("worker", 17) + redone("worker", 3))
    proposal_id = json.loads(router(project_dir, "report", "--json").stdout)["proposals"][0]["id"]
    result = router(project_dir, "decide", proposal_id, "accept")
    assert result.returncode == 0, result.stderr
    overlay = json.loads((project_dir / ".claude/agent-router.json").read_text())
    assert overlay["tiers"]["worker"] == {"effort": "high"}
    agent = (project_dir / ".claude/agents/router-worker.md").read_text()
    assert "effort: high" in agent and "model: sonnet" in agent
    (decision,) = decisions.read_decisions(project_dir)
    assert (decision["decision"], decision["tier"]) == ("accepted", "worker")
    assert json.loads(router(project_dir, "report", "--json").stdout)["proposals"] == []


def test_rejecting_leaves_the_overlay_alone_and_silences_the_proposal(project_dir):
    fill(project_dir, clean("worker", 17) + redone("worker", 3))
    before = (project_dir / ".claude/agent-router.json").read_text()
    proposal_id = json.loads(router(project_dir, "report", "--json").stdout)["proposals"][0]["id"]
    assert router(project_dir, "decide", proposal_id, "reject").returncode == 0
    assert (project_dir / ".claude/agent-router.json").read_text() == before
    assert json.loads(router(project_dir, "report", "--json").stdout)["proposals"] == []


def test_unknown_proposal_id_and_bad_usage_fail_cleanly(project_dir):
    assert router(project_dir, "decide", "nope", "accept").returncode == 1
    assert router(project_dir, "decide", "nope").returncode == 2


def test_commands_refuse_a_project_that_has_not_opted_in(tmp_path):
    assert router(tmp_path, "report").returncode == 1


def test_apply_edit_operations():
    overlay = {"version": 1, "trials": [{"tier": "worker"}, {"tier": "scout"}]}
    edit = [
        {"op": "set", "path": ["tiers", "worker", "effort"], "value": "low"},
        {"op": "append", "path": ["review_language", "remove"], "value": "audit"},
        {"op": "append", "path": ["review_language", "remove"], "value": "audit"},
        {"op": "remove_trial", "tier": "worker"},
    ]
    result = decisions.apply_edit(overlay, edit)
    assert result["tiers"]["worker"]["effort"] == "low"
    assert result["review_language"]["remove"] == ["audit"]
    assert result["trials"] == [{"tier": "scout"}]
    assert "tiers" not in overlay


def test_mark_script_appends_to_the_sessions_log(project_dir):
    command = [sys.executable, str(ROOT / "scripts" / "mark.py"), "--root", str(project_dir)]
    done = subprocess.run(
        [*command, "--session", "s1", "agent42", "redone"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    (record,) = log.read_records(project_dir)
    assert (record["kind"], record["agent_id"], record["outcome"]) == ("mark", "agent42", "redone")
    bad = subprocess.run(
        [*command, "--session", "s1", "../x", "redone"], capture_output=True, text=True
    )
    assert bad.returncode == 2
    worse = subprocess.run(
        [*command, "--session", "s1", "agent42", "great"], capture_output=True, text=True
    )
    assert worse.returncode == 2


def test_summaries_hold_no_more_than_the_logged_descriptions(project_dir):
    fill(project_dir, [spawn("worker", requested_model="opus"), reject("worker")])
    data = report.summaries(project_dir, config_module.load(project_dir))
    assert len(data["overrides"]) == 1 and len(data["rejections"]) == 1
    assert set(data["overrides"][0]) == {"tier", "model", "summary"}
