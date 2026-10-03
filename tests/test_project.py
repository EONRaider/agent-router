from agent_router import project


def test_root_is_the_nearest_ancestor_with_an_overlay(project_dir):
    assert project.find_root(project_dir / "sub" / "deep") == project_dir


def test_overlay_beats_a_nested_git_directory(project_dir):
    (project_dir / "sub" / ".git").mkdir()
    assert project.find_root(project_dir / "sub" / "deep") == project_dir


def test_without_an_overlay_the_git_root_is_used(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "a" / "b").mkdir(parents=True)
    assert project.find_root(tmp_path / "repo" / "a" / "b") == tmp_path / "repo"


def test_git_worktree_pointer_file_counts_as_a_root(tmp_path):
    worktree = tmp_path / "wt"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt", encoding="utf-8")
    assert project.find_root(worktree / "src") == worktree


def test_outside_any_repo_the_fallback_is_used(tmp_path):
    start = tmp_path / "loose" / "dir"
    start.mkdir(parents=True)
    assert project.find_root(start, tmp_path / "loose") == tmp_path / "loose"
    assert project.find_root(start) == start


def test_session_root_is_resolved_once_then_cached(project_dir, env):
    payload = {"session_id": "s1", "cwd": str(project_dir / "sub")}
    assert project.session_root(payload, env) == project_dir
    moved = dict(payload, cwd="/somewhere/else/entirely")
    assert project.session_root(moved, env) == project_dir


def test_sessions_do_not_share_a_cache(project_dir, tmp_path, env):
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    assert project.session_root({"session_id": "s1", "cwd": str(project_dir)}, env) == project_dir
    assert project.session_root({"session_id": "s2", "cwd": str(other)}, env) == other


def test_scratchpad_dir_is_preferred_for_the_cache(tmp_path, env):
    scratchpad = tmp_path / "session" / "scratchpad"
    scratchpad.parent.mkdir()
    cache = project.cache_dir({"session_id": "s1", "scratchpad_dir": str(scratchpad)}, env)
    assert cache == scratchpad / "agent-router"


def test_only_the_first_claim_of_a_key_succeeds(env):
    payload = {"session_id": "s1"}
    assert project.claim(payload, "post-toolu_1", env) is True
    assert project.claim(payload, "post-toolu_1", env) is False
    assert project.claim(payload, "post-toolu_2", env) is True
    assert project.claim({"session_id": "s2"}, "post-toolu_1", env) is True


def test_ids_cannot_escape_the_directory():
    assert "/" not in project.safe_id("../../etc/passwd")
    assert project.safe_id(None) == "unknown"
