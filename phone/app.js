"use strict";
/* Dental Desk — склад в телефоне. A static PWA over the cloud of the stock (cloud/stock/functions/stock/index.ts):
   the clinic code once → who are you → a personal 6-digit PIN; rows of the stock live in IndexedDB (works offline),
   operations go to a queue with their own id (`op`), so a repeat after a lost answer is done once. */
const API = window.DD_API;
const MAIN = "Основной склад", SOON = 30, DAY = 864e5;
const $ = (s, el = document) => el.querySelector(s), $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const app = $("#app");
const LS = {
  get: (k) => { try { return JSON.parse(localStorage.getItem("dd." + k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem("dd." + k, JSON.stringify(v)); } catch { /* private mode */ } },
  del: (k) => { try { localStorage.removeItem("dd." + k); } catch { /* private mode */ } },
};
const S = { device: LS.get("device"), session: LS.get("session"), user: LS.get("user"), clinic: LS.get("clinic") || "",
  staff: LS.get("staff") || [], since: LS.get("since") || 0, last: LS.get("last") || 0, rows: new Map(), queue: [],
  syncing: false, stopCam: null, code: "", form: null };
let D = {};

/* ------------------------------------------------------------------------------------------------ small helpers */
const ICON = {
  back: '<path d="M15 5l-7 7 7 7"/>', home: '<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
  box: '<path d="M4 8l8-4 8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M7 12h10"/>',
  tool: '<path d="M14.5 6.5a4 4 0 0 0-5.3 5L4 16.7 7.3 20l5.2-5.2a4 4 0 0 0 5-5.3l-2.5 2.5-2.6-.6-.6-2.6z"/>',
  me: '<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
};
const ico = (n) => `<svg class="ico" viewBox="0 0 24 24">${ICON[n]}</svg>`;
const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const fmtDate = (s) => (s && /^\d{4}-\d\d-\d\d/.test(s) ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}` : s || "");
const days = (s) => Math.round((Date.parse(s) - Date.parse(today())) / DAY);
const q3 = (x) => Math.round((Number(x) || 0) * 1000) / 1000;
const qty = (x, unit) => `${q3(x).toLocaleString("ru-RU", { maximumFractionDigits: 3 })}${unit ? " " + esc(unit) : ""}`;
const money = (x) => `${(Math.round((Number(x) || 0) * 100) / 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const plural = (n, a, b, c) => { const m = Math.abs(n) % 100, k = m % 10; return m > 10 && m < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; };
const opId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/[^A-Za-z0-9]/g, "").slice(0, 40);
const can = (k) => !!(S.user && S.user.can && S.user.can[k]);

function toast(msg, bad) {
  $$(".toast").forEach((t) => t.remove());
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = msg;
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 5200 : 3200);
}

/* ------------------------------------------------------------------------------------------------ IndexedDB */
let dbp;
function idb() {
  return dbp ||= new Promise((ok, no) => {
    const r = indexedDB.open("dd-stock", 1);
    r.onupgradeneeded = () => { r.result.createObjectStore("rows", { keyPath: "id" }); r.result.createObjectStore("queue", { keyPath: "op" }); };
    r.onsuccess = () => ok(r.result);
    r.onerror = () => no(r.error);
  });
}
async function tx(store, fn) {
  const db = await idb();
  return new Promise((ok, no) => {
    const t = db.transaction(store, "readwrite"), st = t.objectStore(store), out = fn(st);
    t.oncomplete = () => ok(out && out.result);
    t.onerror = () => no(t.error);
  });
}
const idbAll = (s) => tx(s, (st) => st.getAll());
const idbPut = (s, items) => tx(s, (st) => items.forEach((x) => st.put(x)));
const idbDel = (s, keys) => tx(s, (st) => keys.forEach((k) => st.delete(k)));
const idbClear = (s) => tx(s, (st) => st.clear());

/* ------------------------------------------------------------------------------------------------ the cloud */
async function call(path, body, auth) {
  const h = { "Content-Type": "application/json" };
  if (auth === "device") h["X-DD-Device"] = (S.device || {}).token || "";
  if (auth === "session") h["X-DD-Session"] = S.session || "";
  let r;
  try { r = await fetch(API + path, { method: "POST", headers: h, body: JSON.stringify(body || {}) }); }
  catch { throw Object.assign(new Error("Нет связи с облаком склада"), { net: true }); }
  let j = {};
  try { j = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw Object.assign(new Error(j.error || `Ошибка ${r.status}`), { status: r.status, auth });
  return j;
}

function signedOut(e) {  // 401: the session is over → the PIN; the phone was disconnected → the clinic code
  if (e.status !== 401) return false;
  if (e.auth === "device" || /Телефон отключён|не подключён/.test(e.message)) { forget(); route(); }
  else { S.session = null; LS.del("session"); go("#/pin"); }
  toast(e.message, true);
  return true;
}

async function forget() {
  for (const k of ["device", "session", "user", "clinic", "staff", "since", "last", "owner"]) LS.del(k);
  Object.assign(S, { device: null, session: null, user: null, clinic: "", staff: [], since: 0, last: 0, rows: new Map(), queue: [] });
  await idbClear("rows").catch(() => {}); await idbClear("queue").catch(() => {});
  index();
}

async function sync(loud) {
  if (S.syncing || !S.session) return;
  S.syncing = true; badge();
  try {
    await flush();
    for (let more = true, n = 0; more && n < 60; n++) {
      const r = await call("/p/pull", { since: S.since }, "session");
      if (r.rows.length) {
        const put = [], del = [];
        for (const x of r.rows) {
          const id = x.t + "|" + x.k;
          if (x.row) { S.rows.set(id, { id, t: x.t, k: x.k, row: x.row }); put.push(S.rows.get(id)); }
          else { S.rows.delete(id); del.push(id); }
        }
        await idbPut("rows", put); if (del.length) await idbDel("rows", del);
      }
      S.since = r.next; S.user = r.user; more = r.more;
      LS.set("since", S.since); LS.set("user", S.user);
    }
    S.last = Date.now(); LS.set("last", S.last);
    index(); render();
    if (loud) toast("Данные обновлены");
  } catch (e) {
    if (!signedOut(e) && loud) toast(e.message, true);
  } finally { S.syncing = false; badge(); }
}

async function flush() {
  for (const q of [...S.queue].sort((a, b) => a.at - b.at)) {
    if (q.error) continue;
    try { await call("/p/op", q.body, "session"); await dropQ(q.op); }
    catch (e) {
      if (e.net || e.status === 401 || e.status >= 500) throw e;
      q.error = e.message; await idbPut("queue", [q]);
      toast(`«${q.title}» не прошло: ${e.message}`, true);
    }
  }
}
async function dropQ(op) { S.queue = S.queue.filter((q) => q.op !== op); await idbDel("queue", [op]); badge(); }

/* an operation: into the queue first, then to the cloud; without the network it waits there */
async function doOp(body, title) {
  body.op = opId();
  const q = { op: body.op, body, title, at: Date.now() };
  S.queue.push(q); await idbPut("queue", [q]); badge();
  try {
    const r = await call("/p/op", body, "session");
    await dropQ(q.op);
    toast(r.message || "Готово");
    sync();
    return r;
  } catch (e) {
    if (e.net) { toast("Нет связи — операция сохранена и уйдёт сама, когда появится сеть"); return { queued: true }; }
    await dropQ(q.op);
    if (!signedOut(e)) throw e;
    return null;
  }
}

/* ------------------------------------------------------------------------------------------------ the data */
const idOf = (k) => { try { return JSON.parse(k)[0]; } catch { return k; } };
function index() {
  D = { mats: new Map(), bar: new Map(), eq: new Map(), inv: new Map(), locs: new Map(), sups: new Map(), docs: new Map(),
    moves: [], mv: new Map(), lots: [], reqs: [], aps: [], ev: new Map(), set: new Map(), bal: new Map() };
  for (const { t, k, row } of S.rows.values()) {
    const id = idOf(k);
    if (t === "materials") { D.mats.set(id, row); if (row.barcode && Number(row.active ?? 1)) D.bar.set(String(row.barcode), id); }
    else if (t === "equipment") { D.eq.set(id, row); if (row.inv_number) D.inv.set(String(row.inv_number), id); }
    else if (t === "stock_locations") D.locs.set(id, row);
    else if (t === "suppliers") D.sups.set(id, row);
    else if (t === "stock_docs") D.docs.set(id, row);
    else if (t === "stock_moves") { D.moves.push(row); D.mv.set(id, row); }
    else if (t === "stock_lots") D.lots.push(row);
    else if (t === "stock_requests") D.reqs.push(row);
    else if (t === "stock_approvals") D.aps.push(row);
    else if (t === "equipment_events") { if (!D.ev.has(row.equipment_id)) D.ev.set(row.equipment_id, []); D.ev.get(row.equipment_id).push(row); }
    else if (t === "stock_settings") D.set.set(id, row.v);
  }
  for (const m of D.moves) {
    if (!D.bal.has(m.material_id)) D.bal.set(m.material_id, new Map());
    const b = D.bal.get(m.material_id), l = m.location_id || "";
    b.set(l, q3((b.get(l) || 0) + Number(m.qty || 0)));
  }
  const by = (a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""));
  D.reqs.sort(by); D.aps.sort(by); D.moves.sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
  for (const l of D.ev.values()) l.sort((a, b) => (b.date || "").localeCompare(a.date || "") || (b.created_at || "").localeCompare(a.created_at || ""));
}
const total = (mid) => q3([...(D.bal.get(mid) || new Map()).values()].reduce((s, x) => s + x, 0));
const at = (mid, loc) => q3((D.bal.get(mid) || new Map()).get(loc || "") || 0);
const places = () => [{ id: "", name: MAIN }, ...[...D.locs.values()].filter((p) => Number(p.active ?? 1)).sort((a, b) => String(a.name).localeCompare(b.name, "ru"))];
const placeName = (id) => (id ? (D.locs.get(id) || {}).name || "—" : MAIN);
const activeMats = () => [...D.mats.values()].filter((m) => Number(m.active ?? 1)).sort((a, b) => String(a.name).localeCompare(b.name, "ru"));

/* lots on hand worked out from the ledger (FEFO), as app/stock.py `_lots_by_material` does */
function lotsOf(mid) {
  const groups = new Map();
  for (const l of D.lots.filter((x) => x.material_id === mid).sort((a, b) => String(a.created_at).localeCompare(b.created_at))) {
    const key = (l.lot || "") + "|" + (l.expires || "");
    let g = groups.get(key);
    if (!g) {
      if (Number(l.qty) <= 0) continue;
      const mv = D.mv.get(l.move_id && l.move_id.$ref ? l.move_id.$ref[0] : "") || {}, doc = D.docs.get(mv.doc_id) || {};
      g = { lot: l.lot || "", expires: l.expires || "", qty: 0, created: l.created_at || "", received: (mv.at || "").slice(0, 10),
        doc: doc.number || "", supplier: (D.sups.get(doc.supplier_id) || {}).name || "" };
      groups.set(key, g);
    }
    g.qty += Number(l.qty || 0);
  }
  let left = Math.max(0, total(mid));
  const list = [...groups.values()].sort((a, b) => (b.expires || "9999-12-31").localeCompare(a.expires || "9999-12-31") || b.created.localeCompare(a.created));
  for (const g of list) {
    g.qty = q3(Math.max(0, g.qty)); g.left = q3(Math.min(g.qty, left)); left = q3(left - g.left);
    g.days = g.expires ? days(g.expires) : null;
    g.state = !g.expires ? "ok" : g.days < 0 ? "expired" : g.days <= SOON ? "soon" : "ok";
  }
  return { lots: list.reverse(), noLot: q3(left) };
}

const low = () => activeMats().filter((m) => Number(m.min_qty) > 0 && total(m.id) < Number(m.min_qty));
const expiring = () => activeMats().flatMap((m) => lotsOf(m.id).lots.filter((g) => g.left > 0 && g.state !== "ok").map((g) => ({ ...g, m })))
  .sort((a, b) => a.days - b.days);
const serviceDue = () => [...D.eq.values()].filter((e) => e.status !== "written_off" && e.next_service && days(e.next_service) <= SOON)
  .sort((a, b) => a.next_service.localeCompare(b.next_service));
const mine = (r) => S.user && r.created_by === S.user.login;
const pendingAps = () => D.aps.filter((a) => a.status === "pending" && (can("approve") || mine(a)));
const openReqs = () => D.reqs.filter((r) => ["new", "accepted", "partial"].includes(r.status) && (can("handle_requests") || mine(r)));

/* ------------------------------------------------------------------------------------------------ layout */
function badge() {
  const b = $("#net");
  if (!b) return;
  const n = S.queue.length, off = !navigator.onLine;
  b.className = "net" + (off ? " off" : n ? " q" : "");
  b.textContent = S.syncing ? "обновляю…" : off ? (n ? `офлайн · ${n} в очереди` : "офлайн") : n ? `${n} в очереди` : "";
  b.hidden = !b.textContent;
}

function page(title, body, opt = {}) {
  stopCam();
  const tab = opt.tab;
  const t = (h, n, label, cls = "") => `<a href="${h}" class="${cls}${tab === h ? " on" : ""}"><span>${ico(n)}</span>${label}</a>`;
  app.className = "";
  app.innerHTML = `<header class="top">${opt.back ? `<button class="back" data-back aria-label="Назад">${ico("back")}</button>` : ""}
      <h1>${esc(title)}</h1><span id="net" class="net" hidden></span></header>${body}
    <nav class="tabs">${t("#/", "home", "Главная")}${can("stock") ? t("#/stock", "box", "Склад") : "<span></span>"}
      ${t("#/scan", "scan", "Скан", "scan")}${can("equipment") ? t("#/eq", "tool", "Оборудование") : "<span></span>"}${t("#/me", "me", "Профиль")}</nav>`;
  const b = $("[data-back]");
  if (b) b.onclick = () => (history.length > 1 ? history.back() : go("#/"));
  badge();
  window.scrollTo(0, 0);
}
function gate(body) { stopCam(); app.className = "bare"; app.innerHTML = `<div class="gate">${body}</div>`; }
const brand = () => `<div class="brand"><i>${ico("scan").replace('class="ico"', 'class="ico" style="color:#4FC5B8"')}</i>Склад клиники${S.clinic ? " · " + esc(S.clinic) : ""}</div>`;
const empty = (b, s = "") => `<div class="list"><div class="empty"><b>${esc(b)}</b>${esc(s)}</div></div>`;
function sheet(html, bind) {
  const s = document.createElement("div");
  s.className = "sheet";
  s.innerHTML = `<div>${html}</div>`;
  s.onclick = (e) => { if (e.target === s || e.target.closest("[data-close]")) close(); };
  const close = () => { stopCam(); s.remove(); };
  document.body.append(s);
  bind && bind(s.firstChild, close);
  return close;
}
const go = (h) => { if (location.hash === h) route(); else location.hash = h; };

/* ------------------------------------------------------------------------------------------------ sign-in */
function viewCode(err) {
  gate(`${brand()}<h1>Подключите телефон к клинике</h1>
    <p>Код клиники есть в программе на компьютере: Склад → Телефон. Можно навести камеру на QR-код там же.</p>
    <label class="fld"><span>Код клиники</span><input id="code" class="inp codein" maxlength="9" autocomplete="off" autocapitalize="characters"
      spellcheck="false" placeholder="XXXX-XXXX" value="${esc(S.code)}"></label>
    ${err ? `<div class="note bad">${esc(err)}</div>` : ""}
    <button class="btn" id="join">Подключить</button>`);
  const inp = $("#code");
  inp.oninput = () => { const v = inp.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8); inp.value = v.length > 4 ? v.slice(0, 4) + "-" + v.slice(4) : v; };
  $("#join").onclick = async () => {
    const b = $("#join"); b.disabled = true; b.textContent = "Подключаю…";
    try {
      const r = await call("/p/hello", { code: inp.value, name: phoneName() });
      S.device = { id: r.device, token: r.token }; S.clinic = r.clinic || ""; S.staff = r.staff || []; S.code = "";
      LS.set("device", S.device); LS.set("clinic", S.clinic); LS.set("staff", S.staff);
      go("#/who");
    } catch (e) { S.code = inp.value; viewCode(e.message); }
  };
  if (S.code && S.code.replace(/-/g, "").length === 8 && !err) $("#join").click();
}
function phoneName() {
  const u = navigator.userAgent;
  return /iPhone/.test(u) ? "iPhone" : /Android/.test(u) ? "Android" + ((u.match(/;\s*([^;)]+)\s+Build/) || [])[1] ? " " + u.match(/;\s*([^;)]+)\s+Build/)[1] : "") : "Телефон";
}

