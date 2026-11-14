"use strict";
/* ---------------------------------------------------------------- bridge */
/* Every computer talks to the clinic server over HTTP; the session token goes in X-Session. */
const SESSION_KEY = "dd.session";
let TOKEN = sessionStorage.getItem(SESSION_KEY) || "";
let ME = null;
let serverLost = false;
async function post(kind, name, args) {
  let r;
  try {
    r = await fetch(`/${kind}/${name}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Session": TOKEN}, body: JSON.stringify(args)});
  } catch (e) { lostServer(); throw new Error("Нет связи с сервером клиники"); }
  if (serverLost) foundServer();
  let j = null; try { j = await r.json(); } catch (e) {}
  if (r.status === 401 && kind === "api") { needLogin(j && j.error); }
  if (!r.ok) throw new Error((j && j.error) || "Ошибка " + r.status);
  return j;
}
const api = new Proxy({}, {get: (_, name) => (...args) => post("api", name, args)});
const authApi = new Proxy({}, {get: (_, name) => (...args) => post("auth", name, args)});
const can = p => !!(ME && ME.perms.includes(p));
const canAny = (...ps) => ps.some(can);
const NET_PUBLIC_HINT = "Windows считает эту сеть Wi-Fi «общедоступной» и не пускает к компьютеру планшеты и другие компьютеры. Сделайте её частной: Параметры Windows → Сеть и Интернет → Wi-Fi → свойства вашей сети → «Частная сеть». Если не поможет — Настройки программы → «Разрешить подключения в брандмауэре Windows».";
const errText = e => String((e && (e.message || e)) || "Ошибка").replace(/^Error:\s*/, "");
window.addEventListener("unhandledrejection", e => { const t = errText(e.reason); if (!/Нет связи|Войдите/.test(t)) toast(t, true); });

/* ------------------------------------------------------- modal & toast */
let modalLeaveT;
function modal(html, {wide = false, onClose} = {}) {
  const box = $("#modalBox");
  clearTimeout(modalLeaveT); $("#modal").classList.remove("leaving");
  box.className = "modal" + (wide ? " wide" : "");
  box.innerHTML = html;
  $("#modal").hidden = false;
  box._onClose = onClose;
  box._dirty = false; box._gen = (box._gen || 0) + 1;
  const f = box.querySelector("[autofocus]"); if (f) setTimeout(() => f.focus(), 30);
  box.querySelectorAll("[data-close]").forEach(b => b.onclick = closeModal);
  return box;
}
/* the dialog fades out for 140 ms; its content stays readable until then, a new dialog cancels the exit */
function closeModal() {
  const box = $("#modalBox"), wrap = $("#modal");
  if (wrap.hidden) return;
  const cb = box._onClose; box._onClose = null;
  wrap.classList.add("leaving");
  clearTimeout(modalLeaveT);
  modalLeaveT = setTimeout(() => { if (!wrap.classList.contains("leaving")) return; wrap.hidden = true; wrap.classList.remove("leaving"); box.innerHTML = ""; }, 140);
  if (cb) cb();
}
/* a click beside the dialog closes it only while nothing was typed or changed in it (a mis-click lost a dictated record) */
const markModalDirty = e => { if (e.target.type !== "search") document.getElementById("modalBox")._dirty = true; };
document.getElementById("modalBox").addEventListener("input", markModalDirty);
document.getElementById("modalBox").addEventListener("change", markModalDirty);
/* 3.9: Esc asks the same way as a click beside the dialog */
async function requestCloseModal() {
  const box = document.getElementById("modalBox"), gen = box._gen;
  if (box._dirty && !(await ask("Закрыть без сохранения?", {icon: "warn", ok: "Закрыть", cancel: "Вернуться", text: "Введённые данные не сохранятся."}))) return;
  if (box._gen === gen) closeModal();  // not if another dialog opened meanwhile
}
document.getElementById("modal").addEventListener("mousedown", async e => {
  if (e.target.id !== "modal") return;
  const box = document.getElementById("modalBox"), gen = box._gen;
  if (box._dirty && !(await ask("Закрыть без сохранения?", {icon: "warn", ok: "Закрыть", cancel: "Вернуться", text: "Введённые данные не сохранятся."}))) return;
  if (box._gen === gen) closeModal();  // not if another dialog opened meanwhile
});
/* ------------------------------------------- confirm / input dialogs (instead of the browser's own) */
const ASK_ICONS = {
  question: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.8M12 17.2v.01"/></svg>',
  danger: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10 11v5M14 11v5"/></svg>',
  print: '<svg viewBox="0 0 24 24"><path d="M7 9V3.5h10V9M7 17H4.5V10.5a1.5 1.5 0 0 1 1.5-1.5h12a1.5 1.5 0 0 1 1.5 1.5V17H17"/><rect x="7" y="14" width="10" height="6.5" rx="1"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
};
function askLayer({title, text = "", icon = "question", ok = "Да", cancel = "Отмена", danger = false, fields = null}) {
  return new Promise(resolve => {
    const prevFocus = document.activeElement;
    const el = document.createElement("div");
    el.className = "ask-wrap";
    el.innerHTML = `<div class="ask ${danger ? "danger" : ""}" role="alertdialog" aria-modal="true" aria-labelledby="askT">
      <div class="ask-ic ${danger ? "danger" : icon}">${ASK_ICONS[danger ? "danger" : icon] || ASK_ICONS.question}</div>
      <div class="ask-c"><h3 id="askT">${esc(title)}</h3>${text ? `<p>${esc(text).replace(/\n/g, "<br>")}</p>` : ""}
        ${fields ? `<div class="ask-f">${fields.map((f, i) => `<label>${esc(f.label)}<input class="input" data-i="${i}" type="${f.type || "text"}" value="${esc(f.value ?? "")}" ${f.type === "number" ? 'step="any" min="0"' : ""}></label>`).join("")}</div>` : ""}
        <div class="ask-err"></div></div>
      <div class="ask-b"><button class="btn ghost" data-a="no">${esc(cancel)}</button><button class="btn ${danger ? "danger-btn" : ""}" data-a="yes">${esc(ok)}</button></div></div>`;
    document.body.appendChild(el);
    const done = val => {
      document.removeEventListener("keydown", onKey, true);
      el.classList.add("leaving");
      setTimeout(() => el.remove(), 140);
      if (prevFocus && prevFocus.focus) prevFocus.focus();
      resolve(val);
    };
    const yes = () => {
      if (!fields) return done(true);
      const vals = $$("input", el).map(i => i.value.trim());
      const miss = fields.findIndex((f, i) => f.required !== false && !vals[i]);
      if (miss >= 0) { $(".ask-err", el).textContent = `Заполните поле «${fields[miss].label}»`; $$("input", el)[miss].focus(); return; }
      done(vals);
    };
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(fields ? null : false); }
      else if (e.key === "Enter" && !(e.target.tagName === "BUTTON" && e.target.dataset.a === "no")) { e.preventDefault(); e.stopPropagation(); yes(); }
      else if (e.key === "Tab") {  // keep focus inside the dialog
        const f = $$("input, button", el); const i = f.indexOf(document.activeElement);
        if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);
    $$("input", el).forEach(i => i.oninput = () => { $(".ask-err", el).textContent = ""; });
    $('[data-a="yes"]', el).onclick = yes;
    $('[data-a="no"]', el).onclick = () => done(fields ? null : false);
    el.addEventListener("mousedown", e => { if (e.target === el) done(fields ? null : false); });
    setTimeout(() => { const first = $("input", el); (first || $(danger ? '[data-a="no"]' : '[data-a="yes"]', el)).focus(); if (first) first.select(); }, 30);
  });
}
/** await ask("Удалить?", {text, ok, danger}) → true / false */
const ask = (title, opts = {}) => askLayer({title, ...opts});
/** await askInput("Новая услуга", [{label, value, type}], {ok}) → [values] or null */
const askInput = (title, fields, opts = {}) => askLayer({title, icon: "edit", ok: "Сохранить", ...opts, fields});

let toastT;
function toast(t, bad) {
  const el = $("#toast"); el.textContent = t; el.className = "toast" + (bad ? " bad" : ""); el.hidden = false; clearTimeout(toastT);
  toastT = setTimeout(() => { el.classList.add("out"); toastT = setTimeout(() => { el.hidden = true; el.classList.remove("out"); }, 160); }, bad ? 4800 : 3200);
}
/** В6: the button stays off until the action ends — a double click or a second Enter does nothing. */
async function busy(btn, fn) {
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try { return await fn(); } finally { btn.disabled = false; }
}
/** Request id of a window: the server does a money action sent twice with it only once. */
const reqId = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
const money = n => (Math.round((+n || 0) * 100) / 100).toLocaleString("ru-RU", {minimumFractionDigits: 0, maximumFractionDigits: 2}) + " ₽";
const nowLocal = () => { const d = new Date(); return `${iso(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
let REF = null;
async function ref(force) { if (!REF || force) REF = await api.reference(); return REF; }
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const pad = n => String(n).padStart(2, "0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDay = s => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = parseDay(s); d.setDate(d.getDate() + n); return iso(d); };
const hm = s => s ? s.slice(11, 16) : "";
const mins = s => s ? (+s.slice(11, 13)) * 60 + (+s.slice(14, 16)) : 0;
const MONTHS = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
const WD = ["воскресенье","понедельник","вторник","среда","четверг","пятница","суббота"];
const WDS = ["вс","пн","вт","ср","чт","пт","сб"];
const fmtDate = s => { if (!s) return ""; const d = parseDay(s.slice(0, 10)); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const fmtDT = s => s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)} ${hm(s)}`.trim() : "—";
const ago = s => {
  if (!s) return "никогда";
  const t = new Date(s.replace(" ", "T")); const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return "только что"; if (m < 60) return `${m} мин назад`;
  if (m < 60 * 24) return `${Math.floor(m / 60)} ч ${m % 60} мин назад`;
  return fmtDT(s);
};
const initials = n => (n || "?").split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();
const age = b => { if (!b || !/^\d{4}-\d{2}-\d{2}/.test(b)) return ""; const d = parseDay(b.slice(0, 10)), n = new Date();
  let a = n.getFullYear() - d.getFullYear(); if (n < new Date(n.getFullYear(), d.getMonth(), d.getDate())) a--; return a; };
const plural = (n, a, b, c) => { const m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 10 || h >= 20) ? b : c; };
function stClass(s) {
  s = (s || "").toLowerCase();
  if (/отмен|cancel|не приш|неявк|no.?show|удал/.test(s)) return "st-cancel";
  if (/заверш|done|finish|complet|оплач|закрыт/.test(s)) return "st-done";
  if (/пришел|пришёл|в кресле|при[её]м|arriv|в клиник/.test(s)) return "st-come";
  if (/подтв|confirm/.test(s)) return "st-ok";
  return "";
}

/* --------------------------------------------------------------- state */
const S = {view: "schedule", day: iso(new Date()), branch: "", mode: "grid", settings: {day_start: 8, day_end: 21}, status: {}, lastLoaded: null, prevView: "patients"};

/* ---------------------------------------------------------------- views */
const VIEW_PERM = {schedule: "schedule_view", patients: "patients_view", patient: "patients_view", cash: ["cash_report", "expenses_day"],
  journal: ["transfer", "reports", "medcard_edit"], refs: "refs", settings: "settings", staff: "staff", stock: ["stock_view", "stock_edit", "equipment", "sterilization"],
  reports: "reports", accounting: "accounting", marketing: "marketing", shifts: ["schedule_view", "shifts_edit", "staff"],
  lab: ["lab", "accounting"], director: "reports"};
const canView = v => { const p = VIEW_PERM[v]; return !p || (Array.isArray(p) ? canAny(...p) : can(p)); };
function firstView() { return ["schedule", "patients", "cash", "director", "reports", "accounting", "marketing", "shifts", "lab", "stock", "journal", "refs", "staff", "settings"].find(canView) || "none"; }
function show(view) {
  if (!canView(view)) view = firstView();
  S.view = view;
  if (view === "none") { $$(".view").forEach(v => v.hidden = true); toast("Для вашей учётной записи пока не назначены разделы. Обратитесь к директору.", true); return; }
  $$(".view").forEach(v => v.hidden = v.id !== "view-" + view);
  $$(".nav").forEach(b => b.classList.toggle("active", b.dataset.view === view || (view === "patient" && b.dataset.view === "patients")));
  if (view === "schedule") loadDay();
  if (view === "patients") { searchPatients(); setTimeout(() => $("#patSearch").focus(), 30); }
  if (view === "settings") loadSettings();
  if (view === "cash") loadCash();
  if (view === "journal") loadJournal();
  if (view === "refs") loadRefs();
  if (view === "staff") loadStaff();
  if (view === "stock") loadStock();
  if (view === "reports") loadReports();
  if (view === "director" && typeof loadDirector === "function") loadDirector();
  if (view === "accounting") loadAccounting();
  if (view === "marketing") loadMarketing();
  if (view === "shifts") loadShifts();
  if (view === "lab" && typeof loadLab === "function") loadLab();
}
$$(".nav").forEach(b => b.onclick = () => show(b.dataset.view));

/* -------------------------------------------------------------- status */
function applyBrand(b) {
  if (!b) return;
  S.brandSet = true; document.title = b.name;
  $(".rail .brandmark b").textContent = b.short; $(".rail .brandmark small").textContent = b.sub; $(".rail .logo").title = b.name;
}
async function refreshStatus() {
  let st;
  try { st = await api.status(); } catch (e) { return; }
  S.status = st;
  if (st.brand && !S.brandSet) applyBrand(st.brand);
  const dot = $("#syncDot"), title = $("#syncTitle"), sub = $("#syncSub"), banner = $("#banner");
  dot.className = "dot";
  $("#syncBar").style.width = st.running ? (st.progress || 3) + "%" : "0";
  const fresh = `Данные на ${fmtDT(st.last_ok)}`;
  banner.hidden = true; banner.className = "banner";
  if (st.demo) { dot.classList.add("busy"); dot.style.animation = "none"; title.textContent = "Демо-режим"; sub.textContent = "Тестовые данные. Подключите API в настройках."; }
  else if (st.running) { dot.classList.add("busy"); title.textContent = "Синхронизация…"; sub.textContent = st.phase; }
  else if (!st.configured) { title.textContent = "Не подключено"; sub.textContent = "Укажите логин и пароль API в настройках"; }
  else if (st.online === false) {
    dot.classList.add("off"); title.textContent = "Офлайн"; sub.textContent = `${fresh}. Проверяем связь каждые 30 с.`;
    banner.hidden = false;
    banner.innerHTML = `<svg viewBox="0 0 24 24"><path d="M2 8.5a15 15 0 0 1 20 0M5.5 12a10 10 0 0 1 13 0M9 15.5a5 5 0 0 1 6 0M3 3l18 18"/></svg>Нет интернета — показаны сохранённые данные, актуальные на <b>&nbsp;${esc(fmtDT(st.last_ok))}</b>. Как только связь появится, всё обновится само.`;
  } else if (st.last_error) {
    dot.classList.add("err"); title.textContent = "Ошибка обновления"; sub.textContent = st.last_error;
    banner.hidden = false; banner.classList.add("err");
    banner.innerHTML = `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/></svg>${esc(st.last_error)} · сохранённые данные на ${esc(fmtDT(st.last_ok))}`;
  } else { dot.classList.add("on"); title.textContent = "Онлайн";
    sub.textContent = `Обновлено ${ago(st.last_ok)}` + (st.dp_main && st.dp_main.role === "follower" ? ` · через «${st.dp_main.name}»` : ""); }
  $("#syncBtn").disabled = !!st.running;
  const sb = $("#stockBadge"); if (sb) { const n = st.stock_alerts ?? st.stock_low; sb.hidden = !n; sb.textContent = n || "";
    sb.title = [st.stock_low ? `Заканчиваются: ${st.stock_low}` : "", st.stock_exp ? `Истекает срок: ${st.stock_exp}` : ""].filter(Boolean).join(" · "); }
  const lb = $("#labBadge"); if (lb) { lb.hidden = !st.lab_due; lb.textContent = st.lab_due || ""; }
  if (typeof platformStatus === "function") platformStatus(st);
  if (typeof addonStatus === "function") addonStatus(st);
  if (typeof crmStatus === "function") crmStatus(st);
  if (typeof stockAutoStatus === "function") stockAutoStatus(st);  // 3.5: visits waiting for the write-off
  if (typeof planCallsStatus === "function") planCallsStatus(st);  // 3.6: abandoned plans to call about
  if (st.me_perms && ME && st.me_perms.join() !== ME.perms.join()) {  // 2.14: the director changed this person's position
    ME.perms = st.me_perms; applyPerms();
    toast("Директор изменил ваши права — меню обновлено");
    if (!canView(S.view)) show(firstView());
  }
  if (st.backup_warn && st.backup_warn !== S.backupWarned) { S.backupWarned = st.backup_warn; toast(st.backup_warn + " Настройки → «Резервные копии».", true); }
  for (const id of ["#pendingBadge", "#pendingBadge2"]) { const pb = $(id); pb.hidden = !st.pending; pb.textContent = st.pending || ""; }
  if (typeof dpStatus === "function") dpStatus(st);  // 3.3: records not transferred, the reminder at the end of the day
  // data changed -> refresh current screen
  if (S.lastLoaded !== st.last_ok && !st.running) {
    const first = S.lastLoaded === null; S.lastLoaded = st.last_ok;
    if (!first) { if (S.view === "schedule") loadDay(); if (S.view === "patients") searchPatients(); }
  }
  $("#patCount").textContent = st.counts ? `${st.counts.patients} ${plural(st.counts.patients, "пациент", "пациента", "пациентов")} в локальной базе` : "";
}
$("#syncBtn").onclick = async () => { await api.sync_now(); setTimeout(refreshStatus, 400); };

/* ------------------------------------------------------------ schedule */
const DOC_COLORS = ["#6D0100", "#3E5C8A", "#5E7F5A", "#A8742A", "#6B5B7B", "#3F6F73", "#8C4A5E", "#7A6A4F", "#4F5D75", "#9A5B3C"];
const docColor = id => { const ids = ((S.dayData || {}).doctors || []).map(d => d.id); const i = ids.indexOf(id); return DOC_COLORS[(i < 0 ? 0 : i) % DOC_COLORS.length]; };
S.days = +(localStorage.getItem("dd.days") || 1);
S.by = localStorage.getItem("dd.by") || "doctor";
S.hiddenDocs = new Set(JSON.parse(localStorage.getItem("dd.hiddenDocs") || "[]"));
const DAYS_LBL = {1: "На день", 2: "2 дня", 3: "3 дня", 7: "Неделя"};

async function loadDay() {
  const d = parseDay(S.day);
  const last = parseDay(addDays(S.day, S.days - 1));
  $("#dayTitle").textContent = S.days === 1 ? `${WD[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`
    : `${d.getDate()} ${MONTHS[d.getMonth()]} — ${last.getDate()} ${MONTHS[last.getMonth()]}`;
  $("#dayPick").value = S.day;
  $("#ddDaysLbl").textContent = DAYS_LBL[S.days] || S.days + " дн.";
  $("#ddByLbl").textContent = S.by === "chair" ? "По креслам" : "По докторам";
  $("#ddModeLbl").textContent = S.mode === "list" ? "Список" : "Сетка";
  const days = Array.from({length: S.days}, (_, i) => addDays(S.day, i));
  const results = await Promise.all(days.map(x => api.day(x, S.branch || null)));
  const res = {visits: [], doctors: results[0].doctors, branches: results[0].branches, perDay: results.map((r, i) => ({day: days[i], visits: r.visits, shifts: r.shifts || null}))};
  results.forEach(r => res.visits.push(...r.visits));
  S.dayData = res;
  fillBranches(res.branches);
  fillDocsMenu(res.doctors);
  const v = res.visits.filter(x => S.by === "chair" || !S.hiddenDocs.has(x.doctor_id || "_"));
  const active = v.filter(x => stClass(x.status) !== "st-cancel").length;
  $("#daySub").textContent = v.length ? `${v.length} ${plural(v.length, "запись", "записи", "записей")}${active !== v.length ? `, из них ${v.length - active} отменено` : ""}` : "";
  const visibleDocs = res.doctors.filter(d => (!S.branch || !d.branch_id || d.branch_id === S.branch) && !S.hiddenDocs.has(d.id));
  const allHidden = S.by === "doctor" && res.doctors.length > 0 && !visibleDocs.length;
  const gridAnyway = S.mode === "grid" && visibleDocs.length && S.settings.show_empty_doctors !== false;
  const empty = (!v.length && !gridAnyway) || allHidden;
  $("#dayEmpty").hidden = !empty;
  const st = S.status;
  $("#dayEmpty b").textContent = allHidden ? "Не выбрано ни одного доктора" : "На этот день записей нет";
  $("#dayEmptySub").textContent = allHidden ? "Отметьте врачей в списке «Выбрано докторов»" : st.counts && st.counts.range && st.counts.range[0]
    ? `В локальной базе — записи с ${fmtDate(st.counts.range[0])} по ${fmtDate(st.counts.range[1])}` : "Локальная база пока пуста — дождитесь первой синхронизации";
  $("#grid").hidden = empty || S.mode !== "grid";
  $("#list").hidden = empty || S.mode !== "list";
  if (!empty) S.mode === "grid" ? renderGrid(res) : renderList(v);
  if (typeof refreshWaitBadge === "function") refreshWaitBadge();
}
function fillBranches(branches) {
  const sel = $("#branchSel");
  sel.hidden = branches.length < 2;
  const html = `<option value="">Все филиалы</option>` + branches.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  if (sel.dataset.h !== html) { sel.innerHTML = html; sel.dataset.h = html; }
  sel.value = S.branch;
}
function fillDocsMenu(doctors) {
  const list = doctors.filter(d => !S.branch || !d.branch_id || d.branch_id === S.branch);
  const shown = list.filter(d => !S.hiddenDocs.has(d.id)).length;
  $("#ddDocsLbl").textContent = `Выбрано докторов: ${shown === list.length ? "все" : shown}`;
  $("#docsMenu").innerHTML = `<div class="dm-h"><button class="linkbtn" data-all="1">Все</button><button class="linkbtn" data-all="0">Никого</button></div>` +
    list.map(d => `<label class="dm-row"><input type="checkbox" data-doc="${esc(d.id)}" ${S.hiddenDocs.has(d.id) ? "" : "checked"}><i style="background:${docColor(d.id)}"></i>${esc(d.name)}</label>`).join("");
  $$("#docsMenu input").forEach(cb => cb.onchange = () => { cb.checked ? S.hiddenDocs.delete(cb.dataset.doc) : S.hiddenDocs.add(cb.dataset.doc); saveDocs(); loadDay(); });
  $$("#docsMenu [data-all]").forEach(b => b.onclick = e => { e.stopPropagation(); if (b.dataset.all === "1") S.hiddenDocs.clear(); else list.forEach(d => S.hiddenDocs.add(d.id)); saveDocs(); loadDay(); });
}
const saveDocs = () => localStorage.setItem("dd.hiddenDocs", JSON.stringify([...S.hiddenDocs]));
function renderWeek() {}

const PX = 84 / 60; // px per minute: a 30-min visit fits name + time
function buildColumns(dayVisits, doctors, day) {
  const cols = new Map();
  if (S.by === "chair") {
    for (const v of dayVisits) { const k = v.chair ? String(v.chair) : "_"; if (!cols.has(k)) cols.set(k, {id: k, day, name: k === "_" ? "Кресло не указано" : (/^\d+$/.test(k) ? "Кресло " + k : k), items: [], chair: true}); cols.get(k).items.push(v); }
    return [...cols.values()].sort((a, b) => a.id === "_" ? 1 : b.id === "_" ? -1 : a.name.localeCompare(b.name, "ru", {numeric: true}));
  }
  const docName = Object.fromEntries(doctors.map(d => [d.id, d.name]));
  if (S.settings.show_empty_doctors !== false)
    for (const d of doctors) if ((!S.branch || !d.branch_id || d.branch_id === S.branch) && !S.hiddenDocs.has(d.id)) cols.set(d.id, {id: d.id, day, name: d.name, items: []});
  for (const v of dayVisits) {
    const k = v.doctor_id || "_";
    if (S.hiddenDocs.has(k)) continue;
    if (!cols.has(k)) cols.set(k, {id: k, day, name: v.doctor_name || docName[k] || (k === "_" ? "Без врача" : `Врач #${k}`), items: []});
    cols.get(k).items.push(v);
  }
  return [...cols.values()].sort((a, b) => a.name.localeCompare(b.name, "ru"));
}
function renderGrid(res) {
  const doctors = res.doctors;
  const perDay = res.perDay.map(pd => ({day: pd.day, shifts: pd.shifts, cols: buildColumns(pd.visits, doctors, pd.day)}));
  const all = perDay.flatMap(p => p.cols);
  let h0 = +S.settings.day_start || 8, h1 = +S.settings.day_end || 21;
  for (const v of res.visits) { h0 = Math.min(h0, Math.floor(mins(v.start) / 60)); h1 = Math.max(h1, Math.ceil((mins(v.end) || mins(v.start) + 30) / 60)); }
  h1 = Math.min(24, h1);
  const top = h0 * 60, height = (h1 - h0) * 60 * PX;
  const grid = $("#grid");
  const colW = S.days > 2 ? 150 : 190;
  grid.style.gridTemplateColumns = `56px repeat(${Math.max(1, all.length)}, minmax(${colW}px, 1fr))`;
  const today = iso(new Date());
  // row 1: days, row 2: doctor/chair headers
  let html = `<div class="g-corner" style="grid-row:1 / span 2"></div>`;
  for (const p of perDay) {
    const d = parseDay(p.day);
    html += `<div class="g-day ${p.day === today ? "today" : ""}" style="grid-column:span ${Math.max(1, p.cols.length)}">${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} <span>(${WD[d.getDay()]})</span></div>`;
  }
  for (const p of perDay) {
    if (!p.cols.length) { html += `<div class="g-head"><span class="muted">нет записей</span></div>`; continue; }
    for (const c of p.cols) {
      const pos = doctors.find(d => d.id === c.id) || {};
      const color = c.chair ? "#7A8794" : docColor(c.id);
      const first = c.items.map(x => x.start).sort()[0], lastE = c.items.map(x => x.end || x.start).sort().slice(-1)[0];
      const shift = !c.chair && p.shifts ? p.shifts[c.id] : undefined;  // work schedule, when the clinic keeps one
      const sub = c.chair ? [...new Set(c.items.map(x => x.doctor_name).filter(Boolean))].slice(0, 2).join(", ")
        : p.shifts ? (shift ? `смена ${shift.start} – ${shift.end}${shift.source === "dp" ? " · Dentist Plus" : ""}` : "выходной по графику") : (first ? `${hm(first)} – ${hm(lastE)}` : "нет записей");
      html += `<div class="g-head" style="--dc:${color}"><div class="gh-band"><span class="gh-av">${esc(initials(c.name))}</span><span class="gh-n">${esc(c.name)}<small>${esc(sub)}</small></span></div>
        <div class="gh-meta">${c.items.length} ${plural(c.items.length, "запись", "записи", "записей")}${pos.position ? " · " + esc(pos.position) : ""}</div></div>`;
    }
  }
  let times = "";
  for (let h = h0; h <= h1; h++) { times += `<div style="top:${(h * 60 - top) * PX}px">${pad(h)}:00</div>`; if (h < h1) times += `<div class="half" style="top:${(h * 60 + 30 - top) * PX}px">${pad(h)}:30</div>`; }
  html += `<div class="g-times" style="height:${height}px">${times}</div>`;
  const nowM = new Date().getHours() * 60 + new Date().getMinutes();
  const ws = +S.settings.day_start || 8, we = +S.settings.day_end || 21;
  for (const p of perDay) {
    const cols = p.cols.length ? p.cols : [{id: "_", day: p.day, items: []}];
    for (const c of cols) {
      let lines = "";
      for (let m = top; m < h1 * 60; m += 30) lines += `<div class="hl ${m % 60 ? "half" : ""}" style="top:${(m - top) * PX}px"></div>`;
      // hatched time outside working hours: the doctor's shift when there is a work schedule for the day, else the clinic's day
      const sh = !c.chair && p.shifts && c.id !== "_" ? (p.shifts[c.id] || {start: "00:00", end: "00:00"}) : null;
      const cs = sh ? Math.max(top, mins("0000-00-00 " + sh.start)) : ws * 60, ce = sh ? Math.min(h1 * 60, Math.max(cs, mins("0000-00-00 " + sh.end))) : we * 60;
      if (cs > top) lines += `<div class="off-hours" style="top:0;height:${(cs - top) * PX}px"></div>`;
      if (ce < h1 * 60) lines += `<div class="off-hours" style="top:${(ce - top) * PX}px;height:${(h1 * 60 - ce) * PX}px"></div>`;
      const items = c.items.slice().sort((a, b) => a.start.localeCompare(b.start));
      let lanes = []; const groups = []; let g = null, gEnd = -1;
      for (const v of items) {
        const s = mins(v.start), e = Math.max(s + 15, mins(v.end) || s + 30);
        if (s >= gEnd) { g = []; groups.push(g); lanes = []; }
        let li = lanes.findIndex(end => end <= s);
        if (li < 0) { li = lanes.length; lanes.push(e); } else lanes[li] = e;
        v._s = s; v._e = e; v._lane = li; g.push(v); gEnd = Math.max(gEnd, e);
      }
      for (const grp of groups) { const n = Math.max(...grp.map(v => v._lane)) + 1; grp.forEach(v => v._n = n); }
      let evs = "";
      for (const v of items) {
        const hgt = Math.max(24, (v._e - v._s) * PX - 3), w = 100 / v._n, short = hgt < 46;
        const dc = docColor(v.doctor_id);
        evs += `<div class="ev ${stClass(v.status)} ${v.local ? "is-local" : ""} ${v.conflict ? "is-conflict" : ""}" data-id="${esc(v.id)}" title="${esc((v.patient_name || "") + " · " + (v.status || "") + (v.local ? " · изменено в программе" : "") + (v.conflict ? " · ДВОЙНАЯ ЗАПИСЬ у врача" : ""))}" style="--dc:${dc};top:${(v._s - top) * PX + 1}px;height:${hgt}px;left:calc(${w * v._lane}% + 4px);right:auto;width:calc(${w}% - 8px)">
          <div class="ev-t"><span class="st-dot"></span>${hm(v.start)} – ${hm(v.end)}${v.local ? '<i class="lc" title="Нужно перенести в Dentist Plus"></i>' : ""}${v.comment ? '<i class="cm" title="' + esc(v.comment) + '">💬</i>' : ""}</div>
          <b>${esc(v.patient_name || "Пациент #" + (v.patient_id || "?"))}</b>
          ${short ? "" : `<div class="s">${esc(v.title || "")}${S.by === "chair" && v.doctor_name ? " · " + esc(v.doctor_name) : ""}</div>`}</div>`;
      }
      const now = p.day === today && nowM >= top && nowM <= h1 * 60 ? `<div class="now-line" style="top:${(nowM - top) * PX}px"></div>` : "";
      const docAttr = S.by === "chair" ? "" : (c.id === "_" ? "" : c.id);
      html += `<div class="g-col ${p.day === today ? "is-today" : ""}" data-doc="${esc(docAttr)}" data-chair="${esc(S.by === "chair" && c.id !== "_" ? c.id : "")}" data-day="${p.day}" data-top="${top}" style="height:${height}px">${lines}${now}${evs}<div class="slot-hover" hidden></div></div>`;
    }
  }
  grid.innerHTML = html;
  $$(".ev", grid).forEach(el => el.onclick = e => { e.stopPropagation(); openVisit(el.dataset.id); });
  if (typeof enableDragMove === "function") enableDragMove(grid);
  const slot = +S.settings.slot_min || 15;
  const minuteAt = (col, e) => { const y = e.clientY - col.getBoundingClientRect().top; return Math.floor((+col.dataset.top + y / PX) / slot) * slot; };
  if (can("schedule_edit")) $$(".g-col", grid).forEach(col => {
    const hov = $(".slot-hover", col);
    col.onmousemove = e => { if (e.target.closest(".ev")) { hov.hidden = true; return; } const m = minuteAt(col, e);
      hov.hidden = false; hov.style.top = (m - col.dataset.top) * PX + "px"; hov.style.height = 30 * PX + "px"; hov.textContent = `+ ${pad(Math.floor(m / 60))}:${pad(m % 60)}`; };
    col.onmouseleave = () => hov.hidden = true;
    col.onclick = e => { if (e.target.closest(".ev")) return; const m = minuteAt(col, e);
      openBooking({doctor_id: col.dataset.doc, chair: col.dataset.chair, start: `${col.dataset.day} ${pad(Math.floor(m / 60))}:${pad(m % 60)}`}); };
  });
  if (perDay.some(p => p.day === today) && !grid.dataset.scrolled) { $(".sched-wrap").scrollTop = Math.max(0, (nowM - top - 60) * PX); grid.dataset.scrolled = 1; }
}
function renderList(visits) {
  $("#list").innerHTML = `<table class="tbl"><thead><tr><th>Дата и время</th><th>Пациент</th><th>Доктор</th><th>Кресло</th><th>Услуга</th><th>Статус</th></tr></thead><tbody>${
    visits.map(v => `<tr data-id="${esc(v.id)}"><td><b>${S.days > 1 ? fmtDT(v.start).slice(0, 5) + " " : ""}${hm(v.start)}–${hm(v.end)}</b></td>
      <td>${v.local ? '<i class="lc"></i>' : ""}<b>${esc(v.patient_name || "Пациент #" + (v.patient_id || "?"))}</b><small class="muted" style="display:block">${esc(v.patient_phone || "")}</small></td>
      <td><span class="dc-dot" style="background:${docColor(v.doctor_id)}"></span>${esc(v.doctor_name || "—")}</td><td>${esc(v.chair || "")}</td><td>${esc(v.title || "")}</td>
      <td><span class="pill ${stClass(v.status)}">${esc(v.status || "—")}</span></td></tr>`).join("")}</tbody></table>`;
  $$("#list tr[data-id]").forEach(el => el.onclick = () => openVisit(el.dataset.id));
}
/* dropdowns */
$$(".dd").forEach(dd => {
  $(".dd-btn", dd).onclick = e => { e.stopPropagation(); const open = dd.classList.contains("open"); $$(".dd.open").forEach(x => x.classList.remove("open")); if (!open) dd.classList.add("open"); };
  $(".dd-menu", dd).addEventListener("click", e => { if (!dd.id.includes("Docs")) dd.classList.remove("open"); e.stopPropagation(); });
});
document.addEventListener("click", () => $$(".dd.open").forEach(x => x.classList.remove("open")));
$$("#ddDays [data-days]").forEach(b => b.onclick = () => { S.days = +b.dataset.days; localStorage.setItem("dd.days", S.days); $("#grid").dataset.scrolled = ""; loadDay(); });
$$("#ddBy [data-by]").forEach(b => b.onclick = () => { S.by = b.dataset.by; localStorage.setItem("dd.by", S.by); loadDay(); });
$$("#modeSeg [data-mode]").forEach(b => b.onclick = () => { S.mode = b.dataset.mode; loadDay(); });
$("#prevDay").onclick = () => { S.day = addDays(S.day, -S.days); loadDay(); };
$("#nextDay").onclick = () => { S.day = addDays(S.day, S.days); loadDay(); };
$("#todayBtn").onclick = () => { S.day = iso(new Date()); $("#grid").dataset.scrolled = ""; loadDay(); };
$("#dayPick").onchange = e => { if (e.target.value) { S.day = e.target.value; loadDay(); } };
$("#branchSel").onchange = e => { S.branch = e.target.value; loadDay(); };
$("#newVisitBtn").onclick = () => openBooking({start: `${S.day} ${pad(Math.max(+S.settings.day_start || 8, Math.min(20, new Date().getHours() + 1)))}:00`});
$("#printBtn").onclick = () => {
  const v = (S.dayData || {}).visits || [];
  const byDoc = {};
  v.forEach(x => (byDoc[(S.days > 1 ? x.start.slice(0, 10) + " · " : "") + (x.doctor_name || "Без врача")] ||= []).push(x));
  $("#printArea").innerHTML = `<h2>Расписание: ${esc($("#dayTitle").textContent)}</h2><div>Данные на ${esc(fmtDT(S.status.last_ok))}</div>` +
    Object.entries(byDoc).sort().map(([doc, items]) => `<h3>${esc(doc)}</h3><table><tr><th>Время</th><th>Пациент</th><th>Телефон</th><th>Услуга</th><th>Статус</th></tr>${
      items.map(x => `<tr><td>${hm(x.start)}–${hm(x.end)}</td><td>${esc(x.patient_name || "")}</td><td>${esc(x.patient_phone || "")}</td><td>${esc(x.title || "")}</td><td>${esc(x.status || "")}</td></tr>`).join("")}</table>`).join("");
  window.print();
};

/* ------------------------------------------------- top bar: search, add */
let gsT, gsRows = [];
$("#gSearch").oninput = () => { clearTimeout(gsT); gsT = setTimeout(gSearch, 140); };
$("#gSearch").onfocus = () => { if ($("#gSearch").value) gSearch(); };
$("#gSearch").onkeydown = e => {
  if (e.key === "Enter" && gsRows[0]) { openPatient(gsRows[0].id, S.view === "patient" ? S.prevView : S.view); $("#gDrop").hidden = true; $("#gSearch").blur(); }
  if (e.key === "Escape") { $("#gDrop").hidden = true; $("#gSearch").blur(); }
};
document.addEventListener("click", e => { if (!e.target.closest(".gsearch")) $("#gDrop").hidden = true; });
async function gSearch() {
  const q = $("#gSearch").value.trim();
  if (!q) { $("#gDrop").hidden = true; return; }
  gsRows = (await api.search(q)).slice(0, 8);
  $("#gDrop").innerHTML = gsRows.map(p => `<div class="pp-row" data-id="${esc(p.id)}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}${p.birth ? " · " + fmtDate(p.birth) : ""}${p.next_visit ? " · визит " + fmtDT(p.next_visit) : ""}</small></span></div>`).join("")
    || `<div class="muted" style="padding:10px 12px">Не найдено.${can("patients_edit") ? ` <button class="linkbtn" id="gsNew">Добавить пациента</button>` : ""}</div>`;
  $("#gDrop").hidden = false;
  $$("#gDrop .pp-row").forEach(r => r.onclick = () => { openPatient(r.dataset.id, S.view === "patient" ? S.prevView : S.view); $("#gDrop").hidden = true; });
  const n = $("#gsNew"); if (n) n.onclick = () => { $("#gDrop").hidden = true; openNewPatient(q); };
}
function openNewPatient(q = "") {
  const parts = q.trim().split(/\s+/).filter(Boolean), isPhone = /\d/.test(q);
  const box = modal(`<div class="m-h"><h3>Новый пациент</h3><button class="x" data-close>×</button></div><div class="m-b">
    <div class="grid3"><label class="fl">Фамилия*<input class="input" id="npL" value="${esc(isPhone ? "" : parts[0] || "")}" autofocus></label>
      <label class="fl">Имя*<input class="input" id="npF" value="${esc(isPhone ? "" : parts[1] || "")}"></label><label class="fl">Отчество<input class="input" id="npM" value="${esc(isPhone ? "" : parts[2] || "")}"></label></div>
    <div class="grid3"><label class="fl">Телефон<input class="input" id="npPh" value="${esc(isPhone ? q : "")}"></label>
      <label class="fl">Дата рождения<input class="input" type="date" id="npB"></label><label class="fl">Пол<select class="input" id="npG"><option value="">—</option><option>М</option><option>Ж</option></select></label></div>
    <label class="fl">Адрес<input class="input" id="npA"></label><div class="grid2"><label class="fl">Комментарий<input class="input" id="npC"></label>
      <label class="fl">Откуда узнал о клинике<select class="input" id="npSrc"><option value="">— не указан —</option></select></label></div></div>
    <div class="m-f"><span class="muted">Пациент будет добавлен в список «Перенести в DP»</span><button class="btn ghost" data-close>Отмена</button>
      ${can("schedule_edit") ? `<button class="btn ghost" id="npSaveBook">Сохранить и записать</button>` : ""}<button class="btn" id="npSave">Сохранить</button></div>`);
  const save = async () => {
    if (!$("#npL", box).value.trim() || !$("#npF", box).value.trim()) { toast("Укажите фамилию и имя", true); return null; }
    const p = await api.create_patient({lname: $("#npL", box).value, fname: $("#npF", box).value, mname: $("#npM", box).value, phone: $("#npPh", box).value,
      birth_date: $("#npB", box).value, gender: $("#npG", box).value, address: $("#npA", box).value, comment: $("#npC", box).value});
    const src = $("#npSrc", box).value;
    if (src && p && p.id) { try { await api.set_patient_marketing(p.id, {source: src}); } catch (e) {} }
    return p;
  };
  mkSourceList().then(list => { const sel = $("#npSrc", box); if (sel) sel.innerHTML += list.map(x => `<option>${esc(x)}</option>`).join(""); });
  const npSave = $("#npSave", box), npBook = $("#npSaveBook", box);
  npSave.onclick = () => !(npBook && npBook.disabled) && busy(npSave, async () => { const p = await save(); if (!p) return; closeModal(); toast("Пациент добавлен"); refreshStatus(); openPatient(p.id, S.view === "patient" ? S.prevView : S.view); });
  if (npBook) npBook.onclick = () => !npSave.disabled && busy(npBook, async () => { const p = await save(); if (!p) return; closeModal(); refreshStatus();
    openBooking({patient_id: p.id, patient_name: p.name, start: `${S.day} ${pad(Math.min(20, new Date().getHours() + 1))}:00`}); });
}
$("#tbAddPatient").onclick = () => openNewPatient();
/* 3.7: change the card of a patient. A Dentist Plus patient: the change goes to «Перенос» (or by itself with the
   automatic transfer, PUT /patients/{id}); a patient created here: the card itself is changed. */
function openEditPatient(p, d) {
  const g = String(d.gender || "").toLowerCase(), gv = /^(male|м)/.test(g) ? "М" : /^(female|ж)/.test(g) ? "Ж" : "";
  const birth = String(d.birth_date || d.date_of_birth || p.birth || "").slice(0, 10);
  const box = modal(`<div class="m-h"><h3>Изменить карточку</h3><button class="x" data-close>×</button></div><div class="m-b">
    <div class="grid3"><label class="fl">Фамилия<input class="input" id="epL" value="${esc(d.lname || "")}"></label>
      <label class="fl">Имя*<input class="input" id="epF" value="${esc(d.fname || "")}"></label><label class="fl">Отчество<input class="input" id="epM" value="${esc(d.mname || "")}"></label></div>
    <div class="grid3"><label class="fl">Телефон<input class="input" id="epPh" value="${esc(d.phone || p.phone || "")}"></label>
      <label class="fl">Дата рождения<input class="input" type="date" id="epB" value="${esc(birth)}"></label><label class="fl">Пол<select class="input" id="epG"><option value="">—</option><option ${gv === "М" ? "selected" : ""}>М</option><option ${gv === "Ж" ? "selected" : ""}>Ж</option></select></label></div>
    <div class="grid2"><label class="fl">Адрес<input class="input" id="epA" value="${esc(d.address || "")}"></label><label class="fl">Email<input class="input" id="epE" value="${esc(d.email || "")}"></label></div></div>
    <div class="m-f"><span class="muted">${p.local ? "" : "Изменение попадёт в «Перенос» для Dentist Plus"}</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="epSave">Сохранить</button></div>`);
  $("#epSave", box).onclick = async () => {
    if (!$("#epF", box).value.trim()) { toast("Укажите имя", true); return; }
    try {
      await api.patient_edit(p.id, {lname: $("#epL", box).value, fname: $("#epF", box).value, mname: $("#epM", box).value, phone: $("#epPh", box).value,
        birth_date: $("#epB", box).value, gender: $("#epG", box).value, address: $("#epA", box).value, email: $("#epE", box).value});
    } catch (e) { toast(errText(e), true); return; }
    closeModal(); toast("Карточка изменена"); refreshStatus(); openPatient(p.id, S.prevView);
  };
}
$("#tbJournal").onclick = () => show("journal");

/* ---------------------------------------------------------- visit drawer */
async function openVisit(id) {
  const v = await api.visit(id);
  if (!v) return;
  const raw = v.data || {};
  $("#drawer").innerHTML = `<div class="dw-h"><button class="x" onclick="closeDrawer()">×</button>
      <span class="pill ${stClass(v.status)}">${esc(v.status || "Без статуса")}</span>
      <h3>${esc(v.patient_name || "Пациент #" + (v.patient_id || "?"))}</h3>
      <div class="muted">${fmtDate(v.start)}, ${hm(v.start)}–${hm(v.end)}${!v.local && typeof dpSrc === "function" ? dpSrc("Запись на приём") : ""}</div></div>
    <div class="dw-b"><dl class="kv" style="grid-template-columns:1fr">
      ${kvRow("Врач", v.doctor_name)}${kvRow("Филиал", v.branch_name)}${kvRow("Телефон пациента", v.patient_phone)}${kvRow("Услуга / комментарий", v.title)}${kvRow("Комментарий", v.comment)}
    </dl>${Object.keys(raw).length ? `<div class="raw">${rawTree(raw, 0, ["id", "patient_id", "doctor_id", "branch_id", "start", "end", "status", "title"])}</div>` : ""}</div>
    ${v.conflict_text ? `<div class="conflict-note"><b>Двойная запись.</b> ${esc(v.conflict_text[0].toUpperCase() + v.conflict_text.slice(1))}. Перенесите одну из записей или уточните у пациентов.</div>` : ""}
    ${v.allergies && v.allergies.length ? `<div class="conflict-note allergy-note"><b>Аллергия:</b> ${esc(v.allergies.join("; "))}</div>` : ""}
    ${v.series_id ? `<div class="series-note" id="dwSeries">Повторяющийся визит…</div>` : ""}
    ${v.local ? `<div class="local-note">Изменено в этой программе: <b>${esc({create: "новая запись", edit: "изменение", move: "перенос", cancel: "отмена", status: "смена статуса"}[v.action] || "изменение")}</b>. Нужно перенести в Dentist Plus.
       ${v.origin_id ? `<button class="linkbtn" id="dwRevert">Вернуть как в Dentist Plus</button>` : ""}</div>` : ""}
    ${visitActions(v)}`;
  const dw = $("#drawer");
  const drop = (sel, cond) => { if (cond) $$(sel, dw).forEach(el => el.remove()); };
  drop("[data-st='Не пришёл'], [data-st='Отменён'], #dwEdit, #dwRevert", !can("schedule_edit"));
  drop("[data-st]", !canAny("schedule_edit", "medcard_edit"));
  drop("#dwRec", !can("medcard_view")); drop("#dwInv", !canAny("billing", "payments")); drop("#dwDoc", !can("docs")); drop("#dwCard", !can("patients_view"));
  $$("[data-st]", dw).forEach(b => b.onclick = async () => {
    if (b.dataset.st === "Отменён" && !(await ask("Отменить запись?", {danger: true, ok: "Отменить запись", cancel: "Не отменять", text: `${v.patient_name || "Пациент"}, ${fmtDT(v.start)}`}))) return;
    await api.set_visit_status(v.id, b.dataset.st); toast(`Статус: ${b.dataset.st}`); closeDrawer(); afterChange();
    if (["Отменён", "Не пришёл"].includes(b.dataset.st) && typeof waitlistHint === "function") waitlistHint(v);
  });
  if (v.series_id) api.visit_series(v.series_id).then(list => {
    const el = $("#dwSeries", dw); if (!el) return;
    const i = list.findIndex(x => x.id === v.id), later = list.filter(x => x.start > v.start && stClass(x.status) !== "st-cancel");
    el.innerHTML = `Повторяющийся визит: <b>${i + 1} из ${list.length}</b>${later.length ? ` · дальше: ${later.slice(0, 4).map(x => fmtDT(x.start).slice(0, 5)).join(", ")}${later.length > 4 ? "…" : ""}` : ""}
      ${can("schedule_edit") && stClass(v.status) !== "st-cancel" ? `<button class="linkbtn" id="dwSerCancel">Отменить этот и следующие</button>` : ""}`;
    const b = $("#dwSerCancel", dw);
    if (b) b.onclick = async () => {
      if (!(await ask("Отменить этот и все следующие визиты серии?", {danger: true, ok: "Отменить", cancel: "Не отменять",
        text: `${v.patient_name || "Пациент"}: будет отменено ${later.length + 1} ${plural(later.length + 1, "визит", "визита", "визитов")}, начиная с ${fmtDT(v.start)}.`}))) return;
      const n = await api.cancel_series(v.series_id, v.start);
      toast(`Отменено визитов: ${n}`); closeDrawer(); afterChange();
      if (typeof waitlistHint === "function") waitlistHint(v);
    };
  }).catch(() => {});
  const de = $("#dwEdit", dw); if (de) de.onclick = () => { closeDrawer(); openBooking(v); };
  const rv = $("#dwRevert", dw); if (rv) rv.onclick = async () => { if (await ask("Вернуть запись как в Dentist Plus?", {icon: "warn", ok: "Вернуть", text: "Изменения, сделанные в программе, будут убраны."})) { await api.revert_visit(v.id); closeDrawer(); afterChange(); } };
  if (v.patient_id) {
    const on = (s, f) => { const el = $(s, dw); if (el) el.onclick = f; };
    on("#dwRec", () => { closeDrawer(); openRecord({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id, date: v.start.slice(0, 10), id: (v.records[0] || {}).id}); });
    on("#dwInv", () => { closeDrawer(); openInvoice({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id, id: (v.invoices[0] || {}).id}); });
    on("#dwDoc", () => { closeDrawer(); openDocPicker({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id}); });
    on("#dwCard", () => { closeDrawer(); openPatient(v.patient_id, "schedule"); });
  }
  $("#scrim").hidden = false;
  setTimeout(() => $("#drawer").classList.add("open"), 10);
}
/* 3.9: the panel's buttons by importance. The big one is the next step for this visit: «Пришёл» before the patient
   comes, «Счёт и оплата» once they are here or done, «Перенести» for a cancelled visit. «Не пришёл» and «Отменить»
   sit apart at the bottom, so they are not pressed by mistake. Ids and data-st stay: openVisit wires them. */
function visitActions(v) {
  const stc = stClass(v.status), rec = v.records && v.records.length, inv = v.invoices && v.invoices.length, pid = !!v.patient_id;
  const acts = {
    arrived: stc === "st-come" || stc === "st-done" ? "" : `<button class="btn ghost" data-st="Пришёл">Пришёл</button>`,
    done: stc === "st-done" ? "" : `<button class="btn ghost" data-st="Завершён">Завершён</button>`,
    inv: pid ? `<button class="btn ghost ${inv ? "on" : ""}" id="dwInv">${inv ? "Счёт ✓" : "Счёт и оплата"}</button>` : "",
    rec: pid ? `<button class="btn ghost ${rec ? "on" : ""}" id="dwRec">${rec ? "Медкарта ✓" : "Медкарта: приём"}</button>` : "",
    edit: `<button class="btn ghost" id="dwEdit">Перенести</button>`,
    doc: pid ? `<button class="btn ghost" id="dwDoc">Документ</button>` : "",
    card: pid ? `<button class="btn ghost" id="dwCard">Карта пациента</button>` : "",
  };
  const main = stc === "st-cancel" ? "edit" : stc === "st-come" || stc === "st-done" ? (acts.inv ? "inv" : "done") : "arrived";
  return `<div class="dw-f"><div class="dw-main">${acts[main].replace('class="btn ghost', 'class="btn')}</div>`
    + `<div class="dw-grid">${Object.keys(acts).filter(k => k !== main).map(k => acts[k]).join("")}</div>`
    + `<div class="dw-danger"><button class="btn ghost small" data-st="Не пришёл">Не пришёл</button><button class="btn ghost small danger" data-st="Отменён">Отменить запись</button></div></div>`;
}
/** Allergy banner in the record / invoice editors: the allergy itself, and red lines for clashes with what is prescribed. */
function allergyBar(el, r) {
  if (!el) return;
  const al = (r && r.allergies) || [], w = (r && r.warnings) || [];
  el.hidden = !al.length;
  if (!al.length) { el.innerHTML = ""; return; }
  el.className = "allergy-bar" + (w.some(x => x.level === "stop") ? " stop" : w.length ? " warn" : "");
  el.innerHTML = `<b>Аллергия: ${esc(al.join("; "))}</b>` + w.map(x => `<div class="al-w ${x.level}">${x.level === "stop" ? "Стоп" : "Осторожно"}: ${esc(x.text)}</div>`).join("");
}
function afterChange() {
  refreshStatus();
  if (S.view === "schedule") loadDay();
  if (S.view === "patient" && P) openPatient(P.id, S.prevView, S.patientTab);
  if (S.view === "journal") loadJournal();
  if (S.view === "cash") loadCash();
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").hidden = true; }
$("#scrim").onclick = closeDrawer;
const kvRow = (k, v) => v === undefined || v === null || v === "" ? "" : `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`;

/* ------------------------------------------------------------ patients */
let searchT;
$("#patSearch").oninput = () => { clearTimeout(searchT); searchT = setTimeout(searchPatients, 160); };
$("#patSearch").onkeydown = e => { if (e.key === "Enter") { const r = $("#patTable tbody tr"); if (r) r.click(); } };
async function searchPatients() {
  const rows = await api.search($("#patSearch").value);
  $("#patEmpty").hidden = rows.length > 0;
  $("#patTable").hidden = !rows.length;
  $("#patTable tbody").innerHTML = rows.map(p => `<tr data-id="${esc(p.id)}">
    <td><div class="who"><span class="av">${esc(initials(p.name))}</span>${esc(p.name)}</div></td>
    <td>${esc(p.phone || "—")}</td><td>${p.birth ? esc(fmtDate(p.birth)) + ` <span class="muted">(${age(p.birth)})</span>` : "—"}</td>
    <td>${p.last_visit ? fmtDT(p.last_visit) : "—"}</td><td>${p.next_visit ? `<b>${fmtDT(p.next_visit)}</b>` : "—"}</td></tr>`).join("");
  $$("#patTable tbody tr").forEach(tr => tr.onclick = () => openPatient(tr.dataset.id, "patients"));
}

/* -------------------------------------------------------- patient card */
const LABELS = {
  id: "ID", lname: "Фамилия", fname: "Имя", mname: "Отчество", last_name: "Фамилия", first_name: "Имя", middle_name: "Отчество",
  name: "Имя", fio: "ФИО", full_name: "ФИО", gender: "Пол", sex: "Пол", birth_date: "Дата рождения", birthday: "Дата рождения",
  date_of_birth: "Дата рождения", phone: "Телефон", mphone: "Мобильный", phone2: "Доп. телефон", email: "Email", address: "Адрес",
  card_number: "Номер карты", card: "Номер карты", comment: "Комментарий", comments: "Комментарии", note: "Примечание", notes: "Примечания",
  allergies: "Аллергии", allergy: "Аллергии", chronic_diseases: "Хронические заболевания", diseases: "Заболевания", blood_type: "Группа крови",
  balance: "Баланс", debt: "Долг", discount: "Скидка", source: "Источник", created_at: "Создан", updated_at: "Обновлён",
  status: "Статус", title: "Название", code: "Код", tooth: "Зуб", teeth: "Зубы", date: "Дата", start: "Начало", end: "Окончание",
  doctor: "Врач", doctor_id: "ID врача", patient_id: "ID пациента", branch_id: "ID филиала", branch: "Филиал", chair: "Кресло",
  description: "Описание", diagnosis: "Диагноз", diagnoses: "Диагнозы", complaints: "Жалобы", anamnesis: "Анамнез",
  treatment: "Лечение", recommendations: "Рекомендации", price: "Цена", sum: "Сумма", total: "Итого", passport: "Паспорт", snils: "СНИЛС",
  inn: "ИНН", polis: "Полис", oms: "Полис ОМС", dms: "ДМС", workplace: "Место работы", parent: "Представитель", dental_formula: "Зубная формула",
  position: "Должность", duration: "Длительность", services: "Услуги", tags: "Метки", representative: "Представитель", city: "Город"
};
const label = k => LABELS[k] || LABELS[k.toLowerCase()] || k.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const isEmpty = v => v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
function prim(v, k = "") {
  if (typeof v === "boolean") return v ? "Да" : "Нет";
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}.*)?$/.test(s)) return s.length > 10 && s.slice(11, 16) !== "00:00" ? fmtDT(s.replace("T", " ")) : fmtDate(s);
  if (/(balance|sum|price|debt|total)/i.test(k) && /^-?\d+(\.\d+)?$/.test(s)) return Number(s).toLocaleString("ru-RU") + " ₽";
  return s;
}
function rawTree(obj, depth = 0, skip = []) {
  if (isEmpty(obj)) return `<div class="muted">Нет данных</div>`;
  if (Array.isArray(obj)) {
    return obj.map((it, i) => typeof it === "object" && it ? `<details ${depth < 1 ? "open" : ""}><summary>${esc(it.title || it.name || it.code || "#" + (i + 1))}</summary>${rawTree(it, depth + 1)}</details>`
      : `<div class="r"><span>${i + 1}</span><span>${esc(prim(it))}</span></div>`).join("");
  }
  return Object.entries(obj).filter(([k, v]) => !skip.includes(k) && !isEmpty(v)).map(([k, v]) =>
    typeof v === "object" ? `<details ${depth < 1 && JSON.stringify(v).length < 600 ? "open" : ""}><summary>${esc(label(k))}</summary>${rawTree(v, depth + 1)}</details>`
      : `<div class="r"><span>${esc(label(k))}</span><span>${esc(prim(v, k))}</span></div>`).join("");
}
function findTeeth(data) {
  for (const [k, v] of Object.entries(data || {})) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const keys = Object.keys(v); const n = keys.filter(x => /^[1-8][1-8]$/.test(x)).length;
      if (n >= 8) return {key: k, map: Object.fromEntries(keys.filter(x => /^[1-8][1-8]$/.test(x)).map(x => [x, typeof v[x] === "object" ? (v[x].status || v[x].title || JSON.stringify(v[x])) : v[x]]))};
    }
    if (Array.isArray(v) && v.length >= 4 && v.every(x => x && typeof x === "object" && /^[1-8][1-8]$/.test(String(x.tooth ?? x.number ?? x.num ?? "")))) {
      return {key: k, map: Object.fromEntries(v.map(x => [String(x.tooth ?? x.number ?? x.num), x.status || x.state || x.title || x.diagnosis || ""]))};
    }
  }
  return null;
}
function toothCls(s) {
  s = String(s || "").toLowerCase();
  if (/отсут|удал|missing|extract/.test(s)) return "t-miss";
  if (/имплант|implant/.test(s)) return "t-impl";
  if (/корон|crown|мост|bridge/.test(s)) return "t-crown";
  if (/пломб|fill|леч/.test(s)) return "t-fill";
  if (/кари|пульп|периодон|caries|разруш/.test(s)) return "t-bad";
  return "";
}
function teethHtml(t) {
  const row = qs => `<div class="jaw">${qs.map((q, qi) => (qi ? `<span class="gap"></span>` : "") + q.map(n => {
    const st = t.map[String(n)] || ""; return `<div class="tooth ${toothCls(st)}" title="${esc(n + ": " + st)}"><b>${n}</b>${esc(st && toothCls(st) ? "" : "")}</div>`; }).join("")).join("")}</div>`;
  const up = [[18, 17, 16, 15, 14, 13, 12, 11], [21, 22, 23, 24, 25, 26, 27, 28]];
  const lo = [[48, 47, 46, 45, 44, 43, 42, 41], [31, 32, 33, 34, 35, 36, 37, 38]];
  return `<div class="teeth">${row(up)}${row(lo)}
    <div class="legend"><span><i style="background:var(--danger-soft)"></i>Кариес / лечение нужно</span><span><i style="background:var(--blue-soft)"></i>Пломба</span>
    <span><i style="background:var(--warn-soft)"></i>Коронка</span><span><i style="background:var(--accent-soft)"></i>Имплант</span><span><i style="background:#F3F5F7"></i>Отсутствует</span></div></div>`;
}
let P = null;
async function openPatient(id, from, tab) {
  P = await api.patient(id);
  if (!P) return;
  S.prevView = from || S.view;
  if (S.view !== "patient") show("patient");
  renderPatient(tab || S.patientTab || "visits");
}

/* --- tooth formula: own profile drawings, 5-surface scheme, states drawn over the tooth.
   Shapes are drawn for the lower jaw (crown up, roots down) and mirrored for the upper one.
   No colours here: every part has a class, styles-teeth.css paints it from theme tokens. --- */
const TOOTH_SHAPES = {
  front: {crown: "M11 5Q18 2.5 25 5L26.2 17Q26 27 23 33H13Q10 27 9.8 17Z", fill: "M12.6 9Q18 7.4 23.4 9L23.8 18.5Q18 20.5 12.2 18.5Z",
    roots: ["M13 32H23Q22.6 58 19.2 80Q18 82.5 16.8 80Q13.4 58 13 32Z"], canals: "M18 30V77", apex: [[18, 81]], spot: [18, 15]},
  canine: {crown: "M10.5 14Q12 7 18 2.5Q24 7 25.5 14L25 25Q24 30 22.5 34H13.5Q12 30 11 25Z", fill: "M13.6 13Q18 8.5 22.4 13L22.6 21Q18 23 13.4 21Z",
    roots: ["M13.5 33H22.5Q22.4 62 19 84Q18 85.6 17 84Q13.6 62 13.5 33Z"], canals: "M18 31V81", apex: [[18, 84.5]], spot: [18, 17]},
  pre: {crown: "M8.5 12Q10 5 15 4.5Q18 3 21 4.5Q26 5 27.5 12L27 22Q26 29 23.5 33H12.5Q10 29 9 22Z", fill: "M11.6 10.5Q18 8 24.4 10.5L24.2 19.5Q18 21.5 11.8 19.5Z",
    roots: ["M12.5 32H23.5Q23 56 19.3 78Q18 80 16.7 78Q13 56 12.5 32Z"], canals: "M18 30V75", apex: [[18, 79]], spot: [18, 14]},
  pre2: {crown: "M8.5 12Q10 5 15 4.5Q18 3 21 4.5Q26 5 27.5 12L27 22Q26 29 23.5 33H12.5Q10 29 9 22Z", fill: "M11.6 10.5Q18 8 24.4 10.5L24.2 19.5Q18 21.5 11.8 19.5Z",
    roots: ["M12.5 32H23.5Q23.6 52 22.2 73Q21.2 75 20.2 73Q19.2 56 18 47Q16.8 56 15.8 73Q14.8 75 13.8 73Q12.4 52 12.5 32Z"],
    canals: "M15 31Q14.6 52 14.8 71M21 31Q21.4 52 21.2 71", apex: [[14.8, 74], [21.2, 74]], spot: [18, 14]},
  molar: {crown: "M4.5 12Q5 5 10 4.5Q13.5 2.5 16.5 5Q18 3.5 19.5 5Q22.5 2.5 26 4.5Q31 5 31.5 12L31 21Q30 28 27.5 32H8.5Q6 28 5 21Z",
    fill: "M8.2 10.5Q18 8 27.8 10.5L27.4 19.5Q18 22 8.6 19.5Z",
    roots: ["M8.5 31H27.5Q28 38 26.8 45Q26.4 58 24.8 70Q23.8 72.5 22.8 70Q21.6 58 20.6 46Q19.6 41 18 41Q16.4 41 15.4 46Q14.4 58 13.2 70Q12.2 72.5 11.2 70Q9.6 58 9.2 45Q8 38 8.5 31Z"],
    canals: "M13 31Q11.6 52 12.2 68M23 31Q24.4 52 23.8 68", apex: [[12.2, 71.5], [23.8, 71.5]], spot: [14.5, 13]},
};
const TOOTH_PALATAL = "M15 37Q18 35 21 37Q21.4 58 19 77Q18 78.6 17 77Q14.6 58 15 37Z";
const TOOTH_SURF = {
  v: "M3.99 3.99A8.5 8.5 0 0 1 16.01 3.99L12.55 7.45A3.6 3.6 0 0 0 7.45 7.45Z",
  d: "M16.01 3.99A8.5 8.5 0 0 1 16.01 16.01L12.55 12.55A3.6 3.6 0 0 0 12.55 7.45Z",
  o: "M16.01 16.01A8.5 8.5 0 0 1 3.99 16.01L7.45 12.55A3.6 3.6 0 0 0 12.55 12.55Z",
  m: "M3.99 16.01A8.5 8.5 0 0 1 3.99 3.99L7.45 7.45A3.6 3.6 0 0 0 7.45 12.55Z",
};
/* status text -> what to draw; several statuses in one string ("кариес, пломба") all show.
   surf = {o|m|d|v|l: "Кариес" | "Пломба" | "Временная пломба"} — marks on single surfaces (2.9.0) */
function toothState(status, surf) {
  const s = String(status || "").toLowerCase(), sv = Object.values(surf || {});
  const pontic = /промежуточн|pontic/.test(s), canalFill = /канал\S* запломб|запломбирован\S* канал|obtur/.test(s);
  const openCanal = /эндо|депульп/.test(s) || (/канал/.test(s) && !canalFill);
  return {
    miss: /отсут|удал(ён|ен)|missing/.test(s) && !pontic, pontic, extract: /удалить|extract/.test(s), impl: /имплант|implant/.test(s),
    cap: /корон|мост|винир|crown|bridge/.test(s), bridge: /мост|bridge/.test(s),
    fill: /(^|[^а-яё])пломб|вкладк|fill/.test(s) || sv.some(x => /пломб/i.test(x)), caries: /кари|caries|разруш/.test(s) || sv.includes("Кариес"),
    endo: /пульп|периодон|депульп/.test(s) || openCanal, canal: openCanal, canalFill, post: /штифт|post/.test(s),
    perio: /периодон/.test(s), root: /корень|корни|root/.test(s), mobile: /подвиж/.test(s),
  };
}
function toothKind(n, upper) {
  const d = n % 10, milk = Math.floor(n / 10) >= 5;
  if (milk) return d >= 4 ? "molar" : d === 3 ? "canine" : "front";
  if (d >= 6) return "molar";
  if (d >= 4) return upper && d === 4 ? "pre2" : "pre";
  return d === 3 ? "canine" : "front";
}
function toothSvg(n, status, upper, surf) {
  const k = toothKind(n, upper), sh = TOOTH_SHAPES[k], t = toothState(status, surf);
  const wisdom = n % 10 === 8 && Math.floor(n / 10) < 5;
  const rootT = wisdom ? ` transform="translate(0 31) scale(1 .8) translate(0 -31)"` : "";
  let roots;
  if (t.impl) {
    const thr = []; for (let y = 38; y <= 68; y += 5) { const dx = (y - 32) / 38; thr.push(`M${(12.6 + dx).toFixed(1)} ${y}L${(23.4 - dx).toFixed(1)} ${y + 2}`); }
    roots = `<path class="t-imp" d="M12.5 31H23.5L22.5 70Q18 78 13.5 70Z"/><path class="t-imp-th" d="${thr.join("")}"/><rect class="t-imp" x="15" y="28" width="6" height="5" rx="1"/>`;
  } else if (t.pontic) {  /* bridge over a gap: no roots, only the crown */
    roots = (upper && k === "molar" ? `<path class="t-root t-lost" d="${TOOTH_PALATAL}"/>` : "") + sh.roots.map(d => `<path class="t-root t-lost" d="${d}"/>`).join("");
  } else {
    roots = (upper && k === "molar" ? `<path class="t-root t-pal" d="${TOOTH_PALATAL}"/>` : "") + sh.roots.map(d => `<path class="t-root" d="${d}"/>`).join("")
      + (t.canalFill ? `<path class="t-canal t-obt" d="${sh.canals}"/>` : t.canal ? `<path class="t-canal" d="${sh.canals}"/>` : "")
      + (t.post ? `<path class="t-post" d="M18 27V${k === "molar" ? 46 : 52}"/>` : "")
      + (t.perio ? sh.apex.map(([x, y]) => `<circle class="t-apex" cx="${x}" cy="${y}" r="3.4"/>`).join("") : "");
  }
  const crown = t.root ? `<path class="t-crown t-lost" d="${sh.crown}"/>`
    : `<path class="t-crown${t.cap ? " t-cap" : ""}" d="${sh.crown}"/>` + (t.fill && !t.cap ? `<path class="t-fil" d="${sh.fill}"/>` : "")
      + (t.caries ? `<ellipse class="t-car" cx="${sh.spot[0]}" cy="${sh.spot[1]}" rx="3.3" ry="2.7"/>` : "");
  const marks = (t.extract ? `<path class="t-x" d="M7 8L29 76M29 8L7 76"/>` : "") + (t.mobile ? `<path class="t-mob" d="M1.5 14Q0 20 1.5 26M34.5 14Q36 20 34.5 26"/>` : "");
  const cls = ["tooth-g", t.endo && !t.impl ? "is-endo" : "", t.miss ? "is-miss" : ""].filter(Boolean).join(" ");
  return `<svg class="${cls}" viewBox="0 0 36 86" width="32" height="76" aria-hidden="true"><g${upper ? ` transform="translate(0 86) scale(1 -1)"` : ""}>`
    + `<g${rootT}>${roots}</g>${crown}${marks}</g></svg>`;
}
/* surfaces of a tooth: o — chewing / cutting, m — mesial, d — distal, v — vestibular (lip, cheek), l — oral (tongue, palate) */
const SURF_NAMES = {o: "Жевательная (режущий край)", m: "Медиальная", d: "Дистальная", v: "Вестибулярная", l: "Язычная / нёбная"};
const SURF_SHORT = {o: "О", m: "М", d: "Д", v: "В", l: "Я"};
const SURF_STATES = ["Кариес", "Пломба", "Временная пломба"];
/* where each surface sits on the round scheme: the lip side faces up on upper teeth, down on lower;
   the mesial side faces the middle line (right on the patient's right quadrants, left on the left ones) */
function surfGeo(n, upper) {
  const q = Math.floor(n / 10) % 4, right = q === 1 || q === 0; /* 1x, 4x, 5x, 8x — the patient's right, shown on the left */
  return {v: upper ? "v" : "o", l: upper ? "o" : "v", m: right ? "d" : "m", d: right ? "m" : "d"};
}
const SURF_CLS = {"Кариес": "s-car", "Пломба": "s-fil", "Временная пломба": "s-tmp"};
function surfSvg(status, upper, surf, n, big) {
  const t = toothState(status), on = t.cap ? "s-cap" : "";
  const sz = big ? 64 : 15;
  if (surf && Object.keys(surf).length && n) {
    const g = surfGeo(n, upper), cls = k => SURF_CLS[surf[k]] || on;
    return `<svg class="surf${t.miss ? " is-miss" : ""}${big ? " big" : ""}" viewBox="0 0 20 20" width="${sz}" height="${sz}" aria-hidden="true">`
      + ["v", "d", "l", "m"].map(k => `<path class="s-p ${cls(k)}" data-s="${k}" d="${TOOTH_SURF[g[k]]}"/>`).join("")
      + `<circle class="s-p ${cls("o")}" data-s="o" cx="10" cy="10" r="3.6"/></svg>`;
  }
  const c = t.caries ? "s-car" : t.fill ? "s-fil" : on;
  if (n) { /* same markup with data-s, so the editor can click a surface of an unmarked tooth */
    const g = surfGeo(n, upper);
    return `<svg class="surf${t.miss ? " is-miss" : ""}${big ? " big" : ""}" viewBox="0 0 20 20" width="${sz}" height="${sz}" aria-hidden="true">`
      + ["v", "d", "l", "m"].map(k => `<path class="s-p ${on}" data-s="${k}" d="${TOOTH_SURF[g[k]]}"/>`).join("")
      + `<circle class="s-p ${c}" data-s="o" cx="10" cy="10" r="3.6"/></svg>`;
  }
  const sides = upper ? {v: "v", o: "o"} : {v: "o", o: "v"};
  const p = k => `<path class="s-p ${on}" d="${TOOTH_SURF[k]}"/>`;
  return `<svg class="surf${t.miss ? " is-miss" : ""}" viewBox="0 0 20 20" width="15" height="15" aria-hidden="true">`
    + `${p(sides.v)}${p("d")}${p(sides.o)}${p("m")}<circle class="s-p ${c}" cx="10" cy="10" r="3.6"/></svg>`;
}
/* "36: кариес (О, М)" — the surfaces in words for titles and documents */
function surfText(surf) {
  const by = {};
  Object.entries(surf || {}).forEach(([k, v]) => { if (v) (by[v] ||= []).push(SURF_SHORT[k] || k); });
  return Object.entries(by).map(([v, ks]) => `${v.toLowerCase()} (${ks.join(", ")})`).join(", ");
}
function toothCol(n, status, upper, extra, surf, badge) {
  const id = `<span class="ft-id"><b>${n}</b>${surfSvg(status, upper, surf, n)}</span>`;
  const st = [status, surfText(surf)].filter(Boolean).join("; ");
  return `<button class="ft${st ? " has" : ""}${extra ? " " + extra : ""}" data-n="${n}" title="${esc(n + (st ? ": " + st : ": не указано"))}">`
    + (badge ? `<i class="ft-b">${esc(badge)}</i>` : "")
    + `${upper ? toothSvg(n, status, true, surf) + id : id + toothSvg(n, status, false, surf)}</button>`;
}
/* opt.plan: teeth in a treatment plan (Set of strings), opt.sel: the tooth being edited,
   opt.surf: {tooth: {surface: state}}, opt.badge: {tooth: "1"} — stage numbers on the presentation */
function formulaHtml(map, milk, opt) {
  opt = opt || {};
  const U = milk ? [[55, 54, 53, 52, 51], [61, 62, 63, 64, 65]] : [[18, 17, 16, 15, 14, 13, 12, 11], [21, 22, 23, 24, 25, 26, 27, 28]];
  const L = milk ? [[85, 84, 83, 82, 81], [71, 72, 73, 74, 75]] : [[48, 47, 46, 45, 44, 43, 42, 41], [31, 32, 33, 34, 35, 36, 37, 38]];
  const plan = opt.plan || new Set(), surf = opt.surf || {}, badge = opt.badge || {};
  const br = n => toothState(map[String(n)] || "").bridge;
  const cell = (n, upper, prev, next) => toothCol(n, map[String(n)] || "", upper, [String(opt.sel) === String(n) ? "sel" : "", plan.has(String(n)) ? "plan" : "",
    br(n) && prev && br(prev) ? "br-l" : "", br(n) && next && br(next) ? "br-r" : ""].filter(Boolean).join(" "), surf[String(n)], badge[String(n)]);
  const row = (qs, upper) => { const all = qs[0].concat(qs[1]);
    return `<div class="f-row ${upper ? "up" : "lo"}">${qs.map((q, i) => `<div class="f-q ${i ? "r" : "l"}">${q.map(n => { const j = all.indexOf(n);
      return cell(n, upper, all[j - 1], all[j + 1]); }).join("")}</div>`).join("")}</div>`; };
  return `<div class="formula">${row(U, true)}<div class="f-mid"></div>${row(L, false)}</div>`;
}
function formulaLegend(withPlan) {
  const it = [["car", "Кариес"], ["fil", "Пломба"], ["tmp", "Временная пломба"], ["cap", "Коронка / мост"], ["endo", "Пульпит / каналы"], ["obt", "Каналы запломбированы"],
    ["imp", "Имплант"], ["miss", "Отсутствует"]];
  if (withPlan) it.push(["plan", "В плане лечения"]);
  return `<div class="legend f-legend">${it.map(([k, t]) => `<span><i class="lg-${k}"></i>${t}</span>`).join("")}</div>`;
}
/* tooth numbers mentioned in plan items ("36", "36, 37") */
function planTeeth(plans) {
  const out = new Set();
  (plans || []).forEach(i => (i.items || []).forEach(x => (String(x.tooth || "").match(/\b[1-8][1-8]\b/g) || []).forEach(m => out.add(m))));
  return out;
}

const ICON = {
  cal: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  rec: '<svg viewBox="0 0 24 24"><path d="M6 3.5h9l4 4v13H6z"/><path d="M9 12h7M9 15.5h5"/></svg>',
  inv: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M6 3.5h9l4 4v13H6z"/><path d="M14.5 3.5V8H19"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
};

function renderPatient(tab) {
  S.patientTab = tab;
  const p = P, d = p.data || {};
  const alerts = [];
  for (const [k, v] of Object.entries(d)) {
    if (typeof v !== "string" && typeof v !== "number") continue;
    const s = String(v).trim(); if (!s || /^(нет|no|none|-|—|0|не выявлено|отрицает)$/i.test(s)) continue;
    if (/allerg|аллерг/i.test(k)) alerts.push(`<span class="alert"><svg viewBox="0 0 24 24"><path d="M12 3 2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>Аллергия: ${esc(s)}</span>`);
    else if (/chronic|хрон|disease|заболев/i.test(k)) alerts.push(`<span class="alert w">${esc(label(k))}: ${esc(s)}</span>`);
  }
  if (p.questionnaire) for (const a of p.questionnaire.alerts) alerts.push(`<span class="alert${/^Аллерг/.test(a) ? "" : " w"}">Анкета: ${esc(a)}</span>`);
  if (p.local) alerts.push(`<span class="alert w">Пациент создан в программе — завести в Dentist Plus</span>`);
  let teeth = findTeeth(d);
  const tmap = {...(teeth ? teeth.map : {}), ...(p.teeth_local || {})};
  const extras = p.extras.filter(e => !isEmpty(e.data));
  const nowS = nowLocal();
  const past = p.visits.filter(v => v.start < nowS && stClass(v.status) !== "st-cancel");
  const next = p.visits.filter(v => v.start >= nowS && stClass(v.status) !== "st-cancel").slice(-1)[0];
  const docCount = {}; p.visits.forEach(v => { if (v.doctor_name) docCount[v.doctor_name] = (docCount[v.doctor_name] || 0) + 1; });
  const mainDoc = Object.entries(docCount).sort((a, b) => b[1] - a[1])[0];
  const invs = p.invoices.filter(i => i.kind !== "plan"), plans = p.invoices.filter(i => i.kind === "plan");
  const paidTotal = invs.reduce((a, i) => a + (+i.paid || 0), 0);
  const apiDebt = Number(get0(d, ["debt", "balance"]));
  const debt = Math.max(0, -p.balance_local) + (apiDebt < 0 ? -apiDebt : 0);
  const card = get0(d, ["card_number", "card", "medcard_number", "number"]) || (p.local ? "—" : p.id);
  const discount = get0(d, ["discount", "discount_percent"]);
  const gender = get0(d, ["gender", "sex"]);
  const invByVisit = {}; invs.forEach(i => { if (i.visit_id) (invByVisit[i.visit_id] ||= []).push(i); });
  const recByVisit = {}; p.records.forEach(r => { if (r.visit_id) recByVisit[r.visit_id] = r; });
  const ctx = {patient_id: p.id, doctor_id: (p.visits.find(v => v.start.slice(0, 10) === iso(new Date())) || p.visits[0] || {}).doctor_id};

  const tabs = [["visits", "Визиты", p.visits.length], ["formula", "Формула"], ["records", "Лечения", p.records.length],
    ["files", "Снимки и файлы", p.files_count || ""], ["perio", "Пародонтограмма", p.perio_count || ""], ["lab", "Лаборатория", p.lab_count || ""], ["crm", "CRM", p.crm_open || ""], ["payments", "Оплаты", invs.length],
    ["plans", "План лечения", plans.length], ["docs", "Документы", p.documents.length], ["notes", "Примечания", p.notes.length],
    ...extras.map(e => ["x:" + e.kind, label(e.kind), Array.isArray(e.data) ? e.data.length : ""]),
    ["personal", "Персональные данные"], ["feed", "Живая лента"]].filter(([k]) => {
    if (k === "formula" || k === "records" || k === "perio") return can("medcard_view");
    if (k === "files") return canAny("medcard_view", "patients_view");
    if (k === "lab") return canAny("lab", "billing", "accounting");
    if (k === "crm") return can("marketing");
    if (k === "payments" || k === "plans") return canAny("billing", "payments");
    if (k === "docs") return can("docs");
    return true;
  });
  if (!tabs.some(x => x[0] === tab)) tab = "visits";
  S.patientTab = tab;
  let body = "";
  const addBtn = (id, t) => `<div class="tab-tools"><button class="btn ghost small" id="${id}">${t}</button><span class="muted">${""}</span></div>`;
  const tr = x => x.transferred ? '<span class="pill st-done">в DP</span>' : '<span class="pill st-cancel">перенести</span>';

  if (tab === "visits") {
    body = addBtn("tAddVisit", "Добавить") + `<div class="muted cnt-line">Записей: ${p.visits.length}</div>` + (p.visits.length ? `<table class="tbl"><thead><tr><th>Визит</th><th>Статус</th><th>Услуги</th><th>Кресло</th><th>Филиал</th><th>Цена</th><th>Оплата</th><th>Действия</th></tr></thead><tbody>${
      p.visits.map(v => { const iv = invByVisit[v.id] || invByVisit[v.origin_id] || []; const sum = iv.reduce((a, i) => a + i.total, 0), paid = iv.reduce((a, i) => a + i.paid, 0);
        const rec = recByVisit[v.id] || recByVisit[v.origin_id];
        return `<tr data-v="${esc(v.id)}" class="${v.start >= nowS ? "future" : ""}"><td><b class="lnk">${fmtDT(v.start)}</b>${v.local ? '<i class="lc"></i>' : ""}<small class="muted" style="display:block">${esc(v.doctor_name || "")}</small></td>
          <td><span class="pill ${stClass(v.status)}">${esc(v.status || "—")}</span></td><td>${esc(v.title || "")}</td><td>${esc(v.chair || "")}</td><td>${esc(v.branch_name || "")}</td>
          <td>${sum ? money(sum) : "—"}</td><td>${sum ? `<span class="${paid >= sum ? "ok-t" : "bad-t"}">${money(paid)}</span>` : "—"}</td>
          <td class="acts"><button class="ia ${rec ? "on" : ""}" data-act="rec" data-v="${esc(v.id)}" data-r="${esc(rec ? rec.id : "")}" title="${rec ? "Открыть лечение" : "Провести лечение"}">${ICON.rec}</button>
            <button class="ia ${iv.length ? "on" : ""}" data-act="inv" data-v="${esc(v.id)}" data-i="${esc(iv[0] ? iv[0].id : "")}" title="Счёт / оплата">${ICON.inv}</button>
            <button class="ia" data-act="doc" data-v="${esc(v.id)}" title="Документ">${ICON.doc}</button></td></tr>`; }).join("")}</tbody></table>` : `<div class="empty"><b>Визитов в сохранённом периоде нет</b></div>`);
  } else if (tab === "formula") {
    S.milk = S.milk || false;
    body = `<div class="f-tools"><div class="seg"><button data-milk="0" class="${S.milk ? "" : "on"}">Постоянные зубы</button><button data-milk="1" class="${S.milk ? "on" : ""}">Молочные зубы</button></div>
      <span class="muted">Формула собирается из лечений и данных Dentist Plus. Щёлкните по зубу, чтобы провести лечение.</span></div>${formulaHtml(tmap, S.milk, {plan: planTeeth(plans), surf: p.surf_local || {}})}
      ${formulaLegend(true)}`;
  } else if (tab === "records") {
    body = addBtn("tAddRec", "Провести лечение") + (typeof dpDraft === "function" ? dpDraft("Перенесите запись в медкарту Dentist Plus — отметка «в DP» появится после переноса") : "") + (p.records.length ? p.records.map(r => {
      const dd = r.data || {}, dg = (dd.diagnoses || []).map(x => `${x.tooth ? x.tooth + ": " : ""}${x.code} ${x.title}`).join("; ");
      const src = dd.source || [], srcT = [src.includes("visit") ? "по записи приёма" : src.includes("dictation") ? "по диктовке" : "", src.includes("voice_formula") ? "формула голосом" : "", src.includes("ai") ? "с помощью ИИ" : ""].filter(Boolean).join(", ");
      return `<div class="rec" data-r="${esc(r.id)}"><div class="rec-h"><b>${fmtDate(r.date)}</b><span class="muted">${esc(r.doctor_name || "")}</span>${tr(r)}${srcT ? `<span class="pill src-pill" title="Как создана запись">${esc(srcT)}</span>` : ""}</div>
        ${dd.complaints ? `<div><span class="muted">Жалобы:</span> ${esc(dd.complaints)}</div>` : ""}
        ${dg ? `<div><span class="muted">Диагноз:</span> ${esc(dg)}</div>` : ""}
        ${dd.treatment ? `<div><span class="muted">Лечение:</span> ${esc(dd.treatment)}</div>` : ""}
        ${typeof dpRecTools === "function" ? dpRecTools(r) : ""}</div>`;
    }).join("") : `<div class="empty"><b>Лечений, проведённых в программе, пока нет</b><span>История из Dentist Plus — во вкладке «Персональные данные»</span></div>`);
  } else if (tab === "payments") {
    const pays = invs.flatMap(i => i.payments.map(x => ({...x, inv: i}))).concat((p.free_payments || []).map(x => ({...x, inv: null})))
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    body = addBtn("tAddInv", "Добавить счёт") + `<div class="muted cnt-line">Баланс по программе: <b class="${p.balance_local < 0 ? "bad-t" : ""}">${money(p.balance_local)}</b></div><div id="finPatient"></div>` +
      `<h4 class="sub-h">Оплаты</h4>` + (pays.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Счёт</th><th>Способ оплаты</th><th>Сумма</th><th>DP</th><th>Действия</th></tr></thead><tbody>${
        pays.map(x => !x.inv ? `<tr><td>${fmtDT(x.created_at)}</td><td class="muted">${x.amount < 0 ? "из аванса" : "аванс"}${x.comment ? ` <small>${esc(x.comment)}</small>` : ""}</td><td>${esc(typeof payLabel === "function" ? payLabel(x) : x.method)}</td><td><b class="${x.amount < 0 ? "bad-t" : ""}">${money(x.amount)}</b></td><td>${tr(x)}</td>
          <td class="acts">${can("payments") ? `<button class="linkbtn" data-delfree="${esc(x.id)}">удалить</button>` : ""}</td></tr>` : `<tr data-inv="${esc(x.inv.id)}"><td>${fmtDT(x.created_at)}</td><td class="lnk">от ${fmtDT(x.inv.created_at)}</td><td>${esc(typeof payLabel === "function" ? payLabel(x) : x.method)}</td><td><b class="${x.amount < 0 ? "bad-t" : ""}">${money(x.amount)}</b></td><td>${tr(x)}</td>
          <td class="acts"><button class="ia" data-receipt="${esc(x.inv.id)}" title="Квитанция">${ICON.doc}</button></td></tr>`).join("")}</tbody></table>` : `<div class="muted" style="padding:8px 16px">Оплат нет</div>`) +
      `<h4 class="sub-h">Счета</h4>` + (invs.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Услуги</th><th>Сумма</th><th>Оплачено</th><th>Статус</th></tr></thead><tbody>${
        invs.map(i => `<tr data-inv="${esc(i.id)}"><td>${fmtDT(i.created_at)}</td><td>${esc(i.items.map(x => x.title).join(", ").slice(0, 90))}</td><td><b>${money(i.total)}</b></td><td>${money(i.paid)}</td>
          <td><span class="pill ${i.status === "Оплачен" ? "st-ok" : "st-cancel"}">${esc(i.status)}</span></td></tr>`).join("")}</tbody></table>` : `<div class="muted" style="padding:8px 16px">Счетов нет</div>`);
  } else if (tab === "plans") {
    body = addBtn("tAddPlan", "Добавить") + `<div class="muted cnt-line">Записей: ${plans.length}</div>` + (plans.length ? `<table class="tbl"><thead><tr><th>Название</th><th>Этапы и зубы</th><th>Автор</th><th>Создан</th><th>Сумма</th><th>Статус</th></tr></thead><tbody>${
      plans.map(i => { const st = {}; i.items.forEach(x => (st[x.stage || "1"] ||= []).push(x.tooth));
        const vs = i.variants || [], ch = vs.find(v => v.key === i.variant);
        const vline = vs.length ? `<small class="muted" style="display:block">${ch ? "Выбран вариант «" + esc(ch.name) + "»" : "Варианты: " + vs.map(v => esc(v.name)).join(" / ")}</small>` : "";
        return `<tr data-inv="${esc(i.id)}"><td class="lnk"><b>${esc(i.title || "План лечения")}</b>${vline}</td><td>${Object.entries(st).map(([k, t]) => `<div>● Этап ${esc(k)} [ ${esc([...new Set(t.flatMap(x => String(x || "").split(/\s*,\s*/)).filter(Boolean))].join(", "))} ]</div>`).join("")}</td>
          <td>${esc(i.doctor_name || "")}</td><td>${fmtDate(i.created_at)}</td><td>${money(i.total)}</td><td>${typeof pstPill === "function" ? pstPill(i.plan_status || "Предварительный") : `<span class="pill ${/Актив/.test(i.plan_status) ? "st-cancel" : /заверш/.test(i.plan_status) ? "st-ok" : ""}">${esc(i.plan_status || "")}</span>`}</td></tr>`; }).join("")}</tbody></table>`
      : `<div class="empty"><b>Планов лечения нет</b><span>Составьте план, распечатайте его пациенту и выставляйте счета по этапам</span></div>`);
  } else if (tab === "docs") {
    body = addBtn("tAddDoc", "Создать документ") + (p.documents.length ? `<table class="tbl"><thead><tr><th>Документ</th><th>Создан</th><th>DP</th></tr></thead><tbody>${
      p.documents.map(x => `<tr data-doc="${esc(x.id)}"><td class="lnk"><b>${esc(x.title)}</b>${x.signed ? ' <span class="pill st-ok">подписан</span>' : ""}</td><td>${fmtDT(x.created_at)}</td><td>${tr(x)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Документов пока нет</b><span>Анкета, договор, согласия, план, акт, выписка, карта 043 — заполняются автоматически</span></div>`);
  } else if (tab === "notes") {
    body = `<div class="notes"><span class="muted">Примечания хранятся только на этом компьютере и в Dentist Plus не отправляются.</span>
      <textarea class="input" id="noteText" placeholder="Например: свет отключили — приём перенесли на 12.11 14:00"></textarea>
      <div><button class="btn" id="noteAdd">Добавить примечание</button></div>
      ${p.notes.map(n => `<div class="note"><button data-n="${n.id}" title="Удалить">×</button><small>${esc(n.created_at)}</small><div>${esc(n.text)}</div></div>`).join("")}</div>`;
  } else if (tab === "personal") {
    const skip = new Set(["id", teeth && teeth.key].filter(Boolean));
    const flat = Object.entries(d).filter(([k, v]) => !skip.has(k) && !isEmpty(v) && typeof v !== "object");
    body = `<dl class="kv">${flat.map(([k, v]) => kvRow(label(k), prim(v, k))).join("") || `<div class="muted">Нет данных</div>`}</dl>
      <h4 class="sub-h">Все данные из Dentist Plus</h4><div class="raw">${rawTree(Object.fromEntries(Object.entries(d).filter(([k, v]) => typeof v === "object")))}</div>`;
  } else if (tab === "feed") {
    const ev = [];
    p.visits.forEach(v => ev.push({at: v.start, icon: "visit", title: `Визит ${fmtDT(v.start)}`, st: v.status, lines: [`Врач: ${v.doctor_name || "—"}`, v.title ? `Услуги: ${v.title}` : "", v.chair ? `Кресло: ${v.chair}` : ""]}));
    p.records.forEach(r => { const dd = r.data || {}; ev.push({at: r.created_at, icon: "rec", title: "Лечение", lines: [`Врач: ${r.doctor_name || "—"}`, (dd.diagnoses || []).map(x => `${x.tooth ? x.tooth + ": " : ""}${x.code} ${x.title}`).join("; "), dd.treatment || ""]}); });
    invs.forEach(i => { ev.push({at: i.created_at, icon: "inv", title: `Счёт на ${money(i.total)}`, st: i.status, lines: [i.items.map(x => x.title).join(", ")]}); i.payments.forEach(x => ev.push({at: x.created_at, icon: "pay", title: `Оплата ${money(x.amount)}`, lines: [`Способ: ${x.method}`]})); });
    plans.forEach(i => ev.push({at: i.created_at, icon: "plan", title: `План лечения: ${i.title || ""}`, st: i.plan_status, lines: [`Сумма: ${money(i.total)}`]}));
    p.documents.forEach(x => ev.push({at: x.created_at, icon: "doc", title: `Документ: ${x.title}`, lines: []}));
    p.notes.forEach(n => ev.push({at: n.created_at, icon: "note", title: "Примечание", lines: [n.text]}));
    ev.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
    body = `<div class="feed">${ev.map(e => `<div class="fe"><div class="fe-at">${fmtDT(e.at)}</div><div class="fe-card fe-${e.icon}"><div class="fe-h"><b>${esc(e.title)}</b>${e.st ? `<span class="pill ${stClass(e.st)}">${esc(e.st)}</span>` : ""}</div>${
      e.lines.filter(Boolean).map(l => `<div>${esc(l)}</div>`).join("")}</div></div>`).join("") || `<div class="empty"><b>Событий нет</b></div>`}</div>`;
  } else if (tab === "files" || tab === "perio" || tab === "lab" || tab === "crm") {
    body = `<div id="${{files: "pfBody", perio: "perioBody", lab: "labPBody", crm: "crmPBody"}[tab]}"><div class="scan"><i></i>Загрузка…</div></div>`;
  } else if (tab.startsWith("x:")) {
    const e = extras.find(x => "x:" + x.kind === tab);
    const arr = Array.isArray(e.data) ? e.data : [e.data];
    const simple = arr.every(x => x && typeof x === "object" && Object.values(x).every(v => typeof v !== "object" || v === null));
    if (simple && arr.length) {
      const cols = [...new Set(arr.flatMap(Object.keys))].filter(c => !["id", "patient_id"].includes(c)).slice(0, 7);
      body = `<table class="tbl compact"><thead><tr>${cols.map(c => `<th>${esc(label(c))}</th>`).join("")}</tr></thead><tbody>${
        arr.map(r => `<tr>${cols.map(c => `<td>${esc(isEmpty(r[c]) ? "" : prim(r[c], c))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    } else body = `<div class="raw">${rawTree(e.data)}</div>`;
    body += `<div class="muted" style="padding:8px 16px;font-size:12px">Из Dentist Plus, синхронизировано ${fmtDT(e.synced_at)}</div>`;
  }

  const back = S.prevView === "schedule" ? "Календарь" : "Пациенты";
  $("#patientCard").innerHTML = `
    <div class="crumbs"><button class="linkbtn plain" id="backBtn">${back}</button> / <span>${esc(p.name)}</span>
      <div class="crumb-acts">
        ${can("patients_edit") ? `<button class="pill-btn" id="aEditP" title="Изменить ФИО, телефон, дату рождения">Изменить</button>` : ""}
        <button class="pill-btn" id="aAnketa">${ICON.doc}Анкета</button>
        <button class="pill-btn" id="aContract" data-official-doc title="${typeof addonDocKind === "function" && addonDocKind("doc_contract") === "official" ? esc(addonNote("official")) : "Договор"}">${ICON.doc}Договор</button>
        <button class="pill-btn" id="aBook" title="Записать на приём">${ICON.cal}Записать</button>
        <button class="btn" id="aPay" title="Счёт и оплата: неоплаченный счёт или новый">${ICON.inv}Принять оплату</button>
        <div class="dd right" id="ddPrint"><button class="dd-btn pill-btn">Печать<svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"/></svg></button>
          <div class="dd-menu"><button data-tpl="doc_card043" data-official-doc>Медкарта 043/у<i class="dp-doc-tag">из DP</i></button><button data-tpl="doc_extract" data-official-doc>Выписка из медкарты<i class="dp-doc-tag">из DP</i></button><button data-tpl="doc_consent_treatment" data-official-doc>Согласие на лечение<i class="dp-doc-tag">из DP</i></button><button data-tpl="doc_consent_pd" data-official-doc>Согласие на обработку ПД<i class="dp-doc-tag">из DP</i></button><button data-tpl="">Другой документ…</button><button id="aTax" data-official-doc>Справка для налогового вычета<i class="dp-doc-tag">из DP</i></button></div></div>
        <div class="dd right" id="ddAdd"><button class="dd-btn btn">Добавить<svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"/></svg></button>
          <div class="dd-menu"><button data-add="visit">Визит</button><button data-add="rec">Лечение (запись в медкарту)</button><button data-add="plan">План лечения</button><button data-add="inv">Счёт</button><button data-add="doc">Документ</button><button data-add="note">Примечание</button></div></div>
      </div></div>
    <div class="phead2">
      <div class="ph-main"><span class="av lg">${esc(initials(p.name))}</span><div>
        <h2>${esc(p.name)}</h2>
        <div class="ph-lines">${gender ? `<div>${esc(gender)}</div>` : ""}${p.birth ? `<div>Лет: ${age(p.birth)} (${esc(fmtDate(p.birth))})</div>` : ""}${p.phone ? `<div class="lnk">${esc(p.phone)}</div>` : ""}</div></div></div>
      <div class="ph-col"><dt>Номер карточки</dt><dd>${esc(card)}</dd><dt>Статус</dt><dd>${p.local ? "Новый (создан в программе)" : "Из Dentist Plus"}</dd><dt>Лечащий врач</dt><dd>${esc(mainDoc ? mainDoc[0] : "—")}</dd><dt>Откуда пришёл</dt><dd>${canAny("marketing", "patients_edit") ? `<button class="linkbtn" id="aSource">${esc((p.marketing && p.marketing.source) || "указать")}</button>` : esc((p.marketing && p.marketing.source) || "—")}${p.marketing && p.marketing.no_calls ? ' <span class="pill st-cancel">не звонить</span>' : ""}</dd></div>
      <div class="ph-col"><dt>Всего оплачено (в программе)</dt><dd>${money(paidTotal)}</dd><dt>Скидка</dt><dd>${discount ? esc(discount) + "%" : "—"}</dd><dt>Карта обновлена</dt><dd>${fmtDT(p.detail_synced_at || p.synced_at)}</dd></div>
      <div class="ph-col"><dt>Последний визит</dt><dd>${past[0] ? fmtDT(past[0].start) : "—"}</dd><dt>Следующий визит</dt><dd>${next ? fmtDT(next.start) : "—"}</dd><dt>Долг</dt><dd class="${debt ? "bad-t" : ""}">${debt ? money(debt) : "—"}</dd></div>
    </div>
    ${alerts.length ? `<div class="alerts">${alerts.join("")}</div>` : ""}
    <div class="tabs">${tabs.map(([k, t, c]) => `<button class="tab ${k === tab ? "on" : ""}" data-t="${esc(k)}">${esc(t)}${c ? `<span class="cnt">${c}</span>` : ""}</button>`).join("")}</div>
    <div class="pbody">${body}</div>`;

  if (tab === "files" && typeof loadPatientFiles === "function") loadPatientFiles(p);
  if (tab === "perio" && typeof loadPerio === "function") loadPerio(p);
  if (tab === "lab" && typeof loadPatientLab === "function") loadPatientLab(p);
  if (tab === "crm" && typeof loadPatientCrm === "function") loadPatientCrm(p);
  if (typeof loyaltyHeader === "function") loyaltyHeader(p);
  if (typeof finHeader === "function") finHeader(p);
  if (tab === "payments" && typeof finPatientTab === "function") finPatientTab(p);
  if (typeof aiPatientCard === "function") aiPatientCard(p, tab);  // 2.13: record check, consent, voice note, drafts
  // hide what this employee may not do
  const hideIf = (sel, cond) => $$(sel, $("#patientCard")).forEach(el => { if (cond) el.remove(); });
  hideIf("#aAnketa, #aContract, #ddPrint, #tAddDoc, [data-add=doc], .ia[data-act=doc], [data-receipt]", !can("docs"));
  hideIf("#aPay, .ia[data-act=inv]", !canAny("billing", "payments"));
  hideIf("#aTax", !canAny("payments", "docs"));
  hideIf("[data-add=inv], [data-add=plan], #tAddInv, #tAddPlan", !can("billing"));
  hideIf("[data-add=rec], #tAddRec", !can("medcard_edit"));
  hideIf(".ia[data-act=rec]", !can("medcard_view"));
  hideIf("[data-add=visit], #tAddVisit, #aBook", !can("schedule_edit"));
  hideIf("[data-add=note], #noteText, #noteAdd, .note button", !can("patients_edit"));
  if (!$$("#ddAdd [data-add]").length) hideIf("#ddAdd", true);
  const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };
  on("#backBtn", () => show(S.prevView === "schedule" ? "schedule" : "patients"));
  $$("#patientCard .tab").forEach(b => b.onclick = () => renderPatient(b.dataset.t));
  $$("#patientCard .dd").forEach(dd => { $(".dd-btn", dd).onclick = e => { e.stopPropagation(); const o = dd.classList.contains("open"); $$(".dd.open").forEach(x => x.classList.remove("open")); if (!o) dd.classList.add("open"); }; });
  const book = () => openBooking({patient_id: p.id, patient_name: p.name, start: `${S.day} ${pad(Math.min(20, new Date().getHours() + 1))}:00`});
  const actions = {visit: book, rec: () => openRecord({...ctx, date: iso(new Date())}), plan: () => openInvoice({...ctx, kind: "plan"}),
    inv: () => openInvoice(ctx), doc: () => openDocPicker(ctx), note: () => renderPatient("notes")};
  $$("#ddAdd [data-add]").forEach(b => b.onclick = () => actions[b.dataset.add]());
  $$("#ddPrint [data-tpl]").forEach(b => b.onclick = () => b.dataset.tpl ? openDocFill({...ctx, template_id: b.dataset.tpl}) : openDocPicker(ctx));
  on("#aTax", () => typeof openTaxCert === "function" && openTaxCert(p));
  on("#aAnketa", () => typeof openQuestionnaire === "function" ? openQuestionnaire(p) : openDocFill({...ctx, template_id: "doc_anketa"}));
  on("#aContract", () => openDocFill({...ctx, template_id: "doc_contract"}));
  on("#aSource", () => editPatientSource(p, () => openPatient(p.id, S.prevView)));
  on("#aEditP", () => openEditPatient(p, d));
  on("#aBook", () => actions.visit());
  on("#aPay", () => { const unpaid = invs.find(i => i.status !== "Оплачен"); openInvoice(unpaid ? {patient_id: p.id, id: unpaid.id} : ctx); });
  on("#tAddVisit", book); on("#tAddRec", actions.rec); on("#tAddInv", actions.inv); on("#tAddPlan", actions.plan); on("#tAddDoc", actions.doc);
  $$("#patientCard tr[data-v]").forEach(el => el.onclick = e => { if (!e.target.closest(".ia")) openVisit(el.dataset.v); });
  $$("#patientCard .ia[data-act]").forEach(b => b.onclick = e => { e.stopPropagation(); const v = p.visits.find(x => x.id === b.dataset.v) || {};
    if (b.dataset.act === "rec") openRecord(b.dataset.r ? {patient_id: p.id, id: b.dataset.r} : {patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id, date: v.start.slice(0, 10)});
    if (b.dataset.act === "inv") openInvoice(b.dataset.i ? {patient_id: p.id, id: b.dataset.i} : {patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id});
    if (b.dataset.act === "doc") openDocPicker({patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id}); });
  $$("#patientCard [data-receipt]").forEach(b => b.onclick = e => { e.stopPropagation(); openDocFill({...ctx, template_id: "doc_receipt", invoice_id: b.dataset.receipt}); });
  $$("#patientCard .rec").forEach(el => el.onclick = () => openRecord({patient_id: p.id, id: el.dataset.r}));
  if (typeof dpBindRecTools === "function") dpBindRecTools($("#patientCard"), () => openPatient(p.id, S.prevView, "records"));
  $$("#patientCard tr[data-doc]").forEach(el => el.onclick = () => openDocument(el.dataset.doc));
  $$("#patientCard tr[data-inv]").forEach(el => el.onclick = () => openInvoice({patient_id: p.id, id: el.dataset.inv}));
  $$("#patientCard [data-milk]").forEach(b => b.onclick = () => { S.milk = b.dataset.milk === "1"; renderPatient("formula"); });
  if (can("medcard_edit")) $$("#patientCard .ft").forEach(b => b.onclick = () => openRecord({...ctx, date: iso(new Date()), tooth: b.dataset.n}));
  const add = $("#noteAdd");
  if (add) add.onclick = async () => { P.notes = await api.add_note(P.id, $("#noteText").value); renderPatient("notes"); };
  $$(".note button").forEach(b => b.onclick = async () => { if (await ask("Удалить примечание?", {danger: true, ok: "Удалить"})) { P.notes = await api.delete_note(P.id, +b.dataset.n); renderPatient("notes"); } });
}
function get0(o, keys) { for (const k of keys) if (o && o[k] !== undefined && o[k] !== null && o[k] !== "") return o[k]; return ""; }

/* ------------------------------------------------------------ settings */
/* Fill the Dentist Plus fields from get_settings(). parts: "conn" (connection), "store" («Что хранить»), "expert"
   («Для специалиста»). After a save only the saved parts are filled, so unsaved edits in other panels stay. */
function fillDpSettings(s, parts = ["conn", "store", "expert"]) {
  S.settings = s;
  if (parts.includes("conn")) {
    $("#sDemo").checked = !!s.demo; $("#sLogin").value = s.login || ""; $("#sPass").value = "";
    $("#sPass").placeholder = s.has_password ? "сохранён — оставьте пустым" : "введите пароль";
    $("#sBase").value = s.base_url;
  }
  if (parts.includes("store")) {
    $("#sBack").value = s.days_back; $("#sFwd").value = s.days_forward; $("#sInt").value = s.interval_min;
    $("#sDs").value = s.day_start; $("#sDe").value = s.day_end; $("#sAllPat").checked = !!s.sync_all_patients; $("#sAuto").checked = !!s.autostart;
  }
  if (parts.includes("expert")) {
    $("#sFromP").value = s.visit_from_param; $("#sToP").value = s.visit_to_param; $("#sChunk").value = s.chunk_days; $("#sPer").value = s.per_page;
    $("#sExtras").value = JSON.stringify(s.patient_extras, null, 1);
    $("#sWriteMap").value = s.write_map && Object.keys(s.write_map).length ? JSON.stringify(s.write_map, null, 1) : "";
  }
  loadDpMain();
  $("#dataDir").textContent = "Данные: " + s.data_dir;
  $("#histTable tbody").innerHTML = s.history.map(h => `<tr><td>${fmtDT(h.finished)}</td><td class="${h.ok ? "ok-t" : "bad-t"}">${esc(h.message)}</td><td>${h.counts.visits ?? "—"}</td><td>${h.counts.patients ?? "—"}</td></tr>`).join("")
    || `<tr><td colspan="4" class="muted">Ещё не было</td></tr>`;
}
async function loadSettings() {
  const s = await api.get_settings();
  fillDpSettings(s);
  (s.transfer_mode === "auto" ? $("#tmAuto") : $("#tmManual")).checked = true;
  $$(".mode-card").forEach(c => c.classList.toggle("on", c.querySelector("input").checked));
  $("#verLbl").textContent = "Версия " + (S.status.version || "");
  loadFiscalSettings();
  loadVoiceSettings();
  if (typeof loadBackupSettings === "function") loadBackupSettings();
  if (typeof loadSecuritySettings === "function") loadSecuritySettings();
  if (typeof loadFilesSettings === "function") loadFilesSettings();
  if (typeof loadTabletSettings === "function") loadTabletSettings();
  if (typeof loadMoneySettings === "function") loadMoneySettings();
  if (typeof loadPlatformSettings === "function") loadPlatformSettings();
  if (typeof loadAddonPanel === "function") { loadAddonPanel(); applyAddon(); }
  if (typeof loadDpSettings === "function") loadDpSettings();  // 3.3: the sections of the copy for Dentist Plus, the reminder
  if (typeof loadDaySettings === "function") loadDaySettings();
  api.network_info().then(n => {
    $("#netBox").innerHTML = (typeof netClinicHtml === "function" ? netClinicHtml(n.clinic) : "")
      + (n.urls.length ? `Адрес этого компьютера в сети: ${n.urls.map(u => `<code>${esc(u)}</code>`).join(" или ")}`
      : "Компьютер не подключён к сети — другие компьютеры его не видят.") + (n.public ? `<div class="warn-line" style="margin-top:6px">${NET_PUBLIC_HINT}</div>` : "");
    if (typeof netClinicBind === "function") netClinicBind(n.clinic);
  }).catch(() => {});
}
/* 3.7.2: only one computer of the clinic talks to Dentist Plus (one API login: a new login logs the other one out) */
async function loadDpMain() {
  const box = $("#dpMainBox"); if (!box) return;
  let m; try { m = await api.dp_main_status(); } catch (e) { box.innerHTML = ""; return; }
  if (!m.in_network) { box.innerHTML = ""; return; }
  let html;
  if (m.role === "main") html = `<div class="ok-line">С Dentist Plus обменивается <b>этот компьютер</b>. Остальные компьютеры клиники получают данные Dentist Plus от него по сети клиники и сами к API не подключаются.</div>`;
  else if (m.role === "follower") html = `<div class="warn-line">С Dentist Plus обменивается компьютер <b>«${esc(m.name)}»</b>${m.online === false ? " — сейчас он не в сети клиники, поэтому данные Dentist Plus здесь не обновляются" : ""}. Этот компьютер получает данные от него и сам к API не подключается: у клиники один логин API, и второй вход отключил бы первый компьютер.</div>
    <div class="row"><button class="btn ghost" id="dpMainClaim">Обмен с Dentist Plus ведёт этот компьютер</button></div>`;
  else html = `<div class="hint">Обмениваться с Dentist Plus будет первый компьютер сети клиники, на котором указан логин API.</div>`;
  box.innerHTML = html;
  const b = $("#dpMainClaim");
  if (b) b.onclick = async () => {
    if (!(await ask("Перенести обмен с Dentist Plus на этот компьютер?", {ok: "Перенести",
      text: `Компьютер «${m.name}» перестанет подключаться к Dentist Plus, а этот начнёт и будет передавать данные остальным. Выбирайте компьютер, который включён весь рабочий день. На этом компьютере должны быть указаны логин и пароль API.`}))) return;
    try { await api.dp_main_claim(); toast("Обмен с Dentist Plus теперь ведёт этот компьютер"); } catch (e) { toast(e.message || String(e), "bad"); }
    loadDpMain(); refreshStatus();
  };
}
$$('input[name="tmode"]').forEach(r => r.onchange = async () => {
  const mode = r.value;
  if (mode === "auto" && !(await ask("Включить автоматическую отправку в Dentist Plus?", {icon: "warn", ok: "Включить", text: "Новые пациенты и записи (создание, перенос, статус, отмена) будут уходить в Dentist Plus сами, как только появится интернет.\n\nСначала проверьте на одной тестовой записи, что всё приходит правильно."}))) {
    $("#tmManual").checked = true; return;
  }
  await api.save_settings({transfer_mode: mode});
  S.settings.transfer_mode = mode;
  $$(".mode-card").forEach(c => c.classList.toggle("on", c.querySelector("input").checked));
  toast(mode === "auto" ? "Автоматическая отправка включена" : "Перенос вручную по списку");
  refreshStatus();
});
/* 3.7.2: the demo switch acts at once (before, it waited for «Сохранить и синхронизировать» and seemed not to work) */
$("#sDemo").onchange = async () => {
  const box = $("#sDemo"), demo = box.checked;
  if (demo === !!S.settings.demo) return;
  msgBox = "#sMsg";
  if (!demo && !$("#sLogin").value.trim()) { box.checked = true; return msg("Чтобы выключить демо-режим, укажите логин API", false); }
  if (!(await ask(demo ? "Включить демо-режим?" : "Выключить демо-режим?", {icon: "warn", ok: demo ? "Включить" : "Выключить",
    text: demo ? "Сохранённые реальные данные будут удалены с этого компьютера (заметки останутся). Программа перестанет подключаться к Dentist Plus." : "Тестовые данные будут удалены, начнётся загрузка из Dentist Plus."}))) {
    box.checked = !demo; return;
  }
  box.disabled = true;
  try {
    const s = await api.save_settings(demo ? {demo} : {demo, login: $("#sLogin").value.trim(), password: $("#sPass").value});
    msg(demo ? "Демо-режим включён" : "Демо-режим выключен, загружаем данные из Dentist Plus", true);
    toast(demo ? "Демо-режим включён" : "Демо-режим выключен");
    S.lastLoaded = "x";
    fillDpSettings(s, ["conn"]); refreshStatus();  // only the connection fields: the other panels keep their unsaved edits
  } catch (e) {
    box.checked = !demo;
    const t = String(e.message || e).replace(/^Error:\s*/, "");
    msg("Не удалось: " + t, false); toast(t, true);
  }
  box.disabled = false;
};
$("#sWriteMapDef").onclick =async () => { $("#sWriteMap").value = JSON.stringify(await api.write_map_default(), null, 1); };
let msgBox = "#sMsg";   // the message line next to the button that was pressed
function msg(t, ok) {
  for (const id of ["#sMsg", "#sMsg2"]) { const m = $(id); if (m) { m.textContent = id === msgBox ? t : ""; m.className = "msg " + (ok ? "ok" : "bad"); } }
}
const STORE_NUMS = [["#sBack", "Дней назад"], ["#sFwd", "Дней вперёд"], ["#sInt", "Обновлять каждые, мин"],
  ["#sDs", "Рабочий день, начало"], ["#sDe", "Рабочий день, конец"]];
const EXPERT_NUMS = [["#sChunk", "Размер окна запроса, дней"], ["#sPer", "Записей на страницу"]];
/* the first empty or non-numeric number field: its message (and the focus), before the server is asked */
function badNumber(fields) {
  for (const [id, name] of fields) {
    const el = $(id), v = el.value.trim();
    const t = (el.validity && el.validity.badInput) || (v && !/^-?\d+$/.test(v)) ? `Поле «${name}»: укажите целое число`
      : !v ? `Заполните поле «${name}»` : "";
    if (t) { const d = el.closest("details"); if (d) d.open = true; el.focus(); return t; }
  }
  return "";
}
const storeFields = () => ({days_back: $("#sBack").value, days_forward: $("#sFwd").value, interval_min: $("#sInt").value,
  day_start: $("#sDs").value, day_end: $("#sDe").value, sync_all_patients: $("#sAllPat").checked, autostart: $("#sAuto").checked});
// 3.7.2: a computer that takes the Dentist Plus data from the main one has no API login on purpose
const dpFollower = () => !!(S.status && S.status.dp_main && S.status.dp_main.role === "follower");
$("#sSave").onclick = () => { msgBox = "#sMsg"; return saveSettings(); };
// «Что хранить» saves only its own fields: no API login check (followers have none) and no JSON of «Для специалиста»
$("#sSave2").onclick = async () => {
  msgBox = "#sMsg2";
  const bad = badNumber(STORE_NUMS);
  if (bad) return msg(bad, false);
  $("#sSave").disabled = $("#sSave2").disabled = true;
  try {
    const s = await api.save_settings(storeFields());
    msg("Сохранено", true);
    S.lastLoaded = "x";  // the working hours change the schedule grid
    fillDpSettings(s, ["store"]); refreshStatus();
  } catch (e) { msg("Не удалось сохранить: " + errText(e), false); }
  $("#sSave").disabled = $("#sSave2").disabled = false;
};
async function saveSettings() {
  const bad = badNumber([...STORE_NUMS, ...EXPERT_NUMS]);
  if (bad) return msg(bad, false);
  let extras;
  try { extras = JSON.parse($("#sExtras").value || "[]"); } catch (e) { return msg("Ошибка в JSON доп. разделов", false); }
  let writeMap;
  try { writeMap = JSON.parse($("#sWriteMap").value.trim() || "{}"); } catch (e) { return msg("Ошибка в JSON настроек записи в Dentist Plus", false); }
  const demo = $("#sDemo").checked;
  if (!demo && !dpFollower() && !$("#sLogin").value.trim()) return msg("Укажите логин или включите демо-режим", false);
  if (demo !== !!S.settings.demo && !(await ask(demo ? "Включить демо-режим?" : "Выключить демо-режим?", {icon: "warn", ok: demo ? "Включить" : "Выключить", text: demo ? "Сохранённые реальные данные будут удалены с этого компьютера (заметки останутся)." : "Тестовые данные будут удалены, начнётся загрузка из Dentist Plus."}))) return;
  $("#sSave").disabled = $("#sSave2").disabled = true;
  try {
    const s = await api.save_settings({demo, login: $("#sLogin").value.trim(), password: $("#sPass").value, base_url: $("#sBase").value.trim(),
      ...storeFields(), visit_from_param: $("#sFromP").value.trim(),
      visit_to_param: $("#sToP").value.trim(), chunk_days: $("#sChunk").value, per_page: $("#sPer").value, patient_extras: extras,
      write_map: writeMap});
    msg("Сохранено. Синхронизация запущена.", true);
    S.lastLoaded = "x";
    fillDpSettings(s); refreshStatus();  // only the Dentist Plus fields: the other panels keep their unsaved edits
  } catch (e) { msg("Не удалось сохранить: " + errText(e), false); }
  $("#sSave").disabled = $("#sSave2").disabled = false;
}
$("#sTest").onclick = async () => {
  msgBox = "#sMsg";
  msg("Проверяем…", true);
  try {
    const r = await api.test_connection($("#sLogin").value.trim(), $("#sPass").value, $("#sBase").value.trim());
    msg(r.message, r.ok);
  } catch (e) { msg("Не удалось проверить: " + errText(e), false); }
};
$("#sDiag").onclick = async () => {
  const o = $("#diagOut"); o.hidden = false; o.textContent = "Запрашиваем API…";
  try { o.textContent = await api.diagnostics(); } catch (e) { o.textContent = "Не удалось получить диагностику: " + errText(e); }
};
$("#openDir").onclick = () => api.open_data_dir();
let devRepText = "";
$("#devRep").onclick = async () => {
  const b = $("#devRep"), m = $("#devRepMsg");
  b.disabled = true; m.className = "msg ok"; m.textContent = "Собираем отчёт…";
  try {
    const r = await api.dev_report();
    if (!r.ok) { m.className = "msg bad"; m.textContent = r.message; return; }
    devRepText = r.text;
    m.textContent = (r.on_desktop ? "Файл сохранён на рабочем столе: " : "Файл сохранён: ") + r.name
      + ". Отправьте его разработчику в Telegram.";
    $("#devRepShow").hidden = false; $("#devRepCopy").hidden = false;
  } catch (e) { m.className = "msg bad"; m.textContent = "Не удалось создать отчёт: " + e; }
  finally { b.disabled = false; }
};
$("#devRepShow").onclick = async () => { if (!(await api.show_dev_report())) toast("Файл не найден", true); };
$("#devRepCopy").onclick = async () => {
  try { await navigator.clipboard.writeText(devRepText); toast("Текст отчёта скопирован"); }
  catch { toast("Не удалось скопировать, отправьте файл", true); }
};
$("#netFw").onclick = async () => {
  const pw = window.pywebview && window.pywebview.api;
  if (!pw || !pw.allow_firewall || !/^(127\.0\.0\.1|localhost)$/.test(location.hostname)) return toast("Откройте настройки в программе на компьютере-сервере", true);
  $("#netMsg").textContent = "Windows попросит подтвердить…"; $("#netMsg").className = "msg ok";
  let r;
  try { r = await pw.allow_firewall(); } catch (e) { r = {ok: false, err: errText(e)}; }
  $("#netMsg").textContent = r.ok ? "Готово: другие компьютеры клиники могут подключаться" : r.err ? "Не получилось: " + r.err : "Не получилось — подтвердите запрос Windows";
  $("#netMsg").className = "msg " + (r.ok ? "ok" : "bad");
};

/* ------------------------------------------------------------ keyboard */
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "k" || e.code === "KeyK")) { e.preventDefault(); $("#gSearch").focus(); $("#gSearch").select(); return; }
  if (e.key === "Escape") {  // 3.9: Esc closes the dialog first (asks when something was typed), then the visit panel, then the card
    if (!$("#modal").hidden) { if (!document.querySelector(".ask-wrap")) requestCloseModal(); return; }
    if ($("#drawer").classList.contains("open")) closeDrawer(); else if (S.view === "patient") $("#backBtn").click();
  }
  if (S.view === "schedule" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
    if (e.key === "ArrowLeft") $("#prevDay").click();
    if (e.key === "ArrowRight") $("#nextDay").click();
  }
});

