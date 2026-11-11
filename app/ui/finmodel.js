"use strict";
/* 2.15: «Бухгалтерия» → «Финмодель»: the month's profit by steps with guide ranges, break-even, a «what if»
   scenario, money that is likely to come and profit by months. Also the profit tile on the director's screen. */
S.fmMonth = iso(new Date()).slice(0, 7);
S.fmWhat = {price: 0, visits: 0, doctors: 0, fixed: 0, target: ""};
const FM_SLIDERS = [
  ["price", "Цены на услуги", -30, 50, 1, "%"],
  ["visits", "Число приёмов", -50, 50, 1, "%"],
  ["doctors", "Процент врачам", -10, 10, 0.5, " п."],
  ["fixed", "Постоянные расходы", -50, 50, 1, "%"],
];
const fmSign = (v, unit) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("ru-RU")}${unit}`;
const fmShare = s => s == null ? "—" : `${(+s).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
const fmN = v => (+v).toLocaleString("ru-RU");
const fmGuide = (g, profit) => !g ? "" : profit ? `от ${fmN(g[0])} %` : g[0] ? `${fmN(g[0])}–${fmN(g[1])} %` : `до ${fmN(g[1])} %`;
const FM_FLAG = {high: "выше ориентира", low: "ниже ориентира"};

async function accFinmodel(body) {
  let r;
  try { r = await api.finmodel(S.fmMonth); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  S.fm = r;
  const line = (x, cls = "", profit = false) => `<tr class="${cls}" ${x.detail && x.detail.length ? `title="${esc(x.detail.map(d => `${d.name}: ${rub(d.amount ?? (d.doctors || d.staff))}`).join("\n"))}"` : ""}>
      <td>${esc(x.name)}</td><td class="num">${money(x.amount)}</td><td class="num">${fmShare(x.share)}</td>
      <td class="fm-guide">${x.guide ? `<span class="muted">${fmGuide(x.guide, profit)}</span>` : ""}${x.flag && x.flag !== "ok" ? ` <span class="pill fm-flag">${FM_FLAG[x.flag]}</span>` : ""}</td></tr>`;
  const op = r.operating, be = r.break_even;
  const beText = be == null ? `<small class="muted">не считается: переменные расходы не меньше поступлений</small>`
    : r.to_break_even > 0 ? `<small class="bad-t">осталось ${rub(r.to_break_even)}${r.per_day_left ? ` · ${rub(r.per_day_left)} в рабочий день` : ""}</small>`
    : `<small class="ok-t">пройдена${r.safety != null ? ` · запас ${fmShare(r.safety)}` : ""}</small>`;
  body.innerHTML = accTools(`<div class="month-nav"><button class="icon-btn" id="fmPrev" title="Предыдущий месяц">‹</button><b>${monthName(r.month)}</b><button class="icon-btn" id="fmNext" title="Следующий месяц">›</button></div>`, false) +
    `${r.current ? `<div class="note-box">Месяц ещё идёт: рабочий день ${r.workdays_done} из ${r.workdays}. Цифры — на сегодня; аренда и другие расходы месяца могут быть внесены ещё не все.</div>` : ""}
    ${r.no_schemes ? `<div class="note-box">Схемы оплаты сотрудников не заданы — зарплата в расчёт попадает только по выплатам. Задайте процент и оклады во вкладке «Зарплата».</div>` : ""}
    <div class="stat-row dir-tiles">
      <div class="stat"><span>Поступления</span><b>${rub(r.revenue)}</b><small class="muted">выставлено счетов на ${rub(r.billed)}</small></div>
      <div class="stat"><span>Маржинальная прибыль</span><b>${rub(r.margin.amount)}</b><small class="muted">${fmShare(r.margin.share)} поступлений</small></div>
      <div class="stat ${op.amount < 0 ? "warn" : ""}"><span>${op.amount < 0 ? "Операционный убыток" : "Операционная прибыль"}</span><b>${rub(op.amount)}</b><small class="muted">рентабельность ${fmShare(op.share)}</small></div>
      <div class="stat ${r.to_break_even > 0 ? "warn" : ""}"><span>Точка безубыточности</span><b>${be == null ? "—" : rub(be)}</b>${beText}</div>
      <div class="stat ${r.net.amount < 0 ? "warn" : ""}"><span>Чистая прибыль</span><b>${rub(r.net.amount)}</b><small class="muted">после налогов и взносов</small></div>
    </div>
    <div class="dir-grid">
      <div class="dir-col">
        <div class="pbody"><div class="pb-head"><b>Прибыль по ступеням</b><span class="muted">${fmtShort(r.from)} — ${fmtShort(r.to)}</span></div>
          <div class="tbl-scroll"><table class="tbl compact fm-pnl" id="fmPnl"><thead><tr><th>Статья</th><th class="num">Сумма</th><th class="num">Доля</th><th>Ориентир</th></tr></thead><tbody>
            <tr class="fm-total"><td>Поступления от пациентов</td><td class="num">${money(r.revenue)}</td><td class="num">${r.revenue ? "100 %" : "—"}</td><td></td></tr>
            <tr class="fm-group"><td>− Переменные расходы</td><td class="num">${money(r.variable_total)}</td><td class="num">${fmShare(r.variable_share)}</td><td class="muted">растут вместе с выручкой</td></tr>
            ${r.variable.map(x => line(x, "fm-sub")).join("")}
            ${line(r.margin, "fm-total", true)}
            <tr class="fm-group"><td>− Постоянные расходы</td><td class="num">${money(r.fixed_total)}</td><td class="num">${fmShare(r.fixed_share)}</td><td class="muted">не зависят от числа приёмов</td></tr>
            ${r.fixed.map(x => line(x, "fm-sub")).join("")}
            ${line(op, "fm-total", true)}
            ${line({...r.taxes, name: "− " + r.taxes.name}, "fm-group")}
            ${line(r.net, "fm-total fm-net", true)}
          </tbody></table></div>
          <div class="muted note-line dir-note">Зарплата — начисленная по схемам оплаты за этот месяц: процент врачей — переменный расход, оклады — постоянный. Наведите на строку зарплаты, чтобы увидеть, кому сколько. Ориентиры — примерные доли для стоматологии, повод присмотреться, а не правило.</div></div>
        <div class="pbody"><div class="pb-head"><b>Прибыль по месяцам</b><span class="muted">после налогов</span></div>
          <div class="tbl-scroll"><table class="tbl compact fm-hist"><thead><tr><th>Месяц</th><th class="num">Поступления</th><th class="num">Расходы</th><th class="num">Прибыль</th><th></th><th class="num">Доля</th></tr></thead><tbody>${(() => {
            const mx = Math.max(0, ...r.history.filter(h => h.has_data).map(h => Math.abs(h.net)));
            return r.history.map(h => !h.has_data ? `<tr data-m="${h.month}" class="lnk-row ${h.month === r.month ? "fm-cur" : ""}"><td>${esc(monthName(h.month))}</td><td colspan="5" class="muted">нет поступлений и расходов в программе</td></tr>` : `<tr data-m="${h.month}" class="lnk-row ${h.month === r.month ? "fm-cur" : ""}"><td>${esc(monthName(h.month))}</td><td class="num">${rub(h.revenue)}</td><td class="num">${rub(h.expense)}</td>
              <td class="num ${h.net < 0 ? "bad-t" : ""}"><b>${rub(h.net)}</b></td><td class="bar-cell ${h.net < 0 ? "fm-neg" : ""}">${hbar(Math.abs(h.net), mx)}</td><td class="num muted">${fmShare(h.share)}</td></tr>`).join("");
          })()}</tbody></table></div></div>
      </div>
      <div class="dir-col">
        <div class="pbody fm-what" id="fmWhat"><div class="pb-head"><b>Что если</b><button class="linkbtn" id="fmReset">Сбросить</button></div>
          <div class="fm-sliders">${FM_SLIDERS.map(([k, t, lo, hi, st, u]) => `<label class="fm-sl"><span>${t}</span><output id="fmo-${k}">${fmSign(S.fmWhat[k], u)}</output>
            <input type="range" id="fmi-${k}" min="${lo}" max="${hi}" step="${st}" value="${S.fmWhat[k]}" aria-label="${t}"></label>`).join("")}
            <label class="fl">Желаемая прибыль в месяц, ₽<input class="input num" id="fmi-target" type="number" min="0" step="10000" value="${esc(S.fmWhat.target)}" placeholder="например, ${rub(Math.max(100000, Math.round(Math.max(0, op.amount) * 1.2 / 10000) * 10000)).replace(" ₽", "")}"></label></div>
          <div id="fmOut"></div></div>
        <div class="pbody"><div class="pb-head"><b>Деньги впереди</b><span class="muted">ещё не поступили</span></div>
          <table class="tbl compact fm-res"><tbody>
            <tr data-go="plans" class="lnk-row"><td>Подтверждённые планы лечения<br><small class="muted">${r.reserve.plans_confirmed_n} ${plural(r.reserve.plans_confirmed_n, "план", "плана", "планов")}, лечение не начато</small></td><td class="num"><b>${rub(r.reserve.plans_confirmed)}</b></td></tr>
            <tr data-go="plans" class="lnk-row"><td>Предварительные планы<br><small class="muted">${r.reserve.plans_draft_n} ${plural(r.reserve.plans_draft_n, "план", "плана", "планов")} ждут решения пациента</small></td><td class="num">${rub(r.reserve.plans_draft)}</td></tr>
            <tr data-go="debts" class="lnk-row"><td>Рассрочки по графику<br><small class="muted">срок платежей ещё не наступил</small></td><td class="num">${rub(r.reserve.installments)}</td></tr>
            <tr data-go="debts" class="lnk-row"><td>Долги пациентов</td><td class="num">${rub(r.reserve.debts)}</td></tr>
          </tbody></table></div>
      </div>
    </div>`;
  $("#fmPrev").onclick = () => { S.fmMonth = shiftMonth(S.fmMonth, -1); loadAccounting(); };
  $("#fmNext").onclick = () => { S.fmMonth = shiftMonth(S.fmMonth, 1); loadAccounting(); };
  $$("#accBody .fm-hist [data-m]").forEach(tr => tr.onclick = () => { S.fmMonth = tr.dataset.m; loadAccounting(); });
  $$("#accBody .fm-res [data-go]").forEach(tr => tr.onclick = () => {
    if (tr.dataset.go === "plans") { S.repTab = "conversion"; } else { S.repTab = "debts"; }
    $$("#repTabs button").forEach(x => x.classList.toggle("on", x.dataset.k === S.repTab)); show("reports");
  });
  let timer = 0;
  const recount = () => { clearTimeout(timer); timer = setTimeout(fmScenario, 120); };
  FM_SLIDERS.forEach(([k, , , , , u]) => { const i = $("#fmi-" + k); i.oninput = () => { S.fmWhat[k] = +i.value; $("#fmo-" + k).textContent = fmSign(+i.value, u); recount(); }; });
  $("#fmi-target").oninput = e => { S.fmWhat.target = e.target.value; recount(); };
  $("#fmReset").onclick = () => { S.fmWhat = {price: 0, visits: 0, doctors: 0, fixed: 0, target: ""}; loadAccounting(); };
  fmScenario();
}

async function fmScenario() {
  const out = $("#fmOut"), r = S.fm;
  if (!out || !r) return;
  let s;
  try { s = await api.finmodel_scenario(r.month, S.fmWhat); } catch (e) { out.innerHTML = `<div class="auth-err">${esc(errText(e))}</div>`; return; }
  const changed = FM_SLIDERS.some(([k]) => S.fmWhat[k]);
  const d = s.delta;
  out.innerHTML = `<table class="tbl compact fm-out"><tbody>
      <tr><td>Поступления</td><td class="num">${rub(s.revenue)}</td></tr>
      <tr><td>Операционная прибыль</td><td class="num"><b>${rub(s.operating)}</b>${changed ? `<br><small class="${d >= 0 ? "ok-t" : "bad-t"}">${d >= 0 ? "▲" : "▼"} ${rub(Math.abs(d))} к факту</small>` : ""}</td></tr>
      <tr><td>Рентабельность</td><td class="num">${fmShare(s.operating_share)}</td></tr>
      <tr><td>Точка безубыточности</td><td class="num">${s.break_even == null ? "—" : rub(s.break_even)}</td></tr></tbody></table>
    ${S.fmWhat.target && +S.fmWhat.target > 0 ? (s.need == null ? `<div class="note-box">При таких условиях переменные расходы съедают всю выручку — прибыль не получится.</div>`
      : `<div class="note-box fm-need">Чтобы зарабатывать <b>${rub(s.target)}</b> в месяц до налогов, нужно поступлений <b>${rub(s.need)}</b>${s.need_per_day ? ` — около <b>${rub(s.need_per_day)}</b> в рабочий день` : ""}${s.need_growth != null && !r.current ? ` (${s.need_growth >= 0 ? "+" : "−"}${fmShare(Math.abs(s.need_growth))} к факту месяца)` : ""}.</div>`) : ""}
    <div class="muted note-line">Материалы и лаборатория меняются вместе с числом приёмов, эквайринг и налоги — вместе с выручкой, процент врачам — от новой выручки. Ничего не сохраняется.</div>`;
}

/* the tile on the director's screen (only with «Бухгалтерия») */
async function dirProfitTile(row) {
  if (!row || !can("accounting")) return;
  let b;
  try { b = await api.finmodel_brief(); } catch (e) { return; }
  const el = document.createElement("div");
  el.className = "stat fm-tile" + (b.operating < 0 ? " warn" : "");
  el.innerHTML = `<span>Прибыль за месяц</span><b>${rub(b.operating)}</b><small class="${b.to_break_even > 0 ? "bad-t" : "muted"}">${b.break_even == null ? "безубыточность не считается"
    : b.to_break_even > 0 ? `до безубыточности ${rub(b.to_break_even)}` : `безубыточность пройдена · ${fmShare(b.operating_share)}`}</small>
    <button class="linkbtn">Финмодель →</button>`;
  $("button", el).onclick = () => { S.accTab = "finmodel"; S.fmMonth = b.month; show("accounting"); };
  row.appendChild(el);
}
