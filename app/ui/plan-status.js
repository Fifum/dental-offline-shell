"use strict";
/* 3.6: treatment plans as sales — statuses with the history (in the plan), «CRM» → «Обзвон» → «Брошенные планы»
   (who to call, why, the money, the last visit; results and «перезвонить» on a date) and «Отчёты» → «Планы лечения»
   (by status and doctor, conversion, money left in abandoned plans, plans brought back by calls). */
const PST = [["Предварительный", "Предложен"], ["Подтверждён", "Продан"], ["Активен", "В работе"], ["Лечение завершено", "Завершён"],
  ["Брошен", "Брошен"], ["Отказ", "Отказ"]];
const PST_LABEL = Object.fromEntries(PST);
const PST_OPTION = {"Предварительный": "Предложен (предварительный)", "Подтверждён": "Продан (подтверждён)", "Активен": "В работе (активен)",
  "Лечение завершено": "Завершён", "Брошен": "Брошен", "Отказ": "Отказ пациента"};
const PST_PILL = {"Подтверждён": "st-ok", "Активен": "st-come", "Лечение завершено": "st-done", "Брошен": "st-cancel", "Отказ": "st-cancel"};
const PC_CLS = {"Записался": "st-done", "Дозвонились": "st-ok", "Перезвонить": "st-come", "Не дозвонились": "", "Отказ": "st-cancel"};
const pstPill = s => `<span class="pill ${PST_PILL[s] || ""}" title="${esc(s || "")}">${esc(PST_LABEL[s] || s || "")}</span>`;
S.pcDue = true;
S.pcDoc = "";
S.pcMonths = null;
S.rpDoc = "";
S.rpStatus = "";
S.planCallsDue = 0;

function planCallsStatus(st) {
  S.planCallsDue = st.plan_calls || 0;
  const el = $("#mkPlanCnt");
  if (el) { el.hidden = !S.planCallsDue; el.textContent = S.planCallsDue || ""; }
}

/* ------------------------------------------------------------ the plan editor: the select and the history */
function pstOptions(cur) {
  cur = cur || "Предварительный";
  const keys = PST.map(x => x[0]);
  return (keys.includes(cur) ? keys : [...keys, cur]).map(s => `<option value="${esc(s)}" ${s === cur ? "selected" : ""}>${esc(PST_OPTION[s] || s)}</option>`).join("");
}
async function planHistoryInto(el, planId) {
  if (!el || !planId) return;
  let rows = [];
  try { rows = await api.plan_history(planId); } catch (e) { return; }
  if (!rows.length) { el.innerHTML = ""; return; }
  const last = rows[rows.length - 1];
  el.innerHTML = `<details class="pst-hist"><summary>История статуса <span class="muted">· ${fmtDT(last.at)}${last.auto ? " · автоматически" : ""}</span></summary>
    <div class="ev-list">${rows.slice().reverse().map(r => `<div class="ev-row"><span class="nowrap">${r.old ? pstPill(r.old) + " → " : ""}${pstPill(r.new)}</span>
      <span class="grow">${esc(r.reason || "")}${r.credit_name ? ` <small class="muted">· после звонка: ${esc(r.credit_name)}</small>` : ""}</span>
      <small class="muted nowrap">${fmtDT(r.at)} · ${esc(r.auto ? "автоматически" : (r.who || "—"))}</small></div>`).join("")}</div></details>`;
}

