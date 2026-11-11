"use strict";
/* 3.4: the owner's management accounting and the staff's time.
   «Бухгалтерия» → «ОПиУ» (profit and loss by months), «Деньги» (cash flow by days / months and accounts),
   «Мотивация» (the administrators' bonus rules and the month); the report for a week / a month (preview and send);
   «Графики» → «Табель» (arrival and leaving against the schedule); «Я пришёл» / «Я ушёл» in the user menu. */
S.pnlTo = iso(new Date()).slice(0, 7);
S.pnlN = 6;
S.cfGroup = "day";
S.motMonth = iso(new Date()).slice(0, 7);
S.tsMonth = iso(new Date()).slice(0, 7);
S.shTab = "plan";
const fsMoney = v => money(v);
const fsH = v => (+v || 0).toLocaleString("ru-RU", {maximumFractionDigits: 1});
const fsShare = s => s == null ? "—" : `${(+s).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
const DP_PAY_NOTE = `<div class="note-box fs-dp">Оплаты, принятые только в Dentist Plus, здесь не видны: <b>в API Dentist Plus нет оплат</b>. Суммы — по оплатам и расходам, проведённым в этой программе.</div>`;

/* ------------------------------------------------------------ ОПиУ: profit and loss by months */
async function accPnl(body) {
  const from = shiftMonth(S.pnlTo, -(S.pnlN - 1));
  let r;
  try { r = await api.fin_pnl(from, S.pnlTo); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  const cls = x => x.kind === "total" ? "fm-total" : x.kind === "group" ? "fm-group" : "fm-sub";
  const cell = (v, x) => `<td class="num ${x.profit && v < 0 ? "bad-t" : ""}">${v ? money(v) : `<span class="muted">—</span>`}</td>`;
  body.innerHTML = accTools(`<div class="month-nav"><button class="icon-btn" id="pnPrev" title="Раньше">‹</button><b>${esc(r.titles[0])} — ${esc(r.titles[r.titles.length - 1])}</b><button class="icon-btn" id="pnNext" title="Позже">›</button></div>
      <div class="seg sm" id="pnN">${[3, 6, 12].map(n => `<button data-n="${n}" class="${S.pnlN === n ? "on" : ""}">${n} мес.</button>`).join("")}</div>
      <button class="btn ghost" id="pnRep">Отчёт владельцу</button>`, false) +
    `${r.no_schemes ? `<div class="note-box">Схемы оплаты не заданы — зарплата попадает в расчёт только по выплатам. Задайте их во вкладке «Зарплата».</div>` : ""}
    <div class="stat-row">
      <div class="stat"><span>Поступления за ${r.months.length} мес.</span><b>${rub(r.revenue_total)}</b></div>
      <div class="stat"><span>Зарплата (начислено)</span><b>${rub(r.salaries_total)}</b><small class="muted">${fsShare(r.revenue_total ? r.salaries_total * 100 / r.revenue_total : null)} поступлений</small></div>
      <div class="stat ${r.net_total < 0 ? "warn" : ""}"><span>${r.net_total < 0 ? "Чистый убыток" : "Чистая прибыль"}</span><b>${rub(r.net_total)}</b><small class="muted">${fsShare(r.revenue_total ? r.net_total * 100 / r.revenue_total : null)} поступлений</small></div></div>
    <div class="pbody"><div class="tbl-scroll"><table class="tbl compact fm-pnl fs-pnl" id="pnTbl"><thead><tr><th>Статья</th>${r.titles.map((t, i) => `<th class="num">${esc(t)}${r.current[i] ? `<br><small class="muted">идёт</small>` : ""}</th>`).join("")}<th class="num">Итого</th><th class="num">Доля</th></tr></thead><tbody>
      ${r.rows.map(x => `<tr class="${cls(x)}"><td>${x.kind === "group" ? "− " : ""}${esc(x.name)}</td>${x.values.map(v => cell(v, x)).join("")}<td class="num"><b>${money(x.total)}</b></td><td class="num muted">${fsShare(x.share)}</td></tr>`).join("")}
      <tr class="fs-sal"><td>в т. ч. зарплата (врачи + персонал)</td>${r.salaries.map(v => `<td class="num muted">${v ? money(v) : "—"}</td>`).join("")}<td class="num muted">${money(r.salaries_total)}</td><td></td></tr>
    </tbody></table></div>
    <div class="muted note-line">Каждый месяц посчитан так же, как во вкладке «Финмодель»: зарплата — начисленная по схемам оплаты (вместе с мотивацией администраторов), выплаты не считаются второй раз. Расходы без документов входят в статьи.</div></div>
    ${DP_PAY_NOTE}`;
  $("#pnPrev").onclick = () => { S.pnlTo = shiftMonth(S.pnlTo, -S.pnlN); loadAccounting(); };
  $("#pnNext").onclick = () => { S.pnlTo = shiftMonth(S.pnlTo, S.pnlN); loadAccounting(); };
  $$("#pnN button").forEach(b => b.onclick = () => { S.pnlN = +b.dataset.n; loadAccounting(); });
  $("#pnRep").onclick = () => openPeriodReport("month");
}

/* ------------------------------------------------------------ Деньги: cash flow */
async function accCashflow(body) {
  let r;
  try { r = await api.fin_cashflow(S.period.from, S.period.to, S.cfGroup); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  const accs = r.accounts;
  const lbl = p => r.group === "month" ? monthName(p) : fmtShort(p);
  const ins = Object.entries(r.in_by_method), outs = Object.entries(r.out_by_category);
  const iMax = Math.max(0, ...ins.map(x => x[1])), oMax = Math.max(0, ...outs.map(x => x[1]));
  body.innerHTML = accTools(`<div class="seg sm" id="cfG"><button data-g="day" class="${r.group === "day" ? "on" : ""}">По дням</button><button data-g="month" class="${r.group === "month" ? "on" : ""}">По месяцам</button></div>
      <button class="btn ghost" id="cfRep">Отчёт владельцу</button>`) +
    `<div class="stat-row">
      <div class="stat"><span>Пришло денег</span><b>${rub(r.in)}</b>${r.certs ? `<small class="muted">в т. ч. сертификаты ${rub(r.certs)}</small>` : ""}</div>
      <div class="stat"><span>Ушло денег</span><b>${rub(r.out)}</b>${r.refunds ? `<small class="muted">в т. ч. возвраты ${rub(r.refunds)}</small>` : ""}</div>
      <div class="stat ${r.net < 0 ? "warn" : ""}"><span>Итог</span><b>${rub(r.net)}</b></div>
      <div class="stat"><span>Расходы с документами</span><b>${rub(r.out_doc)}</b></div>
      <div class="stat ${r.out_nodoc ? "warn" : ""}"><span>Без документов (внутренние)</span><b>${rub(r.out_nodoc)}</b></div></div>
    <div class="pbody"><div class="pb-head"><b>Где деньги</b><span class="muted">за период</span></div><div class="tbl-scroll"><table class="tbl compact"><thead><tr><th>Счёт</th><th class="num">Пришло</th><th class="num">Ушло</th><th class="num">Внесено / изъято</th><th class="num">Итог</th></tr></thead><tbody>
      ${accs.map(a => `<tr><td><b>${esc(a.name)}</b></td><td class="num">${money(a.in)}</td><td class="num">${money(a.out)}</td><td class="num muted">${a.moves_in || a.moves_out ? `+${money(a.moves_in)} / −${money(a.moves_out)}` : "—"}</td><td class="num ${a.net < 0 ? "bad-t" : ""}"><b>${money(a.net)}</b></td></tr>`).join("")}
    </tbody></table></div>${Object.keys(r.moves).length ? `<div class="muted note-line">Касса: ${Object.entries(r.moves).map(([k, v]) => `${esc(k)} ${money(v)}`).join(" · ")} — перемещения внутри клиники, в итог движения не входят.</div>` : ""}</div>
    <div class="rep-grid">
      <div class="pbody rep-card"><div class="pb-head"><b>Откуда пришли</b></div>${ins.length ? `<table class="tbl compact"><tbody>${ins.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${money(v)}</td><td class="bar-cell">${hbar(v, iMax)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty sm"><span>Поступлений нет</span></div>`}</div>
      <div class="pbody rep-card"><div class="pb-head"><b>На что ушли</b></div>${outs.length ? `<table class="tbl compact"><tbody>${outs.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${money(v)}</td><td class="bar-cell">${hbar(v, oMax)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty sm"><span>Расходов нет</span></div>`}</div></div>
    <div class="pbody"><div class="pb-head"><b>${r.group === "month" ? "По месяцам" : "По дням"}</b><span class="muted">нарастающий итог — с начала периода</span></div>${r.rows.length ? `<div class="tbl-scroll"><table class="tbl compact" id="cfTbl"><thead><tr><th>${r.group === "month" ? "Месяц" : "День"}</th>${accs.map(a => `<th class="num">${esc(a.name)}</th>`).join("")}<th class="num">Пришло</th><th class="num">Ушло</th><th class="num">Итог</th><th class="num">Нарастающий</th></tr></thead><tbody>
      ${r.rows.map(x => `<tr><td>${esc(lbl(x.period))}</td>${accs.map(a => { const v = x.by_acc[a.key]; return `<td class="num muted">${v ? `${v.in ? "+" + money(v.in) : ""}${v.in && v.out ? "<br>" : ""}${v.out ? "−" + money(v.out) : ""}` : "—"}</td>`; }).join("")}
        <td class="num">${money(x.in)}</td><td class="num">${money(x.out)}</td><td class="num ${x.net < 0 ? "bad-t" : ""}"><b>${money(x.net)}</b></td><td class="num ${x.cum < 0 ? "bad-t" : ""}">${money(x.cum)}</td></tr>`).join("")}
      </tbody><tfoot><tr><td>Итого</td>${accs.map(a => `<td class="num">${money(a.in - a.out)}</td>`).join("")}<td class="num">${money(r.in)}</td><td class="num">${money(r.out)}</td><td class="num">${money(r.net)}</td><td></td></tr></tfoot></table></div>`
      : `<div class="empty sm"><span>За период деньги не двигались</span></div>`}</div>
    ${r.shifts.length ? `<div class="pbody"><div class="pb-head"><b>Сверка кассы по сменам</b><span class="muted">${r.shift_diffs ? `с расхождением: ${r.shift_diffs}` : "расхождений нет"}</span></div><div class="tbl-scroll"><table class="tbl compact"><thead><tr><th>Смена</th><th class="num">Наличные по расчёту</th><th class="num">Пересчитано</th><th class="num">Разница</th><th class="num">Карта: терминал − расчёт</th><th class="num">СБП: банк − расчёт</th></tr></thead><tbody>
      ${r.shifts.map(s => `<tr><td>${esc(fmtShort(s.opened_at))} ${esc((s.opened_at || "").slice(11, 16))}${s.closed_at ? "" : ` <span class="pill">открыта</span>`}</td><td class="num">${money(s.expected_cash)}</td><td class="num">${s.counted_cash == null ? "—" : money(s.counted_cash)}</td>
        <td class="num ${Math.abs(s.diff_cash || 0) >= 0.01 ? "bad-t" : ""}">${s.diff_cash == null ? "—" : money(s.diff_cash)}</td><td class="num ${Math.abs(s.diff_card || 0) >= 0.01 ? "bad-t" : ""}">${s.diff_card == null ? "—" : money(s.diff_card)}</td><td class="num ${Math.abs(s.diff_sbp || 0) >= 0.01 ? "bad-t" : ""}">${s.diff_sbp == null ? "—" : money(s.diff_sbp)}</td></tr>`).join("")}
    </tbody></table></div></div>` : ""}
    <div class="pbody"><div class="pb-head"><b>Сверка с оплатами Dentist Plus</b><span class="muted">нет данных из Dentist Plus</span></div><div class="muted note-line">API Dentist Plus не отдаёт оплаты, поэтому сверить кассу этой программы с оплатами в Dentist Plus автоматически нельзя. Сверка по сменам выше — касса против терминала и банка.</div></div>
    ${DP_PAY_NOTE}`;
  $$("#cfG button").forEach(b => b.onclick = () => { S.cfGroup = b.dataset.g; loadAccounting(); });
  $("#cfRep").onclick = () => openPeriodReport("week");
}

/* ------------------------------------------------------------ Мотивация администраторов */
async function accMotivation(body) {
  let rules, m;
  try { [rules, m] = await Promise.all([api.motivation_rules(), api.motivation_month(S.motMonth)]); }
  catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  const F = rules.fields, title = Object.fromEntries(F.map(f => [f.key, f]));
  const ruleText = x => !x ? "—" : F.filter(f => x[f.key] > 0).map(f => `${f.unit === "%" ? fsH(x[f.key]) + " %" : money(x[f.key])} — ${f.title.toLowerCase()}`).join("; ") || "не задано";
  const item = it => {
    const f = title[it.rule] || {title: it.rule};
    const how = it.rule === "per_visit" ? `${it.count} из ${it.of} записей × ${money(it.rate)}`
      : it.rule === "per_new" || it.rule === "lead_came" || it.rule === "plan_back" ? `${it.count} × ${money(it.rate)}`
      : it.rule === "plan_bonus" ? (it.plan ? `план ${money(it.plan)}, факт ${money(it.fact)} — ${it.done ? "выполнен" : "не выполнен"}` : "план клиники на месяц не задан")
      : `${fsH(it.rate)} % от ${money(it.base)}`;
    return `<div class="mot-it"><span>${esc(f.title)}</span><small class="muted">${esc(how)}</small><b>${money(it.amount)}</b></div>`;
  };
  body.innerHTML = accTools(`<div class="month-nav"><button class="icon-btn" id="mtPrev" title="Предыдущий месяц">‹</button><b>${monthName(m.month)}</b><button class="icon-btn" id="mtNext" title="Следующий месяц">›</button></div>`, false) +
    `<div class="stat-row"><div class="stat"><span>Мотивация за месяц</span><b>${rub(m.total)}</b><small class="muted">входит в «Зарплату» и в прибыль</small></div></div>
    <div class="pbody"><div class="pb-head"><b>Начислено за ${esc(monthName(m.month).toLowerCase())}</b></div>${m.rows.length ? `<div class="mot-rows">${m.rows.map(r => `<div class="mot-row"><div class="mot-h"><b>${esc(r.name)}</b><span class="muted">${esc(r.position || "")}${r.own ? "" : " · общее правило для администраторов"}</span><b class="mot-sum">${money(r.total)}</b></div>${r.items.map(item).join("")}</div>`).join("")}</div>`
      : `<div class="empty sm"><b>Пока ничего не начислено</b><span>Задайте правила ниже — по умолчанию всё по нулям, зарплата не меняется</span></div>`}
      <div class="muted note-line">${esc(m.note)} Пришедшим считается визит со статусом «пришёл» или «завершён».</div></div>
    <div class="pbody"><div class="pb-head"><b>Правила</b><span class="muted">общее для всех администраторов или своё для сотрудника</span></div>
      <table class="tbl compact"><tbody>
        <tr class="lnk-row" data-mp="*"><td><b>Все администраторы</b><br><small class="muted">сотрудники с должностью на основе «Администратор»</small></td><td class="muted">${esc(ruleText(rules.all))}</td><td class="row-acts"><button class="linkbtn">изменить</button></td></tr>
        ${rules.staff.map(s => `<tr class="lnk-row" data-mp="${esc(s.key)}"><td><b>${esc(s.name)}</b>${s.position ? `<br><small class="muted">${esc(s.position)}</small>` : ""}</td>
          <td class="muted">${s.own ? esc(ruleText(s.rule)) : s.from_all ? "общее правило" : "нет"}</td><td class="row-acts"><button class="linkbtn">${s.own ? "изменить" : "своё правило"}</button></td></tr>`).join("")}
      </tbody></table>
      ${rules.staff.length ? "" : `<div class="muted note-line">Сотрудники появятся после одобрения их заявок в разделе «Сотрудники».</div>`}</div>`;
  $("#mtPrev").onclick = () => { S.motMonth = shiftMonth(S.motMonth, -1); loadAccounting(); };
  $("#mtNext").onclick = () => { S.motMonth = shiftMonth(S.motMonth, 1); loadAccounting(); };
  $$("#accBody [data-mp]").forEach(tr => tr.onclick = () => editMotivation(tr.dataset.mp, rules));
}

function editMotivation(key, rules) {
  const s = key === "*" ? null : rules.staff.find(x => x.key === key);
  const cur = (s ? (s.own ? s.rule : rules.all) : rules.all) || {};
  const box = modal(`<div class="m-h"><h3>Мотивация: ${esc(s ? s.name : "все администраторы")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${s && !s.own && s.from_all ? `<p class="muted">Сейчас действует общее правило для администраторов. Сохраните, чтобы задать своё.</p>` : ""}
      <div class="grid2">${rules.fields.map(f => `<label class="fl">${esc(f.title)}, ${f.unit}<input class="input num" type="number" min="0" step="any" ${f.unit === "%" ? 'max="100"' : ""} data-mf="${f.key}" value="${cur[f.key] || ""}"></label>`).join("")}</div>
      <p class="hint">Всё, что 0, не начисляется. Записи считаются сделанные в этой программе (в Dentist Plus не видно, кто записал); продажи — оплаты по счетам, которые выставил сотрудник, и проданные им сертификаты; премия за план — если клиника выполнила план по поступлениям («Директор» → «План»).</p>
      <div class="auth-err" id="mfErr"></div></div>
    <div class="m-f">${s && s.own ? `<button class="btn ghost small" id="mfReset">Вернуть общее правило</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="mfOk">Сохранить</button></div>`, {wide: true});
  $("#mfOk", box).onclick = async () => {
    const f = {person: key};
    $$("[data-mf]", box).forEach(i => f[i.dataset.mf] = i.value || 0);
    try { await api.motivation_save(f); closeModal(); toast("Правило сохранено"); loadAccounting(); } catch (e) { $("#mfErr").textContent = errText(e); }
  };
  const rs = $("#mfReset", box);
  if (rs) rs.onclick = async () => { await api.motivation_save({person: key, reset: true}); closeModal(); loadAccounting(); };
}

