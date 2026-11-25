"use strict";
/* 3.11: what the calendar of Dentist Plus does besides showing the grid, so staff working in both programs find it in
   the same place:
   - «⋮» on a visit card or the right mouse button: the actions of the visit (status, move, invoice, record, cancel)
   - the right mouse button on free time: «Новый визит в 10:30», the waiting list
   - a click on the doctor's band: the doctor's month, working days in green; a click on a day opens it
   - the gear «Настройки календаря»: colours of doctors and of statuses, the legend, the scale of the grid
   - Home: today. Everything else (grid, dragging, the visit panel) stays in app.js, calendar-dnd.js and lounge.js. */

const CAL_MI = {
  open: '<svg viewBox="0 0 24 24"><path d="M4 12s3-6.5 8-6.5S20 12 20 12s-3 6.5-8 6.5S4 12 4 12z"/><circle cx="12" cy="12" r="2.6"/></svg>',
  move: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
  pay: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M7 15h3"/></svg>',
  rec: '<svg viewBox="0 0 24 24"><path d="M6 3.5h9l3 3V20.5H6z"/><path d="M9 10h6M9 13.5h6M9 17h4"/></svg>',
  card: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.8 3.4-5.8 7-5.8s6.2 2 7 5.8"/></svg>',
  add: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M12 9.5v7M8.5 13h7"/></svg>',
  wait: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  noshow: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.8 3.4-5.8 7-5.8 1.3 0 2.5.3 3.5.8M16.5 16.5l4 4M20.5 16.5l-4 4"/></svg>',
  cancel: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5"/></svg>',
};

/* ---------------------------------------------------------------- the menu */
let calMenuEl = null;
function calMenuClose() {
  if (!calMenuEl) return;
  calMenuEl.remove(); calMenuEl = null;
  document.removeEventListener("mousedown", calMenuOutside, true);
  document.removeEventListener("keydown", calMenuKey, true);
  window.removeEventListener("resize", calMenuClose);
  const w = document.querySelector(".sched-wrap"); if (w) w.removeEventListener("scroll", calMenuClose);
}
function calMenuOutside(e) { if (calMenuEl && !calMenuEl.contains(e.target)) calMenuClose(); }
function calMenuKey(e) {
  if (!calMenuEl) return;
  const items = $$("button:not([disabled])", calMenuEl), i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); calMenuClose(); }
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); e.stopPropagation();
    const n = items.length, j = e.key === "ArrowDown" ? (i + 1) % n : (i - 1 + n) % n; if (items[j]) items[j].focus();
  } else if (e.key === "Tab") { e.preventDefault(); calMenuClose(); }
}
/** items: [{t, ic, run, danger, head, sep, note}] at the mouse point (kept inside the window). */
function calMenu(items, x, y, title) {
  calMenuClose();
  const el = document.createElement("div");
  el.className = "cal-menu"; el.setAttribute("role", "menu");
  el.innerHTML = (title ? `<div class="cm-title">${title}</div>` : "") + items.map((it, i) => it.sep ? `<div class="cm-sep"></div>`
    : it.head ? `<div class="cm-head">${esc(it.head)}</div>`
    : `<button type="button" role="menuitem" data-i="${i}" class="${it.danger ? "danger" : ""} ${it.st ? "cm-st " + it.st : ""}">${it.ic || ""}<span>${esc(it.t)}</span>${it.kb ? `<kbd>${esc(it.kb)}</kbd>` : ""}</button>`).join("");
  document.body.appendChild(el);
  const r = el.getBoundingClientRect();
  el.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
  el.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
  $$("button[data-i]", el).forEach(b => b.onclick = e => { e.stopPropagation(); const it = items[+b.dataset.i]; calMenuClose(); if (it && it.run) it.run(); });
  calMenuEl = el;
  setTimeout(() => {
    document.addEventListener("mousedown", calMenuOutside, true);
    document.addEventListener("keydown", calMenuKey, true);
    window.addEventListener("resize", calMenuClose);
    const w = document.querySelector(".sched-wrap"); if (w) w.addEventListener("scroll", calMenuClose, {passive: true});
    const f = $("button[data-i]", el); if (f) f.focus({preventScroll: true});
  }, 0);
}

