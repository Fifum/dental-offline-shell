"use strict";
/* 3.13 «Карточка материала» — a screen of «Склад → Главная / Остатки» in the style of the equipment card (stock-eqcard.js,
   classes .eqc-*): the photo, the balance and its money, the stock by place, lots and expiry dates, the history of suppliers
   by each delivery (date, supplier, quantity, price, invoice — a material is bought from different suppliers over time),
   the last supplier and the best price, the norms per service and the moves. */
const MT = {id: null, tab: "main", data: null};
const MTI = {
  box: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/></svg>',
  truck: '<svg viewBox="0 0 24 24"><path d="M3 6.5h11v9H3zM14 9.5h3.8l3.2 3.3v2.7h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/></svg>',
  tag: '<svg viewBox="0 0 24 24"><path d="M3.5 12.2V4.5h7.7l9.3 9.3-7.7 7.7z"/><circle cx="8" cy="9" r="1.4"/></svg>',
  bar: '<svg viewBox="0 0 24 24"><path d="M4 6v12M7 6v12M10 6v12M13.5 6v12M16 6v12M20 6v12"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/></svg>',
  cart: '<svg viewBox="0 0 24 24"><path d="M3 4.5h2.4l2.3 10.3h10.5l2.3-7.3H6.3"/><circle cx="9.3" cy="18.8" r="1.4"/><circle cx="16.8" cy="18.8" r="1.4"/></svg>',
  use: '<svg viewBox="0 0 24 24"><path d="M12 3.5v4M12 16.5v4M7 12H3.5M20.5 12H17"/><circle cx="12" cy="12" r="4.5"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 4 2.4 5 5.4.6-4 3.7 1.1 5.4L12 16l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z"/></svg>',
};
const mtQty = (n, u) => qtyFmt(n, u);

/** Opens the card of a material in place of the list (home screen or «Остатки»). */
async function openMaterial(id, tab) {
  if ($("#modal") && !$("#modal").hidden) closeModal();
  document.querySelectorAll(".sn-menu,.eqc-menu").forEach(x => x.remove());
  S.eqOpen = null;
  MT.tab = tab || (MT.id === id ? MT.tab : "main") || "main"; MT.id = id;
  S.matOpen = id;
  // 3.14: the card belongs to «Склад и материалы» (its home screen or «Остатки»); from elsewhere — a scan, a task, another section
  if (S.view !== "stock" || $("#view-stock").hidden || !["home", "balance"].includes(S.stockTab))
    return stockGo("stock", ["home", "balance"].includes(S.stockTabs.stock) ? S.stockTabs.stock : canAny("stock_view", "stock_edit") ? "balance" : "home");
  return mtCard();
}
function mtClose() { S.matOpen = null; MT.id = null; MT.data = null; loadStock(); }

