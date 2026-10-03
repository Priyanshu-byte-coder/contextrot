// The terminal: what contextrot actually prints, replayed. Text is taken from the
// synthetic showcase corpus — the same data behind every screenshot in the repo.

const sleep = (ms, tok) => new Promise((res, rej) => {
  const id = setTimeout(() => (tok.dead ? rej(new Error("x")) : res()), ms);
  tok.timers.push(id);
});

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const REPORT = [
  "",
  `<span class="t-badge"> ✗ CONTEXT ROT DETECTED </span>`,
  "",
  `  Your agent slips <span class="t-b t-red">11.1%</span> of the time when the context is nearly full, against <span class="t-b t-blue">5.0%</span> when it's fresh`,
  `  — <span class="t-b">2.2× worse</span>. Quality drops past <span class="t-b">~60% full</span> and stays down.`,
  `  <span class="t-dim">Also worth knowing:</span> it slips 2.7× as often after 3–4 earlier mistakes as with no mistakes yet`,
  `  in the session (15.3% vs 5.7%).`,
  "",
  `  <span class="t-dim">Measured on 5,943 steps, up to 90% full.</span>`,
  `  <span class="t-amber">8.1%</span> of your token spend went to steps that slipped — retries, failed edits and re-reads`,
  `  that produced nothing.`,
  "",
  `  <span class="t-b">What to do</span>`,
  `  <span class="t-violet">→</span> <span class="t-b">Compact or restart sessions before ~60% context fill</span>`,
  `     <span class="t-dim">Estimated $63.60 of recent spend went to degraded steps and their retries; most of it is</span>`,
  `     <span class="t-dim">concentrated past that threshold.</span>`,
  "",
  `  <span class="t-dim">Next</span>  <span class="t-cyan">contextrot --full</span>  <span class="t-dim">·</span>  <span class="t-cyan">contextrot factors</span>  <span class="t-dim">·</span>  <span class="t-cyan">contextrot share</span>`,
];

const gapbar = (r) => `<span style="display:inline-block;width:100px"><span class="t-gapbar" style="width:${Math.round(Math.min(1, Math.log(r) / Math.log(10)) * 90)}px"></span></span>`;
const FROWS = [
  ["●", "Mistakes so far", "3–4 15.3%", "none yet 5.7%", 2.7, "clear"],
  ["●", "Context fill", "60–80% 11.7%", "0–20% 4.3%", 2.7, "clear"],
  ["●", "Time of day", "night 9.4%", "evening 5.1%", 1.8, "clear"],
  ["◐", "Model", "GPT 5.4 7.0%", "Haiku 4.5 4.2%", 1.7, "maybe"],
  ["○", "Coding agent", null, null, 1.1, "no effect"],
  ["○", "Steps since you last spoke", null, null, 1.1, "no effect"],
];
const pad = (s, n) => s + " ".repeat(Math.max(0, n - s.length));
const FACTORS = [
  "",
  `  <span class="t-b">What actually moves your failure rate</span>`,
  `  <span class="t-dim">Measured on 5,943 steps.</span>`,
  "",
  `     <span class="t-dim">${pad("Factor", 28)}${pad("Worst vs best", 34)}Gap</span>`,
  ...FROWS.map(([m, n, w, b, r, s]) => {
    const vs = w ? `<span class="t-red">${w}</span>  <span class="t-dim">vs</span>  <span class="t-blue">${b}</span>` : `<span class="t-dim">no real difference</span>`;
    const vsLen = w ? w.length + b.length + 6 : 18;
    const strong = s === "clear" ? "t-b" : "t-dim";
    return `  <span class="${strong}">${m}</span>  <span class="${strong}">${pad(n, 28)}</span>${vs}${" ".repeat(Math.max(1, 34 - vsLen))}${r.toFixed(1)}×  ${s === "no effect" ? gapbar(1) : gapbar(r)}  <span class="${strong}">${s}</span>`;
  }),
  "",
  `  <span class="t-b">● Mistakes so far</span>`,
  `    It slips 2.7× as often after 3–4 earlier mistakes as with no mistakes yet in the session.`,
  `    <span class="t-violet">→</span> When mistakes start piling up, start a fresh session instead of pushing on.`,
  "",
  `  <span class="t-b">● Context fill</span>`,
  `    It slips 2.7× as often at 60–80% context fill as at 0–20% (11.7% vs 4.3%).`,
  `    <span class="t-violet">→</span> Compact or start fresh before the context reaches 60–80%.`,
  "",
  `  <span class="t-dim">Association, not causation. ● clear = ranges don't overlap, ◐ maybe = they do.</span>`,
];

