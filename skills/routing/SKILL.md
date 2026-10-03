---
name: routing
description: Choose the right agent-router tier (scout, worker, analyst or judge) before spawning a subagent with the Agent tool. Use whenever you are about to delegate work to a subagent, when a spawn was rejected by the agent-router hook, or when deciding whether a task can go to a cheaper agent. Covers how to size the agent, how to write the brief, and how to record what happened to its output.
---

# Routing a subagent

Every spawn should name a tier. An agent that is too small is the costlier mistake: its work
gets redone or, worse, trusted. An agent that is too large only wastes usage.

## The tiers

| Tier | Agent type | Takes | Model, effort |
|---|---|---|---|
| scout | `agent-router:scout` | Lookups, file finding, status reads, bounded extraction | Haiku, low |
| worker | `agent-router:worker` | Implementation with a checkable result (tests, a diff) | Sonnet, medium |
| analyst | `agent-router:analyst` | Research and synthesis across many sources | Sonnet, high |
| judge | `agent-router:judge` | Review, adversarial critique, security or design calls | Opus, high |

A project can rename or resize tiers. If the session start message lists a tier table for
this project, use the agent types it names; they replace the ones above.

## How to choose

Ask two questions about the task.

1. **What does a wrong answer cost?** If a wrong answer would be acted on, merged or shown to
   the user as true, the cost is high.
2. **How cheaply can the result be checked?** A file path, a test run or a diff is cheap to
   check. A review verdict, a design recommendation or a security assessment is not.

Then:

- Start from the tier whose "takes" column matches the work.
- If the result is cheap to check and you will check it, go down one tier.
- Judgment work never goes down. Review, audit, critique, security and design calls go to
  judge even when they look small.
- When unsure between two tiers, take the higher one.

Do not set `model` on the call to make a tier cheaper. The hook rejects an override below the
tier's floor. An override above it is allowed; use it only when this one task needs it.

## Writing the brief

- `description` is logged as the task summary. Make it a short, general label ("find config
  loader", "review auth diff") with no names, secrets or pasted content.
- Say what done means and how the result will be checked.
- When you send work to judge that another agent produced, include a line
  `Reviews: <agent-id>` with that agent's id from its result. This links the verdict to the
  spawn it judges.

## If the hook rejects a spawn

The rejection reason names the call to make instead. Re-spawn as it says. Moving up a tier is
always allowed, so a rejection never blocks the work.

## Recording outcomes

The log only learns what happened to an agent's output if it is told. When the session start
message gives a `mark` command, run it in these cases, with the agent's id:

- `redone`: you discarded the agent's result and did the task yourself or re-spawned it.
- `review-failed`: a review found a serious problem in that agent's output.
- `user-rejected`: the user corrected or reverted that agent's result.
