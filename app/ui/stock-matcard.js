"use strict";
/* «Карточка материала» — a screen of «Склад и материалы → Главная / Остатки» in the style of the equipment card (stock-eqcard.js,
   classes .eqc-*). 3.14 — after the mockup the clinic chose: the number «МТ-…», the photo gallery and the status, the tiles
   (current, reserved for the cabinets' requests, on its way from suppliers, the average use a month), the coverage in days,
   the tabs Основное / Остатки и партии / Расход / Закупки / Аналоги / Документы / История, the barcode and the QR of its label,
   the four fields saved at once (minimum, optimal stock, delivery term, main supplier), quick actions by the rights, the
   analytics and the services it is used in. 3.13: the history of suppliers by each delivery stays in «Закупки». */
const MT = {id: null, tab: "main", data: null, gal: 0, docKind: null};
const MTI = {
  box: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/></svg>',
  truck: '<svg viewBox="0 0 24 24"><path d="M3 6.5h11v9H3zM14 9.5h3.8l3.2 3.3v2.7h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/></svg>',
  tag: '<svg viewBox="0 0 24 24"><path d="M3.5 12.2V4.5h7.7l9.3 9.3-7.7 7.7z"/><circle cx="8" cy="9" r="1.4"/></svg>',
  bar: '<svg viewBox="0 0 24 24"><path d="M4 6v12M7 6v12M10 6v12M13.5 6v12M16 6v12M20 6v12"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/></svg>',
  cart: '<svg viewBox="0 0 24 24"><path d="M3 4.5h2.4l2.3 10.3h10.5l2.3-7.3H6.3"/><circle cx="9.3" cy="18.8" r="1.4"/><circle cx="16.8" cy="18.8" r="1.4"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 4 2.4 5 5.4.6-4 3.7 1.1 5.4L12 16l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z"/></svg>',
  stack: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="6.5" rx="7" ry="2.8"/><path d="M5 6.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5M5 11.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5"/></svg>',
  reserve: '<svg viewBox="0 0 24 24"><path d="M4 19.5h16M6.5 15.5l4-4 3 3 5-6"/><path d="M15 8.5h3.5V12"/></svg>',
  cycle: '<svg viewBox="0 0 24 24"><path d="M19.5 12a7.5 7.5 0 0 1-13 5M4.5 12a7.5 7.5 0 0 1 13-5"/><path d="M17.5 3.5V7H14M6.5 20.5V17H10"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8.5v7M8.5 12h7"/></svg>',
  inbox: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2.5"/><path d="M12 8.5v6M9.3 11.8 12 14.5l2.7-2.7"/></svg>',
  out: '<svg viewBox="0 0 24 24"><path d="M4 12h12M12.5 8l4 4-4 4M19.5 5v14"/></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2H5z"/><path d="M10 20.5h4"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  rub: '<svg viewBox="0 0 24 24"><ellipse cx="9" cy="7" rx="5.5" ry="2.5"/><path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5S14.5 12.4 14.5 11V7"/><path d="M9.5 15.5c.6 1 2.6 1.8 5 1.8 3 0 5.5-1.1 5.5-2.5v-4c0-1.2-1.8-2.2-4.3-2.5"/></svg>',
  box2: '<svg viewBox="0 0 24 24"><rect x="4.5" y="7" width="15" height="12.5" rx="2"/><path d="M8.5 7V5.5a1.5 1.5 0 0 1 1.5-1.5h4a1.5 1.5 0 0 1 1.5 1.5V7M4.5 11.5h15"/></svg>',
  target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 12 19 5"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
};
const mtQty = (n, u) => qtyFmt(n, u);
const mtDays = n => `${Math.round(n)} ${plural(Math.round(n), "день", "дня", "дней")}`;