/* ------------------------------------------------------- a visit: «⋮» / right click */
async function calSetStatus(v, st) {
  if (st === "Отменён" && !(await ask("Отменить запись?", {danger: true, ok: "Отменить запись", cancel: "Не отменять", text: `${v.patient_name || "Пациент"}, ${fmtDT(v.start)}`}))) return;
  try { await api.set_visit_status(v.id, st); } catch (e) { return toast(errText(e), true); }
  toast(`${v.patient_name || "Пациент"}: ${st.toLowerCase()}`);
  if ($("#drawer").classList.contains("open")) closeDrawer();
  afterChange();
  if (["Отменён", "Не пришёл"].includes(st) && typeof waitlistHint === "function") waitlistHint(v);
}
function calVisitMenu(id, e) {
  const v = ((S.dayData || {}).visits || []).find(x => x.id === id);
  if (!v) return;
  const sc = stClass(v.status), pid = !!v.patient_id, edit = can("schedule_edit"), stOk = canAny("schedule_edit", "medcard_edit");
  const full = async () => { const f = await api.visit(v.id); if (!f) toast("Запись не найдена — обновите расписание", true); return f; };
  const items = [{t: "Открыть запись", ic: CAL_MI.open, run: () => openVisit(v.id)}];
  const sts = [];
  if (stOk && sc === "") sts.push({t: "Подтверждён", st: "st-ok", ic: ST_IC["st-ok"], run: () => calSetStatus(v, "Подтверждён")});
  if (stOk && !["st-come", "st-done", "st-cancel"].includes(sc)) sts.push({t: "Пришёл", st: "st-come", ic: ST_IC["st-come"], run: () => calSetStatus(v, "Пришёл")});
  if (stOk && !["st-done", "st-cancel"].includes(sc)) sts.push({t: "Завершён", st: "st-done", ic: ST_IC["st-done"], run: () => calSetStatus(v, "Завершён")});
  if (stOk && sc === "st-cancel") sts.push({t: "Вернуть: записан", st: "st-new", ic: ST_IC["st-new"], run: () => calSetStatus(v, "Запланирован")});
  if (sts.length) items.push({sep: 1}, {head: "Статус визита"}, ...sts);
  const acts = [];
  if (edit) acts.push({t: sc === "st-cancel" ? "Перенести на другое время" : "Перенести / изменить", ic: CAL_MI.move, run: async () => { const f = await full(); if (f) openBooking(f); }});
  if (pid && canAny("billing", "payments")) acts.push({t: "Счёт и оплата", ic: CAL_MI.pay, run: async () => { const f = await full(); if (f) openInvoice({patient_id: f.patient_id, visit_id: f.id, doctor_id: f.doctor_id, id: (f.invoices[0] || {}).id}); }});
  if (pid && can("medcard_view")) acts.push({t: "Медкарта: приём", ic: CAL_MI.rec, run: async () => { const f = await full(); if (f) openRecord({patient_id: f.patient_id, visit_id: f.id, doctor_id: f.doctor_id, date: f.start.slice(0, 10), id: (f.records[0] || {}).id}); }});
  if (pid && can("patients_view")) acts.push({t: "Карта пациента", ic: CAL_MI.card, run: () => openPatient(v.patient_id, "schedule")});
  if (pid && edit) acts.push({t: "Новый визит этому пациенту", ic: CAL_MI.add, run: () => openBooking({patient_id: v.patient_id, patient_name: v.patient_name, doctor_id: v.doctor_id, chair: v.chair, start: `${addDays(v.start.slice(0, 10), 7)} ${hm(v.start)}`})});
  if (acts.length) items.push({sep: 1}, ...acts);
  const bad = [];
  if (edit && !["st-cancel", "st-done"].includes(sc)) bad.push({t: "Не пришёл", ic: CAL_MI.noshow, danger: true, run: () => calSetStatus(v, "Не пришёл")});
  if (edit && sc !== "st-cancel") bad.push({t: "Отменить запись", ic: CAL_MI.cancel, danger: true, run: () => calSetStatus(v, "Отменён")});
  if (bad.length) items.push({sep: 1}, ...bad);
  const title = `<b>${esc(v.patient_name || "Пациент")}</b><small>${hm(v.start)} - ${hm(v.end)}${v.doctor_name ? " · " + esc(v.doctor_name) : ""} · <span class="pill ${sc}">${esc(v.status || "Записан")}</span></small>`;
  const r = e.target.closest(".ev-k") ? e.target.closest(".ev-k").getBoundingClientRect() : null;
  calMenu(items, r ? r.left : e.clientX, r ? r.bottom + 2 : e.clientY, title);
}
/* ------------------------------------------------------------ free time: right click */
function calSlotMenu(col, m, e) {
  const t = `${pad(Math.floor(m / 60))}:${pad(m % 60)}`, d = col.dataset.day;
  const items = [{t: `Новый визит в ${t}`, ic: CAL_MI.add, run: () => openBooking({doctor_id: col.dataset.doc, chair: col.dataset.chair, start: `${d} ${t}`})}];
  if (typeof openWaitlist === "function") items.push({t: "Лист ожидания", ic: CAL_MI.wait, run: openWaitlist});
  const pd = parseDay(d);
  calMenu(items, e.clientX, e.clientY, `<b>${pd.getDate()} ${MONTHS[pd.getMonth()]}, ${t}</b>`);
}

