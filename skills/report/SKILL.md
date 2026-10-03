---
name: report
description: Show the agent-router report for the current project (spawns, problems and estimated spend per tier) and walk the user through its proposals, accepting or rejecting each one. Use when the user runs /agent-router:report, asks how the routing tiers are performing, asks whether a tier should be resized, or wants to review agent-router proposals. With the argument "print" it only prints the report; with "group" it also groups similar briefs.
---

# agent-router report

The plugin never changes its own configuration. Every proposal is accepted or rejected by the
user. Do not accept one on their behalf, and do not edit `.claude/agent-router.json` by hand
to apply one.

## 1. Run the report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" report
```

Show the user the tier lines and the proposals. Say plainly that the signals are proxies:
"not redone" is not "good", and estimated spend uses list prices on logged tokens.

If the argument is `print`, stop here.

## 2. Decide each proposal

For each proposal, ask the user with AskUserQuestion: accept or reject. Put the evidence and
the overlay edit in the question so the choice is informed. Then record the choice:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" decide <proposal-id> accept
```

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" decide <proposal-id> reject
```

- Accepting edits `.claude/agent-router.json`, regenerates the project agents and records the
  decision. Nothing is committed: tell the user the changed files so they can review and
  commit them. A resized or added tier loads in the next session.
- Rejecting records the decision. The proposal stays quiet until new evidence, on its own,
  meets the threshold again.
- A downgrade is a trial. Later reports judge it on the spawns made since it started and
  propose reverting it if the tier starts being redone.
- A proposal with no overlay edit (a shared preamble) needs work by hand; relay its
  instructions and do not record a decision unless the user rejects it.

## 3. Grouping similar briefs (only for `group`)

The rules count exact matches. To see whether overrides or rejections cluster around one kind
of task, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" report --summaries
```

Group the summaries yourself by kind of task and tell the user which groups recur and what
that suggests (a project tier, a phrase to drop, a specialised agent). This step only
informs; it produces no automatic edit. Run it when asked, not on every report.

## Scheduling

To run the report on a schedule, the user can schedule `/agent-router:report print`. The
scheduled run prints the report; proposals still wait for a person.