/* ---------------------------------------------------------------- boot */
let started = false;
async function startApp(user) {
  ME = user;
  if (window.DDTheme) DDTheme.useFor(ME.login);
  $("#authScreen").hidden = true;
  $("#ucAv").textContent = initials(ME.name); $("#ucName").textContent = ME.name;
  $("#ucRole").textContent = ME.role_title || ME.position || "";
  applyPerms();
  $("#ucServer").hidden = !(window.pywebview && window.pywebview.api && window.pywebview.api.open_setup);
  try { Object.assign(S.settings, await api.ui_settings()); } catch (e) {}
  if (typeof applyAddon === "function") applyAddon();  // 3.2: «Надстройка над Dentist Plus»
  REF = null;
  await refreshStatus();
  show(ME.role === "director" && can("reports") ? "director" : can("schedule_view") ? "schedule" : firstView());
  if (can("staff")) refreshStaffBadge();
  startOfflineCopies();
  if (typeof aiStart === "function") aiStart();  // 2.13: the assistant in the corner
  if (!started) {
    started = true;
    setInterval(() => { if (ME) refreshStatus(); }, 3000);
    setInterval(() => { if (ME && S.view === "schedule" && S.mode === "grid" && S.day === iso(new Date())) loadDay(); }, 60000);
    setInterval(() => { if (ME && can("staff")) refreshStaffBadge(); }, 30000);
  }
}
function applyPerms() {
  $$("[data-perm]").forEach(el => el.hidden = !can(el.dataset.perm));
  $$("[data-perm-any]").forEach(el => el.hidden = !canAny(...el.dataset.permAny.split(",")));
  document.body.classList.toggle("no-export", !can("export"));  // 2.14: «Excel» buttons only with the right
}
function needLogin(message) {
  if (!ME && !$("#authScreen").hidden) return;
  ME = null; TOKEN = ""; sessionStorage.removeItem(SESSION_KEY);
  if (typeof aiStop === "function") aiStop();
  closeModal(); if (typeof closeDrawer === "function" && $("#drawer").classList.contains("open")) closeDrawer();
  showLogin(message && !/Войдите/.test(message) ? message : "Сеанс завершён — войдите снова");
}
let veilTimer = null;
function lostServer() {
  if (serverLost) return;
  serverLost = true; $("#offlineVeil").hidden = false;
  $("#veilSetup").hidden = !(window.pywebview && window.pywebview.api && window.pywebview.api.open_setup);
  const pwb = window.pywebview && window.pywebview.api;
  $("#veilOffline").hidden = true;
  if (pwb && pwb.offline_available) pwb.offline_available().then(l => { $("#veilOffline").hidden = !l.length; }).catch(() => {});
  veilTimer = setInterval(async () => {
    try { const r = await fetch("/ping", {cache: "no-store"}); if (r.ok) foundServer(); }
    catch (e) { const pw = window.pywebview && window.pywebview.api; if (pw && pw.reconnect) pw.reconnect(); }
  }, 5000);
}
function foundServer() { serverLost = false; $("#offlineVeil").hidden = true; clearInterval(veilTimer); }
$("#veilSetup").onclick = () => window.pywebview.api.open_setup();
$("#veilOffline").onclick = () => window.pywebview.api.open_offline();

