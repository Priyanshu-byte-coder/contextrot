// Five tiny pixel stories, one per failure signal, in the same language as the field.

const BLUE = "#3b7bff", BLUE2 = "#7aa5ff", VIOLET = "#9b5cff", RED = "#ff3b4a";
const DIM = "rgba(255,255,255,0.07)";
const ease = (t) => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
const inout = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));

function rand(seed) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) / 2147483647);
}

class Pix {
  constructor(canvas) {
    this.c = canvas;
    this.x = canvas.getContext("2d");
    this.resize();
  }
  resize() {
    const r = this.c.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.w = r.width; this.h = r.height;
    this.c.width = Math.round(r.width * dpr);
    this.c.height = Math.round(r.height * dpr);
    this.x.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cell = 10;
    this.cols = Math.floor(this.w / this.cell);
    this.rows = Math.floor(this.h / this.cell);
    this.ox = Math.round((this.w - this.cols * this.cell) / 2);
    this.oy = Math.round((this.h - this.rows * this.cell) / 2);
    this.left = Math.max(2, Math.round(this.cols * 0.1));
  }
  clear() { this.x.clearRect(0, 0, this.w, this.h); }
  px(c, r, color, a = 1, s = 1, glow = 0) {
    const x = this.x, k = this.cell;
    const size = (k - 2) * s;
    const cx = this.ox + c * k + k / 2, cy = this.oy + r * k + k / 2;
    x.globalAlpha = clamp(a);
    if (glow) { x.shadowColor = color; x.shadowBlur = glow; }
    x.fillStyle = color;
    x.beginPath();
    x.roundRect(cx - size / 2, cy - size / 2, size, size, Math.min(2, size / 4));
    x.fill();
    if (glow) x.shadowBlur = 0;
    x.globalAlpha = 1;
  }
  line(row, from, len, color, a = 1, skip) {
    for (let c = 0; c < len; c++) if (!skip || !skip(from + c)) this.px(from + c, row, color, a);
  }
}

