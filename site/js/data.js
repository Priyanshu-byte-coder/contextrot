// Every number on this page, in one place.
//
// "real"  — `contextrot share --days 0` on the maintainer's own sessions, 2026-10-04.
// "demo"  — the synthetic showcase corpus (scripts/make_showcase_data.py), the same data
//           behind every screenshot in the repo.
// "edge" and "insufficient" curves are illustrations of those verdicts, and are labelled so.

export const Z = 1.959964;

/** Wilson 95% interval, as contextrot computes it. */
export function wilson(k, n) {
  if (!n) return [0, 0];
  const p = k / n;
  const z2 = Z * Z;
  const den = 1 + z2 / n;
  const mid = (p + z2 / (2 * n)) / den;
  const half = (Z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / den;
  return [Math.max(0, mid - half), Math.min(1, mid + half)];
}

const curve = (ns, fs) => ns.map((n, i) => ({ lo: i * 10, hi: i * 10 + 10, n, failures: fs[i] }));

export const CURVES = {
  clean: {
    source: "Real sessions · one developer · 31,991 steps",
    title: "No measurable rot",
    desc: "The failure rate doesn't climb as the window fills — if anything, the freshest context is the worst. Filling the window isn't what hurts this developer. Something else does.",
    threshold: null,
    curve: curve(
      [2726, 6988, 5823, 4946, 4169, 3306, 2421, 1232, 296, 84],
      [130, 277, 194, 184, 108, 122, 73, 46, 6, 1],
    ),
  },
  rot: {
    source: "Demo dataset (synthetic) · 5,943 steps",
    title: "Context rot detected",
    desc: "Slips 2.2× as often with a nearly full context as with a fresh one, and the damage starts around 60%. The prescription writes itself: compact or restart before ~60%.",
    threshold: 60,
    curve: curve(
      [788, 945, 965, 936, 697, 648, 611, 264, 69, 20],
      [31, 44, 55, 51, 48, 42, 71, 31, 3, 2],
    ),
  },
  edge: {
    source: "Illustration",
    title: "Edge rot",
    desc: "Flat for most of the window, then it climbs near the limit. Use the room you have — just not the last stretch.",
    threshold: 80,
    curve: curve(
      [820, 960, 930, 880, 790, 700, 610, 420, 230, 96],
      [34, 38, 36, 37, 32, 29, 26, 19, 19, 10],
    ),
  },
  insufficient: {
    source: "Illustration",
    title: "Not enough data yet",
    desc: "Too few steps with a deep context to say anything honest — so it doesn't. Keep using your agent, or look further back with --days 0.",
    threshold: null,
    curve: curve(
      [140, 96, 64, 38, 20, 9, 3, 0, 0, 0],
      [7, 7, 2, 3, 2, 1, 0, 0, 0, 0],
    ),
  },
};

export function zoneRates(c) {
  const f = c.filter((b) => b.hi <= 40);
  const d = c.filter((b) => b.lo >= 60);
  const sum = (a, k) => a.reduce((s, b) => s + b[k], 0);
  const fr = sum(f, "n") ? sum(f, "failures") / sum(f, "n") : null;
  const dr = sum(d, "n") ? sum(d, "failures") / sum(d, "n") : null;
  return { fresh: fr, deep: dr, freshN: sum(f, "n"), deepN: sum(d, "n") };
}

const g = (label, n, failures) => ({ label, n, failures });

export const FACTORS = {
  real: [
    { key: "model", strength: "clear", ordinal: false, ratio: 8.535, groups: [g("Opus 5", 25548, 788), g("Opus 4.8", 1887, 94), g("Fable 5", 1651, 76), g("Opus 5.5", 1319, 34), g("GPT 5.4", 543, 47), g("Deepseek", 350, 77), g("other", 150, 6), g("Sonnet 5", 145, 10), g("GPT 5.6", 124, 0), g("Sonnet 4.6", 122, 5)] },
    { key: "agent", strength: "clear", ordinal: false, ratio: 4.526, groups: [g("claude-code", 30731, 1006), g("codex", 666, 47), g("opencode", 594, 88)] },
    { key: "context_fill", strength: "clear", ordinal: true, ratio: 2.274, groups: [g("0–20%", 9714, 407), g("20–40%", 10769, 378), g("40–60%", 7475, 230), g("60–80%", 3653, 119), g("80–100%", 380, 7)] },
    { key: "time_of_day", strength: "clear", ordinal: false, ratio: 1.596, groups: [g("night", 3268, 166), g("morning", 4178, 133), g("afternoon", 10464, 379), g("evening", 14081, 463)] },
    { key: "mistakes", strength: "none", ordinal: true, ratio: 1.071, groups: [g("none yet", 7834, 267), g("1", 2395, 74), g("2", 890, 41), g("3–4", 3550, 127), g("5+", 17322, 632)] },
    { key: "autonomy", strength: "none", ordinal: true, ratio: 1.046, groups: [g("1–3", 3481, 116), g("4–10", 5749, 205), g("11–25", 7588, 336), g("26+", 13651, 476)] },
  ],
  demo: [
    { key: "mistakes", strength: "clear", ordinal: true, ratio: 2.697, groups: [g("none yet", 4607, 262), g("1", 717, 49), g("2", 456, 42), g("3–4", 163, 25)] },
    { key: "context_fill", strength: "clear", ordinal: true, ratio: 2.694, groups: [g("0–20%", 1733, 75), g("20–40%", 1901, 106), g("40–60%", 1345, 90), g("60–80%", 875, 102), g("80–100%", 89, 5)] },
    { key: "time_of_day", strength: "clear", ordinal: false, ratio: 1.831, groups: [g("night", 780, 73), g("morning", 1121, 67), g("afternoon", 3455, 208), g("evening", 587, 30)] },
    { key: "model", strength: "maybe", ordinal: false, ratio: 1.682, groups: [g("Opus 5", 3347, 224), g("Sonnet 5", 1219, 68), g("GPT 5.4", 1016, 71), g("Haiku 4.5", 361, 15)] },
    { key: "agent", strength: "none", ordinal: false, ratio: 1.122, groups: [g("claude-code", 4927, 307), g("codex", 1016, 71)] },
    { key: "autonomy", strength: "none", ordinal: true, ratio: 1.118, groups: [g("1–3", 3363, 208), g("4–10", 1330, 92)] },
  ],
};

export const FACTOR_NAMES = {
  model: "Model",
  agent: "Coding agent",
  context_fill: "Context fill",
  time_of_day: "Time of day",
  mistakes: "Mistakes so far",
  autonomy: "Steps since you last spoke",
};

const HOURS = { night: "at night (0–6h)", morning: "in the morning (6–12h)", afternoon: "in the afternoon (12–18h)", evening: "in the evening (18–24h)" };

export function phrase(key, label) {
  switch (key) {
    case "model": return `on ${label}`;
    case "agent": return `in ${label}`;
    case "context_fill": return `at ${label} context fill`;
    case "time_of_day": return HOURS[label] || label;
    case "mistakes": return label === "none yet" ? "with no mistakes yet" : `after ${label} earlier mistakes`;
    case "autonomy": return `${label} steps after you last spoke`;
    default: return label;
  }
}

export const MIN_N = 150;

/** Worst and best group, the way `contextrot factors` picks them. */
export function extremes(f) {
  const el = f.groups.filter((x) => x.n >= MIN_N);
  const rate = (x) => x.failures / x.n;
  if (f.ordinal) {
    const [a, b] = [el[0], el[el.length - 1]];
    return rate(a) >= rate(b) ? { worst: a, best: b } : { worst: b, best: a };
  }
  const s = [...el].sort((a, b) => rate(b) - rate(a));
  return { worst: s[0], best: s[s.length - 1] };
}

export const SIGNAL_RATES = { edit: 0.0015, retry: 0.0068, reread: 0.007, error: 0.0219, sorry: 0.0014 };

export const SHARE_SAMPLE = {
  schema: 1,
  tool: "contextrot",
  version: "2.0.0",
  days: null,
  sessions: 57,
  steps: 31991,
  agents: ["claude-code", "codex", "opencode"],
  max_window: 1000000,
  verdict: { kind: "clean", threshold_pct: null, fresh_rate: 0.0383, deep_rate: 0.0312, ratio: 0.815, significant: false },
  curve: CURVES.clean.curve,
  signals: { edit_failure: 0.0015, reread: 0.007, retry: 0.0068, self_correction: 0.0014, tool_error: 0.0219 },
  waste_share: 0.0293,
};
