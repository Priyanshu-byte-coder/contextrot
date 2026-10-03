// A burst of pixels — the copy button's reward.

const COLORS = ["#3b7bff", "#7aa5ff", "#9b5cff", "#ff3b4a", "#ffffff"];
let canvas, ctx, parts = [], running = false;

function ensure() {
  if (canvas) return;
  canvas = document.createElement("canvas");
  canvas.className = "burst";
  document.body.append(canvas);
  ctx = canvas.getContext("2d");
  const size = () => {
    const d = Math.min(2, devicePixelRatio || 1);
    canvas.width = innerWidth * d; canvas.height = innerHeight * d;
    canvas.style.width = innerWidth + "px"; canvas.style.height = innerHeight + "px";
    ctx.setTransform(d, 0, 0, d, 0, 0);
  };
  size();
  addEventListener("resize", size);
}

function loop() {
  ctx.clearRect(0, 0, innerWidth, innerHeight);
  parts = parts.filter((p) => p.life > 0);
  for (const p of parts) {
    p.vx *= 0.97; p.vy = p.vy * 0.97 + 0.22;
    p.x += p.vx; p.y += p.vy; p.life -= 0.018; p.rot += p.vr;
    ctx.save();
    ctx.globalAlpha = Math.max(0, p.life);
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rot);
    ctx.fillStyle = p.c;
    ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s);
    ctx.restore();
  }
  if (parts.length) requestAnimationFrame(loop);
  else { running = false; ctx.clearRect(0, 0, innerWidth, innerHeight); }
}

export function burst(x, y, n = 46) {
  ensure();
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const v = 3 + Math.random() * 7;
    parts.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 3, s: 3 + Math.random() * 5, c: COLORS[i % COLORS.length], life: 1, rot: Math.random() * 3, vr: (Math.random() - 0.5) * 0.3 });
  }
  if (!running) { running = true; requestAnimationFrame(loop); }
}