/* ------------------------------------------------------------ «CRM» → «Обзвон» → «Брошенные планы» */
async function planCalls(body) {
  let r;
  try { r = await api.plan_calls({due_only: S.pcDue, doctor_id: S.pcDoc || null, months: S.pcMonths}); }
  catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  const set = r.settings;
  const xls = `<button class="icon-btn" title="Скачать в Excel" data-xls="#mkBody table.tbl" data-xls-title="#mkTabs button.on"><svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg></button>`;
  body.innerHTML = `<div class="tab-tools rep-tools"><div class="seg sm" id="mkLists">${MK_LISTS.map(([k, t]) => `<button data-l="${k}" class="${k === S.mkList ? "on" : ""}">${t}${k === "abandoned" ? ` <i class="cnt" id="mkPlanCnt" ${S.planCallsDue ? "" : "hidden"}>${S.planCallsDue || ""}</i>` : ""}</button>`).join("")}</div>
      <div class="seg sm" id="pcDue"><button data-v="1" class="${S.pcDue ? "on" : ""}">К звонку</button><button data-v="0" class="${S.pcDue ? "" : "on"}">Все брошенные</button></div>
      <select class="input sm-sel" id="pcDoc" title="Врач"><option value="">Все врачи</option>${r.doctors.map(d => `<option value="${esc(d.id)}" ${String(d.id) === String(S.pcDoc) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>
      <select class="input sm-sel" id="pcMonths" title="Последнее движение по плану не раньше">${[[3, "за 3 мес."], [6, "за 6 мес."], [12, "за год"], [24, "за 2 года"], [0, "за всё время"]].map(([n, t]) => `<option value="${n}" ${n === r.months ? "selected" : ""}>${t}</option>`).join("")}</select>
      <span class="grow"></span><span class="muted">${r.rows.length ? `${r.rows.length} ${plural(r.rows.length, "план", "плана", "планов")} · осталось <b>${money(r.sum_left)}</b>` : ""}</span>
      ${can("reports") || can("settings") ? `<button class="btn ghost small" id="pcSet">Правила</button>` : ""}${xls}<button class="icon-btn" id="mkPrint" title="Печать списка">${PRINT_ICON}</button></div>
    <div class="pbody">${r.rows.length ? `<table class="tbl pc-tbl"><thead><tr><th>Пациент</th><th>Телефон</th><th>План</th><th class="num">Осталось</th><th>Последний визит</th><th>Почему в списке</th><th>Последний звонок</th><th></th></tr></thead><tbody>${
      r.rows.map((x, i) => `<tr class="${x.due ? "" : "muted-row"}"><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name || "—")}</b></td><td class="nowrap">${esc(x.phone || "—")}</td>
        <td>${can("billing") ? `<span class="lnk" data-plan="${i}">${esc(x.title)}</span>` : esc(x.title)}<br><small class="muted">${esc(x.doctor_name || "врач не указан")} · от ${fmtDate(x.created_at)}</small></td>
        <td class="num"><b>${money(x.left)}</b>${x.billed ? `<br><small class="muted">из ${money(x.total)}</small>` : ""}</td>
        <td class="nowrap">${x.last_visit ? fmtDate(x.last_visit) : '<span class="muted">не было</span>'}${x.future ? `<br><small class="ok-t">записан на ${fmtDate(x.future)}</small>` : ""}</td>
        <td>${esc(x.reason || "брошен вручную")}${x.manual ? ' <small class="muted">(вручную)</small>' : ""}${x.lost_at ? `<br><small class="muted">брошен ${fmtDate(x.lost_at)}</small>` : ""}</td>
        <td>${x.last_call ? `<span class="pill ${PC_CLS[x.last_call.result] || ""}">${esc(x.last_call.result)}</span> <small class="muted">${fmtDT(x.last_call.at)}${x.last_call.user_name ? " · " + esc(x.last_call.user_name) : ""}</small>${x.next_call ? `<br><small class="${x.due ? "bad-t" : "muted"}">перезвонить ${fmtDate(x.next_call)}</small>` : ""}${x.last_call.comment ? `<br><small class="muted">${esc(x.last_call.comment)}</small>` : ""}` : `<span class="muted">не звонили</span>`}</td>
        <td class="row-acts"><button class="btn small ${x.due ? "" : "ghost"}" data-pcall="${i}">Звонок</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>${S.pcDue ? "Звонить сегодня некому" : "Брошенных планов нет"}</b><span>${S.pcDue ? "Остальные брошенные планы — во вкладке «Все брошенные»" : "Планы с движением: визиты, счета или запись"}</span></div>`}</div>
    <div class="muted note-line">${set.on ? `Брошенный план — продан или начат, но ${set.days} ${plural(set.days, "день", "дня", "дней")} нет ни визита, ни счёта по плану, ни записи${set.proposed_days ? `; предложенный — через ${set.proposed_days} ${plural(set.proposed_days, "день", "дня", "дней")}` : ""}. Как только появится визит, счёт или запись, план сам вернётся в работу.` : "Автоматические статусы выключены: план попадает сюда, только если перевести его в «Брошен» вручную."}
      «Перезвонить» ставит задачу CRM на выбранный день, «Отказ» переводит план в «Отказ» с причиной. Пациенты с отметкой «не звонить» в список не попадают.</div>`;
  $$("#mkLists button").forEach(b => b.onclick = () => { S.mkList = b.dataset.l; loadMarketing(); });
  $$("#pcDue button").forEach(b => b.onclick = () => { S.pcDue = b.dataset.v === "1"; loadMarketing(); });
  $("#pcDoc").onchange = e => { S.pcDoc = e.target.value; loadMarketing(); };
  $("#pcMonths").onchange = e => { S.pcMonths = +e.target.value; loadMarketing(); };
  const ps = $("#pcSet"); if (ps) ps.onclick = () => planStatusSettings(loadMarketing);
  $$("#mkBody [data-p]").forEach(td => td.onclick = () => openPatient(td.dataset.p, "marketing"));
  $$("#mkBody [data-plan]").forEach(el => el.onclick = () => { const x = r.rows[+el.dataset.plan]; openInvoice({patient_id: x.patient_id, id: x.plan_id, after: () => loadMarketing()}); });
  $$("#mkBody [data-pcall]").forEach(b => b.onclick = () => planCallDialog(r.rows[+b.dataset.pcall], r, loadMarketing));
}

