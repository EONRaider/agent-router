# agent-router: implementation plan

> This is the plan as approved before the build, kept as a design record. Where the build
> departed from it, see "Departures from the plan" at the end. The README and the other files
> in `docs/` describe the plugin as built.

Status: approved on 2026-10-03 and built as v0.1.0.

## 1. Verification results

Checked against the current docs (code.claude.com) and by running a throwaway probe plugin in
headless Claude Code 2.1.270 on this machine. "Observed" means seen in a real hook payload.

| # | Question | Answer | Source |
|---|---|---|---|
| 1 | Can PreToolUse see and reject spawns? Rewrite them? | Yes. The tool name is `Agent`. `tool_input` carries `subagent_type`, `description`, `prompt`, `run_in_background`, and `model` when the caller overrides it. `permissionDecision: "deny"` blocks the spawn and the reason text reaches the model, which retried. Rewrite via `updatedInput` is documented but untested; the design does not use it. | Observed (deny, fields); docs (rewrite) |
| 2 | Do agent files accept `effort`? | Yes: `low`, `medium`, `high`, `xhigh`, `max`; available levels depend on the model. The Agent tool has no per-call effort parameter, so effort comes only from the definition. | Docs; Agent tool schema |
| 3 | Can a hook read tokens and duration? | Yes for foreground spawns: PostToolUse `tool_response` has `status`, `agentId`, `resolvedModel`, `totalTokens`, `totalDurationMs`, `totalToolUseCount` and a `usage` split. Background spawns return at once with `status: "async_launched"`, `agentId` and `resolvedModel` only; totals must be read from `agent_transcript_path` when SubagentStop fires. | Observed |
| 4 | Packaging | One plugin: `.claude-plugin/plugin.json`, `agents/`, `skills/`, `hooks/hooks.json`, `scripts/`. `commands/` is legacy; commands are skills (`/agent-router:report`). Plugin agents are namespaced `agent-router:scout` and cannot set `hooks`, `mcpServers` or `permissionMode`. | Docs; observed namespacing |
| 5 | Finding the project | Hooks get `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and a `cwd` field. `CLAUDE_PROJECT_DIR` is the directory the session started in, not the repo root (observed: a subdirectory). `CLAUDE_PLUGIN_ROOT` is not in the Bash tool's environment. | Observed; docs |

Other facts the design relies on:

- Every hook payload has `session_id` and `prompt_id`. `tool_use_id` changes on a retry; `prompt_id` does not. `agentId` links PostToolUse to SubagentStart and SubagentStop, and the parent session sees it in the Agent result. (Observed.)
- A turn-limited agent returns `status: "completed"` with content starting `NOTE: this agent stopped at its N-turn limit ... PARTIAL`. SubagentStop did not fire for it. (Observed.)
- A per-call `model: "sonnet"` on a Haiku-pinned agent resolved to Sonnet. (Observed.)
- Concurrent hooks interleaved writes in the probe's shared log file. (Observed.)
- Plugins do not load in cloud sessions. A single-repo cloud session does read the repo's `.claude/settings.json` (including hooks) and `.claude/agents/`. (Docs.)
- A `.claude/agents/` directory created mid-session is not picked up until restart. (Docs.)

No answer was "no". Four findings change the design:

1. Project root must be found by walking up, not taken from `CLAUDE_PROJECT_DIR`.
2. Background spawns need a second record at SubagentStop.
3. A plugin cannot change its agent definitions per project, and effort has no per-call override. A project that remaps a tier therefore needs a project-level agent file.
4. Cloud sessions need the hooks and agents vendored into the repo.

## 2. Decisions settled with you

- Local repo `~/programming/agent-router`; GitHub `EONRaider/agent-router`, public.
- Untiered spawns: built-in agents are mapped to a tier and checked; other plugins' agents pass and are logged.
- Log: committed to the project, one file per session.
- Cloud sessions: covered in v0.1 by an opt-in vendor mode.

## 3. Decisions I made (say so if you disagree)

- Python 3.8+ standard library only. No dependencies, network or model calls in any hook. Linux and macOS; Windows is out of scope for v0.1.
- `analyst` defaults to Sonnet at high effort. The spec allows Sonnet or Opus, and raising it is a one-line overlay change.
- Models are pinned by family alias (`haiku`, `sonnet`, `opus`), so tiers survive model releases.
- Hooks fail open: a crash, a malformed overlay or an unknown model allows the spawn and logs a warning. Each hook has a 5-second timeout.
- A project is opted in by `/agent-router:init`. Without an overlay the plugin writes nothing into the repo and keeps no log; only the model-floor rule denies, and review language sent to the plugin's own scout or worker gets a warning, not a denial. SessionStart prints one line pointing at `/agent-router:init`.
- `mark.py` is called by absolute path printed at SessionStart, not shipped under `bin/`. A `bin/` directory would avoid a Bash permission prompt, but it does not exist in vendored or cloud sessions; `init` adds a permission rule for it to `.claude/settings.local.json` (machine-specific, uncommitted); a vendored project uses the repo-relative vendored `mark.py`, whose rule can be committed.
- A custom agent that is neither mapped nor exempted passes and is logged, unless the overlay sets `strict: true`. (The reviewer showed that rejecting these by default would block every personal and project agent in every repo.)
- The log is append-only. Outcomes are separate records that reference a spawn and are joined at report time.
- The plugin never runs git. Log files ride along with the session's normal commits.
- Cut from v0.1 on the reviewer's advice: the keyword rule on user prompts for "user corrected" (weak, and it would run on every prompt). That signal comes from an explicit `mark` instead.
- One release, `v0.1.0`, after the last stage, then the marketplace entry. Before that, each stage is usable through `claude --plugin-dir`.

Two places where the plan departs from the spec's letter:

- "Reject a spawn with no tier chosen" applies only under `strict: true` (your decision, extended to custom agents as above).
- "The log stays local to the project" is read as "inside the project's repository", which now means it is pushed with the repo.

## 4. Repository layout

```
agent-router/
├── .claude-plugin/plugin.json
├── agents/            scout.md  worker.md  analyst.md  judge.md
├── skills/
│   ├── routing/SKILL.md      how to pick a tier
│   ├── init/SKILL.md         /agent-router:init (overlay, optional vendor step)
│   └── report/SKILL.md       /agent-router:report
├── hooks/hooks.json
├── scripts/
│   ├── hook.py               entry point: read stdin, dispatch, never raise
│   ├── report.py             report, sync, vendor subcommands
│   ├── mark.py               records an outcome for a spawn
│   └── agent_router/
│       ├── config.py         defaults + overlay loading and validation
│       ├── project.py        project root resolution and per-session cache
│       ├── policy.py         decide(tool_input, config) -> Allow | Deny(reason)
│       ├── log.py            record building and locked append
│       ├── outcomes.py       derive outcome signals from records
│       ├── proposals.py      proposal rules and guardrails
│       └── defaults.json     tiers, aliases, phrases, model ranks, prices, thresholds
├── tests/                    pytest; fixtures are sanitised real payloads from the probe
├── docs/                     overlay reference, log record schema, design notes (this plan)
├── .github/
│   ├── workflows/ci.yml      pytest on Python 3.8 and latest, ruff, on Linux and macOS
│   ├── ISSUE_TEMPLATE/       bug_report.yml, feature_request.yml, config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS
│   └── dependabot.yml        GitHub Actions updates
├── README.md  CHANGELOG.md  RELEASING.md  LICENSE
├── CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md
├── pyproject.toml            ruff and pytest configuration only; nothing is packaged
└── .editorconfig  .gitignore  .gitattributes
```

### 4.1 Open-source scaffolding

- **LICENSE**: MIT, as in your other plugins.
- **README.md**: what it does, install from the `eonraider` marketplace, quick start, the tier table, overlay reference link, privacy note on what the log stores, known limits, CI and license badges.
- **CONTRIBUTING.md**: dev setup (`claude --plugin-dir`), running tests and ruff, the rule that hook code makes no model or network calls, tests-first for `policy.py` and `proposals.py`, commit and PR conventions, how to capture a payload fixture.
- **SECURITY.md**: supported versions, reporting through GitHub private vulnerability reporting (no email address published), what counts as a vulnerability here (a hook that leaks prompt text, a path escape in `vendor` or `sync`, a bypass of a hard floor).
- **CODE_OF_CONDUCT.md**: Contributor Covenant 2.1, with reports routed through the same private channel.
- **CHANGELOG.md**: Keep a Changelog format, as in simplicity. **RELEASING.md**: the tag-and-marketplace steps.
- **Issue and PR templates, CODEOWNERS, dependabot** as listed above.

GitHub repository settings, applied with `gh` when the repo is created: description and topics,
private vulnerability reporting on, Dependabot alerts on, issues on, wiki off, delete branch on
merge, and a `main` ruleset requiring a PR and a passing CI run.

## 5. Files the plugin writes in a project

```
.claude/agent-router.json                     overlay, committed
.claude/agent-router/log/<session-id>.jsonl   spawn log, committed
.claude/agent-router/decisions.jsonl          accepted and rejected proposals, committed
.claude/agents/router-<tier>.md               generated for remapped or added tiers; all tiers in vendor mode
.claude/agent-router/vendor/                  vendor mode only: copy of scripts/ plus a VERSION file
.claude/settings.json                         vendor mode only: hook registrations added
```

Project root is resolved once, at SessionStart: the nearest ancestor of the start directory with
`.claude/agent-router.json`, else the nearest with `.git`, else `CLAUDE_PROJECT_DIR`. The result
is cached in the session's `scratchpad_dir` (observed in every probe payload; fallback
`CLAUDE_PLUGIN_DATA`, then the system temp directory), so later `cwd` changes and worktree-isolated
subagents still log to the session's root.

`init` also pre-creates `.claude/agents/` and adds a `.gitattributes` line marking the log
directory `linguist-generated`, so it collapses in PR diffs.

## 6. Design by component

### 6.1 Tiers

| Agent | Model | Effort | Tools |
|---|---|---|---|
| `agent-router:scout` | haiku | low | no Write, Edit, NotebookEdit or Agent; `maxTurns: 25` |
| `agent-router:worker` | sonnet | medium | all except Agent |
| `agent-router:analyst` | sonnet | high | all except Agent |
| `agent-router:judge` | opus | high | no Write, Edit or Agent; Bash allowed so it can run tests |

`judge` ends every report with `VERDICT: pass | concerns | fail` and echoes any
`Reviews: <agent-id>` line from its brief, so review outcomes can be read by rule.

Built-in aliases: `Explore` → scout, `Plan` → analyst, `general-purpose` / `claude` / no type →
worker. Aliases are checked by the hook and logged, but the plugin cannot resize them and they
run on models it does not control, so the report lists them separately and **proposals count
only real tier agents**. Exempt by default: other plugins' namespaced agents,
`statusline-setup`, `claude-code-guide`, forks.

### 6.2 Routing skill and session context

The skill is short. Two questions: what does a wrong answer cost, and how cheaply can the result
be checked? Cheap to check goes down one tier; judgment work never does.

A SessionStart hook (matcher `startup|resume|clear|compact`) prints about ten lines into
context: the project's effective tier table, and the exact absolute `mark.py` command with the
session id filled in. The session therefore routes correctly and can record outcomes without
loading the skill, and the command does not depend on `CLAUDE_PLUGIN_ROOT`.

### 6.3 Enforcement hook (PreToolUse, matcher `Agent`)

`policy.decide` is a pure function. Rules in order; the first match denies with one line naming
the correct call:

1. `strict` is on and the type is not a tier, alias, overlay tier or exemption.
2. The type is a shipped tier this project remapped, **and** the generated `router-<tier>` file
   existed when the session started: "worker is remapped here, spawn `router-worker`". If the
   file appeared mid-session the shipped tier is still allowed, since the new one cannot load yet.
3. Review language sent to a scout or worker tier. Matched only on the `description` and the
   first sentence of the prompt, using imperative phrases (`review the`, `audit`, `critique`,
   `security review`, `threat model`, `sign off`) with a shipped exclusion list (`review
   comments`, `audit log`). The overlay can add or remove phrases and set this rule to `warn`.
4. A per-call `model` that ranks below the tier's floor. Ranks: haiku 1, sonnet 2, opus 3;
   family is derived from full model IDs; the overlay can add ranks. A model with no known rank
   is allowed and logged.
5. The tier's declared model, or the per-call override, ranks below the project's hard floor.

Moving up is always allowed: judge accepts any brief and an override above the tier's model
passes and is logged. A false positive costs money, never a deadlock. Every denial is logged as
a `reject` record.

### 6.4 Spawn log

Record kinds, one JSON object per line:

- `reject`: time, `prompt_id`, type, tier, rule, matched phrase, description.
- `spawn` (PostToolUse): `tool_use_id`, `agent_id`, the spawner's `agent_id` if any,
  `prompt_id`, type, tier, alias flag, requested model, `resolvedModel`, effort (from the tier
  definition; `unknown` otherwise), token totals (input, output, cache read, cache write),
  duration, tool-use count, status, background flag, partial flag, the `description` capped at
  80 characters, prompt length, a SHA-256 of the whole normalised prompt, and SHA-256s of its
  first 200/500/1000 characters.
- `finish` (SubagentStop): for background spawns, totals summed from the agent transcript.
- `fail` (PostToolUseFailure).
- `mark`: an outcome recorded through `mark.py` (`redone`, `review-failed`, `user-rejected`).

The raw prompt is never stored. The summary is the Agent tool's `description` field, which the
spawning session writes as a three-to-five-word label. It is still free text and it ends up in
repo history; `log.summary: false` drops it. The prompt hashes are for spotting repeats, not
for secrecy. Each record is one `O_APPEND` write under an advisory lock.

| Signal | How | Used in proposal counts? |
|---|---|---|
| Hook rejected the first attempt | `reject` then `spawn` with the same `prompt_id` | Yes |
| Session overrode the tier's model | requested model differs from the tier's | Yes |
| Turn limit or failed | partial marker, `fail` record | Yes (context limit is unverified) |
| Background spawn with no `finish` | missing record | Shown, not counted: the session may still be running |
| Escalated or retried | a later spawn with the **same full-prompt hash** that started after the first one ended, at a higher or the same tier | Yes |
| Parent redid the work | `mark redone` | Yes |
| Review found serious problems | judge `VERDICT: fail` with a `Reviews:` link | Yes; unlinked verdicts are shown but not counted |
| Judge contradicted | two differing verdicts on the same target within one `prompt_id`, with no worker spawn or mark between them | Yes |
| User corrected or reverted | `mark user-rejected` | Yes |

The full-prompt hash keeps parallel fan-out and briefs that merely share a preamble from
counting as retries. The same-turn and "nothing in between" conditions keep fail, fix, pass
from counting as a contradiction.

### 6.5 Overlay

```json
{
  "version": 1,
  "strict": false,
  "vendored": false,
  "tiers": { "worker": { "model": "opus", "effort": "high" },
             "migrator": { "model": "sonnet", "effort": "high", "like": "worker" } },
  "aliases": { "my-db-agent": "worker" },
  "exempt": ["vendored-agent"],
  "review_language": { "mode": "deny", "add": ["pentest"], "remove": [] },
  "model_ranks": {},
  "floor": "sonnet",
  "locked": ["judge"],
  "trials": [],
  "log": { "enabled": true, "summary": true }
}
```

`report.py sync` writes `.claude/agents/router-<tier>.md` for every remapped or added tier,
deterministically, from the overlay and the shipped agent body. It runs when a proposal is
accepted, and the report tells the user the new agent loads on the next session.

### 6.6 Vendor mode (cloud sessions)

`/agent-router:init` offers an opt-in vendor step, `report.py vendor`, which:

- copies `scripts/` to `.claude/agent-router/vendor/` with a `VERSION` file;
- generates all four tiers as `.claude/agents/router-<tier>.md`;
- merges the hook registrations, SessionStart included, into `.claude/settings.json`, calling
  the vendored `hook.py`. Existing keys and hooks are kept, and a re-run changes nothing;
- sets `vendored: true` in the overlay.

Cloud sessions have no plugin and so no routing skill. They learn the tiers from the vendored
SessionStart tier table and from the `router-*` agent descriptions, which are written to stand
alone.

In a local session of a vendored project both hook sets may fire. The first one to handle an
event claims it by creating a marker file (`O_EXCL`, keyed by event and `tool_use_id` or
`prompt_id`) in the session cache; the second sees the marker and exits silently. So each event
is decided and logged once, there is one tier table and one `mark.py` command, and nothing
depends on the two copies being the same version or on the vendored hooks having loaded. When
`vendored` is true all four shipped tiers count as remapped, so tier names are `router-*` in
both local and cloud sessions.

The vendored registrations bind everyone who clones the repo, so the hook command is wrapped to
exit 0 when `python3` or the script is missing, and the script finds its files from its own
location. The vendor directory is marked `linguist-generated`; the README documents excluding
it from the host project's linters. The plugin's SessionStart hook compares `VERSION` with the installed plugin and
prints one line when the vendored copy is behind; re-running the vendor step updates it.

The docs confirm Python 3 is in the default cloud image and that single-repo cloud sessions run
repo hooks. Whether repo hooks load when a local session starts in a subdirectory decides the
command form, so it is probed in stage 2.

### 6.7 Report and proposals

`/agent-router:report` runs `report.py`, which reads every log file in the project and emits
per-tier counts, spend and proposals. `report.py --print` gives a plain-text report with no
prompts, for `/schedule` or `/loop`; the plugin ships no scheduler. In the skill, each proposal
is accepted or rejected: accepting applies the overlay edit, runs `sync`, and leaves the result
uncommitted for you to commit; either choice is appended to `decisions.jsonl`.

Thresholds live in `defaults.json` and can be overridden per project:

| Pattern | Proposal | Default threshold |
|---|---|---|
| Tier often redone or escalated | Raise effort one step, then model | ≥ 20 spawns, ≥ 3 incidents, rate ≥ 15% |
| Judge verdicts contradicted | Judge effort high → max | ≥ 2 linked contradictions |
| Tier always accepted on short tasks | Lower effort one step, on trial | ≥ 50 spawns, 0 negative signals, median ≤ 3 tool uses |
| Same override recurs | Add a project tier with that setting | same tier and model ≥ 5 times |
| Shared long preamble | Add a specialised type | same 500-char prefix hash ≥ 5 spawns |
| Hook keeps rejecting one kind | Adjust phrases or add a type | same rule and phrase ≥ 5 times |

Each proposal has a stable id (hash of rule, tier and change), its counts, three or four
example spawns (summaries only), the estimated change in spend and the overlay diff. Spend uses
a shipped per-family price table on the logged token totals. A model change gets a number; an
effort change gets a direction only, because the log cannot predict token use at another effort.

Guardrails:

- Minimum sample per tier before any proposal.
- Asymmetry: an upgrade needs 3 incidents; a downgrade needs 50 clean spawns.
- Trial downgrades: recorded in `trials`. Once the trial has at least the minimum sample, the
  report proposes reverting it if the tier meets the upgrade threshold.
- `locked` tiers and anything at the `floor` are never proposed for downgrade.
- A rejected proposal returns only when the evidence gathered since the rejection would, on its
  own, meet the threshold again.

Grouping similar briefs is the one model-assisted step. It runs only when the user asks for it
(`/agent-router:report group`), inside the session already running, over summaries only.

## 7. Known limits

- Outcome signals are proxies. "Not redone" is not "good". Linked judge verdicts are the strongest; `mark` depends on the session following the instruction.
- The log reaches the remote only if the session commits it. A session that never commits loses its records.
- Summaries and overlay edits become part of repo history, public in a public repo.
- Built-in agents can be checked and counted but not resized.
- Vendor mode is a copy. It goes stale until re-vendored, and multi-repo cloud sessions do not run repo hooks at all.
- Small projects never reach the thresholds and run on defaults.
- The review-language rule will misfire sometimes. The cost is a more expensive agent; the rejection counts feed a proposal to fix the phrase list.
- No log rotation in v0.1.

## 8. Build order

Tests are written first for `policy.py`, `outcomes.py` and `proposals.py`, from fixture
payloads, and run without Claude Code.

1. **Tiers and routing skill.** Full open-source scaffold (section 4.1), repository settings, CI, four agents, routing skill, `claude plugin validate`.
2. **Spawn log.** `config.py` (overlay parsing), `project.py`, `log.py`; SessionStart, PostToolUse, SubagentStop and PostToolUseFailure hooks; `init` skill. Probe: background failure payloads, the context-limit case, hooks firing inside subagents, repo hooks in a session started in a subdirectory.
3. **Enforcement.** `policy.py`, PreToolUse hook, tier table in SessionStart, `sync`.
4. **Report and proposals.** `outcomes.py`, `proposals.py`, `report.py`, `mark.py`, report skill, `decisions.jsonl`.
5. **Vendor mode.** `report.py vendor`, the first-writer marker, version note. Probe: a vendored project run with the plugin disabled.
6. **Release.** Version `0.1.0`, CHANGELOG, annotated tag `v0.1.0` (not `claude plugin tag`), per the simplicity RELEASING.md.
7. **Marketplace.** PR to `EONRaider/claude-plugins`: new entry (`source: url`, HTTPS, `ref: v0.1.0`, `sha`), README line and install command, `claude plugin validate`, merge, then `claude plugin marketplace update eonraider` and install.

## 9. Outward-facing actions, in order, after approval

1. Create `~/programming/agent-router` and `git init`.
2. `gh repo create EONRaider/agent-router --public`.
3. Stages 1 to 5, each on a branch with a PR into `main`.
4. Tag `v0.1.0` and push.
5. PR to `EONRaider/claude-plugins`.

## 10. Adversarial review: what changed

Two passes. The first raised 17 findings and all but two were adopted; the second, on the
revision and the new vendor mode, raised 11 and all were adopted. Main changes: custom agents are no
longer rejected by default; remap denial waits until the generated agent can load; unknown
models are allowed, not rejected; the cloud claim was corrected and vendor mode added; the
review-language rule matches a much smaller surface; aliases are excluded from proposal counts;
retry, contradiction and trial rules were tightened; `mark.py` and root resolution no longer
depend on values the session cannot see. From the second pass: plugin and vendored hooks no
longer both act on one event; retries are matched on a full-prompt hash; unfinished background
spawns are not counted as failures. Not adopted: cutting preamble hashing and trial
downgrades from v0.1, because the spec asks for both and each is small.

## 11. Departures from the plan

- The admin command line is `scripts/router.py` (`init`, `sync`, `vendor`, `report`,
  `decide`), not `report.py`.
- `init` does not add a permission rule for `mark.py`. A tool that writes its own allow rules
  does more than it should unasked; the README says which rule to add by hand.
- Fable is ranked (4) and priced, because the pricing page lists it above Opus. Proposals
  still only move along the haiku, sonnet, opus ladder.
- Probed during the build: project `.claude/settings.json` hooks do not load when a local
  session starts in a subdirectory, although `.claude/agents/` does. Vendored hooks therefore
  cover sessions that start at the repository root, which cloud sessions do; locally the
  plugin's own hooks cover every start directory.
- Not probed: the context-limit case and background-agent failure payloads. A background
  spawn with no `finish` record is shown in the report and not counted.
- The session cache claim for SessionStart uses a five-second time bucket, because that event
  has no id of its own.
