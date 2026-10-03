# Contributing to agent-router

Thanks for helping. Bug reports, rule fixes and documentation corrections are all welcome.

## Before you start

- For anything larger than a small fix, open an issue first so the approach can be agreed.
- Security problems go through [private reporting](SECURITY.md), not public issues.
- By contributing you agree that your work is released under the [MIT license](LICENSE) and
  that you will follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

You need Python 3.8 or later and, to try the plugin live, Claude Code.

```bash
git clone https://github.com/EONRaider/agent-router.git
cd agent-router
python3 -m pip install pytest ruff
```

Run the checks CI runs:

```bash
pytest
ruff check .
ruff format --check .
```

Try the plugin from your checkout, in any project:

```bash
claude --plugin-dir /path/to/agent-router
```

Validate the plugin manifest:

```bash
claude plugin validate .
```

## Ground rules for the code

1. **Hooks make no model calls and no network calls.** They read the hook payload and local
   files, apply rules, and write local files.
2. **Standard library only.** Nothing under `scripts/` may import a third-party package.
   The code must run on Python 3.8.
3. **Hooks fail open.** A bug in this plugin must never stop a session from working. Catch
   errors at the entry point, allow the action, and print a warning.
4. **Never store a raw prompt.** Log records hold the short task description, lengths and
   hashes only.
5. **The plugin never edits a project's configuration on its own.** Changes to an overlay
   happen only when a person accepts a proposal.
6. **Tests first for rule code.** `policy.py`, `outcomes.py` and `proposals.py` are plain rule
   code. Write the failing test, then the rule. Tests must run without Claude Code.

## Test fixtures

Fixtures under `tests/fixtures/` are real hook payloads with paths, ids and prompt text
replaced. If you add one, capture it with a throwaway plugin that dumps hook input, then
remove anything private before committing.

## Pull requests

- Branch from `main`; `main` is protected and takes changes only through pull requests.
- Keep a PR to one change. Add an entry under `Unreleased` in `CHANGELOG.md` when users would
  notice the change.
- CI must pass.

Releases are cut by the maintainer; see [RELEASING.md](RELEASING.md).
