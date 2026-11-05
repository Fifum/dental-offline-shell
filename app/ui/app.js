"use strict";
/* ---------------------------------------------------------------- bridge */
const api = new Proxy({}, {
  get: (_, name) => (...args) => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) return window.pywebview.api[name](...args);
    return fetch("/api/" + name, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(args)})
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || "Ошибка"); return j; });
  }
});
const errText = e => String((e && (e.message || e)) || "Ошибка").replace(/^Error:\s*/, "");

/* ------------------------------------------------------- modal & toast */
function modal(html, {wide = false, onClose} = {}) {
  const box = $("#modalBox");
  box.className = "modal" + (wide ? " wide" : "");
  box.innerHTML = html;
  $("#modal").hidden = false;
  box._onClose = onClose;
  const f = box.querySelector("[autofocus]"); if (f) setTimeout(() => f.focus(), 30);
  box.querySelectorAll("[data-close]").forEach(b => b.onclick = closeModal);
  return box;
}
function closeModal() { const box = $("#modalBox"); $("#modal").hidden = true; box.innerHTML = ""; if (box._onClose) box._onClose(); }
document.getElementById("modal").addEventListener("mousedown", e => { if (e.target.id === "modal") closeModal(); });
let toastT;
function toast(t, bad) { const el = $("#toast"); el.textContent = t; el.className = "toast" + (bad ? " bad" : ""); el.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => el.hidden = true, 3200); }
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
function show(view) {
  S.view = view;
  $$(".view").forEach(v => v.hidden = v.id !== "view-" + view);
  $$(".nav").forEach(b => b.classList.toggle("active", b.dataset.view === view || (view === "patient" && b.dataset.view === "patients")));
  if (view === "schedule") loadDay();
  if (view === "patients") { searchPatients(); setTimeout(() => $("#patSearch").focus(), 30); }
  if (view === "settings") loadSettings();
  if (view === "cash") loadCash();
  if (view === "journal") loadJournal();
  if (view === "refs") loadRefs();
}
$$(".nav").forEach(b => b.onclick = () => show(b.dataset.view));

/* -------------------------------------------------------------- status */
async function refreshStatus() {
  let st;
  try { st = await api.status(); } catch (e) { return; }
  S.status = st;
  if (st.brand && !S.brandSet) { S.brandSet = true; document.title = st.brand.name;
    $(".brandmark b").textContent = st.brand.short; $(".brandmark small").textContent = st.brand.sub; $(".rail .logo").title = st.brand.name; }
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
  } else { dot.classList.add("on"); title.textContent = "Онлайн"; sub.textContent = `Обновлено ${ago(st.last_ok)}`; }
  $("#syncBtn").disabled = !!st.running;
  for (const id of ["#pendingBadge", "#pendingBadge2"]) { const pb = $(id); pb.hidden = !st.pending; pb.textContent = st.pending || ""; }
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
  const res = {visits: [], doctors: results[0].doctors, branches: results[0].branches, perDay: results.map((r, i) => ({day: days[i], visits: r.visits}))};
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
  const perDay = res.perDay.map(pd => ({day: pd.day, cols: buildColumns(pd.visits, doctors, pd.day)}));
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
      const sub = c.chair ? [...new Set(c.items.map(x => x.doctor_name).filter(Boolean))].slice(0, 2).join(", ") : (first ? `${hm(first)} – ${hm(lastE)}` : "нет записей");
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
      // hatched time outside working hours
      if (ws * 60 > top) lines += `<div class="off-hours" style="top:0;height:${(ws * 60 - top) * PX}px"></div>`;
      if (we < h1) lines += `<div class="off-hours" style="top:${(we * 60 - top) * PX}px;height:${(h1 - we) * 60 * PX}px"></div>`;
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
        evs += `<div class="ev ${stClass(v.status)} ${v.local ? "is-local" : ""}" data-id="${esc(v.id)}" title="${esc((v.patient_name || "") + " · " + (v.status || "") + (v.local ? " · изменено в программе" : ""))}" style="--dc:${dc};top:${(v._s - top) * PX + 1}px;height:${hgt}px;left:calc(${w * v._lane}% + 4px);right:auto;width:calc(${w}% - 8px)">
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
  const slot = +S.settings.slot_min || 15;
  const minuteAt = (col, e) => { const y = e.clientY - col.getBoundingClientRect().top; return Math.floor((+col.dataset.top + y / PX) / slot) * slot; };
  $$(".g-col", grid).forEach(col => {
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
    || `<div class="muted" style="padding:10px 12px">Не найдено. <button class="linkbtn" id="gsNew">Добавить пациента</button></div>`;
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
    <label class="fl">Адрес<input class="input" id="npA"></label><label class="fl">Комментарий<input class="input" id="npC"></label></div>
    <div class="m-f"><span class="muted">Пациент будет добавлен в список «Перенести в DP»</span><button class="btn ghost" data-close>Отмена</button>
      <button class="btn ghost" id="npSaveBook">Сохранить и записать</button><button class="btn" id="npSave">Сохранить</button></div>`);
  const save = async () => {
    if (!$("#npL", box).value.trim() || !$("#npF", box).value.trim()) { toast("Укажите фамилию и имя", true); return null; }
    return api.create_patient({lname: $("#npL", box).value, fname: $("#npF", box).value, mname: $("#npM", box).value, phone: $("#npPh", box).value,
      birth_date: $("#npB", box).value, gender: $("#npG", box).value, address: $("#npA", box).value, comment: $("#npC", box).value});
  };
  $("#npSave", box).onclick = async () => { const p = await save(); if (!p) return; closeModal(); toast("Пациент добавлен"); refreshStatus(); openPatient(p.id, S.view === "patient" ? S.prevView : S.view); };
  $("#npSaveBook", box).onclick = async () => { const p = await save(); if (!p) return; closeModal(); refreshStatus();
    openBooking({patient_id: p.id, patient_name: p.name, start: `${S.day} ${pad(Math.min(20, new Date().getHours() + 1))}:00`}); };
}
$("#tbAddPatient").onclick = () => openNewPatient();
$("#tbJournal").onclick = () => show("journal");