/* client computers keep an encrypted read-only copy of the schedule and cards for server outages */
let offlineTimer = null;
async function saveOfflineCopy() {
  const pw = window.pywebview && window.pywebview.api;
  if (!ME || !pw || !pw.offline_save || serverLost) return;
  try {
    if (!(await pw.is_client())) return;
    const snap = await api.offline_snapshot();
    await pw.offline_save(ME.login, JSON.stringify(snap));
  } catch (e) { /* next attempt in 10 minutes */ }
}
function startOfflineCopies() { clearInterval(offlineTimer); setTimeout(saveOfflineCopy, 5000); offlineTimer = setInterval(saveOfflineCopy, 10 * 60 * 1000); }

/* theme: Settings panel and the user menu; theme.js applies it before the first paint */
function syncThemeSeg() {
  const p = window.DDTheme ? DDTheme.get() : "system";
  $$("[data-theme-seg] button").forEach(b => b.classList.toggle("on", b.dataset.tp === p));
}
$$("[data-theme-seg] button").forEach(b => b.onclick = e => { e.stopPropagation(); if (window.DDTheme) DDTheme.set(b.dataset.tp, ME && ME.login); });
$$(".um-theme").forEach(el => el.onclick = e => e.stopPropagation());
document.addEventListener("dd-theme", syncThemeSeg);
syncThemeSeg();
$("#ucBtn").onclick = e => { e.stopPropagation(); $("#ucMenu").hidden = !$("#ucMenu").hidden; };
document.addEventListener("click", () => { $("#ucMenu").hidden = true; });
$("#ucOut").onclick = async () => { try { await authApi.logout(); } catch (e) {} ME = null; TOKEN = ""; sessionStorage.removeItem(SESSION_KEY); showLogin(); };
$("#ucServer").onclick = () => window.pywebview.api.open_setup();
$("#ucPass").onclick = () => {
  const box = modal(`<div class="m-h"><h3>Смена пароля</h3><button class="x" data-close>×</button></div>
    <div class="m-b auth-form"><label>Текущий пароль<input class="input" type="password" id="cpOld" autofocus></label>
    <label>Новый пароль (от 6 символов)<input class="input" type="password" id="cpNew"></label>
    <label>Повторите новый пароль<input class="input" type="password" id="cpNew2"></label><div class="auth-err" id="cpErr"></div></div>
    <div class="m-f"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="cpOk">Сменить</button></div>`);
  $("#cpOk", box).onclick = async () => {
    if ($("#cpNew").value !== $("#cpNew2").value) return $("#cpErr").textContent = "Новые пароли не совпадают";
    try { await authApi.change_password($("#cpOld").value, $("#cpNew").value); closeModal(); toast("Пароль изменён"); }
    catch (e) { $("#cpErr").textContent = errText(e); }
  };
};

