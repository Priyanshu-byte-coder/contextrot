import { createField } from "./field.js";
import { splitWords, scramble, rotWord, countUp } from "./text.js";
import { initCurve } from "./curve.js";
import { initFactors } from "./factors.js";
import { initSignals } from "./signals.js";
import { initTerminal } from "./terminal.js";
import { initPool } from "./pool.js";
import { initShare } from "./share.js";
import { burst } from "./burst.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;

document.body.classList.add("loading");

/* ─── field ─────────────────────────────────────────────────── */
let field = null;
try { field = createField($("#field"), { reducedMotion: reduced }); } catch (e) { console.warn("field disabled:", e); }
if (field) field.jump({ fill: 0, rot: 1, rotStart: 0.42, heal: 0, opacity: 1 });
let introFill = 0;

/* ─── text prep ─────────────────────────────────────────────── */
$$("[data-split]").forEach(splitWords);
$$("[data-scramble]").forEach((el) => { el.dataset.final = el.textContent; if (!reduced) el.textContent = ""; });
rotWord($("[data-rot]"), { reduced });

/* ─── loader ────────────────────────────────────────────────── */
function runLoader() {
  const loader = $(".loader");
  const num = $("[data-loader-num]");
  const bar = $(".loader-bar");
  const done = () => {
    loader.classList.add("done");
    document.body.classList.remove("loading");
    setTimeout(() => loader.classList.add("gone"), 1200);
    introFill = 0.86;
    revealHero();
  };
  if (reduced) { done(); return; }
  const start = performance.now();
  const D = 1300;
  const tick = (now) => {
    const t = clamp((now - start) / D);
    const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    num.textContent = Math.round(e * 100);
    bar.style.setProperty("--p", e);
    if (t < 1) requestAnimationFrame(tick);
    else setTimeout(done, 180);
  };
  requestAnimationFrame(tick);
}

function revealHero() {
  const hero = $(".hero");
  $$("[data-split], [data-reveal]", hero).forEach((el) => el.classList.add("in"));
  $$("[data-scramble]", hero).forEach((el) => scramble(el, { reduced }));
}

/* ─── reveals ───────────────────────────────────────────────── */
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const el = e.target;
    if (el.closest(".hero")) continue;
    el.classList.add("in");
    if (el.matches("[data-scramble]")) scramble(el, { reduced });
    if (el.matches("[data-count]")) countUp(el, { reduced });
    io.unobserve(el);
  }
}, { threshold: 0.18, rootMargin: "0px 0px -6% 0px" });
$$("[data-split], [data-reveal], [data-scramble], [data-count]").forEach((el) => io.observe(el));

/* ─── components ────────────────────────────────────────────── */
const curve = initCurve($(".curve-card"), { reduced });
const factors = initFactors($("#factors"));
initSignals($$(".signal"), { reduced });
initTerminal($(".term"), { reduced });
initPool($(".pool"), { reduced });
initShare($("#share"), { reduced });

const once = (el, fn, threshold = 0.3) => {
  const o = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { fn(); o.disconnect(); } }, { threshold });
  o.observe(el);
};
once($(".curve-card"), () => curve.start(), 0.35);
once($(".factors-panel"), () => factors.start(), 0.25);

/* ─── scroll choreography ───────────────────────────────────── */
const nav = $(".nav");
const meterPct = $("[data-meter-pct]");
const meterBar = $("[data-meter-bar]");
const sceneWindow = $("#window");
const sceneAnswer = $("#answer");
const steps = $$(".wstep");
const hudPct = $("[data-hud-pct]");
const hudBar = $("[data-hud-bar]");
const hudTok = $("[data-hud-tokens]");
const hudState = $("[data-hud-state]");
const hudBox = $(".window-hud");
const winProg = $('[data-scene-progress="window"]');
const alines = $$("[data-aline]");
const answerCount = $("[data-answer-count]");
const footer = $(".footer");

const progressOf = (el) => {
  const r = el.getBoundingClientRect();
  return clamp(-r.top / (r.height - innerHeight));
};

let sy = scrollY;
let lastState = "";

