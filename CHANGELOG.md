# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Four pre-sized agent tiers with pinned model and effort: `scout` (Haiku, low), `worker`
  (Sonnet, medium), `analyst` (Sonnet, high) and `judge` (Opus, high).
- `routing` skill: how to pick a tier, write the brief and record outcomes.
- Enforcement hook on the `Agent` tool. It rejects, with one line naming the correct call: a
  review or audit brief sent to scout or worker, a model override below the tier's floor, a
  spawn below the project's hard floor, a shipped tier the project remapped, and (with
  `strict`) an untiered agent type. Moving up a tier is always allowed.
- Overlay options: resize or add tiers, aliases, exemptions, review phrases, floors.
- `router.py sync` generates `.claude/agents/router-<tier>.md` for resized or added tiers.
- Spawn log for opted-in projects: one JSON line per spawn in
  `.claude/agent-router/log/<session-id>.jsonl`, with tier, model, effort, tokens, duration and
  the short task description. The raw prompt is never stored.
- `/agent-router:init` to opt a project in, and the overlay file `.claude/agent-router.json`.
- Session start message listing the project's tiers.
- Repository scaffold: license, contribution and security policies, CI, issue and PR templates.