async function mtCard() {
  const body = $("#stockBody");
  let m;
  try { m = await api.material(MT.id); } catch (e) { toast(errText(e), true); S.matOpen = null; return loadStock(); }
  if (!m) { toast("Материал не найден", true); S.matOpen = null; return loadStock(); }
  MT.data = m;
  const c = m.can || {}, off = !m.active, u = m.unit;
  const usable = Math.round((m.balance - (m.expired_qty || 0)) * 1000) / 1000;
  const state = m.balance < 0 ? ["bad", "Меньше нуля"] : m.balance <= 0 ? ["bad", "Нет в наличии"] : m.low ? ["warn", "Заканчивается"] : ["ok", "Есть в наличии"];
  const ls = m.last_supply, best = m.best_offer, us = m.usage || {};
  const lots = (m.lot_list && m.lot_list.lots) || [], near = lots.filter(g => g.expires).sort((a, b) => a.expires < b.expires ? -1 : 1)[0];
  const target = m.min_qty ? m.min_qty * 2 : 0;
  const pct = target ? Math.max(0, Math.min(100, m.balance / target * 100)) : (m.balance > 0 ? 100 : 0);
  const tile = (ic, t, v, sub = "") => `<div class="eqc-tile"><i>${ic}</i><span>${t}</span><b>${v}</b>${sub ? `<small class="mtc-sub">${sub}</small>` : ""}</div>`;
  const tabs = [["main", EQI.info, "Основное"], ["supplies", MTI.truck, `Поставки${m.supply_count ? ` <i class="cnt">${m.supply_count}</i>` : ""}`],
    ["lots", EQI.cal, "Партии и сроки"], ["norms", MTI.list, "Нормы по услугам"], ["moves", EQI.hist, "Движение"]];
  if (!tabs.some(t => t[0] === MT.tab)) MT.tab = "main";
  const acts = off ? [] : [
    c.edit ? ["in", SN_ICON.receive, "Приход по накладной"] : c.ops && ["receive", SN_ICON.receive, "Принять поставку"],
    c.edit ? ["out", EQI.trash, "Списание"] : c.ops && ["use", SN_ICON.use, c.direct ? "Зафиксировать расход" : "Расход — на согласование"],
    c.ops && hasPlaces() && ["issue", SN_ICON.issue, "Выдать в кабинет"],
    c.ops && ["req", MTI.cart, "Добавить в заявку"],
    c.edit && ["order", MTI.truck, "Заказ поставщикам"],
    c.photo && ["photo", EQI.camera, m.photo_id ? "Заменить фотографию" : "Добавить фотографию"]].filter(Boolean);
  const back = S.stockTab === "home" ? "Склад" : "Остатки";
  body.innerHTML = `<div class="eqc mtc">
    <div class="eqc-crumbs"><button class="eqc-back" id="mtBack" title="К списку материалов">${EQI.back}</button><button class="linkbtn" id="mtBack2">${back}</button>${EQI.chev}<b>Карточка материала</b></div>
    <div class="eqc-head"><h2>Карточка материала</h2>${m.code ? `<span class="eqc-chip">Арт. ${esc(m.code)}</span>` : ""}<span class="grow"></span>
      ${c.edit && !off ? `<button class="btn ghost eqc-hb" id="mtIn">${SN_ICON.receive}Приход</button><button class="btn ghost eqc-hb" id="mtEdit">${EQI.pen}Редактировать</button>` : ""}
      ${c.edit && !off ? `<button class="icon-btn eqc-more" id="mtMore" title="Ещё">${EQI.more}</button>` : ""}</div>
    ${off ? `<div class="warn-line">Материал убран из справочника. История поставок и движения сохранилась; карточка только для просмотра.</div>` : ""}
    <div class="eqc-grid"><div class="eqc-main">
      <section class="eqc-card eqc-top">
        <div class="eqc-gal"><div class="eqc-photo" id="mtPhoto" ${m.photo_id ? `data-big="${esc(m.photo_id)}"` : ""}>${EQI.ph}${m.photo_id ? `<button class="eqc-exp" id="mtExp" title="Открыть фото">${EQI.expand}</button>` : ""}</div>
          <div class="eqc-dots">${c.photo && !off ? `<button class="linkbtn" id="mtPh">${EQI.camera}${m.photo_id ? "Заменить фото" : "Добавить фото"}</button>${m.photo_id ? `<button class="linkbtn" id="mtPhDel">убрать</button>` : ""}` : ""}</div></div>
        <div class="eqc-id"><span class="eqc-badge ${state[0]}">${state[0] === "ok" ? EQI.okc : EQI.warn}${state[1]}</span>${m.exp_state === "expired" ? `<span class="eqc-badge bad">${EQI.cal}Есть просроченное</span>` : m.exp_state === "soon" ? `<span class="eqc-badge warn">${EQI.cal}Истекает срок</span>` : ""}
          <h3>${esc(m.name)}</h3><div class="eqc-inv">${m.code ? `Артикул: ${esc(m.code)}` : "Артикул не указан"}</div>
          <ul><li>${EQI.layers}<span>${esc(m.category || "Раздел не указан")}</span></li><li>${MTI.box}<span>Единица: ${esc(u || "шт")}</span></li>
            ${m.barcode ? `<li>${MTI.bar}<span class="mtc-code">${esc(m.barcode)}</span></li>` : ""}
            <li>${MTI.truck}${ls ? `<span>Поставщик: <b>${esc(ls.supplier_name)}</b></span>` : `<span class="muted">Поставок от поставщиков ещё не было</span>`}</li></ul></div>
        <div class="eqc-money"><div class="eqc-tiles">${tile(MTI.box, "Остаток", mtQty(m.balance, u), m.balance_doc !== undefined && Math.abs(m.balance - m.balance_doc) > 1e-9 ? `по документам: ${mtQty(m.balance_doc, u)}` : m.min_qty ? `минимум ${mtQty(m.min_qty, u)}` : "")}
            ${tile(EQI.coins, "Сумма остатка", money(m.value), `по ${money(m.price)} за ${esc(u || "шт")}`)}
            ${tile(MTI.tag, "Последняя цена", ls ? money(ls.price) : money(m.price), ls ? `закупка ${fmtDate(ls.date)}` : "")}
            ${tile(MTI.star, "Лучшая цена", best ? money(best.price) : "—", best ? esc(best.supplier_name) : "нет поставок")}</div>
          <div class="eqc-amort"><div><span>${m.min_qty ? "Запас к минимуму" : "Запас"}</span><b>${us.days_left != null ? `хватит ≈ на ${Math.round(us.days_left)} ${plural(Math.round(us.days_left), "день", "дня", "дней")}` : usable > 0 ? "расхода не было" : "нет"}</b></div>
            <i><u class="${m.low || m.balance <= 0 ? "low" : ""}" style="width:${pct}%"></u></i><small class="muted">${us.used ? `Расход за ${us.days} дней: ${mtQty(us.used, u)} · в среднем ${mtQty(us.daily, u)} в день` : `За ${us.days || 60} дней материал не расходовался`}${m.min_qty ? ` · полоса — от двух минимумов (${mtQty(target, u)})` : ""}</small></div></div>
      </section>
      <div class="eqc-tabs" id="mtTabs" role="tablist">${tabs.map(([k, ic, t]) => `<button data-t="${k}" class="${k === MT.tab ? "on" : ""}">${ic}${t}</button>`).join("")}</div>
      <section class="eqc-card eqc-pane" id="mtPane"></section>
    </div>
    <aside class="eqc-side">
      ${acts.length ? `<section class="eqc-card"><h3>Быстрые действия</h3><div class="eqc-acts">${acts.map(([k, ic, t]) => `<button data-act="${k}">${ic}<span>${t}</span>${EQI.chev}</button>`).join("")}</div></section>` : ""}
      <button class="eqc-card eqc-next" id="mtLast"><i>${MTI.truck}</i><span><small>Последний поставщик</small><b>${ls ? esc(ls.supplier_name) : "Нет поставок"}</b>${ls ? `<small>${fmtDate(ls.date)} · ${mtQty(ls.qty, u)} по ${money(ls.price)}${ls.doc_number ? ` · № ${esc(ls.doc_number)}` : ""}</small>` : ""}</span>${EQI.chev}</button>
      <button class="eqc-card eqc-next mtc-best" id="mtBest"><i>${MTI.star}</i><span><small>Лучшая цена</small><b>${best ? money(best.price) : "—"}</b>${best ? `<small>${esc(best.supplier_name)} · последняя закупка ${fmtDate(best.date)}</small>` : `<small>Появится после прихода от поставщика</small>`}</span>${EQI.chev}</button>
      <button class="eqc-card eqc-next ${near && near.state !== "ok" ? "due" : ""}" id="mtNear"><i>${EQI.cal}</i><span><small>Ближайший срок годности</small><b>${near ? eqLongDate(near.expires) : "Без сроков"}</b>${near ? (near.state === "expired" ? `<em>просрочено: ${mtQty(near.left, u)}</em>` : near.state === "soon" ? `<em>осталось ${near.days} ${plural(near.days, "день", "дня", "дней")} · ${mtQty(near.left, u)}</em>` : `<small>партия ${esc(near.lot || "без номера")} · ${mtQty(near.left, u)}</small>`) : ""}</span>${EQI.chev}</button>
    </aside></div></div>`;
  const on = (s, f) => { const el = $(s, body); if (el) el.onclick = f; };
  on("#mtBack", mtClose); on("#mtBack2", mtClose);
  on("#mtIn", () => mtAction("in")); on("#mtEdit", () => editMaterial(m));
  on("#mtMore", ev => mtMoreMenu(ev.currentTarget, m));
  on("#mtLast", () => mtTab("supplies")); on("#mtBest", () => mtTab("supplies")); on("#mtNear", () => mtTab("lots"));
  on("#mtPh", () => photoPick("material", m.id, () => mtCard()));
  on("#mtPhDel", async () => { try { await api.stock_photo_clear("material", m.id); toast("Фото убрано"); mtCard(); } catch (x) { toast(errText(x), true); } });
  $$("#mtTabs button", body).forEach(b => b.onclick = () => mtTab(b.dataset.t));
  $$("[data-act]", body).forEach(b => b.onclick = () => mtAction(b.dataset.act));
  mtPane();
  const big = $("#mtPhoto", body);
  if (big && big.dataset.big) {
    try { const ph = await api.stock_photo(big.dataset.big); big.insertAdjacentHTML("afterbegin", `<img src="${ph.url}" alt="">`); big.classList.add("has");
      const ex = $("#mtExp", body); if (ex) ex.onclick = () => eqViewer(ph.url, m.name); big.onclick = ev => { if (ev.target === big || ev.target.tagName === "IMG") eqViewer(ph.url, m.name); };
    } catch (x) { /* the photo did not come from the other computer yet */ }
  }
}
function mtTab(t) { MT.tab = t; $$("#mtTabs button").forEach(b => b.classList.toggle("on", b.dataset.t === t)); mtPane(); const p = $("#mtPane"); if (p && t !== "main") p.scrollIntoView({block: "nearest", behavior: "smooth"}); }