/* ---------------------------------------------- the doctor's month (a click on the band) */
let calPop = null;
function calPopClose() { if (calPop) { calPop.remove(); calPop = null; document.removeEventListener("mousedown", calPopOutside, true); document.removeEventListener("keydown", calPopKey, true); } }
function calPopOutside(e) { if (calPop && !calPop.contains(e.target) && !e.target.closest(".gh-band")) calPopClose(); }
function calPopKey(e) { if (e.key === "Escape" && calPop) { e.preventDefault(); e.stopPropagation(); calPopClose(); } }
async function calDoctorMonth(band) {
  const docId = band.dataset.doc;
  if (!docId) return;
  if (calPop && calPop.dataset.doc === docId && calPop.dataset.day === band.dataset.day) return calPopClose();
  calPopClose();
  const doc = ((S.dayData || {}).doctors || []).find(d => d.id === docId) || {id: docId, name: (band.querySelector(".gh-nm").firstChild || {}).textContent};
  const el = document.createElement("div");
  el.className = "cal-pop"; el.dataset.doc = docId; el.dataset.day = band.dataset.day;
  el.style.setProperty("--dc", docColor(docId));
  document.body.appendChild(el);
  calPop = el;
  const place = () => {
    const r = band.getBoundingClientRect(), w = el.getBoundingClientRect();
    el.style.left = Math.max(8, Math.min(r.left, innerWidth - w.width - 8)) + "px";
    el.style.top = Math.max(8, Math.min(r.bottom + 6, innerHeight - w.height - 8)) + "px";
  };
  let month = band.dataset.day.slice(0, 7);
  const draw = async () => {
    const [y, m] = month.split("-").map(Number);
    let mine = {}, used = false;
    if (canAny("schedule_view", "shifts_edit", "staff")) {
      try { const r = await api.shifts_month(month); mine = (r.shifts || {})["d:" + docId] || {}; used = Object.keys(r.shifts || {}).length > 0; } catch (e) { /* no schedules here */ }
    }
    if (calPop !== el) return;
    const first = new Date(y, m - 1, 1), n = new Date(y, m, 0).getDate(), lead = (first.getDay() + 6) % 7, today = iso(new Date());
    const sh = mine[band.dataset.day];
    let cells = "";
    for (let i = 0; i < lead; i++) cells += "<span></span>";
    for (let d = 1; d <= n; d++) {
      const k = `${month}-${pad(d)}`, s = mine[k];
      cells += `<button type="button" data-d="${k}" class="${s ? "work" : ""} ${k === today ? "today" : ""} ${k === S.day ? "on" : ""}" title="${s ? `смена ${esc(s.start)} - ${esc(s.end)}` : used ? "не работает по графику" : ""}">${d}</button>`;
    }
    el.innerHTML = `<div class="cp-h"><span class="cp-av">${esc(initials(doc.name))}</span><div><b>${esc(doc.name || "")}</b>
        <small>${sh ? `${esc(sh.start)} - ${esc(sh.end)}` : used ? "в этот день не работает" : esc(doc.position || "")}</small></div></div>
      <div class="cp-nav"><button type="button" data-m="-1" title="Предыдущий месяц">‹</button><b>${["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"][m - 1]} ${y}</b><button type="button" data-m="1" title="Следующий месяц">›</button></div>
      <div class="cp-wd">${["п", "в", "с", "ч", "п", "с", "в"].map(x => `<span>${x}</span>`).join("")}</div>
      <div class="cp-days">${cells}</div>
      <div class="cp-f">${Object.keys(mine).length ? "Зелёным — рабочие дни по графику. Нажмите на день, чтобы открыть его." : used ? "В этом месяце у врача нет смен по графику." : "Графики работы не заполнены (раздел «Графики работы»). Нажмите на день, чтобы открыть его."}</div>`;
    $$("[data-m]", el).forEach(b => b.onclick = () => { const d = new Date(y, m - 1 + +b.dataset.m, 1); month = `${d.getFullYear()}-${pad(d.getMonth() + 1)}`; draw(); });
    $$("[data-d]", el).forEach(b => b.onclick = () => { calPopClose(); S.day = b.dataset.d; $("#grid").dataset.scrolled = ""; loadDay(); });
    place();
  };
  el.innerHTML = `<div class="cp-h"><span class="cp-av">${esc(initials(doc.name))}</span><div><b>${esc(doc.name || "")}</b><small>…</small></div></div>`;
  place();
  setTimeout(() => { document.addEventListener("mousedown", calPopOutside, true); document.addEventListener("keydown", calPopKey, true); }, 0);
  draw();
}

