# Log format

The spawn log lives in `.claude/agent-router/log/`, one file per session, named
`<session-id>.jsonl`. Each line is one JSON object. The log is append-only: an outcome is a
new record that refers to a spawn, never a rewrite of an earlier line. Records from the
plugin's hooks and from a vendored copy are deduplicated by id when read.

The raw prompt is never stored.

## Common fields

| Field | Meaning |
|---|---|
| `v` | Record format version, `1` |
| `kind` | `spawn`, `finish`, `fail`, `reject` or `mark` |
| `ts` | UTC time the record was written |
| `session` | Session id |
| `prompt_id` | Id of the user turn the event happened in |

## `spawn`

Written when an `Agent` call returns (for a background spawn, when it is launched).

| Field | Meaning |
|---|---|
| `tool_use_id`, `agent_id` | Ids of the call and of the agent |
| `parent_agent_id` | The spawning agent, when a subagent made the call |
| `type` | The `subagent_type` requested |
| `resolution` | `tier`, `alias`, `exempt` or `unknown` |
| `tier` | The tier it counts as, if any |
| `requested_model` | The per-call model override, if any |
| `resolved_model` | The model Claude Code ran it on |
| `effort` | The tier's effort; `unknown` for aliases and exempt agents |
| `status`, `background`, `partial`, `empty` | Completion status; whether it ran in the background, stopped at its turn limit, or returned nothing |
| `tokens` | Cumulative `input`, `output`, `cache_read`, `cache_write`, summed from the agent's transcript |
| `context_tokens`, `duration_ms`, `tool_uses` | As reported by Claude Code |
| `summary` | The Agent tool's `description`, capped at 80 characters; `null` when `log.summary` is off |
| `prompt_len`, `prompt_hash`, `prefix_hashes` | Length of the whitespace-normalised prompt, a truncated SHA-256 of it, and of its first 200, 500 and 1000 characters. They identify repeats; they are not a secrecy measure |
| `reviews` | The agent id from a `Reviews:` line in the brief |
| `verdict` | For a judge: `pass`, `concerns` or `fail` from its `VERDICT:` line |

## `finish`

Written when a subagent stops. Carries `agent_id`, `type`, `tier`, cumulative `tokens`,
`duration_ms`, `tool_uses` and, for a judge, `verdict`. It is the only source of totals for a
background spawn.

## `fail`

Written when an `Agent` call errors. Carries the routing fields, `tool_use_id`, `summary` and
`interrupted`.

## `reject`

Written when the enforcement hook matches a rule. Carries the routing fields, `tool_use_id`,
`rule` (`untiered`, `remapped`, `review-language`, `model-floor`, `project-floor`), the
matched `phrase`, `summary`, `prompt_hash` and `enforced` (`false` when the rule only warned).

## `mark`

Written by `mark.py`. Carries `agent_id` and `outcome`: `redone`, `review-failed` or
`user-rejected`.

## Decisions

`.claude/agent-router/decisions.jsonl` has one line per proposal you decided: `id`, `rule`,
`tier`, `decision` (`accepted` or `rejected`), `ts`, `title` and the `evidence` it was decided
on.
