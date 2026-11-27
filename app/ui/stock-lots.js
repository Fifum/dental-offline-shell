"use strict";
/* Stock, part 2: lots with expiry dates (FEFO), write-off of expired lots and the purchase list for suppliers. */

const daysWord = n => `${n} ${plural(n, "день", "дня", "дней")}`;

/* a short line under the material name: the nearest expiry date */
function expLine(m) {
  if (!m.exp_state) return "";
  const t = m.exp_state === "expired" ? `просрочено ${qtyFmt(m.expired_qty, m.unit)}` : `${qtyFmt(m.soon_qty, m.unit)} истекает`;
  return `<small class="exp-note ${m.exp_state}">${t} · годен до ${fmtDate(m.expires)}</small>`;
}

function lotState(g) {
  if (!g.expires) return `<span class="muted">без даты</span>`;
  if (g.state === "expired") return `<span class="pill exp-pill expired">истёк ${daysWord(-g.days)} назад</span>`;
  if (g.state === "soon") return `<span class="pill exp-pill soon">${g.days ? "через " + daysWord(g.days) : "сегодня последний день"}</span>`;
  return `<span class="pill st-ok">годен</span>`;
}

/* lots of one material in its card: earliest expiry first, then what no lot covers */
function lotsTable(ll, unit, edit) {
  if (!ll || (!ll.lots.length && !ll.no_lot)) return `<div class="muted">Партий нет. Номер партии и срок годности указываются при приходе.</div>`;
  if (!ll.lots.length) return `<div class="muted">Весь остаток без партий и сроков: ${qtyFmt(ll.no_lot, unit)}. Номер партии и срок годности указываются при приходе.</div>`;
  return `<table class="tbl compact lots-t"><thead><tr><th>Партия</th><th>Годен до</th><th>Срок</th><th class="num">Остаток</th><th>Приход</th><th></th></tr></thead><tbody>${
    ll.lots.map(g => `<tr class="${g.state === "ok" ? "" : "exp-" + g.state}"><td><b>${esc(g.lot || "—")}</b></td><td>${g.expires ? fmtDate(g.expires) : "—"}</td><td>${lotState(g)}</td>
      <td class="num"><b>${qtyFmt(g.left, unit)}</b>${g.left < g.qty ? `<small class="muted"> из ${qtyFmt(g.qty)}</small>` : ""}</td>
      <td class="muted">${esc([g.received ? fmtDate(g.received) : "", g.doc_number ? "№ " + g.doc_number : "", g.supplier_name].filter(Boolean).join(" · "))}</td>
      <td>${edit ? `<button class="linkbtn" data-lot-out="${g.id}">списать</button>` : ""}</td></tr>`).join("")}
    ${ll.no_lot > 0 ? `<tr><td class="muted">без партии</td><td>—</td><td></td><td class="num">${qtyFmt(ll.no_lot, unit)}</td><td class="muted">приходы без срока, начальный остаток</td><td></td></tr>` : ""}</tbody></table>
    <div class="muted small-note">Расходуется сначала то, что истекает раньше. Остаток партий считается по движению склада.</div>`;
}

/* «Списать просроченное»: the usual write-off form, filled with every expired lot on hand */
async function writeOffExpired() {
  const lines = await api.stock_expired();
  if (!lines.length) return toast("Просроченных партий на складе нет");
  openStockDoc("writeoff", lines.map(l => ({material_id: l.material_id, qty: l.qty, lot_id: l.lot_id, lot: l.lot, expires: l.expires})),
    {reason: "Истёк срок годности"});
}

