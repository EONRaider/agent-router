# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Four pre-sized agent tiers with pinned model and effort: `scout` (Haiku, low), `worker`
  (Sonnet, medium), `analyst` (Sonnet, high) and `judge` (Opus, high).
- `routing` skill: how to pick a tier, write the brief and record outcomes.
- Spawn log for opted-in projects: one JSON line per spawn in
  `.claude/agent-router/log/<session-id>.jsonl`, with tier, model, effort, tokens, duration and
  the short task description. The raw prompt is never stored.
- `/agent-router:init` to opt a project in, and the overlay file `.claude/agent-router.json`.
- Session start message listing the project's tiers.
- Repository scaffold: license, contribution and security policies, CI, issue and PR templates.
