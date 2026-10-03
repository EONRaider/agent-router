"""Repository-level checks that do not need Claude Code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMMUNITY_FILES = [
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "RELEASING.md",
]


def test_community_files_exist():
    missing = [name for name in COMMUNITY_FILES if not (ROOT / name).is_file()]
    assert not missing, missing
