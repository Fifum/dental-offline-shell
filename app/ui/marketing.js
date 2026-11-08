"use strict";
/* Marketing: call lists (visit reminders, lapsed patients, unstarted plans, debts), birthdays and patient sources. */
S.mkTab = "calls";
S.mkList = "remind";
const MK_LISTS = [["remind", "Напомнить о визите"], ["lost", "Давно не были"], ["plans", "План не начат"], ["debts", "Должники"]];
const CALL_CLS = {"Записался": "st-done", "Дозвонились": "st-ok", "Перезвонить": "st-come", "Не дозвонились": "", "Отказ": "st-cancel"};
$$("#mkTabs button").forEach(b => b.onclick = () => { S.mkTab = b.dataset.k; $$("#mkTabs button").forEach(x => x.classList.toggle("on", x === b)); loadMarketing(); });

async function loadMarketing() {
  $$("#mkTabs button").forEach(x => x.classList.toggle("on", x.dataset.k === S.mkTab));
  const body = $("#mkBody");
  const fn = {calls: mkCalls, birthdays: mkBirthdays, sources: mkSources}[S.mkTab] || mkCalls;
  await fn(body);
  bindPeriod(body, loadMarketing);
  const pr = $("#mkPrint", body); if (pr) pr.onclick = () => printTable($("#mkTabs button.on").textContent, "#mkBody table.tbl");
}

function callTable(r) {
  if (!r.rows.length) return `<div class="empty"><b>Список пуст</b><span>${{remind: "На этот день нет записей", lost: "Все пациенты приходили недавно или уже записаны", plans: "Все планы лечения начаты или пациенты записаны", debts: "Должников нет", birthdays: "В ближайшие дни дней рождения нет"}[r.kind] || ""}</span></div>`;
  return `<table class="tbl"><thead><tr><th>Пациент</th><th>Телефон</th><th>${r.kind === "remind" ? "Запись" : "Почему в списке"}</th><th>Последний звонок</th><th></th></tr></thead><tbody>${
    r.rows.map((x, i) => `<tr class="${x.last_call ? "muted-row" : ""}"><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name || "—")}</b></td><td class="nowrap">${esc(x.phone || "—")}</td><td>${esc(x.info || "")}</td>
      <td>${x.last_call ? `<span class="pill ${CALL_CLS[x.last_call.result] || ""}">${esc(x.last_call.result)}</span> <small class="muted">${fmtDT(x.last_call.at)}${x.last_call.user_name ? " · " + esc(x.last_call.user_name) : ""}</small>${x.last_call.comment ? `<br><small class="muted">${esc(x.last_call.comment)}</small>` : ""}` : `<span class="muted">—</span>`}</td>
      <td class="row-acts"><button class="btn small ${x.last_call ? "ghost" : ""}" data-call="${i}">Звонок</button></td></tr>`).join("")}</tbody></table>`;
}
function bindCalls(r, reload) {
  $$("#mkBody [data-p]").forEach(td => td.onclick = () => openPatient(td.dataset.p, "marketing"));
  $$("#mkBody [data-call]").forEach(b => b.onclick = () => logCall(r.rows[+b.dataset.call], r.kind, r.results, reload));
}

