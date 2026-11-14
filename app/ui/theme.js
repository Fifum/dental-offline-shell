/* Theme before the first paint: load synchronously in <head>, before the stylesheets.
   Choice: "light" | "dark" | "system". Stored per user (dd.theme.<login>) and as the last choice on this
   computer (dd.theme), which is what the sign-in screen uses. Pages opened from files (first start, the
   saved copy) live on another origin, so the app passes the choice to them as ?theme=. */
(function () {
  "use strict";
  var KEY = "dd.theme", root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var ok = function (v) { return v === "light" || v === "dark" || v === "system"; };
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function write(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage off: still applies */ } }
  var q = /[?&]theme=(light|dark|system)\b/.exec(location.search);
  if (q) write(KEY, q[1]);
  function pref() { var v = read(KEY); return ok(v) ? v : "light"; }  // 3.9: light until someone picks another
  function apply(p) {
    p = ok(p) ? p : pref();
    var dark = p === "dark" || (p === "system" && !!(mq && mq.matches));
    var next = dark ? "dark" : "light", prev = root.getAttribute("data-theme");
    if (prev && prev !== next) {  // switch in one frame: no half-faded buttons from colour transitions
      root.classList.add("theme-switching");
      setTimeout(function () { root.classList.remove("theme-switching"); }, 60);
    }
    root.setAttribute("data-theme", next);
    root.setAttribute("data-theme-pref", p);
    return dark;
  }
  apply();
  if (mq) {
    var onSys = function () { if (pref() === "system") { apply("system"); fire(); } };
    if (mq.addEventListener) mq.addEventListener("change", onSys); else if (mq.addListener) mq.addListener(onSys);
  }
  function fire() {
    try { document.dispatchEvent(new CustomEvent("dd-theme", {detail: {pref: pref(), dark: root.getAttribute("data-theme") === "dark"}})); } catch (e) {}
  }
  window.DDTheme = {
    get: pref,
    isDark: function () { return root.getAttribute("data-theme") === "dark"; },
    /* p: new choice; login: whose choice it is (optional) */
    set: function (p, login) {
      if (!ok(p)) return;
      write(KEY, p);
      if (login) write(KEY + "." + login, p);
      apply(p); fire();
      var api = window.pywebview && window.pywebview.api;
      if (api && api.set_theme) api.set_theme(p).catch(function () {});
    },
    /* after sign-in: switch to this user's own choice, if they made one */
    useFor: function (login) {
      var v = login && read(KEY + "." + login);
      if (ok(v) && v !== pref()) this.set(v); else fire();
      return pref();
    }
  };
})();
