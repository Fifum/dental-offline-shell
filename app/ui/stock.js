"use strict";
/* Stock: materials (balances, supplier invoices, write-offs, stock count, norms per service) and equipment.
   3.14: three sections of the menu on one screen (#view-stock, #stockBody): «Склад и материалы», «Оборудование» and
   «Инвентаризация». The section is S.view, its open tab S.stockTab (each section remembers its own in S.stockTabs). */
S.stockTab = "home";  // 3.10: the home screen with the four tiles (stock-nurse.js)
S.stockArea = null;
S.stockTabs = {stock: "home", equipment: "eq_overview", inventory: "inv_mat"};
const STOCK_AREAS = {
  stock: {title: "Склад и материалы", sub: "Поставки, выдача в кабинеты, расход, заявки и закупки — медицинские и хозяйственные материалы",
    tabs: [["home", "Главная"], ["balance", "Остатки"], ["docs", "Документы"], ["moves", "Движение"],
      ["visits", 'По приёмам<i class="cnt" id="stVisitsCnt" hidden></i>', "Списание материалов по приёмам Dentist Plus"],
      ["places", "Места хранения", "Кабинеты, филиалы и перемещения"], ["orders", "Закупки", "Заказы поставщикам и что в пути"],
      ["norms", "Нормы списания"], ["suppliers", "Поставщики"]]},
  // 3.15: the bar of the mockups — the main tabs with icons and «Ещё» (stock-eqsection.js draws it)
  equipment: {title: "Оборудование", sub: "Учёт, обслуживание и управление имуществом клиники",
    tabs: [["eq_overview", "Обзор"], ["equipment", "Реестр оборудования"], ["service", "Обслуживание и ремонт"],
      ["amort", "Амортизация", "Видят директор и учредитель (право «Бухгалтерия»)"]],
    more: [["disposed", "Выбытие и списание"], ["inv", "Инвентаризация"], ["steril", "Стерилизация"], ["eq_refs", "Справочники и настройки"]]},
  inventory: {title: "Инвентаризация", sub: "Пересчёт материалов по местам и проверка оборудования по инвентарным номерам",
    tabs: [["inv_mat", "Материалы"], ["inv_eq", "Оборудование"], ["inv_hist", "История"]]},
};
let STK = {units: [], move_kinds: {}, eq_status: {}};
// 3.14: the categories offered for a material (any other may be typed); the household ones (napkins, paper, cleaning) are
// the stock too, and the P&L puts what was written off of them into «Хозяйственные расходы»
const MAT_CATS = ["Пломбировочные материалы", "Анестезия", "Эндодонтия", "Ортопедия и слепочные материалы", "Хирургия и имплантация",
  "Гигиена и профилактика", "Дезинфекция и стерилизация", "Расходные одноразовые", "Хозяйственные товары", "Канцелярия"];
const qtyFmt = (n, u) => `${(Math.round((+n || 0) * 1000) / 1000).toLocaleString("ru-RU")}${u ? " " + esc(u) : ""}`;  // HTML: the unit is escaped
const DOC_KIND = {receipt: "Приходная накладная", writeoff: "Акт списания материалов", inventory: "Инвентаризация",
  transfer: "Перемещение материалов", visit: "Списание по приёму"};  // 3.5: places and visits of Dentist Plus
