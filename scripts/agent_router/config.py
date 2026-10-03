"""Shipped defaults merged with a project's overlay.

The overlay is `.claude/agent-router.json` in the project. It is only ever edited by a person
or by an accepted proposal; nothing in this module writes it.
"""

import json
from pathlib import Path

from . import OVERLAY_RELPATH, PLUGIN_NAMESPACE, PROJECT_AGENT_PREFIX

DEFAULTS_PATH = Path(__file__).resolve().parent / "defaults.json"

OVERLAY_KEYS = {
    "version": int,
    "strict": bool,
    "vendored": bool,
    "tiers": dict,
    "aliases": dict,
    "exempt": list,
    "review_language": dict,
    "model_ranks": dict,
    "floor": str,
    "locked": list,
    "trials": list,
    "log": dict,
    "thresholds": dict,
}


class ConfigError(ValueError):
    """The overlay exists but cannot be used."""


class Tier:
    """One routing tier as it applies in this project."""

    def __init__(self, name, model, effort, shipped, remapped, floor=None, like=None):
        self.name = name
        self.model = model
        self.effort = effort
        self.shipped = shipped
        self.remapped = remapped
        self.floor = floor or model
        self.like = like

    @property
    def agent_type(self):
        """The subagent type a session should spawn for this tier."""
        if self.shipped and not self.remapped:
            return f"{PLUGIN_NAMESPACE}:{self.name}"
        return f"{PROJECT_AGENT_PREFIX}{self.name}"


class Resolution:
    """What a `subagent_type` means to the router."""

    def __init__(self, kind, tier=None, via_shipped_agent=False):
        self.kind = kind  # "tier" | "alias" | "exempt" | "unknown"
        self.tier = tier
        self.via_shipped_agent = via_shipped_agent


class Config:
    def __init__(self, defaults, overlay=None):
        overlay = overlay or {}
        self.initialised = bool(overlay)
        self.strict = overlay.get("strict", False)
        self.vendored = overlay.get("vendored", False)
        self.tier_order = list(defaults["tier_order"])
        self.effort_order = list(defaults["effort_order"])
        self.model_ranks = dict(defaults["model_ranks"], **overlay.get("model_ranks", {}))
        self.aliases = dict(defaults["aliases"], **overlay.get("aliases", {}))
        self.exempt = set(defaults["exempt"]) | set(overlay.get("exempt", []))
        self.floor = overlay.get("floor")
        self.locked = set(overlay.get("locked", []))
        self.trials = list(overlay.get("trials", []))
        self.thresholds = dict(defaults["thresholds"], **overlay.get("thresholds", {}))
        self.prices = defaults["prices_per_mtok"]

        log = overlay.get("log", {})
        self.log_enabled = self.initialised and log.get("enabled", True)
        self.log_summary = log.get("summary", True)

        review = defaults["review_language"]
        review_overlay = overlay.get("review_language", {})
        removed = {phrase.lower() for phrase in review_overlay.get("remove", [])}
        phrases = [p for p in review["phrases"] if p not in removed]
        phrases += [p.lower() for p in review_overlay.get("add", [])]
        self.review_phrases = phrases
        self.review_exclusions = list(review["exclusions"])
        self.review_tiers = set(review["tiers"])
        # Until a project opts in there is no overlay in which to relax the rule, so it warns.
        self.review_mode = review_overlay.get("mode", "deny" if self.initialised else "warn")

        self.tier_descriptions = {
            name: spec["description"]
            for name, spec in overlay.get("tiers", {}).items()
            if isinstance(spec, dict) and spec.get("description")
        }
        self.tiers = {}
        for name, spec in defaults["tiers"].items():
            override = overlay.get("tiers", {}).get(name, {})
            remapped = bool(override) or self.vendored
            merged = dict(spec, **override)
            self.tiers[name] = Tier(
                name, merged["model"], merged["effort"], True, remapped, merged.get("floor")
            )
        for name, spec in overlay.get("tiers", {}).items():
            if name in self.tiers:
                continue
            like = spec.get("like")
            if like and like not in self.tier_order:
                raise ConfigError(f"tier {name!r}: 'like' names unknown tier {like!r}")
            self.tiers[name] = Tier(
                name, spec["model"], spec["effort"], False, True, spec.get("floor"), like
            )

    def model_rank(self, model):
        """Rank of a model alias or full id, or None when it is not known."""
        if not model:
            return None
        lowered = model.lower()
        if lowered in self.model_ranks:
            return self.model_ranks[lowered]
        for family, rank in self.model_ranks.items():
            if family in lowered:
                return rank
        return None

    def model_family(self, model):
        """The known family a model alias or full id belongs to, or None."""
        if not model:
            return None
        lowered = model.lower()
        for family in self.prices:
            if family in lowered:
                return family
        return None

    def tier_rank(self, tier_name):
        """Position of a tier in the shipped order; custom tiers rank as the tier they are like."""
        tier = self.tiers.get(tier_name)
        if tier is None:
            return None
        base = tier.like if tier.like else tier.name
        return self.tier_order.index(base) if base in self.tier_order else None

    def resolve(self, subagent_type):
        """Classify a subagent type as a tier, an alias, an exemption or unknown."""
        name = subagent_type or ""
        prefix = f"{PLUGIN_NAMESPACE}:"
        if name.startswith(prefix) and name[len(prefix) :] in self.tiers:
            return Resolution("tier", self.tiers[name[len(prefix) :]], via_shipped_agent=True)
        if name.startswith(PROJECT_AGENT_PREFIX):
            tier = self.tiers.get(name[len(PROJECT_AGENT_PREFIX) :])
            if tier is not None:
                return Resolution("tier", tier)
        if name in self.aliases and self.aliases[name] in self.tiers:
            return Resolution("alias", self.tiers[self.aliases[name]])
        if name in self.exempt or ":" in name:
            return Resolution("exempt")
        return Resolution("unknown")