async function mkCalls(body) {
  const f = {day: S.mkDay || null, months: S.mkMonths || 6};
  const r = await api.call_list(S.mkList, f);
  const extra = S.mkList === "remind" ? `<label class="inline-f">На дату<input type="date" class="input" id="mkDay" value="${r.day || ""}"></label>`
    : S.mkList === "lost" ? `<label class="inline-f">Не были больше<select class="input sm-sel" id="mkMonths">${[3, 6, 9, 12, 18, 24].map(n => `<option value="${n}" ${n === +f.months ? "selected" : ""}>${n} мес.</option>`).join("")}</select></label>` : "";
  body.innerHTML = `<div class="tab-tools rep-tools"><div class="seg sm" id="mkLists">${MK_LISTS.map(([k, t]) => `<button data-l="${k}" class="${k === S.mkList ? "on" : ""}">${t}</button>`).join("")}</div>${extra}
      <span class="grow"></span><span class="muted">${r.rows.length ? `Обзвонено ${r.done} из ${r.rows.length}` : ""}</span><button class="icon-btn" id="mkPrint" title="Печать списка">${PRINT_ICON}</button></div>
    <div class="pbody">${callTable(r)}</div>
    <div class="muted note-line">${{remind: "Записи на выбранный день, кроме отменённых. Отметка звонка видна всем администраторам.",
      lost: "Пациенты, у которых последний визит был давно и нет будущих записей.",
      plans: "Предварительные и активные планы старше недели, по которым не было счетов и нет записи.",
      debts: "Пациенты с долгом по программе или по данным Dentist Plus."}[S.mkList]} Пациенты с отметкой «не звонить» в списки не попадают.</div>`;
  $$("#mkLists button").forEach(b => b.onclick = () => { S.mkList = b.dataset.l; loadMarketing(); });
  const d = $("#mkDay"); if (d) d.onchange = () => { S.mkDay = d.value; loadMarketing(); };
  const m = $("#mkMonths"); if (m) m.onchange = () => { S.mkMonths = +m.value; loadMarketing(); };
  bindCalls(r, loadMarketing);
}

async function mkBirthdays(body) {
  const days = S.mkBdDays || 14;
  const r = await api.call_list("birthdays", {days});
  body.innerHTML = `<div class="tab-tools rep-tools"><div class="seg sm" id="mkBd">${[[1, "Сегодня"], [7, "Неделя"], [14, "2 недели"], [31, "Месяц"]].map(([n, t]) => `<button data-d="${n}" class="${n === days ? "on" : ""}">${t}</button>`).join("")}</div>
      <span class="grow"></span><span class="muted">${r.rows.length} ${plural(r.rows.length, "пациент", "пациента", "пациентов")}</span><button class="icon-btn" id="mkPrint" title="Печать списка">${PRINT_ICON}</button></div>
    <div class="pbody">${callTable(r)}</div>
    <div class="muted note-line">Поздравление — хороший повод напомнить о профгигиене или контрольном осмотре.</div>`;
  $$("#mkBd button").forEach(b => b.onclick = () => { S.mkBdDays = +b.dataset.d; loadMarketing(); });
  bindCalls(r, loadMarketing);
}

