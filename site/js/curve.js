// The curve: failure rate per 10% of context fill, with Wilson bands, morphing between
// the four verdicts. Every frame interpolates the numbers, not the paths, so a band
// widening or a threshold appearing reads as the data changing — which it is.

import { CURVES, wilson, zoneRates } from "./data.js";

const NS = "http://www.w3.org/2000/svg";
const W = 1000, H = 460;
const P = { l: 58, r: 18, t: 18, b: 120 };
const PH = H - P.t - P.b;            // plot height
const PW = W - P.l - P.r;
const YMAX = 0.16;
const HIST_Y = H - 32;               // histogram baseline
const HIST_H = 42;

const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.append(e);
  return e;
};

const BLUE = [59, 123, 255], VIOLET = [155, 92, 255], RED = [255, 59, 74];
function rampRGB(t) {
  t = Math.max(0, Math.min(1, t));
  const [a, b, u] = t < 0.5 ? [BLUE, VIOLET, t * 2] : [VIOLET, RED, (t - 0.5) * 2];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * u)).join(",")})`;
}
// colour a rate: around the typical 4% is calm blue, ~11% is red
const heat = (r) => (r - 0.045) / 0.06;

function prepare(v) {
  const c = CURVES[v];
  return c.curve.map((b) => {
    const rate = b.n ? b.failures / b.n : null;
    const [lo, hi] = wilson(b.failures, b.n);
    return { n: b.n, rate, lo, hi, a: b.n >= 20 ? 1 : 0 };
  });
}

export function initCurve(root, { reduced = false } = {}) {
  const svg = root.querySelector(".curve-svg");
  const tip = root.querySelector(".curve-tip");
  const fig = root.querySelector(".curve-figure");
  const side = {
    source: root.querySelector("[data-curve-source]"),
    title: root.querySelector("[data-curve-title]"),
    desc: root.querySelector("[data-curve-desc]"),
    fresh: root.querySelector("[data-curve-fresh]"),
    deep: root.querySelector("[data-curve-deep]"),
    ratio: root.querySelector("[data-curve-ratio]"),
  };
  const tabs = [...root.querySelectorAll(".ctab")];

  const x = (pct) => P.l + (pct / 100) * PW;
  const y = (r) => P.t + PH - (Math.min(r, YMAX) / YMAX) * PH;

  // defs
  const defs = el("defs", {}, svg);
  const bandGrad = el("linearGradient", { id: "bandGrad", x1: 0, y1: 0, x2: 1, y2: 0 }, defs);
  el("stop", { offset: "0", "stop-color": "#3b7bff", "stop-opacity": ".22" }, bandGrad);
  el("stop", { offset: "1", "stop-color": "#9b5cff", "stop-opacity": ".22" }, bandGrad);
  const glow = el("filter", { id: "glow", x: "-20%", y: "-20%", width: "140%", height: "140%" }, defs);
  el("feGaussianBlur", { stdDeviation: "5", result: "b" }, glow);
  const merge = el("feMerge", {}, glow);
  el("feMergeNode", { in: "b" }, merge);
  el("feMergeNode", { in: "SourceGraphic" }, merge);

  // zones
  const gz = el("g", {}, svg);
  el("rect", { x: x(0), y: P.t, width: x(40) - x(0), height: PH, fill: "rgba(59,123,255,0.045)" }, gz);
  el("rect", { x: x(60), y: P.t, width: x(100) - x(60), height: PH, fill: "rgba(255,59,74,0.04)" }, gz);
  el("text", { x: x(1), y: P.t + 16 }, gz).textContent = "FRESH  <40%";
  const dz = el("text", { x: x(99), y: P.t + 16, "text-anchor": "end" }, gz);
  dz.textContent = "DEEP  >60%";

  // grid
  const gg = el("g", {}, svg);
  for (const r of [0, 0.05, 0.1, 0.15]) {
    el("line", { x1: P.l, x2: W - P.r, y1: y(r), y2: y(r), stroke: "rgba(255,255,255,0.07)", "stroke-dasharray": r ? "2 6" : "" }, gg);
    el("text", { x: P.l - 12, y: y(r) + 4, "text-anchor": "end" }, gg).textContent = `${Math.round(r * 100)}%`;
  }
  for (let p = 0; p <= 100; p += 20) {
    el("text", { x: x(p), y: H - 10, "text-anchor": p === 0 ? "start" : p === 100 ? "end" : "middle" }, gg).textContent = `${p}%`;
  }
  el("text", { x: (P.l + W - P.r) / 2, y: H - 10, "text-anchor": "middle", opacity: 0 }, gg);
  const xl = el("text", { x: W - P.r, y: HIST_Y - HIST_H - 8, "text-anchor": "end" }, gg);
  xl.textContent = "steps per bucket";

  // threshold
  const thr = el("g", { opacity: 0 }, svg);
  const thrLine = el("line", { y1: P.t, y2: P.t + PH, stroke: "#ff3b4a", "stroke-width": 1.5, "stroke-dasharray": "4 5" }, thr);
  const thrLbl = el("text", { y: P.t + 36, fill: "#ff7b85", "text-anchor": "start" }, thr);

  // histogram of steps: pixel columns, the site's language
  const hist = el("g", {}, svg);
  const PIX = 7, COLS = 10;
  const histCols = [];
  for (let i = 0; i < COLS; i++) {
    const colG = el("g", {}, hist);
    const cells = [];
    for (let k = 0; k < 6; k++) {
      cells.push(el("rect", { width: PIX * 4, height: PIX - 2, rx: 1.5, x: x(i * 10 + 5) - PIX * 2, y: HIST_Y - (k + 1) * PIX, fill: "rgba(122,165,255,0.5)", opacity: 0 }, colG));
    }
    histCols.push(cells);
  }

  const band = el("path", { fill: "url(#bandGrad)" }, svg);
  const segs = [];
  for (let i = 0; i < COLS - 1; i++) segs.push(el("path", { fill: "none", "stroke-width": 3, "stroke-linecap": "round", filter: "url(#glow)" }, svg));
  const dots = [];
  for (let i = 0; i < COLS; i++) dots.push(el("circle", { r: 4, fill: "#05060a", "stroke-width": 2.5 }, svg));

  // hover targets
  const hov = el("g", {}, svg);
  const cross = el("line", { y1: P.t, y2: P.t + PH, stroke: "rgba(255,255,255,0.25)", opacity: 0 }, svg);
  for (let i = 0; i < COLS; i++) {
    const r = el("rect", { x: x(i * 10), y: P.t, width: x(10) - x(0), height: H - P.t - 20, fill: "transparent" }, hov);
    r.addEventListener("pointerenter", () => hover(i));
    r.addEventListener("pointermove", () => hover(i));
  }
  svg.addEventListener("pointerleave", () => { hovered = -1; tip.classList.remove("show"); cross.setAttribute("opacity", 0); });

  let verdict = "clean";
  let target = prepare(verdict);
  let cur = target.map((b) => ({ n: 0, rate: 0.02, lo: 0.02, hi: 0.02, a: 0 }));
  let thrCur = { x: 60, a: 0 };
  let hovered = -1;
  let running = false;
  let started = false;

  function hover(i) {
    hovered = i;
    const b = CURVES[verdict].curve[i];
    const t = target[i];
    const rect = svg.getBoundingClientRect();
    const fr = fig.getBoundingClientRect();
    const sx = rect.width / W, sy = rect.height / H;
    const px = rect.left - fr.left + x(i * 10 + 5) * sx;
    const py = rect.top - fr.top + y(t.rate ?? 0) * sy;
    tip.innerHTML = b.n
      ? `<b>${b.lo}–${b.hi}% full</b><br>${(t.rate * 100).toFixed(1)}% slipped · ${b.failures}/${b.n.toLocaleString()}<br>95% range ${(t.lo * 100).toFixed(1)}–${(t.hi * 100).toFixed(1)}%`
      : `<b>${b.lo}–${b.hi}% full</b><br>no steps here`;
    tip.style.left = `${px}px`;
    tip.style.top = `${py}px`;
    tip.classList.add("show");
    cross.setAttribute("x1", x(i * 10 + 5));
    cross.setAttribute("x2", x(i * 10 + 5));
    cross.setAttribute("opacity", 1);
  }

  function render() {
    const pts = cur.map((b, i) => [x(i * 10 + 5), y(b.rate)]);
    // band: hi forward, lo back
    let d = "";
    cur.forEach((b, i) => {
      const hi = b.rate + (b.hi - b.rate) * b.a;
      d += `${i ? "L" : "M"}${pts[i][0]},${y(hi)}`;
    });
    for (let i = cur.length - 1; i >= 0; i--) {
      const b = cur[i];
      const lo = b.rate - (b.rate - b.lo) * b.a;
      d += `L${pts[i][0]},${y(lo)}`;
    }
    band.setAttribute("d", d + "Z");

    for (let i = 0; i < segs.length; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
      const p0 = pts[i - 1] || pts[i], p3 = pts[i + 2] || pts[i + 1];
      const c1 = [x0 + (x1 - p0[0]) / 6, y0 + (y1 - p0[1]) / 6];
      const c2 = [x1 - (p3[0] - x0) / 6, y1 - (p3[1] - y0) / 6];
      segs[i].setAttribute("d", `M${x0},${y0}C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${x1},${y1}`);
      const a = Math.min(cur[i].a, cur[i + 1].a);
      segs[i].setAttribute("stroke", rampRGB(heat((cur[i].rate + cur[i + 1].rate) / 2)));
      segs[i].setAttribute("opacity", a.toFixed(3));
    }
    const maxN = Math.max(...target.map((b) => b.n), 1);
    cur.forEach((b, i) => {
      const dot = dots[i];
      dot.setAttribute("cx", pts[i][0]);
      dot.setAttribute("cy", pts[i][1]);
      dot.setAttribute("r", (3 + Math.min(9, Math.sqrt(b.n) / 9)) * (hovered === i ? 1.35 : 1));
      dot.setAttribute("stroke", rampRGB(heat(b.rate)));
      dot.setAttribute("opacity", b.a.toFixed(3));
      const lit = b.n > 0 ? Math.max(1, Math.round((Math.log1p(b.n) / Math.log1p(maxN)) * 6)) : 0;
      const hc = rampRGB(heat(b.rate));
      histCols[i].forEach((c, k) => {
        c.setAttribute("opacity", k < lit ? (0.22 + 0.5 * (k / 6)).toFixed(2) : 0);
        c.setAttribute("fill", hc);
      });
    });
    thrLine.setAttribute("x1", x(thrCur.x));
    thrLine.setAttribute("x2", x(thrCur.x));
    thrLbl.setAttribute("x", x(thrCur.x) + 10);
    thr.setAttribute("opacity", thrCur.a.toFixed(3));
  }

  function loop() {
    let moving = 0;
    const k = reduced ? 1 : 0.09;
    cur.forEach((b, i) => {
      const t = target[i];
      const tr = t.rate ?? (i ? cur[i - 1].rate : 0.03);
      for (const [key, tv] of [["rate", tr], ["lo", t.rate == null ? tr : t.lo], ["hi", t.rate == null ? tr : t.hi], ["n", t.n], ["a", t.a]]) {
        const dv = tv - b[key];
        b[key] += dv * k;
        moving = Math.max(moving, Math.abs(dv) / (key === "n" ? 10000 : 1));
      }
    });
    const thrT = CURVES[verdict].threshold;
    thrCur.a += ((thrT ? 1 : 0) - thrCur.a) * k;
    if (thrT) thrCur.x += (thrT - thrCur.x) * k;
    render();
    if (moving > 0.00005 || Math.abs((thrT ? 1 : 0) - thrCur.a) > 0.002) requestAnimationFrame(loop);
    else running = false;
  }
  const kick = () => { if (!running) { running = true; requestAnimationFrame(loop); } };

  const pct = (v) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
  function setVerdict(v) {
    verdict = v;
    target = prepare(v);
    const c = CURVES[v];
    tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.verdict === v)));
    side.source.textContent = c.source;
    side.title.textContent = c.title;
    side.desc.textContent = c.desc;
    const z = zoneRates(c.curve);
    side.fresh.textContent = pct(z.fresh);
    side.deep.textContent = z.deepN >= 150 ? pct(z.deep) : "–";
    side.ratio.textContent = z.fresh && z.deep && z.deepN >= 150 ? `${(z.deep / z.fresh).toFixed(2)}×` : "–";
    thrLbl.textContent = c.threshold ? `threshold ~${c.threshold}%` : "";
    root.dataset.verdict = v;
    if (started) kick();
    if (hovered >= 0) hover(hovered);
  }

  tabs.forEach((t) => t.addEventListener("click", () => setVerdict(t.dataset.verdict)));
  root.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key) || !e.target.classList.contains("ctab")) return;
    const i = tabs.indexOf(e.target);
    const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    n.focus();
    setVerdict(n.dataset.verdict);
  });

  setVerdict("clean");
  render();
  return {
    start() { if (started) return; started = true; kick(); },
  };
}
