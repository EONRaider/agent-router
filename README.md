# agent-router

[![CI](https://github.com/EONRaider/agent-router/actions/workflows/ci.yml/badge.svg)](https://github.com/EONRaider/agent-router/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin that sizes subagents to the task.

When a Claude Code session spawns a subagent, nothing matches the agent's model and effort to
the work. Sessions run cheap lookups on an expensive model, or send judgment work to a model
too weak for it. agent-router turns that into a choice between a few pre-sized agent types,
enforces the choice with a hook, logs what happened to each spawn, and uses that log to
propose changes per project. It never changes its own configuration: a person accepts or
rejects every proposal.

> **Status:** under development. Nothing is released yet; see [CHANGELOG.md](CHANGELOG.md) and
> the [design plan](docs/design/plan.md).

## License

[MIT](LICENSE)