async function viewWho() {
  const draw = () => gate(`${brand()}<h1>Кто работает?</h1><p>Выберите себя и введите личный ПИН-код. Его задают в программе: Мой профиль → ПИН для телефона.</p>
    <div class="list">${S.staff.length ? S.staff.map((u, i) => `<button class="row" data-u="${i}"><span class="t"><b>${esc(u.name || u.login)}</b>
      <small>${esc(u.role_title || "")}</small></span>›</button>`).join("") : `<div class="empty"><b>Нет сотрудников с ПИН-кодом</b>
      Задайте ПИН в программе на компьютере: Мой профиль → ПИН для телефона.</div>`}</div>
    <p class="small muted" style="margin-top:18px">Не та клиника? <a href="#" id="other">Подключить другую</a></p>`);
  draw();
  $$("[data-u]").forEach((b) => (b.onclick = () => { S.pick = S.staff[+b.dataset.u]; go("#/pin"); }));
  $("#other").onclick = async (e) => { e.preventDefault(); await call("/p/leave", {}, "device").catch(() => {}); await forget(); route(); };
  try {
    const r = await call("/p/staff", {}, "device");
    if (JSON.stringify(r.staff) !== JSON.stringify(S.staff) || r.clinic !== S.clinic) {
      S.staff = r.staff; S.clinic = r.clinic; LS.set("staff", S.staff); LS.set("clinic", S.clinic);
      if (location.hash === "#/who") viewWho();
    }
  } catch (e) { signedOut(e); }
}