function planCallDialog(x, r, reload) {
  let pick = "";
  const tomorrow = addDays(iso(new Date()), 1);
  const box = modal(`<div class="m-h"><h3>Звонок: ${esc(x.name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="call-phone">${esc(x.phone || "телефон не указан")}</div>
      <p class="muted">${esc(x.title)} · ${esc(x.doctor_name || "врач не указан")} · осталось ${money(x.left)}${x.last_visit ? ` · последний визит ${fmtDate(x.last_visit)}` : ""}</p>
      <div class="call-res">${r.results.map(t => `<button class="pill-btn" data-r="${esc(t.key)}">${esc(t.label)}</button>`).join("")}</div>
      <div class="grid2" id="pcMore" hidden>
        <label class="fl" id="pcOnF" hidden>Когда перезвонить<input type="date" class="input" id="pcOn" value="${tomorrow}" min="${iso(new Date())}"></label>
        <label class="fl" id="pcWhyF" hidden>Причина отказа<select class="input" id="pcWhy"><option value="">— выберите —</option>${r.reasons.map(t => `<option>${esc(t)}</option>`).join("")}</select></label></div>
      <label class="fl">Комментарий<input class="input" id="pcT" placeholder="Что сказал пациент"></label>
      <label class="switch-row"><input type="checkbox" id="pcNo"><span class="sw"></span>Больше не звонить этому пациенту</label><div class="auth-err" id="pcErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button>
      ${can("schedule_edit") ? `<button class="btn ghost" id="pcBook">Записать на приём</button>` : ""}<button class="btn" id="pcOk">Сохранить</button></div>`);
  const choose = k => {
    pick = k;
    $$(".call-res button", box).forEach(y => y.classList.toggle("on", y.dataset.r === k));
    $("#pcOnF", box).hidden = k !== "callback"; $("#pcWhyF", box).hidden = k !== "refused"; $("#pcMore", box).hidden = k !== "callback" && k !== "refused";
    $("#pcErr", box).textContent = "";
  };
  $$(".call-res button", box).forEach(b => b.onclick = () => choose(b.dataset.r));
  const save = async () => {
    if (!pick) { $("#pcErr", box).textContent = "Выберите результат звонка"; return false; }
    if (pick === "refused" && !$("#pcWhy", box).value) { $("#pcErr", box).textContent = "Укажите причину отказа"; return false; }
    if (pick === "callback" && !$("#pcOn", box).value) { $("#pcErr", box).textContent = "Укажите, когда перезвонить"; return false; }
    const res = await api.plan_call({plan_id: x.plan_id, result: pick, comment: $("#pcT", box).value, call_on: pick === "callback" ? $("#pcOn", box).value : null,
      reason: pick === "refused" ? $("#pcWhy", box).value : "", no_calls: $("#pcNo", box).checked});
    return res;
  };
  $("#pcOk", box).onclick = async () => {
    try {
      const on = $("#pcOn", box).value || tomorrow;
      const res = await save(); if (!res) return;
      closeModal();
      toast(pick === "callback" ? `Задача «перезвонить» на ${fmtDate(on)} — в «CRM» → «Задачи»` : pick === "refused" ? "План переведён в «Отказ»"
        : pick === "booked" && res.status !== "Брошен" ? "План снова в работе" : "Звонок отмечен");
      reload();
    } catch (e) { $("#pcErr", box).textContent = errText(e); }
  };
  const bk = $("#pcBook", box);
  if (bk) bk.onclick = async () => {
    if (!pick) choose("booked");
    try { if (!await save()) return; closeModal(); openBooking({patient_id: x.patient_id, patient_name: x.name, start: `${tomorrow} 10:00`}); }
    catch (e) { $("#pcErr", box).textContent = errText(e); }
  };
}