/* ------------------------------------------------------------ the report for a week / a month */
async function openPeriodReport(kind = "week", start = null) {
  let r;
  try { r = await api.period_report(kind, start); } catch (e) { toast(errText(e), true); return; }
  const st = r.state;
  const box = modal(`<div class="m-h"><h3>Отчёт владельцу</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="row fs-pr-top"><div class="seg sm" id="prKind"><button data-k="week" class="${kind === "week" ? "on" : ""}">За неделю</button><button data-k="month" class="${kind === "month" ? "on" : ""}">За месяц</button></div>
        <div class="month-nav"><button class="icon-btn" id="prPrev" title="Раньше">‹</button><b>${esc(r.title)}</b><button class="icon-btn" id="prNext" title="Позже">›</button></div></div>
      <p class="muted">${st && st.status === "sent" ? `Отправлен ${esc(fmtShort(st.sent_at))} ${esc((st.sent_at || "").slice(11, 16))}: ${esc(st.where)}` : st && st.status === "error" ? `<span class="bad-t">Не отправлен: ${esc(st.error || "")}</span>` : r.channels.length ? "Уходит сам: за неделю — в понедельник, за месяц — 1-го числа, во время отчёта за день." : "Почта и Telegram не настроены: Настройки → «Касса и оплаты» → «Отчёт за день». Пока не настроено, отчёт никуда не уходит."}</p>
      <pre class="fs-pr-text">${esc(r.text)}</pre><div class="auth-err" id="prErr"></div></div>
    <div class="m-f"><span class="muted">${esc(r.subject)}</span><button class="btn ghost" data-close>Закрыть</button>${r.channels.length && can("accounting") ? `<button class="btn" id="prSend">Отправить сейчас</button>` : ""}</div>`, {wide: true});
  $$("#prKind button", box).forEach(b => b.onclick = () => { closeModal(); openPeriodReport(b.dataset.k); });
  const step = n => { const d = parseDay(r.from); if (kind === "week") d.setDate(d.getDate() + 7 * n); else d.setMonth(d.getMonth() + n); closeModal(); openPeriodReport(kind, iso(d)); };
  $("#prPrev", box).onclick = () => step(-1);
  $("#prNext", box).onclick = () => step(1);
  const sb = $("#prSend", box);
  if (sb) sb.onclick = async () => {
    sb.disabled = true; sb.textContent = "Отправляю…";
    try { const s = await api.period_report_send(kind, r.from, true); closeModal(); toast(`Отчёт отправлен: ${s.where}`); }
    catch (e) { $("#prErr").textContent = errText(e); sb.disabled = false; sb.textContent = "Отправить сейчас"; }
  };
}

