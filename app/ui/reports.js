"use strict";
/* Reports: revenue, doctors, services, visits, debts. Also the shared period picker and bars used by
   accounting.js and marketing.js. Money is what was billed and paid in this program. */

/* ------------------------------------------------------------ shared */
const PERIODS = [["month", "Этот месяц"], ["prev", "Прошлый месяц"], ["d30", "30 дней"], ["quarter", "Квартал"], ["year", "Год"]];
function periodRange(k) {
  const t = new Date(), y = t.getFullYear(), m = t.getMonth();
  if (k === "prev") return {from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0))};
  if (k === "d30") return {from: addDays(iso(t), -29), to: iso(t)};
  if (k === "quarter") return {from: iso(new Date(y, Math.floor(m / 3) * 3, 1)), to: iso(t)};
  if (k === "year") return {from: iso(new Date(y, 0, 1)), to: iso(t)};
  return {from: iso(new Date(y, m, 1)), to: iso(t)};
}
S.period = {key: "month", ...periodRange("month")};
const fmtShort = s => s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}` : "";
const periodText = () => `${fmtShort(S.period.from)} — ${fmtShort(S.period.to)}`;
function periodBar() {
  return `<div class="period-bar"><div class="seg sm" data-period>${PERIODS.map(([k, t]) => `<button data-p="${k}" class="${S.period.key === k ? "on" : ""}">${t}</button>`).join("")}</div>
    <span class="pb-dates"><input type="date" class="input" data-pf value="${S.period.from}"><span class="muted">—</span><input type="date" class="input" data-pt value="${S.period.to}"></span></div>`;
}
function bindPeriod(root, reload) {
  $$("[data-period] button", root).forEach(b => b.onclick = () => { S.period = {key: b.dataset.p, ...periodRange(b.dataset.p)}; reload(); });
  const f = $("[data-pf]", root), t = $("[data-pt]", root);
  const set = () => { if (f.value && t.value) { S.period = {key: "", from: f.value, to: t.value}; reload(); } };
  if (f) { f.onchange = set; t.onchange = set; }
}
/* a thin horizontal bar for a table cell; one hue (the accent), the number beside it stays in ink */
const hbar = (v, max) => `<span class="hb"><i style="width:${max > 0 ? Math.max(v > 0 ? 1.5 : 0, Math.min(100, v * 100 / max)) : 0}%"></i></span>`;
/* columns by day; the tooltip is CSS-only (data-tip), labels on the first, middle and last day */
function colChart(rows, val, tip, label) {
  if (!rows.length) return `<div class="empty sm"><span>Нет данных за период</span></div>`;
  const max = Math.max(...rows.map(val), 0);
  const marks = new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]);
  return `<div class="vchart" style="--n:${rows.length}"><div class="vc-max muted">${esc(label(max))}</div>${rows.map((r, i) => `<div class="vc" data-tip="${esc(tip(r))}">
      <i style="height:${max > 0 ? Math.max(val(r) > 0 ? 2 : 0, val(r) * 100 / max) : 0}%"></i>${marks.has(i) ? `<small>${esc(r._x || "")}</small>` : ""}</div>`).join("")}</div>`;
}
const dayLbl = s => `${+s.slice(8, 10)} ${MONTHS[+s.slice(5, 7) - 1].slice(0, 3)}`;
/* fill the gaps so a quiet day shows as an empty column, not a missing one */
function everyDay(rows, from, to, blank) {
  const by = Object.fromEntries(rows.map(r => [r.day, r])), out = [];
  if (!from || !to || (parseDay(to) - parseDay(from)) / 864e5 > 120) return rows.map(r => ({...r, _x: dayLbl(r.day)}));
  for (let d = from; d <= to; d = addDays(d, 1)) out.push({...(by[d] || {day: d, ...blank}), _x: dayLbl(d)});
  return out;
}
const pct = (a, b) => b ? Math.round(a * 1000 / b) / 10 + "%" : "—";
const tabSeg = (id, tabs, cur) => `<div class="seg" id="${id}">${tabs.map(([k, t]) => `<button data-k="${k}" class="${k === cur ? "on" : ""}">${t}</button>`).join("")}</div>`;
async function printTable(title, sel) {
  const t = $(sel); if (!t) return;
  $("#printArea").innerHTML = `${typeof clinicHead === "function" ? await clinicHead() : ""}<h2>${esc(title)}</h2>${S.period ? `<div>Период: ${periodText()}</div>` : ""}${t.outerHTML.replace(/<span class="hb">.*?<\/span><\/span>/g, "")}`;
  window.print();
}
const PRINT_ICON = '<svg viewBox="0 0 24 24"><path d="M7 9V3.5h10V9M7 17H4.5V10.5a1.5 1.5 0 0 1 1.5-1.5h12a1.5 1.5 0 0 1 1.5 1.5V17H17"/><rect x="7" y="14" width="10" height="6.5" rx="1"/></svg>';

/* ------------------------------------------------------------ reports */
S.repTab = "revenue";
$$("#repTabs button").forEach(b => b.onclick = () => { S.repTab = b.dataset.k; $$("#repTabs button").forEach(x => x.classList.toggle("on", x === b)); loadReports(); });

async function loadReports() {
  const body = $("#repBody");
  const fn = {revenue: repRevenue, doctors: repDoctors, services: repServices, visits: repVisits, debts: repDebts,
    patients: typeof repPatients === "function" ? repPatients : null, load: typeof repLoad === "function" ? repLoad : null,
    conversion: typeof repConversion === "function" ? repConversion : null}[S.repTab] || repRevenue;
  await fn(body);
  bindPeriod(body, loadReports);
  const pr = $("#repPrint", body); if (pr) pr.onclick = () => printTable($("#repTabs button.on").textContent, "#repBody table.tbl");
}
const repTools = (extra = "") => `<div class="tab-tools rep-tools">${periodBar()}<span class="grow"></span>${extra}<button class="icon-btn" title="Скачать в Excel" data-xls="#repBody table.tbl" data-xls-title="#repTabs button.on"><svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg></button><button class="icon-btn" id="repPrint" title="Печать">${PRINT_ICON}</button></div>`;
const moneyNote = `<div class="muted note-line">Счета и оплаты, проведённые в этой программе. Оплаты, принятые только в Dentist Plus, сюда не попадают.</div>`;

async function repRevenue(body) {
  const r = await api.report_revenue(S.period.from, S.period.to);
  const days = everyDay(r.by_day, r.from, r.to, {billed: 0, paid: 0});
  const meth = Object.entries(r.by_method), mMax = Math.max(0, ...meth.map(x => x[1]));
  body.innerHTML = repTools() + `<div class="stat-row">
      <div class="stat"><span>Поступило от пациентов</span><b>${money(r.paid)}</b></div>
      <div class="stat"><span>Выставлено счетов</span><b>${money(r.billed)}</b></div>
      <div class="stat"><span>Счетов</span><b>${r.invoices}</b></div>
      <div class="stat"><span>Средний чек</span><b>${money(r.avg_check)}</b></div>
      <div class="stat"><span>Пациентов со счетами</span><b>${r.patients}</b></div></div>
    <div class="rep-grid">
      <div class="pbody rep-card"><div class="pb-head"><b>Поступления по дням</b><span class="muted">${periodText()}</span></div>
        ${colChart(days, x => x.paid, x => `${fmtShort(x.day)}: ${money(x.paid)} оплачено, счетов на ${money(x.billed)}`, money)}</div>
      <div class="pbody rep-card"><div class="pb-head"><b>Способы оплаты</b></div>
        ${meth.length ? `<table class="tbl compact"><tbody>${meth.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${money(v)}</td><td class="bar-cell">${hbar(v, mMax)}</td><td class="num muted">${pct(v, r.paid)}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty sm"><span>Оплат за период нет</span></div>`}</div></div>${moneyNote}`;
}

async function repDoctors(body) {
  const r = await api.report_revenue(S.period.from, S.period.to);
  const max = Math.max(0, ...r.by_doctor.map(d => d.billed));
  body.innerHTML = repTools() + `<div class="pbody">${r.by_doctor.length ? `<table class="tbl"><thead><tr><th>Врач</th><th class="num">Выставлено</th><th class="bar-h"></th><th class="num">Оплачено</th><th class="num">Счетов</th><th class="num">Пациентов</th><th class="num">Средний чек</th><th class="num">Доля</th></tr></thead><tbody>${
    r.by_doctor.map(d => `<tr><td><b>${esc(d.name)}</b></td><td class="num">${money(d.billed)}</td><td class="bar-cell">${hbar(d.billed, max)}</td><td class="num">${money(d.paid)}</td>
      <td class="num">${d.invoices}</td><td class="num">${d.patients}</td><td class="num">${money(d.invoices ? d.billed / d.invoices : 0)}</td><td class="num muted">${pct(d.billed, r.billed)}</td></tr>`).join("")}
    </tbody><tfoot><tr><td>Итого</td><td class="num">${money(r.billed)}</td><td></td><td class="num">${money(r.paid)}</td><td class="num">${r.invoices}</td><td class="num">${r.patients}</td><td class="num">${money(r.avg_check)}</td><td></td></tr></tfoot></table>`
    : `<div class="empty"><b>За период нет счетов</b><span>Выберите другой период</span></div>`}</div>${moneyNote}`;
}

async function repServices(body) {
  const [r, mt] = await Promise.all([api.report_revenue(S.period.from, S.period.to),
    can("reports") ? api.report_materials(S.period.from, S.period.to).catch(() => null) : null]);
  const q = (S.repSrvQ || "").toLowerCase();
  const rows = r.by_service.filter(s => !q || `${s.title} ${s.code}`.toLowerCase().includes(q));
  const max = Math.max(0, ...rows.map(s => s.sum)), total = r.by_service.reduce((a, s) => a + s.sum, 0);
  const mat = mt && mt.has_norms ? mt.by_service : null;  // cost of materials by service, when norms are set
  const share = s => { const c = mat[s.title] || 0;
    return `<td class="num">${c ? money(c) : `<span class="muted">—</span>`}</td><td class="num ${s.sum && c * 100 / s.sum >= 25 ? "bad-t" : "muted"}">${c ? pct(c, s.sum) : ""}</td>`; };
  body.innerHTML = repTools(`<div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="rsQ" placeholder="Услуга или код" value="${esc(S.repSrvQ || "")}"></div>`) +
    (mat ? `<div class="stat-row"><div class="stat"><span>Выставлено по счетам</span><b>${money(mt.billed)}</b></div>
      <div class="stat"><span>Материалы по нормам</span><b>${money(mt.cost)}</b></div>
      <div class="stat ${mt.share >= 20 ? "warn" : ""}"><span>Доля материалов в выручке</span><b>${pct(mt.cost, mt.billed)}</b></div>
      <div class="stat"><span>Списано вручную</span><b>${money(mt.manual_writeoff)}</b><small class="muted">брак, просрочка, хозяйственные</small></div></div>` : "") +
    `<div class="pbody">${rows.length ? `<table class="tbl"><thead><tr><th>Код</th><th>Услуга</th><th class="num">Количество</th><th class="num">Сумма</th><th class="bar-h"></th><th class="num">Доля</th>${mat ? `<th class="num">Материалы</th><th class="num">Доля материалов</th>` : ""}</tr></thead><tbody>${
      rows.map(s => `<tr><td class="muted">${esc(s.code)}</td><td>${esc(s.title)}</td><td class="num">${(+s.qty).toLocaleString("ru-RU")}</td><td class="num"><b>${money(s.sum)}</b></td><td class="bar-cell">${hbar(s.sum, max)}</td><td class="num muted">${pct(s.sum, total)}</td>${mat ? share(s) : ""}</tr>`).join("")}
      </tbody></table>` : `<div class="empty"><b>${q ? "Ничего не найдено" : "За период услуг не было"}</b></div>`}</div>
    <div class="muted note-line">Суммы по строкам счетов с учётом скидок.${mat ? ` Материалы — списание по нормам услуг (Склад → «Нормы списания»).${mt.estimated ? ` Для ${mt.estimated} ${plural(mt.estimated, "счёта", "счетов", "счетов")} без автосписания стоимость посчитана по нормам и текущим ценам материалов.` : ""}` : ""}</div>`;
  let t; $("#rsQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.repSrvQ = e.target.value; repServices(body).then(() => { bindPeriod(body, loadReports); const i = $("#rsQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
}

async function repVisits(body) {
  const r = await api.report_visits(S.period.from, S.period.to);
  const days = everyDay(r.by_day, r.from, r.to, {total: 0, cancel: 0, noshow: 0});
  const max = Math.max(0, ...r.by_doctor.map(d => d.total));
  body.innerHTML = repTools() + `<div class="stat-row">
      <div class="stat"><span>Записей</span><b>${r.total}</b></div>
      <div class="stat"><span>Пришли и завершены</span><b>${r.done + r.came}</b></div>
      <div class="stat"><span>Запланировано</span><b>${r.planned}</b></div>
      <div class="stat ${r.lost_share >= 15 ? "warn" : ""}"><span>Отмены и неявки</span><b>${r.cancel + r.noshow} <small class="muted">${r.lost_share}%</small></b></div>
      <div class="stat"><span>Новых пациентов</span><b>${r.new_patients}</b></div>
      <div class="stat"><span>Часов приёма</span><b>${Math.round(r.minutes / 6) / 10}</b></div></div>
    <div class="pbody rep-card" style="margin-bottom:12px"><div class="pb-head"><b>Записи по дням</b><span class="muted">${periodText()}</span></div>
      ${colChart(days, x => x.total, x => `${fmtShort(x.day)}: ${x.total} ${plural(x.total, "запись", "записи", "записей")}${x.cancel + x.noshow ? `, отмен и неявок ${x.cancel + x.noshow}` : ""}`, v => String(v))}</div>
    <div class="pbody">${r.by_doctor.length ? `<table class="tbl"><thead><tr><th>Врач</th><th class="num">Записей</th><th class="bar-h"></th><th class="num">Пришли</th><th class="num">Запланировано</th><th class="num">Отмены</th><th class="num">Неявки</th><th class="num">Пациентов</th><th class="num">Часов</th></tr></thead><tbody>${
      r.by_doctor.map(d => `<tr><td><b>${esc(d.name)}</b></td><td class="num">${d.total}</td><td class="bar-cell">${hbar(d.total, max)}</td><td class="num">${d.done + d.came}</td><td class="num">${d.planned}</td>
        <td class="num ${d.cancel ? "bad-t" : ""}">${d.cancel}</td><td class="num ${d.noshow ? "bad-t" : ""}">${d.noshow}</td><td class="num">${d.patients}</td><td class="num">${Math.round(d.minutes / 6) / 10}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>За период записей нет</b></div>`}</div>
    <div class="muted note-line">Записи из Dentist Plus и созданные в программе. «Новый пациент» — первый визит в базе приходится на этот период.</div>`;
}