async function planStatusSettings(after) {
  let m;
  try { m = await api.plan_status_meta(); } catch (e) { return toast(errText(e), true); }
  const s = m.settings;
  const box = modal(`<div class="m-h"><h3>Статусы планов лечения</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <label class="switch-row"><input type="checkbox" id="psOn" ${s.on ? "checked" : ""}><span class="sw"></span>Менять статусы автоматически</label>
      <div class="grid2"><label class="fl">Проданный или начатый план брошен через, дней<input class="input num" type="number" min="14" max="730" id="psDays" value="${s.days}"></label>
        <label class="fl">Предложенный план брошен через, дней (0 — не трогать)<input class="input num" type="number" min="0" max="730" id="psProp" value="${s.proposed_days}"></label></div>
      <label class="switch-row"><input type="checkbox" id="psVisit" ${s.visit_auto ? "checked" : ""}><span class="sw"></span>Приём в Dentist Plus с услугой из плана — план «В работе»</label>
      <label class="switch-row"><input type="checkbox" id="psDone" ${s.done_auto ? "checked" : ""}><span class="sw"></span>Все услуги плана выставлены в счета — план «Завершён»</label>
      <label class="fl">Обзвон по умолчанию: планы с движением за последние, мес. (0 — за всё время)<input class="input num" type="number" min="0" max="120" id="psMon" value="${s.call_months}"></label>
      <p class="hint">Движение — визит пациента, счёт по плану или запись на приём. Статус, поставленный вручную, программа не перебивает: правила смотрят только на то, что случилось после него. Каждое изменение — в истории плана и в журнале действий.</p>
      <div class="auth-err" id="psErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="psOk">Сохранить</button></div>`);
  $("#psOk", box).onclick = async () => {
    try {
      await api.plan_status_settings_save({on: $("#psOn", box).checked, days: +$("#psDays", box).value, proposed_days: +$("#psProp", box).value,
        visit_auto: $("#psVisit", box).checked, done_auto: $("#psDone", box).checked, call_months: +$("#psMon", box).value});
      closeModal(); toast("Правила сохранены"); S.pcMonths = null; if (after) after();
    } catch (e) { $("#psErr", box).textContent = errText(e); }
  };
}

