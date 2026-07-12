"""Self-generated SVG verdict badge.

A shields.io-style flat badge (`context rot | clean ✓`) rendered entirely
locally — embed it in a README, blog post, or profile without any badge
service seeing your data. Colors follow the verdict semantics used across
every report surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from contextrot.analysis import AnalysisResult

_LABEL = "context rot"

_COLORS = {
    "clean": "#2da44e",
    "edge": "#d4a72c",
    "rot": "#cf222e",
    "insufficient": "#8c959f",
}

# Approximate Verdana-11 advance width used by badge services; close enough
# for a fixed-label badge and keeps this dependency-free.
_CHAR_W = 6.6
_PAD = 10


def badge_value(result: AnalysisResult) -> tuple[str, str]:
    """(value text, hex color) for the badge's right half."""
    kind = result.verdict_kind
    color = _COLORS.get(kind, _COLORS["insufficient"])
    if kind == "clean":
        return "clean ✓", color
    if kind == "edge":
        knee = result.curve.knee_pct
        return (f"edge · knee ~{knee:.0f}%" if knee is not None else "edge rot"), color
    if kind == "rot":
        ratio = result.curve.degradation_ratio
        if ratio is not None and ratio != float("inf"):
            return f"rot ✗ {ratio:.1f}×", color
        return "rot ✗", color
    return "not enough data", color


def render_badge(result: AnalysisResult) -> str:
    """A complete standalone SVG document for the verdict badge."""
    value, color = badge_value(result)
    left_w = round(len(_LABEL) * _CHAR_W + _PAD)
    right_w = round(len(value) * _CHAR_W + _PAD)
    total = left_w + right_w
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{_LABEL}: {value}">'
    )
    font = "Verdana,Geneva,DejaVu Sans,sans-serif"
    return f"""{svg_open}
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{left_w}" height="20" fill="#555"/>
    <rect x="{left_w}" width="{right_w}" height="20" fill="{color}"/>
    <rect width="{total}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="{font}" font-size="11">
    <text x="{left_w / 2:.0f}" y="14">{_LABEL}</text>
    <text x="{left_w + right_w / 2:.0f}" y="14">{value}</text>
  </g>
</svg>
"""
