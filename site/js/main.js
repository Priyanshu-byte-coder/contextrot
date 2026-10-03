// The director: one scroll position in, every moving part out.

import { createField, COLS, ROWS } from "./field.js";
import { splitWords } from "./text.js";
import { initSignals } from "./signals.js";
import { initTerminal } from "./terminal.js";
import { initPool } from "./pool.js";
import { burst } from "./burst.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
const ASPECT = ROWS / COLS;

document.body.classList.add("loading");

/* ─── the window ─────────────────────────────────────────────── */
const frame = $(".frame");
const framePct = $("[data-frame-pct]");
const chartLine = $(".fc-line");
let field = null;
try { field = createField($("#field"), { reducedMotion: reduced }); } catch (e) { console.warn("field off:", e); }
if (!field) frame.style.display = "none";

// the "flat line" the finding draws inside the window: the real curve, 3.1–4.8%
(() => {
  const rates = [0.0477, 0.0396, 0.0333, 0.0372, 0.0259, 0.0369, 0.0302, 0.0373, 0.0203, 0.0119];
  const pts = rates.map((r, i) => [i * (640 / 9), 380 - (r / 0.12) * 380]);
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    d += ` C${x0 + 30},${y0} ${x1 - 30},${y1} ${x1},${y1}`;
  }
  chartLine.setAttribute("d", d);
  chartLine.setAttribute("pathLength", "1");
})();

const extra = { chart: 0, draw: 0 };
if (field) {
  field.onframe = (s) => {
    const cell = s.w / COLS;
    const h = s.w * ASPECT;
    const pad = cell * 1.3;
    const bar = Math.max(24, s.w * 0.052);
    const fw = s.w + pad * 2;
    frame.style.width = `${fw}px`;
    frame.style.height = `${h + bar + pad * 1.6}px`;
    frame.style.transform = `translate(${s.x - pad}px, ${s.y - bar - pad * 0.6}px)`;
    frame.style.opacity = Math.min(1, s.opacity * 1.2).toFixed(3);
    frame.style.setProperty("--fw", `${fw}px`);
    frame.style.setProperty("--bar", `${bar}px`);
    const heat = clamp(s.rot * (1 - s.heal) * smooth(0.5, 0.9, s.fill));
    const c = heat < 0.5 ? [59 + (155 - 59) * heat * 2, 123 + (92 - 123) * heat * 2, 255] : [155 + 100 * (heat - 0.5) * 2, 92 - 33 * (heat - 0.5) * 2, 255 - 181 * (heat - 0.5) * 2];
    frame.style.setProperty("--rc", `rgba(${c.map(Math.round).join(",")},0.65)`);
    frame.style.setProperty("--chart", extra.chart.toFixed(3));
    frame.style.setProperty("--draw", extra.draw.toFixed(3));
    framePct.textContent = Math.round(s.fill * 100);
  };
}

/* rects for each chapter, in css px */
function rectHero(vw, vh) {
  if (vw > 900) {
    const w = Math.min(vw * 0.38, vh * 0.92);
    return { x: vw - w - Math.max(56, vw * 0.06), y: vh / 2 - (w * ASPECT) / 2 + 14, w };
  }
  const w = vw * 0.84;
  return { x: (vw - w) / 2, y: vh * 0.66, w };
}
function rectWindow(vw, vh) {
  if (vw > 900) {
    const w = Math.min(vw * 0.44, vh * 1.0);
    return { x: vw * 0.5, y: vh / 2 - (w * ASPECT) / 2 + 14, w };
  }
  const w = vw * 0.86;
  return { x: (vw - w) / 2, y: vh * 0.16, w };
}
function rectAnswer(vw, vh, z) {
  const w0 = vw > 900 ? Math.min(vw * 0.44, vh * 0.95) : vw * 0.86;
  const w1 = vw > 900 ? Math.min(vw * 0.8, vh * 1.18) : vw * 0.94;
  const w = lerp(w0, w1, z);
  return { x: (vw - w) / 2, y: vh / 2 - (w * ASPECT) / 2 + 16, w };
}
const mixRect = (a, b, t) => ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), w: lerp(a.w, b.w, t) });

