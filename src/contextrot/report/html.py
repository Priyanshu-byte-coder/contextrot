"""Self-contained HTML report rendering.

Produces a single file with inline CSS/JS/SVG — no CDN, no network calls,
safe to share as-is.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from contextrot import __version__
from contextrot.analysis import AnalysisResult
from contextrot.analysis.rot import RotCurve
from contextrot.report._hero import hero_stat

# Chart geometry (viewBox units)
_PLOT_X0, _PLOT_X1 = 60, 840
_PLOT_Y0, _PLOT_Y1 = 20, 260  # y grows downward; Y1 is the baseline

_COMP_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"]

# Share-card palette. Literal hex, never CSS vars: the card SVG is serialized
# and rasterized outside the page, where page-level custom properties do not
# exist. Fixed dark design so every export looks identical.
_CARD = {
    "bg": "#0d0d0d",
    "surface": "#1a1a19",
    "ink": "#ffffff",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "bar": "#3987e5",
}
_CARD_ACCENT = {
    "rot": "#e05252",
    "edge": "#fab219",
    "clean": "#22b322",
    "insufficient": "#fab219",
}


def render_html(result: AnalysisResult, out_path: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("template.html.j2")
    html = template.render(**_context(result))
    out_path = out_path.expanduser().resolve()
    if out_path.is_dir():
        out_path = out_path / "contextrot-report.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _chart_max_rate(buckets: list) -> float:
    """Y-axis ceiling for the rot chart.

    Low-confidence buckets are excluded: a 4-step bucket's Wilson interval
    tops out near 50% and squashes every real bar to the baseline. Fall back
    to all visible buckets when everything is low-confidence.
    """
    visible = [b for b in buckets if b.n > 0]
    trusted = [b for b in visible if not b.low_confidence] or visible
    max_rate = max((b.ci[1] for b in trusted), default=0.05)
    return max(max_rate, 0.05)


def _curve_geometry(
    curve: RotCurve,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    max_rate: float | None = None,
) -> dict:
    """Bars/gridlines/knee_x for a RotCurve rendered into an arbitrary plot
    rect. Pass a shared ``max_rate`` to place several curves on one honest
    y-scale (model small-multiples)."""
    if max_rate is None:
        max_rate = _chart_max_rate(curve.buckets)

    def y_of(rate: float) -> float:
        return y1 - (min(rate, max_rate) / max_rate) * (y1 - y0)

    visible = [b for b in curve.buckets if b.n > 0]
    peak_rate = max((v.rate for v in visible), default=0)

    slot_w = (x1 - x0) / len(curve.buckets)
    bar_w = slot_w * 0.6
    bars = []
    for i, b in enumerate(curve.buckets):
        if b.n == 0:
            continue
        x = x0 + i * slot_w + (slot_w - bar_w) / 2
        cx = x + bar_w / 2
        y = y_of(b.rate)
        lo_ci, hi_ci = b.ci
        past_knee = curve.knee_pct is not None and b.lo >= curve.knee_pct
        bars.append(
            {
                "x": round(x, 1),
                "y": round(y, 1),
                "w": round(bar_w, 1),
                "h": round(max(y1 - y, 1.5), 1),
                "cx": round(cx, 1),
                "ci_top": round(y_of(hi_ci), 1),
                "ci_bot": round(y_of(lo_ci), 1),
                "label": f"{b.lo}–{b.hi}",
                "val": f"{b.rate:.0%}",
                "show_val": b.rate == peak_rate and b.rate > 0,
                "past_knee": past_knee,
                "low_conf": b.low_confidence,
                "clipped": hi_ci > max_rate,
                "tip": (
                    f"{b.lo}–{b.hi}% fill: {b.rate:.1%} of {b.n} steps degraded "
                    f"(95% CI {lo_ci:.0%}–{hi_ci:.0%})"
                ),
            }
        )

    gridlines = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        rate = frac * max_rate
        gridlines.append({"y": round(y_of(rate), 1), "label": f"{rate:.0%}"})

    knee_x = None
    if curve.knee_pct is not None:
        knee_x = round(x0 + (curve.knee_pct / 100.0) * (x1 - x0), 1)

    return {"bars": bars, "gridlines": gridlines, "knee_x": knee_x, "max_rate": max_rate}


def _wrap(text: str, width: int = 48, max_lines: int = 2) -> list[str]:
    """Word-wrap for SVG <text> lines (SVG has no text wrapping)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        cut = lines[-1][: width - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        lines[-1] = cut.rstrip() + " …"
    return lines


def _fmt_rate(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "n/a"


def _fmt_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "n/a"
    if ratio == float("inf"):
        return "∞"
    return f"{ratio:.1f}×"


def _context(result: AnalysisResult) -> dict:
    curve = result.curve
    ratio = curve.degradation_ratio
    ratio_str = _fmt_ratio(ratio)

    icons = {"rot": "✗", "edge": "!", "clean": "✓", "insufficient": "?"}
    headline = {
        "verdict_kind": result.verdict_kind,
        "verdict_text": result.verdict_text,
        "verdict_icon": icons.get(result.verdict_kind, ""),
        "ratio": None if ratio in (None, float("inf")) else ratio,
        "ratio_str": ratio_str,
        "high_rate": _fmt_rate(curve.high_fill_rate),
        "low_rate": _fmt_rate(curve.low_fill_rate),
        "significant": curve.ratio_significant,
        "knee_str": f"~{curve.knee_pct}%" if curve.knee_pct is not None else "not found",
        "rework_cost": result.rework_cost_usd,
        "total_cost": result.total_cost_usd,
    }

    hero = hero_stat(result)
    chart = _curve_geometry(curve, _PLOT_X0, _PLOT_X1, _PLOT_Y0, _PLOT_Y1)

    # Model comparison: shared y-scale across all minis, or the comparison lies.
    models = []
    real_models = [m for m in result.models if not m.is_other]
    if len(real_models) >= 2:
        shared_max = max(_chart_max_rate(m.curve.buckets) for m in real_models)
        for m in result.models:
            mini = None
            if not m.is_other:
                mini = _curve_geometry(m.curve, 10, 270, 10, 100, max_rate=shared_max)
            models.append(
                {
                    "label": m.label,
                    "steps": m.steps,
                    "fresh": _fmt_rate(m.curve.low_fill_rate),
                    "deep": _fmt_rate(m.curve.high_fill_rate),
                    "ratio": _fmt_ratio(m.curve.degradation_ratio),
                    "knee": (f"~{m.curve.knee_pct}%" if m.curve.knee_pct is not None else "none"),
                    "verdict_kind": m.verdict_kind,
                    "verdict_icon": icons.get(m.verdict_kind, ""),
                    "is_other": m.is_other,
                    "mini": mini,
                }
            )

    # Per-project comparison: same shared-y-scale treatment as models.
    projects = []
    real_projects = [p for p in result.projects if not p.is_other]
    if len(real_projects) >= 2:
        shared_max = max(_chart_max_rate(p.curve.buckets) for p in real_projects)
        for p in result.projects:
            mini = None
            if not p.is_other:
                mini = _curve_geometry(p.curve, 10, 270, 10, 100, max_rate=shared_max)
            projects.append(
                {
                    "label": p.label,
                    "steps": p.steps,
                    "fresh": _fmt_rate(p.curve.low_fill_rate),
                    "deep": _fmt_rate(p.curve.high_fill_rate),
                    "ratio": _fmt_ratio(p.curve.degradation_ratio),
                    "knee": (f"~{p.curve.knee_pct}%" if p.curve.knee_pct is not None else "none"),
                    "verdict_kind": p.verdict_kind,
                    "verdict_icon": icons.get(p.verdict_kind, ""),
                    "is_other": p.is_other,
                    "mini": mini,
                }
            )

    comp = result.composition
    comp_rows_src = [
        ("Startup overhead (avg)", comp.overhead_tokens),
        ("Tool outputs (est.)", comp.tool_output_tokens),
        ("Conversation (est.)", comp.conversation_tokens),
        ("Other growth (est.)", comp.other_growth_tokens),
    ]
    comp_max = max((t for _, t in comp_rows_src), default=1) or 1
    comp_rows = []
    for i, (label, tokens) in enumerate(comp_rows_src):
        comp_rows.append(
            {
                "label": label,
                "y": 10 + i * 30,
                "w": round(600 * tokens / comp_max, 1),
                "val": f"{tokens:,}",
                "color": _COMP_COLORS[i % len(_COMP_COLORS)],
                "tip": f"{label}: ~{tokens:,} tokens",
            }
        )

    table_rows = []
    for b in curve.buckets:
        if b.n == 0:
            continue
        lo_ci, hi_ci = b.ci
        table_rows.append(
            {
                "range": f"{b.lo}–{b.hi}%",
                "n": b.n,
                "degraded": b.degraded,
                "rate": f"{b.rate:.1%}",
                "ci": f"{lo_ci:.0%}–{hi_ci:.0%}",
                **{
                    name: b.by_signal.get(name, 0)
                    for name in ("tool_error", "edit_failure", "retry", "reread", "self_correction")
                },
            }
        )

    reversal_rows = []
    for rb in result.reversal_curve.buckets:
        if rb.n == 0:
            continue
        lo_ci, hi_ci = rb.ci
        reversal_rows.append(
            {
                "range": rb.label,
                "n": rb.n,
                "degraded": rb.degraded,
                "rate": f"{rb.rate:.1%}",
                "ci": f"{lo_ci:.0%}-{hi_ci:.0%}",
                "low_conf": rb.low_confidence,
            }
        )

    # Share card: mini curve on the card's own plot rect, fixed hex colors.
    card_chart = _curve_geometry(curve, 640, 1140, 170, 470)
    card = {
        **_CARD,
        "accent": _CARD_ACCENT.get(result.verdict_kind, _CARD["bar"]),
        "hero": hero,
        "verdict_lines": _wrap(result.verdict_text, width=52, max_lines=3),
        "chart": card_chart,
        "footer": (
            f"{len(result.sessions)} sessions · {curve.total_steps:,} steps · "
            "pip install contextrot"
        ),
    }

    return {
        "meta": {
            "sessions": len(result.sessions),
            "steps": curve.total_steps,
            "days": result.days,
            "window": result.context_window,
            "version": __version__,
        },
        "headline": headline,
        "hero": hero,
        "chart": chart,
        "models": models,
        "projects": projects,
        "comp": {
            "rows": comp_rows,
            "height": 10 + len(comp_rows) * 30 + 10,
            "overhead_pct": comp.overhead_pct_of_window,
        },
        "prescriptions": result.prescriptions,
        "table_rows": table_rows,
        "reversal_rows": reversal_rows,
        "card": card,
    }