def load_defaults():
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


def validate_overlay(overlay):
    """Raise ConfigError for an overlay that cannot be used."""
    if not isinstance(overlay, dict):
        raise ConfigError("overlay must be a JSON object")
    for key, value in overlay.items():
        expected = OVERLAY_KEYS.get(key)
        if expected is None:
            raise ConfigError(f"unknown overlay key {key!r}")
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ConfigError(f"overlay key {key!r} must be {expected.__name__}")
    if overlay.get("version", 1) != 1:
        raise ConfigError(f"unsupported overlay version {overlay.get('version')!r}")
    for name, spec in overlay.get("tiers", {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"tier {name!r} must be an object")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ConfigError(f"tier name {name!r} must be letters, digits, '-' or '_'")
    mode = overlay.get("review_language", {}).get("mode", "deny")
    if mode not in ("deny", "warn", "off"):
        raise ConfigError("review_language.mode must be 'deny', 'warn' or 'off'")


def read_overlay(root):
    """The project's overlay as a dict, or None when the project has not opted in."""
    path = Path(root) / OVERLAY_RELPATH
    if not path.is_file():
        return None
    try:
        overlay = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"{OVERLAY_RELPATH}: {error}") from error
    validate_overlay(overlay)
    return overlay or {"version": 1}


def load(root):
    """Config for a project. Raises ConfigError when the overlay is unusable."""
    defaults = load_defaults()
    overlay = read_overlay(root)
    config = Config(defaults, overlay)
    for name, tier in config.tiers.items():
        if not tier.shipped and (not tier.model or not tier.effort):
            raise ConfigError(f"tier {name!r} needs a model and an effort")
        if tier.effort not in config.effort_order:
            raise ConfigError(f"tier {name!r}: unknown effort {tier.effort!r}")
    return config


def load_or_defaults(root):
    """Config for a project, falling back to shipped defaults when the overlay is unusable.

    Returns (config, warning). Hooks use this so a bad overlay never blocks a session.
    """
    try:
        return load(root), None
    except (ConfigError, KeyError, TypeError) as error:
        return Config(load_defaults()), f"agent-router: overlay ignored ({error})"