/* ─── text prep ──────────────────────────────────────────────── */
$$("[data-split]").forEach(splitWords);

/* ─── loader ─────────────────────────────────────────────────── */
let introFill = 0;
function runLoader() {
  const loader = $(".loader"), num = $("[data-loader-num]"), bar = $(".loader-bar");
  const done = () => {
    loader.classList.add("done");
    document.body.classList.remove("loading");
    setTimeout(() => loader.classList.add("gone"), 1100);
    introFill = 0.74;
    $$(".hero [data-split], .hero [data-reveal]").forEach((el) => el.classList.add("in"));
  };
  if (reduced) return done();
  const t0 = performance.now(), D = 1100;
  const tick = (now) => {
    const t = clamp((now - t0) / D);
    const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    num.textContent = Math.round(e * 100);
    bar.style.setProperty("--p", e);
    if (t < 1) requestAnimationFrame(tick); else setTimeout(done, 150);
  };
  requestAnimationFrame(tick);
}

/* ─── reveals ────────────────────────────────────────────────── */
const io = new IntersectionObserver((es) => {
  for (const e of es) {
    if (!e.isIntersecting || e.target.closest(".hero")) continue;
    e.target.classList.add("in");
    io.unobserve(e.target);
  }
}, { threshold: 0.2 });
$$("[data-split], [data-reveal], .fac").forEach((el) => io.observe(el));

/* ─── components ─────────────────────────────────────────────── */
initSignals($$(".sig"), { reduced });
initTerminal($(".term"), { reduced });
initPool($(".pool"), { reduced });

/* ─── horizontal chapters ────────────────────────────────────── */
const tracks = $$("[data-hs]").map((sec) => ({ sec, track: $(".hs-track", sec), dir: sec.dataset.hs, x: null, dist: 0, panels: $$(".panel", sec) }));
function sizeTracks() {
  for (const t of tracks) {
    t.track.style.width = "max-content";
    t.dist = Math.max(0, t.track.scrollWidth - innerWidth);
    t.sec.style.height = `${t.dist + innerHeight * 1.15}px`;
  }
}

/* ─── share grid ─────────────────────────────────────────────── */
const waffle = $("[data-waffle]");
function buildWaffle() {
  const cols = innerWidth > 900 ? 44 : 20;
  const cell = innerWidth / cols;
  const rows = Math.ceil(waffle.parentElement.offsetHeight / cell) + 1;
  waffle.style.setProperty("--cols", cols);
  waffle.innerHTML = "";
  const lit = Math.floor(rows * 0.2) * cols + Math.floor(cols / 2);
  for (let i = 0; i < cols * rows; i++) {
    const c = document.createElement("i");
    if (i === lit) c.className = "lit";
    waffle.append(c);
  }
}
if (finePointer && !reduced) {
  $(".share").addEventListener("pointermove", (e) => {
    const el = document.elementsFromPoint(e.clientX, e.clientY).find((n) => n.parentElement === waffle);
    if (!el || el.classList.contains("lit")) return;
    el.classList.add("ping");
    setTimeout(() => el.classList.remove("ping"), 450);
  });
}

/* ─── scroll ─────────────────────────────────────────────────── */
const sec = {
  hero: $(".hero"), window: $("#window"), signals: $("#signals"), answer: $("#answer"), factors: $("#factors"),
};
const lines = $$("[data-l]");
const aEls = $$("[data-a]");
const heroNote = $(".hero-note");
const chapters = $$("[data-chapter]");
const chNum = $("[data-ch-num]"), chTitle = $("[data-ch-title]"), chBar = $("[data-ch-bar]");
let lastCh = "";