const hasPlaces = () => (STK.locations || []).length > 1;
const placeSelect = (id, cur = "", label = "Место") => hasPlaces() ? `<label class="fl">${label}<select class="input" id="${id}">${STK.locations.map(l => `<option value="${esc(l.id)}" ${l.id === (cur || "") ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>` : "";

/** The section's title and its tabs (3.14): drawn again when another section of the stock is opened. */
function stockHead(area) {
  const a = STOCK_AREAS[area];
  $("#stockTitle").textContent = a.title; $("#stockSub").textContent = a.sub;
  const tabs = $("#stockTabs");
  tabs.classList.toggle("eqnav", !!a.more);
  tabs.classList.toggle("seg", !a.more);  // the sliding pill of a segmented control is not for the big tabs
  if (a.more) tabs.classList.remove("has-ind");
  tabs.innerHTML = a.more ? eqNavHtml(a) : a.tabs.map(([k, t, tip]) => `<button data-k="${k}" ${tip ? `title="${esc(tip)}"` : ""}>${t}</button>`).join("");
  if (a.more) eqNavWire();
  $$("#stockTabs button[data-k]").forEach(b => b.onclick = () => {
    if (b.dataset.k === "inv") return stockGo("inventory", "inv_eq");  // 3.15: «Ещё → Инвентаризация» is the section of its own
    stockSetTab(b.dataset.k);
    S.eqOpen = null; S.matOpen = null;  // 3.13: a tab opens its list, not the card left open
    loadStock();
  });
}
function stockSetTab(tab) {
  S.stockTab = tab; S.stockTabs[S.stockArea || "stock"] = tab;
  $$("#stockTabs button[data-k]").forEach(x => x.classList.toggle("on", x.dataset.k === tab));
  eqNavMark();
}
/** 3.15: «Ещё» shows the name of the tab opened from it. */
function eqNavMark() {
  const a = STOCK_AREAS[S.stockArea || "stock"], b = $("#eqMoreBtn");
  if (!a || !a.more || !b) return;
  const m = a.more.find(t => t[0] === S.stockTab);
  b.classList.toggle("on", !!m); $("span", b).textContent = m ? m[1] : "Ещё";
  const menu = $("#eqMoreMenu"); if (menu) menu.hidden = true;
}
/** Opens a tab of a section of the stock from anywhere (a card, a task, a scan): switches the section when needed. */
function stockGo(area, tab) {
  if (tab) S.stockTabs[area] = tab;
  if (S.view !== area || $("#view-stock").hidden) return show(area);  // show() → loadStock() draws the tab
  if (tab) stockSetTab(tab);
  return loadStock();
}

function stockTabsByRights() {
  const st = canAny("stock_view", "stock_edit");
  const vis = {home: canAny("stock_view", "stock_edit", "stock_ops"), balance: st, docs: st, moves: st, visits: st && !!STK.dp_link, places: st,
    norms: st, suppliers: can("stock_edit"), orders: st,
    equipment: canAny("equipment", "stock_view"), service: canAny("equipment", "stock_view"), amort: can("accounting"),
    disposed: canAny("equipment", "stock_view"), steril: canAny("sterilization", "equipment"),
    inv_mat: can("stock_edit"), inv_eq: can("equipment"), inv_hist: canAny("stock_edit", "equipment"),
    inv: can("equipment"), eq_refs: canAny("equipment", "stock_view"), eq_overview: canAny("equipment", "stock_view", "equipment_approve")};  // 3.15
  const area = STOCK_AREAS[S.stockArea], keys = [...area.tabs, ...(area.more || [])].map(t => t[0]).filter(k => k !== "inv");
  $$("#stockTabs button[data-k]").forEach(b => b.hidden = !vis[b.dataset.k]);
  const mb = $("#eqMoreBtn"); if (mb) mb.parentElement.hidden = !(area.more || []).some(t => vis[t[0]]);
  if (!vis[S.stockTab] || !keys.includes(S.stockTab)) S.stockTab = keys.find(k => vis[k]) || keys[0];
  S.stockTabs[S.stockArea] = S.stockTab;
  $$("#stockTabs button[data-k]").forEach(b => b.classList.toggle("on", b.dataset.k === S.stockTab));
  eqNavMark();
}

async function loadStock() {
  const area = STOCK_AREAS[S.view] ? S.view : "stock";
  if (S.stockArea !== area) { S.stockArea = area; S.stockTab = S.stockTabs[area]; stockHead(area); }
  if (area !== "stock") S.matOpen = null;
  if (area !== "equipment") S.eqOpen = null;
  stockTabsByRights();
  if (S.stockTab === "steril") return sterilJournal();  // the journal is also for those without stock rights
  STK = await api.stock_summary();
  stockTabsByRights();  // 3.13: «По приёмам» only while the stock is linked to Dentist Plus (STK.dp_link)
  if (S.matOpen && ["home", "balance"].includes(S.stockTab)) return mtCard();  // 3.13: the material card is a screen of these tabs
  const fn = {home: stockHome, balance: stockBalance, docs: stockDocs, moves: stockMoves, norms: stockNorms, suppliers: stockSuppliers,
    visits: stockVisits, places: stockPlaces, orders: stockOrders,
    equipment: stockEquipment, service: eqServiceTab, amort: eqAmortTab, disposed: eqDisposedTab,
    inv_mat: invMaterials, inv_eq: invEquipment, inv_hist: invHistory, eq_refs: eqRefsTab, eq_overview: eqOverview}[S.stockTab];
  await fn();
}

function statRow() {
  return `<div class="stat-row">
    <div class="stat"><span>Материалов</span><b>${STK.materials}</b></div>
    <div class="stat ${STK.low ? "warn" : ""}"><span>Заканчиваются</span><b>${STK.low}</b></div>
    <div class="stat ${STK.expired ? "bad" : STK.expiring ? "warn" : ""}" title="Партии с истёкшим сроком или сроком до 30 дней"><span>Истекает срок</span><b>${(STK.expired || 0) + (STK.expiring || 0)}</b></div>
    <div class="stat"><span>Сумма остатков</span><b>${money(STK.value)}</b></div></div>`;
}
/** 3.14: the equipment's own figures (the money only with «Бухгалтерия» — the server sends it only then). */
function eqStatRow() {
  return `<div class="stat-row">
    <div class="stat"><span>Оборудование в работе</span><b>${STK.equipment}</b></div>
    <div class="stat ${STK.eq_repair ? "warn" : ""}"><span>В ремонте</span><b>${STK.eq_repair || 0}</b></div>
    <div class="stat ${STK.service_due ? "warn" : ""}"><span>Пора на ТО</span><b>${STK.service_due}</b></div>
    ${STK.eq_money ? `<div class="stat"><span>Стоимость</span><b>${money(STK.eq_cost)}</b></div><div class="stat ok" title="Стоимость минус начисленная амортизация"><span>Остаточная стоимость</span><b>${money(STK.eq_residual)}</b></div>` : ""}</div>`;
}

/* ------------------------------------------------------------ balances */
async function stockBalance() {
  S.matOpen = null;
  const body = $("#stockBody");
  const q = S.stockQ || "", low = !!S.stockLow, exp = !!S.stockExp;
  if (!hasPlaces() || !STK.locations.some(l => l.id === S.stockLoc)) S.stockLoc = null;  // 3.5: «все места» or one place
  const loc = S.stockLoc, locName = loc != null ? STK.locations.find(l => l.id === loc).name : "";
  const all = await api.materials(q, low, exp, loc);
  const cats = [...new Set(all.map(m => m.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  if (S.stockCat && !cats.includes(S.stockCat)) S.stockCat = "";
  const rows = S.stockCat ? all.filter(m => m.category === S.stockCat) : all;  // 3.14: one category (e.g. «Хозяйственные товары»)
  S.stockRows = rows;
  const edit = can("stock_edit"), acc = can("accounting") && rows.some(m => m.balance_doc !== undefined);
  const docDiff = acc && loc == null && rows.some(m => Math.abs(m.balance - m.balance_doc) > 1e-9);
  body.innerHTML = statRow() + `<div class="tab-tools">
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="stQ" placeholder="Материал, код, штрихкод" value="${esc(q)}"></div>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="stLow" ${low ? "checked" : ""}><span class="sw"></span>Только заканчиваются</label>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="stExp" ${exp ? "checked" : ""}><span class="sw"></span>Истекает срок</label>
      ${cats.length > 1 ? `<select class="input sm-sel" id="stCat" title="Категория материалов"><option value="">Все категории</option>${cats.map(c => `<option value="${esc(c)}" ${c === S.stockCat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>` : ""}
      ${hasPlaces() ? `<select class="input sm-sel" id="stLoc" title="Остатки по месту хранения"><option value="*">Все места</option>${STK.locations.map(l => `<option value="${esc(l.id)}" ${l.id === loc ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>` : ""}
      <span class="grow"></span>
      ${edit && hasPlaces() ? `<button class="btn ghost" id="stMove" title="Переместить между кабинетами и филиалами">Перемещение</button>` : ""}
      <button class="btn ghost" id="stOrder" title="Что и сколько заказать, у кого дешевле">Заказ поставщикам</button>
      ${edit && STK.expired ? `<button class="btn ghost danger-t" id="stExpOut">Списать просроченное</button>` : ""}
      ${edit ? `<button class="btn" id="stIn">Приход</button><button class="btn ghost" id="stOut">Списание</button><button class="btn ghost" id="stInv" title="Раздел «Инвентаризация»">Инвентаризация</button><button class="btn ghost" id="stNew">Новый материал</button>` : ""}
      <button class="icon-btn" id="stPrint" title="Печать остатков"><svg viewBox="0 0 24 24"><path d="M7 9V3.5h10V9M7 17H4.5V10.5a1.5 1.5 0 0 1 1.5-1.5h12a1.5 1.5 0 0 1 1.5 1.5V17H17"/><rect x="7" y="14" width="10" height="6.5" rx="1"/></svg></button>
      ${acc ? `<button class="btn ghost small" id="stPrintDoc" title="Остатки только по документам — для бухгалтерии">Печать по документам</button>` : ""}</div>
    ${loc != null ? `<div class="note-box">Остатки места «${esc(locName)}». Минимум и «заканчиваются» — по всей клинике; общий остаток — в подсказке у количества.</div>` : ""}
    ${docDiff ? `<div class="warn-line">Есть приход или списание без документов: остаток «по документам» отличается от фактического. Его видите только вы (право «Бухгалтерия»).</div>` : ""}
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Код</th><th>Материал</th><th>Раздел</th><th class="num">Остаток</th>${docDiff ? '<th class="num" title="Только движения с документами">По документам</th>' : ""}<th class="num">Минимум</th><th class="num">Цена</th><th class="num">Сумма</th><th></th></tr></thead><tbody>${
      rows.map(m => `<tr data-m="${esc(m.id)}" class="${m.balance < 0 ? "neg" : ""} ${m.exp_state ? "exp-" + m.exp_state : ""}"><td class="muted">${esc(m.code)}</td><td class="lnk"><div class="sn-mat sm">${phHtml(m.photo_id)}<span><b>${esc(m.name)}</b>${expLine(m)}</span></div></td><td>${esc(m.category)}</td>
        <td class="num" ${m.total_balance !== undefined ? `title="Во всей клинике: ${qtyFmt(m.total_balance, m.unit)}"` : ""}><b>${qtyFmt(m.balance, m.unit)}</b></td>${docDiff ? `<td class="num ${Math.abs(m.balance - m.balance_doc) > 1e-9 ? "warn-t" : "muted"}">${qtyFmt(m.balance_doc, m.unit)}</td>` : ""}<td class="num muted">${m.min_qty ? qtyFmt(m.min_qty) : "—"}</td><td class="num">${money(m.price)}</td><td class="num">${money(m.value)}</td>
        <td class="pills">${m.balance < 0 ? '<span class="pill st-cancel">меньше нуля</span>' : m.low ? '<span class="pill st-cancel">заканчивается</span>' : m.exp_state ? "" : '<span class="pill st-ok">есть</span>'}${m.exp_state === "expired" ? '<span class="pill exp-pill expired">просрочено</span>' : m.exp_state === "soon" ? '<span class="pill exp-pill soon">истекает срок</span>' : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>${q || low || exp ? "Ничего не найдено" : "Склад пока пуст"}</b><span>${edit ? "Добавьте материалы и оформите приход по накладной" : ""}</span></div>`}</div>`;
  let t; $("#stQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.stockQ = e.target.value; stockBalance().then(() => { const i = $("#stQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  $("#stLow").onchange = e => { S.stockLow = e.target.checked; stockBalance(); };
  $("#stExp").onchange = e => { S.stockExp = e.target.checked; stockBalance(); };
  const sl = $("#stLoc"); if (sl) sl.onchange = e => { S.stockLoc = e.target.value === "*" ? null : e.target.value; stockBalance(); };
  const sc = $("#stCat"); if (sc) sc.onchange = e => { S.stockCat = e.target.value; stockBalance(); };
  $$("#stockBody tr[data-m]").forEach(tr => tr.onclick = () => openMaterial(tr.dataset.m));
  const on = (id, f) => { const el = $(id); if (el) el.onclick = f; };
  on("#stIn", () => openStockDoc("receipt")); on("#stOut", () => openStockDoc("writeoff")); on("#stInv", () => { S.invLoc = loc; stockGo("inventory", "inv_mat"); });
  on("#stNew", () => editMaterial({})); on("#stPrint", () => printBalance()); on("#stPrintDoc", () => printBalance(true));
  on("#stOrder", () => openPurchase()); on("#stExpOut", writeOffExpired);
  on("#stMove", () => openTransfer({from: loc ?? ""}));
  loadThumbs(body);
}

function editMaterial(m, {onSaved} = {}) {
  const box = modal(`<div class="m-h"><h3>${m.id ? "Редактировать: " + esc(m.name) : "Карточка материала"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <label class="fl">Название*<input class="input" id="mName" value="${esc(m.name || "")}" autofocus></label>
      <div class="grid3"><label class="fl" title="Внутренний номер карточки: на наклейке, в QR и для сканера">Номер<input class="input" id="mNum" value="${esc(m.number || "")}" placeholder="присвоится сам"></label>
        <label class="fl">Артикул (код поставщика)<input class="input" id="mCode" value="${esc(m.code || "")}"></label>
        <label class="fl">Единица<input class="input" id="mUnit" value="${esc(m.unit || "шт")}" list="mUnits"></label></div>
      <div class="grid2"><label class="fl">Производитель<input class="input" id="mMan" value="${esc(m.manufacturer || "")}" placeholder="например: 3M"></label>
        <label class="fl">Категория<input class="input" id="mCat" value="${esc(m.category || "")}" list="mCats"></label></div>
      <label class="fl">Описание<input class="input" id="mDesc" value="${esc(m.description || "")}" placeholder="например: композит светового отверждения"></label>
      <div class="grid3"><label class="fl">Форма выпуска<input class="input" id="mForm" value="${esc(m.form || "")}" placeholder="шприц 4 г"></label>
        <label class="fl">Срок годности (общий)<input class="input" id="mLife" value="${esc(m.shelf_life || "")}" placeholder="2 года"></label>
        <label class="fl">Условия хранения<input class="input" id="mStore" value="${esc(m.storage || "")}" placeholder="+15…+25 °C"></label></div>
      <div class="grid3"><label class="fl">Минимальный остаток<input class="input" id="mMin" type="number" step="any" min="0" value="${m.min_qty || ""}"></label>
        <label class="fl" title="До него «Заказ поставщикам» дозаказывает материал">Оптимальный остаток<input class="input" id="mOpt" type="number" step="any" min="0" value="${m.opt_qty || ""}"></label>
        <label class="fl">Срок поставки, дней<input class="input" id="mLead" type="number" step="1" min="0" max="365" value="${m.lead_days || ""}"></label></div>
      <div class="grid3"><label class="fl">Цена за единицу, ₽<input class="input" id="mPrice" type="number" step="any" min="0" value="${m.price ?? ""}"></label>
        <label class="fl">Штрихкод<input class="input" id="mBar" value="${esc(m.barcode || "")}"></label>
        <label class="fl" title="${m.id ? "У него «Заказ поставщикам» заказывает этот материал" : "Основной поставщик; начальный остаток запишется приходом от него — он появится в истории поставок"}">${m.id ? "Основной поставщик" : "Поставщик"}<select class="input" id="mSup"><option value="">— не выбран —</option></select></label></div>
      ${m.id ? "" : `<div class="grid2"><label class="fl">Начальный остаток<input class="input" id="mStart" type="number" step="any" min="0"></label>
        <label class="fl">Номер накладной начального остатка<input class="input" id="mDoc" placeholder="если есть"></label></div>`}
      <label class="fl">Комментарий<input class="input" id="mCom" value="${esc(m.comment || "")}"></label>
      <datalist id="mUnits">${STK.units.map(u => `<option value="${esc(u)}">`).join("")}</datalist>
      <datalist id="mCats">${[...new Set([...MAT_CATS, ...(S.stockRows || []).map(r => r.category).filter(Boolean)])].map(c => `<option value="${esc(c)}">`).join("")}</datalist>
      <div class="auth-err" id="mErr"></div></div>
    <div class="m-f">${m.id ? `<button class="btn ghost small danger" id="mDel">Убрать из справочника</button>` : ""}<span class="muted">Когда остаток опустится до минимума, материал попадёт в «Заканчиваются»</span>
      <button class="btn ghost" data-close>Отмена</button><button class="btn" id="mOk">Сохранить</button></div>`, {wide: true});
  $("#mOk", box).onclick = async () => {
    try {
      const id = await api.save_material({id: m.id, name: $("#mName").value, number: $("#mNum").value, code: $("#mCode").value, category: $("#mCat").value, unit: $("#mUnit").value,
        manufacturer: $("#mMan").value, description: $("#mDesc").value, form: $("#mForm").value, shelf_life: $("#mLife").value, storage: $("#mStore").value,
        min_qty: $("#mMin").value, opt_qty: $("#mOpt").value, lead_days: $("#mLead").value, price: $("#mPrice").value, barcode: $("#mBar").value,
        comment: $("#mCom").value, supplier_id: $("#mSup").value, start_qty: m.id ? null : $("#mStart").value, doc_number: m.id ? null : $("#mDoc").value});
      closeModal(); toast(m.id ? "Сохранено" : "Карточка создана");
      if (onSaved) onSaved(id);
      else if (!m.id && ["home", "balance"].includes(S.stockTab)) openMaterial(id);  // 3.13: like equipment, the new card opens
      else loadStock();
    } catch (e) { $("#mErr").textContent = errText(e); }
  };
  const del = $("#mDel", box);
  if (del) del.onclick = async () => { if (await ask(`Убрать «${m.name}» из справочника?`, {danger: true, ok: "Убрать", text: "История движения сохранится, нормы списания по услугам удалятся."})) { await api.delete_material(m.id); closeModal(); S.matOpen = null; loadStock(); } };
  const ms = $("#mSup", box);
  if (ms) api.suppliers().then(list => { ms.insertAdjacentHTML("beforeend", list.map(x => `<option value="${esc(x.id)}" ${x.id === m.supplier_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")); }).catch(() => {});
}

/* openMaterial — the screen «Карточка материала»: stock-matcard.js (3.13) */

function movesTable(moves, withMaterial = true) {
  if (!moves.length) return `<div class="empty"><b>Движений нет</b></div>`;
  const pl = hasPlaces();  // 3.5: the place of every move once the clinic has cabinets or branches
  return `<table class="tbl compact"><thead><tr><th>Когда</th><th>Операция</th>${withMaterial ? "<th>Материал</th>" : ""}<th class="num">Кол-во</th>${pl ? "<th>Место</th>" : ""}<th>Основание</th><th>Сотрудник</th></tr></thead><tbody>${
    moves.map(x => `<tr><td>${fmtDT(x.at)}</td><td><span class="mv mv-${x.kind}">${esc(x.kind_title)}</span></td>${withMaterial ? `<td>${esc(x.name)}</td>` : ""}
      <td class="num ${x.qty < 0 ? "bad-t" : "ok-t"}"><b>${x.qty > 0 ? "+" : ""}${qtyFmt(x.qty, x.unit)}</b></td>${pl ? `<td class="muted">${esc(x.location_name || "")}</td>` : ""}
      <td class="muted">${esc([x.doc_number ? "№ " + x.doc_number : "", x.patient_name || "", x.reason || ""].filter(Boolean).join(" · "))}${x.nodoc ? " " + '<span class="pill dx-nodoc">без документа</span>' : ""}</td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody></table>`;
}

/* ---------------------------------------------- receipt and write-off */
async function openStockDoc(kind, preset, opts = {}) {
  const place0 = hasPlaces() ? (opts.location ?? S.stockLoc ?? "") : null;  // 3.5: the place of the receipt / write-off
  let [mats, sups] = await Promise.all([api.materials("", false, false, place0), kind === "receipt" ? api.suppliers() : Promise.resolve([])]);
  const blank = () => ({material_id: "", qty: "", price: "", lot: "", expires: ""});
  const st = {lines: preset && preset.length ? preset.map(x => ({...blank(), ...x})) : [blank()]};
  const isIn = kind === "receipt";
  const box = modal(`<div class="m-h"><h3>${isIn ? "Приход по накладной" : "Списание материалов"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      ${isIn ? `<div class="grid3"><label class="fl">Поставщик<select class="input" id="dSup"><option value="">—</option>${sups.map(s => `<option value="${esc(s.id)}" ${s.id === opts.supplier_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
        <label class="fl">Номер накладной<input class="input" id="dNum"></label><label class="fl">Дата<input class="input" type="date" id="dDate" value="${iso(new Date())}"></label></div>
        <div class="scan-row"><svg viewBox="0 0 24 24"><path d="M4 6v12M7 6v12M10 6v12M13.5 6v12M16 6v12M20 6v12"/></svg><input class="input" id="dScan" placeholder="Сканируйте штрихкод" autocomplete="off" autofocus>
          <span class="muted" id="dScanMsg">Сканер добавит строку или прибавит 1 к количеству. Код с партией и сроком («Честный знак», GS1) заполнит их сам.</span></div>`
      : `<div class="grid2"><label class="fl">Причина списания*<input class="input" id="dReason" list="woReasons" placeholder="например: истёк срок годности" value="${esc(opts.reason || "")}"></label><label class="fl">Дата<input class="input" type="date" id="dDate" value="${iso(new Date())}"></label></div>
        <datalist id="woReasons"><option value="Истёк срок годности"><option value="Повреждение, брак"><option value="Использовано вне услуг (общие нужды)"><option value="Утеря"></datalist>`}
      ${place0 != null ? `<div class="grid3">${placeSelect("dPlace", place0, isIn ? "Куда оприходовать" : "Откуда списать")}</div>` : ""}
      <table class="tbl compact doc-lines"><thead><tr><th>Материал</th><th class="num">Остаток</th>${isIn ? `<th style="width:120px">Партия</th><th style="width:150px">Годен до</th>` : ""}<th class="num" style="width:110px">Количество</th>${isIn ? `<th class="num" style="width:120px">Цена, ₽</th><th class="num">Сумма</th>` : ""}<th></th></tr></thead><tbody id="dLines"></tbody></table>
      <div><button class="btn ghost small" id="dAdd">+ Ещё материал</button></div>
      <label class="fl">Комментарий<input class="input" id="dCom" value="${esc(opts.comment || "")}"></label>
      <div class="nodoc-row"><label class="dx-doc"><input type="checkbox" id="dNodoc">${isIn ? "Без накладной (без документов)" : "Без акта (без документов)"}</label>
        ${isIn && canAny("expenses_day", "accounting") ? `<label class="fl inline">Записать в расходы за день<select class="input" id="dPay"><option value="">— не записывать —</option>${["Наличные из кассы", "Карта клиники", "Перевод", "Свои деньги сотрудника"].map(m => `<option>${m}</option>`).join("")}</select></label>` : ""}
        <span class="muted">${isIn ? "Материал всё равно придёт на склад; в остатке «по документам» его не будет." : "Материал уйдёт со склада без акта; номер акта не займёт."}</span></div>
      <div class="auth-err" id="dErr"></div></div>
    <div class="m-f"><span class="muted" id="dTotal"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="dOk">${isIn ? "Оприходовать" : "Списать"}</button></div>`, {wide: true});
  let byId = Object.fromEntries(mats.map(m => [m.id, m]));
  const draw = () => {
    $("#dLines").innerHTML = st.lines.map((l, i) => { const m = byId[l.material_id];
      const lotTag = !isIn && l.lot_id ? `<small class="lot-tag ${l.expires && l.expires < iso(new Date()) ? "expired" : ""}">партия ${esc(l.lot || "без номера")}${l.expires ? " · годен до " + fmtDate(l.expires) : ""}</small>` : "";
      return `<tr><td><select class="input" data-i="${i}" data-f="material_id" ${l.lot_id ? "disabled" : ""}><option value="">— выберите материал —</option>${mats.map(x => `<option value="${esc(x.id)}" ${x.id === l.material_id ? "selected" : ""}>${esc(x.name)}${x.code ? " · " + esc(x.code) : ""}</option>`).join("")}</select>${lotTag}</td>
        <td class="num muted">${m ? qtyFmt(m.balance, m.unit) : ""}</td>
        ${isIn ? `<td><input class="input" data-i="${i}" data-f="lot" value="${esc(l.lot)}" placeholder="№ партии"></td><td><input class="input" type="date" data-i="${i}" data-f="expires" value="${esc(l.expires)}"></td>` : ""}
        <td><input class="input num" type="number" step="any" min="0" data-i="${i}" data-f="qty" value="${esc(l.qty)}"></td>
        ${isIn ? `<td><input class="input num" type="number" step="any" min="0" data-i="${i}" data-f="price" value="${esc(l.price)}"></td><td class="num">${money((+l.qty || 0) * (+l.price || 0))}</td>` : ""}
        <td><button class="linkbtn" data-rm="${i}">убрать</button></td></tr>`; }).join("");
    const total = st.lines.reduce((a, l) => a + (+l.qty || 0) * (+(isIn ? l.price : (byId[l.material_id] || {}).price) || 0), 0);
    $("#dTotal").textContent = `Строк: ${st.lines.filter(l => l.material_id).length} · на сумму ${money(total)}`;
    $$("#dLines [data-f]").forEach(el => el.onchange = () => { const l = st.lines[+el.dataset.i]; l[el.dataset.f] = el.value;
      if (el.dataset.f === "material_id" && isIn && byId[el.value] && !l.price) l.price = byId[el.value].price; draw(); });
    $$("#dLines [data-rm]").forEach(b => b.onclick = () => { st.lines.splice(+b.dataset.rm, 1); if (!st.lines.length) st.lines.push(blank()); draw(); });
  };
  draw();
  const dp = $("#dPlace", box);
  if (dp) dp.onchange = async () => { mats = await api.materials("", false, false, dp.value); byId = Object.fromEntries(mats.map(m => [m.id, m])); draw(); };
  $("#dAdd", box).onclick = () => { st.lines.push(blank()); draw(); };
  const scan = $("#dScan", box);
  if (scan) {
    const msg = (t, bad) => { const el = $("#dScanMsg"); el.textContent = t; el.className = bad ? "bad-t" : "muted"; };
    const addMaterial = (m, p) => {
      byId[m.id] = m;
      const same = st.lines.find(l => l.material_id === m.id && (l.lot || "") === (p.lot || "") && (l.expires || "") === (p.expires || ""));
      if (same) same.qty = String((+same.qty || 0) + 1);
      else {
        const empty = st.lines.findIndex(l => !l.material_id);
        const line = {...blank(), material_id: m.id, qty: "1", price: m.price || "", lot: p.lot || "", expires: p.expires || ""};
        if (empty >= 0) st.lines[empty] = line; else st.lines.push(line);
      }
      draw(); msg(`✓ ${m.name}${p.lot ? " · партия " + p.lot : ""}${p.expires ? " · годен до " + fmtDate(p.expires) : ""}`);
    };
    scan.onkeydown = async e => {
      if (e.key !== "Enter") return;
      e.preventDefault(); e.stopPropagation();
      const code = scan.value.trim(); scan.value = "";
      if (!code) return;
      let p;
      try { p = await api.stock_scan(code); } catch (err) { msg(errText(err), true); return; }
      if (p.material) return addMaterial(p.material, p);
      const vals = await askInput("Новый материал", [{label: "Название", value: ""}, {label: "Единица", value: "шт"}, {label: "Цена за единицу, ₽", type: "number", required: false}],
        {text: `Штрихкода ${p.barcode} нет в справочнике. Создать материал с этим штрихкодом и добавить в приход?`, ok: "Создать и добавить"});
      scan.focus();
      if (!vals) { msg(`Штрихкод ${p.barcode} не найден`, true); return; }
      try {
        const id = await api.save_material({name: vals[0], unit: vals[1], price: vals[2], barcode: p.barcode});
        mats = await api.materials(""); byId = Object.fromEntries(mats.map(m => [m.id, m]));
        addMaterial(byId[id], p); toast("Материал добавлен в справочник");
      } catch (err) { msg(errText(err), true); }
    };
  }
  $("#dOk", box).onclick = async () => {
    const lines = st.lines.filter(l => l.material_id);
    const nodoc = $("#dNodoc").checked, pay = $("#dPay") ? $("#dPay").value : "";
    const f = {date: $("#dDate").value, comment: $("#dCom").value, lines, nodoc};
    if (dp) f.location_id = dp.value;
    try {
      const id = isIn ? await api.stock_receive({...f, supplier_id: $("#dSup").value, number: $("#dNum").value, pay, order_id: opts.order_id || undefined})
        : await api.stock_write_off({...f, reason: $("#dReason").value});
      closeModal(); toast((isIn ? "Приход оформлен" : "Материалы списаны") + (nodoc ? " — без документов" : "") + (pay ? ", расход записан" : ""));
      loadStock();
      if (!isIn && !nodoc && await ask("Распечатать акт списания?", {icon: "print", ok: "Распечатать", cancel: "Не сейчас", text: "Акт можно распечатать и позже: «Склад» → «Документы»."})) printStockDoc(id);
    } catch (e) { $("#dErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------ 3.14 «Инвентаризация» */
const invRows = mats => mats.map(m => `<tr data-cat="${esc(m.category || "")}" data-q="${esc(`${m.name} ${m.code || ""} ${m.number || ""} ${m.barcode || ""}`.toLowerCase())}"><td>${esc(m.name)}<small class="muted" style="display:block">${esc([m.number, m.category].filter(Boolean).join(" · "))}</small></td><td class="num">${qtyFmt(m.balance, m.unit)}</td>
  <td><input class="input num" type="number" step="any" min="0" data-im="${esc(m.id)}" data-b="${m.balance}"></td><td class="num" data-d="${esc(m.id)}"></td></tr>`).join("");
function invRecount(root) {
  let n = 0, plus = 0, minus = 0;
  $$("[data-im]", root).forEach(i => { const d = $(`[data-d="${i.dataset.im}"]`, root); if (i.value === "") { d.textContent = ""; return; } n++;
    const diff = Math.round((+i.value - +i.dataset.b) * 1000) / 1000; if (diff > 0) plus++; if (diff < 0) minus++;
    d.textContent = diff ? (diff > 0 ? "+" : "") + diff.toLocaleString("ru-RU") : "0"; d.className = "num " + (diff < 0 ? "bad-t" : diff > 0 ? "ok-t" : "muted"); });
  const c = $("#invCnt", root); if (c) c.textContent = n ? `Пересчитано: ${n}${plus || minus ? ` · излишки: ${plus} · недостачи: ${minus}` : ""}` : "";
}
async function invConduct(root, place) {
  const f = {comment: $("#invCom", root).value, nodoc: $("#invNodoc", root).checked,
    lines: $$("[data-im]", root).filter(i => i.value !== "").map(i => ({material_id: i.dataset.im, actual: i.value}))};
  if (!f.lines.length) throw new Error("Впишите фактический остаток хотя бы одного материала");
  if (place != null) f.location_id = place;
  return api.stock_inventory(f);
}

/** «Инвентаризация → Материалы»: the count of one place on the whole screen (3.14; before — a dialog of «Остатки»). */
async function invMaterials() {
  if (!hasPlaces() || !STK.locations.some(l => l.id === S.invLoc)) S.invLoc = hasPlaces() ? (STK.locations.some(l => l.id === S.stockLoc) ? S.stockLoc : "") : null;
  const place = hasPlaces() ? S.invLoc : null;
  const mats = await api.materials("", false, false, place);
  const cats = [...new Set(mats.map(m => m.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  const body = $("#stockBody");
  body.innerHTML = `<div class="inv-screen">
    <div class="tab-tools">${place != null ? placeSelect("invPlace", place, "Где считаем") : ""}
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="invQ" placeholder="Найти: название, код, штрихкод" autocomplete="off"></div>
      ${cats.length > 1 ? `<select class="input sm-sel" id="invCat"><option value="">Все категории</option>${cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select>` : ""}
      <span class="grow"></span><button class="btn ghost" id="invSheet">Печать бланка</button></div>
    <div class="note-box">Пересчитайте материалы${place != null ? ` в месте «${esc(STK.locations.find(l => l.id === place).name)}»` : ""} и впишите фактический остаток. Пустые строки не меняются. Разница с учётом станет движением «Инвентаризация», документ — в «Истории».</div>
    <div class="pbody" style="margin-top:8px">${mats.length ? `<table class="tbl compact inv-t"><thead><tr><th>Материал</th><th class="num">По учёту</th><th class="num" style="width:150px">Фактически</th><th class="num">Разница</th></tr></thead><tbody>${invRows(mats)}</tbody></table>`
      : `<div class="empty"><b>Материалов нет</b><span>Добавьте их в «Склад и материалы → Остатки»</span></div>`}</div>
    <div class="inv-foot"><label class="fl grow">Комментарий<input class="input" id="invCom" placeholder="например: годовая инвентаризация, комиссия: …"></label>
      <label class="dx-doc"><input type="checkbox" id="invNodoc">Внутренняя (без документов)</label><span class="muted" id="invCnt"></span>
      <button class="btn" id="invOk" ${mats.length ? "" : "disabled"}>Провести инвентаризацию</button></div><div class="auth-err" id="invErr"></div></div>`;
  $$("[data-im]", body).forEach(i => i.oninput = () => invRecount(body));
  const filter = () => { const q = ($("#invQ").value || "").trim().toLowerCase(), c = $("#invCat") ? $("#invCat").value : "";
    $$(".inv-t tbody tr", body).forEach(tr => { tr.hidden = (q && !tr.dataset.q.includes(q)) || (c && tr.dataset.cat !== c); }); };
  $("#invQ").oninput = filter; const ic = $("#invCat"); if (ic) ic.onchange = filter;
  $("#invQ").onkeydown = async e => {  // a scanner: the material's row gets the focus
    if (e.key !== "Enter" || !e.target.value.trim()) return;
    e.preventDefault();
    try { const r = await api.stock_scan(e.target.value.trim()); if (r.material) { e.target.value = ""; filter(); const i = $(`[data-im="${r.material.id}"]`, body); if (i) { i.focus(); i.select(); } } } catch (x) { /* not a barcode */ }
  };
  const ip = $("#invPlace"); if (ip) ip.onchange = () => { S.invLoc = ip.value; invMaterials(); };
  $("#invSheet").onclick = () => printInventorySheet(mats.filter(m => { const tr = $(`[data-im="${m.id}"]`, body); return !tr || !tr.closest("tr").hidden; }), place);
  $("#invOk").onclick = async () => {
    try { const r = await invConduct(body, place); toast(r.diffs.length ? `Проведено. Расхождений: ${r.diffs.length}` : "Проведено. Расхождений нет"); loadStock(); }
    catch (e) { $("#invErr").textContent = errText(e); }
  };
}

/** A count of some materials in a dialog (the material card's «Провести инвентаризацию»). */
async function openInventory(place, onlyIds) {
  if (place === undefined) place = hasPlaces() ? (S.stockLoc ?? "") : null;  // 3.5: a count of one place
  let mats = await api.materials("", false, false, place);
  if (onlyIds) mats = mats.filter(m => onlyIds.includes(m.id));
  const box = modal(`<div class="m-h"><h3>Инвентаризация${place != null ? ": " + esc(STK.locations.find(l => l.id === place).name) : ""}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      ${place != null ? `<div class="grid3">${placeSelect("invPlace", place, "Где считаем")}</div>` : ""}
      <div class="muted">Пересчитайте и впишите фактический остаток. Разница с учётом станет движением «Инвентаризация».</div>
      <table class="tbl compact"><thead><tr><th>Материал</th><th class="num">По учёту</th><th class="num" style="width:140px">Фактически</th><th class="num">Разница</th></tr></thead><tbody>${invRows(mats)}</tbody></table>
      <label class="fl">Комментарий<input class="input" id="invCom"></label>
      <label class="dx-doc"><input type="checkbox" id="invNodoc">Внутренняя инвентаризация (без документов)</label><div class="auth-err" id="invErr"></div></div>
    <div class="m-f"><span class="muted" id="invCnt"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="invOk">Провести</button></div>`, {wide: true});
  $$("[data-im]", box).forEach(i => i.oninput = () => invRecount(box));
  const ip = $("#invPlace", box); if (ip) ip.onchange = () => { closeModal(); openInventory(ip.value, onlyIds); };
  $("#invOk", box).onclick = async () => {
    try { const r = await invConduct(box, place); closeModal(); toast(r.diffs.length ? `Проведено. Расхождений: ${r.diffs.length}` : "Проведено. Расхождений нет"); loadStock(); }
    catch (e) { $("#invErr", box).textContent = errText(e); }
  };
}

/** «Инвентаризация → Оборудование»: every piece in the list — found or not, where, in what condition; one button for all. */
async function invEquipment() {
  const [rows, places] = await Promise.all([api.equipment_list("", false), api.stock_locations().catch(() => [])]);
  const pl = (places || []).filter(p => p.id);
  const C = {ok: "Исправно", service: "Требует обслуживания", faulty: "Неисправно"};
  const where = S.invEqLoc || "";
  const body = $("#stockBody");
  const list = rows.filter(e => !where || (where === "-" ? !e.location_id : e.location_id === where));
  body.innerHTML = `<div class="inv-screen">
    <div class="tab-tools">${pl.length ? `<select class="input sm-sel" id="ieLoc" title="Проверять по одному кабинету"><option value="">Всё оборудование</option>${pl.map(p => `<option value="${esc(p.id)}" ${p.id === where ? "selected" : ""}>${esc(p.name)}</option>`).join("")}<option value="-" ${where === "-" ? "selected" : ""}>Место не выбрано</option></select>` : ""}
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="ieQ" placeholder="Инв. №, название или QR со сканера" autocomplete="off"></div>
      <span class="grow"></span><button class="btn ghost" id="ieAll">Отметить все найденными</button><button class="btn ghost" id="iePrint">Печать описи</button></div>
    <div class="note-box">Отметьте каждую единицу: «найдено» или «не найдено». Если место или состояние отличаются от карточки, это запишется как расхождение, и карточка обновится. Неотмеченные строки не проводятся.</div>
    <div class="pbody" style="margin-top:8px">${list.length ? `<table class="tbl compact ie-t"><thead><tr><th style="width:190px">Проверка</th><th>Инв. №</th><th>Оборудование</th><th>Где находится</th><th>Состояние</th><th>Последняя проверка</th><th>Комментарий</th></tr></thead><tbody>${
      list.map(e => `<tr data-ie="${esc(e.id)}" data-q="${esc(`${e.inv_number} ${e.name} ${e.serial || ""} ${e.model || ""}`.toLowerCase())}">
        <td><div class="seg ie-f"><button data-f="1">Найдено</button><button data-f="0">Нет</button></div></td><td><b>${esc(e.inv_number)}</b></td>
        <td class="lnk" data-open="${esc(e.id)}"><b>${esc(e.name)}</b><small class="muted" style="display:block">${esc([e.model, e.serial && "S/N " + e.serial].filter(Boolean).join(" · "))}</small></td>
        <td><select class="input sm-sel" data-loc><option value="">${esc(e.location_id ? "— как в карточке —" : e.location || "— не указано —")}</option>${pl.map(p => `<option value="${esc(p.id)}" ${p.id === e.location_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></td>
        <td><select class="input sm-sel" data-cond>${Object.entries(C).map(([k, t]) => `<option value="${k}" ${k === e.condition ? "selected" : ""}>${t}</option>`).join("")}</select></td>
        <td class="muted">${e.last_inventory_date ? fmtDate(e.last_inventory_date) : "не проводилась"}</td><td><input class="input" data-com placeholder="если есть"></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Оборудования нет</b><span>Его добавляют в разделе «Оборудование»</span></div>`}</div>
    <div class="inv-foot"><span class="muted" id="ieCnt"></span><span class="grow"></span><button class="btn" id="ieOk" ${list.length ? "" : "disabled"}>Провести инвентаризацию</button></div><div class="auth-err" id="ieErr"></div></div>`;
  const count = () => { const t = $$("tr[data-ie]", body), f = t.filter(tr => tr.dataset.found === "1").length, n = t.filter(tr => tr.dataset.found === "0").length;
    $("#ieCnt").textContent = f + n ? `Проверено: ${f + n} из ${t.length} · найдено: ${f}${n ? ` · не найдено: ${n}` : ""}` : `Всего: ${t.length}`; };
  const mark = (tr, v) => { tr.dataset.found = v; $$(".ie-f button", tr).forEach(b => b.classList.toggle("on", b.dataset.f === v));
    $$("select", tr).forEach(s => s.disabled = v === "0"); tr.classList.toggle("ie-miss", v === "0"); count(); };
  $$("tr[data-ie]", body).forEach(tr => $$(".ie-f button", tr).forEach(b => b.onclick = () => mark(tr, tr.dataset.found === b.dataset.f ? "" : b.dataset.f)));
  $$("[data-open]", body).forEach(td => td.onclick = () => openEquipment(td.dataset.open, "inventory"));
  const il = $("#ieLoc"); if (il) il.onchange = () => { S.invEqLoc = il.value; invEquipment(); };
  $("#ieAll").onclick = () => $$("tr[data-ie]", body).filter(tr => !tr.hidden && !tr.dataset.found).forEach(tr => mark(tr, "1"));
  const q = $("#ieQ");
  q.oninput = () => { const s = q.value.trim().toLowerCase(); $$("tr[data-ie]", body).forEach(tr => tr.hidden = !!s && !tr.dataset.q.includes(s)); };
  q.onkeydown = async e => {  // the QR of a label: the row is marked «найдено»
    if (e.key !== "Enter" || !q.value.trim()) return;
    e.preventDefault();
    let id = null; try { id = (await api.stock_scan(q.value.trim())).equipment_id; } catch (x) { /* not a code */ }
    const tr = id && $(`tr[data-ie="${id}"]`, body);
    if (tr) { q.value = ""; q.oninput(); mark(tr, "1"); tr.scrollIntoView({block: "center"}); tr.classList.add("ie-hit"); setTimeout(() => tr.classList.remove("ie-hit"), 1200); }
    else toast(id ? "Это оборудование не в выбранном месте" : "Не нашли оборудование по этому коду", true);
  };
  $("#iePrint").onclick = () => printEquipmentSheet(list, il && il.value && il.value !== "-" ? pl.find(p => p.id === il.value).name : "");
  $("#ieOk").onclick = async () => {
    const lines = $$("tr[data-ie]", body).filter(tr => tr.dataset.found).map(tr => { const f = {id: tr.dataset.ie, found: tr.dataset.found === "1", comment: $("[data-com]", tr).value};
      if (f.found) { const l = $("[data-loc]", tr).value; if (l) f.location_id = l; f.condition = $("[data-cond]", tr).value; } return f; });
    try { const r = await api.equipment_inventory_batch(lines);
      toast(`Проведено: ${r.done}${r.diffs ? ` · с расхождениями: ${r.diffs}` : ""}${r.not_found ? ` · не найдено: ${r.not_found}` : ""}`); invEquipment(); }
    catch (e) { $("#ieErr").textContent = errText(e); }
  };
  count();
}

/** «Инвентаризация → История»: the documents of the materials' counts and the checks of the equipment. */
async function invHistory() {
  const mat = canAny("stock_view", "stock_edit"), eq = canAny("equipment", "stock_view");
  const [docs, evs] = await Promise.all([mat ? api.stock_docs("inventory") : [], eq ? api.equipment_inventory_log() : []]);
  const body = $("#stockBody");
  body.innerHTML = `<div class="inv-hist">${mat ? `<section><h3 class="sub-h">Материалы <span class="muted">${docs.length}</span></h3>${docs.length ? `<table class="tbl compact"><thead><tr><th>Дата</th><th>№</th>${hasPlaces() ? "<th>Место</th>" : ""}<th class="num">Расхождений</th><th class="num">Сумма разницы</th><th>Сотрудник</th></tr></thead><tbody>${
      docs.map(d => `<tr data-d="${esc(d.id)}" class="lnk-row"><td>${fmtDate(d.date)}</td><td class="lnk"><b>${esc(d.number || "—")}</b>${d.nodoc ? ' <span class="pill dx-nodoc">без документа</span>' : ""}</td>${hasPlaces() ? `<td class="muted">${esc(d.location_name || "")}</td>` : ""}
        <td class="num">${d.lines}</td><td class="num">${d.total ? money(d.total) : "—"}</td><td class="muted">${esc(d.user_name || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted">Инвентаризаций материалов ещё не было</div>`}</section>` : ""}
    ${eq ? `<section><h3 class="sub-h">Оборудование <span class="muted">${evs.length}</span></h3>${evs.length ? `<table class="tbl compact"><thead><tr><th>Дата</th><th>Инв. №</th><th>Оборудование</th><th>Результат</th><th>Сотрудник</th></tr></thead><tbody>${
      evs.map(x => `<tr data-e="${esc(x.equipment_id)}" class="lnk-row"><td>${fmtDate(x.date)}</td><td><b>${esc(x.inv_number || "")}</b></td><td class="lnk">${esc(x.name)}</td>
        <td class="${!x.found ? "bad-t" : x.diffs.length ? "warn-t" : "ok-t"}">${!x.found ? "Не найдено" : x.diffs.length ? "Расхождения: " + esc(x.diffs.join("; ")) : "Найдено, всё совпадает"}</td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted">Оборудование ещё не проверялось</div>`}</section>` : ""}</div>`;
  $$("tr[data-d]", body).forEach(tr => tr.onclick = () => openStockDocView(tr.dataset.d));
  $$("tr[data-e]", body).forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e, "inventory"));
}

/* ------------------------------------------------------- documents */
async function stockDocs() {
  const kind = S.stockDocKind || "";
  const rows = await api.stock_docs(kind || null);
  $("#stockBody").innerHTML = `<div class="tab-tools"><div class="seg" id="sdKind">${[["", "Все"], ["receipt", "Приход"], ["writeoff", "Списание"], ["inventory", "Инвентаризация"], ["visit", "По приёмам"], ["transfer", "Перемещения"]].map(([k, t]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${t}</button>`).join("")}</div></div>
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Документ</th><th>№</th><th>Поставщик / причина</th><th class="num">Строк</th><th class="num">Сумма</th><th>Сотрудник</th></tr></thead><tbody>${
      rows.map(d => `<tr data-d="${esc(d.id)}"><td>${fmtDate(d.date)}</td><td class="lnk"><b>${esc(DOC_KIND[d.kind] || d.kind)}</b>${d.nodoc ? " " + '<span class="pill dx-nodoc">без документа</span>' : ""}</td><td>${esc(d.number || "—")}</td>
        <td>${esc(d.kind === "transfer" ? `${d.location_name} → ${d.to_location_name}` : d.supplier_name || d.reason || "")}${hasPlaces() && d.kind !== "transfer" && d.location_id ? ` <small class="muted">· ${esc(d.location_name)}</small>` : ""}</td><td class="num">${d.lines}</td><td class="num">${d.total ? money(d.total) : "—"}</td><td class="muted">${esc(d.user_name || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Документов пока нет</b></div>`}</div>`;
  $$("#sdKind button").forEach(b => b.onclick = () => { S.stockDocKind = b.dataset.k; stockDocs(); });
  $$("#stockBody tr[data-d]").forEach(tr => tr.onclick = () => openStockDocView(tr.dataset.d));
}

async function openStockDocView(id) {
  const d = await api.stock_doc(id);
  modal(`<div class="m-h"><h3>${esc(DOC_KIND[d.kind] || "Документ")} ${d.number ? "№ " + esc(d.number) : ""} от ${fmtDate(d.date)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${d.supplier_name ? `<div>Поставщик: <b>${esc(d.supplier_name)}</b></div>` : ""}${d.reason && d.kind === "writeoff" ? `<div>Причина: <b>${esc(d.reason)}</b></div>` : ""}
      ${d.kind === "transfer" ? `<div>Откуда: <b>${esc(d.location_name)}</b> → куда: <b>${esc(d.to_location_name)}</b></div>` : d.kind === "visit" ? `<div>${esc(d.reason)} · место: <b>${esc(d.location_name)}</b></div>` : hasPlaces() ? `<div class="muted">Место: ${esc(d.location_name)}</div>` : ""}
      <table class="tbl compact"><thead><tr><th>Материал</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${
        d.moves.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${x.qty > 0 && d.kind === "inventory" ? "+" : ""}${qtyFmt(d.kind === "writeoff" || d.kind === "visit" ? -x.qty : x.qty, x.unit)}</td><td class="num">${money(x.price)}</td><td class="num">${money(Math.abs(x.qty) * x.price)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Расхождений не было</td></tr>`}</tbody></table>
      ${d.comment ? `<div class="muted">${esc(d.comment)}</div>` : ""}</div>
    <div class="m-f"><span class="muted">Оформил: ${esc(d.user_name || "—")}, ${fmtDT(d.created_at)}${d.nodoc ? " · без документов, не печатается" : ""}</span><button class="btn ghost" data-close>Закрыть</button>${d.nodoc ? "" : `<button class="btn" id="sdPrint">Печать</button>`}</div>`, {wide: true});
  const sp = $("#sdPrint"); if (sp) sp.onclick = () => printStockDoc(id);
}

/* ------------------------------------------------------- moves */
async function stockMoves() {
  const f = S.moveF || {from: addDays(iso(new Date()), -30), to: iso(new Date()), kind: "", location: null};
  S.moveF = f;
  const rows = await api.stock_moves(f);
  $("#stockBody").innerHTML = `<div class="tab-tools"><input type="date" class="input" id="mvFrom" value="${f.from}"> — <input type="date" class="input" id="mvTo" value="${f.to}">
      <select class="input sm-sel" id="mvKind"><option value="">Все операции</option>${Object.entries(STK.move_kinds).map(([k, t]) => `<option value="${k}" ${k === f.kind ? "selected" : ""}>${t}</option>`).join("")}</select>
      ${hasPlaces() ? `<select class="input sm-sel" id="mvLoc"><option value="*">Все места</option>${STK.locations.map(l => `<option value="${esc(l.id)}" ${l.id === f.location ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>` : ""}
      <span class="muted">Списание по услугам происходит само, когда выставлен счёт или подтверждён приём («По приёмам»)</span></div>
    <div class="pbody" style="margin-top:8px">${movesTable(rows)}</div>`;
  const upd = () => { const l = $("#mvLoc"); S.moveF = {from: $("#mvFrom").value, to: $("#mvTo").value, kind: $("#mvKind").value,
    location: l && l.value !== "*" ? l.value : null}; stockMoves(); };
  $("#mvFrom").onchange = upd; $("#mvTo").onchange = upd; $("#mvKind").onchange = upd;
  const ml = $("#mvLoc"); if (ml) ml.onchange = upd;
}

/* ------------------------------------------------------- norms */
async function stockNorms() {
  const [svc, norms] = await Promise.all([api.services(""), api.norms()]);
  const by = {}; norms.forEach(n => (by[n.service_id] ||= []).push(n));
  const q = (S.normQ || "").toLowerCase();
  const list = svc.filter(s => !q || `${s.code} ${s.title}`.toLowerCase().includes(q));
  $("#stockBody").innerHTML = `<div class="tab-tools"><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="nQ" placeholder="Услуга" value="${esc(S.normQ || "")}"></div>
      <span class="muted">Какие материалы и сколько уходит на одну услугу (техкарта). Материалы списываются сами по счёту и по приёмам Dentist Plus («По приёмам»).</span></div>
    <div class="pbody" style="margin-top:8px"><table class="tbl"><thead><tr><th>Услуга</th><th>Материалы на одну услугу</th><th class="num" title="По последним ценам закупки">Материалы, ₽</th></tr></thead><tbody>${
      list.map(s => `<tr data-s="${esc(s.id)}"><td class="lnk"><b>${esc(s.title)}</b><small class="muted" style="display:block">${esc(s.code || "")}</small></td>
        <td>${(by[s.id] || []).map(n => `<span class="chip">${esc(n.name)} · ${qtyFmt(n.qty, n.unit)}</span>`).join(" ") || '<span class="muted">не заданы</span>'}</td>
        <td class="num">${(by[s.id] || []).length ? money((by[s.id] || []).reduce((a, n) => a + n.qty * (n.price || 0), 0)) : "—"}</td></tr>`).join("")}</tbody></table></div>`;
  let t; $("#nQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.normQ = e.target.value; stockNorms().then(() => { const i = $("#nQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  if (can("stock_edit")) $$("#stockBody tr[data-s]").forEach(tr => tr.onclick = () => editNorms(svc.find(s => s.id === tr.dataset.s), by[tr.dataset.s] || []));
}

async function editNorms(svc, cur) {
  const mats = await api.materials("");
  const st = {lines: cur.map(n => ({material_id: n.material_id, qty: n.qty}))};
  if (!st.lines.length) st.lines.push({material_id: "", qty: ""});
  const box = modal(`<div class="m-h"><h3>Нормы: ${esc(svc.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted">Расход на одну услугу. Если в счёте услуга указана 2 раза, спишется вдвое больше.</div>
      <table class="tbl compact"><thead><tr><th>Материал</th><th class="num" style="width:140px">Количество</th><th></th></tr></thead><tbody id="nLines"></tbody></table>
      <div><button class="btn ghost small" id="nAdd">+ Материал</button></div><div class="auth-err" id="nErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="nOk">Сохранить</button></div>`);
  const draw = () => {
    $("#nLines").innerHTML = st.lines.map((l, i) => `<tr><td><select class="input" data-i="${i}" data-f="material_id"><option value="">—</option>${mats.map(m => `<option value="${esc(m.id)}" ${m.id === l.material_id ? "selected" : ""}>${esc(m.name)} (${esc(m.unit)})</option>`).join("")}</select></td>
      <td><input class="input num" type="number" step="any" min="0" data-i="${i}" data-f="qty" value="${esc(l.qty)}"></td><td><button class="linkbtn" data-rm="${i}">убрать</button></td></tr>`).join("");
    $$("#nLines [data-f]").forEach(el => el.onchange = () => { st.lines[+el.dataset.i][el.dataset.f] = el.value; });
    $$("#nLines [data-rm]").forEach(b => b.onclick = () => { st.lines.splice(+b.dataset.rm, 1); draw(); });
  };
  draw();
  $("#nAdd", box).onclick = () => { st.lines.push({material_id: "", qty: ""}); draw(); };
  $("#nOk", box).onclick = async () => {
    try { await api.save_norms(svc.id, st.lines.filter(l => l.material_id && +l.qty > 0)); closeModal(); toast("Нормы сохранены"); stockNorms(); }
    catch (e) { $("#nErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------------- suppliers */
async function stockSuppliers() {
  const rows = await api.suppliers();
  $("#stockBody").innerHTML = `<div class="tab-tools"><span class="grow"></span><button class="btn" id="supNew">Добавить поставщика</button></div>
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Поставщик</th><th>Телефон</th><th>ИНН</th><th>Комментарий</th></tr></thead><tbody>${
      rows.map(s => `<tr data-s="${esc(s.id)}"><td class="lnk"><b>${esc(s.name)}</b></td><td>${esc(s.phone)}</td><td>${esc(s.inn)}</td><td class="muted">${esc(s.comment)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Поставщиков пока нет</b></div>`}</div>`;
  $("#supNew").onclick = () => editSupplier({});
  $$("#stockBody tr[data-s]").forEach(tr => tr.onclick = () => editSupplier(rows.find(s => s.id === tr.dataset.s)));
}
function editSupplier(s) {
  const box = modal(`<div class="m-h"><h3>${s.id ? "Поставщик" : "Новый поставщик"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Название*<input class="input" id="sN" value="${esc(s.name || "")}" autofocus></label>
      <div class="grid2"><label class="fl">Телефон<input class="input" id="sP" value="${esc(s.phone || "")}"></label><label class="fl">ИНН<input class="input" id="sI" value="${esc(s.inn || "")}"></label></div>
      <label class="fl">Комментарий<input class="input" id="sC" value="${esc(s.comment || "")}"></label><div class="auth-err" id="sErr"></div></div>
    <div class="m-f">${s.id ? `<button class="btn ghost small danger" id="sDel">Удалить</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="sOk">Сохранить</button></div>`);
  $("#sOk", box).onclick = async () => {
    try { await api.save_supplier({id: s.id, name: $("#sN").value, phone: $("#sP").value, inn: $("#sI").value, comment: $("#sC").value}); closeModal(); stockSuppliers(); }
    catch (e) { $("#sErr").textContent = errText(e); }
  };
  const d = $("#sDel", box); if (d) d.onclick = async () => { if (await ask("Удалить поставщика?", {danger: true, ok: "Удалить", text: "Накладные этого поставщика сохранятся."})) { await api.delete_supplier(s.id); closeModal(); stockSuppliers(); } };
}

/* ------------------------------------------------------- equipment */
/* stockEquipment — «Реестр оборудования»: stock-eqsection.js (3.15) */

/** 3.14 «Оборудование → ТО и ремонт»: what is due for service, what is in repair, and every service and repair with its cost. */
async function eqServiceTab() {
  const f = S.eqSvcF || {};
  const r = await api.equipment_service_log(f.from || null, f.to || null);
  S.eqSvcF = {from: r.from, to: r.to};
  const body = $("#stockBody");
  body.innerHTML = eqStatRow() + `<div class="eq-svc">
    <section class="eq-svc-due"><h3 class="sub-h">Ближайшее ТО <span class="muted">просрочено и на 60 дней вперёд</span></h3>${r.due.length ? `<table class="tbl compact"><thead><tr><th>Дата ТО</th><th>Инв. №</th><th>Оборудование</th><th>Где</th><th>Статус</th></tr></thead><tbody>${
      r.due.map(x => `<tr data-e="${esc(x.id)}" class="lnk-row"><td class="${x.due ? "bad-t" : x.days <= 14 ? "warn-t" : ""}"><b>${fmtDate(x.next_service)}</b><small style="display:block">${x.due ? (x.days < 0 ? `просрочено на ${-x.days} ${plural(-x.days, "день", "дня", "дней")}` : "сегодня") : `через ${x.days} ${plural(x.days, "день", "дня", "дней")}`}</small></td>
        <td><b>${esc(x.inv_number)}</b></td><td class="lnk">${esc(x.name)}</td><td class="muted">${esc(x.location || "")}</td><td>${esc(x.status_title)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted">В ближайшие 60 дней ТО не назначено</div>`}
      ${r.in_repair.length ? `<h3 class="sub-h">Сейчас в ремонте <span class="muted">${r.in_repair.length}</span></h3><div class="eq-svc-chips">${r.in_repair.map(x => `<button class="chip" data-e="${esc(x.id)}">${esc(x.inv_number)} · ${esc(x.name)}</button>`).join("")}</div>` : ""}</section>
    <section><div class="tab-tools"><h3 class="sub-h" style="margin:0">Журнал ТО и ремонтов</h3><span class="grow"></span><input type="date" class="input" id="svF" value="${r.from}"> — <input type="date" class="input" id="svT" value="${r.to}"></div>
      <div class="stat-row"><div class="stat"><span>Записей</span><b>${r.events.length}</b></div><div class="stat"><span>Плановое ТО</span><b>${money(r.cost_service)}</b></div><div class="stat"><span>Ремонт</span><b>${money(r.cost_repair)}</b></div><div class="stat"><span>Всего затрат</span><b>${money(r.cost)}</b></div></div>
      ${r.events.length ? `<table class="tbl compact"><thead><tr><th>Дата</th><th>Вид</th><th>Оборудование</th><th>Что сделано</th><th class="num">Стоимость</th><th>Сотрудник</th></tr></thead><tbody>${
        r.events.map(x => `<tr data-e="${esc(x.equipment_id)}" class="lnk-row"><td>${fmtDate(x.date)}</td><td><span class="mv mv-${esc(x.kind)}">${esc(x.kind_title)}</span></td><td class="lnk"><b>${esc(x.inv_number || "")}</b> ${esc(x.name)}</td>
          <td class="wrap">${esc(x.text || "")}</td><td class="num">${x.cost ? money(x.cost) : "—"}</td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody></table>`
        : `<div class="muted">За период ТО и ремонтов не записано. Запись делают в карточке оборудования → «Обслуживание».</div>`}
      <div class="muted eqc-hint">Затраты на ТО и ремонт попадают в финансовый отчёт, когда их оплату записывают в расходы («Ремонт и обслуживание»).</div></section></div>`;
  $$("[data-e]", body).forEach(el => el.onclick = () => openEquipment(el.dataset.e, "service"));
  const upd = () => { S.eqSvcF = {from: $("#svF").value, to: $("#svT").value}; eqServiceTab(); };
  $("#svF").onchange = upd; $("#svT").onchange = upd;
}

/** 3.14 «Оборудование → Выбывшее»: what was written off, sold or given back, with the act and (with «Бухгалтерия») the money. */
async function eqDisposedTab() {
  const rows = (await api.equipment_list("", true)).filter(e => e.status === "written_off");
  const mon = !!STK.eq_money;
  const K = {writeoff: "Списание", sale: "Продажа", return: "Возврат владельцу"};
  const body = $("#stockBody");
  body.innerHTML = `<div class="pbody">${rows.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Инв. №</th><th>Оборудование</th><th>Вид</th><th>Основание</th>${mon ? `<th class="num">Стоимость</th><th class="num">Остаточная</th><th class="num">Продажа</th>` : ""}<th></th></tr></thead><tbody>${
      rows.map(e => `<tr data-e="${esc(e.id)}" class="lnk-row"><td>${e.writeoff_date ? fmtDate(e.writeoff_date) : "—"}</td><td><b>${esc(e.inv_number)}</b></td><td class="lnk"><b>${esc(e.name)}</b><small class="muted" style="display:block">${esc([e.model, e.serial && "S/N " + e.serial].filter(Boolean).join(" · "))}</small></td>
        <td>${esc(K[e.disposal_kind || "writeoff"] || "")}${e.writeoff_act ? `<small class="muted" style="display:block">акт № ${esc(e.writeoff_act)}</small>` : ""}</td><td class="wrap muted">${esc(e.writeoff_reason || "")}</td>
        ${mon ? `<td class="num">${money(e.price)}</td><td class="num">${money(e.residual || 0)}</td><td class="num">${e.disposal_kind === "sale" ? money(e.disposal_amount || 0) : "—"}</td>` : ""}
        <td>${(e.disposal_kind || "writeoff") === "writeoff" ? `<button class="icon-btn" data-act="${esc(e.id)}" title="Печать акта списания">${PRINT_ICON}</button>` : ""}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty"><b>Выбывшего оборудования нет</b><span>Выбытие оформляют в карточке: «Оформить выбытие»</span></div>`}</div>
    ${mon && rows.length ? `<div class="muted eqc-hint">В финансовом отчёте выбытие идёт в месяц выбытия: остаточная стоимость минус сумма продажи.</div>` : ""}`;
  $$("tr[data-e]", body).forEach(tr => tr.onclick = ev => { if (!ev.target.closest("[data-act]")) openEquipment(tr.dataset.e); });
  $$("[data-act]", body).forEach(b => b.onclick = async () => { const e = await api.equipment(b.dataset.act); printEquipmentAct(e); });
}

/* editEquipment, openEquipment and the disposal: stock-eqcard.js (3.13 «Карточка оборудования») */

/* ------------------------------------------------------- printing */
async function clinicHead() {
  const c = (await ref()).clinic || {};
  return `<div class="pr-head"><b>${esc(c.name || (S.status.brand || {}).name || "")}</b>${c.address ? `<br>${esc(c.address)}` : ""}${c.inn ? `<br>ИНН ${esc(c.inn)}` : ""}</div>`;
}
function signLines(names) { return `<div class="pr-sign">${names.map(n => `<div><span>${esc(n.role)}</span><i></i><small>${esc(n.name || "")}</small></div>`).join("")}</div>`; }
async function printStockDoc(id) {
  const d = await api.stock_doc(id);
  const head = await clinicHead();
  const c = (await ref()).clinic || {};
  const rows = d.moves.map((x, i) => { const q = d.kind === "writeoff" || d.kind === "visit" ? -x.qty : x.qty;
    return `<tr><td>${i + 1}</td><td>${esc(x.name)}</td><td>${esc(x.unit)}</td><td>${qtyFmt(q)}</td><td>${money(x.price)}</td><td>${money(Math.abs(x.qty) * x.price)}</td></tr>`; }).join("");
  const total = d.moves.reduce((a, x) => a + Math.abs(x.qty) * x.price, 0);
  $("#printArea").innerHTML = `${head}<h2 style="text-align:center">${esc(DOC_KIND[d.kind])} № ${esc(d.number || "")} от ${fmtDate(d.date)}</h2>
    ${d.supplier_name ? `<p>Поставщик: ${esc(d.supplier_name)}${d.supplier_inn ? ", ИНН " + esc(d.supplier_inn) : ""}</p>` : ""}${d.kind === "writeoff" ? `<p>Причина списания: ${esc(d.reason)}</p>` : ""}${d.kind === "transfer" ? `<p>Откуда: ${esc(d.location_name)} → куда: ${esc(d.to_location_name)}</p>` : d.kind === "visit" ? `<p>${esc(d.reason)}</p>` : ""}
    <table><tr><th>№</th><th>Наименование</th><th>Ед.</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr>${rows}<tr><td colspan="5" style="text-align:right"><b>Итого</b></td><td><b>${money(total)}</b></td></tr></table>
    ${d.kind === "writeoff" ? signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Член комиссии"}, {role: "Утверждаю, руководитель", name: c.director || ""}])
      : d.kind === "transfer" ? signLines([{role: "Отпустил", name: d.user_name}, {role: "Принял"}]) : d.kind === "visit" ? signLines([{role: "Ответственный", name: d.user_name}])
      : signLines([{role: "Принял", name: d.user_name}, {role: "Сдал (поставщик)"}])}`;
  window.print();
}
async function printBalance(byDocs) {
  /* byDocs (2.14.1, «Бухгалтерия»): only the documented moves — the balance for the accountant */
  const rows = (S.stockRows || []).map(m => byDocs ? {...m, balance: m.balance_doc, value: m.value_doc} : m);
  $("#printArea").innerHTML = `${await clinicHead()}<h2>Остатки материалов на ${fmtDT(nowLocal())}</h2>
    <table><tr><th>Код</th><th>Материал</th><th>Остаток</th><th>Минимум</th><th>Цена</th><th>Сумма</th></tr>${rows.map(m => `<tr><td>${esc(m.code)}</td><td>${esc(m.name)}</td><td>${qtyFmt(m.balance, m.unit)}</td><td>${m.min_qty ? qtyFmt(m.min_qty) : ""}</td><td>${money(m.price)}</td><td>${money(m.value)}</td></tr>`).join("")}
    <tr><td colspan="5" style="text-align:right"><b>Итого</b></td><td><b>${money(rows.reduce((a, m) => a + (m.balance > 0 ? m.value : 0), 0))}</b></td></tr></table>`;
  window.print();
}
async function printInventorySheet(mats, place) {
  const where = place != null && hasPlaces() ? (STK.locations.find(l => l.id === place) || {}).name || "" : "";
  $("#printArea").innerHTML = `${await clinicHead()}<h2>Инвентаризационная опись материалов от ${fmtDate(iso(new Date()))}</h2>${where ? `<p>Место хранения: ${esc(where)}</p>` : ""}
    <table><tr><th>№</th><th>Материал</th><th>Ед.</th><th>По учёту</th><th style="width:110px">Фактически</th><th style="width:110px">Разница</th></tr>${mats.map((m, i) => `<tr><td>${i + 1}</td><td>${esc(m.name)}</td><td>${esc(m.unit)}</td><td>${qtyFmt(m.balance)}</td><td></td><td></td></tr>`).join("")}</table>
    ${signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Материально ответственное лицо"}])}`;
  window.print();
}
/** 3.14: the inventory list of the equipment — the commission ticks what it found. */
async function printEquipmentSheet(list, where) {
  $("#printArea").innerHTML = `${await clinicHead()}<h2>Инвентаризационная опись основных средств от ${fmtDate(iso(new Date()))}</h2>${where ? `<p>Место: ${esc(where)}</p>` : ""}
    <table><tr><th>№</th><th>Инв. №</th><th>Наименование</th><th>Модель / серийный №</th><th>Место по учёту</th><th style="width:80px">Найдено</th><th style="width:160px">Примечание</th></tr>${
      list.map((e, i) => `<tr><td>${i + 1}</td><td>${esc(e.inv_number)}</td><td>${esc(e.name)}</td><td>${esc([e.model, e.serial].filter(Boolean).join(" / "))}</td><td>${esc(e.location || "")}</td><td></td><td></td></tr>`).join("")}</table>
    ${signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Член комиссии"}, {role: "Материально ответственное лицо"}])}`;
  window.print();
}
async function printEquipmentAct(e) {
  const c = (await ref()).clinic || {};
  const com = (() => { try { return JSON.parse(e.writeoff_commission || "[]"); } catch (x) { return []; } })();
  $("#printArea").innerHTML = `${await clinicHead()}
    <div class="pr-approve">УТВЕРЖДАЮ<br>Руководитель ____________ ${esc(c.director || "")}<br>«___» ____________ 20__ г.</div>
    <h2 style="text-align:center">АКТ № ${esc(e.writeoff_act || "")}<br>о списании объекта основных средств</h2>
    <p style="text-align:center">от ${fmtDate(e.writeoff_date)}</p>
    <p>Комиссия в составе: председатель — ${esc(com[0] || "")}; члены комиссии — ${esc(com.slice(1).join("; "))} — осмотрела указанный ниже объект и установила, что он подлежит списанию.</p>
    <table><tr><th>Наименование</th><th>Инв. №</th><th>Модель / серийный №</th><th>Дата покупки</th><th>Стоимость</th><th>Остаточная стоимость</th></tr>
      <tr><td>${esc(e.name)}</td><td>${esc(e.inv_number)}</td><td>${esc([e.model, e.serial].filter(Boolean).join(" / "))}</td><td>${e.purchase_date ? fmtDate(e.purchase_date) : ""}</td><td>${money(e.price)}</td><td>${money(e.residual)}</td></tr></table>
    <p><b>Причина списания:</b> ${esc(e.writeoff_reason)}</p>
    <p><b>Заключение комиссии:</b> объект к дальнейшему использованию непригоден, подлежит списанию и утилизации.</p>
    ${signLines(com.map((n, i) => ({role: i ? "Член комиссии" : "Председатель комиссии", name: n})))}`;
  window.print();
}
