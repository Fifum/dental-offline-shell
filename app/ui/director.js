"use strict";
/* The director's screen (today, the month, forecast and plan, doctors, what needs attention, the week ahead),
   the plan for the month, and the analytics tabs of «Отчёты»: patients, load, conversion. Uses the period
   picker, bars and charts of reports.js. */

const pctT = v => v == null ? "—" : `${(+v).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
const rub = n => Math.round(+n || 0).toLocaleString("ru-RU") + " ₽";
/* «Ахмедова Мадина Руслановна» → «Ахмедова М. Р.» for narrow tables */
const shortFio = n => { const w = String(n || "").trim().split(/\s+/); return w.length > 1 ? `${w[0]} ${w.slice(1, 3).map(x => x[0] + ".").join(" ")}` : (n || ""); };
const hrs = m => (Math.round((+m || 0) / 6) / 10).toLocaleString("ru-RU");
/* progress toward a target: the bar is the share done, the tick is where the month should be by now */
const meter = (v, tick) => `<span class="meter"><i style="width:${Math.max(0, Math.min(100, +v || 0))}%"></i>${tick != null ? `<u style="left:${Math.max(0, Math.min(100, tick))}%" title="Должно быть к сегодняшнему дню"></u>` : ""}</span>`;
/* change against the previous month: an arrow and the words, never colour alone */
function delta(cur, prev, {lowerIsBetter = false, points = false} = {}) {
  if (!prev) return `<small class="muted">в прошлом месяце данных нет</small>`;
  const d = points ? Math.round((cur - prev) * 10) / 10 : Math.round((cur - prev) * 1000 / prev) / 10;
  if (!d) return `<small class="muted">как в прошлом месяце</small>`;
  const good = lowerIsBetter ? d < 0 : d > 0;
  return `<small class="${good ? "ok-t" : "bad-t"}">${d > 0 ? "▲" : "▼"} ${Math.abs(d).toLocaleString("ru-RU")}${points ? " п." : " %"} к прошлому месяцу</small>`;
}
const ADV_ICON = {
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>',
  ok: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16 9.8"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5v.01"/></svg>',
};
const ADV_LABEL = {warn: "Внимание", ok: "Хорошо", info: "К сведению"};

/* ------------------------------------------------------- director screen */
async function loadDirector() {
  const body = $("#dirBody");
  let r;
  try { r = await api.director_dashboard(); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  S.dir = r;
  const m = r.month, t = r.today;
  const wd = WD[parseDay(t.day).getDay()];
  $("#dirSub").textContent = `${wd[0].toUpperCase() + wd.slice(1)}, ${+t.day.slice(8, 10)} ${MONTHS[+t.day.slice(5, 7) - 1]} · ${monthName(m.from.slice(0, 7)).toLowerCase()}, рабочий день ${m.workdays_done} из ${m.workdays}`;
  const pace = m.workdays ? m.workdays_done * 100 / m.workdays : null;
  const days = everyDay(m.by_day, m.from, m.to, {billed: 0, paid: 0});
  body.innerHTML = `<div class="stat-row dir-tiles">
      <div class="stat"><span>Поступило сегодня</span><b>${money(t.paid)}</b>
        <small class="muted">${t.workday || t.visits ? `${t.visits} ${plural(t.visits, "запись", "записи", "записей")} · загрузка ${pctT(t.load)}` : "Сегодня выходной"}</small></div>
      <div class="stat"><span>Поступило за месяц</span><b>${money(m.paid)}</b>${delta(m.paid, m.prev_paid)}</div>
      <div class="stat ${m.plan && m.forecast_pct < 97 ? "warn" : ""}"><span>Прогноз на месяц</span><b>${money(m.forecast)}</b>
        ${m.plan ? `<small class="muted">план ${rub(m.plan)} · выполнено ${pctT(m.plan_pct)}</small>${meter(m.plan_pct, pace)}`
          : `<button class="linkbtn dir-plan-btn" data-kpi>Задать план на месяц →</button>`}</div>
      <div class="stat"><span>Средний чек</span><b>${money(m.avg_check)}</b>${delta(m.avg_check, m.prev_avg_check)}</div>
      <div class="stat"><span>Новые пациенты</span><b>${m.new_patients}</b>${delta(m.new_patients, m.prev_new_patients)}</div>
      <div class="stat ${m.lost_share >= 15 ? "warn" : ""}"><span>Отмены и неявки</span><b>${pctT(m.lost_share)}</b>${m.prev_visits ? delta(m.lost_share, m.prev_lost_share, {lowerIsBetter: true, points: true}) : `<small class="muted">записей за месяц</small>`}</div>
    </div>
    <div class="dir-grid">
      <div class="dir-col">
        <div class="pbody"><div class="pb-head"><b>Врачи в этом месяце</b><button class="linkbtn" data-kpi>План на месяц →</button></div>
          ${r.doctors.length ? `<div class="tbl-scroll"><table class="tbl" id="dirDocs"><thead><tr><th>Врач</th><th class="num">Поступило</th><th class="num">План</th><th>Выполнение</th><th class="num">Прогноз</th><th class="num">Приёмов</th><th class="num">Загрузка</th></tr></thead><tbody>${
            r.doctors.map(d => `<tr><td title="${esc(d.name)}"><b>${esc(shortFio(d.name))}</b></td><td class="num">${rub(d.paid)}</td><td class="num">${d.plan ? rub(d.plan) : `<span class="muted">—</span>`}</td>
              <td class="meter-cell">${d.plan ? `${meter(d.plan_pct, pace)}<span class="num-s">${pctT(d.plan_pct)}</span>` : `<span class="muted">план не задан</span>`}</td>
              <td class="num">${rub(d.forecast)}</td><td class="num">${d.visits}</td>
              <td class="num" title="${d.by_shifts ? "По графику работы" : "По дням, когда были приёмы"}">${pctT(d.load)}</td></tr>`).join("")}</tbody></table></div>`
            : `<div class="empty sm"><span>В этом месяце приёмов и оплат пока нет</span></div>`}
          <div class="muted note-line dir-note">Метка на полосе — сколько должно быть выполнено к сегодняшнему дню. Загрузка — занятое время приёмов от рабочего времени по графику.</div></div>
        <div class="pbody rep-card"><div class="pb-head"><b>Поступления по дням</b><span class="muted">${fmtShort(m.from)} — ${fmtShort(m.to)}</span></div>
          ${colChart(days, x => x.paid, x => `${fmtShort(x.day)}: ${money(x.paid)}`, money)}</div>
      </div>
      <div class="dir-col">
        <div class="pbody"><div class="pb-head"><b>На что обратить внимание</b></div>
          <ul class="advice">${r.advice.map((a, i) => `<li class="adv-${a.level}" data-adv="${i}" role="button" tabindex="0"><span class="adv-ic" title="${ADV_LABEL[a.level]}">${ADV_ICON[a.level] || ADV_ICON.info}</span><span>${esc(a.text)}</span></li>`).join("")}</ul></div>
        <div class="pbody"><div class="pb-head"><b>Запись на неделю вперёд</b><span class="muted">${r.chairs} ${plural(r.chairs, "кресло", "кресла", "кресел")}, ${r.hours[0]}:00–${r.hours[1]}:00</span></div>
          ${r.ahead.length ? `<table class="tbl compact ahead"><tbody>${r.ahead.map(a => `<tr data-day="${a.day}" class="lnk-row"><td>${a.wd}, ${fmtShort(a.day).slice(0, 5)}</td>
            <td class="bar-cell">${hbar(a.load, 100)}</td><td class="num">${pctT(a.load)}</td><td class="num muted">${a.visits} ${plural(a.visits, "запись", "записи", "записей")}</td></tr>`).join("")}</tbody></table>`
            : `<div class="empty sm"><span>Рабочих дней впереди нет</span></div>`}</div>
      </div>
    </div>
    <div class="muted note-line">Деньги — счета и оплаты, проведённые в программе. Прогноз — поступления за прошедшие рабочие дни, продолженные до конца месяца.</div>`;
  $$("[data-kpi]", body).forEach(b => b.onclick = () => openKpi());
  if (typeof dirProfitTile === "function") dirProfitTile($(".dir-tiles", body));  // 2.15: profit and break-even
  if (typeof aiWeeklyCard === "function") aiWeeklyCard($$(".dir-col", body)[1]);  // 2.13 (14.8): the weekly summary
  $$("#dirBody .ahead [data-day]").forEach(tr => tr.onclick = () => { S.day = tr.dataset.day; show("schedule"); });
  const go = a => {
    if (a.go === "plan") return openKpi();
    if (a.go === "crm") { S.mkTab = "tasks"; S.crmScope = "overdue"; return show("marketing"); }
    if (a.go === "schedule") { S.day = (r.ahead[0] || {}).day || S.day; return show("schedule"); }
    S.repTab = a.go; $$("#repTabs button").forEach(x => x.classList.toggle("on", x.dataset.k === a.go)); show("reports");
  };
  $$("#dirBody [data-adv]").forEach(li => { const a = r.advice[+li.dataset.adv]; li.onclick = () => go(a); li.onkeydown = e => { if (e.key === "Enter") go(a); }; });
}
$("#dirPlan").onclick = () => openKpi();
$("#dirPrint").onclick = async () => {
  $("#printArea").innerHTML = `${typeof clinicHead === "function" ? await clinicHead() : ""}<h2>Сводка директора</h2><div>${esc($("#dirSub").textContent)}</div>${
    [...$$("#dirBody .stat")].map(s => `<p><b>${esc($("span", s).textContent)}:</b> ${esc($("b", s).textContent)}</p>`).join("")}${($("#dirDocs") || {outerHTML: ""}).outerHTML.replace(/<span class="meter">.*?<\/span>/g, "")}
    <h3>На что обратить внимание</h3><ul>${(S.dir ? S.dir.advice : []).map(a => `<li>${esc(a.text)}</li>`).join("")}</ul>`;
  window.print();
};

/* ---------------------------------------------------- plan for the month */
async function openKpi(month) {
  month = month || (S.kpiMonth = S.kpiMonth || iso(new Date()).slice(0, 7));
  S.kpiMonth = month;
  let k, st;
  try { [k, st] = await Promise.all([api.kpi(month), api.director_settings()]); } catch (e) { return toast(errText(e), true); }
  const keys = Object.keys(k.metrics);
  const cell = (row, key) => {
    const x = row.metrics[key], isRub = key === "revenue";
    const f = isRub ? rub(x.fact) : x.fact, fc = isRub ? rub(x.forecast) : x.forecast;
    return `<td class="kpi-in"><input class="input num" data-s="${esc(row.scope)}" data-m="${key}" type="number" min="0" step="any" value="${x.plan ?? ""}" placeholder="—"></td>
      <td class="num kpi-fact">${f}${x.plan ? `<small class="muted">${pctT(x.pct)}</small>` : ""}${k.current ? `<small class="muted" title="Прогноз до конца месяца">прогноз ${fc}</small>` : ""}</td>`;
  };
  const rows = [k.clinic, ...k.doctors];
  const box = modal(`<div class="m-h"><h3>План на месяц</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="kpi-month"><button class="icon-btn" id="kpPrev" title="Предыдущий месяц"><svg viewBox="0 0 24 24"><path d="m14.5 6-6 6 6 6"/></svg></button>
        <b>${esc(monthName(month))}</b><button class="icon-btn" id="kpNext" title="Следующий месяц"><svg viewBox="0 0 24 24"><path d="m9.5 6 6 6-6 6"/></svg></button>
        <span class="grow"></span>${k.prev_has_plan ? `<button class="btn ghost small" id="kpCopy">Как в прошлом месяце</button>` : ""}</div>
      <div class="tbl-scroll"><table class="tbl compact kpi-tbl"><thead><tr><th></th>${keys.map(x => `<th colspan="2">${esc(k.metrics[x])}</th>`).join("")}</tr>
        <tr class="sub"><th></th>${keys.map(() => `<th>План</th><th class="num">Факт</th>`).join("")}</tr></thead>
        <tbody>${rows.map(r => `<tr class="${r.scope === "clinic" ? "kpi-clinic" : ""}"><td><b>${esc(r.name)}</b></td>${keys.map(x => cell(r, x)).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="grid2 kpi-set"><label class="fl">Кресел в клинике (для загрузки)<input class="input num" id="kpChairs" type="number" min="1" max="60" value="${st.chairs ?? ""}" placeholder="по записям: ${st.chairs_seen || "—"}"></label>
        <div class="muted note-line">Рабочие часы — ${st.hours[0]}:00–${st.hours[1]}:00 (Настройки → «Расписание»). Поступления — оплаты по счетам врача. Приёмы — визиты, которые состоялись; прогноз приёмов — с учётом уже записанных.</div></div>
      <div class="auth-err" id="kpErr"></div></div>
    <div class="m-f"><span class="muted">Пустое поле — план не задан</span><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="kpOk">Сохранить</button></div>`, {wide: true});
  $("#kpPrev", box).onclick = () => openKpi(shiftMonth(month, -1));
  $("#kpNext", box).onclick = () => openKpi(shiftMonth(month, 1));
  const after = () => { if (S.view === "director") loadDirector(); };
  const cp = $("#kpCopy", box);
  if (cp) cp.onclick = async () => {
    if (rows.some(r => keys.some(x => r.metrics[x].plan != null)) && !await ask("Заменить план этого месяца планом прошлого?", {ok: "Заменить"})) return;
    try { await api.kpi_save(month, [], true); toast("План скопирован"); openKpi(month); after(); } catch (e) { $("#kpErr").textContent = errText(e); }
  };
  $("#kpOk", box).onclick = async () => {
    try {
      const items = $$("[data-s]", box).map(i => ({scope: i.dataset.s, metric: i.dataset.m, value: i.value.trim()}));
      await api.kpi_save(month, items);
      await api.director_settings_save({chairs: $("#kpChairs").value.trim()});
      closeModal(); toast("План сохранён"); after();
    } catch (e) { $("#kpErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------------ reports: patients */
async function repPatients(body) {
  const r = await api.report_patients(S.period.from, S.period.to);
  const maxM = Math.max(0, ...r.by_month.map(m => m.new + m.repeat));
  const rd = r.return_days.map(n => Math.round(n / 30));
  body.innerHTML = repTools() + `<div class="stat-row">
      <div class="stat"><span>Пациентов на приёме</span><b>${r.patients}</b><small class="muted">${r.visits} ${plural(r.visits, "приём", "приёма", "приёмов")}</small></div>
      <div class="stat"><span>Новые</span><b>${r.new} <small class="muted">${pctT(r.new_share)}</small></b></div>
      <div class="stat"><span>Повторные</span><b>${r.repeat}</b></div>
      <div class="stat"><span>Выставлено новым</span><b>${money(r.revenue_new)}</b><small class="muted">повторным ${money(r.revenue_repeat)}</small></div>
      <div class="stat ${r.gone ? "warn" : ""}"><span>Перестали ходить</span><b>${r.gone}</b>${can("marketing") && r.gone ? `<button class="linkbtn" id="rpGone">Обзвонить →</button>` : `<small class="muted">не были ${Math.round(r.gone_days[0] / 30)}–${Math.round(r.gone_days[1] / 30)} мес.</small>`}</div></div>
    ${r.history_short ? `<div class="note-box">История визитов в программе — с ${fmtShort(r.history_from)}. Пациенты, которые приходили раньше, в начале истории считаются новыми; со временем цифры станут точными.</div>` : ""}
    <div class="rep-grid">
      <div class="pbody"><div class="pb-head"><b>Новые и повторные по месяцам</b></div>
        ${r.by_month.length ? `<table class="tbl compact"><thead><tr><th>Месяц</th><th class="num">Новые</th><th class="num">Повторные</th><th class="bar-h"></th><th class="num">Доля новых</th></tr></thead><tbody>${
          r.by_month.map(m => `<tr><td>${esc(monthName(m.month))}</td><td class="num">${m.new}</td><td class="num">${m.repeat}</td><td class="bar-cell">${hbar(m.new + m.repeat, maxM)}</td><td class="num muted">${pct(m.new, m.new + m.repeat)}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty sm"><span>За период приёмов не было</span></div>`}</div>
      <div class="pbody"><div class="pb-head"><b>Удержание: сколько новых пациентов вернулись</b></div>
        ${r.cohorts.length ? `<table class="tbl compact"><thead><tr><th>Первый визит</th><th class="num">Новых</th>${rd.map(n => `<th class="num" title="Доля вернувшихся в течение ${n} мес. после первого визита">За ${n} мес.</th>`).join("")}</tr></thead><tbody>${
          r.cohorts.map(c => `<tr><td>${esc(monthName(c.month))}</td><td class="num">${c.new}</td>${r.return_days.map(n => `<td class="num">${c["p" + n] == null ? `<span class="muted" title="Прошло меньше ${Math.round(n / 30)} мес.">рано</span>` : pctT(c["p" + n])}</td>`).join("")}</tr>`).join("")}</tbody></table>`
          : `<div class="empty sm"><span>Новых пациентов за год нет</span></div>`}</div></div>
    <div class="pbody" style="margin-top:12px">${r.by_doctor.length ? `<table class="tbl"><thead><tr><th>Врач</th><th class="num">Приёмов</th><th class="num">Новых пациентов</th><th class="num">Повторных</th><th class="num">Доля новых</th></tr></thead><tbody>${
      r.by_doctor.map(d => `<tr><td><b>${esc(d.name)}</b></td><td class="num">${d.visits}</td><td class="num">${d.new}</td><td class="num">${d.repeat}</td><td class="num muted">${pct(d.new, d.new + d.repeat)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty sm"><span>За период приёмов не было</span></div>`}</div>
    <div class="muted note-line">Новый пациент — первый состоявшийся визит в программе приходится на период. Вернулся — был ещё раз в течение 3 или 6 месяцев после первого визита. «Перестали ходить» — последний визит ${Math.round(r.gone_days[0] / 30)}–${Math.round(r.gone_days[1] / 30)} месяцев назад и нет новой записи.</div>`;
  const g = $("#rpGone"); if (g) g.onclick = () => { S.mkTab = "calls"; S.mkList = "lost"; show("marketing"); };
}

/* ---------------------------------------------------------- reports: load */
async function repLoad(body) {
  const r = await api.report_load(S.period.from, S.period.to);
  const days = r.by_day.map(x => ({...x, _x: dayLbl(x.day)}));
  const free = Math.max(0, r.capacity - r.booked);
  const hours = Array.from({length: r.hours[1] - r.hours[0]}, (_, i) => r.hours[0] + i);
  const heatCell = v => `<td class="hm" style="--a:${Math.min(100, v)}%" title="${pctT(v)}"><span>${v >= 1 ? Math.round(v) : ""}</span></td>`;
  body.innerHTML = repTools(`<button class="btn ghost small" id="rlChairs">Кресел: ${r.chairs}</button>`) + `<div class="stat-row">
      <div class="stat ${r.load < 50 ? "warn" : ""}"><span>Загрузка кресел</span><b>${pctT(r.load)}</b>${meter(r.load)}</div>
      <div class="stat"><span>Занято часов</span><b>${hrs(r.booked)}</b><small class="muted">из ${hrs(r.capacity)}</small></div>
      <div class="stat"><span>Свободно часов</span><b>${hrs(free)}</b></div>
      <div class="stat ${r.lost ? "warn" : ""}"><span>Потеряно часов на отменах и неявках</span><b>${hrs(r.lost)}</b></div>
      <div class="stat"><span>Рабочих дней</span><b>${r.workdays}</b><small class="muted">${r.hours[0]}:00–${r.hours[1]}:00</small></div></div>
    <div class="pbody rep-card" style="margin-bottom:12px"><div class="pb-head"><b>Загрузка по дням</b><span class="muted">${periodText()}</span></div>
      ${colChart(days, x => x.load, x => `${fmtShort(x.day)}: ${pctT(x.load)}, занято ${hrs(x.booked)} ч`, v => pctT(v))}</div>
    <div class="pbody" style="margin-bottom:12px"><div class="pb-head"><b>Когда кресла заняты</b><span class="muted">доля занятого времени по дням недели и часам</span></div>
      ${r.heat.length ? `<div class="tbl-scroll"><table class="tbl compact heat"><thead><tr><th></th>${hours.map(h => `<th class="num">${h}</th>`).join("")}<th class="num">Отмены и неявки</th></tr></thead><tbody>${
        r.heat.map(w => `<tr><td><b>${w.wd}</b></td>${w.cells.map(heatCell).join("")}<td class="num ${w.lost_share >= 15 ? "bad-t" : "muted"}">${pctT(w.lost_share)}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="empty sm"><span>Нет данных за период</span></div>`}</div>
    <div class="rep-stack">
      <div class="pbody">${r.by_doctor.length ? `<table class="tbl"><thead><tr><th>Врач</th><th class="num">Приёмов</th><th class="num">Занято, ч</th><th class="num">Рабочее время, ч</th><th>Загрузка</th><th class="num">Потеряно, ч</th></tr></thead><tbody>${
        r.by_doctor.map(d => `<tr><td title="${esc(d.name)}"><b>${esc(shortFio(d.name))}</b></td><td class="num">${d.visits}</td><td class="num">${hrs(d.booked)}</td>
          <td class="num" title="${d.by_shifts ? "По графику работы" : "По дням, когда были приёмы"}">${hrs(d.available)}${d.by_shifts ? "" : ` <small class="muted">*</small>`}</td>
          <td class="meter-cell">${meter(d.load)}<span class="num-s">${pctT(d.load)}</span></td><td class="num ${d.lost ? "bad-t" : ""}">${hrs(d.lost)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty sm"><span>За период приёмов не было</span></div>`}</div>
      <div class="pbody">${r.by_chair.length ? `<table class="tbl compact"><thead><tr><th>Кресло</th><th class="num">Приёмов</th><th class="num">Занято, ч</th><th>Загрузка</th></tr></thead><tbody>${
        r.by_chair.map(c => `<tr><td>${c.chair ? esc(/^\d+$/.test(c.chair) ? "Кресло " + c.chair : c.chair) : `<span class="muted">Кресло не указано</span>`}</td><td class="num">${c.visits}</td><td class="num">${hrs(c.booked)}</td>
          <td class="meter-cell">${c.load == null ? "" : `${meter(c.load)}<span class="num-s">${pctT(c.load)}</span>`}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty sm"><span>Кресла в записях не указаны</span></div>`}</div></div>
    <div class="muted note-line">Загрузка — время записей (без отмен и неявок) от рабочего времени кресел: ${r.chairs} ${plural(r.chairs, "кресло", "кресла", "кресел")} × ${r.hours[1] - r.hours[0]} ч × рабочие дни. Рабочее время врача — по графику работы; * — графика нет, считаются дни, когда были приёмы.</div>`;
  $("#rlChairs").onclick = async () => {
    const st = await api.director_settings();
    const v = await askInput("Кресел в клинике", [{label: "Сколько кресел", value: st.chairs ?? "", type: "number", required: false}],
      {text: `Пусто — посчитать по записям (сейчас ${st.chairs_seen || "не указано"}).`});
    if (v == null) return;
    try { await api.director_settings_save({chairs: v[0]}); toast("Сохранено"); loadReports(); } catch (e) { toast(errText(e), true); }
  };
}

/* ---------------------------------------------------- reports: conversion */
async function repConversion(body) {
  const r = await api.report_conversion(S.period.from, S.period.to), t = r.total;
  const fun = [["Первичный приём", t.consult], ["Составлен план", t.with_plan], ["Начали лечение", t.started]];
  body.innerHTML = repTools() + `<div class="stat-row">
      <div class="stat"><span>Первичных приёмов</span><b>${t.consult}</b></div>
      <div class="stat"><span>Получили план</span><b>${t.with_plan} <small class="muted">${pctT(t.plan_rate)}</small></b></div>
      <div class="stat"><span>Начали лечение</span><b>${t.started} <small class="muted">${pctT(t.start_rate)}</small></b></div>
      <div class="stat"><span>Планов составлено</span><b>${t.plans}</b><small class="muted">на ${money(t.plans_sum)}</small></div>
      <div class="stat"><span>Начато по планам</span><b>${pctT(t.plans_rate)}</b><small class="muted">на ${money(t.sum_started)} · ${pctT(t.sum_rate)} суммы</small></div></div>
    <div class="pbody" style="margin-bottom:12px"><div class="pb-head"><b>Воронка: консультация → план → лечение</b><span class="muted">${periodText()}</span></div>
      <div class="funnel">${fun.map(([k, v], i) => `<div class="fn-row"><span>${k}</span>${hbar(v, t.consult || 1)}<b>${v}</b><small class="muted">${i ? pct(v, t.consult) : ""}</small></div>`).join("")}</div></div>
    <div class="pbody">${r.by_doctor.length ? `<div class="tbl-scroll"><table class="tbl"><thead><tr><th>Врач</th><th class="num">Первичных</th><th class="num">С планом</th><th class="num">Начали лечение</th><th class="num">Планов</th><th class="num">На сумму</th><th class="num">Начато</th><th class="num">Начато на сумму</th><th class="num">Отказ</th><th class="num">Выставлено по планам</th></tr></thead><tbody>${
      r.by_doctor.map(d => `<tr><td title="${esc(d.name)}"><b>${esc(shortFio(d.name))}</b></td><td class="num">${d.consult}</td><td class="num">${d.with_plan} <small class="muted">${pctT(d.plan_rate)}</small></td>
        <td class="num">${d.started} <small class="muted">${pctT(d.start_rate)}</small></td><td class="num">${d.plans}</td><td class="num">${money(d.plans_sum)}</td>
        <td class="num">${d.plans_started} <small class="muted">${pctT(d.plans_rate)}</small></td><td class="num">${money(d.sum_started)}</td>
        <td class="num ${d.refused ? "bad-t" : ""}">${d.refused}</td><td class="num">${money(d.billed)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty"><b>За период нет первичных приёмов и планов</b></div>`}</div>
    <div class="muted note-line">Первичный приём — первый состоявшийся визит пациента в программе; врач — тот, кто его принял. Начатым считается план в статусе «Активен» или «Лечение завершено» либо план, по которому уже выставлен счёт.</div>`;
}
