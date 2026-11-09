"use strict";
/* Motion helpers: the rail indicator that travels between sections, sliding pills in segmented
   controls, the one-time shell entrance after sign-in. Pure decoration — nothing waits for it. */
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");

  /* ---------- rail indicator ---------- */
  const rail = document.querySelector(".rail");
  const ind = document.createElement("i");
  ind.className = "rail-ind instant";
  rail.appendChild(ind);
  const navBox = rail.querySelector("nav");
  function moveRail() {
    const a = rail.querySelector(".nav.active:not([hidden])");
    if (!a) { ind.style.opacity = "0"; return; }
    const r = a.getBoundingClientRect(), base = rail.getBoundingClientRect();
    let top = r.top + 6, bottom = r.bottom - 6;
    if (navBox && navBox.contains(a)) {  /* the menu scrolls: show only the part of the item that is in view */
      const v = navBox.getBoundingClientRect();
      top = Math.max(top, v.top); bottom = Math.min(bottom, v.bottom);
    }
    ind.style.opacity = bottom > top + 2 ? "1" : "0";
    ind.style.setProperty("--y", `${top - base.top}px`);
    ind.style.setProperty("--h", `${Math.max(0, bottom - top)}px`);
    if (ind.classList.contains("instant") && !scrolling) { void ind.offsetWidth; setTimeout(() => ind.classList.remove("instant"), 30); }
  }
  /* while the menu scrolls the bar follows the item without the travel animation */
  let scrolling = null;
  if (navBox) navBox.addEventListener("scroll", () => {
    ind.classList.add("instant"); clearTimeout(scrolling);
    scrolling = setTimeout(() => { scrolling = null; ind.classList.remove("instant"); }, 150);
    moveRail();
  }, {passive: true});
  const _show = window.show;
  window.show = function (view) { _show(view); moveRail(); };
  addEventListener("resize", () => { ind.classList.add("instant"); moveRail(); });

  /* ---------- segmented controls ---------- */
  function syncSeg(seg) {
    if (!seg.offsetParent) return;  // hidden view
    let pill = seg.querySelector(":scope > .seg-ind");
    const on = seg.querySelector(":scope > button.on:not([hidden])");
    if (!pill) {
      pill = document.createElement("i");
      pill.className = "seg-ind instant";
      seg.prepend(pill);
      seg.classList.add("has-ind");
    }
    if (!on) { pill.style.opacity = "0"; return; }
    pill.style.opacity = "1";
    const x = on.offsetLeft, w = on.offsetWidth;
    if (pill._x === x && pill._w === w) return;
    pill._x = x; pill._w = w;
    pill.style.transform = `translateX(${x}px)`;
    pill.style.width = `${w}px`;
    if (pill.classList.contains("instant")) { void pill.offsetWidth; setTimeout(() => pill.classList.remove("instant"), 30); }
  }
  let queued = false;
  function syncAll() {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; document.querySelectorAll(".seg").forEach(syncSeg); }, 0);
  }
  new MutationObserver(syncAll).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["class", "hidden"]});
  addEventListener("resize", () => { document.querySelectorAll(".seg-ind").forEach(p => { p.classList.add("instant"); p._x = null; }); syncAll(); });

  /* ---------- sign-in moment and shell entrance ---------- */
  const _renderAuth = window.renderAuth;
  window.renderAuth = function (...a) {
    _renderAuth(...a);
    const b = (typeof AUTH_STATE !== "undefined" && AUTH_STATE && AUTH_STATE.brand) || (S.status && S.status.brand) || {};
    document.getElementById("authScreen").dataset.mark = b.short || "";
  };
  // the first screen may have been drawn before this file loaded: catch up
  const markNow = () => {
    const b = (typeof AUTH_STATE !== "undefined" && AUTH_STATE && AUTH_STATE.brand) || (S.status && S.status.brand) || {};
    if (b.short) document.getElementById("authScreen").dataset.mark = b.short;
  };
  markNow(); setTimeout(() => { markNow(); moveRail(); }, 1500);
  setTimeout(() => { ind.classList.add("instant"); moveRail(); }, 0);
  const _startApp = window.startApp;
  window.startApp = async function (user) {
    const first = !document.body.dataset.entered;
    if (first && !reduce.matches) document.body.classList.add("app-enter");
    document.body.dataset.entered = "1";
    const r = await _startApp(user);
    ind.classList.add("instant"); moveRail();
    setTimeout(() => document.body.classList.remove("app-enter"), 900);
    return r;
  };
})();