/* ------------------------------------------------------------ «Графики» → «Табель» */
function bindShiftTabs() {
  $$("#shTabs button").forEach(b => {
    b.classList.toggle("on", b.dataset.k === S.shTab);
    b.onclick = () => { S.shTab = b.dataset.k; loadShifts(); };
  });
}

async function loadTimesheet() {
  bindShiftTabs();
  let r;
  try { r = await api.timesheet(S.tsMonth); } catch (e) { $("#shBody").innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  S.tsData = r;
  const today = iso(new Date()), wd = d => (parseDay(d).getDay() + 6) % 7;
  const ST = {ok: "ts-ok", late: "ts-late", early: "ts-late", absent: "ts-bad", noleave: "ts-bad", extra: "ts-extra", wait: "ts-wait", future: "ts-fut", untracked: "ts-fut"};
  const head = r.days.map(d => `<th class="sh-d ${wd(d) >= 5 ? "we" : ""} ${d === today ? "today" : ""}"><b>${+d.slice(8)}</b><small>${WD_SHORT[wd(d)]}</small></th>`).join("");
  const tip = (d, c) => [fmtShort(d), c.plan ? `график ${c.plan[0]}–${c.plan[1]}` : "вне графика", c.came ? `пришёл ${c.came}` : "", c.left ? `ушёл ${c.left}` : "",
    c.late ? `опоздание ${c.late} мин` : "", c.early ? `ушёл раньше на ${c.early} мин` : "", r.statuses[c.status] && !["ok", "late", "early"].includes(c.status) ? r.statuses[c.status] : "",
    c.edited ? "исправлено вручную" : "", c.note].filter(Boolean).join(" · ");
  const rows = r.rows.map(p => `<tr><th class="sh-p"><b>${esc(p.name)}</b><small class="muted">${esc(p.position || (p.kind === "doctor" ? "врач" : "сотрудник"))}</small></th>${
      r.days.map(d => { const c = p.cells[d]; return `<td class="sh-c ts-c ${wd(d) >= 5 ? "we" : ""} ${d === today ? "today" : ""} ${c ? "on " + (ST[c.status] || "") : ""} ${r.can_edit && d <= today ? "ed" : ""}" data-k="${esc(p.key)}" data-d="${d}" ${c ? `data-tip="${esc(tip(d, c))}"` : ""}>${c ? (c.came ? `<span>${hShort(c.came)}<i></i>${c.left ? hShort(c.left) : "…"}</span>` : `<span class="ts-none">${c.status === "absent" ? "нет" : hShort(c.plan[0])}</span>`) : ""}${c && c.edited ? `<em class="ts-ed" title="исправлено"></em>` : ""}</td>`; }).join("")}
      <td class="sh-t num ts-tot">${!p.tracked ? `<span class="muted">${fsH(p.totals.plan_h)} ч по графику<br><small>не отмечается</small></span>` : `<b>${fsH(p.totals.fact_h)}</b> из ${fsH(p.totals.plan_h)} ч<br><small class="${p.totals.late_n || p.totals.absent_n || p.totals.noleave_n ? "bad-t" : "muted"}">${[p.totals.late_n ? `опозд. ${p.totals.late_n}` : "", p.totals.absent_n ? `нет ${p.totals.absent_n}` : "", p.totals.noleave_n ? `без ухода ${p.totals.noleave_n}` : "", p.totals.extra_n ? `вне графика ${p.totals.extra_n}` : ""].filter(Boolean).join(", ") || "без замечаний"}</small>`}</td></tr>`).join("");
  const me = await api.time_me().catch(() => null);
  $("#shBody").innerHTML = `<div class="tab-tools rep-tools"><div class="month-nav"><button class="icon-btn" id="tsPrev" title="Предыдущий месяц">‹</button><b>${monthName(r.month)}</b><button class="icon-btn" id="tsNext" title="Следующий месяц">›</button></div>
      <button class="pill-btn" id="tsToday">Текущий месяц</button><span class="grow"></span>
      ${me && me.can ? `<span class="muted">${me.state === "out" ? "Вы ещё не отметились" : me.state === "in" ? `Вы пришли в ${esc(me.came)}` : `Вы пришли в ${esc(me.came)}, ушли в ${esc(me.left)}`}</span><button class="btn ${me.state === "in" ? "ghost" : ""}" id="tsClock">${me.state === "in" ? "Я ушёл" : "Я пришёл"}</button>` : ""}
      ${r.can_edit ? `<button class="icon-btn" id="tsSet" title="Допуск опоздания"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/></svg></button>` : ""}<button class="icon-btn" id="tsPrint" title="Печать табеля">${PRINT_ICON}</button></div>
    <div class="pbody sh-wrap">${r.rows.length ? `<table class="sh-tbl ts-tbl" id="tsTbl"><thead><tr><th class="sh-p">Сотрудник</th>${head}<th class="sh-t">Факт / график</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty"><b>${r.all ? "За месяц нет ни графика, ни отметок" : r.linked === false ? "Вы вошли не под своей учётной записью" : "У вас пока нет отметок за этот месяц"}</b><span>Сотрудник отмечает приход и уход кнопкой «Я пришёл» / «Я ушёл» — здесь или в меню своего имени вверху справа. График составляется во вкладке «График».</span></div>`}</div>
    <div class="ts-legend"><span class="ts-ok">по графику</span><span class="ts-late">опоздание или ранний уход (больше ${r.settings.late_grace} мин)</span><span class="ts-bad">нет отметки / нет ухода</span><span class="ts-extra">вне графика</span></div>
    <div class="muted note-line">${r.all ? "Табель виден тем, кто составляет графики, и директору; каждый сотрудник видит только свои дни. Кто за месяц ни разу не отметился (например, врач, который не пользуется табелем), показан серым и в отсутствующие не попадает. " : "Вы видите только свои дни. "}${r.can_edit ? "Нажмите на клетку, чтобы исправить отметку — исправление помечается. " : ""}Отметки сохраняются на компьютере и передаются на другие компьютеры клиники.</div>`;
  $("#tsPrev").onclick = () => { S.tsMonth = shiftMonth(S.tsMonth, -1); loadTimesheet(); };
  $("#tsNext").onclick = () => { S.tsMonth = shiftMonth(S.tsMonth, 1); loadTimesheet(); };
  $("#tsToday").onclick = () => { S.tsMonth = iso(new Date()).slice(0, 7); loadTimesheet(); };
  $("#tsPrint").onclick = () => { $("#printArea").innerHTML = `<h2>Табель: ${esc(monthName(r.month).toLowerCase())}</h2>${($("#tsTbl") || {}).outerHTML || ""}`; window.print(); };
  const ck = $("#tsClock");
  if (ck) ck.onclick = async () => { try { await api.time_clock(me.state === "in" ? "out" : "in"); toast(me.state === "in" ? "Уход отмечен" : "Приход отмечен"); loadTimesheet(); refreshClock(); } catch (e) { toast(errText(e), true); } };
  const ts = $("#tsSet");
  if (ts) ts.onclick = () => tsSettings(r.settings);
  if (r.can_edit) $$("#shBody td.ts-c.ed").forEach(td => td.onclick = () => editMark(td.dataset.k, td.dataset.d));
}

function editMark(key, day) {
  const p = S.tsData.rows.find(x => x.key === key) || {}, c = (p.cells || {})[day] || {};
  const box = modal(`<div class="m-h"><h3>${esc(p.name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">${esc(fmtDate(day))}${c.plan ? ` · по графику ${esc(c.plan[0])}–${esc(c.plan[1])}` : " · смены по графику нет"}</p>
      <div class="grid2"><label class="fl">Пришёл<input class="input" type="time" id="tmC" value="${esc(c.came || (c.plan ? c.plan[0] : ""))}" autofocus></label><label class="fl">Ушёл<input class="input" type="time" id="tmL" value="${esc(c.left || "")}"></label></div>
      <label class="fl">Заметка<input class="input" id="tmN" value="${esc(c.note || "")}" placeholder="Забыл отметиться, отпросился…"></label><div class="auth-err" id="tmErr"></div></div>
    <div class="m-f">${c.came ? `<button class="btn ghost small danger" id="tmDel">Убрать отметку</button>` : ""}<span class="muted">Исправление будет помечено</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="tmOk">Сохранить</button></div>`);
  $("#tmOk", box).onclick = async () => {
    try { await api.time_mark_save({person: key, date: day, came: $("#tmC").value, left: $("#tmL").value, note: $("#tmN").value}); closeModal(); loadTimesheet(); }
    catch (e) { $("#tmErr").textContent = errText(e); }
  };
  const del = $("#tmDel", box);
  if (del) del.onclick = async () => { await api.time_mark_save({person: key, date: day, came: "", left: ""}); closeModal(); loadTimesheet(); };
}

function tsSettings(s) {
  const box = modal(`<div class="m-h"><h3>Табель: допуск</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="grid2"><label class="fl">Опоздание не считается до, мин<input class="input num" type="number" min="0" max="120" id="tgL" value="${s.late_grace}"></label>
      <label class="fl">Ранний уход не считается до, мин<input class="input num" type="number" min="0" max="120" id="tgE" value="${s.early_grace}"></label></div><div class="auth-err" id="tgErr"></div></div>
    <div class="m-f"><span class="muted">Одинаково на всех компьютерах клиники</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="tgOk">Сохранить</button></div>`);
  $("#tgOk", box).onclick = async () => {
    try { await api.timesheet_settings_save({late_grace: $("#tgL").value, early_grace: $("#tgE").value}); closeModal(); loadTimesheet(); }
    catch (e) { $("#tgErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------------------ «Я пришёл» / «Я ушёл» in the user menu */
let CLOCK = null;
async function refreshClock() {
  const b = $("#ucClock");
  if (!b) return;
  try { CLOCK = await api.time_me(); } catch (e) { CLOCK = null; }
  b.hidden = !(CLOCK && CLOCK.can);
  if (!CLOCK || !CLOCK.can) return;
  b.textContent = CLOCK.state === "in" ? `Я ушёл (пришёл в ${CLOCK.came})` : CLOCK.state === "left" ? `Я снова пришёл (ушёл в ${CLOCK.left})` : "Я пришёл";
}
(() => {
  const b = $("#ucClock");
  if (!b) return;
  b.onclick = async e => {
    e.stopPropagation();
    if (!CLOCK) await refreshClock();
    if (!CLOCK || !CLOCK.can) return;
    const out = CLOCK.state === "in";
    try { await api.time_clock(out ? "out" : "in"); toast(out ? "Уход отмечен" : "Приход отмечен"); $("#ucMenu").hidden = true; await refreshClock();
      if (S.view === "shifts" && S.shTab === "fact") loadTimesheet(); }
    catch (err) { toast(errText(err), true); }
  };
  const ub = $("#ucBtn");
  if (ub) ub.addEventListener("click", () => { if (ME) refreshClock(); });
})();