/* each story: (p: Pix, t: seconds) → void */
const STORIES = {
  edit(p, t) {
    const T = 3.4; t %= T;
    const L = p.left, span = Math.min(p.cols - L * 2, 26);
    const rows = [3, 5, 7, 9, 11, 13].filter((r) => r < p.rows - 1);
    const gapRow = rows[2], gapC = L + 8, gapLen = 6;
    const lens = [span, span - 6, span - 2, span - 10, span - 4, span - 8];
    rows.forEach((r, i) => p.line(r, L + (i % 3 === 1 ? 2 : 0), lens[i], BLUE, 0.85, r === gapRow ? (c) => c >= gapC && c < gapC + gapLen : null));
    // the hole it was supposed to fill
    const pulse = 0.25 + 0.2 * Math.sin(t * 5);
    for (let c = 0; c < gapLen; c++) p.px(gapC + c, gapRow, BLUE2, pulse * (t > 2.6 ? 1 : 0.5), 0.55);

    const target = { c: gapC + 2.4, r: gapRow + 1.1 }; // lands wrong: a line low, a bit right
    const start = { c: p.cols + 2, r: gapRow - 3 };
    const r0 = rand(7);
    for (let k = 0; k < gapLen; k++) {
      let c, r, color = VIOLET, a = 1, s = 1, glow = 6;
      if (t < 1.1) {
        const e = inout(t / 1.1);
        c = start.c + (target.c - start.c) * e + k;
        r = start.r + (target.r - start.r) * e + Math.sin(e * Math.PI) * -1.2;
      } else if (t < 1.8) {
        const shake = Math.sin(t * 60) * 0.12 * (1.8 - t);
        c = target.c + k + shake; r = target.r;
        color = Math.floor(t * 9) % 2 ? RED : VIOLET; glow = 12;
      } else {
        const d = ease((t - 1.8) / 0.9);
        const rx = r0(), ry = r0();
        c = target.c + k + d * (1.5 + rx * 6); r = target.r + d * (ry - 0.3) * 4;
        color = RED; a = 1 - d; s = 1 - d * 0.5; glow = 0;
      }
      if (t < 2.8) p.px(c, r, color, a, s, glow);
    }
  },

  retry(p, t) {
    const T = 3.6; t %= T;
    const L = p.left, wall = Math.min(p.cols - L, L + 26);
    const midR = Math.floor(p.rows / 2) - 1;
    for (let r = 2; r < p.rows - 3; r++) p.px(wall, r, "rgba(255,255,255,0.22)", 1, 0.9);
    // dim context lines behind
    [3, 5, p.rows - 5].forEach((r, i) => p.line(r, L, [12, 8, 15][i], DIM, 1));
    const shots = [0, 1.1, 2.2];
    shots.forEach((s0, i) => {
      const lt = t - s0;
      if (lt < 0) return;
      const go = 0.55, back = 0.45;
      let c, color = BLUE2, a = 1;
      if (lt < go) c = L + (wall - 1 - L) * ease(lt / go);
      else if (lt < go + back) { const e = (lt - go) / back; c = wall - 1 - e * 7; color = RED; a = 1 - e; }
      else return;
      for (let k = 0; k < 4; k++) p.px(c - k * 0.9, midR + (k % 2 ? 0.08 : 0), color, a * (1 - k * 0.22), 1 - k * 0.12, k ? 0 : 10);
      if (lt >= go && lt < go + 0.12) for (let r = midR - 2; r <= midR + 2; r++) p.px(wall, r, RED, 1 - (lt - go) / 0.12, 1.1, 14);
    });
    // attempt counter
    shots.forEach((s0, i) => p.px(L + i * 2, p.rows - 2, t > s0 + 0.55 ? RED : DIM, 1, 0.8, t > s0 + 0.55 ? 8 : 0));
  },

  reread(p, t) {
    const T = 3.6; t %= T;
    const L = p.left;
    const rows = []; for (let r = 2; r < p.rows - 2; r += 2) rows.push(r);
    const lens = [22, 17, 24, 12, 20, 15, 23];
    const scan = (from, dur) => clamp((t - from) / dur);
    const s1 = scan(0.1, 1.2), s2 = scan(1.7, 1.2);
    const pos1 = 1 + s1 * (p.rows - 2), pos2 = 1 + s2 * (p.rows - 2);
    rows.forEach((r, i) => {
      const len = Math.min(lens[i % lens.length], p.cols - L * 2);
      const read1 = s1 > 0 && pos1 > r;
      const read2 = s2 > 0 && pos2 > r;
      const color = read2 ? RED : read1 ? BLUE2 : BLUE;
      const a = read2 ? 0.9 : read1 ? 0.95 : 0.45;
      p.line(r, L, len, color, a);
    });
    const bar = (pos, color, a) => {
      const x = p.x;
      const y = p.oy + pos * p.cell;
      const g = x.createLinearGradient(0, y - 34, 0, y);
      g.addColorStop(0, "transparent");
      g.addColorStop(1, color);
      x.globalAlpha = a;
      x.fillStyle = g;
      x.fillRect(p.ox, y - 34, p.cols * p.cell, 34);
      x.fillStyle = color;
      x.fillRect(p.ox, y - 1, p.cols * p.cell, 1.5);
      x.globalAlpha = 1;
    };
    if (s1 > 0 && s1 < 1) bar(pos1, "rgba(122,165,255,0.35)", 1);
    if (s2 > 0 && s2 < 1) bar(pos2, "rgba(255,59,74,0.4)", 1);
    if (t > 1.7 && t < 3.3) {
      p.x.font = "600 11px 'JetBrains Mono', monospace";
      p.x.fillStyle = RED;
      p.x.globalAlpha = clamp((t - 1.7) * 4) * clamp((3.3 - t) * 4);
      p.x.fillText("again ↻", p.w - p.ox - p.left * p.cell - 52, p.oy + 1.6 * p.cell);
      p.x.globalAlpha = 1;
    }
  },

  error(p, t) {
    const T = 3.2; t %= T;
    const L = p.left, row = Math.floor(p.rows / 2);
    const len = Math.min(p.cols - L * 2, 24);
    const typed = Math.floor(clamp(t / 1.1) * len);
    const r0 = rand(11);
    [row - 4, row - 2].forEach((r, i) => p.line(r, L, [14, 9][i], DIM, 1));
    p.px(L - 2, row, VIOLET, 1, 0.7);
    for (let c = 0; c < typed; c++) {
      const broken = t > 1.15 && c > len - 7;
      if (broken) continue;
      p.px(L + c, row, t > 1.15 && t < 1.6 ? RED : BLUE, 0.9);
    }
    if (t < 1.15 && Math.floor(t * 6) % 2) p.px(L + typed, row, "#fff", 0.9, 0.9);
    if (t > 1.15) {
      const lt = t - 1.15;
      for (let k = 0; k < 22; k++) {
        const vx = (r0() * 2 - 0.4) * 9, vy = -(r0() * 6 + 1);
        const c = L + len - 4 + vx * lt;
        const r = row + vy * lt + 9 * lt * lt;
        const a = 1 - lt / 1.6;
        if (a > 0) p.px(c, r, k % 3 ? RED : "#ffb03b", a, 0.6 + r0() * 0.4, 6);
      }
      if (lt < 0.25) {
        p.x.globalAlpha = 0.2 * (1 - lt / 0.25);
        p.x.fillStyle = RED;
        p.x.fillRect(0, 0, p.w, p.h);
        p.x.globalAlpha = 1;
      }
      if (lt > 0.3 && lt < 1.9) {
        p.x.font = "600 11px 'JetBrains Mono', monospace";
        p.x.fillStyle = RED;
        p.x.globalAlpha = clamp((lt - 0.3) * 4) * clamp((1.9 - lt) * 4);
        p.x.fillText("exit 1 · no such file", p.ox + L * p.cell, p.oy + (row + 3) * p.cell);
        p.x.globalAlpha = 1;
      }
    }
  },

  sorry(p, t) {
    const T = 5.2; t %= T;
    const x = p.x, L = p.ox + p.left * p.cell;
    x.font = "500 12.5px 'JetBrains Mono', monospace";
    x.textBaseline = "middle";
    const y1 = p.h * 0.36, y2 = p.h * 0.62;
    const a = "✓ Done — all tests pass.";
    const b = "I apologize, let me fix that.";
    const n1 = Math.floor(clamp(t / 1.0) * a.length);
    x.fillStyle = BLUE2;
    x.fillText(a.slice(0, n1), L, y1);
    if (t > 1.5) {
      const w = x.measureText(a).width;
      const e = ease((t - 1.5) / 0.45);
      x.strokeStyle = RED; x.lineWidth = 2;
      x.beginPath(); x.moveTo(L - 3, y1); x.lineTo(L - 3 + (w + 6) * e, y1); x.stroke();
      x.globalAlpha = 1;
    }
    if (t > 2.2) {
      const n2 = Math.floor(clamp((t - 2.2) / 1.3) * b.length);
      x.fillStyle = "#ff8b94";
      x.fillText(b.slice(0, n2), L, y2);
      if (n2 < b.length && Math.floor(t * 6) % 2) { const w = x.measureText(b.slice(0, n2)).width; x.fillRect(L + w + 2, y2 - 7, 7, 14); }
    }
    // a little block of context above, slowly losing pixels
    for (let c = 0; c < 18; c++) {
      const gone = (c * 7919) % 13 < (t / T) * 6;
      p.px(p.left + c, 2, gone ? VIOLET : BLUE, gone ? 0.25 : 0.4, 0.8);
    }
  },
};

export function initSignals(cards, { reduced = false } = {}) {
  const items = cards.map((card) => {
    const kind = card.dataset.signal;
    const canvas = card.querySelector("canvas");
    if (!kind || !canvas) return null;
    const item = { card, kind, pix: new Pix(canvas), t: 0.4 + Math.random() * 0.6, speed: 1, visible: false };
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
    card.addEventListener("pointerenter", () => { item.speed = 1.6; });
    card.addEventListener("pointerleave", () => { item.speed = 1; });
    return item;
  }).filter(Boolean);

  const io = new IntersectionObserver((es) => es.forEach((e) => {
    const it = items.find((i) => i.card === e.target);
    if (it) it.visible = e.isIntersecting;
  }), { rootMargin: "60px" });
  items.forEach((i) => io.observe(i.card));

  let last = performance.now();
  const draw = (now) => {
    requestAnimationFrame(draw);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    for (const it of items) {
      if (!it.visible) continue;
      if (!reduced) it.t += dt * it.speed;
      it.pix.clear();
      STORIES[it.kind](it.pix, reduced ? 1.4 : it.t);
    }
  };
  requestAnimationFrame(draw);
  window.addEventListener("resize", () => items.forEach((i) => i.pix.resize()));
}
