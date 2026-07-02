"""Self-contained HTML report rendering.

Produces a single file with inline CSS/JS/SVG — no CDN, no network calls,
safe to share as-is.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from contextrot import __version__
from contextrot.analysis import AnalysisResult

# Chart geometry (viewBox units)
_PLOT_X0, _PLOT_X1 = 60, 840
_PLOT_Y0, _PLOT_Y1 = 20, 260  # y grows downward; Y1 is the baseline

_COMP_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"]


def render_html(result: AnalysisResult, out_path: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("template.html.j2")
    html = template.render(**_context(result))
    out_path = out_path.expanduser().resolve()
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _context(result: AnalysisResult) -> dict:
    curve = result.curve
    ratio = curve.degradation_ratio
    if ratio is None:
        ratio_str = "n/a"
    elif ratio == float("inf"):
        ratio_str = "∞"
    else:
        ratio_str = f"{ratio:.1f}×"

    headline = {
        "ratio": None if ratio in (None, float("inf")) else ratio,
        "ratio_str": ratio_str,
        "high_rate": f"{curve.high_fill_rate:.1%}" if curve.high_fill_rate is not None else "n/a",
        "low_rate": f"{curve.low_fill_rate:.1%}" if curve.low_fill_rate is not None else "n/a",
        "significant": curve.ratio_significant,
        "knee_str": f"~{curve.knee_pct}%" if curve.knee_pct is not None else "not found",
        "rework_cost": result.rework_cost_usd,
        "total_cost": result.total_cost_usd,
    }

    visible = [b for b in curve.buckets if b.n > 0]
    max_rate = max((b.ci[1] for b in visible), default=0.05)
    max_rate = max(max_rate, 0.05)

    def y_of(rate: float) -> float:
        return _PLOT_Y1 - (rate / max_rate) * (_PLOT_Y1 - _PLOT_Y0)

    slot_w = (_PLOT_X1 - _PLOT_X0) / len(curve.buckets)
    bar_w = slot_w * 0.6
    bars = []
    for i, b in enumerate(curve.buckets):
        if b.n == 0:
            continue
        x = _PLOT_X0 + i * slot_w + (slot_w - bar_w) / 2
        cx = x + bar_w / 2
        y = y_of(b.rate)
        lo_ci, hi_ci = b.ci
        past_knee = curve.knee_pct is not None and b.lo >= curve.knee_pct
        bars.append(
            {
                "x": round(x, 1),
                "y": round(y, 1),
                "w": round(bar_w, 1),
                "h": round(max(_PLOT_Y1 - y, 1.5), 1),
                "cx": round(cx, 1),
                "ci_top": round(y_of(hi_ci), 1),
                "ci_bot": round(y_of(lo_ci), 1),
                "label": f"{b.lo}–{b.hi}",
                "val": f"{b.rate:.0%}",
                "show_val": b.rate == max((v.rate for v in visible), default=0) and b.rate > 0,
                "past_knee": past_knee,
                "low_conf": b.low_confidence,
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
        knee_x = round(_PLOT_X0 + (curve.knee_pct / 100.0) * (_PLOT_X1 - _PLOT_X0), 1)

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

    return {
        "meta": {
            "sessions": len(result.sessions),
            "steps": curve.total_steps,
            "days": result.days,
            "window": result.context_window,
            "version": __version__,
        },
        "headline": headline,
        "chart": {"bars": bars, "gridlines": gridlines, "knee_x": knee_x},
        "comp": {
            "rows": comp_rows,
            "height": 10 + len(comp_rows) * 30 + 10,
            "overhead_pct": comp.overhead_pct_of_window,
        },
        "prescriptions": result.prescriptions,
        "table_rows": table_rows,
    }