async function repDebts(body) {
  const r = await api.report_debts();
  const row = x => `<td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name)}</b></td><td>${esc(x.phone || "—")}</td>`;
  body.innerHTML = `<div class="tab-tools rep-tools"><span class="muted">Состояние на сегодня</span><span class="grow"></span><button class="icon-btn" title="Скачать в Excel" data-xls="#repBody table.tbl" data-xls-title="#repTabs button.on"><svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg></button><button class="icon-btn" id="repPrint" title="Печать">${PRINT_ICON}</button></div>
    <div class="stat-row"><div class="stat ${r.total_debt ? "warn" : ""}"><span>Пациенты должны</span><b>${money(r.total_debt)}</b></div>
      <div class="stat"><span>Должников</span><b>${r.debts.length}</b></div>
      <div class="stat"><span>Авансы пациентов</span><b>${money(r.total_advance)}</b></div>
      <div class="stat"><span>Пациентов с авансом</span><b>${r.advances.length}</b></div></div>
    <div class="pbody"><div class="pb-head"><b>Долги</b>${can("marketing") ? `<button class="linkbtn" id="debtCalls">Обзвонить должников →</button>` : ""}</div>
      ${r.debts.length ? `<table class="tbl" id="debtTbl"><thead><tr><th>Пациент</th><th>Телефон</th><th class="num">Выставлено</th><th class="num">Оплачено</th><th class="num">Долг в программе</th><th class="num">Долг в Dentist Plus</th><th class="num">Всего</th><th>Последняя операция</th></tr></thead><tbody>${
        r.debts.map(x => `<tr>${row(x)}<td class="num">${money(x.billed)}</td><td class="num">${money(x.paid)}</td><td class="num">${x.debt ? money(x.debt) : "—"}</td><td class="num">${x.dp_debt ? money(x.dp_debt) : "—"}</td><td class="num bad-t"><b>${money(x.total)}</b></td><td class="muted">${fmtDT(x.last)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty sm"><span>Долгов нет</span></div>`}</div>
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Авансы (оплачено больше, чем выставлено)</b></div>
      ${r.advances.length ? `<table class="tbl compact"><thead><tr><th>Пациент</th><th>Телефон</th><th class="num">Выставлено</th><th class="num">Оплачено</th><th class="num">Аванс</th><th>Последняя операция</th></tr></thead><tbody>${
        r.advances.map(x => `<tr>${row(x)}<td class="num">${money(x.billed)}</td><td class="num">${money(x.paid)}</td><td class="num ok-t"><b>${money(x.advance)}</b></td><td class="muted">${fmtDT(x.last)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty sm"><span>Авансов нет</span></div>`}</div>`;
  $$("#repBody [data-p]").forEach(td => td.onclick = () => openPatient(td.dataset.p, "reports"));
  const dc = $("#debtCalls"); if (dc) dc.onclick = () => { S.mkTab = "calls"; S.mkList = "debts"; show("marketing"); };
  if (typeof finDebts === "function") finDebts(body, r);
}

/* ---- Excel: any table on the screen → .xlsx (buttons with data-xls="<table selector>") */
async function exportTable(title, sel) {
  const t = $(sel); if (!t) return toast("Нет таблицы для выгрузки", true);
  const skip = c => c.classList.contains("no-print") || c.classList.contains("row-acts") || c.classList.contains("acts");
  const text = c => { if (!c.querySelector(".no-print")) return c.innerText; const x = c.cloneNode(true); x.querySelectorAll(".no-print").forEach(e => e.remove()); return x.textContent; };
  const cells = tr => [...tr.children].filter(c => !skip(c)).map(c => text(c).replace(/[ \t]+\n/g, "\n").trim());
  const head = t.tHead && t.tHead.rows.length ? cells(t.tHead.rows[t.tHead.rows.length - 1]) : [];
  const rows = [...(t.tBodies[0] ? t.tBodies[0].rows : [])].map(cells).concat(t.tFoot ? [...t.tFoot.rows].map(cells) : []);
  try { const r = await api.export_xlsx(title, head, rows); await saveDataUrl(r.name, r.url); } catch (e) { toast(errText(e), true); }
}
async function saveDataUrl(name, url) {
  const pw = window.pywebview && window.pywebview.api;
  if (pw && pw.save_file) { const path = await pw.save_file(name, url); if (path) toast(`Сохранено: ${path}`); return; }
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-xls]"); if (!b) return;
  const ts = b.dataset.xlsTitle && $(b.dataset.xlsTitle);
  exportTable(ts ? ts.textContent.trim() : (b.dataset.xlsName || "Таблица"), b.dataset.xls);
});