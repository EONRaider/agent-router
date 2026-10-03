---
name: init
description: Opt the current project in to agent-router by creating its overlay file (.claude/agent-router.json) and enabling the committed spawn log. Use when the user runs /agent-router:init, asks to set up or enable agent-router in a project, or when the session start message says the project has not opted in and the user wants spawn logging.
disable-model-invocation: true
---

# Set up agent-router in this project

Opting in writes files into the project's repository. Do it only because the user asked.

1. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" init
   ```

   It finds the project root (the repository root), then creates, without overwriting
   anything that exists:

   - `.claude/agent-router.json`: the overlay, where this project resizes tiers, adds
     tiers, exempts agent types and sets floors;
   - `.claude/agents/`: where generated agents for remapped tiers go;
   - `.claude/agent-router/log/`: the spawn log, one file per session;
   - a `.gitattributes` line that collapses the log in pull request diffs.

2. Tell the user what was created, using the command's output, and these three facts:

   - The overlay and the log are meant to be committed. The plugin never runs git; the files
     ride along with the project's normal commits.
   - Each log line stores the short task description of a spawn, never the prompt. That
     description becomes part of the repository's history. Setting `"log": {"summary":
     false}` in the overlay leaves it out.
   - Logging starts with the next session.

3. Ask the user whether they run cloud sessions (Claude Code on the web, routines) on this
   repository. Plugins do not load there, so by default a cloud session runs no agent-router
   hooks and logs nothing. If they want cloud sessions covered, run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" vendor
   ```

   This copies the hook scripts and agent definitions to `.claude/agent-router/vendor/`,
   registers the hooks in `.claude/settings.json` (existing settings are kept), and generates
   all four tiers as project agents named `router-scout`, `router-worker`, `router-analyst`
   and `router-judge`. From the next session on, those names replace the `agent-router:*`
   ones in this project. Tell the user:

   - the vendored hooks run for everyone who clones the repository, and do nothing where
     `python3` is missing;
   - the copy does not update with the plugin. Running this command again refreshes it, and
     the session start message says when it is behind;
   - only single-repository cloud sessions run repository hooks.

   Skip this step if the user does not use cloud sessions. If the session start message said
   the vendored copy is behind, run the same command to update it.

4. Do not commit the files yourself unless the user asks.