export function initTerminal(root, { reduced = false } = {}) {
  const screen = root.querySelector("[data-term-screen]");
  const tabs = [...root.querySelectorAll(".ttab")];
  let tok = { dead: true, timers: [], raf: 0 };
  let current = null;
  let visible = false;

  const stop = () => {
    tok.dead = true;
    tok.timers.forEach(clearTimeout);
    cancelAnimationFrame(tok.raf);
    clearInterval(tok.iv);
  };

  const line = (html = "") => {
    const s = document.createElement("span");
    s.className = "ln";
    s.innerHTML = html || " ";
    screen.append(s);
    return s;
  };

  async function type(el, text, t, speed = 38) {
    if (reduced) { el.innerHTML = text; return; }
    for (let i = 1; i <= text.length; i++) {
      el.innerHTML = `<span class="t-violet">$</span> ${esc(text.slice(0, i))}<span class="t-caret"></span>`;
      await sleep(speed + Math.random() * 40, t);
    }
    el.innerHTML = `<span class="t-violet">$</span> ${esc(text)}`;
  }

  async function prompt(cmd, t) {
    const l = line();
    l.innerHTML = `<span class="t-violet">$</span> <span class="t-caret"></span>`;
    await sleep(reduced ? 0 : 500, t);
    await type(l, cmd, t);
    await sleep(reduced ? 0 : 250, t);
  }

  async function progress(label, t, ms = 1200) {
    const l = line(`  <span class="t-dim">${label}</span> <span class="t-prog"><i style="transform:scaleX(0)"></i></span> <span class="t-dim" data-c>0</span>`);
    const bar = l.querySelector("i"), c = l.querySelector("[data-c]");
    const start = performance.now();
    await new Promise((res, rej) => {
      const step = (now) => {
        if (t.dead) return rej(new Error("x"));
        const p = reduced ? 1 : Math.min(1, (now - start) / ms);
        bar.style.transform = `scaleX(${p})`;
        c.textContent = `${Math.round(p * 84)} sessions · ${p < 1 ? "parsing" : "2 agents"}`;
        if (p < 1) t.raf = requestAnimationFrame(step); else res();
      };
      t.raf = requestAnimationFrame(step);
    });
  }

  async function lines(arr, t, gap = 55) {
    for (const h of arr) { line(h); if (!reduced) await sleep(gap, t); }
  }

  const SCRIPTS = {
    async report(t) {
      await prompt("uvx contextrot", t);
      await progress("Reading sessions", t);
      await lines(REPORT, t);
      line(`<span class="t-violet">$</span> <span class="t-caret"></span>`);
    },
    async factors(t) {
      screen.classList.add("wide");
      await prompt("contextrot factors", t);
      await progress("Reading sessions", t, 900);
      await lines(FACTORS, t, 60);
      line(`<span class="t-violet">$</span> <span class="t-caret"></span>`);
    },
    async status(t) { statusLine(t); },
    async water(t) { water(t); },
  };

  /* ─── status line: a little Claude Code session, looping ───────────────── */
  function statusLine(t) {
    screen.innerHTML = `
      <div class="cc">
        <div class="cc-log" data-log></div>
        <div class="cc-input">&gt; <span data-input></span><span class="t-caret" style="background:var(--ink-3)"></span></div>
        <div class="cc-status" data-status></div>
      </div>`;
    const log = screen.querySelector("[data-log]");
    const input = screen.querySelector("[data-input]");
    const status = screen.querySelector("[data-status]");
    const THRESH = 60;
    let pct = 14, water = 214, frame = 0;
    const DROP = ["·", "⁘", "∘", "○", "◌", "∘", "·", " "];

    const cells = (p, n = 10) => {
      let h = "";
      for (let i = 0; i < n; i++) {
        const lit = (i + 0.5) / n * 100 < p;
        const at = (i + 0.5) / n * 100;
        const c = !lit ? "" : at < THRESH * 0.75 ? "#3b7bff" : at < THRESH ? "#9b5cff" : "#ff3b4a";
        h += `<i style="${c ? `background:${c}` : ""}"></i>`;
      }
      return `<span class="cc-bar">${h}</span>`;
    };
    const paint = () => {
      const k = Math.round(pct * 10);
      const left = Math.max(0, Math.round((THRESH - pct) / 4.5));
      const col = pct < THRESH * 0.75 ? "t-blue" : pct < THRESH ? "t-violet" : "t-red";
      status.innerHTML =
        `<span class="t-dim">ctx</span> <span class="${col} t-b">${Math.round(pct)}%</span> ${cells(pct)}` +
        `<span class="sep">·</span><span>${k}k/1M</span>` +
        `<span class="sep">·</span><span class="${pct >= THRESH ? "t-red" : ""}">${pct >= THRESH ? "past your threshold" : (left < 1 ? "threshold next turn" : `~${left} turns to your threshold`)}</span>` +
        `<span class="sep">·</span><span class="t-dim">5h</span> ${cells(24, 5)} <span>24%</span>` +
        `<span class="sep">·</span><span class="t-cyan">water ${water} ml</span> <span class="drop t-cyan">${DROP[frame % DROP.length]}</span>`;
    };
    const msg = (html, cls = "") => {
      const d = document.createElement("div");
      d.className = `cc-msg ${cls} ln`;
      d.innerHTML = html;
      log.append(d);
      while (log.children.length > 5) log.firstChild.remove();
    };
    const say = async (txt) => {
      for (let i = 1; i <= txt.length; i++) { input.textContent = txt.slice(0, i); await sleep(reduced ? 0 : 30, t); }
      await sleep(250, t);
      input.textContent = "";
    };

    const TURNS = [
      ["refactor the auth middleware to use the new session store", ["● Read src/auth/middleware.ts", "● Read src/session/store.ts", "● Edit src/auth/middleware.ts  (+42 −18)"]],
      ["now update the tests", ["● Read tests/auth.test.ts", "● Edit tests/auth.test.ts  (+31 −9)", "● Bash npm test — 48 passed"]],
      ["add rate limiting to the login route", ["● Read src/routes/login.ts", "● Edit src/routes/login.ts  (+27 −2)"]],
      ["and wire it into the config", ["● Read config/default.ts", "● Edit config/default.ts  (+6)", "● Bash npm test — 51 passed"]],
      ["document the new options in the README", ["● Read README.md", "● Edit README.md  (+19)"]],
    ];

    tok.iv = setInterval(() => { frame++; paint(); }, 180);
    paint();
    (async () => {
      try {
        for (;;) {
          for (const [ask, tools] of TURNS) {
            await sleep(reduced ? 0 : 700, t);
            await say(ask);
            msg(`<span class="who">you</span>${esc(ask)}`, "user");
            for (const tl of tools) {
              await sleep(reduced ? 0 : 650, t);
              msg(`<span class="t-dim">${esc(tl)}</span>`);
              const before = pct;
              pct = Math.min(96, pct + 2 + Math.random() * 3.5);
              water += Math.round(30 + Math.random() * 60);
              paint();
              if (before < THRESH && pct >= THRESH) {
                await sleep(500, t);
                const w = document.createElement("div");
                w.className = "cc-warn";
                w.innerHTML = `⚠ <b>contextrot</b>: this session just crossed <b>60%</b> — where <i>your</i> measured failure rate starts climbing. <span class="t-dim">/compact now keeps the next steps in your good range.</span>`;
                log.append(w);
                while (log.children.length > 5) log.firstChild.remove();
                await sleep(2600, t);
                await say("/compact");
                msg(`<span class="cc-sys">Compacted · ${Math.round(pct)}% → 12%</span>`);
                const from = pct;
                const t0 = performance.now();
                await new Promise((res) => {
                  const step = (now) => {
                    const p = Math.min(1, (now - t0) / 900);
                    pct = from + (12 - from) * (1 - Math.pow(1 - p, 3));
                    paint();
                    if (p < 1 && !t.dead) t.raf = requestAnimationFrame(step); else res();
                  };
                  t.raf = requestAnimationFrame(step);
                });
                await sleep(1200, t);
              }
            }
          }
        }
      } catch { /* tab switched */ }
    })();
  }

  /* ─── water: the tank, as the CLI draws it ──────────────────────────────── */
  function water(t) {
    screen.innerHTML = "";
    const head = line();
    const tank = Object.assign(document.createElement("canvas"), { className: "tank" });
    const out = document.createElement("div");
    (async () => {
      try {
        head.innerHTML = `<span class="t-violet">$</span> <span class="t-caret"></span>`;
        await sleep(400, t);
        await type(head, "contextrot water", t);
        const TOTAL = 57.1;
        const big = line(`  <span class="t-b t-cyan" style="font-size:2.2em;letter-spacing:-.02em">0.0 L</span>`);
        line(`  <span class="t-dim">of water · about 3 office water cooler jugs</span>`);
        screen.append(tank, out);
        const ctx = tank.getContext("2d");
        const dpr = Math.min(2, devicePixelRatio || 1);
        const r = tank.getBoundingClientRect();
        tank.width = r.width * dpr; tank.height = r.height * dpr;
        ctx.scale(dpr, dpr);
        const Wc = r.width, Hc = r.height, cw = 9, ch = 16;
        const cols = Math.floor((Wc - 4) / cw), rows = Math.floor((Hc - 4) / ch);
        const drops = [], ripples = [];
        const start = performance.now();
        let lastDrop = 0;
        const step = (now) => {
          if (t.dead) return;
          const s = (now - start) / 1000;
          const fillP = reduced ? 1 : 1 - Math.pow(1 - Math.min(1, s / 3.2), 3);
          big.innerHTML = `  <span class="t-b t-cyan" style="font-size:2.2em;letter-spacing:-.02em">${(TOTAL * fillP).toFixed(1)} L</span>`;
          ctx.clearRect(0, 0, Wc, Hc);
          ctx.strokeStyle = "rgba(255,255,255,.18)";
          ctx.strokeRect(1.5, 1.5, cols * cw + 2, rows * ch + 2);
          const level = 0.12 + fillP * 0.78; // fraction of height
          if (s - lastDrop > 0.12 + fillP * 0.5 && !reduced) {
            lastDrop = s;
            drops.push({ c: Math.floor(Math.random() * cols), y: 0, v: 0 });
          }
          const surf = (c) => {
            let h = Math.sin(c * 0.33 + s * 2.1) * 0.35 + Math.sin(c * 0.13 - s * 1.37) * 0.25;
            for (const rp of ripples) {
              const d = Math.abs(c - rp.c), a = s - rp.t;
              h += Math.cos(d * 0.9 - a * 9) * Math.exp(-d * 0.18) * Math.exp(-a * 2.2) * 0.9;
            }
            return h;
          };
          for (let c = 0; c < cols; c++) {
            const top = rows * (1 - level) - surf(c); // in rows, fractional
            const x = 2.5 + c * cw;
            for (let rr = 0; rr < rows; rr++) {
              const y = 2.5 + rr * ch;
              const cover = Math.max(0, Math.min(1, rr + 1 - top));
              if (cover <= 0) continue;
              const eighth = Math.ceil(cover * 8) / 8;
              const depth = (rr - top) / rows;
              ctx.fillStyle = `rgba(${Math.round(59 + 60 * (1 - depth))},${Math.round(123 + 60 * (1 - depth))},255,${0.35 + 0.5 * (1 - depth)})`;
              ctx.fillRect(x, y + ch * (1 - eighth), cw - 1.5, ch * eighth - 1);
            }
          }
          for (let i = drops.length - 1; i >= 0; i--) {
            const d = drops[i];
            d.v += 0.6; d.y += d.v * 0.2;
            const top = rows * (1 - level) - surf(d.c);
            if (d.y >= top) { ripples.push({ c: d.c, t: s }); drops.splice(i, 1); continue; }
            ctx.fillStyle = "#bcd2ff";
            ctx.fillRect(2.5 + d.c * cw + 2, 2.5 + d.y * ch, cw - 5, ch * 0.5);
          }
          while (ripples.length > 8) ripples.shift();
          if (s < 3.6 || !reduced) t.raf = requestAnimationFrame(step);
        };
        t.raf = requestAnimationFrame(step);
        await sleep(reduced ? 0 : 3300, t);
        const rows2 = [
          `  <span class="t-b">Where it went</span>`,
          `  cache reads  <span class="t-cyan">51.0 L</span>  <span class="t-bar" style="width:${0.89 * 260}px;background:#3b7bff"></span> 89%`,
          `  output       <span class="t-cyan">4.47 L</span>  <span class="t-bar" style="width:${0.08 * 260}px;background:#9b5cff"></span> 8%`,
          `  fresh input  <span class="t-cyan">1.64 L</span>  <span class="t-bar" style="width:${0.03 * 260}px;background:#ff3b4a"></span> 3%`,
          "",
          `  <span class="t-dim">19.8 kWh · 1.6B tokens · somewhere between 28.6 L and 114 L — an estimate, ±2×.</span>`,
        ];
        for (const h of rows2) { const l = document.createElement("span"); l.className = "ln"; l.innerHTML = h || " "; out.append(l); if (!reduced) await sleep(90, t); }
      } catch { /* switched */ }
    })();
  }

  function run(name) {
    stop();
    current = name;
    tok = { dead: false, timers: [], raf: 0 };
    screen.innerHTML = "";
    screen.classList.remove("wide");
    tabs.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.term === name)));
    SCRIPTS[name](tok).catch(() => {});
  }

  tabs.forEach((b) => b.addEventListener("click", () => run(b.dataset.term)));
  const io = new IntersectionObserver((es) => {
    const v = es.some((e) => e.isIntersecting);
    if (v && !visible) { visible = true; if (!current || tok.dead) run(current || "report"); }
    else if (!v && visible) { visible = false; if (current === "status" || current === "water") stop(); }
  }, { threshold: 0.25 });
  io.observe(root);
}
