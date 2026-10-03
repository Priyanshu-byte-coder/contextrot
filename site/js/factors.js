// contextrot factors, as a ranked, expandable list — plus a 24-hour ring for time of day.

import { FACTORS, FACTOR_NAMES, extremes, phrase, wilson, MIN_N } from "./data.js";

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const rate = (g) => g.failures / g.n;

function finding(f) {
  const { worst, best } = extremes(f);
  const r = f.ratio.toFixed(1);
  const w = phrase(f.key, worst.label), b = phrase(f.key, best.label);
  if (f.strength === "none") return `No real difference: ${pct(rate(worst))} at worst against ${pct(rate(best))} at best — inside each other's error bars.`;
  let line = `Slips ${r}× as often ${w} as ${b} (${pct(rate(worst))} vs ${pct(rate(best))}).`;
  if (f.key === "context_fill" && f.ordinal && worst.label.startsWith("0")) line += " Backwards from the folklore: a fuller context isn't what hurts here.";
  if (f.strength === "maybe") line += " The ranges overlap, so treat it as a lead, not a finding.";
  if (f.key === "model" || f.key === "agent") line += " Confounded: different models and agents did different jobs.";
  if (f.key === "mistakes" && f.strength === "clear") line += " In this synthetic data, failures were generated independently — the effect is confounding with depth, which is why it says association, not causation.";
  return line;
}

function row(f, i) {
  const { worst, best } = extremes(f);
  const li = document.createElement("li");
  li.className = `factor ${f.strength}`;
  li.style.setProperty("--i", i);
  const gap = f.strength === "none" ? 0.04 : Math.min(1, Math.log(f.ratio) / Math.log(10));
  const vs = f.strength === "none"
    ? `<span>no real difference</span>`
    : `<span class="worst">${worst.label} ${pct(rate(worst))}</span> <span style="opacity:.5">vs</span> <span class="best">${best.label} ${pct(rate(best))}</span>`;

  const eligible = f.groups.filter((g) => g.n >= MIN_N);
  const shown = f.groups.slice(0, 8);
  const scaleMax = Math.max(...eligible.map((g) => wilson(g.failures, g.n)[1]), 0.05);
  const groupsHtml = shown.map((g) => {
    const [lo, hi] = wilson(g.failures, g.n);
    const cls = g.n < MIN_N ? "small" : g === worst ? "worst" : g === best ? "best" : "";
    const w = (v) => `${Math.min(100, (v / scaleMax) * 100)}%`;
    return `<div class="fd-g ${cls}">
      <span class="lbl">${g.label}</span>
      <span class="fd-track"><span class="bar" style="width:${w(rate(g))}"></span><span class="ci" style="left:${w(lo)};width:calc(${w(hi)} - ${w(lo)})"></span></span>
      <span class="num">${pct(rate(g))} · n=${g.n.toLocaleString()}</span>
    </div>`;
  }).join("");
  const more = f.groups.length > shown.length ? `<p class="mono" style="font-size:11px;color:var(--ink-3);margin:10px 0 0">+ ${f.groups.length - shown.length} smaller groups</p>` : "";
  const small = f.groups.some((g) => g.n < MIN_N) ? `<p class="mono" style="font-size:11px;color:var(--ink-3);margin:10px 0 0">faded rows have fewer than ${MIN_N} steps and don't take part</p>` : "";

  li.innerHTML = `
    <button class="factor-row" aria-expanded="false">
      <span class="f-mark ${f.strength}"></span>
      <span class="f-name">${FACTOR_NAMES[f.key]}</span>
      <span class="f-vs">${vs}</span>
      <span class="f-gap"><span>${f.ratio.toFixed(1)}×</span><span class="f-gap-bar"><i style="--g:${gap}"></i></span></span>
      <span class="f-strength">${f.strength === "none" ? "no effect" : f.strength}</span>
    </button>
    <div class="factor-detail"><div><div class="fd-inner">
      <p class="fd-finding">${finding(f)}</p>
      <div class="fd-groups">${groupsHtml}</div>${more}${small}
    </div></div></div>`;
  const btn = li.querySelector(".factor-row");
  btn.addEventListener("click", () => {
    const open = li.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
  });
  return li;
}

export function initFactors(section) {
  const list = section.querySelector("[data-factor-list]");
  const btns = [...section.querySelectorAll(".seg-btn")];
  let shown = false;

  function show(ds) {
    btns.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.dataset === ds)));
    list.innerHTML = "";
    FACTORS[ds].forEach((f, i) => list.append(row(f, i)));
    if (shown) grow();
  }
  function grow() {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      list.querySelectorAll(".f-gap-bar i").forEach((i) => { i.style.transform = `scaleX(${i.style.getPropertyValue("--g")})`; });
    }));
  }
  btns.forEach((b) => b.addEventListener("click", () => show(b.dataset.dataset)));
  show("real");
  initClock(section.querySelector(".clock-card"));
  return { start() { shown = true; grow(); list.firstElementChild?.querySelector(".factor-row")?.click(); } };
}