/* ---------------------------------------------------------- visit drawer */
async function openVisit(id) {
  const v = await api.visit(id);
  if (!v) return;
  const raw = v.data || {};
  $("#drawer").innerHTML = `<div class="dw-h"><button class="x" onclick="closeDrawer()">×</button>
      <span class="pill ${stClass(v.status)}">${esc(v.status || "Без статуса")}</span>
      <h3>${esc(v.patient_name || "Пациент #" + (v.patient_id || "?"))}</h3>
      <div class="muted">${fmtDate(v.start)}, ${hm(v.start)}–${hm(v.end)}</div></div>
    <div class="dw-b"><dl class="kv" style="grid-template-columns:1fr">
      ${kvRow("Врач", v.doctor_name)}${kvRow("Филиал", v.branch_name)}${kvRow("Телефон пациента", v.patient_phone)}${kvRow("Услуга / комментарий", v.title)}${kvRow("Комментарий", v.comment)}
    </dl>${Object.keys(raw).length ? `<div class="raw">${rawTree(raw, 0, ["id", "patient_id", "doctor_id", "branch_id", "start", "end", "status", "title"])}</div>` : ""}</div>
    ${v.local ? `<div class="local-note">Изменено в этой программе: <b>${esc({create: "новая запись", edit: "изменение", move: "перенос", cancel: "отмена", status: "смена статуса"}[v.action] || "изменение")}</b>. Нужно перенести в Dentist Plus.
       ${v.origin_id ? `<button class="linkbtn" id="dwRevert">Вернуть как в Dentist Plus</button>` : ""}</div>` : ""}
    <div class="dw-f">
      <div class="dw-actions">
        <button class="btn ghost small" data-st="Пришёл">Пришёл</button>
        <button class="btn ghost small" data-st="Завершён">Завершён</button>
        <button class="btn ghost small" data-st="Не пришёл">Не пришёл</button>
        <button class="btn ghost small danger" data-st="Отменён">Отменить</button>
        <button class="btn ghost small" id="dwEdit">Перенести / изменить</button>
      </div>
      ${v.patient_id ? `<div class="dw-actions">
        <button class="btn small" id="dwRec">Медкарта: заполнить приём${v.records && v.records.length ? " ✓" : ""}</button>
        <button class="btn ghost small" id="dwInv">Счёт${v.invoices && v.invoices.length ? " ✓" : ""}</button>
        <button class="btn ghost small" id="dwDoc">Документ</button>
        <button class="btn ghost small" id="dwCard">Карта пациента</button></div>` : ""}
    </div>`;
  const dw = $("#drawer");
  $$("[data-st]", dw).forEach(b => b.onclick = async () => {
    if (b.dataset.st === "Отменён" && !confirm("Отменить запись?")) return;
    await api.set_visit_status(v.id, b.dataset.st); toast(`Статус: ${b.dataset.st}`); closeDrawer(); afterChange();
  });
  $("#dwEdit", dw).onclick = () => { closeDrawer(); openBooking(v); };
  const rv = $("#dwRevert", dw); if (rv) rv.onclick = async () => { if (confirm("Убрать изменения, сделанные в программе, и показать запись как в Dentist Plus?")) { await api.revert_visit(v.id); closeDrawer(); afterChange(); } };
  if (v.patient_id) {
    $("#dwRec", dw).onclick = () => { closeDrawer(); openRecord({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id, date: v.start.slice(0, 10), id: (v.records[0] || {}).id}); };
    $("#dwInv", dw).onclick = () => { closeDrawer(); openInvoice({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id, id: (v.invoices[0] || {}).id}); };
    $("#dwDoc", dw).onclick = () => { closeDrawer(); openDocPicker({patient_id: v.patient_id, visit_id: v.id, doctor_id: v.doctor_id}); };
    $("#dwCard", dw).onclick = () => { closeDrawer(); openPatient(v.patient_id, "schedule"); };
  }
  $("#scrim").hidden = false;
  setTimeout(() => $("#drawer").classList.add("open"), 10);
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

/* --- tooth glyphs for the formula tab (simple own drawings) --- */
function toothSvg(n, status, upper) {
  const s = String(status || "").toLowerCase();
  const kind = n % 10 >= 6 ? "molar" : n % 10 >= 4 ? "pre" : "front";
  const missing = /отсут|удал(ён|ен)/.test(s);
  const crownFill = /корон|мост|винир|вкладк/.test(s) ? "#F2A93B" : /имплант/.test(s) ? "#9AD4CC" : "#FFFFFF";
  const rootFill = /имплант/.test(s) ? "#7C8A96" : /пульп|периодон|эндо|канал/.test(s) ? "#B49AE6" : "#F4F1EA";
  const w = 34, crown = kind === "molar" ? "M5 4h24q3 0 3 4v10q0 4-4 4H6q-4 0-4-4V8q0-4 3-4z" : kind === "pre" ? "M8 4h18q3 0 3 4v10q0 4-4 4H9q-4 0-4-4V8q0-4 3-4z" : "M10 4h14q3 0 3 4v10q0 4-4 4H11q-4 0-4-4V8q0-4 3-4z";
  const roots = kind === "molar" ? "M7 22l2 26h5l2-22M18 22l2 26h5l2-26" : kind === "pre" ? "M11 22l3 28h6l3-28" : "M12 22l3 30h4l3-30";
  const marks = [];
  if (/кари/.test(s)) marks.push(`<circle cx="17" cy="12" r="3.6" fill="#D9534F"/>`);
  if (/пломб/.test(s)) marks.push(`<rect x="12" y="8" width="10" height="8" rx="2" fill="#4B7BE5"/>`);
  if (/корень/.test(s)) marks.push(`<path d="M8 8h18" stroke="#D9534F" stroke-width="2"/>`);
  if (/удалить/.test(s)) marks.push(`<path d="M6 6l22 40M28 6L6 46" stroke="#D9534F" stroke-width="2.2"/>`);
  if (/подвиж/.test(s)) marks.push(`<path d="M2 30h4M28 30h4" stroke="#E39B2D" stroke-width="2"/>`);
  const g = `<g opacity="${missing ? 0.22 : 1}"><path d="${roots}" fill="${rootFill}" stroke="#9AA6B2" stroke-width="1.2"/>
    <path d="${crown}" fill="${crownFill}" stroke="#9AA6B2" stroke-width="1.2"/>${marks.join("")}</g>${missing ? '<path d="M8 20h18" stroke="#9AA6B2" stroke-dasharray="3 2"/>' : ""}`;
  return `<svg viewBox="0 0 ${w} 54" width="${w}" height="54"><g transform="${upper ? `translate(0 54) scale(1 -1)` : ""}">${g}</g></svg>`;
}
function formulaHtml(map, milk) {
  const U = milk ? [[55, 54, 53, 52, 51], [61, 62, 63, 64, 65]] : [[18, 17, 16, 15, 14, 13, 12, 11], [21, 22, 23, 24, 25, 26, 27, 28]];
  const L = milk ? [[85, 84, 83, 82, 81], [71, 72, 73, 74, 75]] : [[48, 47, 46, 45, 44, 43, 42, 41], [31, 32, 33, 34, 35, 36, 37, 38]];
  const cell = (n, upper) => { const st = map[String(n)] || ""; return `<button class="ft ${st ? "has" : ""}" data-n="${n}" title="${esc(n + (st ? ": " + st : ""))}">
      ${upper ? toothSvg(n, st, true) + `<b>${n}</b>` : `<b>${n}</b>` + toothSvg(n, st, false)}<small>${esc(st ? st.slice(0, 9) : "")}</small></button>`; };
  const row = (qs, upper) => `<div class="f-row">${qs.map((q, i) => `<div class="f-q ${i ? "r" : "l"}">${q.map(n => cell(n, upper)).join("")}</div>`).join("")}</div>`;
  return `<div class="formula">${row(U, true)}<div class="f-mid"></div>${row(L, false)}</div>`;
}

const ICON = {
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

  const tabs = [["visits", "Визиты", p.visits.length], ["formula", "Формула"], ["records", "Лечения", p.records.length], ["payments", "Оплаты", invs.length],
    ["plans", "План лечения", plans.length], ["docs", "Документы", p.documents.length], ["notes", "Примечания", p.notes.length],
    ...extras.map(e => ["x:" + e.kind, label(e.kind), Array.isArray(e.data) ? e.data.length : ""]),
    ["personal", "Персональные данные"], ["feed", "Живая лента"]];
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
      <span class="muted">Формула собирается из лечений и данных Dentist Plus. Щёлкните по зубу, чтобы провести лечение.</span></div>${formulaHtml(tmap, S.milk)}
      <div class="legend"><span><i style="background:#D9534F"></i>Кариес</span><span><i style="background:#4B7BE5"></i>Пломба</span><span><i style="background:#F2A93B"></i>Коронка / мост</span>
      <span><i style="background:#B49AE6"></i>Пульпит / каналы</span><span><i style="background:#9AD4CC"></i>Имплант</span><span><i style="background:#E9EDF1"></i>Отсутствует</span></div>`;
  } else if (tab === "records") {
    body = addBtn("tAddRec", "Провести лечение") + (p.records.length ? p.records.map(r => {
      const dd = r.data || {}, dg = (dd.diagnoses || []).map(x => `${x.tooth ? x.tooth + ": " : ""}${x.code} ${x.title}`).join("; ");
      return `<div class="rec" data-r="${esc(r.id)}"><div class="rec-h"><b>${fmtDate(r.date)}</b><span class="muted">${esc(r.doctor_name || "")}</span>${tr(r)}</div>
        ${dd.complaints ? `<div><span class="muted">Жалобы:</span> ${esc(dd.complaints)}</div>` : ""}
        ${dg ? `<div><span class="muted">Диагноз:</span> ${esc(dg)}</div>` : ""}
        ${dd.treatment ? `<div><span class="muted">Лечение:</span> ${esc(dd.treatment)}</div>` : ""}</div>`;
    }).join("") : `<div class="empty"><b>Лечений, проведённых в программе, пока нет</b><span>История из Dentist Plus — во вкладке «Персональные данные»</span></div>`);
  } else if (tab === "payments") {
    const pays = invs.flatMap(i => i.payments.map(x => ({...x, inv: i})));
    body = addBtn("tAddInv", "Добавить счёт") + `<div class="muted cnt-line">Баланс по программе: <b class="${p.balance_local < 0 ? "bad-t" : ""}">${money(p.balance_local)}</b></div>` +
      `<h4 class="sub-h">Оплаты</h4>` + (pays.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Счёт</th><th>Способ оплаты</th><th>Сумма</th><th>DP</th><th>Действия</th></tr></thead><tbody>${
        pays.map(x => `<tr data-inv="${esc(x.inv.id)}"><td>${fmtDT(x.created_at)}</td><td class="lnk">от ${fmtDT(x.inv.created_at)}</td><td>${esc(x.method)}</td><td><b>${money(x.amount)}</b></td><td>${tr(x)}</td>
          <td class="acts"><button class="ia" data-receipt="${esc(x.inv.id)}" title="Квитанция">${ICON.doc}</button></td></tr>`).join("")}</tbody></table>` : `<div class="muted" style="padding:8px 16px">Оплат нет</div>`) +
      `<h4 class="sub-h">Счета</h4>` + (invs.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Услуги</th><th>Сумма</th><th>Оплачено</th><th>Статус</th></tr></thead><tbody>${
        invs.map(i => `<tr data-inv="${esc(i.id)}"><td>${fmtDT(i.created_at)}</td><td>${esc(i.items.map(x => x.title).join(", ").slice(0, 90))}</td><td><b>${money(i.total)}</b></td><td>${money(i.paid)}</td>
          <td><span class="pill ${i.status === "Оплачен" ? "st-ok" : "st-cancel"}">${esc(i.status)}</span></td></tr>`).join("")}</tbody></table>` : `<div class="muted" style="padding:8px 16px">Счетов нет</div>`);
  } else if (tab === "plans") {
    body = addBtn("tAddPlan", "Добавить") + `<div class="muted cnt-line">Записей: ${plans.length}</div>` + (plans.length ? `<table class="tbl"><thead><tr><th>Название</th><th>Этапы и зубы</th><th>Автор</th><th>Создан</th><th>Сумма</th><th>Статус</th></tr></thead><tbody>${
      plans.map(i => { const st = {}; i.items.forEach(x => (st[x.stage || "1"] ||= []).push(x.tooth));
        return `<tr data-inv="${esc(i.id)}"><td class="lnk"><b>${esc(i.title || "План лечения")}</b></td><td>${Object.entries(st).map(([k, t]) => `<div>● Этап ${esc(k)} [ ${esc(t.filter(Boolean).join(", "))} ]</div>`).join("")}</td>
          <td>${esc(i.doctor_name || "")}</td><td>${fmtDate(i.created_at)}</td><td>${money(i.total)}</td><td><span class="pill ${/Актив/.test(i.plan_status) ? "st-cancel" : /заверш/.test(i.plan_status) ? "st-ok" : ""}">${esc(i.plan_status || "")}</span></td></tr>`; }).join("")}</tbody></table>`
      : `<div class="empty"><b>Планов лечения нет</b><span>Составьте план, распечатайте его пациенту и выставляйте счета по этапам</span></div>`);
  } else if (tab === "docs") {
    body = addBtn("tAddDoc", "Создать документ") + (p.documents.length ? `<table class="tbl"><thead><tr><th>Документ</th><th>Создан</th><th>DP</th></tr></thead><tbody>${
      p.documents.map(x => `<tr data-doc="${esc(x.id)}"><td class="lnk"><b>${esc(x.title)}</b></td><td>${fmtDT(x.created_at)}</td><td>${tr(x)}</td></tr>`).join("")}</tbody></table>`
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
        <button class="pill-btn" id="aAnketa">${ICON.doc}Анкета</button>
        <button class="pill-btn" id="aContract">${ICON.doc}Договор</button>
        <button class="pill-btn" id="aPay">${ICON.inv}Оплата</button>
        <div class="dd right" id="ddPrint"><button class="dd-btn pill-btn">Печать<svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"/></svg></button>
          <div class="dd-menu"><button data-tpl="doc_card043">Медкарта 043/у</button><button data-tpl="doc_extract">Выписка из медкарты</button><button data-tpl="doc_consent_treatment">Согласие на лечение</button><button data-tpl="doc_consent_pd">Согласие на обработку ПД</button><button data-tpl="">Другой документ…</button></div></div>
        <div class="dd right" id="ddAdd"><button class="dd-btn btn">Добавить<svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"/></svg></button>
          <div class="dd-menu"><button data-add="visit">Визит</button><button data-add="rec">Лечение (запись в медкарту)</button><button data-add="plan">План лечения</button><button data-add="inv">Счёт</button><button data-add="doc">Документ</button><button data-add="note">Примечание</button></div></div>
      </div></div>
    <div class="phead2">
      <div class="ph-main"><span class="av lg">${esc(initials(p.name))}</span><div>
        <h2>${esc(p.name)}</h2>
        <div class="ph-lines">${gender ? `<div>${esc(gender)}</div>` : ""}${p.birth ? `<div>Лет: ${age(p.birth)} (${esc(fmtDate(p.birth))})</div>` : ""}${p.phone ? `<div class="lnk">${esc(p.phone)}</div>` : ""}</div></div></div>
      <div class="ph-col"><dt>Номер карточки</dt><dd>${esc(card)}</dd><dt>Статус</dt><dd>${p.local ? "Новый (создан в программе)" : "Из Dentist Plus"}</dd><dt>Лечащий врач</dt><dd>${esc(mainDoc ? mainDoc[0] : "—")}</dd></div>
      <div class="ph-col"><dt>Всего оплачено (в программе)</dt><dd>${money(paidTotal)}</dd><dt>Скидка</dt><dd>${discount ? esc(discount) + "%" : "—"}</dd><dt>Карта обновлена</dt><dd>${fmtDT(p.detail_synced_at || p.synced_at)}</dd></div>
      <div class="ph-col"><dt>Последний визит</dt><dd>${past[0] ? fmtDT(past[0].start) : "—"}</dd><dt>Следующий визит</dt><dd>${next ? fmtDT(next.start) : "—"}</dd><dt>Долг</dt><dd class="${debt ? "bad-t" : ""}">${debt ? money(debt) : "—"}</dd></div>
    </div>
    ${alerts.length ? `<div class="alerts">${alerts.join("")}</div>` : ""}
    <div class="tabs">${tabs.map(([k, t, c]) => `<button class="tab ${k === tab ? "on" : ""}" data-t="${esc(k)}">${esc(t)}${c ? `<span class="cnt">${c}</span>` : ""}</button>`).join("")}</div>
    <div class="pbody">${body}</div>`;

  const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };
  on("#backBtn", () => show(S.prevView === "schedule" ? "schedule" : "patients"));
  $$("#patientCard .tab").forEach(b => b.onclick = () => renderPatient(b.dataset.t));
  $$("#patientCard .dd").forEach(dd => { $(".dd-btn", dd).onclick = e => { e.stopPropagation(); const o = dd.classList.contains("open"); $$(".dd.open").forEach(x => x.classList.remove("open")); if (!o) dd.classList.add("open"); }; });
  const book = () => openBooking({patient_id: p.id, patient_name: p.name, start: `${S.day} ${pad(Math.min(20, new Date().getHours() + 1))}:00`});
  const actions = {visit: book, rec: () => openRecord({...ctx, date: iso(new Date())}), plan: () => openInvoice({...ctx, kind: "plan"}),
    inv: () => openInvoice(ctx), doc: () => openDocPicker(ctx), note: () => renderPatient("notes")};
  $$("#ddAdd [data-add]").forEach(b => b.onclick = () => actions[b.dataset.add]());
  $$("#ddPrint [data-tpl]").forEach(b => b.onclick = () => b.dataset.tpl ? openDocFill({...ctx, template_id: b.dataset.tpl}) : openDocPicker(ctx));
  on("#aAnketa", () => openDocFill({...ctx, template_id: "doc_anketa"}));
  on("#aContract", () => openDocFill({...ctx, template_id: "doc_contract"}));
  on("#aPay", () => { const unpaid = invs.find(i => i.status !== "Оплачен"); openInvoice(unpaid ? {patient_id: p.id, id: unpaid.id} : ctx); });
  on("#tAddVisit", book); on("#tAddRec", actions.rec); on("#tAddInv", actions.inv); on("#tAddPlan", actions.plan); on("#tAddDoc", actions.doc);
  $$("#patientCard tr[data-v]").forEach(el => el.onclick = e => { if (!e.target.closest(".ia")) openVisit(el.dataset.v); });
  $$("#patientCard .ia[data-act]").forEach(b => b.onclick = e => { e.stopPropagation(); const v = p.visits.find(x => x.id === b.dataset.v) || {};
    if (b.dataset.act === "rec") openRecord(b.dataset.r ? {patient_id: p.id, id: b.dataset.r} : {patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id, date: v.start.slice(0, 10)});
    if (b.dataset.act === "inv") openInvoice(b.dataset.i ? {patient_id: p.id, id: b.dataset.i} : {patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id});
    if (b.dataset.act === "doc") openDocPicker({patient_id: p.id, visit_id: v.id, doctor_id: v.doctor_id}); });
  $$("#patientCard [data-receipt]").forEach(b => b.onclick = e => { e.stopPropagation(); openDocFill({...ctx, template_id: "doc_receipt", invoice_id: b.dataset.receipt}); });
  $$("#patientCard .rec").forEach(el => el.onclick = () => openRecord({patient_id: p.id, id: el.dataset.r}));
  $$("#patientCard tr[data-doc]").forEach(el => el.onclick = () => openDocument(el.dataset.doc));
  $$("#patientCard tr[data-inv]").forEach(el => el.onclick = () => openInvoice({patient_id: p.id, id: el.dataset.inv}));
  $$("#patientCard [data-milk]").forEach(b => b.onclick = () => { S.milk = b.dataset.milk === "1"; renderPatient("formula"); });
  $$("#patientCard .ft").forEach(b => b.onclick = () => openRecord({...ctx, date: iso(new Date()), tooth: b.dataset.n}));
  const add = $("#noteAdd");
  if (add) add.onclick = async () => { P.notes = await api.add_note(P.id, $("#noteText").value); renderPatient("notes"); };
  $$(".note button").forEach(b => b.onclick = async () => { if (confirm("Удалить примечание?")) { P.notes = await api.delete_note(P.id, +b.dataset.n); renderPatient("notes"); } });
}
function get0(o, keys) { for (const k of keys) if (o && o[k] !== undefined && o[k] !== null && o[k] !== "") return o[k]; return ""; }