function viewPin() {
  const u = S.pick || (S.user && S.staff.find((x) => x.login === S.user.login));
  if (!u) return go("#/who");
  let pin = "";
  gate(`${brand()}<h1>${esc(u.name || u.login)}</h1><p>${esc(u.role_title || "")} · введите ПИН-код из 6 цифр</p>
    <div class="dots" id="dots">${"<i></i>".repeat(6)}</div><div id="err" class="note bad" hidden></div>
    <div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button data-k="${n}">${n}</button>`).join("")}
      <button class="fn" data-k="who">Другой</button><button data-k="0">0</button><button class="fn" data-k="del">Стереть</button></div>`);
  const dots = () => $$("#dots i").forEach((d, i) => d.classList.toggle("on", i < pin.length));
  const send = async () => {
    try {
      const r = await call("/p/login", { login: u.login, pin }, "device");
      if (LS.get("owner") !== u.login) { S.rows = new Map(); S.since = 0; LS.set("since", 0); await idbClear("rows"); index(); }
      S.session = r.session; S.user = r.user; S.pick = null;
      LS.set("session", S.session); LS.set("user", S.user); LS.set("owner", u.login);
      go(S.after || "#/"); S.after = null; sync();
    } catch (e) {
      if (signedOut(e)) return;
      pin = ""; dots(); const d = $("#dots"); d.classList.remove("shake"); void d.offsetWidth; d.classList.add("shake");
      const er = $("#err"); er.hidden = false; er.textContent = e.net ? "Нет связи. Для входа нужен интернет." : e.message;
    }
  };
  $$(".pad button").forEach((b) => (b.onclick = () => {
    const k = b.dataset.k;
    if (k === "who") { S.pick = null; return go("#/who"); }
    if (k === "del") pin = pin.slice(0, -1); else if (pin.length < 6) pin += k;
    dots();
    if (pin.length === 6) send();
  }));
}

/* ------------------------------------------------------------------------------------------------ home */
function viewHome() {
  const u = S.user || {};
  const rows = [];
  const item = (h, title, sub, n, cls) => rows.push(`<a class="row" href="${h}"><span class="t"><b>${title}</b><small>${sub}</small></span><span class="count ${n ? cls : ""}">${n}</span></a>`);
  if (can("stock")) {
    item("#/aps", can("approve") ? "На согласовании" : "Мои списания на согласовании", can("approve") ? "Ждут вашего решения" : "Спишутся после проверки менеджера", pendingAps().length, "hot");
    item("#/reqs", can("handle_requests") ? "Заявки из кабинетов" : "Мои заявки", "Новые, принятые и выданные частично", openReqs().length, "hot");
    item("#/stock?f=low", "Ниже минимума", "Пора заказывать", low().length, "warn");
    item("#/exp", "Сроки годности", `Истекли или истекут за ${SOON} дней`, expiring().length, "bad");
  }
  if (can("equipment")) item("#/svc", "Техобслуживание", `Просрочено или в ближайшие ${SOON} дней`, serviceDue().length, "warn");
  const quick = [];
  if (can("use")) quick.push(`<a class="btn soft" href="#/do/use">Расход</a>`);
  if (can("receive")) quick.push(`<a class="btn soft" href="#/do/receive">Приход</a>`);
  if (can("request")) quick.push(`<a class="btn soft" href="#/do/request">Заявка</a>`);
  if (can("transfer")) quick.push(`<a class="btn soft" href="#/do/transfer">Выдать в кабинет</a>`);
  page(u.name ? `Здравствуйте, ${u.name.split(" ")[0]}` : "Склад", `
    <button class="finder" id="hero"><i></i><em></em><b>Сканировать</b><small>Штрихкод материала или QR-этикетка оборудования — откроется его карточка</small></button>
    <div class="list">${rows.join("") || '<div class="empty"><b>Нет доступа к складу</b>У вашей должности нет прав склада и оборудования.</div>'}</div>
    ${quick.length ? `<div class="sec">Быстро</div><div class="acts">${quick.join("")}</div>` : ""}
    <p class="small muted">${S.last ? "Обновлено " + new Date(S.last).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "Ещё не обновлялось"}</p>`, { tab: "#/" });
  $("#hero").onclick = () => go("#/scan");
}

/* ------------------------------------------------------------------------------------------------ scanner */
const FORMATS = ["qr_code", "ean_13", "ean_8", "code_128", "code_39", "code_93", "upc_a", "upc_e", "itf", "data_matrix", "codabar"];
async function detector() {
  if (S.det) return S.det;
  let BD = window.BarcodeDetector, formats = FORMATS;
  if (BD) { try { const f = await BD.getSupportedFormats(); formats = FORMATS.filter((x) => f.includes(x)); if (!formats.length) BD = null; } catch { BD = null; } }
  if (!BD) { BD = (await import(window.DD_SCAN_POLYFILL)).BarcodeDetector; formats = FORMATS; }
  return (S.det = new BD({ formats }));
}
function stopCam() { if (S.stopCam) { S.stopCam(); S.stopCam = null; } }
async function camera(box, onCode) {
  stopCam();
  const v = $("video", box), msg = $(".msg", box);
  let stream, done = false, last = 0;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false }); }
  catch { msg.textContent = "Нет доступа к камере. Разрешите камеру для этого сайта или сфотографируйте код."; return; }
  const halt = () => { done = true; stream.getTracks().forEach((t) => t.stop()); };
  S.stopCam = halt;
  v.srcObject = stream; await v.play().catch(() => {});
  let det = null;
  try { det = await detector(); } catch { msg.textContent = "Сканер не загрузился — введите код вручную."; }
  const tick = async (t) => {
    if (done || !v.isConnected) return halt();
    if (det && t - last > 200 && v.readyState >= 2) {
      last = t;
      try { const r = await det.detect(v); if (r.length && !done) { halt(); S.stopCam = null; navigator.vibrate && navigator.vibrate(40); return onCode(r[0].rawValue); } }
      catch { /* a frame that could not be read */ }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
async function fromPhoto(file, onCode) {
  try {
    const det = await detector(), img = await createImageBitmap(file), r = await det.detect(img);
    if (r.length) onCode(r[0].rawValue); else toast("На фото не найден код. Снимите ближе и ровнее.", true);
  } catch { toast("Не удалось прочитать фото", true); }
}
const camHtml = `<div class="cam"><video playsinline muted></video><div class="aim"></div><div class="msg">Наведите на штрихкод или QR-код</div></div>
  <div class="acts"><label class="btn ghost">Сфотографировать<input type="file" accept="image/*" capture="environment" hidden></label>
  <button class="btn ghost" data-manual>Ввести вручную</button></div>`;
function bindCam(el, onCode) {
  camera($(".cam", el), onCode);
  $("input[type=file]", el).onchange = (e) => e.target.files[0] && fromPhoto(e.target.files[0], onCode);
  $("[data-manual]", el).onclick = () => { const c = prompt("Штрихкод, инвентарный номер или код материала"); if (c && c.trim()) onCode(c.trim()); };
}

/* what a code is: a label link /e/<инв. №>, a barcode of a material, an inventory number, a code of a material */
function resolve(code) {
  const s = String(code).trim(), m = s.match(/\/e\/([^/?#\s]+)/);
  const inv = m ? decodeURIComponent(m[1]) : s;
  if (D.inv.has(inv)) return { t: "e", id: D.inv.get(inv) };
  if (D.bar.has(s)) return { t: "m", id: D.bar.get(s) };
  const byCode = activeMats().find((x) => x.code && String(x.code).toLowerCase() === s.toLowerCase());
  if (byCode) return { t: "m", id: byCode.id };
  const bySerial = [...D.eq.values()].find((e) => e.serial && e.serial === s);
  return bySerial ? { t: "e", id: bySerial.id } : null;
}
function viewScan() {
  page("Сканер", camHtml + `<p class="small muted">Код читается сам. Если камера не видит код — сфотографируйте его или введите номер вручную.</p>`, { tab: "#/scan" });
  bindCam(app, found);
}
function found(code) {
  const r = resolve(code);
  if (r) return go(r.t === "e" ? `#/e/${encodeURIComponent(r.id)}` : `#/m/${encodeURIComponent(r.id)}`);
  page("Код не найден", `<div class="tag"><div class="code">${esc(code)}</div><h2>Такого кода нет в справочнике</h2>
      <p>Это не штрихкод материала и не этикетка оборудования клиники.</p></div>
    ${can("barcode") ? `<button class="btn" id="bind">Привязать к материалу</button>` : `<div class="note">Привязать штрихкод к материалу может менеджер склада.</div>`}
    <div class="acts"><a class="btn ghost" href="#/scan">Сканировать ещё</a><a class="btn ghost" href="#/stock">Найти в списке</a></div>`, { back: true });
  const b = $("#bind");
  if (b) b.onclick = () => pickMaterial("", async (mid) => {
    try { await doOp({ kind: "barcode", id: mid, barcode: code }, "Штрихкод"); go(`#/m/${encodeURIComponent(mid)}`); } catch (e) { toast(e.message, true); }
  });
}

