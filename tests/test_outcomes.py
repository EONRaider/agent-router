"""Outcome signals derived from log records."""

from agent_router import outcomes
from agent_router.config import Config, load_defaults
from builders import fail, finish, mark, reject, spawn

CONFIG = Config(load_defaults(), {"version": 1})


def analyse(*records):
    return outcomes.analyse(list(records), CONFIG)


def signals(result, record):
    return next(s for s in result.spawns if s["agent_id"] == record["agent_id"])["signals"]


def test_clean_spawn_has_no_signals():
    one = spawn()
    assert signals(analyse(one), one) == set()


def test_rejected_first_attempt_is_linked_by_turn_and_prompt():
    blocked = reject("scout", minute=1, prompt_id="p", prompt_hash="h")
    retry = spawn("judge", minute=2, prompt_id="p", prompt_hash="h")
    other = spawn("judge", minute=3, prompt_id="p", prompt_hash="different")
    result = analyse(blocked, retry, other)
    assert signals(result, retry) == {"rejected_first"}
    assert signals(result, other) == set()


def test_warn_only_match_is_not_a_rejected_first_attempt():
    warned = reject("worker", minute=1, prompt_id="p", prompt_hash="h", enforced=False)
    went_ahead = spawn("worker", minute=2, prompt_id="p", prompt_hash="h")
    assert signals(analyse(warned, went_ahead), went_ahead) == set()


def test_model_override_is_a_signal_but_not_a_negative_one():
    one = spawn("worker", requested_model="opus", resolved_model="claude-opus-5-5")
    result = analyse(one)
    assert signals(result, one) == {"override"}
    assert not outcomes.is_incident(result.spawns[0])


def test_partial_and_empty_output_are_incidents():
    partial, empty = spawn(partial=True), spawn(empty=True)
    result = analyse(partial, empty)
    assert signals(result, partial) == {"partial"} and signals(result, empty) == {"empty"}
    assert all(outcomes.is_incident(s) for s in result.spawns)


def test_failed_call_counts_against_its_tier():
    result = analyse(fail("worker"))
    assert result.spawns[0]["signals"] == {"failed"} and result.spawns[0]["tier"] == "worker"


def test_same_prompt_later_at_a_higher_tier_is_an_escalation():
    first = spawn("worker", minute=10, prompt_hash="h")
    second = spawn("judge", minute=12, prompt_hash="h")
    result = analyse(first, second)
    assert signals(result, first) == {"escalated"}
    assert signals(result, second) == set()


def test_same_prompt_later_at_the_same_tier_is_a_retry():
    first = spawn("worker", minute=10, prompt_hash="h")
    second = spawn("worker", minute=12, prompt_hash="h")
    assert signals(analyse(first, second), first) == {"retried"}


def test_parallel_fan_out_is_not_a_retry():
    # Both ended at minute 10 after running for five minutes: they overlapped.
    first = spawn("worker", minute=10, prompt_hash="h", duration_ms=300_000)
    second = spawn("worker", minute=10, prompt_hash="h", duration_ms=300_000)
    result = analyse(first, second)
    assert signals(result, first) == set() and signals(result, second) == set()


def test_shared_preamble_with_different_tasks_is_not_a_retry():
    first = spawn("worker", minute=10, prompt_hash="a", prefix_hashes={"500": "same"})
    second = spawn("worker", minute=12, prompt_hash="b", prefix_hashes={"500": "same"})
    assert signals(analyse(first, second), first) == set()


def test_same_prompt_in_another_session_is_not_a_retry():
    first = spawn("worker", minute=10, prompt_hash="h")
    second = spawn("worker", minute=12, prompt_hash="h", session="s2")
    assert signals(analyse(first, second), first) == set()


def test_marks_attach_to_the_agent_they_name():
    one, two = spawn(), spawn()
    result = analyse(one, two, mark(one["agent_id"], "redone"), mark("nobody", "redone"))
    assert signals(result, one) == {"redone"} and signals(result, two) == set()


def test_linked_failing_verdict_lands_on_the_reviewed_spawn():
    work = spawn("worker", minute=1)
    review = spawn("judge", minute=2, verdict="fail", reviews=work["agent_id"])
    result = analyse(work, review)
    assert signals(result, work) == {"review_failed"}
    assert signals(result, review) == set()
    assert result.unlinked_verdicts == []


def test_passing_or_concerned_verdicts_are_not_incidents():
    work = spawn("worker", minute=1)
    result = analyse(
        work,
        spawn("judge", minute=2, verdict="pass", reviews=work["agent_id"]),
        spawn("judge", minute=3, verdict="concerns", reviews=work["agent_id"], prompt_id="other"),
    )
    assert signals(result, work) == set()


def test_unlinked_failing_verdict_is_shown_but_blames_nobody():
    work = spawn("worker", minute=1)
    review = spawn("judge", minute=2, verdict="fail")
    result = analyse(work, review)
    assert signals(result, work) == set()
    assert [v["agent_id"] for v in result.unlinked_verdicts] == [review["agent_id"]]


def test_background_judge_verdict_comes_from_its_finish_record():
    work = spawn("worker", minute=1)
    review = spawn("judge", minute=2, background=True, reviews=work["agent_id"], tokens=None)
    done = finish(review["agent_id"], 5, verdict="fail", tokens={"input": 1, "output": 2})
    result = analyse(work, review, done)
    assert signals(result, work) == {"review_failed"}
    merged = next(s for s in result.spawns if s["agent_id"] == review["agent_id"])
    assert merged["tokens"] == {"input": 1, "output": 2}


def test_two_differing_verdicts_in_one_turn_are_a_contradiction():
    work = spawn("worker", minute=1)
    first = spawn("judge", minute=2, verdict="pass", reviews=work["agent_id"], prompt_id="t")
    second = spawn("judge", minute=3, verdict="fail", reviews=work["agent_id"], prompt_id="t")
    result = analyse(work, first, second)
    assert signals(result, first) == {"contradicted"}
    assert signals(result, second) == set()


def test_fail_then_fix_then_pass_is_not_a_contradiction():
    work = spawn("worker", minute=1)
    first = spawn("judge", minute=2, verdict="fail", reviews=work["agent_id"], prompt_id="t")
    fix = spawn("worker", minute=3, prompt_id="t")
    second = spawn("judge", minute=4, verdict="pass", reviews=work["agent_id"], prompt_id="t")
    result = analyse(work, first, fix, second)
    assert signals(result, first) == set()


def test_verdicts_in_different_turns_are_not_a_contradiction():
    work = spawn("worker", minute=1)
    first = spawn("judge", minute=2, verdict="fail", reviews=work["agent_id"], prompt_id="t1")
    second = spawn("judge", minute=3, verdict="pass", reviews=work["agent_id"], prompt_id="t2")
    assert signals(analyse(work, first, second), first) == set()


def test_background_spawn_without_a_finish_is_unfinished_not_an_incident():
    launched = spawn(background=True, status="async_launched", tokens=None, duration_ms=None)
    result = analyse(launched)
    assert signals(result, launched) == {"unfinished"}
    assert not outcomes.is_incident(result.spawns[0])


def test_duplicate_records_from_two_hook_sets_are_dropped():
    one = spawn()
    assert len(analyse(one, dict(one)).spawns) == 1
