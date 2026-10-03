import json
import shutil
from pathlib import Path

from agent_router import log
from agent_router.config import Config, load_defaults

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def config(overlay=None):
    return Config(load_defaults(), overlay or {"version": 1})


def test_foreground_spawn_record(payload):
    record = log.spawn_record(payload("post_foreground"), config())
    assert record["kind"] == "spawn"
    assert (record["type"], record["tier"], record["resolution"]) == (
        "agent-router:scout",
        "scout",
        "tier",
    )
    assert record["resolved_model"] == "claude-haiku-4-5-20251001"
    assert record["effort"] == "low"
    assert record["agent_id"] == "a928c9bf16b62279b"
    assert (record["duration_ms"], record["tool_uses"], record["context_tokens"]) == (6514, 1, 7733)
    assert record["background"] is False and record["partial"] is False
    assert record["summary"] == "Read a.txt from current directory"


def test_record_never_contains_the_prompt(payload):
    data = payload("post_foreground")
    record = log.spawn_record(data, config())
    assert data["tool_input"]["prompt"] not in json.dumps(record)
    assert record["prompt_len"] == len(data["tool_input"]["prompt"])
    assert len(record["prompt_hash"]) == 16


def test_summary_can_be_left_out(payload):
    record = log.spawn_record(payload("post_foreground"), config({"log": {"summary": False}}))
    assert record["summary"] is None


def test_summary_is_capped(payload):
    data = payload("post_foreground")
    data["tool_input"]["description"] = "x" * 500
    assert len(log.spawn_record(data, config())["summary"]) == log.SUMMARY_MAX


def test_background_spawn_is_flagged_and_has_no_totals(payload):
    record = log.spawn_record(payload("post_background"), config())
    assert record["background"] is True and record["status"] == "async_launched"
    assert record["tokens"] is None and record["duration_ms"] is None
    assert record["empty"] is False


def test_turn_limited_spawn_is_partial_and_override_is_kept(payload):
    record = log.spawn_record(payload("post_partial"), config())
    assert record["partial"] is True
    assert record["requested_model"] == "opus"
    assert record["resolved_model"] == "claude-opus-5-5"


def test_alias_spawn_has_unknown_effort(payload):
    data = payload("post_foreground")
    data["tool_input"]["subagent_type"] = "Explore"
    record = log.spawn_record(data, config())
    assert (record["resolution"], record["tier"], record["effort"]) == ("alias", "scout", "unknown")


def test_foreground_totals_come_from_the_subagent_transcript(payload, tmp_path):
    data = payload("post_foreground")
    session = tmp_path / "session"
    (session / "subagents").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "agent_transcript.jsonl",
        session / "subagents" / "agent-a928c9bf16b62279b.jsonl",
    )
    data["transcript_path"] = str(session) + ".jsonl"
    record = log.spawn_record(data, config())
    assert record["tokens"] == {"input": 18, "output": 614, "cache_read": 6489, "cache_write": 7617}


def test_transcript_totals_count_each_message_once():
    totals = log.transcript_totals(FIXTURES / "agent_transcript.jsonl")
    assert totals["tokens"]["output"] == 506 + 108
    assert totals["tool_uses"] == 1
    assert totals["duration_ms"] == 6417


def test_missing_transcript_gives_no_totals(tmp_path):
    assert log.transcript_totals(tmp_path / "nope.jsonl") is None


def test_finish_record_carries_background_totals(payload):
    data = payload("subagent_stop")
    data["agent_transcript_path"] = str(FIXTURES / "agent_transcript.jsonl")
    record = log.finish_record(data, config())
    assert record["kind"] == "finish" and record["agent_id"] == "a7ba453706d4e6dd5"
    assert record["tokens"]["output"] == 614 and record["tier"] == "scout"


def test_judge_verdict_and_review_link_are_parsed(payload):
    data = payload("post_foreground")
    data["tool_input"]["subagent_type"] = "agent-router:judge"
    data["tool_input"]["prompt"] = "Check the diff.\nReviews: a928c9bf16b62279b\nBe thorough."
    data["tool_response"]["content"] = [
        {"type": "text", "text": "Findings...\nVERDICT: pass\nmore\nVERDICT: fail\n"}
    ]
    record = log.spawn_record(data, config())
    assert record["verdict"] == "fail"
    assert record["reviews"] == "a928c9bf16b62279b"


def test_verdict_is_only_read_from_a_judge(payload):
    data = payload("post_foreground")
    data["tool_response"]["content"] = [{"type": "text", "text": "VERDICT: pass"}]
    assert log.spawn_record(data, config())["verdict"] is None


def test_prefix_hashes_only_exist_for_long_prompts():
    short = log.prompt_fingerprint("short prompt")
    long_a = log.prompt_fingerprint("p" * 600 + " task one")
    long_b = log.prompt_fingerprint("p" * 600 + " task two")
    assert short["prefix_hashes"] == {}
    assert set(long_a["prefix_hashes"]) == {"200", "500"}
    assert long_a["prefix_hashes"]["500"] == long_b["prefix_hashes"]["500"]
    assert long_a["prompt_hash"] != long_b["prompt_hash"]


def test_whitespace_does_not_change_a_fingerprint():
    assert log.prompt_fingerprint("a  b\n c") == log.prompt_fingerprint("a b c")


def test_append_writes_one_line_per_record_and_read_returns_them(tmp_path):
    path = log.log_path(tmp_path, "sess/../1")
    assert path.parent == tmp_path / ".claude" / "agent-router" / "log"
    log.append(path, {"v": 1, "kind": "spawn", "n": 1})
    log.append(path, {"v": 1, "kind": "spawn", "n": 2})
    path.write_text(path.read_text() + "not json\n" + '{"v": 99}\n', encoding="utf-8")
    assert [r["n"] for r in log.read_records(tmp_path)] == [1, 2]


def test_fail_record(payload):
    data = payload("post_foreground")
    data.pop("tool_response")
    data["is_interrupt"] = True
    record = log.fail_record(data, config())
    assert (record["kind"], record["tier"], record["interrupted"]) == ("fail", "scout", True)
