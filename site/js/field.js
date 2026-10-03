// The window: the logo, as a living object.
//
// A context window drawn as lines of code made of pixels — one GPU instance each, on a
// fixed grid, so moving or resizing the window moves and scales every pixel with it.
// The page drives a handful of numbers:
//
//   rect      where the window sits on screen (x, y, width); height follows the grid
//   fill      how far down the window has been "typed" (0..1)
//   rot       how strongly the deep lines dissolve into drifting pixels
//   rotStart  how deep in the window the rot begins
//   heal      a diagonal sweep that snaps every pixel back home
//   opacity
//
// The pointer heals rot near it and lenses the grid; clicks send ripples.

export const COLS = 64;
export const ROWS = 38;

const VERT = `#version 300 es
precision highp float;
layout(location=0) in vec2 a_quad;
layout(location=1) in vec4 a_cell;   // col, row, indent, len
layout(location=2) in vec4 a_rnd;

uniform vec2  u_res;
uniform vec3  u_rect;     // x, y, cell size (css px)
uniform vec2  u_grid;
uniform float u_time;
uniform float u_fill;
uniform float u_rot;
uniform float u_rotStart;
uniform float u_heal;
uniform float u_opacity;
uniform vec3  u_mouse;
uniform vec4  u_rip[4];

out vec2  v_uv;
out vec3  v_col;
out float v_a;
out float v_glow;

const vec3 BLUE   = vec3(0.231, 0.482, 1.000);
const vec3 VIOLET = vec3(0.608, 0.361, 1.000);
const vec3 RED    = vec3(1.000, 0.231, 0.290);
const float G = 2.4;

vec3 ramp(float t) {
  t = clamp(t, 0.0, 1.0);
  return t < 0.5 ? mix(BLUE, VIOLET, t * 2.0) : mix(VIOLET, RED, (t - 0.5) * 2.0);
}

void main() {
  float col = a_cell.x, row = a_cell.y, indent = a_cell.z, len = a_cell.w;
  float cell = u_rect.z;
  float x01 = col / u_grid.x;
  float y01 = row / u_grid.y;
  vec2 home = u_rect.xy + (vec2(col, row) + 0.5) * cell;

  // typing: a head moves down the rows; each line types left to right as it passes
  float head = u_fill * (u_grid.y + 2.0);
  float lineProg = clamp((head - row) / 1.6, 0.0, 1.0);
  float vis = clamp(lineProg * (len + 1.0) - (col - indent), 0.0, 1.0);

  // rot: deeper lines, and the ends of lines, go first — as in the logo
  float cf = (col - indent) / max(len, 1.0);
  float depth = y01 + (a_rnd.x - 0.5) * 0.09;
  float r = u_rot * smoothstep(u_rotStart, u_rotStart + 0.34, depth);
  r *= mix(0.25, 1.0, smoothstep(0.05, 0.85, cf));
  r *= 0.9 + 0.1 * sin(u_time * 0.45 + row * 0.37);

  // the finding: a diagonal sweep heals everything behind it
  float s = x01 * 0.55 + y01 * 0.45;
  float front = u_heal * 1.5 - 0.25;
  float healed = 1.0 - smoothstep(front - 0.07, front + 0.01, s);
  float flash = exp(-pow((s - front) * 14.0, 2.0)) * step(0.002, u_heal) * step(u_heal, 0.995);
  r *= 1.0 - healed;

  vec2 dm = home - u_mouse.xy;
  float md = length(dm);
  float reach = 4.0 + cell * 14.0;
  r *= mix(1.0, smoothstep(reach * 0.25, reach, md), u_mouse.z);

  float det = smoothstep(a_rnd.y * 0.86 + 0.06, a_rnd.y * 0.86 + 0.16, r);

  // detached pixels drift right and scatter, escaping the frame
  vec2 dir = vec2(0.5 + a_rnd.z * 2.6, (a_rnd.w - 0.42) * 2.0);
  float wob = u_time * (0.35 + a_rnd.z * 0.55) + a_rnd.w * 6.2831;
  vec2 drift = dir * cell * (1.5 + 6.5 * a_rnd.z) + vec2(sin(wob), cos(wob * 1.3)) * cell * 0.7;
  drift.y += sin(u_time * 0.3 + a_rnd.x * 6.2831) * cell * 0.8;
  vec2 pos = home + drift * det;

  float lens = exp(-md * md / (reach * reach * 0.45)) * u_mouse.z;
  pos += (md > 0.001 ? dm / md : vec2(0.0)) * lens * cell * 0.9;

  float bright = 0.0;
  for (int i = 0; i < 4; i++) {
    vec4 rp = u_rip[i];
    if (rp.w <= 0.0) continue;
    vec2 dv = pos - rp.xy;
    float d = length(dv);
    float ring = rp.z * 700.0;
    float w = exp(-pow((d - ring) / 46.0, 2.0)) * exp(-rp.z * 1.5) * rp.w;
    pos += (d > 0.001 ? dv / d : vec2(0.0)) * w * cell * 1.6;
    bright += w;
  }

  float size = cell * (0.76 - det * (0.18 + 0.2 * a_rnd.w)) * mix(0.15, 1.0, vis);
  size *= 1.0 + lens * 0.5 + bright * 0.35;

  vec2 corner = pos + a_quad * size * 0.5 * G;
  vec2 clip = corner / u_res * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);

  float heat = clamp(r * 1.15 + det * 0.25, 0.0, 1.0);
  vec3 c = ramp(heat);
  c = mix(c, vec3(0.88, 0.94, 1.0), clamp(flash * 0.9 + bright * 0.5, 0.0, 1.0));

  float lively = clamp(r * 1.6 + det + flash + lens * 0.8 + bright, 0.0, 1.0);
  float flicker = mix(1.0, 0.6 + 0.4 * sin(u_time * (2.0 + a_rnd.x * 4.0) + a_rnd.y * 40.0), det);
  v_a = vis * u_opacity * flicker * (1.0 - det * 0.2) * mix(0.62, 1.0, lively);
  v_col = c;
  v_uv = a_quad * G;
  v_glow = 0.3 + flash * 2.2 + bright * 1.6 + lens * 0.6 + det * 0.25;
}`;

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
in vec3 v_col;
in float v_a;
in float v_glow;
out vec4 o;
void main() {
  vec2 q = abs(v_uv) - vec2(0.7);
  float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.3;
  float fw = max(fwidth(d), 1e-3);
  float core = 1.0 - smoothstep(-fw, fw, d);
  float glow = exp(-max(d, 0.0) * 2.6) * v_glow * 0.42;
  float a = (core + glow * (1.0 - core)) * v_a;
  o = vec4(v_col * a, a);
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Code-like lines on the fixed grid: indents, words, ragged ends. */
function layout() {
  const rand = mulberry32(2026);
  const margin = 3;
  const maxLen = COLS - margin * 2;
  const data = [];
  let indent = 0;
  for (let row = 1; row < ROWS - 1; row += 2) {
    if (rand() < 0.08) continue;
    const step = rand();
    if (step < 0.3) indent = Math.min(indent + 1, 4);
    else if (step < 0.52) indent = Math.max(indent - 1, 0);
    else if (step < 0.58) indent = 0;
    const ind = margin + indent * 3;
    const len = Math.max(5, Math.min(maxLen - indent * 3, Math.round(maxLen * (0.3 + Math.sqrt(rand()) * 0.66))));
    let c = 0;
    while (c < len) {
      const word = 2 + Math.floor(rand() * 8);
      for (let k = 0; k < word && c < len; k++, c++) data.push(ind + c, row, ind, len, rand(), rand(), rand(), rand());
      c += rand() < 0.82 ? 1 : 0;
    }
  }
  return new Float32Array(data);
}

export function createField(canvas, { reducedMotion = false } = {}) {
  const gl = canvas.getContext("webgl2", { antialias: false, alpha: true, premultipliedAlpha: true, powerPreference: "high-performance" });
  if (!gl) return null;

  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);

  const U = {};
  for (const n of ["u_res", "u_rect", "u_grid", "u_time", "u_fill", "u_rot", "u_rotStart", "u_heal", "u_opacity", "u_mouse", "u_rip"]) {
    U[n] = gl.getUniformLocation(prog, n);
  }

  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  const data = layout();
  const count = data.length / 8;
  const inst = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, inst);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(1);
  gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 0);
  gl.vertexAttribDivisor(1, 1);
  gl.enableVertexAttribArray(2);
  gl.vertexAttribPointer(2, 4, gl.FLOAT, false, 32, 16);
  gl.vertexAttribDivisor(2, 1);

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE);
  gl.clearColor(0, 0, 0, 0);

  let W = 0, H = 0;
  const cur = { x: 0, y: 0, w: 400, fill: 0, rot: 0, rotStart: 0.6, heal: 0, opacity: 1 };
  const tgt = { ...cur };
  const speed = { x: 0.085, y: 0.085, w: 0.085, fill: 0.05, rot: 0.06, rotStart: 0.06, heal: 0.08, opacity: 0.08 };
  const mouse = { x: -9999, y: -9999, tx: -9999, ty: -9999, s: 0, ts: 0 };
  const rips = [];
  let time = 0;
  let last = performance.now();
  let visible = true;
  let onframe = null;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible) return;
    if (!reducedMotion) time += dt;

    const k = reducedMotion ? 1 : Math.min(1, dt * 60);
    for (const key in cur) cur[key] += (tgt[key] - cur[key]) * Math.min(1, speed[key] * k);
    mouse.x += (mouse.tx - mouse.x) * Math.min(1, 0.18 * k);
    mouse.y += (mouse.ty - mouse.y) * Math.min(1, 0.18 * k);
    mouse.s += (mouse.ts - mouse.s) * Math.min(1, 0.06 * k);
    for (let i = rips.length - 1; i >= 0; i--) { rips[i].age += dt; if (rips[i].age > 2.6) rips.splice(i, 1); }

    onframe?.(cur);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (cur.opacity < 0.004) return;

    const cell = cur.w / COLS;
    gl.uniform2f(U.u_res, W, H);
    gl.uniform3f(U.u_rect, cur.x, cur.y, cell);
    gl.uniform2f(U.u_grid, COLS, ROWS);
    gl.uniform1f(U.u_time, time);
    gl.uniform1f(U.u_fill, cur.fill);
    gl.uniform1f(U.u_rot, cur.rot);
    gl.uniform1f(U.u_rotStart, cur.rotStart);
    gl.uniform1f(U.u_heal, cur.heal);
    gl.uniform1f(U.u_opacity, cur.opacity);
    gl.uniform3f(U.u_mouse, mouse.x, mouse.y, mouse.s);
    const rp = new Float32Array(16);
    rips.slice(-4).forEach((r, i) => rp.set([r.x, r.y, r.age, r.s], i * 4));
    gl.uniform4fv(U.u_rip, rp);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
  }

  resize();
  requestAnimationFrame(frame);
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; last = performance.now(); });

  return {
    set(t) { Object.assign(tgt, t); },
    jump(t) { Object.assign(tgt, t); Object.assign(cur, t); },
    get state() { return cur; },
    set onframe(fn) { onframe = fn; },
    pointer(x, y, on = true) { mouse.tx = x; mouse.ty = y; mouse.ts = on ? 1 : 0; if (mouse.x < -999) { mouse.x = x; mouse.y = y; } },
    ripple(x, y, s = 1) { rips.push({ x, y, age: 0, s }); },
    resize,
  };
}
