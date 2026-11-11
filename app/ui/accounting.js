"use strict";
/* Accounting: profit summary, expenses, staff pay (percent + monthly salary) and payouts. */
S.accTab = "summary";
S.accMonth = iso(new Date()).slice(0, 7);
let ACC = {categories: [], methods: [], bases: {}};
$$("#accTabs button").forEach(b => b.onclick = () => { S.accTab = b.dataset.k; $$("#accTabs button").forEach(x => x.classList.toggle("on", x === b)); loadAccounting(); });

async function loadAccounting() {
  const body = $("#accBody");
  const fn = {summary: accSummary, expenses: accExpenses, payroll: accPayroll, insurance: typeof accInsurance === "function" ? accInsurance : accSummary,
    finmodel: typeof accFinmodel === "function" ? accFinmodel : accSummary,
    pnl: typeof accPnl === "function" ? accPnl : accSummary, cashflow: typeof accCashflow === "function" ? accCashflow : accSummary,
    motivation: typeof accMotivation === "function" ? accMotivation : accSummary,
    cost: typeof accCost === "function" ? accCost : accSummary}[S.accTab] || accSummary;  // 3.5: the cost of services
  $$("#accTabs button").forEach(x => x.classList.toggle("on", x.dataset.k === S.accTab));
  await fn(body);
  bindPeriod(body, loadAccounting);
  const pr = $("#accPrint", body); if (pr) pr.onclick = () => printTable($("#accTabs button.on").textContent, "#accBody table.tbl");
}
const accTools = (extra = "", period = true) => `<div class="tab-tools rep-tools">${period ? periodBar() : ""}<span class="grow"></span>${extra}<button class="icon-btn" title="Скачать в Excel" data-xls="#accBody table.tbl" data-xls-title="#accTabs button.on"><svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg></button><button class="icon-btn" id="accPrint" title="Печать">${PRINT_ICON}</button></div>`;
const monthName = m => { const [y, mm] = m.split("-").map(Number); return ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][mm - 1] + " " + y; };
const shiftMonth = (m, n) => { const [y, mm] = m.split("-").map(Number); const d = new Date(y, mm - 1 + n, 1); return iso(d).slice(0, 7); };