function update() {
  const y = scrollY;
  sy = reduced ? y : lerp(sy, y, 0.2);
  if (Math.abs(sy - y) < 0.5) sy = y;

  // nav meter: how full is this page's context?
  const docH = document.documentElement.scrollHeight - innerHeight;
  const pagePct = clamp(y / docH);
  meterPct.textContent = `${Math.round(pagePct * 100)}%`;
  meterBar.style.transform = `scaleX(${pagePct})`;
  nav.classList.toggle("scrolled", y > 40);

  // the window scene
  const pw = progressOf(sceneWindow);
  const wr = sceneWindow.getBoundingClientRect();
  const inWindow = wr.top <= 0 && wr.bottom >= innerHeight;
  const fillW = smooth(0.05, 0.97, pw);
  const pctNum = Math.round(fillW * 100);
  hudPct.textContent = pctNum;
  hudBar.style.transform = `scaleX(${fillW})`;
  hudTok.textContent = `${Math.round(fillW * 1000)}k/1M`;
  const state = fillW < 0.42 ? "fresh" : fillW < 0.58 ? "filling" : "rotting?";
  if (state !== lastState) {
    lastState = state;
    hudState.textContent = state;
    hudState.className = `hud-state mono ${state === "filling" ? "warn" : state === "rotting?" ? "bad" : ""}`;
  }
  const heat = smooth(0.45, 0.85, fillW);
  hudBox.style.setProperty("--hud-c2", heat < 0.5 ? `color-mix(in srgb, #7aa5ff ${100 - heat * 200}%, #9b5cff)` : `color-mix(in srgb, #9b5cff ${200 - heat * 200}%, #ff3b4a)`);
  hudBox.style.setProperty("--hud-bar", heat < 0.5 ? "#3b7bff" : heat < 0.9 ? "#9b5cff" : "#ff3b4a");
  winProg.style.transform = `scaleX(${pw})`;

  const S = steps.length, span = 0.94 / S;
  steps.forEach((el, i) => {
    const t = (pw - 0.03 - i * span) / span;
    let o = smooth(0, 0.16, t) * (1 - smooth(0.84, 1, t));
    if (i === 0 && t < 0.5) o = 1 - smooth(0.84, 1, t);
    if (i === S - 1 && t > 0.5) o = smooth(0, 0.16, t);
    el.style.setProperty("--o", o.toFixed(3));
    el.style.setProperty("--dir", t < 0.5 ? 1 : -1);
  });

  // the answer scene
  const pa = progressOf(sceneAnswer);
  const ar = sceneAnswer.getBoundingClientRect();
  const aVis = [smooth(0.0, 0.1, pa), smooth(0.16, 0.28, pa), smooth(0.44, 0.58, pa), smooth(0.66, 0.78, pa)];
  alines.forEach((el) => el.style.setProperty("--o", aVis[+el.dataset.aline].toFixed(3)));
  answerCount.textContent = Math.round(31991 * smooth(0.16, 0.36, pa)).toLocaleString("en-US");

  if (field) {
    let t;
    const wide = innerWidth > 900;
    const side = wide ? 1 : 0;              // text sits in a left column on wide screens
    const base = wide ? 1 : 0.55;           // on phones the copy covers everything
    const beforeWindow = wr.top > 0;
    const afterAnswer = ar.bottom < innerHeight;
    if (beforeWindow) {
      // hero: the logo, alive; fading into the window scene
      t = { fill: introFill, rot: 1, rotStart: 0.3, heal: 0, opacity: base, leftFade: side, centerFade: 0 };
      if (wr.top < innerHeight) {
        const k = 1 - wr.top / innerHeight;
        t.fill = lerp(introFill, 0, smooth(0.5, 1, k));
      }
    } else if (inWindow || pw < 1) {
      const f = pw < 0.05 ? 0 : fillW;
      t = { fill: f, rot: smooth(0.5, 0.78, f), rotStart: 0.5, heal: 0, opacity: base, leftFade: side, centerFade: 0 };
    } else if (ar.top > 0) {
      // between: signals — dim it, keep the rot
      const k = ar.top / innerHeight;
      t = { fill: 1, rot: 1, rotStart: 0.5, heal: 0, opacity: k > 1 ? 0.14 : lerp(base, 0.14, smooth(0, 1, k)), leftFade: 0, centerFade: 1 };
    } else if (!afterAnswer) {
      // the finding: the rot heals
      t = { fill: 1, rot: 1, rotStart: 0.5, heal: smooth(0.42, 0.74, pa), opacity: base, leftFade: 0, centerFade: 1 };
    } else {
      const fr = footer.getBoundingClientRect();
      const k = clamp(1 - ar.bottom / innerHeight);
      const nearEnd = clamp(1 - fr.top / innerHeight);
      t = { fill: 1, rot: 1, rotStart: 0.5, heal: 1, opacity: lerp(lerp(base, 0.12, smooth(0, 0.6, k)), 0.4 * base, nearEnd), leftFade: 0, centerFade: 1 };
    }
    field.set(t);
  }

  requestAnimationFrame(update);
}

