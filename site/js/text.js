// Text effects: masked word rises, scramble-decode, and a rotting word.

/** Wrap every word in a mask so it can rise into view. Keeps <em>, <br>, <code>. */
export function splitWords(el) {
  let i = 0;
  const walk = (node) => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE) {
        const parts = child.textContent.split(/(\s+)/);
        const frag = document.createDocumentFragment();
        for (const part of parts) {
          if (!part) continue;
          if (/^\s+$/.test(part)) { frag.append(" "); continue; }
          const w = document.createElement("span");
          w.className = "w";
          const inner = document.createElement("span");
          inner.textContent = part;
          inner.style.setProperty("--i", i++);
          w.append(inner);
          frag.append(w);
        }
        child.replaceWith(frag);
      } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName !== "BR") {
        walk(child);
      }
    }
  };
  walk(el);
}

const GLYPHS = "░▒▓█▚▞▙▟<>/\\{}[]=+*#%&";

/** Decode text from noise, left to right. */
export function scramble(el, { duration = 900, reduced = false } = {}) {
  const final = el.dataset.final ?? (el.dataset.final = el.textContent);
  if (reduced) { el.textContent = final; return; }
  const start = performance.now();
  const n = final.length;
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    let out = "";
    for (let i = 0; i < n; i++) {
      const ch = final[i];
      const settle = (i / n) * 0.7 + 0.3;
      if (ch === " " || t >= settle) out += ch;
      else if (t > settle - 0.3) out += GLYPHS[(Math.random() * GLYPHS.length) | 0];
      else out += " ";
    }
    el.textContent = out;
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** The hero's "rot": every so often a letter decays into a block and comes back. */
export function rotWord(el, { reduced = false } = {}) {
  if (reduced) return;
  const word = el.textContent;
  el.textContent = "";
  el.setAttribute("aria-label", word);
  const spans = [...word].map((ch) => {
    const s = document.createElement("span");
    s.textContent = ch;
    s.setAttribute("aria-hidden", "true");
    s.style.display = "inline-block";
    s.style.transition = "transform .25s, opacity .25s, filter .25s";
    el.append(s);
    return s;
  });
  const decay = () => {
    const k = (Math.random() * spans.length) | 0;
    const s = spans[k];
    const orig = word[k];
    let n = 0;
    const iv = setInterval(() => {
      s.textContent = n % 2 ? orig : "#%/*&"[(Math.random() * 5) | 0];
      s.style.transform = `translate(${(Math.random() - 0.3) * 0.18}em, ${(Math.random() - 0.5) * 0.12}em)`;
      s.style.filter = n % 2 ? "none" : "blur(0.5px)";
      if (++n > 6) {
        clearInterval(iv);
        s.textContent = orig;
        s.style.transform = "none";
        s.style.filter = "none";
      }
    }, 70);
    setTimeout(decay, 1400 + Math.random() * 2600);
  };
  setTimeout(decay, 2200);
}

/** Count a number up when it comes into view. */
export function countUp(el, { reduced = false, duration = 1800 } = {}) {
  const target = parseFloat(el.dataset.count);
  const dec = parseInt(el.dataset.decimals || "0", 10);
  const fmt = (v) => v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  if (reduced) { el.textContent = fmt(target); return; }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const e = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
    el.textContent = fmt(target * e);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
