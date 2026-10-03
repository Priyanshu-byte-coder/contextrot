// contextrot share: the JSON, scanned for anything personal, and the dataset so far.

import { SHARE_SAMPLE } from "./data.js";

function highlight(obj) {
  // the same compact layout `share` prints: flat objects on one line
  const flat = (o) => !o || typeof o !== "object" || Object.values(o).every((v) => v === null || typeof v !== "object" || (Array.isArray(v) && v.every((x) => typeof x !== "object")));
  const val = (v) => {
    if (v === null) return `<span class="n">null</span>`;
    if (typeof v === "string") return `<span class="s">"${v}"</span>`;
    if (typeof v === "number" || typeof v === "boolean") return `<span class="n">${v}</span>`;
    if (Array.isArray(v)) return `[${v.map(val).join(", ")}]`;
    return `{${Object.entries(v).map(([k, x]) => `<span class="k">"${k}"</span>: ${val(x)}`).join(", ")}}`;
  };
  const lines = ["{"];
  const entries = Object.entries(obj);
  entries.forEach(([k, v], i) => {
    const comma = i < entries.length - 1 ? "," : "";
    if (Array.isArray(v) && v.length && typeof v[0] === "object") {
      lines.push(`  <span class="k">"${k}"</span>: [`);
      v.forEach((x, j) => lines.push(`    ${val(x)}${j < v.length - 1 ? "," : ""}`));
      lines.push(`  ]${comma}`);
    } else if (flat(v)) {
      lines.push(`  <span class="k">"${k}"</span>: ${val(v)}${comma}`);
    }
  });
  lines.push("}");
  return lines;
}

export function initShare(section, { reduced = false } = {}) {
  const box = section.querySelector(".share-json");
  const pre = section.querySelector("[data-share-json]");
  const label = section.querySelector("[data-scan-label]");
  const checks = [...section.querySelectorAll("[data-checks] li")];
  const waffle = section.querySelector("[data-waffle]");
  const cap = section.querySelector("[data-waffle-cap]");

  const lines = highlight(SHARE_SAMPLE);
  pre.innerHTML = lines.map((l) => `<span class="jl">${l}</span>`).join("\n");

  // waffle: one lit cell per curve shared so far
  const N = window.innerWidth < 560 ? 200 : 250;
  const capDefault = cap.textContent;
  for (let i = 0; i < N; i++) {
    const c = document.createElement("i");
    if (i === 0) c.className = "lit";
    c.addEventListener("pointerenter", () => {
      c.classList.add("hover");
      cap.textContent = i === 0 ? "The maintainer's curve: clean · 31,991 steps · 3 agents." : "An empty slot. Your curve could fill it.";
    });
    c.addEventListener("pointerleave", () => { c.classList.remove("hover"); cap.textContent = capDefault; });
    waffle.append(c);
  }

  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    if (reduced) {
      checks.forEach((c) => c.classList.add("ok"));
      label.textContent = "nothing personal ✓";
      label.classList.add("ok");
      return;
    }
    box.classList.add("scanning");
    const jl = [...pre.querySelectorAll(".jl")];
    const keys = [...pre.querySelectorAll(".k")];
    keys.forEach((k, i) => setTimeout(() => { k.classList.add("hl"); setTimeout(() => k.classList.remove("hl"), 380); }, (i / keys.length) * 2900));
    checks.forEach((c, i) => setTimeout(() => c.classList.add("ok"), 400 + i * 470));
    setTimeout(() => { label.textContent = "nothing personal ✓"; label.classList.add("ok"); }, 3200);
    void jl;
  };
  new IntersectionObserver((es, io) => { if (es.some((e) => e.isIntersecting)) { run(); io.disconnect(); } }, { threshold: 0.4 }).observe(box);
}