/* ─── pointer ───────────────────────────────────────────────── */
if (finePointer && !reduced) {
  document.documentElement.classList.add("has-cursor");
  const cur = $(".cursor");
  const dot = $(".cursor-dot");
  const ring = $(".cursor-ring");
  let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my;
  addEventListener("pointermove", (e) => {
    mx = e.clientX; my = e.clientY;
    field?.pointer(mx, my, true);
    const hot = e.target.closest("a, button, [role=button], .arc, .waffle i, .pool");
    cur.classList.toggle("is-hover", !!hot && !e.target.closest(".pool"));
  }, { passive: true });
  addEventListener("pointerdown", () => cur.classList.add("is-down"));
  addEventListener("pointerup", () => cur.classList.remove("is-down"));
  document.addEventListener("pointerleave", () => field?.pointer(mx, my, false));
  const follow = () => {
    rx = lerp(rx, mx, 0.16); ry = lerp(ry, my, 0.16);
    dot.style.transform = `translate(${mx}px, ${my}px)`;
    ring.style.transform = `translate(${rx}px, ${ry}px)`;
    requestAnimationFrame(follow);
  };
  follow();

  // magnetic buttons
  $$("[data-magnetic]").forEach((el) => {
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
      el.style.transform = `translate(${dx * 0.18}px, ${dy * 0.28}px)`;
    });
    el.addEventListener("pointerleave", () => {
      el.style.transition = "transform .6s cubic-bezier(.16,1,.3,1)";
      el.style.transform = "";
      setTimeout(() => (el.style.transition = ""), 600);
    });
  });
} else if (field) {
  // touch: a tap heals and ripples where you touch
  addEventListener("pointerdown", (e) => { field.pointer(e.clientX, e.clientY, true); setTimeout(() => field.pointer(e.clientX, e.clientY, false), 900); }, { passive: true });
}

// clicks on empty space send a ripple through the field
addEventListener("click", (e) => {
  if (!field || e.target.closest("a, button, input, .curve-svg, .clock-svg, .waffle, .pool, .term, pre")) return;
  field.ripple(e.clientX, e.clientY, 1);
});

/* ─── copy ──────────────────────────────────────────────────── */
const toast = $(".toast");
let toastT = 0;
function say(msg) {
  toast.textContent = msg;
  toast.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => toast.classList.remove("show"), 2200);
}
$$("[data-copy]").forEach((btn) => btn.addEventListener("click", async (e) => {
  const text = btn.dataset.copy;
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  btn.classList.add("copied");
  setTimeout(() => btn.classList.remove("copied"), 1800);
  say(`Copied: ${text}`);
  const r = btn.getBoundingClientRect();
  if (!reduced) {
    burst(e.clientX || r.left + r.width / 2, e.clientY || r.top + r.height / 2);
    field?.ripple(r.left + r.width / 2, r.top + r.height / 2, 1.4);
  }
}));

/* ─── nav: highlight the section in view ───────────────────── */
const links = $$(".nav-links a");
const secIO = new IntersectionObserver((es) => {
  for (const e of es) {
    if (!e.isIntersecting) continue;
    links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`));
  }
}, { rootMargin: "-45% 0px -50% 0px" });
$$("main > section[id]").forEach((s) => secIO.observe(s));

addEventListener("resize", () => field?.resize());

runLoader();
requestAnimationFrame(update);