/* ------------------------------------------------------------------------------------------------ materials */
function matRow(m, loc) {
  const t = loc === undefined ? total(m.id) : at(m.id, loc), lowq = Number(m.min_qty) > 0 && total(m.id) < Number(m.min_qty);
  return `<a class="row" href="#/m/${encodeURIComponent(m.id)}"><span class="t"><b>${esc(m.name)}</b><small>${esc([m.code, m.category].filter(Boolean).join(" · "))}</small></span>
    <span class="n" style="${lowq ? "color:var(--warn)" : ""}">${qty(t)} <small>${esc(m.unit || "")}</small></span></a>`;
}
function viewStock(qs) {
  const f = qs.get("f") || "", term = (S.term || "").toLowerCase();
  let list = f === "low" ? low() : activeMats();
  if (term) list = list.filter((m) => [m.name, m.code, m.barcode, m.category].some((x) => String(x || "").toLowerCase().includes(term)));
  page("Склад", `<input id="q" class="inp" type="search" placeholder="Название, код или штрихкод" value="${esc(S.term || "")}">
    <div class="seg" style="margin:10px 0"><button data-f="" class="${f ? "" : "on"}">Все</button><button data-f="low" class="${f === "low" ? "on" : ""}">Ниже минимума</button>
      <button data-f="exp">Сроки</button></div>
    ${list.length ? `<div class="list">${list.slice(0, 300).map((m) => matRow(m)).join("")}</div>` : empty(f === "low" ? "Всё выше минимума" : "Ничего не найдено", term ? "Проверьте название или отсканируйте штрихкод." : "")}`, { tab: "#/stock" });
  const q = $("#q");
  q.oninput = () => { S.term = q.value; clearTimeout(S.tq); S.tq = setTimeout(() => { viewStock(qs); const n = $("#q"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 250); };
  $$("[data-f]").forEach((b) => (b.onclick = () => go(b.dataset.f === "exp" ? "#/exp" : b.dataset.f ? "#/stock?f=low" : "#/stock")));
}
const MOVE = { service: "Расход по приёмам", consume: "Расход", receipt: "Приход", writeoff: "Списание", transfer: "Перемещение", inventory: "Инвентаризация", adjust: "Корректировка", visit: "Расход в приёме", opening: "Начальный остаток" };
function viewMaterial(id) {
  const m = D.mats.get(id);
  if (!m) return page("Материал", empty("Материал не найден", "Обновите данные в профиле."), { back: true });
  const t = total(id), ll = lotsOf(id), by = places().map((p) => ({ ...p, q: at(id, p.id) })).filter((p) => p.q);
  const mv = D.moves.filter((x) => x.material_id === id).slice(0, 12);
  const lotState = (g) => !g.expires ? "" : g.state === "expired" ? `<span class="chip bad">истёк ${-g.days} ${plural(-g.days, "день", "дня", "дней")} назад</span>`
    : g.state === "soon" ? `<span class="chip warn">${g.days ? `через ${g.days} ${plural(g.days, "день", "дня", "дней")}` : "сегодня последний день"}</span>` : `<span class="chip ok">годен</span>`;
  const act = (h, l) => `<a class="btn soft" href="${h}">${l}</a>`;
  const ref = `?m=${encodeURIComponent(id)}`;
  page("Материал", `<div class="tag"><div class="code">${esc([m.code, m.barcode].filter(Boolean).join(" · ") || "без кода")}</div><h2>${esc(m.name)}</h2>
      <p>${esc([m.category, m.unit].filter(Boolean).join(" · "))}</p>
      <div class="big"><b style="${Number(m.min_qty) > 0 && t < Number(m.min_qty) ? "color:var(--warn)" : ""}">${qty(t)}</b><span>${esc(m.unit || "")} на складе${Number(m.min_qty) > 0 ? ` · минимум ${qty(m.min_qty)}` : ""}</span></div></div>
    <div class="acts">${can("use") ? act("#/do/use" + ref, "Расход") : ""}${can("use") ? act("#/do/writeoff" + ref, "Списать") : ""}
      ${can("receive") ? act("#/do/receive" + ref, "Приход") : ""}${can("request") ? act("#/do/request" + ref, "В заявку") : ""}
      ${can("transfer") ? act("#/do/transfer" + ref, "Выдать в кабинет") : ""}${can("barcode") ? `<button class="btn ghost" id="bar">${m.barcode ? "Заменить штрихкод" : "Привязать штрихкод"}</button>` : ""}</div>
    ${by.length > 1 || (by[0] && by[0].id) ? `<div class="sec">По местам</div><div class="list">${by.map((p) => `<div class="row"><span class="t"><b>${esc(p.name)}</b></span><span class="n">${qty(p.q)} <small>${esc(m.unit || "")}</small></span></div>`).join("")}</div>` : ""}
    <div class="sec">Партии и сроки</div>
    ${ll.lots.length ? `<div class="list">${ll.lots.filter((g) => g.left > 0).map((g) => `<div class="row"><span class="t"><b>${esc(g.lot || "без номера")}${g.expires ? " · до " + fmtDate(g.expires) : ""}</b>
      <small>${esc([g.received && fmtDate(g.received), g.doc && "№ " + g.doc, g.supplier].filter(Boolean).join(" · "))}</small></span>${lotState(g)}<span class="n">${qty(g.left)}</span></div>`).join("")}
      ${ll.noLot > 0 ? `<div class="row"><span class="t"><b>Без партии</b><small>приходы без срока, начальный остаток</small></span><span class="n">${qty(ll.noLot)}</span></div>` : ""}</div>
      <p class="small muted">Расходуется сначала то, что истекает раньше.</p>` : empty("Партий нет", "Номер партии и срок годности указываются при приходе.")}
    <div class="sec">Движение</div>
    ${mv.length ? `<div class="list">${mv.map((x) => `<div class="row"><span class="t"><b>${MOVE[x.kind] || esc(x.kind)}${x.reason && x.kind !== "receipt" ? " · " + esc(x.reason) : ""}</b>
      <small>${fmtDate((x.at || "").slice(0, 10))} · ${esc(placeName(x.location_id))} · ${esc(x.user_name || "")}</small></span>
      <span class="n" style="color:${x.qty > 0 ? "var(--ok)" : "var(--ink2)"}">${x.qty > 0 ? "+" : ""}${qty(x.qty)}</span></div>`).join("")}</div>` : empty("Движений ещё не было")}
    ${can("money") && m.price ? `<p class="small muted">Цена по последней закупке: ${money(m.price)}</p>` : ""}`, { back: true });
  const b = $("#bar");
  if (b) b.onclick = () => sheet(`<h3>Отсканируйте штрихкод упаковки</h3>${camHtml}<button class="btn ghost" data-close>Отмена</button>`, (el, close) =>
    bindCam(el, async (code) => { close(); try { await doOp({ kind: "barcode", id, barcode: code }, "Штрихкод"); } catch (e) { toast(e.message, true); } }));
}
function viewExp() {
  const list = expiring();
  page("Сроки годности", list.length ? `<div class="list">${list.map((g) => `<a class="row" href="#/m/${encodeURIComponent(g.m.id)}"><span class="t"><b>${esc(g.m.name)}</b>
    <small>партия ${esc(g.lot || "—")} · годен до ${fmtDate(g.expires)}</small></span><span class="chip ${g.state === "expired" ? "bad" : "warn"}">${g.days < 0 ? "истёк" : g.days + " дн."}</span>
    <span class="n">${qty(g.left)}</span></a>`).join("")}</div>
    ${can("use") ? `<p class="small muted">Просроченное списывается с причиной «Истёк срок годности» — откройте материал и нажмите «Списать».</p>` : ""}`
    : empty("Со сроками всё в порядке", `Нет партий, которые истекли или истекут за ${SOON} дней.`), { back: true });
}

/* the picker of a material for a form: search or scan */
function pickMaterial(loc, onPick) {
  sheet(`<h3>Материал</h3><input class="inp" type="search" id="pq" placeholder="Название, код или штрихкод">
    <div class="acts"><button class="btn ghost" id="pscan">Сканировать</button><button class="btn ghost" data-close>Отмена</button></div>
    <div id="pcam"></div><div class="list" id="pl"></div>`, (el, close) => {
    const draw = () => {
      const t = $("#pq", el).value.toLowerCase();
      const l = activeMats().filter((m) => !t || [m.name, m.code, m.barcode].some((x) => String(x || "").toLowerCase().includes(t))).slice(0, 80);
      $("#pl", el).innerHTML = l.map((m) => `<button class="row" data-m="${esc(m.id)}"><span class="t"><b>${esc(m.name)}</b><small>${esc(m.code || "")}</small></span>
        <span class="n">${qty(loc === null ? total(m.id) : at(m.id, loc))} <small>${esc(m.unit || "")}</small></span></button>`).join("") || '<div class="empty">Ничего не найдено</div>';
      $$("[data-m]", el).forEach((b) => (b.onclick = () => { close(); onPick(b.dataset.m); }));
    };
    $("#pq", el).oninput = draw; draw();
    $("#pscan", el).onclick = () => {
      $("#pcam", el).innerHTML = camHtml;
      bindCam($("#pcam", el), (code) => { const r = resolve(code); if (r && r.t === "m") { close(); onPick(r.id); } else toast(`Код ${code} не найден среди материалов`, true); });
    };
  });
}

/* ------------------------------------------------------------------------------------------------ operation forms */
const FORMS = {
  use: { title: "Расход в лечении", btn: "Списать расход", loc: "location_id" },
  writeoff: { title: "Списание", btn: "Списать", loc: "location_id" },
  receive: { title: "Приход поставки", btn: "Принять поставку", loc: "location_id" },
  request: { title: "Заявка на склад", btn: "Отправить заявку", loc: "location_id" },
  transfer: { title: "Выдать в кабинет", btn: "Выдать", loc: "from_id" },
};
const REASONS = ["Брак", "Истёк срок годности", "Повреждено", "Утеряно"];
function viewForm(kind, qs) {
  const cfg = FORMS[kind];
  const need = { use: "use", writeoff: "use", receive: "receive", request: "request", transfer: "transfer" }[kind];
  if (!cfg || !can(need)) return page("Нет доступа", empty("У вашей должности нет на это права"), { back: true });
  let F = S.form;
  if (!F || F.kind !== kind || qs.get("new")) {
    F = S.form = { kind, lines: [], location_id: "", from_id: "", to_id: "", reason: "", comment: "", priority: "normal", need_date: "", number: "", supplier_id: "", request_ids: [] };
    if (qs.get("m")) F.lines.push({ material_id: qs.get("m"), qty: kind === "receive" ? "" : 1 });
    if (qs.get("rq")) {
      const r = D.reqs.find((x) => x.id === qs.get("rq"));
      if (r) {
        let rl = [], iss = {};
        try { rl = JSON.parse(r.lines || "[]"); iss = JSON.parse(r.issued || "{}") || {}; } catch { /* broken JSON */ }
        F.to_id = r.location_id || ""; F.request_ids = [r.id]; F.comment = `По заявке № ${r.number || ""}`;
        F.lines = rl.map((l) => ({ material_id: l.material_id, qty: q3(Math.max(0, Number(l.qty) - Number(iss[l.material_id] || 0))) })).filter((l) => l.qty > 0);
      }
    }
    if (kind === "transfer" && !F.to_id) { const c = places().find((p) => p.id); F.to_id = c ? c.id : ""; }
  }
  const P = places(), src = kind === "transfer" ? F.from_id : F.location_id;
  const sel = (name, val, list) => `<select class="inp" data-f="${name}">${list.map((p) => `<option value="${esc(p.id)}" ${p.id === val ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>`;
  const lineHtml = (l, i) => {
    const m = D.mats.get(l.material_id) || { name: "?", unit: "" }, have = at(l.material_id, src);
    const over = kind !== "receive" && kind !== "request" && Number(l.qty) > have;
    return `<div class="line"><span><b>${esc(m.name)}</b><small style="${over ? "color:var(--bad)" : ""}">${kind === "receive" ? "сейчас " + qty(total(l.material_id), m.unit) : "в наличии " + qty(have, m.unit)}</small></span>
      <input class="inp" inputmode="decimal" data-l="${i}" data-k="qty" value="${esc(l.qty)}" placeholder="кол-во" aria-label="Количество">
      <button class="x" data-del="${i}" aria-label="Убрать">×</button>
      ${kind === "receive" ? `<div class="more"><input class="inp" inputmode="decimal" data-l="${i}" data-k="price" value="${esc(l.price ?? "")}" placeholder="цена, ₽">
        <input class="inp" data-l="${i}" data-k="lot" value="${esc(l.lot || "")}" placeholder="партия"><input class="inp" data-l="${i}" data-k="expires" value="${esc(l.expires || "")}" placeholder="годен до"></div>` : ""}</div>`;
  };
  page(cfg.title, `
    ${kind === "transfer" ? `<label class="fld"><span>Откуда</span>${sel("from_id", F.from_id, P)}</label><label class="fld"><span>Куда</span>${sel("to_id", F.to_id, P)}</label>`
      : `<label class="fld"><span>${kind === "request" ? "Для кабинета" : kind === "receive" ? "Куда принять" : "Откуда"}</span>${sel("location_id", F.location_id, P)}</label>`}
    ${kind === "receive" ? `<label class="fld"><span>Поставщик</span><select class="inp" data-f="supplier_id"><option value="">— не указан —</option>${[...D.sups.values()].filter((s) => Number(s.active ?? 1))
      .map((s) => `<option value="${esc(s.id)}" ${s.id === F.supplier_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
      <label class="fld"><span>Номер накладной</span><input class="inp" data-f="number" value="${esc(F.number)}"></label>` : ""}
    ${kind === "writeoff" ? `<div class="fld"><span>Причина</span><div class="seg">${REASONS.map((r) => `<button data-reason="${esc(r)}" class="${F.reason === r ? "on" : ""}">${r}</button>`).join("")}</div>
      <input class="inp" style="margin-top:8px" data-f="reason" value="${esc(F.reason)}" placeholder="или напишите свою"></div>` : ""}
    ${kind === "request" ? `<div class="fld"><span>Срочность</span><div class="seg">${[["normal", "Обычная"], ["urgent", "Срочно"], ["critical", "Критично"]]
      .map(([v, l]) => `<button data-pr="${v}" class="${F.priority === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
      <label class="fld"><span>Нужно к дате</span><input class="inp" type="date" data-f="need_date" value="${esc(F.need_date)}"></label>` : ""}
    <div class="sec">Материалы</div>
    <div class="list">${F.lines.map(lineHtml).join("") || '<div class="empty">Добавьте материал — из списка или сканером</div>'}</div>
    <button class="btn ghost" id="add" style="margin-top:10px">+ Добавить материал</button>
    <label class="fld"><span>Комментарий</span><textarea class="inp" data-f="comment">${esc(F.comment)}</textarea></label>
    ${kind === "use" && !can("direct") ? `<div class="note">Расход уйдёт менеджеру склада на согласование и спишется после проверки.</div>` : ""}
    ${kind === "writeoff" && !can("direct") ? `<div class="note">Списание уйдёт менеджеру склада на согласование.</div>` : ""}
    <div id="ferr" class="note bad" hidden></div>
    <button class="btn" id="send" style="margin-top:6px">${cfg.btn}</button>`, { back: true });
  $$("[data-f]").forEach((el) => (el.onchange = el.oninput = () => { F[el.dataset.f] = el.value; if (el.tagName === "SELECT") viewForm(kind, new URLSearchParams()); }));
  $$("[data-l]").forEach((el) => (el.oninput = () => { F.lines[+el.dataset.l][el.dataset.k] = el.value; }));
  $$("[data-del]").forEach((b) => (b.onclick = () => { F.lines.splice(+b.dataset.del, 1); viewForm(kind, new URLSearchParams()); }));
  $$("[data-reason]").forEach((b) => (b.onclick = () => { F.reason = b.dataset.reason; viewForm(kind, new URLSearchParams()); }));
  $$("[data-pr]").forEach((b) => (b.onclick = () => { F.priority = b.dataset.pr; viewForm(kind, new URLSearchParams()); }));
  $("#add").onclick = () => pickMaterial(kind === "receive" || kind === "request" ? null : src, (mid) => {
    const ex = F.lines.find((l) => l.material_id === mid);
    if (ex) ex.qty = q3(Number(String(ex.qty).replace(",", ".")) + 1); else F.lines.push({ material_id: mid, qty: kind === "receive" ? "" : 1 });
    viewForm(kind, new URLSearchParams());
  });
  $("#send").onclick = async () => {
    const err = $("#ferr"), b = $("#send");
    const lines = F.lines.map((l) => ({ ...l, qty: String(l.qty).replace(",", ".") })).filter((l) => Number(l.qty) > 0);
    const fail = (m) => { err.hidden = false; err.textContent = m; };
    if (!lines.length) return fail("Укажите количество хотя бы у одного материала");
    if (kind === "writeoff" && !F.reason.trim()) return fail("Укажите причину списания");
    const body = { kind: kind === "writeoff" ? "use" : kind, lines, comment: F.comment };
    if (kind === "writeoff") Object.assign(body, { what: "writeoff", reason: F.reason });
    if (kind === "transfer") Object.assign(body, { from_id: F.from_id, to_id: F.to_id, request_ids: F.request_ids });
    else body.location_id = F.location_id;
    if (kind === "receive") Object.assign(body, { supplier_id: F.supplier_id, number: F.number });
    if (kind === "request") Object.assign(body, { priority: F.priority, need_date: F.need_date });
    b.disabled = true; b.textContent = "Отправляю…";
    try {
      const r = await doOp(body, cfg.title);
      if (r) { S.form = null; go(kind === "request" ? "#/reqs" : kind === "use" && r.status === "pending" ? "#/aps" : "#/"); }
    } catch (e) { b.disabled = false; b.textContent = cfg.btn; fail(e.message); }
  };
}

/* ------------------------------------------------------------------------------------------------ approvals, requests */
const AP_ST = { pending: ["На согласовании", "acc"], approved: ["Согласовано", "ok"], done: ["Списано", "ok"], rejected: ["Отклонено", "bad"], cancelled: ["Отменено", ""], draft: ["Черновик", ""] };
const RQ_ST = { new: ["Новая", "acc"], accepted: ["Принята", "acc"], partial: ["Выдана частично", "warn"], done: ["Выдана", "ok"], rejected: ["Отклонена", "bad"], cancelled: ["Отменена", ""], draft: ["Черновик", ""] };
const chip = (map, s) => `<span class="chip ${(map[s] || ["", ""])[1]}">${(map[s] || [s])[0]}</span>`;
const when = (s) => (s ? `${fmtDate(s.slice(0, 10))} ${s.slice(11, 16)}` : "");
function viewAps() {
  const pend = pendingAps(), rest = D.aps.filter((a) => a.status !== "pending" && (can("approve") || mine(a))).slice(0, 15);
  const card = (a) => `<div class="ev"><b>${esc(a.summary || "—")}</b> ${chip(AP_ST, a.status)}
    <small>${a.kind === "writeoff" ? "Списание" : "Расход"} · ${esc(placeName(a.location_id))} · ${esc(a.created_name || a.created_by)} · ${when(a.created_at)}${can("money") && a.total ? " · " + money(a.total) : ""}</small>
    ${a.answer ? `<small>Ответ: ${esc(a.answer)}</small>` : ""}
    ${a.status === "pending" ? `<div class="acts">${can("approve") ? `<button class="btn" data-ok="${esc(a.id)}">Согласовать</button><button class="btn bad" data-no="${esc(a.id)}">Отклонить</button>`
      : `<button class="btn ghost" data-cancel="${esc(a.id)}">Отменить</button>`}</div>` : ""}</div>`;
  page(can("approve") ? "На согласовании" : "Мои списания", `${pend.length ? `<div class="list">${pend.map(card).join("")}</div>` : empty("Ничего не ждёт согласования")}
    ${rest.length ? `<div class="sec">Недавние</div><div class="list">${rest.map(card).join("")}</div>` : ""}`, { back: true });
  const act = (sel, fn) => $$(sel).forEach((b) => (b.onclick = async () => { b.disabled = true; try { await fn(b); } catch (e) { toast(e.message, true); b.disabled = false; } }));
  act("[data-ok]", (b) => doOp({ kind: "decide", id: b.dataset.ok, action: "approve" }, "Согласование"));
  act("[data-no]", async (b) => { const answer = prompt("Причина отказа — сотрудник увидит её"); if (!answer) { b.disabled = false; return; } await doOp({ kind: "decide", id: b.dataset.no, action: "reject", answer }, "Отказ"); });
  act("[data-cancel]", (b) => doOp({ kind: "approval_cancel", id: b.dataset.cancel }, "Отмена списания"));
}
function viewReqs() {
  const open = openReqs(), rest = D.reqs.filter((r) => !open.includes(r) && (can("handle_requests") || mine(r))).slice(0, 15);
  const card = (r) => {
    let rl = [], iss = {};
    try { rl = JSON.parse(r.lines || "[]"); iss = JSON.parse(r.issued || "{}") || {}; } catch { /* broken JSON */ }
    const lines = rl.map((l) => { const m = D.mats.get(l.material_id) || { name: "?" }; return `${esc(m.name)} — ${qty(l.qty)}${iss[l.material_id] ? ` (выдано ${qty(iss[l.material_id])})` : ""}`; }).join("<br>");
    const h = can("handle_requests"), op = ["new", "accepted", "partial"].includes(r.status);
    return `<div class="ev"><b>Заявка № ${esc(r.number || "—")} · ${esc(placeName(r.location_id))}</b> ${chip(RQ_ST, r.status)}${r.priority !== "normal" ? ` <span class="chip bad">${r.priority === "critical" ? "критично" : "срочно"}</span>` : ""}
      <small>${esc(r.created_name || r.created_by)} · ${when(r.created_at)}${r.need_date ? " · нужно к " + fmtDate(r.need_date) : ""}</small>
      <div class="small" style="margin-top:6px">${lines}</div>${r.comment ? `<small>${esc(r.comment)}</small>` : ""}${r.answer ? `<small>Ответ: ${esc(r.answer)}</small>` : ""}
      ${op && (h || (mine(r) && r.status === "new")) ? `<div class="acts">${h && can("transfer") ? `<a class="btn" href="#/do/transfer?new=1&rq=${encodeURIComponent(r.id)}">Выдать</a>` : ""}
        ${h && r.status === "new" ? `<button class="btn soft" data-acc="${esc(r.id)}">Принять</button>` : ""}${h ? `<button class="btn bad" data-rej="${esc(r.id)}">Отклонить</button>` : ""}
        ${mine(r) && r.status === "new" ? `<button class="btn ghost" data-can="${esc(r.id)}">Отменить</button>` : ""}</div>` : ""}</div>`;
  };
  page(can("handle_requests") ? "Заявки из кабинетов" : "Мои заявки", `${can("request") ? `<a class="btn soft" href="#/do/request?new=1" style="margin-bottom:12px">Новая заявка</a>` : ""}
    ${open.length ? `<div class="list">${open.map(card).join("")}</div>` : empty("Открытых заявок нет")}
    ${rest.length ? `<div class="sec">Недавние</div><div class="list">${rest.map(card).join("")}</div>` : ""}`, { back: true });
  const act = (sel, fn) => $$(sel).forEach((b) => (b.onclick = async () => { b.disabled = true; try { await fn(b); } catch (e) { toast(e.message, true); b.disabled = false; } }));
  act("[data-acc]", (b) => doOp({ kind: "request_accept", id: b.dataset.acc }, "Заявка"));
  act("[data-can]", (b) => doOp({ kind: "request_cancel", id: b.dataset.can }, "Отмена заявки"));
  act("[data-rej]", async (b) => { const answer = prompt("Причина — медсестра увидит её в своих заявках"); if (!answer) { b.disabled = false; return; } await doOp({ kind: "request_reject", id: b.dataset.rej, answer }, "Заявка"); });
}

/* ------------------------------------------------------------------------------------------------ equipment */
const EQ_ST = { in_use: ["В работе", "ok"], repair: ["В ремонте", "bad"], storage: ["На складе", ""], written_off: ["Списано", ""] };
const EQ_CO = { ok: ["Исправно", "ok"], service: ["Требует обслуживания", "warn"], faulty: ["Неисправно", "bad"] };
const EV = { service: "Техобслуживание", repair: "Ремонт", note: "Заметка", move: "Перемещение", condition: "Состояние", status: "Статус", inventory: "Инвентаризация", writeoff: "Выбытие" };
function viewEqList() {
  const term = (S.eterm || "").toLowerCase();
  const list = [...D.eq.values()].filter((e) => e.status !== "written_off" && (!term || [e.name, e.model, e.inv_number, e.serial, e.location].some((x) => String(x || "").toLowerCase().includes(term))))
    .sort((a, b) => String(a.inv_number || "").localeCompare(String(b.inv_number || ""), "ru", { numeric: true }));
  page("Оборудование", `<input id="q" class="inp" type="search" placeholder="Название, инв. № или кабинет" value="${esc(S.eterm || "")}" style="margin-bottom:10px">
    ${list.length ? `<div class="list">${list.map((e) => `<a class="row" href="#/e/${encodeURIComponent(e.id)}"><span class="t"><b>${esc(e.name)}</b><small><span class="mono">${esc(e.inv_number || "")}</span> · ${esc(e.location || "место не указано")}</small></span>${chip(EQ_ST, e.status)}</a>`).join("")}</div>` : empty("Ничего не найдено")}`, { tab: "#/eq" });
  const q = $("#q");
  q.oninput = () => { S.eterm = q.value; clearTimeout(S.tq); S.tq = setTimeout(() => { viewEqList(); const n = $("#q"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 250); };
}
function viewSvc() {
  const l = serviceDue();
  page("Техобслуживание", l.length ? `<div class="list">${l.map((e) => { const d = days(e.next_service); return `<a class="row" href="#/e/${encodeURIComponent(e.id)}"><span class="t"><b>${esc(e.name)}</b>
    <small><span class="mono">${esc(e.inv_number || "")}</span> · ${esc(e.location || "")}</small></span><span class="chip ${d < 0 ? "bad" : "warn"}">${d < 0 ? "просрочено" : fmtDate(e.next_service)}</span></a>`; }).join("")}</div>`
    : empty("Всё обслужено", `ТО в ближайшие ${SOON} дней не нужно.`), { back: true });
}
function viewEq(id) {
  const e = D.eq.get(id);
  if (!e) return page("Оборудование", empty("Оборудование не найдено", "Обновите данные в профиле или проверьте этикетку."), { back: true });
  const ev = (D.ev.get(id) || []).slice(0, 20), live = e.status !== "written_off", ed = can("equipment_edit") && live;
  const ns = e.next_service ? days(e.next_service) : null;
  page("Оборудование", `<div class="tag"><div class="code">ИНВ. № ${esc(e.inv_number || "—")}${e.serial ? " · S/N " + esc(e.serial) : ""}</div><h2>${esc(e.name)}</h2>
      <p>${esc([e.model, e.category].filter(Boolean).join(" · "))}</p>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">${chip(EQ_ST, e.status)}${chip(EQ_CO, e.condition || "ok")}</div></div>
    <dl class="kv"><dt>Где</dt><dd>${esc(e.location || "—")}</dd><dt>Ответственный</dt><dd>${esc(e.responsible || "—")}</dd>
      <dt>Следующее ТО</dt><dd style="${ns !== null && ns <= SOON ? `color:var(--${ns < 0 ? "bad" : "warn"})` : ""}">${e.next_service ? fmtDate(e.next_service) : "—"}</dd>
      ${can("money") && e.price ? `<dt>Стоимость</dt><dd>${money(e.price)}</dd>` : ""}</dl>
    ${ed ? `<div class="acts"><button class="btn" id="inv">На месте</button><button class="btn soft" id="state">Состояние и место</button>
      <button class="btn soft" id="svc">Записать ТО или ремонт</button><button class="btn ghost" id="lost">Не найдено</button></div>` : ""}
    <div class="sec">История</div>
    ${ev.length ? `<div class="list">${ev.map((x) => `<div class="ev"><b>${EV[x.kind] || esc(x.kind)}</b> <small>${fmtDate(x.date)} · ${esc(x.user_name || "")}${can("money") && x.cost ? " · " + money(x.cost) : ""}</small>${esc(x.text || "")}</div>`).join("")}</div>` : empty("Событий ещё не было")}`, { back: true });
  if (!ed) return;
  const run = async (body, title) => { try { await doOp({ id, ...body }, title); } catch (er) { toast(er.message, true); } };
  $("#inv").onclick = () => run({ kind: "equipment_inventory", found: true }, "Инвентаризация");
  $("#lost").onclick = () => { if (confirm("Отметить, что оборудования нет на месте?")) run({ kind: "equipment_inventory", found: false }, "Инвентаризация"); };
  const segs = (name, map, val) => `<div class="seg" data-seg="${name}">${Object.entries(map).filter(([k]) => k !== "written_off").map(([k, [l]]) => `<button data-v="${k}" class="${k === val ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const bindSeg = (el) => $$("[data-seg]", el).forEach((g) => $$("button", g).forEach((b) => (b.onclick = () => { $$("button", g).forEach((x) => x.classList.remove("on")); b.classList.add("on"); })));
  const segVal = (el, n) => ($(`[data-seg="${n}"] .on`, el) || {}).dataset?.v;
  $("#state").onclick = () => sheet(`<h3>Состояние и место</h3><div class="fld"><span>Состояние</span>${segs("condition", EQ_CO, e.condition || "ok")}</div>
    <div class="fld"><span>Статус</span>${segs("status", EQ_ST, e.status)}</div>
    <label class="fld"><span>Где стоит</span><select class="inp" id="sl"><option value="">— как сейчас: ${esc(e.location || "не указано")} —</option>
      ${[...D.locs.values()].filter((p) => Number(p.active ?? 1)).map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select></label>
    <label class="fld"><span>Комментарий</span><input class="inp" id="st"></label><button class="btn" id="ss">Сохранить</button>`, (el, close) => {
    bindSeg(el);
    $("#ss", el).onclick = () => { const b = { kind: "equipment_set", condition: segVal(el, "condition"), status: segVal(el, "status"), text: $("#st", el).value };
      if ($("#sl", el).value) b.location_id = $("#sl", el).value; close(); run(b, "Оборудование"); };
  });
  $("#svc").onclick = () => sheet(`<h3>Записать в историю</h3><div class="fld"><span>Что сделано</span>${segs("event", { service: ["Техобслуживание"], repair: ["Ремонт"], note: ["Заметка"] }, "service")}</div>
    <label class="fld"><span>Описание</span><textarea class="inp" id="et" placeholder="Например: замена фильтров, калибровка"></textarea></label>
    ${can("money") ? `<label class="fld"><span>Стоимость, ₽</span><input class="inp" id="ec" inputmode="decimal"></label>` : ""}
    <label class="fld"><span>Следующее ТО</span><input class="inp" type="date" id="en" value="${esc(e.next_service || "")}"></label>
    ${e.status === "repair" ? `<label class="fld" style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="eb" checked style="width:22px;height:22px"><span style="margin:0">Вернуть в работу — исправно</span></label>` : ""}
    <button class="btn" id="es">Записать</button>`, (el, close) => {
    bindSeg(el);
    $("#es", el).onclick = () => {
      const text = $("#et", el).value.trim();
      if (!text) return toast("Опишите, что сделано", true);
      const b = { kind: "equipment_event", event: segVal(el, "event"), text, cost: ($("#ec", el) || {}).value || 0, back_in_use: !!($("#eb", el) || {}).checked };
      if ($("#en", el).value !== (e.next_service || "")) b.next_service = $("#en", el).value;
      close(); run(b, "Событие оборудования");
    };
  });
}

/* ------------------------------------------------------------------------------------------------ profile */
function viewMe() {
  const u = S.user || {};
  page("Профиль", `<div class="tag"><div class="code">${esc(S.clinic)}</div><h2>${esc(u.name || u.login || "")}</h2><p>${esc(u.role_title || "")}</p></div>
    <dl class="kv"><dt>Обновлено</dt><dd>${S.last ? new Date(S.last).toLocaleString("ru-RU") : "—"}</dd><dt>В очереди</dt><dd>${S.queue.length}</dd>
      <dt>Материалов</dt><dd>${D.mats.size}</dd><dt>Оборудования</dt><dd>${D.eq.size}</dd></dl>
    ${S.queue.length ? `<div class="sec">Очередь операций</div><div class="list">${S.queue.map((q) => `<div class="ev"><b>${esc(q.title)}</b>
      <small>${new Date(q.at).toLocaleString("ru-RU")}${q.error ? " · не прошло: " + esc(q.error) : " · ждёт связи"}</small>
      <button class="btn ghost" data-drop="${esc(q.op)}" style="margin-top:8px;min-height:40px">Убрать из очереди</button></div>`).join("")}</div>` : ""}
    <div class="acts" style="margin-top:16px"><button class="btn soft" id="upd">Обновить данные</button><button class="btn ghost" id="out">Выйти</button></div>
    <button class="btn bad" id="leave">Отключить телефон от клиники</button>
    <p class="small muted">Выйти — вернуться к выбору сотрудника и ПИН-коду. Отключить — стереть данные склада с этого телефона.</p>`, { tab: "#/me" });
  $("#upd").onclick = () => sync(true);
  $("#out").onclick = async () => { await call("/p/logout", {}, "session").catch(() => {}); S.session = null; LS.del("session"); go("#/who"); };
  $("#leave").onclick = async () => {
    if (!confirm("Отключить телефон? Данные склада на нём будут стёрты, для входа снова понадобится код клиники.")) return;
    await call("/p/leave", {}, "device").catch(() => {}); await forget(); go("#/");
  };
  $$("[data-drop]").forEach((b) => (b.onclick = async () => { await dropQ(b.dataset.drop); viewMe(); }));
}

/* ------------------------------------------------------------------------------------------------ router */
function route() {
  const h = location.hash.slice(1) || "/", [path, qstr] = h.split("?"), qs = new URLSearchParams(qstr || ""), p = path.split("/").filter(Boolean);
  if (!S.device) return viewCode();
  if (p[0] === "who") return viewWho();
  if (!S.session) {
    if (p[0] && p[0] !== "pin") S.after = location.hash;  // a label scanned before signing in opens after the PIN
    return S.pick || S.user ? viewPin() : viewWho();
  }
  if (p[0] === "pin") return viewPin();
  const id = decodeURIComponent(p[1] || "");
  switch (p[0]) {
    case undefined: return viewHome();
    case "scan": return viewScan();
    case "stock": return viewStock(qs);
    case "m": return viewMaterial(id);
    case "e": return viewEq(id);
    case "inv": { const e = D.inv.get(id); return e ? location.replace(`#/e/${encodeURIComponent(e)}`) : found(id); }
    case "eq": return viewEqList();
    case "svc": return viewSvc();
    case "exp": return viewExp();
    case "aps": return viewAps();
    case "reqs": return viewReqs();
    case "do": return viewForm(p[1], qs);
    case "me": return viewMe();
  }
  return viewHome();
}
let rt;
function render() {  // after new data: redraw the screen, except a form being filled or a camera
  if (S.stopCam || /^#\/(do|pin|who)/.test(location.hash) || $(".sheet") || document.activeElement?.matches("input,textarea,select")) return badge();
  clearTimeout(rt); rt = setTimeout(route, 30);
}

async function boot() {
  // /e/<инв. №> from the QR label and /j#<код клиники> from the QR in the program
  const path = location.pathname;
  if (path.startsWith("/e/")) history.replaceState(null, "", "/#/inv/" + path.slice(3).split("/")[0]);
  else if (path === "/j" || path === "/j/") {
    const code = decodeURIComponent(location.hash.slice(1)).toUpperCase().replace(/[^A-Z0-9]/g, "");
    history.replaceState(null, "", "/#/");
    if (code.length === 8 && !S.device) S.code = code.slice(0, 4) + "-" + code.slice(4);
  }
  try {
    for (const r of await idbAll("rows")) S.rows.set(r.id, r);
    S.queue = await idbAll("queue");
  } catch { /* no IndexedDB (private mode): works online */ }
  index();
  window.addEventListener("hashchange", route);
  window.addEventListener("online", () => { badge(); sync(); });
  window.addEventListener("offline", badge);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") sync(); else stopCam(); });
  setInterval(() => navigator.onLine && document.visibilityState === "visible" && sync(), 60000);
  route();
  if (S.session) sync();
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
}
boot();
