"use strict";
/* Fitting the program into small windows: every data table (.tbl) gets a frame that scrolls sideways
   on its own, so a wide table never pushes the whole page wider than the window. Works for tables
   drawn later by any module. 3.18.1: the frame scrolls whenever its table is wider than it, on any
   monitor (it used to be only below 1100 px, and at 1280–1366 px with the full menu the lab, the stock
   and the inventory slid sideways as a whole); a table that fits keeps its sticky header. */
(function () {
  const due = new Set();
  let queued = false;
  const fit = () => {
    queued = false;
    for (const box of due) {
      const t = box.firstElementChild;
      if (box.isConnected && t) box.classList.toggle("x", t.offsetWidth > box.clientWidth + 1);
    }
    due.clear();
  };
  // measured in the next frame: never inside the observer's own call (no «ResizeObserver loop» warnings)
  const later = box => { due.add(box); if (!queued) { queued = true; requestAnimationFrame(fit); } };
  const ro = typeof ResizeObserver === "function"
    ? new ResizeObserver(es => { for (const e of es) { const box = e.target.closest(".tbl-scroll"); if (box) later(box); } }) : null;
  const wrap = root => {
    const list = root.matches && root.matches("table.tbl") ? [root] : root.querySelectorAll ? root.querySelectorAll("table.tbl") : [];
    for (const t of list) {
      const p = t.parentElement;
      if (!p || t.closest("[contenteditable]")) continue;
      let box = p;
      if (!p.classList.contains("tbl-scroll")) {
        box = document.createElement("div");
        box.className = "tbl-scroll";
        p.insertBefore(box, t);
        box.appendChild(t);
      }
      if (ro) { ro.observe(box); ro.observe(t); }
      later(box);
    }
  };
  wrap(document.body);
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) wrap(n);
  }).observe(document.body, {childList: true, subtree: true});
  addEventListener("resize", () => document.querySelectorAll(".tbl-scroll").forEach(later));
})();

/* 3.18.2: the big number of a tile («63 пара/мес.», «1 310 937,5 ₽») stays inside its tile on any monitor and with any
   data: it keeps one line and gets smaller until it fits (down to 65 % of its size); still too wide in a very narrow
   window — it wraps between words. Measured again when the tile changes its size or the number changes. */
const FIT_NUMS = ".eqc-tile>b,.eqs-tile>b,.stat>b,.sn-st>b";
const fitNumbers = (function () {
  const due = new Set();
  let queued = false;
  const fitOne = el => {
    el.style.fontSize = "";
    el.classList.remove("fit-wrap");
    if (!el.isConnected || !el.clientWidth || el.scrollWidth <= el.clientWidth + 1) return;
    const base = parseFloat(getComputedStyle(el).fontSize), least = Math.round(base * 6.5) / 10;
    let size = Math.max(least, Math.floor(base * el.clientWidth / el.scrollWidth * 10) / 10);
    el.style.fontSize = size + "px";
    while (el.scrollWidth > el.clientWidth + 1 && size > least) { size = Math.max(least, size - 0.5); el.style.fontSize = size + "px"; }
    if (el.scrollWidth > el.clientWidth + 1) el.classList.add("fit-wrap");
  };
  const run = () => { queued = false; const list = [...due]; due.clear(); list.forEach(fitOne); };
  const later = el => { due.add(el); if (!queued) { queued = true; requestAnimationFrame(run); } };
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(es => {
    for (const e of es) for (const b of e.target.children) if (b.matches(FIT_NUMS)) later(b);
  }) : null;
  const seen = new WeakSet();
  const scan = root => {
    const list = root.matches && root.matches(FIT_NUMS) ? [root] : root.querySelectorAll ? root.querySelectorAll(FIT_NUMS) : [];
    for (const b of list) {
      if (ro && b.parentElement && !seen.has(b.parentElement)) { seen.add(b.parentElement); ro.observe(b.parentElement); }
      later(b);
    }
  };
  scan(document.body);
  new MutationObserver(ms => {
    for (const m of ms) {
      const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      const b = t && t.closest && t.closest(FIT_NUMS);
      if (b) later(b);
      for (const n of m.addedNodes) if (n.nodeType === 1) scan(n);
    }
  }).observe(document.body, {childList: true, subtree: true, characterData: true});
  addEventListener("resize", () => document.querySelectorAll(FIT_NUMS).forEach(later));
  // the fonts of the brand arrive a moment later and change the width of every number
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => document.querySelectorAll(FIT_NUMS).forEach(later));
  return () => document.querySelectorAll(FIT_NUMS).forEach(later);
})();
