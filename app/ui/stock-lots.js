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
          ${edit ? `<button class="btn small" data-po-in="${gi}">Оформить приход по заказу</button>` : ""}</div>
        <table class="tbl compact"><thead><tr><th>Код</th><th>Материал</th><th class="num">Остаток</th><th class="num">Минимум</th><th class="num">Расход в день</th><th>Почему</th><th class="num">Заказать</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${
          g.lines.map(l => `<tr><td class="muted">${esc(l.code)}</td><td><b>${esc(l.name)}</b>${offers(l)}</td>
            <td class="num">${qtyFmt(l.usable, l.unit)}${l.expired_qty ? `<small class="bad-t" style="display:block">+ просрочено ${qtyFmt(l.expired_qty)}</small>` : ""}</td>
            <td class="num muted">${l.min_qty ? qtyFmt(l.min_qty) : "—"}</td><td class="num muted">${l.daily ? qtyFmt(l.daily) : "—"}</td><td class="muted">${esc(l.why)}</td>
            <td class="num"><b>${qtyFmt(l.qty, l.unit)}</b></td><td class="num">${money(l.price)}</td><td class="num">${money(l.sum)}</td></tr>`).join("")}</tbody></table></section>`).join("")
      : `<div class="empty"><b>Заказывать нечего</b><span>Всех материалов хватит больше чем на 14 дней, и все выше минимума</span></div>`}
    </div>
    <div class="m-f"><span class="muted">${r.count ? `Позиций: ${r.count} · поставщиков: ${r.groups.length} · на сумму ${money(r.total)}` : ""}</span>
      <button class="btn ghost" data-close>Закрыть</button>${r.groups.length ? `<button class="btn" id="poPrintAll">Печать всех заявок</button>` : ""}</div>`, {wide: true});
  let t; $("#poCover", box).oninput = e => { clearTimeout(t); t = setTimeout(() => { const v = +e.target.value; if (v >= 1 && v <= 365) openPurchase(v); }, 500); };
  $$("[data-po-print]", box).forEach(b => b.onclick = () => printPurchase([r.groups[+b.dataset.poPrint]]));
  const pa = $("#poPrintAll", box); if (pa) pa.onclick = () => printPurchase(r.groups);
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
