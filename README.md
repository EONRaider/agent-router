# agent-router

[![CI](https://github.com/EONRaider/agent-router/actions/workflows/ci.yml/badge.svg)](https://github.com/EONRaider/agent-router/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin that sizes subagents to the task.

When a Claude Code session spawns a subagent, nothing matches the agent's model and effort to
the work. Sessions run cheap lookups on an expensive model, or send judgment work to a model
too weak for it. The second mistake is the costlier one: the work gets redone or, worse,
trusted.

agent-router turns routing into a choice between four pre-sized agent types, enforces that
choice with a hook, logs what happened to each spawn, and uses the log to propose changes per
project. It never changes its own configuration. A person accepts or rejects every proposal.

## Install

```bash
claude plugin marketplace add EONRaider/claude-plugins
```

```bash
claude plugin install agent-router@eonraider
```

Requires Claude Code 2.1.246 or later and `python3` (3.8+) on the `PATH`. Linux and macOS.
The hooks use the Python standard library only; they make no model calls and no network
calls.

## The tiers

| Tier | Agent type | Work it takes | Model | Effort |
|---|---|---|---|---|
| scout | `agent-router:scout` | Lookups, file finding, status reads, bounded extraction | Haiku | low |
| worker | `agent-router:worker` | Implementation with a checkable result (tests, a diff) | Sonnet | medium |
| analyst | `agent-router:analyst` | Research and synthesis across many sources | Sonnet | high |
| judge | `agent-router:judge` | Review, adversarial critique, security or design calls | Opus | high |

The `routing` skill tells the session how to choose: what does a wrong answer cost, and how
cheaply can the result be checked? Cheap-to-check work goes down a tier. Judgment work never
does.

## What the hook enforces

A `PreToolUse` hook on the `Agent` tool rejects a spawn with one line that names the correct
call, so the session re-spawns correctly. It rejects:

- a brief with review or audit language sent to scout or worker;
- a per-call `model` override below the tier's floor;
- a spawn below the project's hard floor, if the project sets one;
- a shipped tier the project has remapped (it points at the project's version);
- with `"strict": true`, any agent type the project has not mapped or exempted.

Moving up is always allowed, so a wrong rejection costs usage and never blocks the work.
Built-in agents are treated as a tier (`Explore` as scout, `Plan` as analyst,
`general-purpose` as worker). Other plugins' agents pass unchecked.

The hook fails open: if it crashes or the project's overlay is unusable, the spawn goes ahead.

## Opting a project in

Out of the box the plugin provides the tiers and the model-floor rule, and writes nothing
into your repositories. To get the spawn log, the full rules and proposals for a project, run
this in it:

```
/agent-router:init
```

It creates:

| Path | What it is |
|---|---|
| `.claude/agent-router.json` | The overlay: this project's tiers, aliases, exemptions and floors |
| `.claude/agent-router/log/<session-id>.jsonl` | The spawn log, one file per session |
| `.claude/agent-router/decisions.jsonl` | Proposals you accepted or rejected |
| `.claude/agents/router-<tier>.md` | Generated agents for tiers the overlay resizes or adds |

These files are meant to be committed. The plugin never runs git; they ride along with your
normal commits. See the [overlay reference](docs/overlay.md).

### What the log stores

One line per spawn: tier, model, effort, tokens, duration, tool-use count, and the Agent
tool's short `description` as a task summary. **The prompt is never stored**, only its length
and hashes. The description is free text written by the session and becomes part of your
repository's history; set `"log": {"summary": false}` in the overlay to leave it out. The
full record format is in [docs/log-format.md](docs/log-format.md).

### Recording outcomes

Some outcomes can be read from the log by rule: a rejected first attempt, a model override, a
turn limit, an identical brief sent again, a judge's verdict. Others have to be told. At
session start the plugin gives the session a `mark.py` command for three of them: the result
was redone, a review found a serious problem, or the user rejected it. To let the session run
it without a permission prompt, add an allow rule for that command to your own settings.

## Report and proposals

```
/agent-router:report
```

The report lists, per tier, the spawns, how many had problems and the estimated spend at list
prices. Then it lists proposals:

| Pattern in the log | Proposal |
|---|---|
| A tier's output is often redone or escalated | Raise that tier's effort, then its model |
| A judge's verdicts are contradicted by another review | Raise judge effort to max |
| A tier is always accepted on short, low-tool tasks | Lower its effort, on trial |
| The same model override recurs | Add a project tier with that setting |
| Many briefs share a long preamble | Add a specialised agent type |
| The hook keeps rejecting one phrase | Drop the phrase, or add a tier |

Each proposal carries its counts, a few example spawns, the estimated change in spend and the
exact overlay edit. You accept or reject each one. Accepting edits the overlay and regenerates
the project agents; nothing is committed for you. A rejected proposal stays quiet until new
evidence, on its own, meets the threshold again.

Guardrails: no proposal before a tier has 20 logged spawns; an upgrade needs 3 incidents and a
downgrade needs 50 clean spawns; a downgrade runs as a trial and is proposed for revert if the
tier starts being redone; tiers listed under `locked` are never downgraded.

To run the report on a schedule, schedule `/agent-router:report print`. Proposals still wait
for a person.

## Cloud sessions

Plugins do not load in cloud sessions (Claude Code on the web, routines). `/agent-router:init`
offers an opt-in vendor step that copies the hook scripts and agents into the project's
`.claude/` and registers the hooks in `.claude/settings.json`, so a single-repository cloud
session enforces and logs like a local one. In a vendored project the tiers are named
`router-scout`, `router-worker`, `router-analyst` and `router-judge`.

The vendored copy does not update with the plugin; run `/agent-router:init` again to refresh
it. Exclude `.claude/agent-router/vendor/` from your project's linters.

## Known limits

- The outcome signals are proxies. "Not redone" is not "good". A judge verdict linked to the
  spawn it reviews is the strongest signal; a `mark` depends on the session recording it.
- The log reaches your remote only when a session's changes are committed.
- Built-in agents can be checked and counted but not resized, so they never feed proposals.
- Small projects may never reach the sample thresholds. They run on the defaults.
- The review-language rule matches phrases in the description and first sentence of a brief,
  so it will sometimes misfire. The overlay can change the phrases or set the rule to warn.
- Effort has no per-call override in Claude Code. A project that resizes a tier gets a
  generated agent file, which loads from the next session.
- Vendored hooks load only when a session starts at the repository root, which cloud sessions
  do. Multi-repository cloud sessions do not run repository hooks.
- Spend figures use a shipped list-price table and logged tokens. They are estimates.
- There is no log rotation yet.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). The design and the checks made against Claude Code
before building are in [docs/design/plan.md](docs/design/plan.md).

## Security

See [SECURITY.md](SECURITY.md). The enforcement hook is a cost and quality control, not a
security boundary.

## License

[MIT](LICENSE)
