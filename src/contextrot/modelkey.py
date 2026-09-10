"""Canonical model-family keys.

Pure string handling, no dependencies beyond ``re``. It lives outside
``analysis/`` on purpose: the live surfaces (statusline, hook, ``status``)
need to turn a raw model id into a family key on every render, and importing
the analysis package for that pulls in the adapters, the signal extractor and
the whole statistics layer — about 16 ms of import time on a code path that
runs every few seconds.
"""

from __future__ import annotations

import re

_PREFIX_RE = re.compile(r"^(?:(?:us|eu|apac)\.)?(?:anthropic\.)?(?:claude-)?")
_SUFFIX_RES = (
    re.compile(r"-v\d+:\d+$"),  # bedrock "-v1:0"
    re.compile(r"\[\dm\]$"),  # "[1m]" long-context marker
    re.compile(r"-latest$"),
    re.compile(r"-\d{8}$"),  # trailing date "-20241022"
)
# Anthropic families. Keep in step with the families priced in pricing.py —
# a model that has a window there but no family here gets grouped under
# "unknown", which silently mixes it with every other vendor.
_FAMILY_RE = re.compile(r"(opus|sonnet|haiku|fable|mythos)")
# Everything else: leading name plus an optional version, so "gpt-5.6-terra"
# groups with "gpt-5.6-sol" instead of landing in "unknown" beside a Qwen.
_GENERIC_RE = re.compile(r"^([a-z]+)-?(\d+(?:[.\-]\d+)*)?")


def model_family(model_id: str) -> str:
    """Canonical family key for a raw model id.

    "claude-opus-4-8" -> "opus-4.8"; "claude-3-5-sonnet-20241022" -> "sonnet-3.5";
    "us.anthropic.claude-sonnet-4-6-v1:0" -> "sonnet-4.6"; unknown -> "unknown".
    """
    s = (model_id or "").strip().lower()
    if not s:
        return "unknown"
    s = _PREFIX_RE.sub("", s)
    for rx in _SUFFIX_RES:
        s = rx.sub("", s)
    m = _FAMILY_RE.search(s)
    if not m:
        return _generic_family(s)
    family = m.group(1)
    before = s[: m.start()].strip("-")
    after = s[m.end() :].strip("-")
    # Version digits sit after the family word in new ids ("sonnet-4-6"),
    # before it in old ones ("3-5-sonnet").
    digits = after if re.fullmatch(r"\d+(-\d+)*", after or "") else None
    if digits is None and re.fullmatch(r"\d+(-\d+)*", before or ""):
        digits = before
    if digits:
        return f"{family}-{digits.replace('-', '.')}"
    return family


def _generic_family(s: str) -> str:
    """Family key for a non-Anthropic model id.

    Grouping every unrecognised vendor under one "unknown" key is worse than
    useless for per-model statistics: it builds a single curve out of GPT,
    Qwen and Nemotron steps that describes none of them.
    """
    m = _GENERIC_RE.match(s)
    if not m:
        return "unknown"  # e.g. "<synthetic>", which is a placeholder, not a model
    name, digits = m.group(1), m.group(2)
    if not digits:
        return name
    return f"{name}-{digits.replace('-', '.')}"


def model_label(family: str) -> str:
    """Display label: "opus-4.8" -> "Opus 4.8"."""
    parts = family.split("-", 1)
    name = parts[0].capitalize()
    return f"{name} {parts[1]}" if len(parts) > 1 else name