/* ------------------------------------------------------------ summary */
async function accSummary(body) {
  const r = await api.acc_summary(S.period.from, S.period.to);
  ACC = r;
  const cats = Object.entries(r.by_category), cMax = Math.max(0, ...cats.map(x => x[1]));
  body.innerHTML = accTools() + `<div class="stat-row">
      <div class="stat"><span>Поступило от пациентов</span><b>${money(r.income)}</b></div>
      <div class="stat"><span>Расходы</span><b>${money(r.expense)}</b></div>
      <div class="stat ${r.result < 0 ? "warn" : ""}"><span>${r.result < 0 ? "Убыток" : "Прибыль"}</span><b>${money(r.result)}</b></div>
      <div class="stat"><span>Рентабельность</span><b>${r.income ? r.margin + "%" : "—"}</b></div>
      <div class="stat ${r.debts.total_debt ? "warn" : ""}"><span>Долги пациентов</span><b>${money(r.debts.total_debt)}</b></div>
      <div class="stat"><span>Авансы пациентов</span><b>${money(r.debts.total_advance)}</b></div></div>
    <div class="rep-grid">
      <div class="pbody rep-card"><div class="pb-head"><b>По месяцам</b></div>${r.by_month.length ? `<table class="tbl compact"><thead><tr><th>Месяц</th><th class="num">Поступления</th><th class="num">Расходы</th><th class="num">Результат</th></tr></thead><tbody>${
        r.by_month.map(m => `<tr><td>${monthName(m.month)}</td><td class="num">${money(m.income)}</td><td class="num">${money(m.expense)}</td><td class="num ${m.result < 0 ? "bad-t" : ""}"><b>${money(m.result)}</b></td></tr>`).join("")}</tbody>
        <tfoot><tr><td>Итого</td><td class="num">${money(r.income)}</td><td class="num">${money(r.expense)}</td><td class="num">${money(r.result)}</td></tr></tfoot></table>` : `<div class="empty sm"><span>Нет поступлений и расходов за период</span></div>`}</div>
      <div class="pbody rep-card"><div class="pb-head"><b>Расходы по статьям</b>${can("accounting") ? `<button class="linkbtn" id="accAdd2">+ расход</button>` : ""}</div>${cats.length ? `<table class="tbl compact"><tbody>${
        cats.map(([k, v]) => `<tr data-cat="${esc(k)}" class="lnk-row"><td>${esc(k)}</td><td class="num">${money(v)}</td><td class="bar-cell">${hbar(v, cMax)}</td><td class="num muted">${pct(v, r.expense)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty sm"><span>Расходов за период нет</span></div>`}</div></div>
    <div class="muted note-line">Поступления — оплаты пациентов в этой программе за период; выставлено счетов на ${money(r.billed)}. Расходы вносятся во вкладке «Расходы», выплаты зарплаты — во вкладке «Зарплата».</div>`;
  $$("#accBody tr[data-cat]").forEach(tr => tr.onclick = () => { S.accCat = tr.dataset.cat; S.accTab = "expenses"; $$("#accTabs button").forEach(x => x.classList.toggle("on", x.dataset.k === "expenses")); loadAccounting(); });
  const a = $("#accAdd2"); if (a) a.onclick = () => editExpense({});
}

/* ----------------------------------------------------------- expenses */
async function accExpenses(body) {
  if (!ACC.categories.length) ACC = await api.acc_summary(S.period.from, S.period.to);
  const r = await api.expenses(S.period.from, S.period.to, S.accCat || null);
  S.accRows = r.rows;
  body.innerHTML = accTools(`<select class="input sm-sel" id="exCat"><option value="">Все статьи</option>${ACC.categories.map(c => `<option ${c === S.accCat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <button class="btn" id="exNew">+ Расход</button>`) +
    `<div class="pbody">${r.rows.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Статья</th><th>Комментарий</th><th>Сотрудник</th><th>Способ</th><th class="num">Сумма</th><th>Внёс</th></tr></thead><tbody>${
      r.rows.map(x => `<tr data-e="${esc(x.id)}" class="lnk-row"><td>${fmtShort(x.date)}</td><td><b>${esc(x.category)}</b></td><td>${esc(x.comment)}${x.doc === 0 ? ' <span class="pill dx-nodoc">без документа</span>' : ""}</td><td>${esc(x.person_name || "")}${x.period ? ` <span class="muted">за ${esc(monthName(x.period).toLowerCase())}</span>` : ""}</td>
        <td class="muted">${esc(x.method)}</td><td class="num"><b>${money(x.amount)}</b></td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="5">Итого${S.accCat ? ": " + esc(S.accCat) : ""}${(() => { const n = r.rows.filter(y => y.doc === 0).reduce((a, y) => a + y.amount, 0); return n ? ` · без документов ${money(n)}` : ""; })()}</td><td class="num">${money(r.total)}</td><td></td></tr></tfoot></table>`
      : `<div class="empty"><b>Расходов за период нет</b><span>Нажмите «+ Расход», чтобы внести аренду, закупку или другую трату</span></div>`}</div>`;
  $("#exCat").onchange = e => { S.accCat = e.target.value; loadAccounting(); };
  $("#exNew").onclick = () => editExpense({});
  $$("#accBody tr[data-e]").forEach(tr => tr.onclick = () => editExpense(S.accRows.find(x => x.id === tr.dataset.e)));
}

async function editExpense(x) {
  if (!ACC.categories.length) ACC = await api.acc_summary(S.period.from, S.period.to);
  const people = await api.salary_schemes();
  const box = modal(`<div class="m-h"><h3>${x.id ? "Расход" : "Новый расход"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid3"><label class="fl">Дата*<input class="input" type="date" id="exD" value="${esc(x.date || iso(new Date()))}"></label>
        <label class="fl">Сумма, ₽*<input class="input num" id="exA" type="number" step="any" min="0" value="${x.amount ?? ""}" autofocus></label>
        <label class="fl">Способ<select class="input" id="exM">${ACC.methods.map(m => `<option ${m === x.method ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label></div>
      <label class="fl">Статья*<input class="input" id="exC" list="exCats" value="${esc(x.category || S.accCat || "")}" placeholder="Аренда, закупка, лаборатория…"></label>
      <datalist id="exCats">${ACC.categories.map(c => `<option value="${esc(c)}">`).join("")}</datalist>
      <label class="fl" id="exSrcL">Какую рекламу оплатили (для окупаемости в CRM)<select class="input" id="exSrc"><option value="">— не указано —</option>${[...new Set([...(ACC.sources || []), ...(x.source ? [x.source] : [])])].map(s => `<option ${s === x.source ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
      <div class="grid2"><label class="fl">Сотрудник (для зарплаты)<select class="input" id="exP"><option value="">—</option>${people.map(p => `<option value="${esc(p.key)}" ${p.key === x.person ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <label class="fl">За месяц<input class="input" type="month" id="exPer" value="${esc(x.period || "")}"></label></div>
      <label class="fl">Комментарий<input class="input" id="exT" value="${esc(x.comment || "")}"></label>
      <div class="auth-err" id="exErr"></div></div>
    <div class="m-f">${x.id ? `<button class="btn ghost small danger" id="exDel">Удалить</button>` : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Отмена</button><button class="btn" id="exOk">Сохранить</button></div>`);
  const srcShow = () => { $("#exSrcL", box).hidden = $("#exC", box).value.trim() !== (ACC.ad_category || "Реклама"); };
  $("#exC", box).oninput = srcShow; srcShow();
  $("#exOk", box).onclick = async () => {
    try {
      await api.save_expense({id: x.id, date: $("#exD").value, amount: $("#exA").value, method: $("#exM").value, category: $("#exC").value,
        person: $("#exP").value, period: $("#exPer").value, comment: $("#exT").value, source: $("#exSrc").value});
      closeModal(); toast("Расход сохранён"); ACC.categories = []; loadAccounting();
    } catch (e) { $("#exErr").textContent = errText(e); }
  };
  const del = $("#exDel", box);
  if (del) del.onclick = async () => { if (await ask("Удалить расход?", {danger: true, ok: "Удалить", text: `${x.category}: ${money(x.amount)} от ${fmtShort(x.date)}`})) { await api.delete_expense(x.id); closeModal(); loadAccounting(); } };
}

/* ------------------------------------------------------------- payroll */
async function accPayroll(body) {
  if (!ACC.methods.length) ACC = await api.acc_summary(S.period.from, S.period.to);
  const r = await api.payroll(S.accMonth);
  S.payRows = r.rows;
  const scheme = p => [p.percent ? `${(+p.percent).toLocaleString("ru-RU")}% ${ACC.bases[p.base] || ""}${p.minus_materials ? " минус материалы" : ""}${p.minus_lab ? " минус лаборатория" : ""}` : "", p.fixed ? `оклад ${money(p.fixed)}` : "", p.bonus ? "мотивация" : ""].filter(Boolean).join(" + ") || "не задана";
  body.innerHTML = accTools(`<div class="month-nav"><button class="icon-btn" id="pmPrev" title="Предыдущий месяц">‹</button><b>${monthName(r.month)}</b><button class="icon-btn" id="pmNext" title="Следующий месяц">›</button></div>`, false) +
    `<div class="stat-row"><div class="stat"><span>Начислено</span><b>${money(r.earned)}</b></div><div class="stat"><span>Выплачено</span><b>${money(r.paid_out)}</b></div>
      <div class="stat ${r.due > 0 ? "warn" : ""}"><span>К выплате</span><b>${money(r.due)}</b></div></div>
    <div class="pbody">${r.rows.length ? `<table class="tbl"><thead><tr><th>Сотрудник</th><th>Схема оплаты</th><th class="num">Оплачено пациентами</th><th class="num">Выставлено</th><th class="num">По проценту</th><th class="num">Начислено</th><th class="num">Выплачено</th><th class="num">К выплате</th><th></th></tr></thead><tbody>${
      r.rows.map(p => `<tr><td><b>${esc(p.name)}</b>${p.position ? `<br><small class="muted">${esc(p.position)}</small>` : ""}</td><td class="muted">${esc(scheme(p))}</td>
        <td class="num">${p.kind === "doctor" ? money(p.paid) : "—"}</td><td class="num">${p.kind === "doctor" ? money(p.billed) : "—"}</td><td class="num">${p.percent ? money(p.by_percent) : "—"}${p.lab ? `<br><small class="muted">лаборатория −${money(p.lab)}</small>` : ""}${p.materials ? `<br><small class="muted">материалы −${money(p.materials)}</small>` : ""}</td>
        <td class="num"><b>${money(p.earned)}</b>${p.bonus ? `<br><small class="muted">в т. ч. мотивация ${money(p.bonus)}</small>` : ""}</td><td class="num">${money(p.paid_out)}</td><td class="num ${p.due > 0 ? "bad-t" : ""}"><b>${money(p.due)}</b></td>
        <td class="row-acts"><button class="linkbtn" data-sch="${esc(p.key)}">схема</button>${p.due > 0 ? `<button class="btn small" data-pay="${esc(p.key)}">Выплатить</button>` : ""}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="5">Итого</td><td class="num">${money(r.earned)}</td><td class="num">${money(r.paid_out)}</td><td class="num">${money(r.due)}</td><td></td></tr></tfoot></table>`
      : `<div class="empty"><b>Схемы оплаты ещё не заданы</b><span>Укажите процент от услуг и оклад для сотрудников ниже</span></div>`}</div>
    ${r.unset.length ? `<div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Без схемы оплаты</b><span class="muted">Зарплата не считается, пока не задан процент или оклад</span></div>
      <div class="unset-list">${r.unset.map(p => `<button class="chip" data-sch="${esc(p.key)}">${esc(p.name)}${p.position ? ` · ${esc(p.position)}` : ""}</button>`).join("")}</div></div>` : ""}
    <div class="muted note-line">Процент считается от оплат пациентов (или от выставленных счетов) по счетам врача за месяц. Выплата записывается расходом «Зарплата» за этот месяц.</div>`;
  $("#pmPrev").onclick = () => { S.accMonth = shiftMonth(S.accMonth, -1); loadAccounting(); };
  $("#pmNext").onclick = () => { S.accMonth = shiftMonth(S.accMonth, 1); loadAccounting(); };
  const all = [...r.rows, ...r.unset];
  $$("#accBody [data-sch]").forEach(b => b.onclick = () => editScheme(all.find(p => p.key === b.dataset.sch)));
  $$("#accBody [data-pay]").forEach(b => b.onclick = () => paySalary(r.rows.find(p => p.key === b.dataset.pay), r.month));
}

function editScheme(p) {
  const box = modal(`<div class="m-h"><h3>Схема оплаты: ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid2"><label class="fl">Процент от услуг, %<input class="input num" id="scP" type="number" step="any" min="0" max="100" value="${p.percent || ""}" autofocus ${p.kind === "doctor" ? "" : "disabled"}></label>
        <label class="fl">Оклад в месяц, ₽<input class="input num" id="scF" type="number" step="any" min="0" value="${p.fixed || ""}"></label></div>
      ${p.kind === "doctor" ? `<label class="fl">Процент считать<select class="input" id="scB">${Object.entries(ACC.bases).map(([k, t]) => `<option value="${k}" ${k === p.base ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
      <label class="switch-row"><input type="checkbox" id="scM" ${p.minus_materials ? "checked" : ""}><span class="sw"></span>Вычитать стоимость материалов по нормам списания</label>
      <label class="switch-row"><input type="checkbox" id="scL" ${p.minus_lab ? "checked" : ""}><span class="sw"></span>Вычитать стоимость работ лаборатории (по заказ-нарядам врача)</label>`
      : `<p class="muted">Процент от услуг считается только для врачей из Dentist Plus. Для администраторов и ассистентов задайте оклад.</p>`}
      <div class="auth-err" id="scErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="scOk">Сохранить</button></div>`);
  $("#scOk", box).onclick = async () => {
    try {
      await api.save_salary_scheme({person: p.key, percent: p.kind === "doctor" ? $("#scP").value : 0, fixed: $("#scF").value,
        base: $("#scB") ? $("#scB").value : "paid", minus_materials: $("#scM") ? $("#scM").checked : false, minus_lab: $("#scL") ? $("#scL").checked : false});
      closeModal(); toast("Схема сохранена"); loadAccounting();
    } catch (e) { $("#scErr").textContent = errText(e); }
  };
}

function paySalary(p, month) {
  const box = modal(`<div class="m-h"><h3>Выплата: ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">${esc(monthName(month))}: начислено ${money(p.earned)}, выплачено ${money(p.paid_out)}</p>
      <div class="grid3"><label class="fl">Сумма, ₽<input class="input num" id="psA" type="number" step="any" min="0" value="${p.due}" autofocus></label>
        <label class="fl">Дата<input class="input" type="date" id="psD" value="${iso(new Date())}"></label>
        <label class="fl">Способ<select class="input" id="psM">${ACC.methods.map(m => `<option>${esc(m)}</option>`).join("")}</select></label></div>
      <label class="fl">Комментарий<input class="input" id="psT" placeholder="Аванс, расчёт…"></label><div class="auth-err" id="psErr"></div></div>
    <div class="m-f"><span class="muted">Будет записано расходом «Зарплата»</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="psOk">Выплатить</button></div>`);
  $("#psOk", box).onclick = async () => {
    try {
      await api.pay_salary({person: p.key, month, amount: $("#psA").value, date: $("#psD").value, method: $("#psM").value, comment: $("#psT").value});
      closeModal(); toast("Выплата записана"); loadAccounting();
    } catch (e) { $("#psErr").textContent = errText(e); }
  };
}
