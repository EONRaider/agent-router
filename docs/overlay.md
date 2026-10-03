# Overlay reference

The overlay is `.claude/agent-router.json` in a project's repository. `/agent-router:init`
creates it. It is edited by a person, or by a proposal that a person accepted; the plugin
never changes it on its own. Every key is optional.

```json
{
  "version": 1,
  "strict": false,
  "vendored": false,
  "tiers": {
    "worker": { "model": "opus", "effort": "high" },
    "migrator": { "model": "sonnet", "effort": "high", "like": "worker", "description": "Database migrations." }
  },
  "aliases": { "my-db-agent": "worker" },
  "exempt": ["some-vendored-agent"],
  "review_language": { "mode": "deny", "add": ["pentest"], "remove": [] },
  "model_ranks": {},
  "floor": "sonnet",
  "locked": ["judge"],
  "trials": [],
  "log": { "enabled": true, "summary": true },
  "thresholds": {}
}
```

| Key | Meaning |
|---|---|
| `version` | Overlay format. Must be `1`. |
| `strict` | When `true`, an agent type that is not a tier, an alias or an exemption is rejected. Default `false`: such agents pass and are logged. |
| `vendored` | Set by the vendor step. All four shipped tiers are then served by `router-*` project agents. |
| `tiers` | Resize a shipped tier (`model`, `effort`, `floor`) or add one. An added tier needs `model` and `effort`; `like` names the shipped tier whose rules and agent body it uses (default `worker`), and `description` replaces the generated description. |
| `aliases` | Map an agent type to a tier, so it is checked and logged as that tier. |
| `exempt` | Agent types the hook never checks. |
| `review_language` | `mode` is `deny` (default), `warn` (log the match, allow the spawn) or `off`. `add` and `remove` change the phrase list. |
| `model_ranks` | Ranks for models the plugin does not know, used by the floor checks. Shipped: haiku 1, sonnet 2, opus 3, fable 4. |
| `floor` | Hard floor. A spawn that would run on a model below it is rejected. |
| `locked` | Tiers that are never proposed for downgrade. |
| `trials` | Written by an accepted downgrade proposal; closed by a later proposal. |
| `log` | `enabled: false` stops logging. `summary: false` leaves the task description out of each record. |
| `thresholds` | Override the proposal thresholds in `scripts/agent_router/defaults.json`. |

## Generated agents

A plugin cannot change its own agent definitions per project, and Claude Code has no
per-call effort override. So each resized or added tier becomes
`.claude/agents/router-<tier>.md`, generated from the overlay and the shipped agent body.
Accepting a proposal regenerates them. To regenerate by hand after editing the overlay, run
`/agent-router:init` again or:

```bash
python3 /path/to/agent-router/scripts/router.py sync
```

Generated files carry a marker comment. Files without it are never overwritten or removed.
A new or changed agent loads in the next session; until then the hook keeps allowing the
shipped tier.

## An unusable overlay

If the overlay is not valid JSON, has an unknown key or a wrong type, the hooks ignore it,
use the shipped defaults and say so at session start. They never block a session over it.