const prog = (r) => clamp(-r.top / Math.max(1, r.height - innerHeight));

function update() {
  const vw = innerWidth, vh = innerHeight;
  const R = {};
  for (const k in sec) R[k] = sec[k].getBoundingClientRect();

  // horizontal tracks
  for (const t of tracks) {
    const r = t.sec.getBoundingClientRect();
    const p = prog(r);
    const target = t.dir === "left" ? -p * t.dist : -(1 - p) * t.dist;
    t.x = t.x == null || reduced ? target : lerp(t.x, target, 0.14);
    t.track.style.transform = `translate3d(${t.x.toFixed(1)}px,0,0)`;
    if (r.top < vh && r.bottom > 0) {
      for (const pn of t.panels) {
        const b = pn.getBoundingClientRect();
        const off = (b.left + b.width / 2 - vw / 2) / vw;
        pn.style.setProperty("--lift", (off * off * 90).toFixed(1));
        pn.style.setProperty("--tilt", (off * 4).toFixed(2));
      }
    }
  }

  // chapter 01: lines
  const pw = prog(R.window);
  const ranges = [[-1, 0.36], [0.33, 0.68], [0.65, 2]];
  lines.forEach((el, i) => {
    const [a, b] = ranges[i];
    const o = smooth(a, a + 0.06, pw) * (1 - smooth(b - 0.06, b, pw));
    el.style.setProperty("--o", o.toFixed(3));
    el.style.setProperty("--dir", pw < (a + b) / 2 ? 1 : -1);
  });
  heroNote.style.opacity = R.hero.top < -40 ? 0 : 1;

  // chapter 03: the answer
  const pa = prog(R.answer);
  const aO = [smooth(0.03, 0.12, pa) * (1 - smooth(0.3, 0.38, pa)), smooth(0.58, 0.68, pa), smooth(0.76, 0.86, pa)];
  aEls.forEach((el) => el.style.setProperty("--o", aO[+el.dataset.a].toFixed(3)));
  extra.chart = smooth(0.6, 0.68, pa);
  extra.draw = smooth(0.62, 0.86, pa);

  // the window's journey
  if (field) {
    let t;
    if (R.window.top > 0) {
      // hero → window: glide from the right into place
      const k = smooth(0, 1, 1 - R.window.top / vh);
      t = { ...mixRect(rectHero(vw, vh), rectWindow(vw, vh), k), fill: lerp(introFill, 0.04, k), rot: lerp(0.55, 0, k), rotStart: 0.52, heal: 0, opacity: 1 };
    } else if (R.signals.top > 0) {
      // filling up; then sliding out left as the signals arrive
      const fill = smooth(0.04, 0.94, pw);
      const out = smooth(0, 1, 1 - R.signals.top / vh);
      const base = rectWindow(vw, vh);
      t = { ...base, x: lerp(base.x, -base.w - 80, out), fill, rot: smooth(0.55, 0.85, fill), rotStart: 0.5, heal: 0, opacity: 1 };
    } else if (R.answer.top > 0) {
      // arriving from the right, still rotten
      const k = smooth(0, 1, 1 - R.answer.top / vh);
      const base = rectAnswer(vw, vh, 0);
      t = { ...base, x: lerp(vw + 80, base.x, k), fill: 1, rot: 1, rotStart: 0.5, heal: 0, opacity: k > 0 ? 1 : 0 };
    } else if (R.factors.top > 0) {
      // zoom in, heal, draw the flat line; then leave to the right as the next track comes in from the left
      const z = smooth(0.12, 0.45, pa);
      const out = smooth(0, 1, 1 - R.factors.top / vh);
      const base = rectAnswer(vw, vh, z);
      t = { ...base, x: lerp(base.x, vw + 80, out), fill: 1, rot: 1, rotStart: 0.5, heal: smooth(0.36, 0.58, pa), opacity: lerp(1, 0.4, smooth(0.56, 0.64, pa)) };
    } else {
      t = { ...rectAnswer(vw, vh, 1), x: vw + 80, opacity: 0, heal: 1 };
    }
    field.set(t);
  }

  // chapter indicator
  let cur = chapters[0];
  for (const c of chapters) if (c.getBoundingClientRect().top <= vh * 0.5) cur = c;
  const cr = cur.getBoundingClientRect();
  const cp = cr.height > vh * 1.2 ? prog(cr) : clamp((vh * 0.5 - cr.top) / cr.height);
  if (cur.dataset.chapter !== lastCh) {
    lastCh = cur.dataset.chapter;
    chNum.textContent = cur.dataset.chapter;
    chTitle.textContent = cur.dataset.title;
  }
  chBar.style.transform = `scaleX(${cp.toFixed(3)})`;

  requestAnimationFrame(update);
}

