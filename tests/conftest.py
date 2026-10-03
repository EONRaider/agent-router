import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def payload():
    """Load a sanitised hook payload captured from Claude Code."""

    def load(name):
        return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

    return load


@pytest.fixture
def project_dir(tmp_path):
    """An opted-in git project with a nested directory."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir()
    (root / "sub" / "deep").mkdir(parents=True)
    (root / ".claude" / "agent-router.json").write_text('{"version": 1}', encoding="utf-8")
    return root


@pytest.fixture
def write_overlay(project_dir):
    def write(overlay):
        path = project_dir / ".claude" / "agent-router.json"
        path.write_text(json.dumps(overlay), encoding="utf-8")
        return project_dir

    return write


@pytest.fixture
def env(tmp_path):
    """Hook environment whose per-session cache lives under the test's temp directory."""
    data = tmp_path / "plugin-data"
    data.mkdir()
    return {"CLAUDE_PLUGIN_DATA": str(data)}
