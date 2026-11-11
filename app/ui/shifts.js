"use strict";
/* Work schedules: a month grid of shifts per doctor and staff member; the calendar hatches the hours outside a doctor's shift. */
S.shMonth = iso(new Date()).slice(0, 7);
const WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const hShort = t => t ? (t.endsWith(":00") ? String(+t.slice(0, 2)) : `${+t.slice(0, 2)}:${t.slice(3)}`) : "";

async function loadShifts() {
  if (typeof loadTimesheet === "function") {  // 3.4: «График» | «Табель»
    bindShiftTabs();
    if (S.shTab === "fact") return loadTimesheet();
  }
  const r = await api.shifts_month(S.shMonth);
  S.shData = r;
  const edit = can("shifts_edit"), today = iso(new Date());
  const wd = d => (parseDay(d).getDay() + 6) % 7;
  const head = r.days.map(d => `<th class="sh-d ${wd(d) >= 5 ? "we" : ""} ${d === today ? "today" : ""}"><b>${+d.slice(8)}</b><small>${WD_SHORT[wd(d)]}</small></th>`).join("");
  const rows = r.people.map(p => {
    const sh = r.shifts[p.key] || {}, t = r.totals[p.key];
    return `<tr${p.kind === "unknown" ? ' class="muted"' : ""}><th class="sh-p"><b>${esc(p.name)}</b><small class="muted">${esc(p.position || (p.kind === "doctor" ? "врач" : "сотрудник"))}</small></th>${
      r.days.map(d => { const s = sh[d]; return `<td class="sh-c ${wd(d) >= 5 ? "we" : ""} ${d === today ? "today" : ""} ${s ? "on" : ""} ${edit ? "ed" : ""}" data-k="${esc(p.key)}" data-d="${d}" ${s ? `data-tip="${esc(`${fmtShort(d)}: ${s.start}–${s.end}${s.note ? " · " + s.note : ""}`)}"` : ""}>${s ? `<span>${hShort(s.start)}<i></i>${hShort(s.end)}</span>` : ""}</td>`; }).join("")}
      <td class="sh-t num">${t ? `<b>${t.days}</b> дн.<br><small class="muted">${(+t.hours).toLocaleString("ru-RU")} ч</small>` : `<span class="muted">—</span>`}</td></tr>`;
  }).join("");
  $("#shBody").innerHTML = `<div class="tab-tools rep-tools"><div class="month-nav"><button class="icon-btn" id="shPrev" title="Предыдущий месяц">‹</button><b>${monthName(r.month)}</b><button class="icon-btn" id="shNext" title="Следующий месяц">›</button></div>
      <button class="pill-btn" id="shToday">Текущий месяц</button><span class="grow"></span>
      ${edit ? `<button class="btn" id="shFill">Заполнить по дням недели</button>` : ""}<button class="icon-btn" id="shPrint" title="Печать графика">${PRINT_ICON}</button></div>
    <div class="pbody sh-wrap">${r.people.length ? `<table class="sh-tbl" id="shTbl"><thead><tr><th class="sh-p">Сотрудник</th>${head}<th class="sh-t">Итого</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty"><b>Нет сотрудников</b><span>Врачи появятся после синхронизации с Dentist Plus, остальные — после одобрения заявок в разделе «Сотрудники»</span></div>`}</div>
    <div class="muted note-line">${edit ? "Нажмите на клетку, чтобы поставить или убрать смену. " : ""}В календаре время вне смены врача заштриховано. Если на день не задано ни одной смены, календарь показывает обычный рабочий день клиники.</div>`;
  $("#shPrev").onclick = () => { S.shMonth = shiftMonth(S.shMonth, -1); loadShifts(); };
  $("#shNext").onclick = () => { S.shMonth = shiftMonth(S.shMonth, 1); loadShifts(); };
  $("#shToday").onclick = () => { S.shMonth = iso(new Date()).slice(0, 7); loadShifts(); };
  $("#shPrint").onclick = () => { $("#printArea").innerHTML = `<h2>График работы: ${esc(monthName(r.month).toLowerCase())}</h2>${($("#shTbl") || {}).outerHTML || ""}`; window.print(); };
  if (edit) {
    $("#shFill").onclick = fillShifts;
    $$("#shBody td.sh-c").forEach(td => td.onclick = () => editShift(td.dataset.k, td.dataset.d));
  }
}

function lastShift(key) {
  const sh = (S.shData.shifts[key]) || {}; const d = Object.keys(sh).sort().pop();
  return d ? sh[d] : {start: "09:00", end: "18:00"};
}
function editShift(key, day) {
  const p = S.shData.people.find(x => x.key === key) || {}, cur = (S.shData.shifts[key] || {})[day], def = cur || lastShift(key);
  if (p.kind === "unknown") {  // 3.6.1: a shift of an account this computer does not have — it can only be removed
    if (!cur) return;
    const ub = modal(`<div class="m-h"><h3>${esc(p.name)}</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><p class="muted">${esc(fmtDate(day))}: ${cur.start}–${cur.end}</p><p>Смена записана на учётную запись, которой нет на этом компьютере (или она пришла с компьютера со старой версией программы). Её можно только удалить; новую смену поставьте нужному сотруднику.</p></div>
      <div class="m-f"><button class="btn ghost small danger" id="shDel">Удалить смену</button><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button></div>`);
    $("#shDel", ub).onclick = async () => { await api.save_shift({person: key, date: day, start: ""}); closeModal(); loadShifts(); };
    return;
  }
  const box = modal(`<div class="m-h"><h3>${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">${esc(fmtDate(day))}, ${WD[parseDay(day).getDay()]}</p>
      <div class="grid2"><label class="fl">Начало<input class="input" type="time" id="shS" value="${def.start}" autofocus></label><label class="fl">Конец<input class="input" type="time" id="shE" value="${def.end}"></label></div>
      <div class="chips sh-presets">${[["09:00", "15:00"], ["09:00", "18:00"], ["12:00", "20:00"], ["15:00", "21:00"], ["09:00", "21:00"]].map(([a, b]) => `<button class="chip" data-a="${a}" data-b="${b}">${hShort(a)}–${hShort(b)}</button>`).join("")}</div>
      <label class="fl">Заметка<input class="input" id="shN" value="${esc((cur && cur.note) || "")}" placeholder="Кабинет, замена…"></label><div class="auth-err" id="shErr"></div></div>
    <div class="m-f">${cur ? `<button class="btn ghost small danger" id="shDel">Выходной</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="shOk">Сохранить</button></div>`);
  $$(".sh-presets .chip", box).forEach(c => c.onclick = () => { $("#shS").value = c.dataset.a; $("#shE").value = c.dataset.b; });
  $("#shOk", box).onclick = async () => {
    try { await api.save_shift({person: key, date: day, start: $("#shS").value, end: $("#shE").value, note: $("#shN").value}); closeModal(); loadShifts(); }
    catch (e) { $("#shErr").textContent = errText(e); }
  };
  const del = $("#shDel", box);
  if (del) del.onclick = async () => { await api.save_shift({person: key, date: day, start: ""}); closeModal(); loadShifts(); };
}

function fillShifts() {
  const r = S.shData;
  const box = modal(`<div class="m-h"><h3>Заполнить график: ${esc(monthName(r.month).toLowerCase())}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="fl">Сотрудники<div class="fill-people">${r.people.filter(p => p.kind !== "unknown").map(p => `<label class="dm-row"><input type="checkbox" data-pp="${esc(p.key)}">${esc(p.name)}</label>`).join("")}</div>
        <button class="linkbtn" id="fpAll" type="button">выбрать всех</button></div>
      <div class="fl">Дни недели<div class="seg sm wd-pick">${WD_SHORT.map((t, i) => `<button type="button" data-w="${i}" class="${i < 5 ? "on" : ""}">${t}</button>`).join("")}</div></div>
      <div class="grid3"><label class="fl">Начало<input class="input" type="time" id="fS" value="09:00"></label><label class="fl">Конец<input class="input" type="time" id="fE" value="18:00"></label>
        <label class="fl">Повтор<select class="input" id="fEv"><option value="1">Каждую неделю</option><option value="2">Через неделю (1-я, 3-я, 5-я)</option></select></label></div>
      <label class="switch-row"><input type="checkbox" id="fOw"><span class="sw"></span>Заменить уже поставленные смены</label>
      <div class="auth-err" id="fErr"></div></div>
    <div class="m-f"><button class="btn ghost small danger" id="fClr">Очистить месяц у выбранных</button><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="fOk">Заполнить</button></div>`, {wide: true});
  $$(".wd-pick button", box).forEach(b => b.onclick = () => b.classList.toggle("on"));
  $("#fpAll", box).onclick = () => $$("[data-pp]", box).forEach(c => c.checked = true);
  const picked = () => $$("[data-pp]", box).filter(c => c.checked).map(c => c.dataset.pp);
  $("#fOk", box).onclick = async () => {
    try {
      const n = await api.fill_shifts({people: picked(), month: r.month, weekdays: $$(".wd-pick button.on", box).map(b => +b.dataset.w),
        start: $("#fS").value, end: $("#fE").value, every: +$("#fEv").value, overwrite: $("#fOw").checked});
      closeModal(); toast(`Поставлено смен: ${n}`); loadShifts();
    } catch (e) { $("#fErr").textContent = errText(e); }
  };
  $("#fClr", box).onclick = async () => {
    const ps = picked(); if (!ps.length) { $("#fErr").textContent = "Выберите сотрудников"; return; }
    if (!await ask(`Убрать все смены за ${monthName(r.month).toLowerCase()}?`, {danger: true, ok: "Очистить", text: `Сотрудников: ${ps.length}`})) return;
    for (const k of ps) await api.clear_shifts(k, r.month);
    closeModal(); loadShifts();
  };
}
