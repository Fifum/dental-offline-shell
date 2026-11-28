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