/* ─── pointer ────────────────────────────────────────────────── */
const cursor = $(".cursor"), dot = $(".cursor-dot"), ring = $(".cursor-ring"), label = $(".cursor-label");
if (finePointer && !reduced) {
  document.documentElement.classList.add("has-cursor");
  let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my;
  addEventListener("pointermove", (e) => {
    mx = e.clientX; my = e.clientY;
    field?.pointer(mx, my, true);
    const copy = e.target.closest("[data-copy]");
    const hot = e.target.closest("a, button");
    cursor.classList.toggle("is-label", !!copy);
    cursor.classList.toggle("is-hover", !!hot && !copy);
    label.textContent = copy ? (copy.classList.contains("copied") ? "copied" : "copy") : "";
  }, { passive: true });
  document.addEventListener("pointerleave", () => field?.pointer(mx, my, false));
  const follow = () => {
    rx = lerp(rx, mx, 0.18); ry = lerp(ry, my, 0.18);
    dot.style.transform = `translate(${mx}px,${my}px)`;
    ring.style.transform = `translate(${rx}px,${ry}px)`;
    requestAnimationFrame(follow);
  };
  follow();
  $$("[data-magnetic]").forEach((el) => {
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.16}px, ${(e.clientY - r.top - r.height / 2) * 0.26}px)`;
    });
    el.addEventListener("pointerleave", () => {
      el.style.transition = "transform .6s cubic-bezier(.16,1,.3,1)";
      el.style.transform = "";
      setTimeout(() => (el.style.transition = ""), 600);
    });
  });
} else if (field) {
  addEventListener("pointerdown", (e) => { field.pointer(e.clientX, e.clientY, true); setTimeout(() => field.pointer(e.clientX, e.clientY, false), 900); }, { passive: true });
}
addEventListener("click", (e) => {
  if (field && !e.target.closest("a, button, .term, .end")) field.ripple(e.clientX, e.clientY, 1);
});

/* ─── copy ───────────────────────────────────────────────────── */
const toast = $(".toast");
let toastT = 0;
$$("[data-copy]").forEach((btn) => btn.addEventListener("click", async (e) => {
  const text = btn.dataset.copy;
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  btn.classList.add("copied");
  label.textContent = "copied";
  setTimeout(() => btn.classList.remove("copied"), 1800);
  toast.textContent = `copied: ${text}`;
  toast.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => toast.classList.remove("show"), 2000);
  if (!reduced) {
    const r = btn.getBoundingClientRect();
    burst(e.clientX || r.left + r.width / 2, e.clientY || r.top + r.height / 2);
  }
}));

/* ─── go ─────────────────────────────────────────────────────── */
function layoutAll() { sizeTracks(); buildWaffle(); field?.resize(); }
addEventListener("resize", layoutAll);
document.fonts?.ready.then(sizeTracks);
layoutAll();
if (field) {
  const r = rectHero(innerWidth, innerHeight);
  field.jump({ ...r, fill: 0, rot: 0.55, rotStart: 0.52, heal: 0, opacity: 1 });
}
runLoader();
requestAnimationFrame(update);