/* sign-in, registration and the very first (director) account */
let AUTH_STATE = null;
async function showLogin(note) { try { AUTH_STATE = await authApi.state(); } catch (e) {} renderAuth("login", note); }
function brandHead() {
  const b = (S.status && S.status.brand) || {short: "DD", sub: "offline", name: "Dental Desk"};
  return `<div class="auth-brand"><span class="brandmark"><b>${esc(b.short)}</b><i></i><small>${esc(b.sub)}</small></span>
    <div><div class="ab-t">${esc(b.name)}</div><div class="ab-s">Программа для клиники</div></div></div>`;
}
function renderAuth(mode, note) {
  const st = AUTH_STATE || {roles: []};
  const box = $("#authBox");
  $("#authScreen").hidden = false;
  if (mode === "bootstrap") {
    box.innerHTML = brandHead() + `<h2>Добро пожаловать</h2>
      <p class="lead">Создайте учётную запись директора. Директор одобряет заявки сотрудников и назначает им роли и права.</p>
      <form class="auth-form" id="af"><label>ФИО<input class="input" id="aName" autofocus required></label>
      <div class="auth-row"><label>Логин<input class="input" id="aLogin" autocomplete="username" required></label>
      <label>Должность<input class="input" id="aPos" value="Директор"></label></div>
      <label>Пароль (от 6 символов)<input class="input" type="password" id="aPass" autocomplete="new-password" required></label>
      <label>Повторите пароль<input class="input" type="password" id="aPass2" autocomplete="new-password" required></label>
      <div class="auth-err" id="aErr"></div><button class="btn">Создать и войти</button></form>`;
  } else if (mode === "register") {
    box.innerHTML = brandHead() + `<h2>Заявка на доступ</h2>
      <p class="lead">После отправки директор увидит заявку и назначит вам права. Затем войдите со своим логином и паролем.</p>
      <form class="auth-form" id="af"><label>ФИО<input class="input" id="aName" autofocus required></label>
      <div class="auth-row"><label>Логин<input class="input" id="aLogin" autocomplete="username" required></label>
      <label>Должность<select class="input" id="aRole">${st.roles.filter(r => r.key !== "director").map(r => `<option value="${r.key}">${esc(r.title)}</option>`).join("")}</select></label></div>
      <label>Пароль (от 6 символов)<input class="input" type="password" id="aPass" autocomplete="new-password" required></label>
      <label>Повторите пароль<input class="input" type="password" id="aPass2" autocomplete="new-password" required></label>
      <div class="auth-err" id="aErr"></div><button class="btn">Отправить заявку</button></form>
      <div class="auth-switch">Уже есть доступ? <button id="toLogin">Войти</button></div>`;
  } else if (!st.has_users) {
    box.innerHTML = brandHead() + `<h2>Программа ещё не настроена</h2>
      <p class="lead">Учётную запись директора нужно создать на компьютере-сервере. После этого здесь можно будет войти или подать заявку.</p>
      <button class="btn ghost" id="retry" style="width:100%;justify-content:center">Проверить снова</button>`;
  } else {
    box.innerHTML = brandHead() + `<h2>Вход</h2><p class="lead">Войдите под своей учётной записью.</p>
      <form class="auth-form" id="af"><label>Логин<input class="input" id="aLogin" autocomplete="username" autofocus required></label>
      <label>Пароль<input class="input" type="password" id="aPass" autocomplete="current-password" required></label>
      <div class="auth-ok" id="aOk">${esc(note && /отправлена|изменён/.test(note) ? note : "")}</div>
      <div class="auth-err" id="aErr">${esc(note && !/отправлена|изменён/.test(note) ? note : "")}</div><button class="btn">Войти</button></form>
      ${st.has_pins ? `<button class="btn ghost pin-entry" id="toPin" type="button">Вход по ПИН-коду</button>` : ""}
      <div class="auth-switch">Новый сотрудник? <button id="toReg">Подать заявку</button></div>`;
  }
  const f = $("#af", box), err = t => { $("#aErr").textContent = t; };
  const tl = $("#toLogin", box); if (tl) tl.onclick = () => renderAuth("login");
  const tr = $("#toReg", box); if (tr) tr.onclick = () => renderAuth("register");
  const rt = $("#retry", box); if (rt) rt.onclick = boot;
  const tp = $("#toPin", box); if (tp) tp.onclick = () => renderPinLogin();
  setTimeout(() => { const a = box.querySelector("[autofocus]"); if (a) a.focus(); }, 30);
  if (!f) return;
  f.onsubmit = async e => {
    e.preventDefault();
    const btn = f.querySelector(".btn"); btn.disabled = true;
    try {
      if (mode !== "login" && $("#aPass").value !== $("#aPass2").value) throw new Error("Пароли не совпадают");
      if (mode === "register") {
        const r = await authApi.register({name: $("#aName").value, login: $("#aLogin").value, role: $("#aRole").value,
          position: $("#aRole").selectedOptions[0].textContent, password: $("#aPass").value});
        renderAuth("login", r.message); return;
      }
      const r = mode === "bootstrap"
        ? await authApi.bootstrap({name: $("#aName").value, login: $("#aLogin").value, position: $("#aPos").value, password: $("#aPass").value})
        : await authApi.login($("#aLogin").value, $("#aPass").value);
      TOKEN = r.token; sessionStorage.setItem(SESSION_KEY, TOKEN);
      const pwBridge = window.pywebview && window.pywebview.api;
      if (pwBridge && pwBridge.offline_remember) pwBridge.offline_remember($("#aLogin").value, $("#aPass").value).catch(() => {});
      startApp(r.user);
    } catch (ex) { err(errText(ex)); btn.disabled = false; }
  };
}

async function boot() {
  let st;
  try { st = await authApi.state(); } catch (e) { setTimeout(boot, 4000); return; }
  AUTH_STATE = st;
  S.status = {...S.status, brand: st.brand};
  applyBrand(st.brand);
  if (st.user) return startApp(st.user);
  if (st.has_pins && typeof renderPinLogin === "function") return renderPinLogin();  // shared computer: pick yourself, type the PIN
  renderAuth(st.can_bootstrap ? "bootstrap" : "login");
}
boot();