/* ------------------------------------------------ purchase list: one button, grouped by supplier */
async function openPurchase(cover) {
  const r = await api.purchase_list(cover || S.poCover || 30);
  S.poCover = r.cover_days; S.poList = r;
  const edit = can("stock_edit");
  const XLS = `<svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg>`;
  const offers = l => l.offers.length > 1 ? `<small class="po-offers">${l.offers.map((o, i) => `<span class="${i ? "" : "best"}">${esc(o.supplier_name)} — ${money(o.price)}<i>${fmtDate(o.date)}</i></span>`).join("")}</small>`
    : l.offers.length ? "" : `<small class="muted">закупок у поставщиков ещё не было, цена из справочника</small>`;
  const box = modal(`<div class="m-h"><h3>Заказ поставщикам</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="po-head"><span class="muted">Заказываем то, что ниже минимума или закончится раньше чем через 14 дней. Средний расход — за последние 60 дней. Поставщик — тот, у кого последняя цена ниже.</span>
        <label class="fl po-cover">Запас на, дней<input class="input num" type="number" min="1" max="365" id="poCover" value="${r.cover_days}"></label></div>
      ${r.groups.length ? r.groups.map((g, gi) => `<section class="po-group" id="po${gi}">
        <div class="po-gh"><div><b>${esc(g.supplier_name)}</b><small class="muted">${esc([g.phone, g.inn && "ИНН " + g.inn].filter(Boolean).join(" · "))}</small></div>
          <span class="grow"></span><b>${money(g.total)}</b>
          <button class="icon-btn" title="Скачать в Excel" data-xls="#po${gi} table.tbl" data-xls-name="Заказ — ${esc(g.supplier_name)}">${XLS}</button>
          <button class="icon-btn" title="Печать заявки" data-po-print="${gi}">${PRINT_ICON}</button>
          ${edit ? `<button class="btn small" data-po-save="${gi}" title="Записать заказ: заказанное покажется «в пути» и не будет заказано второй раз">Сформировать заказ</button><button class="btn ghost small" data-po-in="${gi}">Оформить приход</button>` : ""}</div>
        <table class="tbl compact"><thead><tr><th>Код</th><th>Материал</th><th class="num">Остаток</th><th class="num">Минимум</th><th class="num">Расход в день</th><th>Почему</th><th class="num">Заказать</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${
          g.lines.map(l => `<tr><td class="muted">${esc(l.code)}</td><td><b>${esc(l.name)}</b>${offers(l)}</td>
            <td class="num">${qtyFmt(l.usable, l.unit)}${l.expired_qty ? `<small class="bad-t" style="display:block">+ просрочено ${qtyFmt(l.expired_qty)}</small>` : ""}</td>
            <td class="num muted">${l.min_qty ? qtyFmt(l.min_qty) : "—"}${l.in_transit ? `<small class="muted" style="display:block">в пути ${qtyFmt(l.in_transit)}</small>` : ""}</td><td class="num muted">${l.daily ? qtyFmt(l.daily) : "—"}</td><td class="muted">${esc(l.why)}</td>
            <td class="num"><b>${qtyFmt(l.qty, l.unit)}</b></td><td class="num">${money(l.price)}</td><td class="num">${money(l.sum)}</td></tr>`).join("")}</tbody></table></section>`).join("")
      : `<div class="empty"><b>Заказывать нечего</b><span>Всех материалов хватит больше чем на 14 дней, и все выше минимума</span></div>`}
    </div>
    <div class="m-f"><span class="muted">${r.count ? `Позиций: ${r.count} · поставщиков: ${r.groups.length} · на сумму ${money(r.total)}` : ""}</span>
      <button class="btn ghost" data-close>Закрыть</button>${r.groups.length ? `<button class="btn" id="poPrintAll">Печать всех заявок</button>` : ""}</div>`, {wide: true});
  let t; $("#poCover", box).oninput = e => { clearTimeout(t); t = setTimeout(() => { const v = +e.target.value; if (v >= 1 && v <= 365) openPurchase(v); }, 500); };
  $$("[data-po-print]", box).forEach(b => b.onclick = () => printPurchase([r.groups[+b.dataset.poPrint]]));
  const pa = $("#poPrintAll", box); if (pa) pa.onclick = () => printPurchase(r.groups);
  $$("[data-po-save]", box).forEach(b => b.onclick = async () => { const g = r.groups[+b.dataset.poSave];
    try { await api.stock_order_save({supplier_id: g.supplier_id || "", lines: g.lines.map(l => ({material_id: l.material_id, qty: l.qty, price: l.price}))});
      toast(`Заказ записан${g.supplier_id ? ": " + g.supplier_name : ""}`); closeModal(); if (S.matOpen) mtCard(); else stockGo("stock", "orders"); } catch (x) { toast(errText(x), true); } });
  $$("[data-po-in]", box).forEach(b => b.onclick = () => { const g = r.groups[+b.dataset.poIn];
    openStockDoc("receipt", g.lines.map(l => ({material_id: l.material_id, qty: l.qty, price: l.price})),
      {supplier_id: g.supplier_id || "", comment: `По заказу от ${fmtDate(iso(new Date()))}`}); });
}

