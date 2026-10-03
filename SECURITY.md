# Security policy

## Supported versions

Only the latest released version receives security fixes.

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub:
[Report a vulnerability](https://github.com/EONRaider/agent-router/security/advisories/new).

Include what you found, how to reproduce it, and the plugin and Claude Code versions. You can
expect a first reply within seven days. Once a fix is released the advisory is published and
you are credited, unless you ask not to be.

## What counts

agent-router runs hook scripts on your machine and writes files into your projects. Problems
of particular interest:

- a hook that stores or exposes raw prompt text, or anything beyond the documented log fields;
- a path escape: the `vendor` or `sync` commands, or the log writer, writing outside the
  project's `.claude/` directory;
- a way to make a hook run code taken from a hook payload, an overlay or a log file;
- a bypass of a project's hard floor or `strict` setting that the documentation says is enforced;
- any network access or model call from hook code.

The enforcement hook is a cost and quality control, not a security boundary: a session can
always choose a more capable agent. Misrouting that only costs money is a bug, not a
vulnerability; please file it as a normal issue.