/* ------------------------------------------------------- «Настройки календаря» */
function calSettings() {
  const scale = CAL.get("scale", "normal");
  const chk = (id, key, label, hint) => `<label class="cs-row"><input type="checkbox" id="${id}" ${CAL.get(key, "1") === "1" ? "checked" : ""}><span><b>${label}</b><small>${hint}</small></span></label>`;
  const box = modal(`<div class="m-h"><h3>Настройки календаря</h3><button class="x" data-close>×</button></div><div class="m-b cal-set">
      ${chk("csDoc", "docColors", "Использовать цвета врачей", "Полоса с именем врача над колонкой и линия слева от неё — в цвет врача")}
      ${chk("csSt", "stColors", "Использовать цвета статусов визита", "Запись окрашена по статусу: записан, подтвердил, в клинике, завершён, отменён")}
      ${chk("csLeg", "legend", "Показывать легенду статусов", "Подписи цветов над расписанием")}
      <div class="cs-scale"><b>Масштаб сетки</b><div class="seg" id="csScale">${[["compact", "Компактный"], ["normal", "Обычный"], ["large", "Крупный"]].map(([k, t]) => `<button type="button" data-s="${k}" class="${k === scale ? "on" : ""}">${t}</button>`).join("")}</div></div>
      <p class="hint">Действует на этом компьютере. Часы работы клиники и шаг записи — в Настройках программы («Расписание»).</p></div>
    <div class="m-f"><span class="muted"></span><button class="btn" data-close>Закрыть</button></div>`);
  // applied at once: nothing is left unsaved, a click beside the dialog just closes it
  const apply = () => { calLegend(); if (S.view === "schedule") loadDay(); setTimeout(() => { box._dirty = false; }, 0); };
  $("#csDoc", box).onchange = e => { CAL.set("docColors", e.target.checked ? "1" : "0"); apply(); };
  $("#csSt", box).onchange = e => { CAL.set("stColors", e.target.checked ? "1" : "0"); apply(); };
  $("#csLeg", box).onchange = e => { CAL.set("legend", e.target.checked ? "1" : "0"); apply(); };
  $$("#csScale button", box).forEach(b => b.onclick = () => {
    CAL.set("scale", b.dataset.s); $$("#csScale button", box).forEach(x => x.classList.toggle("on", x === b)); $("#grid").dataset.scrolled = ""; apply();
  });
  box._dirty = false;
}
function calLegend() { const l = $("#view-schedule .st-legend"); if (l) l.hidden = CAL.get("legend", "1") !== "1"; }
calLegend();
(() => { const b = $("#calSetBtn"); if (b) b.onclick = calSettings; })();

/* Home: today, like the calendar-check button next to the date */
document.addEventListener("keydown", e => {
  if (e.key !== "Home" || S.view !== "schedule" || e.ctrlKey || e.altKey || e.metaKey) return;
  if (/INPUT|SELECT|TEXTAREA/.test((document.activeElement || {}).tagName || "") || !$("#modal").hidden || document.querySelector(".ask-wrap")) return;
  e.preventDefault(); $("#todayBtn").click();
});