async function mkSources(body) {
  const r = await api.mk_sources_report(S.period.from, S.period.to);
  const max = Math.max(0, ...r.rows.map(x => x.new)), pMax = Math.max(0, ...r.rows.map(x => x.paid));
  body.innerHTML = `<div class="tab-tools rep-tools">${periodBar()}<span class="grow"></span><button class="btn ghost" id="mkSrcEdit">Список источников</button><button class="icon-btn" id="mkPrint" title="Печать">${PRINT_ICON}</button></div>
    <div class="stat-row"><div class="stat"><span>Источник указан</span><b>${r.with_source} <small class="muted">из ${r.patients}</small></b></div>
      <div class="stat"><span>Новых пациентов за период</span><b>${r.rows.reduce((a, x) => a + x.new, 0)}</b></div>
      <div class="stat"><span>Оплатили за период</span><b>${money(r.rows.reduce((a, x) => a + x.paid, 0))}</b></div></div>
    <div class="pbody">${r.rows.length ? `<table class="tbl"><thead><tr><th>Источник</th><th class="num">Пациентов всего</th><th class="num">Новых за период</th><th class="bar-h"></th><th class="num">Оплатили за период</th><th class="bar-h"></th></tr></thead><tbody>${
      r.rows.map(x => `<tr class="${x.source ? "" : "muted-row"}"><td><b>${esc(x.source || "Не указан")}</b></td><td class="num">${x.patients || "—"}</td><td class="num">${x.new}</td><td class="bar-cell">${hbar(x.new, max)}</td><td class="num">${money(x.paid)}</td><td class="bar-cell">${hbar(x.paid, pMax)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Пока нет данных</b><span>Укажите источник в карточке пациента или при добавлении нового</span></div>`}</div>
    <div class="muted note-line">Источник выбирается в карточке пациента и при добавлении нового. Если источник есть в Dentist Plus, он подхватывается сам.</div>`;
  $("#mkSrcEdit").onclick = editSources;
}

async function editSources() {
  const list = await api.mk_sources();
  const box = modal(`<div class="m-h"><h3>Источники пациентов</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Каждый источник с новой строки<textarea class="input" id="srcT" rows="10" autofocus>${esc(list.join("\n"))}</textarea></label><div class="auth-err" id="srcErr"></div></div>
    <div class="m-f"><span class="muted">Уже выбранные источники у пациентов сохранятся</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="srcOk">Сохранить</button></div>`);
  $("#srcOk", box).onclick = async () => {
    try { await api.save_mk_sources($("#srcT").value.split("\n")); MK_SOURCES = null; closeModal(); toast("Список сохранён"); loadMarketing(); }
    catch (e) { $("#srcErr").textContent = errText(e); }
  };
}

function logCall(x, kind, results, reload) {
  let pick = "";
  const box = modal(`<div class="m-h"><h3>Звонок: ${esc(x.name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="call-phone">${esc(x.phone || "телефон не указан")}</div><p class="muted">${esc(x.info || "")}</p>
      <div class="call-res">${results.map(t => `<button class="pill-btn" data-r="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <label class="fl">Комментарий<input class="input" id="clT" placeholder="Что сказал пациент"></label>
      <label class="switch-row"><input type="checkbox" id="clNo"><span class="sw"></span>Больше не звонить этому пациенту</label><div class="auth-err" id="clErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button>
      ${kind === "remind" || !can("schedule_edit") ? "" : `<button class="btn ghost" id="clBook">Записать на приём</button>`}<button class="btn" id="clOk">Сохранить</button></div>`);
  $$(".call-res button", box).forEach(b => b.onclick = () => { pick = b.dataset.r; $$(".call-res button", box).forEach(y => y.classList.toggle("on", y === b)); $("#clErr").textContent = ""; });
  const save = async () => {
    if (!pick) { $("#clErr").textContent = "Выберите результат звонка"; return false; }
    await api.log_call({patient_id: x.patient_id, list: kind, result: pick, comment: $("#clT").value, no_calls: $("#clNo").checked});
    return true;
  };
  $("#clOk", box).onclick = async () => { try { if (await save()) { closeModal(); toast("Звонок отмечен"); reload(); } } catch (e) { $("#clErr").textContent = errText(e); } };
  const bk = $("#clBook", box);
  if (bk) bk.onclick = async () => {
    if (!pick) { pick = "Записался"; }
    try { await save(); closeModal(); openBooking({patient_id: x.patient_id, patient_name: x.name, start: `${addDays(iso(new Date()), 1)} 10:00`}); }
    catch (e) { $("#clErr").textContent = errText(e); }
  };
}

/* source of a patient: shown in the card and asked when a new patient is added */
let MK_SOURCES = null;
async function mkSourceList() { if (!MK_SOURCES) { try { MK_SOURCES = await api.mk_sources(); } catch (e) { MK_SOURCES = []; } } return MK_SOURCES; }
const sourceSelect = (id, val, list) => `<select class="input" id="${id}"><option value="">— не указан —</option>${[...new Set([...(list || []), ...(val ? [val] : [])])].map(s => `<option ${s === val ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>`;
async function editPatientSource(p, done) {
  const list = await mkSourceList(), m = p.marketing || {};
  const box = modal(`<div class="m-h"><h3>Откуда пришёл пациент</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Источник${sourceSelect("psrc", m.source || "", list)}</label>
      <label class="switch-row"><input type="checkbox" id="psNo" ${m.no_calls ? "checked" : ""}><span class="sw"></span>Не звонить (не включать в списки обзвона)</label>
      ${(m.calls || []).length ? `<div class="pb-head" style="padding:10px 0 4px"><b>Звонки</b></div><div class="ev-list">${m.calls.map(c => `<div class="ev-row"><span class="pill ${CALL_CLS[c.result] || ""}">${esc(c.result)}</span><span class="grow">${esc(c.comment || "")}</span><small class="muted">${fmtDT(c.at)} · ${esc(c.user_name || "")}</small></div>`).join("")}</div>` : ""}</div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="psOk" autofocus>Сохранить</button></div>`);
  $("#psOk", box).onclick = async () => { await api.set_patient_marketing(p.id, {source: $("#psrc").value, no_calls: $("#psNo").checked}); closeModal(); toast("Сохранено"); if (done) done(); };
}
