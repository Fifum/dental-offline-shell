"use strict";
/* Fitting the program into small windows: every data table (.tbl) gets a frame that scrolls sideways
   on its own (styles-responsive.css turns the scrolling on below 1100 px), so a wide table never
   pushes the whole page wider than the window. Works for tables drawn later by any module. */
(function () {
  const wrap = root => {
    const list = root.matches && root.matches("table.tbl") ? [root] : root.querySelectorAll ? root.querySelectorAll("table.tbl") : [];
    for (const t of list) {
      const p = t.parentElement;
      if (!p || p.classList.contains("tbl-scroll") || t.closest("[contenteditable]")) continue;
      const box = document.createElement("div");
      box.className = "tbl-scroll";
      p.insertBefore(box, t);
      box.appendChild(t);
    }
  };
  wrap(document.body);
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) wrap(n);
  }).observe(document.body, {childList: true, subtree: true});
})();