/* ------------------------------------------------------------ settings */
async function loadSettings() {
  const s = await api.get_settings();
  S.settings = s;
  $("#sDemo").checked = !!s.demo; $("#sLogin").value = s.login || ""; $("#sPass").value = "";
  $("#sPass").placeholder = s.has_password ? "сохранён — оставьте пустым" : "введите пароль";
  $("#sBase").value = s.base_url; $("#sBack").value = s.days_back; $("#sFwd").value = s.days_forward; $("#sInt").value = s.interval_min;
  $("#sDs").value = s.day_start; $("#sDe").value = s.day_end; $("#sAllPat").checked = !!s.sync_all_patients; $("#sAuto").checked = !!s.autostart;
  $("#sFromP").value = s.visit_from_param; $("#sToP").value = s.visit_to_param; $("#sChunk").value = s.chunk_days; $("#sPer").value = s.per_page;
  $("#sExtras").value = JSON.stringify(s.patient_extras, null, 1);
  $("#sWriteMap").value = s.write_map && Object.keys(s.write_map).length ? JSON.stringify(s.write_map, null, 1) : "";
  (s.transfer_mode === "auto" ? $("#tmAuto") : $("#tmManual")).checked = true;
  $$(".mode-card").forEach(c => c.classList.toggle("on", c.querySelector("input").checked));
  $("#dataDir").textContent = "Данные: " + s.data_dir;
  $("#verLbl").textContent = "Версия " + (S.status.version || "");
  $("#histTable tbody").innerHTML = s.history.map(h => `<tr><td>${fmtDT(h.finished)}</td><td class="${h.ok ? "ok-t" : "bad-t"}">${esc(h.message)}</td><td>${h.counts.visits ?? "—"}</td><td>${h.counts.patients ?? "—"}</td></tr>`).join("")
    || `<tr><td colspan="4" class="muted">Ещё не было</td></tr>`;
}
$$('input[name="tmode"]').forEach(r => r.onchange = async () => {
  const mode = r.value;
  if (mode === "auto" && !confirm("Включить автоматическую отправку в Dentist Plus?\n\nНовые пациенты и записи (создание, перенос, статус, отмена) будут уходить в Dentist Plus сами, как только появится интернет.\n\nСначала проверьте на одной тестовой записи, что всё приходит правильно.")) {
    $("#tmManual").checked = true; return;
  }
  await api.save_settings({transfer_mode: mode});
  S.settings.transfer_mode = mode;
  $$(".mode-card").forEach(c => c.classList.toggle("on", c.querySelector("input").checked));
  toast(mode === "auto" ? "Автоматическая отправка включена" : "Перенос вручную по списку");
  refreshStatus();
});
$("#sWriteMapDef").onclick = async () => { $("#sWriteMap").value = JSON.stringify(await api.write_map_default(), null, 1); };
function msg(t, ok) { const m = $("#sMsg"); m.textContent = t; m.className = "msg " + (ok ? "ok" : "bad"); }
$("#sSave").onclick = async () => {
  let extras;
  try { extras = JSON.parse($("#sExtras").value || "[]"); } catch (e) { return msg("Ошибка в JSON доп. разделов", false); }
  let writeMap;
  try { writeMap = JSON.parse($("#sWriteMap").value.trim() || "{}"); } catch (e) { return msg("Ошибка в JSON настроек записи в Dentist Plus", false); }
  const demo = $("#sDemo").checked;
  if (!demo && !$("#sLogin").value.trim()) return msg("Укажите логин или включите демо-режим", false);
  if (demo !== !!S.settings.demo && !confirm(demo ? "Включить демо-режим? Сохранённые реальные данные будут удалены с этого компьютера (заметки останутся)." : "Выключить демо-режим? Тестовые данные будут удалены, начнётся загрузка из Dentist Plus.")) return;
  $("#sSave").disabled = true;
  try {
    await api.save_settings({demo, login: $("#sLogin").value.trim(), password: $("#sPass").value, base_url: $("#sBase").value.trim(),
      days_back: $("#sBack").value, days_forward: $("#sFwd").value, interval_min: $("#sInt").value, day_start: $("#sDs").value, day_end: $("#sDe").value,
      sync_all_patients: $("#sAllPat").checked, autostart: $("#sAuto").checked, visit_from_param: $("#sFromP").value.trim(),
      visit_to_param: $("#sToP").value.trim(), chunk_days: $("#sChunk").value, per_page: $("#sPer").value, patient_extras: extras,
      write_map: writeMap});
    msg("Сохранено. Синхронизация запущена.", true);
    S.lastLoaded = "x";
    await loadSettings(); refreshStatus();
  } catch (e) { msg("Не удалось сохранить: " + e, false); }
  $("#sSave").disabled = false;
};
$("#sTest").onclick = async () => {
  msg("Проверяем…", true);
  const r = await api.test_connection($("#sLogin").value.trim(), $("#sPass").value, $("#sBase").value.trim());
  msg(r.message, r.ok);
};
$("#sDiag").onclick = async () => { const o = $("#diagOut"); o.hidden = false; o.textContent = "Запрашиваем API…"; o.textContent = await api.diagnostics(); };
$("#openDir").onclick = () => api.open_data_dir();

/* ------------------------------------------------------------ keyboard */
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "k" || e.code === "KeyK")) { e.preventDefault(); $("#gSearch").focus(); $("#gSearch").select(); return; }
  if (e.key === "Escape") { if ($("#drawer").classList.contains("open")) closeDrawer(); else if (S.view === "patient") $("#backBtn").click(); }
  if (S.view === "schedule" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
    if (e.key === "ArrowLeft") $("#prevDay").click();
    if (e.key === "ArrowRight") $("#nextDay").click();
  }
});

/* ---------------------------------------------------------------- boot */
async function boot() {
  try { const s = await api.get_settings(); S.settings = s; } catch (e) {}
  await refreshStatus();
  loadDay();
  setInterval(refreshStatus, 3000);
  setInterval(() => { if (S.view === "schedule" && S.mode === "grid" && S.day === iso(new Date())) loadDay(); }, 60000);
}
if (location.protocol.startsWith("http")) boot();
else if (window.pywebview && window.pywebview.api && window.pywebview.api.status) boot();
else window.addEventListener("pywebviewready", boot, {once: true});