/** Opens the card of a material in place of the list (home screen or «Остатки»). */
async function openMaterial(id, tab) {
  if ($("#modal") && !$("#modal").hidden) closeModal();
  document.querySelectorAll(".sn-menu,.eqc-menu").forEach(x => x.remove());
  S.eqOpen = null;
  if (MT.id !== id) { MT.gal = 0; MT.docKind = null; }
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
  const [stCls, stText] = m.status || ["ok", "В наличии"];
  const tile = (ic, t, v, sub = "") => `<div class="eqc-tile"><i>${ic}</i><span>${t}</span><b>${v}</b>${sub ? `<small class="mtc-sub">${sub}</small>` : ""}</div>`;
  const tabs = [["main", EQI.info, "Основное"], ["lots", MTI.stack, "Остатки и партии"], ["use", EQI.chart, "Расход"],
    ["buy", MTI.cart, "Закупки"], ["analogs", MTI.link, "Аналоги"], ["docs", EQI.doc, "Документы"], ["history", EQI.hist, "История"]];
  if (!tabs.some(t => t[0] === MT.tab)) MT.tab = "main";
  const acts = off ? [] : [
    c.edit ? ["order", MTI.plus, "Сформировать закупку"] : c.ops && ["req", MTI.cart, "Добавить в заявку"],
    c.edit ? ["in", MTI.inbox, "Поступление на склад"] : c.ops && ["receive", MTI.inbox, "Принять поставку"],
    c.edit ? ["out", MTI.out, "Списание (расход)"] : c.ops && ["use", MTI.out, c.direct ? "Зафиксировать расход" : "Расход — на согласование"],
    c.edit && hasPlaces() ? ["move", EQI.move, "Перемещение"] : c.ops && hasPlaces() && ["issue", EQI.move, "Выдать в кабинет"],
    c.edit && ["inv", EQI.check, "Провести инвентаризацию"],
    c.edit && ["min", MTI.bell, "Установить минимальный остаток"],
    !c.edit && c.photo && ["photo", EQI.camera, m.photo_id ? "Заменить фотографию" : "Добавить фотографию"]].filter(Boolean);
  const photos = m.photos || [];
  if (MT.gal >= photos.length) MT.gal = 0;
  const back = S.stockTab === "home" ? "Склад и материалы" : "Остатки";
  const cover = m.cover_days != null ? mtDays(m.cover_days) : m.free > 0 ? "расхода не было" : "нет запаса";
  const coverTip = `Свободный остаток ${qtyFmt(m.free, "")} (текущий без просроченного и резерва под заявки кабинетов) / средний расход в день за 60 дней. Полная полоса — ${m.opt_qty ? "оптимальный остаток" : "два минимальных остатка"}${m.cover_full ? ` (${qtyFmt(m.cover_full, "")} ${u || "шт"})` : ""}.`;
  const used = (m.norms || []).map(n => n.title);
  body.innerHTML = `<div class="eqc mtc">
    <div class="eqc-crumbs"><button class="eqc-back" id="mtBack" title="К списку материалов">${EQI.back}</button><button class="linkbtn" id="mtBack2">${back}</button>${EQI.chev}<b>Карточка материала</b></div>
    <div class="eqc-head"><h2>Карточка материала</h2>${m.number ? `<span class="eqc-chip">${esc(m.number)}</span>` : ""}<span class="grow"></span>
      <button class="btn ghost eqc-hb" id="mtLabel">${MTI.bar}Печать штрихкода</button>
      ${c.edit && !off ? `<button class="btn ghost eqc-hb" id="mtEdit">${EQI.pen}Редактировать</button>` : ""}
      <button class="icon-btn eqc-more" id="mtMore" title="Ещё">${EQI.more}</button></div>
    ${off ? `<div class="warn-line">Материал убран из справочника. История поставок и движения сохранилась; карточка только для просмотра.</div>` : ""}
    <div class="eqc-grid"><div class="eqc-main">
      <section class="eqc-card eqc-top mtc-top">
        <div class="eqc-gal"><div class="eqc-photo ${photos.length ? "" : "def"}" id="mtPhoto" ${photos.length ? `data-big="${esc(photos[MT.gal])}"` : ""}>${photos.length ? EQI.ph : `<img class="eqp-defpic" src="${matPic(m.name, m.category)}" alt="" title="Картинка по категории — добавьте своё фото">`}${photos.length ? `<button class="eqc-exp" id="mtExp" title="Открыть фото">${EQI.expand}</button>` : ""}</div>
          <div class="eqc-dots">${photos.length > 1 ? photos.map((p, i) => `<button data-gal="${i}" class="${i === MT.gal ? "on" : ""}" title="Фото ${i + 1}"></button>`).join("")
            : c.photo && !off && !photos.length ? `<button class="linkbtn" id="mtPh">${EQI.camera}Добавить фото</button>` : ""}</div></div>
        <div class="eqc-id"><span class="eqc-badge ${stCls}">${stCls === "ok" ? EQI.okc : EQI.warn}${esc(stText)}</span>${m.exp_state === "expired" && stText !== "Просрочено" ? `<span class="eqc-badge bad">${EQI.cal}Есть просроченное</span>` : m.exp_state === "soon" ? `<span class="eqc-badge warn">${EQI.cal}Истекает срок</span>` : ""}
          <h3>${esc(m.name)}</h3>${m.description ? `<div class="eqc-inv">${esc(m.description)}</div>` : ""}
          <ul><li>${EQI.layers}<span>Производитель: ${m.manufacturer ? esc(m.manufacturer) : `<span class="muted">не указан</span>`}</span></li>
            <li>${MTI.box}<span>Артикул: ${m.code ? esc(m.code) : `<span class="muted">не указан</span>`}</span></li>
            <li>${MTI.tag}<span>Категория: ${m.category ? esc(m.category) : `<span class="muted">не указана</span>`}</span></li></ul></div>
        <div class="eqc-money"><div class="eqc-tiles">${tile(MTI.stack, "Текущий остаток", mtQty(m.balance, u), m.balance_doc !== undefined && Math.abs(m.balance - m.balance_doc) > 1e-9 ? `по документам: ${mtQty(m.balance_doc, u)}` : m.expired_qty ? `просрочено ${mtQty(m.expired_qty, u)}` : "")}
            ${tile(MTI.reserve, "Резервный остаток", mtQty(m.reserve, u), m.reserve ? "под заявки кабинетов" : "")}
            ${tile(MTI.cart, "В пути (заказано)", mtQty(m.in_transit, u), m.orders.length ? `${m.orders.length} ${plural(m.orders.length, "заказ", "заказа", "заказов")}` : "")}
            ${tile(MTI.cycle, "Средний расход", `${mtQty(m.monthly, u)}/мес.`)}</div>
          <div class="eqc-amort mtc-cover"><div><span>Обеспеченность запасом</span><b>${cover}<button class="mtc-tip" title="${esc(coverTip)}" tabindex="-1">${EQI.info}</button></b></div>
            <i><u class="${stCls !== "ok" ? "low" : ""}" style="width:${m.cover_pct}%"></u></i></div></div>
      </section>
      <div class="eqc-tabs" id="mtTabs" role="tablist">${tabs.map(([k, ic, t]) => `<button data-t="${k}" class="${k === MT.tab ? "on" : ""}">${ic}${t}</button>`).join("")}</div>
      <section class="eqc-card eqc-pane" id="mtPane"></section>
      <button class="eqc-access mtc-used" id="mtUsed">${EQI.info}<span>${used.length ? `Используется в услугах: ${esc(used.join(", "))}` : "Не привязан к услугам — нормы списания задаются в «Нормы списания»"}</span>${EQI.chev}</button>
    </div>
    <aside class="eqc-side">
      ${acts.length ? `<section class="eqc-card"><h3>Быстрые действия</h3><div class="eqc-acts">${acts.map(([k, ic, t]) => `<button data-act="${k}">${ic}<span>${t}</span>${EQI.chev}</button>`).join("")}</div></section>` : ""}
      <section class="eqc-card mtc-an"><h3>Учёт и аналитика</h3>
        <div title="Цена, по которой материал списывается со склада (последняя закупка)"><i>${MTI.rub}</i><span><small>Себестоимость за единицу</small><b>${money(m.unit_cost)}</b></span></div>
        <div title="${m.avg_price_qty ? `Средневзвешенная по приходам за 12 месяцев: ${esc(qtyFmt(m.avg_price_qty, u))}` : "Приходов с ценой за 12 месяцев не было — цена из справочника"}"><i>${MTI.tag}</i><span><small>Средняя цена закупки</small><b>${money(m.avg_price)}</b></span></div>
        <div title="Услуги и списания за последние 30 дней"><i>${EQI.chart}</i><span><small>Расход за месяц</small><b>${mtQty(m.used30, u)}</b></span></div>
        <div><i>${EQI.cal}</i><span><small>Остаток на</small><b>${m.cover_days != null ? mtDays(m.cover_days) : "—"}</b></span></div></section>
    </aside></div></div>`;
  const on = (s, f) => { const el = $(s, body); if (el) el.onclick = f; };
  on("#mtBack", mtClose); on("#mtBack2", mtClose);
  on("#mtEdit", () => editMaterial(m, {onSaved: () => mtCard()}));
  on("#mtLabel", () => mtPrintLabel(m));
  on("#mtMore", ev => mtMoreMenu(ev.currentTarget, m));
  on("#mtPh", () => mtUpload("photo"));
  on("#mtUsed", () => { if (c.edit || can("refs")) { S.matOpen = null; stockGo("stock", "norms"); } else mtTab("use"); });
  $$("[data-gal]", body).forEach(b => b.onclick = () => { MT.gal = +b.dataset.gal; mtCard(); });
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
  const m = MT.data, c = m.can || {}, u = m.unit, edit = c.edit && m.active;
  const kv = rows => `<table class="eqc-kv">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
  const nz = (v, t = "Не указан") => v ? esc(v) : `<span class="muted">${t}</span>`;
  if (MT.tab === "main") {
    el.innerHTML = `<div class="mtc-main"><div><h3>Общие сведения</h3>${kv([["Наименование", esc(m.name)], ["Производитель", nz(m.manufacturer)], ["Артикул (код поставщика)", nz(m.code)],
        ["Категория", nz(m.category, "Не указана")], ["Единица измерения", esc(u || "шт")], ["Форма выпуска", nz(m.form, "Не указана")],
        ["Срок годности (общий)", nz(m.shelf_life)], ["Условия хранения", nz(m.storage, "Не указаны")], ...(m.comment ? [["Комментарий", esc(m.comment)]] : [])])}</div>
      <div class="eqc-label mtc-label"><h4>Штрихкод / QR-код</h4>
        <div class="mtc-codes"><div class="mtc-ean" id="mtEan">${m.ean_svg || `<span class="muted">${esc(m.barcode || "")}</span>`}</div><div class="eqc-qr" id="mtQr"><span class="muted">QR…</span></div></div>
        <div class="mtc-lbl-foot"><span class="eqc-chip">${esc(m.number || "—")}</span><span class="grow"></span><button class="btn ghost small mtc-dl" id="mtCodes">${EQI.down}Скачать / Печать</button></div>
        <small class="muted">${m.ean_internal ? "Своего штрихкода у материала нет — показан внутренний. Он запишется в карточку при печати наклейки." : m.barcode && !m.ean ? "Штрихкод не EAN-13 — сканер найдёт материал по QR или номеру." : "Сканер найдёт материал по штрихкоду, по QR и по номеру."}</small></div></div>
      <div class="eqc-sels mtc-quick">
        <label class="eqc-sel"><span>${MTI.bell}Минимальный остаток</span><input class="input num" type="number" min="0" step="any" id="mtMin" data-f="min_qty" value="${m.min_qty || ""}" placeholder="0" ${edit ? "" : "disabled"}><small class="muted">${esc(u || "шт")}</small></label>
        <label class="eqc-sel"><span>${MTI.target}Оптимальный остаток</span><input class="input num" type="number" min="0" step="any" data-f="opt_qty" value="${m.opt_qty || ""}" placeholder="0" ${edit ? "" : "disabled"}><small class="muted">${esc(u || "шт")}</small></label>
        <label class="eqc-sel"><span>${MTI.clock}Срок поставки</span><input class="input num" type="number" min="0" max="365" step="1" data-f="lead_days" value="${m.lead_days || ""}" placeholder="0" ${edit ? "" : "disabled"}><small class="muted">${m.lead_days ? plural(m.lead_days, "день", "дня", "дней") : "дней"}</small></label>
        <label class="eqc-sel"><span>${MTI.truck}Основной поставщик</span><select class="input" data-f="supplier_id" id="mtSup" ${edit ? "" : "disabled"}><option value="">— не выбран —</option>${m.supplier ? `<option value="${esc(m.supplier.id)}" selected>${esc(m.supplier.name)}</option>` : ""}</select></label></div>`;
    mtLoadQr();
    on2(el, "#mtCodes", ev => mtCodesMenu(ev.currentTarget, m));
    if (edit) {
      api.suppliers().then(list => { const s = $("#mtSup", el); if (!s) return; s.innerHTML = `<option value="">— не выбран —</option>` + list.map(x => `<option value="${esc(x.id)}" ${x.id === m.supplier_id ? "selected" : ""}>${esc(x.name)}</option>`).join(""); }).catch(() => {});
      $$("[data-f]", el).forEach(i => i.onchange = async () => {
        try { const v = await api.material_set(m.id, i.dataset.f, i.value); m[i.dataset.f] = v; i.classList.add("saved"); setTimeout(() => i.classList.remove("saved"), 1200); toast("Сохранено");
          if (i.dataset.f !== "lead_days") mtCard(); } catch (x) { toast(errText(x), true); }
      });
    }
    return;
  }
  if (MT.tab === "lots") {
    const locs = (m.by_location || []).filter(x => Math.abs(x.qty) > 1e-9), max = Math.max(1e-9, ...locs.map(x => Math.abs(x.qty)));
    el.innerHTML = `<div class="eqc-stats"><div><span>Текущий остаток</span><b>${mtQty(m.balance, u)}</b></div><div><span>Резерв под заявки</span><b>${mtQty(m.reserve, u)}</b></div>
        <div><span>Свободно</span><b>${mtQty(m.free, u)}</b></div><div><span>Сумма остатка</span><b>${money(m.value)}</b></div></div>
      <div class="eqc-two"><div><h3>Остаток по местам</h3>${locs.length ? `<div class="mtc-locs">${locs.map(x => `<div class="mtc-loc ${x.qty < 0 ? "neg" : ""}"><span>${EQI.pin}${esc(x.name)}</span><b>${mtQty(x.qty, u)}</b><i><u style="width:${Math.max(3, Math.abs(x.qty) / max * 100)}%"></u></i></div>`).join("")}</div>`
        : `<div class="muted">${m.balance ? "Весь остаток на основном складе" : "Остатка нет"}</div>`}</div>
      <div><h3>Партии и сроки годности</h3>${lotsTable(m.lot_list, u, edit)}</div></div>`;
    $$("[data-lot-out]", el).forEach(b => b.onclick = () => { const g = m.lot_list.lots.find(x => String(x.id) === b.dataset.lotOut);
      openStockDoc("writeoff", [{material_id: m.id, qty: g.left, lot_id: g.id, lot: g.lot, expires: g.expires}], {reason: g.state === "expired" ? "Истёк срок годности" : ""}); });
    return;
  }
  if (MT.tab === "use") {
    const ms = m.use_months || [], top = Math.max(1e-9, ...ms.map(x => x.service + x.treatment + x.writeoff)), t = m.use_total || {};
    const mon = k => ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"][+k.slice(5, 7) - 1];
    el.innerHTML = `<div class="eqc-stats"><div><span>По услугам</span><b>${mtQty(t.service, u)}</b></div><div><span>Расход в лечении</span><b>${mtQty(t.treatment, u)}</b></div>
        <div><span>Списания</span><b>${mtQty(t.writeoff, u)}</b></div><div><span>В среднем за месяц</span><b>${mtQty(m.monthly, u)}</b></div></div>
      <h3>Расход по месяцам за год</h3>
      <div class="mtc-bars">${ms.map(x => { const s = x.service + x.treatment + x.writeoff;
        return `<div class="mtc-bar" title="${esc(eqMonth(x.month))}: ${esc(qtyFmt(s, u))}${s ? ` — услуги ${qtyFmt(x.service)}, в лечении ${qtyFmt(x.treatment)}, списания ${qtyFmt(x.writeoff)}; ${money(x.sum)}` : ""}">
          <i>${["service", "treatment", "writeoff"].map(k => x[k] ? `<u class="${k}" style="height:${x[k] / top * 100}%"></u>` : "").join("")}</i><b>${s ? qtyFmt(s) : ""}</b><small>${mon(x.month)}</small></div>`; }).join("")}</div>
      <div class="mtc-legend"><span class="service">По услугам</span><span class="treatment">Расход в лечении</span><span class="writeoff">Списания</span></div>
      <h3>Нормы списания по услугам</h3>${m.norms.length ? `<table class="tbl compact mtc-t"><thead><tr><th>Услуга</th><th>Код</th><th class="num">На одну услугу</th></tr></thead><tbody>${m.norms.map(n => `<tr><td class="wrap">${esc(n.title)}</td><td class="muted">${esc(n.code || "")}</td><td class="num"><b>${mtQty(n.qty, u)}</b></td></tr>`).join("")}</tbody></table>`
        : `<div class="muted">Не привязан к услугам.</div>`}${c.edit ? `<div class="muted eqc-hint">Нормы задаются во вкладке «Нормы списания» <button class="linkbtn" id="mtNorms">открыть</button></div>` : ""}`;
    on2(el, "#mtNorms", () => { S.matOpen = null; stockGo("stock", "norms"); });
    return;
  }
  if (MT.tab === "buy") {
    const sups = m.supplier_stats || [], rows = m.supplies || [], ords = m.orders || [];
    el.innerHTML = `<h3>Заказы поставщикам <span class="muted">${ords.length ? `в пути ${mtQty(m.in_transit, u)}` : ""}</span>${edit ? `<button class="btn small mtc-h3btn" id="mtOrder">${MTI.plus}Сформировать закупку</button>` : ""}</h3>
      ${ords.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Заказ</th><th>Поставщик</th><th>Дата</th><th>Ожидается</th><th class="num">Заказано</th><th class="num">Получено</th><th>Статус</th><th></th></tr></thead><tbody>${ords.map(o => {
          const ln = o.lines.find(x => x.material_id === m.id) || {};
          return `<tr><td><b>${esc(o.number)}</b></td><td class="wrap">${o.supplier_name ? esc(o.supplier_name) : `<span class="muted">не выбран</span>`}</td><td>${fmtDateShort(o.date)}</td>
            <td class="${o.late ? "bad-t" : ""}">${o.expected ? fmtDateShort(o.expected) : "—"}${o.late ? " · опаздывает" : ""}</td><td class="num">${mtQty(ln.qty, u)}</td><td class="num">${mtQty(ln.received, u)}</td>
            <td><span class="pill ${o.status === "partial" ? "st-done" : "st-come"}">${esc(o.status_title)}</span></td>
            <td class="mtc-oacts">${edit ? `<button class="linkbtn" data-o-in="${esc(o.id)}">принять</button><button class="linkbtn danger-t" data-o-x="${esc(o.id)}">отменить</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<div class="muted">Открытых заказов нет.${edit ? " «Сформировать закупку» запишет заказ — заказанное покажется «в пути» и не попадёт в «Заказ поставщикам» второй раз." : ""}</div>`}
      <h3>Поставщики этого материала</h3>
      ${sups.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Поставщик</th><th class="num">Поставок</th><th class="num">Всего</th><th>Последняя</th><th class="num">Посл. цена</th><th class="num">Мин. цена</th><th class="num">Средняя</th><th></th></tr></thead><tbody>${sups.map(g => `<tr class="${g.best ? "mtc-best-row" : ""}">
          <td class="wrap"><b>${esc(g.supplier_name)}</b>${g.supplier_id === m.supplier_id ? ` <span class="pill st-come">основной</span>` : ""}</td><td class="num">${g.count}</td><td class="num">${mtQty(g.qty, u)}</td><td>${fmtDateShort(g.last_date)}</td><td class="num"><b>${money(g.last_price)}</b></td>
          <td class="num">${g.min_price != null ? money(g.min_price) : "—"}</td><td class="num muted">${money(g.avg_price)}</td><td>${g.best ? `<span class="pill st-ok">лучшая цена</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="muted eqc-hint">«Лучшая цена» — у кого последняя закупка дешевле всего. «Заказ поставщикам» берёт основного поставщика, если он выбран, иначе — с лучшей ценой.</div>`
        : `<div class="muted">Поставщиков пока нет. Он запишется сам при приходе по накладной — укажите поставщика в документе.</div>`}
      <h3>История поставок <span class="muted">${m.supply_count || 0}</span></h3>
      ${rows.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Дата</th><th>Поставщик</th><th class="num">Количество</th><th class="num">Цена</th><th class="num">Сумма</th><th>Накладная · партия</th></tr></thead><tbody>${rows.map(r => {
          const lot = [r.lot ? "партия " + r.lot : "", r.expires ? "годен до " + fmtDateShort(r.expires) : ""].filter(Boolean).join(", ");
          const tip = [r.user_name ? "Принял: " + r.user_name : "", hasPlaces() ? "Куда: " + r.location_name : ""].filter(Boolean).join(" · ");
          return `<tr title="${esc(tip)}"><td>${fmtDateShort(r.day)}</td><td class="wrap">${r.supplier_name ? `<b>${esc(r.supplier_name)}</b>` : `<span class="muted">не указан</span>`}</td>
          <td class="num">${mtQty(r.qty, u)}</td><td class="num">${money(r.price)}</td><td class="num">${money(r.sum)}</td>
          <td class="wrap">${r.doc_id ? `<button class="linkbtn" data-doc="${esc(r.doc_id)}">${r.doc_number ? "№ " + esc(r.doc_number) : "без номера"}</button>` : `<span class="muted">—</span>`}${r.nodoc ? ' <span class="pill dx-nodoc">без документа</span>' : ""}${lot ? `<small class="mtc-lot">${esc(lot)}</small>` : ""}</td></tr>`; }).join("")}</tbody></table></div>
        ${m.supply_count > rows.length ? `<div class="muted eqc-hint">Показаны последние ${rows.length} из ${m.supply_count}</div>` : ""}`
        : `<div class="muted">Приходов ещё не было${edit ? " — «Поступление на склад» справа" : ""}.</div>`}`;
    $$("[data-doc]", el).forEach(b => b.onclick = () => openStockDocView(b.dataset.doc));
    on2(el, "#mtOrder", () => mtOrder(m));
    $$("[data-o-in]", el).forEach(b => b.onclick = () => receiveByOrder(ords.find(o => o.id === b.dataset.oIn)));
    $$("[data-o-x]", el).forEach(b => b.onclick = () => cancelOrder(ords.find(o => o.id === b.dataset.oX), () => mtCard()));
    return;
  }
  if (MT.tab === "analogs") {
    const al = m.analogs || [];
    el.innerHTML = `<h3>Аналоги <span class="muted">взаимозаменяемые материалы</span></h3>
      ${al.length ? `<div class="mtc-scroll"><table class="tbl compact mtc-t"><thead><tr><th>Материал</th><th>Номер</th><th class="num">Остаток</th><th class="num">Цена</th><th></th></tr></thead><tbody>${al.map(x => `<tr>
          <td class="wrap"><div class="sn-mat sm">${phHtml(x.photo_id, "", matPic(x.name, x.category))}<span><button class="linkbtn" data-open-m="${esc(x.id)}"><b>${esc(x.name)}</b></button>${x.active ? "" : ' <span class="muted">убран</span>'}</span></div></td>
          <td class="muted">${esc(x.number || x.code || "")}</td><td class="num ${x.balance > 0 ? "" : "bad-t"}"><b>${mtQty(x.balance, x.unit)}</b></td><td class="num">${money(x.price)}</td>
          <td>${edit ? `<button class="linkbtn danger-t" data-al-x="${esc(x.id)}">убрать</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="muted">Аналогов нет. Когда этот материал закончится, аналог с остатком подскажет, чем его заменить.</div>`}
      ${edit ? `<div class="eqc-form mtc-al-add"><input class="input grow" id="mtAlQ" list="mtAlList" placeholder="Найти материал: название, номер, артикул" autocomplete="off"><datalist id="mtAlList"></datalist><button class="btn" id="mtAlAdd">${MTI.plus}Добавить аналог</button></div>` : ""}`;
    loadThumbs(el);
    $$("[data-open-m]", el).forEach(b => b.onclick = () => openMaterial(b.dataset.openM));
    $$("[data-al-x]", el).forEach(b => b.onclick = async () => { try { await api.material_analog_delete(m.id, b.dataset.alX); toast("Убрано"); mtCard(); } catch (x) { toast(errText(x), true); } });
    if (edit) {
      let mats = [];
      api.materials("").then(list => { mats = list.filter(x => x.id !== m.id && !al.some(a => a.id === x.id));
        $("#mtAlList", el).innerHTML = mats.map(x => `<option value="${esc(`${x.name}${x.number ? " · " + x.number : ""}`)}">`).join(""); }).catch(() => {});
      on2(el, "#mtAlAdd", async () => {
        const q = $("#mtAlQ", el).value.trim(), x = mats.find(y => `${y.name}${y.number ? " · " + y.number : ""}` === q) || mats.find(y => y.name.toLowerCase() === q.toLowerCase());
        if (!x) return toast("Выберите материал из списка", true);
        try { await api.material_analog_add(m.id, x.id); toast("Аналог добавлен"); mtCard(); } catch (e) { toast(errText(e), true); }
      });
    }
    return;
  }
  if (MT.tab === "docs") {
    const by = {}; m.docs.forEach(d => (by[d.kind] ||= []).push(d));
    el.innerHTML = `<h3>Документы <span class="muted">${m.docs.length}</span></h3><div class="muted eqc-hint">PDF или фото документа. Файлы хранятся в программе и расходятся по компьютерам клиники вместе с карточкой. Фото попадают в галерею.</div>
      <div class="eqc-dk">${m.doc_kinds.map(k => { const list = by[k.kind] || [];
        const extra = k.kind === "photo" && m.photo_id && !list.some(d => d.file_id === m.photo_id) ? `<div class="eqc-file"><button class="linkbtn" data-ph-open="${esc(m.photo_id)}">${EQI.ph}Главное фото</button></div>` : "";
        const up = k.kind === "photo" ? c.photo && m.active : edit;
        return `<div class="eqc-dkrow ${MT.docKind === k.kind ? "hl" : ""}"><div class="eqc-dkh">${k.kind === "photo" ? EQI.camera : EQI.doc}<b>${esc(k.title)}</b><span class="grow"></span>${up ? `<button class="btn ghost small" data-up="${k.kind}">${EQI.up}Загрузить</button>` : ""}</div>
          ${list.map(d => `<div class="eqc-file"><button class="linkbtn" data-open="${esc(d.id)}">${d.image ? EQI.ph : EQI.doc}${esc(d.title)}</button><small class="muted">${fmtDT(d.created_at)} · ${esc(d.created_by || "")}${d.size ? ` · ${Math.max(1, Math.round(d.size / 1024))} КБ` : ""}</small>${edit ? `<button class="linkbtn danger-t" data-del="${esc(d.id)}">убрать</button>` : ""}</div>`).join("")}${extra}
          ${!list.length && !extra ? `<div class="muted eqc-none">Не загружен</div>` : ""}</div>`; }).join("")}</div>`;
    $$("[data-up]", el).forEach(b => b.onclick = () => mtUpload(b.dataset.up));
    $$("[data-open]", el).forEach(b => b.onclick = async () => { try { eqOpenFile(await api.material_doc_open(b.dataset.open)); } catch (x) { toast(errText(x), true); } });
    $$("[data-ph-open]", el).forEach(b => b.onclick = async () => { try { const f = await api.stock_photo(b.dataset.phOpen); eqViewer(f.url, m.name); } catch (x) { toast(errText(x), true); } });
    $$("[data-del]", el).forEach(b => b.onclick = async () => { if (!await ask("Убрать документ из карточки?", {danger: true, ok: "Убрать"})) return;
      try { await api.material_doc_delete(b.dataset.del); toast("Убрано"); mtCard(); } catch (x) { toast(errText(x), true); } });
    const hl = $(".eqc-dkrow.hl", el); if (hl) { hl.scrollIntoView({block: "center"}); MT.docKind = null; }
    return;
  }
  el.innerHTML = `<h3>История <span class="muted">все движения</span></h3>${movesTable(m.moves, false)}`;
}
const on2 = (root, s, f) => { const el = $(s, root); if (el) el.onclick = f; };

/* ------------------------------------------------------------ the label: barcode and QR */
async function mtLoadQr() {
  const box = $("#mtQr"); if (!box || !MT.data) return;
  try { const q = await api.material_qr(MT.data.id); MT.qr = q; box.innerHTML = q.png ? `<img src="${q.png}" alt="QR ${esc(q.number)}">` : `<span class="muted">QR недоступен</span>`; }
  catch (e) { box.innerHTML = `<span class="muted">QR недоступен</span>`; }
}
/** The sticker 40 × 30 mm: the QR and the number with the name on top, the barcode under them. */
async function mtPrintLabel(m) {
  let q;
  try { q = (m.can || {}).ops && m.active ? await api.material_label(m.id) : await api.material_qr(m.id); } catch (x) { return toast(errText(x), true); }
  $("#printArea").innerHTML = `<div class="eq-sticker mt-sticker"><div class="mt-st-top"><img src="${q.png}" alt=""><div><b>${esc(q.number || "")}</b><span>${esc(q.name)}</span></div></div>${q.ean_svg ? `<div class="mt-st-ean">${q.ean_svg}</div>` : ""}</div>`;
  window.print();
  if (m.ean_internal && !q.ean_internal && S.matOpen === m.id) mtCard();  // the internal barcode is written down now
}
function mtCodesMenu(btn, m) {
  const old = $(".eqc-menu"); if (old) { old.remove(); return; }
  const menu = document.createElement("div"); menu.className = "eqc-menu mtc-codes-menu";
  menu.innerHTML = `<button data-k="label">Печать наклейки 40 × 30 мм</button><button data-k="qr">Скачать QR-код (PNG)</button>${m.ean ? `<button data-k="ean">Скачать штрихкод (SVG)</button>` : ""}`;
  btn.parentElement.appendChild(menu); popOpen(menu, btn, {align: "end"});
  const close = () => { menu.remove(); document.removeEventListener("click", out, true); };
  const out = ev => { if (!menu.contains(ev.target) && !btn.contains(ev.target)) close(); };
  setTimeout(() => document.addEventListener("click", out, true));
  $$("[data-k]", menu).forEach(b => b.onclick = () => { close(); mtCodeDownload(m, b.dataset.k); });
}
async function mtCodeDownload(m, k) {
  const name = String(m.number || m.name).replace(/[\\/:*?"<>|]/g, "-");
  if (k === "label") return mtPrintLabel(m);
  if (k === "qr") { const q = MT.qr && MT.qr.number === m.number ? MT.qr : await api.material_qr(m.id); return saveDataUrl(`QR ${name}.png`, q.png); }
  const svg = m.ean_svg || (await api.material_qr(m.id)).ean_svg;
  return saveDataUrl(`Штрихкод ${name}.svg`, "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg))));
}

/* ------------------------------------------------------------ actions */
function mtUpload(kind) {
  const m = MT.data; if (!m) return;
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = kind === "photo" ? "image/*" : "application/pdf,image/*"; inp.multiple = kind === "photo";
  inp.onchange = async () => {
    const files = [...(inp.files || [])]; if (!files.length) return;
    const read = f => new Promise((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = bad; rd.readAsDataURL(f); });
    for (const f of files) {
      if (f.size > 15 * 1024 * 1024) { toast(`${f.name}: больше 15 МБ`, true); continue; }
      let data; try { data = f.type.startsWith("image/") ? await shrinkImage(f, 1600) : await read(f); } catch (x) { data = await read(f); }
      try { await api.material_doc_add(m.id, kind, f.name, data, kind === "photo" ? "" : (m.doc_kinds.find(x => x.kind === kind) || {}).title || ""); } catch (x) { toast(errText(x), true); return; }
    }
    toast(files.length > 1 ? `Загружено: ${files.length}` : "Загружено"); if (kind !== "photo") MT.docKind = kind; mtCard();
  };
  inp.click();
}

function mtAction(k) {
  const m = MT.data; if (!m) return;
  const leave = () => { S.matOpen = null; };  // the nurse's screens take the place of the card and come back to «Склад»
  if (k === "order") return mtOrder(m);
  if (k === "in") return openStockDoc("receipt", [{material_id: m.id, qty: "", price: (m.last_supply || {}).price || m.price}], {supplier_id: m.supplier_id || (m.last_supply || {}).supplier_id});
  if (k === "out") return openStockDoc("writeoff", [{material_id: m.id, qty: ""}]);
  if (k === "move") return openTransfer({lines: [{material_id: m.id, qty: ""}]});
  if (k === "inv") return openInventory(undefined, [m.id]);
  if (k === "min") { if (MT.tab !== "main") mtTab("main"); const i = $("#mtMin"); if (i) { i.focus(); i.select(); i.closest(".eqc-sel").classList.add("hl"); setTimeout(() => i.closest(".eqc-sel") && i.closest(".eqc-sel").classList.remove("hl"), 1600); } return; }
  if (k === "receive") { leave(); return openReceiveScreen(); }
  if (k === "use") { leave(); return openUseScreen({lines: {[m.id]: 1}}); }
  if (k === "issue") { leave(); return openIssueScreen({lines: {[m.id]: 1}}); }
  if (k === "req") { leave(); return openRequestScreen({lines: {[m.id]: 1}}); }
  if (k === "photo") return photoPick("material", m.id, () => mtCard());
}

/** «Сформировать закупку» of one material: the order goes to the supplier and the quantity is «в пути» until it comes. */
async function mtOrder(m) {
  const sups = await api.suppliers();
  const offer = sid => ((m.supplier_stats || []).find(g => g.supplier_id === sid) || {}).last_price;
  const sid0 = m.supplier_id || (m.best_offer || {}).supplier_id || (m.last_supply || {}).supplier_id || "";
  const target = m.opt_qty || (m.min_qty ? m.min_qty * 2 : 0);
  const want = Math.max(1, Math.ceil(target - m.free - m.in_transit));
  const exp = d => { const x = new Date(); x.setDate(x.getDate() + (+d || 0)); return iso(x); };
  const box = modal(`<div class="m-h"><h3>Сформировать закупку</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="mtc-ord-m"><b>${esc(m.name)}</b><small class="muted">${esc([m.number, m.code && "арт. " + m.code].filter(Boolean).join(" · "))} · свободно ${qtyFmt(m.free, m.unit)}${m.in_transit ? `, в пути ${qtyFmt(m.in_transit, m.unit)}` : ""}${target ? `, ${m.opt_qty ? "оптимум" : "два минимума"} ${qtyFmt(target, m.unit)}` : ""}</small></div>
      <div class="grid2"><label class="fl">Поставщик<select class="input" id="oSup"><option value="">— не выбран —</option>${sups.map(s => `<option value="${esc(s.id)}" ${s.id === sid0 ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
        <label class="fl">Ожидается<input class="input" type="date" id="oExp" value="${m.lead_days ? exp(m.lead_days) : ""}"></label></div>
      <div class="grid3"><label class="fl">Количество, ${esc(m.unit || "шт")}<input class="input num" type="number" min="0" step="any" id="oQty" value="${want}"></label>
        <label class="fl">Цена, ₽<input class="input num" type="number" min="0" step="any" id="oPrice" value="${offer(sid0) || m.price || ""}"></label>
        <label class="fl">Сумма<input class="input num" id="oSum" disabled></label></div>
      <label class="fl">Комментарий<input class="input" id="oCom" placeholder="например: заказано по телефону, менеджер Анна"></label><div class="auth-err" id="oErr"></div></div>
    <div class="m-f"><span class="muted">Заказанное покажется «в пути» до прихода по этому заказу</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="oOk">Записать заказ</button></div>`);
  const sum = () => { $("#oSum", box).value = money((+$("#oQty", box).value || 0) * (+$("#oPrice", box).value || 0)); };
  $("#oQty", box).oninput = sum; $("#oPrice", box).oninput = sum; sum();
  $("#oSup", box).onchange = e => { const p = offer(e.target.value); if (p) { $("#oPrice", box).value = p; sum(); } };
  $("#oOk", box).onclick = async () => {
    try { await api.stock_order_save({supplier_id: $("#oSup", box).value, expected: $("#oExp", box).value, comment: $("#oCom", box).value,
      lines: [{material_id: m.id, qty: $("#oQty", box).value, price: $("#oPrice", box).value}]});
      closeModal(); toast("Заказ записан"); MT.tab = "buy"; mtCard(); } catch (x) { $("#oErr", box).textContent = errText(x); }
  };
}

function mtMoreMenu(btn, m) {
  const c = m.can || {};
  const items = [c.edit && m.active && ["edit", "Редактировать"], ["label", "Печать наклейки 40 × 30 мм"], ["qr", "Скачать QR-код"], m.ean && ["ean", "Скачать штрихкод"],
    c.edit && m.active && ["purchase", "Заказ поставщикам (все материалы)"], c.edit && m.active && ["del", "Убрать из справочника"]].filter(Boolean);
  const old = $(".eqc-menu"); if (old) { old.remove(); return; }
  const menu = document.createElement("div"); menu.className = "eqc-menu";
  menu.innerHTML = items.map(([k, t]) => `<button data-m="${k}" class="${k === "del" ? "danger-t" : ""}">${t}</button>`).join("");
  btn.parentElement.appendChild(menu); popOpen(menu, btn, {align: "end"});
  const close = () => { menu.remove(); document.removeEventListener("click", out, true); };
  const out = ev => { if (!menu.contains(ev.target) && !btn.contains(ev.target)) close(); };
  setTimeout(() => document.addEventListener("click", out, true));
  $$("[data-m]", menu).forEach(b => b.onclick = async () => { close();
    const k = b.dataset.m;
    if (k === "edit") return editMaterial(m, {onSaved: () => mtCard()});
    if (k === "purchase") return openPurchase();
    if (k === "del") {
      if (!(await ask(`Убрать «${m.name}» из справочника?`, {danger: true, ok: "Убрать", text: "История поставок и движения сохранится, нормы списания по услугам удалятся."}))) return;
      try { await api.delete_material(m.id); toast("Убрано из справочника"); mtClose(); } catch (x) { toast(errText(x), true); }
      return;
    }
    mtCodeDownload(m, k);
  });
}