function mtPane() {
  const el = $("#mtPane"); if (!el || !MT.data) return;
  const m = MT.data, c = m.can || {}, u = m.unit;
  const kv = rows => `<table class="eqc-kv">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
  const nz = (v, t = "Не указан") => v ? esc(v) : `<span class="muted">${t}</span>`;
  if (MT.tab === "main") {
    const locs = (m.by_location || []).filter(x => Math.abs(x.qty) > 1e-9), max = Math.max(1e-9, ...locs.map(x => Math.abs(x.qty)));
    el.innerHTML = `<div class="eqc-two"><div><h3>Общие сведения</h3>${kv([["Наименование", esc(m.name)], ["Артикул / код", nz(m.code)], ["Раздел", nz(m.category)],
        ["Единица", esc(u || "шт")], ["Штрихкод", nz(m.barcode)], ["Минимальный остаток", m.min_qty ? mtQty(m.min_qty, u) : nz("", "Не задан")],
        ["Цена (последняя закупка)", money(m.price)], ["Комментарий", nz(m.comment, "—")]])}</div>
      <div><h3>Остаток по местам</h3>${locs.length ? `<div class="mtc-locs">${locs.map(x => `<div class="mtc-loc ${x.qty < 0 ? "neg" : ""}"><span>${EQI.pin}${esc(x.name)}</span><b>${mtQty(x.qty, u)}</b><i><u style="width:${Math.max(3, Math.abs(x.qty) / max * 100)}%"></u></i></div>`).join("")}</div>`
        : `<div class="muted">${m.balance ? "Весь остаток на основном складе" : "Остатка нет"}</div>`}
        ${(m.supplier_stats || []).length ? `<h3>Поставщики</h3><div class="mtc-sups">${m.supplier_stats.slice(0, 4).map(g => `<div class="mtc-sup ${g.best ? "best" : ""}"><b>${esc(g.supplier_name)}</b><span>${g.count} ${plural(g.count, "поставка", "поставки", "поставок")} · последняя ${fmtDate(g.last_date)} по ${money(g.last_price)}</span>${g.best ? `<em>${MTI.star}лучшая цена</em>` : ""}</div>`).join("")}</div>` : ""}</div></div>`;
    return;
  }
  if (MT.tab === "supplies") {
    const sups = m.supplier_stats || [], rows = m.supplies || [];
    el.innerHTML = `<h3>Поставщики этого материала</h3>
      ${sups.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Поставщик</th><th class="num">Поставок</th><th class="num">Всего</th><th>Последняя</th><th class="num">Посл. цена</th><th class="num">Мин. цена</th><th class="num">Средняя</th><th></th></tr></thead><tbody>${sups.map(g => `<tr class="${g.best ? "mtc-best-row" : ""}">
          <td class="wrap"><b>${esc(g.supplier_name)}</b></td><td class="num">${g.count}</td><td class="num">${mtQty(g.qty, u)}</td><td>${fmtDateShort(g.last_date)}</td><td class="num"><b>${money(g.last_price)}</b></td>
          <td class="num">${g.min_price != null ? money(g.min_price) : "—"}</td><td class="num muted">${money(g.avg_price)}</td><td>${g.best ? `<span class="pill st-ok">лучшая цена</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="muted eqc-hint">«Лучшая цена» — у кого последняя закупка дешевле всего. Её же предлагает «Заказ поставщикам».</div>`
        : `<div class="muted">Поставщиков пока нет. Он запишется сам при приходе по накладной — укажите поставщика в документе.</div>`}
      <h3>История поставок <span class="muted">${m.supply_count || 0}</span></h3>
      ${rows.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Дата</th><th>Поставщик</th><th class="num">Количество</th><th class="num">Цена</th><th class="num">Сумма</th><th>Накладная · партия</th></tr></thead><tbody>${rows.map(r => {
          const lot = [r.lot ? "партия " + r.lot : "", r.expires ? "годен до " + fmtDateShort(r.expires) : ""].filter(Boolean).join(", ");
          const tip = [r.user_name ? "Принял: " + r.user_name : "", hasPlaces() ? "Куда: " + r.location_name : ""].filter(Boolean).join(" · ");
          return `<tr title="${esc(tip)}"><td>${fmtDateShort(r.day)}</td><td class="wrap">${r.supplier_name ? `<b>${esc(r.supplier_name)}</b>` : `<span class="muted">не указан</span>`}</td>
          <td class="num">${mtQty(r.qty, u)}</td><td class="num">${money(r.price)}</td><td class="num">${money(r.sum)}</td>
          <td class="wrap">${r.doc_id ? `<button class="linkbtn" data-doc="${esc(r.doc_id)}">${r.doc_number ? "№ " + esc(r.doc_number) : "без номера"}</button>` : `<span class="muted">—</span>`}${r.nodoc ? ' <span class="pill dx-nodoc">без документа</span>' : ""}${lot ? `<small class="mtc-lot">${esc(lot)}</small>` : ""}</td></tr>`; }).join("")}</tbody></table></div>
        ${m.supply_count > rows.length ? `<div class="muted eqc-hint">Показаны последние ${rows.length} из ${m.supply_count}</div>` : ""}`
        : `<div class="muted">Приходов ещё не было${c.edit ? " — нажмите «Приход»" : ""}.</div>`}`;
    $$("[data-doc]", el).forEach(b => b.onclick = () => openStockDocView(b.dataset.doc));
    return;
  }
  if (MT.tab === "lots") {
    el.innerHTML = `<h3>Партии и сроки годности</h3>${lotsTable(m.lot_list, u, c.edit && m.active)}`;
    $$("[data-lot-out]", el).forEach(b => b.onclick = () => { const g = m.lot_list.lots.find(x => String(x.id) === b.dataset.lotOut);
      openStockDoc("writeoff", [{material_id: m.id, qty: g.left, lot_id: g.id, lot: g.lot, expires: g.expires}], {reason: g.state === "expired" ? "Истёк срок годности" : ""}); });
    return;
  }
  if (MT.tab === "norms") {
    el.innerHTML = `<h3>Списывается по услугам</h3>${m.norms.length ? `<table class="tbl compact mtc-t"><thead><tr><th>Услуга</th><th>Код</th><th class="num">На одну услугу</th></tr></thead><tbody>${m.norms.map(n => `<tr><td>${esc(n.title)}</td><td class="muted">${esc(n.code || "")}</td><td class="num"><b>${mtQty(n.qty, u)}</b></td></tr>`).join("")}</tbody></table>`
      : `<div class="muted">Не привязан к услугам.</div>`}<div class="muted eqc-hint">Нормы задаются во вкладке «Нормы списания»${c.edit ? ` <button class="linkbtn" id="mtNorms">открыть</button>` : ""}.</div>`;
    const n = $("#mtNorms", el); if (n) n.onclick = () => { S.matOpen = null; stockGo("stock", "norms"); };
    return;
  }
  el.innerHTML = `<h3>Движение</h3>${movesTable(m.moves, false)}`;
}

function mtAction(k) {
  const m = MT.data; if (!m) return;
  const leave = () => { S.matOpen = null; };  // the nurse's screens take the place of the card and come back to «Склад»
  if (k === "in") return openStockDoc("receipt", [{material_id: m.id, qty: "", price: (m.last_supply || {}).price || m.price}], {supplier_id: (m.last_supply || {}).supplier_id});
  if (k === "out") return openStockDoc("writeoff", [{material_id: m.id, qty: ""}]);
  if (k === "receive") { leave(); return openReceiveScreen(); }
  if (k === "use") { leave(); return openUseScreen({lines: {[m.id]: 1}}); }
  if (k === "issue") { leave(); return openIssueScreen({lines: {[m.id]: 1}}); }
  if (k === "req") { leave(); return openRequestScreen({lines: {[m.id]: 1}}); }
  if (k === "order") return openPurchase();
  if (k === "photo") return photoPick("material", m.id, () => mtCard());
}

function mtMoreMenu(btn, m) {
  const items = [["edit", "Редактировать"], ["out", "Списание"], ["order", "Заказ поставщикам"], ["del", "Убрать из справочника"]];
  const old = $(".eqc-menu"); if (old) { old.remove(); return; }
  const menu = document.createElement("div"); menu.className = "eqc-menu";
  menu.innerHTML = items.map(([k, t]) => `<button data-m="${k}" class="${k === "del" ? "danger-t" : ""}">${t}</button>`).join("");
  btn.parentElement.appendChild(menu);
  const close = () => { menu.remove(); document.removeEventListener("click", out, true); };
  const out = ev => { if (!menu.contains(ev.target) && ev.target !== btn) close(); };
  setTimeout(() => document.addEventListener("click", out, true));
  $$("[data-m]", menu).forEach(b => b.onclick = async () => { close();
    if (b.dataset.m === "edit") return editMaterial(m);
    if (b.dataset.m === "del") {
      if (!(await ask(`Убрать «${m.name}» из справочника?`, {danger: true, ok: "Убрать", text: "История поставок и движения сохранится, нормы списания по услугам удалятся."}))) return;
      try { await api.delete_material(m.id); toast("Убрано из справочника"); mtClose(); } catch (x) { toast(errText(x), true); }
      return;
    }
    mtAction(b.dataset.m);
  });
}
