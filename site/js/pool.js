// A pixel pool: a spring-mass surface you can drop water into.

export function initPool(canvas, { reduced = false } = {}) {
  const ctx = canvas.getContext("2d");
  const section = canvas.parentElement;
  const CELL = 8;
  let W = 0, H = 0, cols = 0, dpr = 1;
  let hgt = [], vel = [];
  const drops = [], sparks = [];
  let visible = false;
  let last = performance.now();
  let nextDrop = 0;
  let time = 0;

  function resize() {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(2, devicePixelRatio || 1);
    W = r.width; H = r.height;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(W / CELL);
    hgt = new Array(cols).fill(0);
    vel = new Array(cols).fill(0);
  }

  const rest = () => H * 0.34; // water surface distance from top of canvas

  function drop(x, big = false) {
    drops.push({ x, y: -20, v: big ? 2 : 0, s: big ? 1.6 : 1 });
  }

  function splash(c, s) {
    for (let k = -2; k <= 2; k++) if (hgt[c + k] !== undefined) vel[c + k] += (k ? 9 : 16) * s;
    for (let i = 0; i < 14 * s; i++) {
      sparks.push({ x: c * CELL, y: rest() + hgt[c] - 4, vx: (Math.random() - 0.5) * 5 * s, vy: -(2 + Math.random() * 5.5) * s, life: 1 });
    }
  }

  function step(dt) {
    time += dt;
    const k = 0.035, damp = 0.986, spread = 0.24;
    for (let i = 0; i < cols; i++) {
      vel[i] += -k * hgt[i];
      vel[i] *= damp;
      hgt[i] += vel[i];
    }
    for (let pass = 0; pass < 3; pass++) {
      for (let i = 0; i < cols; i++) {
        if (i > 0) { const d = spread * (hgt[i] - hgt[i - 1]); vel[i - 1] += d; }
        if (i < cols - 1) { const d = spread * (hgt[i] - hgt[i + 1]); vel[i + 1] += d; }
      }
    }
    for (let i = drops.length - 1; i >= 0; i--) {
      const d = drops[i];
      d.v += 0.55; d.y += d.v;
      const c = Math.max(0, Math.min(cols - 1, Math.round(d.x / CELL)));
      if (d.y >= rest() + hgt[c]) { splash(c, d.s); drops.splice(i, 1); }
    }
    for (let i = sparks.length - 1; i >= 0; i--) {
      const p = sparks[i];
      p.vy += 0.32; p.x += p.vx; p.y += p.vy; p.life -= 0.022;
      if (p.life <= 0 || p.y > rest() + 30) sparks.splice(i, 1);
    }
    if (time > nextDrop) { drop(Math.random() * W); nextDrop = time + 0.7 + Math.random() * 1.4; }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const r0 = rest();
    for (let c = 0; c < cols; c++) {
      const ambient = Math.sin(c * 0.08 + time * 1.3) * 3 + Math.sin(c * 0.031 - time * 0.9) * 4;
      const top = r0 + hgt[c] + ambient;
      const x = c * CELL;
      const topCell = Math.floor(top / CELL);
      for (let y = topCell * CELL; y < H; y += CELL) {
        const depth = (y - top) / (H - r0);
        if (y + CELL < top) continue;
        const a = Math.max(0, 0.62 - depth * 1.05);
        if (a <= 0.01) break;
        const surface = y < top + CELL;
        const lift = Math.min(1, Math.abs(vel[c]) * 0.15);
        ctx.fillStyle = surface
          ? `rgba(${170 + 60 * lift},${205 + 40 * lift},255,${0.95})`
          : `rgba(${40 + 50 * (1 - depth)},${80 + 70 * (1 - depth)},${215 + 40 * (1 - depth)},${a})`;
        ctx.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
      }
    }
    ctx.fillStyle = "#cfe0ff";
    for (const d of drops) {
      ctx.globalAlpha = 0.9;
      ctx.fillRect(d.x - 3 * d.s, d.y - 9 * d.s, 6 * d.s, 6 * d.s);
      ctx.globalAlpha = 0.35;
      ctx.fillRect(d.x - 2 * d.s, d.y - 20 * d.s, 4 * d.s, 8 * d.s);
    }
    for (const p of sparks) {
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillRect(Math.round(p.x / 4) * 4, Math.round(p.y / 4) * 4, 4, 4);
    }
    ctx.globalAlpha = 1;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible) return;
    if (!reduced) step(dt);
    draw();
  }

  section.addEventListener("pointerdown", (e) => {
    if (e.target.closest("a,button")) return;
    const r = canvas.getBoundingClientRect();
    if (e.clientY < r.top - 200) return;
    drop(e.clientX - r.left, true);
  });

  new IntersectionObserver((es) => { visible = es.some((e) => e.isIntersecting); }).observe(section);
  resize();
  window.addEventListener("resize", resize);
  requestAnimationFrame(frame);
}