async function printPurchase(groups) {
  const head = await clinicHead();
  const c = (await ref()).clinic || {};
  $("#printArea").innerHTML = groups.map((g, gi) => `<div style="${gi ? "break-before:page;page-break-before:always" : ""}">${head}
    <h2 style="text-align:center">Заявка на поставку от ${fmtDate(iso(new Date()))}</h2>
    <p>Поставщик: <b>${esc(g.supplier_id ? g.supplier_name : "____________________")}</b>${g.inn ? ", ИНН " + esc(g.inn) : ""}${g.phone ? ", тел. " + esc(g.phone) : ""}</p>
    <table><tr><th>№</th><th>Наименование</th><th>Код</th><th>Ед.</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr>
      ${g.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.name)}</td><td>${esc(l.code)}</td><td>${esc(l.unit)}</td><td>${qtyFmt(l.qty)}</td><td>${money(l.price)}</td><td>${money(l.sum)}</td></tr>`).join("")}
      <tr><td colspan="6" style="text-align:right"><b>Итого</b></td><td><b>${money(g.total)}</b></td></tr></table>
    <p>Цены — по последней закупке, просим подтвердить актуальные цены и срок поставки.</p>
    ${signLines([{role: "Заказ составил", name: ME ? ME.name : ""}, {role: "Руководитель", name: c.director || ""}])}</div>`).join("");
  window.print();
}

/* ------------------------------------------------ 3.14 «Закупки»: orders to suppliers and what is on its way */
async function stockOrders() {
  const body = $("#stockBody");
  const r = await api.stock_orders({status: S.ordStatus || ""});
  const edit = can("stock_edit"), list = r.orders, open = list.filter(o => ["ordered", "partial"].includes(o.status));
  body.innerHTML = `<div class="stat-row"><div class="stat"><span>Открытых заказов</span><b>${open.length}</b></div>
      <div class="stat ${open.some(o => o.late) ? "warn" : ""}"><span>Опаздывают</span><b>${open.filter(o => o.late).length}</b></div>
      <div class="stat"><span>В пути на сумму</span><b>${money(open.reduce((s, o) => s + o.lines.reduce((t, l) => t + l.left * (+l.price || 0), 0), 0))}</b></div></div>
    <div class="tab-tools"><select class="input sm-sel" id="ordSt"><option value="">Все заказы</option>${Object.entries(r.statuses).map(([k, t]) => `<option value="${k}" ${k === S.ordStatus ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <span class="grow"></span><button class="btn" id="ordNew" title="Что и сколько заказать, у кого дешевле">Заказ поставщикам</button></div>
    <div class="pbody" style="margin-top:8px">${list.length ? list.map(o => `<section class="po-group ord-card ${o.status}">
        <div class="po-gh"><div><b>${esc(o.number)} · ${o.supplier_name ? esc(o.supplier_name) : "поставщик не выбран"}</b><small class="muted">от ${fmtDate(o.date)}${o.expected ? ` · ожидается ${fmtDate(o.expected)}` : ""}${o.user_name ? " · " + esc(o.user_name) : ""}${o.comment ? " · " + esc(o.comment) : ""}</small></div>
          <span class="grow"></span>${o.late ? `<span class="pill st-cancel">опаздывает</span>` : ""}<span class="pill ${o.status === "received" ? "st-ok" : o.status === "cancelled" ? "st-cancel" : o.status === "partial" ? "st-done" : "st-come"}">${esc(o.status_title)}</span><b>${money(o.total)}</b>
          ${edit && ["ordered", "partial"].includes(o.status) ? `<button class="btn small" data-in="${esc(o.id)}">Принять по заказу</button><button class="btn ghost small danger-t" data-x="${esc(o.id)}">Отменить</button>` : ""}</div>
        <table class="tbl compact"><thead><tr><th>Материал</th><th class="num">Заказано</th><th class="num">Получено</th><th class="num">В пути</th><th class="num">Цена</th></tr></thead><tbody>${o.lines.map(l => `<tr data-m="${esc(l.material_id)}"><td class="lnk"><b>${esc(l.name)}</b>${l.number ? ` <small class="muted">${esc(l.number)}</small>` : ""}</td>
          <td class="num">${qtyFmt(l.qty, l.unit)}</td><td class="num">${qtyFmt(l.received, l.unit)}</td><td class="num"><b>${["ordered", "partial"].includes(o.status) ? qtyFmt(l.left, l.unit) : "—"}</b></td><td class="num">${money(l.price)}</td></tr>`).join("")}</tbody></table></section>`).join("")
      : `<div class="empty"><b>Заказов нет</b><span>«Заказ поставщикам» подберёт, что заказать, и запишет заказ — заказанное будет «в пути» до прихода</span></div>`}</div>`;
  $("#ordSt").onchange = e => { S.ordStatus = e.target.value; stockOrders(); };
  $("#ordNew").onclick = () => openPurchase();
  $$("tr[data-m]", body).forEach(tr => tr.onclick = () => openMaterial(tr.dataset.m, "buy"));
  $$("[data-in]", body).forEach(b => b.onclick = () => receiveByOrder(list.find(o => o.id === b.dataset.in)));
  $$("[data-x]", body).forEach(b => b.onclick = () => cancelOrder(list.find(o => o.id === b.dataset.x), stockOrders));
}
/** The usual receipt form, filled with what is still on its way by the order; the receipt counts against it. */
function receiveByOrder(o) {
  const lines = o.lines.filter(l => l.left > 0).map(l => ({material_id: l.material_id, qty: l.left, price: l.price}));
  if (!lines.length) return toast("По заказу всё получено");
  openStockDoc("receipt", lines, {supplier_id: o.supplier_id || "", comment: `По заказу ${o.number} от ${fmtDate(o.date)}`, order_id: o.id});
}
async function cancelOrder(o, after) {
  if (!await ask(`Отменить заказ ${o.number}?`, {danger: true, ok: "Отменить заказ", cancel: "Не отменять", text: "Заказанное перестанет считаться «в пути». Полученное по нему останется на складе."})) return;
  try { await api.stock_order_cancel(o.id); toast("Заказ отменён"); after(); } catch (x) { toast(errText(x), true); }
}