/* ─── the clock ─────────────────────────────────────────────── */

const NS = "http://www.w3.org/2000/svg";
const mk = (tag, attrs, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  parent.append(e);
  return e;
};

function arcPath(cx, cy, r, a0, a1) {
  const p = (a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0},${y0} A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1},${y1}`;
}

function initClock(card) {
  const svg = card.querySelector(".clock-svg");
  const val = card.querySelector("[data-clock-val]");
  const lbl = card.querySelector("[data-clock-lbl]");
  const tod = FACTORS.real.find((f) => f.key === "time_of_day").groups;
  const order = ["night", "morning", "afternoon", "evening"];
  const span = { night: "0–6h", morning: "6–12h", afternoon: "12–18h", evening: "18–24h" };
  const C = 160, R = 120;
  const rates = order.map((k) => rate(tod.find((g) => g.label === k)));
  const lo = Math.min(...rates), hi = Math.max(...rates);

  const defs = mk("defs", {}, svg);
  const f = mk("filter", { id: "cglow", x: "-30%", y: "-30%", width: "160%", height: "160%" }, defs);
  mk("feGaussianBlur", { stdDeviation: "6" }, f);

  // 24 ticks
  for (let h = 0; h < 24; h++) {
    const a = (h / 24) * Math.PI * 2;
    const r0 = h % 6 ? 146 : 140, r1 = 152;
    mk("line", { x1: C + r0 * Math.sin(a), y1: C - r0 * Math.cos(a), x2: C + r1 * Math.sin(a), y2: C - r1 * Math.cos(a), stroke: "rgba(255,255,255,.18)", "stroke-width": h % 6 ? 1 : 2 }, svg);
    if (h % 6 === 0) {
      const t = mk("text", { x: C + 164 * Math.sin(a), y: C - 164 * Math.cos(a) + 3.5, "text-anchor": "middle" }, svg);
      t.textContent = String(h).padStart(2, "0");
    }
  }
  mk("circle", { cx: C, cy: C, r: R, fill: "none", stroke: "rgba(255,255,255,.05)", "stroke-width": 26 }, svg);

  const arcs = order.map((k, i) => {
    const t = (rates[i] - lo) / (hi - lo || 1);
    const color = t > 0.66 ? "#ff3b4a" : t > 0.3 ? "#9b5cff" : "#3b7bff";
    const a0 = (i / 4) * Math.PI * 2 + 0.03, a1 = ((i + 1) / 4) * Math.PI * 2 - 0.03;
    const d = arcPath(C, C, R, a0, a1);
    const w = 12 + t * 16;
    const glowP = mk("path", { d, fill: "none", stroke: color, "stroke-width": w, opacity: 0.45, filter: "url(#cglow)", class: "arc-glow" }, svg);
    const p = mk("path", { d, fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "butt", class: "arc", tabindex: 0, role: "button", "aria-label": `${k}: ${pct(rates[i])}` }, svg);
    const len = p.getTotalLength();
    for (const e of [p, glowP]) { e.style.strokeDasharray = len; e.style.strokeDashoffset = len; e.style.transition = `stroke-dashoffset 1.4s cubic-bezier(.16,1,.3,1) ${i * 150}ms, opacity .3s`; }
    const pick = () => {
      val.textContent = pct(rates[i]);
      lbl.textContent = `${k} · ${span[k]}`;
      arcsEls.forEach((o, j) => { o.p.style.opacity = j === i ? 1 : 0.45; });
    };
    p.addEventListener("pointerenter", pick);
    p.addEventListener("focus", pick);
    p.addEventListener("click", pick);
    return { p, glowP };
  });
  const arcsEls = arcs;

  // the hand: your local time, now
  const hand = mk("g", {}, svg);
  mk("line", { x1: C, y1: C, x2: C, y2: C - 92, stroke: "rgba(255,255,255,.55)", "stroke-width": 1.5, "stroke-linecap": "round" }, hand);
  mk("circle", { cx: C, cy: C - 92, r: 3.5, fill: "#fff" }, hand);
  mk("circle", { cx: C, cy: C, r: 3, fill: "rgba(255,255,255,.6)" }, hand);
  const tick = () => {
    const d = new Date();
    const h = d.getHours() + d.getMinutes() / 60;
    hand.setAttribute("transform", `rotate(${(h / 24) * 360} ${C} ${C})`);
  };
  tick();
  setInterval(tick, 60000);

  const io = new IntersectionObserver((es) => {
    if (!es.some((e) => e.isIntersecting)) return;
    arcs.forEach(({ p, glowP }) => { p.style.strokeDashoffset = 0; glowP.style.strokeDashoffset = 0; });
    io.disconnect();
  }, { threshold: 0.35 });
  io.observe(svg);
}