/* ------------------------------------------------------------ «Отчёты» → «Планы лечения» */
async function repPlans(body) {
  let r;
  try { r = await api.plan_report(S.period.from, S.period.to, {doctor_id: S.rpDoc || null, status: S.rpStatus || null}); }
  catch (e) { body.innerHTML = repTools() + `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  const f = r.funnel, ln = r.lost_now;
  const docSel = `<select class="input sm-sel" id="rpDoc" title="Врач"><option value="">Все врачи</option>${r.doctors.map(d => `<option value="${esc(d.id)}" ${String(d.id) === String(S.rpDoc) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>`;
  const fun = [["Предложено", f.proposed], ["Продано", f.sold], ["Начато лечение", f.started], ["Завершено", f.done]];
  body.innerHTML = repTools(docSel + (can("reports") || can("settings") ? `<button class="btn ghost small" id="rpSet">Правила статусов</button>` : "")) + `<div class="stat-row">
      <div class="stat"><span>Планов составлено</span><b>${f.proposed}</b><small class="muted">на ${money(f.sum)}</small></div>
      <div class="stat"><span>Продано</span><b>${f.sold} <small class="muted">${pctT(f.sold_rate)}</small></b><small class="muted">на ${money(f.sum_sold)}</small></div>
      <div class="stat"><span>Начато лечение</span><b>${f.started} <small class="muted">${pctT(f.start_rate)}</small></b><small class="muted">выставлено ${money(f.billed)}</small></div>
      <div class="stat"><span>Брошено сейчас</span><b class="${ln.n ? "bad-t" : ""}">${ln.n}</b><small class="muted">осталось ${money(ln.left)} · за всё время</small></div>
      <div class="stat"><span>Возвращено звонками</span><b>${r.back.n}</b><small class="muted">планы на ${money(r.back.sum)}</small></div></div>
    <div class="dir-grid rp-grid">
      <div class="pbody"><div class="pb-head"><b>Воронка: предложен → продан → в работе → завершён</b><span class="muted">${periodText()}</span></div>
        <div class="funnel">${fun.map(([k, v], i) => `<div class="fn-row"><span>${k}</span>${hbar(v, f.proposed || 1)}<b>${v}</b><small class="muted">${i ? pctT(f.proposed ? Math.round(v * 1000 / f.proposed) / 10 : null) : ""}</small></div>`).join("")}</div></div>
      <div class="pbody"><div class="pb-head"><b>По статусам сейчас</b><span class="muted">планы, составленные за период</span></div>
        <table class="tbl compact rp-st"><tbody><tr class="lnk-row ${S.rpStatus ? "" : "on"}" data-s="" title="Показать все планы ниже"><td>Все</td><td class="num">${f.proposed}</td><td class="num">${money(f.sum)}</td></tr>${
          r.by_status.map(x => `<tr class="lnk-row ${S.rpStatus === x.key ? "on" : ""}" data-s="${esc(x.key)}" title="Показать эти планы ниже"><td>${pstPill(x.key)}</td><td class="num">${x.n}</td><td class="num">${money(x.sum)}</td></tr>`).join("")}</tbody></table></div>
    </div>
    <div class="pbody"><div class="pb-head"><b>По врачам</b><span class="muted">${periodText()}</span></div>${r.by_doctor.length ? `<div class="tbl-scroll"><table class="tbl"><thead><tr><th>Врач</th><th class="num">Планов</th><th class="num">На сумму</th>${PST.map(([, t]) => `<th class="num">${t}</th>`).join("")}<th class="num">Продано</th><th class="num">Начато</th><th class="num">Осталось в брошенных</th></tr></thead><tbody>${
      r.by_doctor.map(d => `<tr><td title="${esc(d.name)}"><b>${esc(shortFio(d.name))}</b></td><td class="num">${d.n}</td><td class="num">${money(d.sum)}</td>${PST.map(([k]) => `<td class="num ${k === "Брошен" && d[k] ? "bad-t" : ""}">${d[k] || "—"}</td>`).join("")}
        <td class="num">${d.sold} <small class="muted">${pctT(d.sold_rate)}</small></td><td class="num">${d.started} <small class="muted">${pctT(d.start_rate)}</small></td><td class="num ${d.lost_left ? "bad-t" : ""}">${d.lost_left ? money(d.lost_left) : "—"}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty sm"><b>За период планов не составлено</b></div>`}</div>
    ${ln.by_doctor.length ? `<div class="pbody"><div class="pb-head"><b>Деньги в брошенных планах</b><span class="muted">все брошенные планы, когда бы ни были составлены</span></div>
      <table class="tbl compact"><tbody>${ln.by_doctor.map(d => `<tr><td>${esc(d.name)}</td><td class="num">${d.n} ${plural(d.n, "план", "плана", "планов")}</td><td class="num"><b>${money(d.left)}</b></td></tr>`).join("")}</tbody></table>
      ${can("marketing") ? `<div class="pay-add"><button class="btn ghost small" id="rpCalls">Открыть обзвон по брошенным</button></div>` : ""}</div>` : ""}
    ${r.back.by_staff.length ? `<div class="pbody"><div class="pb-head"><b>Вернули в работу звонком</b><span class="muted">${periodText()}</span></div>
      <table class="tbl compact"><tbody>${r.back.by_staff.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${x.n} ${plural(x.n, "план", "плана", "планов")}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <div class="pbody"><div class="pb-head"><b>Планы${S.rpStatus ? ` · ${esc(PST_LABEL[S.rpStatus] || S.rpStatus)}` : ""}</b><span class="muted">${r.plans.length}${r.plans.length >= 500 ? " (первые 500)" : ""}</span></div>${r.plans.length ? `<div class="tbl-scroll"><table class="tbl"><thead><tr><th>Создан</th><th>Пациент</th><th>План</th><th>Врач</th><th>Статус</th><th class="num">Сумма</th><th class="num">Выставлено</th></tr></thead><tbody>${
      r.plans.map((p, i) => `<tr class="lnk-row" data-rp="${i}"><td>${fmtDate(p.created_at)}</td><td><b>${esc(p.patient_name || "—")}</b></td><td>${esc(p.title)}</td><td>${esc(shortFio(p.doctor_name))}</td><td>${pstPill(p.status)}</td><td class="num">${money(p.total)}</td><td class="num">${p.billed ? money(p.billed) : "—"}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty sm"><span>Нет планов</span></div>`}</div>
    <div class="muted note-line">Продан — пациент согласился (план подтверждён или выбран вариант); начат — счёт по плану или приём в Dentist Plus с услугой из плана. ${r.settings.on ? `Брошен — продан или начат, но ${r.settings.days} ${plural(r.settings.days, "день", "дня", "дней")} нет ни визита, ни счёта, ни записи.` : "Автоматические статусы выключены."} Осталось — сумма плана минус счета по нему в программе.${r.own ? " Показаны ваши планы." : ""}</div>`;
  $("#rpDoc").onchange = e => { S.rpDoc = e.target.value; loadReports(); };
  $$("#repBody .rp-st [data-s]").forEach(tr => tr.onclick = () => { S.rpStatus = tr.dataset.s; loadReports(); });
  const st = $("#rpSet"); if (st) st.onclick = () => planStatusSettings(loadReports);
  const rc = $("#rpCalls"); if (rc) rc.onclick = () => { S.mkTab = "calls"; S.mkList = "abandoned"; S.pcDue = false; show("marketing"); };
  $$("#repBody [data-rp]").forEach(tr => tr.onclick = () => {
    const p = r.plans[+tr.dataset.rp];
    if (can("billing")) openInvoice({patient_id: p.patient_id, id: p.id, after: () => loadReports()}); else openPatient(p.patient_id);
  });
}
