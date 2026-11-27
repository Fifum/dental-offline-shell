"use strict";
/* 3.13 «Карточка оборудования» — a screen inside «Склад → Оборудование» (not a dialog), after the mockup the clinic chose:
   the photo gallery, the condition, the inventory number, the place, the money tiles (only with «Бухгалтерия» — the server
   does not even send them otherwise), the tabs Основное / Финансы / Обслуживание / Документы / Инвентаризация / История, the
   inventory label with its QR, quick actions, the next service and the documents. */
const EQI = {
  print: '<svg viewBox="0 0 24 24"><path d="M7 9V3.5h10V9M7 17H4.5V10.5a1.5 1.5 0 0 1 1.5-1.5h12a1.5 1.5 0 0 1 1.5 1.5V17H17"/><rect x="7" y="14" width="10" height="6.5" rx="1"/></svg>',
  pen: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-4-4L4 16z"/><path d="m14 6 4 4"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="12" cy="5.5" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="12" cy="18.5" r="1.3"/></svg>',
  expand: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>',
  okc: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.8 2.7L16.2 9.5"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17h.01"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12l9 4.5 9-4.5M3 16l9 4.5 9-4.5"/></svg>',
  bank: '<svg viewBox="0 0 24 24"><path d="M3.5 9.5 12 4.5l8.5 5M5 9.5V18M9.5 9.5V18M14.5 9.5V18M19 9.5V18M3.5 20h17"/></svg>',
  coins: '<svg viewBox="0 0 24 24"><ellipse cx="9" cy="7" rx="5.5" ry="2.5"/><path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5S14.5 12.4 14.5 11V7"/><path d="M9.5 15.5c.6 1 2.6 1.8 5 1.8 3 0 5.5-1.1 5.5-2.5v-4c0-1.2-1.8-2.2-4.3-2.5M20 14.8v3.7c0 1.4-2.5 2.5-5.5 2.5-2.4 0-4.4-.7-5.2-1.7"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M4 19.5h16M6.5 16v-4M10.5 16V9M14.5 16v-5M18.5 16V6"/></svg>',
  cal: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4M7.5 14h2M11 14h2M14.5 14h2M7.5 17h2M11 17h2"/></svg>',
  sigma: '<svg viewBox="0 0 24 24"><path d="M17.5 5h-11l6 7-6 7h11"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8h.01"/></svg>',
  wallet: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="6.5" rx="7" ry="2.8"/><path d="M5 6.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5M5 11.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5"/></svg>',
  wrench: '<svg viewBox="0 0 24 24"><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-5 4 4 0 0 1 0 3z"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 12.5h6M9 16h6"/></svg>',
  check: '<svg viewBox="0 0 24 24"><rect x="4.5" y="4.5" width="15" height="16" rx="2.5"/><path d="M9 3v3h6V3M8.5 13l2.5 2.5 4.5-5"/></svg>',
  hist: '<svg viewBox="0 0 24 24"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5"/><path d="M3.5 4v4.5H8M12 7.5V12l3 2"/></svg>',
  camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l1.6-2.5h6.8L17 8h3v11H4z"/><circle cx="12" cy="13.2" r="3.4"/></svg>',
  move: '<svg viewBox="0 0 24 24"><path d="M4 8.5h15l-3.5-3.5M20 15.5H5l3.5 3.5"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 19.5h14"/></svg>',
  chev: '<svg viewBox="0 0 24 24"><path d="m9.5 6 6 6-6 6"/></svg>',
  chevd: '<svg viewBox="0 0 24 24"><path d="m6 9.5 6 6 6-6"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 5.5 8.5 12l6.5 6.5"/></svg>',
  heart: '<svg viewBox="0 0 24 24"><path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.2a4.3 4.3 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z"/><path d="M7 12h2.5l1.5-2.5 2 4 1.5-1.5H17"/></svg>',
  ph: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m4 17 5-4.5 4 3.5 3-2.5 4 3.5"/></svg>',
};
const EQ = {id: null, tab: "main", data: null, gal: 0, allDocs: false};
const eqMonth = s => { if (!s) return "—"; const [y, m] = s.split("-").map(Number); return `${["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][m - 1]} ${y}`; };
const eqLongDate = s => { if (!s) return "—"; const [y, m, d] = s.split("-").map(Number); return `${d} ${["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"][m - 1]} ${y}`; };
const eqCondCls = c => c === "ok" ? "ok" : c === "service" ? "warn" : "bad";

/** Opens the card of a piece of equipment in place of the list (from anywhere in the stock). */
async function openEquipment(id, tab) {
  if ($("#modal") && !$("#modal").hidden) closeModal();
  EQ.id = id; EQ.tab = tab || "main"; EQ.gal = 0; EQ.allDocs = false;
  S.eqOpen = id; S.matOpen = null;
  // 3.14: the card belongs to «Оборудование → Оборудование»; from elsewhere (a scan, inventory, a task) the section opens first
  if (S.view !== "equipment" || $("#view-stock").hidden || S.stockTab !== "equipment") return stockGo("equipment", "equipment");
  return eqCard();
}
function eqClose() { S.eqOpen = null; EQ.id = null; stockEquipment(); }

async function eqCard() {
  const body = $("#stockBody");
  let r;
  try { r = await api.equipment_card(EQ.id); } catch (e) { toast(errText(e), true); S.eqOpen = null; return stockEquipment(); }
  EQ.data = r;
  const e = r.e, c = r.can, money = !!e.money, off = e.status === "written_off";
  if (!money && EQ.tab === "finance") EQ.tab = "main";
  const a = e.amort || {};
  const tile = (ic, t, v, cls = "") => `<div class="eqc-tile ${cls}"><i>${ic}</i><span>${t}</span><b>${v}</b></div>`;
  const tabs = [["main", EQI.info, "Основное"], ...(money ? [["finance", EQI.wallet, "Финансы"]] : []), ["service", EQI.wrench, "Обслуживание"],
    ["docs", EQI.doc, "Документы"], ["inventory", EQI.check, "Инвентаризация"], ["history", EQI.hist, "История"]];
  const acts = c.edit ? [["photo", EQI.camera, "Добавить фотографию"], ["move", EQI.move, "Переместить оборудование"],
    e.status === "repair" ? ["fixed", EQI.wrench, "Вернуть из ремонта"] : ["repair", EQI.wrench, "Отправить на ремонт"],
    ["inventory", EQI.check, "Провести инвентаризацию"], ["replace", EQI.cal, "Запланировать замену"], ["dispose", EQI.trash, "Оформить выбытие"]] : [];
  const mainKinds = e.doc_kinds.filter(k => k.kind !== "other"), docsShown = EQ.allDocs ? mainKinds : mainKinds.slice(0, 4);
  const photos = e.photos || [];
  body.innerHTML = `<div class="eqc">
    <div class="eqc-crumbs"><button class="eqc-back" id="eqBack" title="К списку оборудования">${EQI.back}</button><button class="linkbtn" id="eqBack2">Оборудование</button>${EQI.chev}<b>Карточка оборудования</b></div>
    <div class="eqc-head"><h2>Карточка оборудования</h2><span class="eqc-chip">${esc(e.inv_number || "—")}</span><span class="grow"></span>
      <button class="btn ghost eqc-hb" id="eqPrintQr">${EQI.print}Печать QR</button>${c.edit ? `<button class="btn ghost eqc-hb" id="eqEdit">${EQI.pen}Редактировать</button>` : ""}
      <button class="icon-btn eqc-more" id="eqMore" title="Ещё">${EQI.more}</button></div>
    ${off ? `<div class="warn-line">${esc(e.status_title)} ${fmtDate(e.writeoff_date)}${e.writeoff_act ? ` по акту № ${esc(e.writeoff_act)}` : ""}: ${esc(e.writeoff_reason || "")}. Карточка только для просмотра.</div>` : ""}
    <div class="eqc-grid"><div class="eqc-main">
      <section class="eqc-card eqc-top ${money ? "" : "no-money"}">
        <div class="eqc-gal"><div class="eqc-photo" id="eqPhoto" ${photos.length ? `data-big="${esc(photos[EQ.gal] || photos[0])}"` : ""}>${EQI.ph}${photos.length ? `<button class="eqc-exp" id="eqExp" title="Открыть фото">${EQI.expand}</button>` : ""}</div>
          <div class="eqc-dots">${photos.length > 1 ? photos.map((p, i) => `<button data-gal="${i}" class="${i === EQ.gal ? "on" : ""}" title="Фото ${i + 1}"></button>`).join("") : c.edit && !photos.length ? `<button class="linkbtn" id="eqPh0">${EQI.camera}Добавить фото</button>` : ""}</div></div>
        <div class="eqc-id"><span class="eqc-badge ${off ? "off" : eqCondCls(e.condition)}">${off ? EQI.info : e.condition === "ok" ? EQI.okc : EQI.warn}${esc(off ? e.status_title : e.condition_title)}</span>${e.status === "repair" && !off ? `<span class="eqc-badge bad">${EQI.wrench}В ремонте</span>` : ""}
          <h3>${esc(e.name)}</h3><div class="eqc-inv">Инвентарный номер: ${esc(e.inv_number || "—")}</div>
          <ul><li>${EQI.pin}${esc(e.location_name || "Место не указано")}</li><li>${EQI.layers}${esc(e.category || "Категория не указана")}</li><li>${EQI.bank}${esc(e.ownership_title)}</li></ul></div>
        ${money ? `<div class="eqc-money"><div class="eqc-tiles">${tile(EQI.coins, "Первоначальная стоимость", eqMoney0(e.price))}${tile(EQI.chart, "Остаточная стоимость", a.on ? eqMoney0(a.residual) : eqMoney0(e.price))}
            ${tile(EQI.cal, "Амортизация в месяц", a.on ? eqMoney0(a.monthly) : "—")}${tile(EQI.sigma, "Накопленная амортизация", a.on ? eqMoney0(a.accumulated) : "—")}</div>
          <div class="eqc-amort"><div><span>Амортизировано</span><b>${a.on ? eqPct(a.percent) : "—"}</b></div><i><u style="width:${a.on ? Math.min(100, a.percent) : 0}%"></u></i>${a.on ? "" : `<small class="muted">Укажите срок полезного использования — в «Редактировать»</small>`}</div></div>` : ""}
      </section>
      <div class="eqc-tabs" id="eqTabs" role="tablist">${tabs.map(([k, ic, t]) => `<button data-t="${k}" class="${k === EQ.tab ? "on" : ""}">${ic}${t}</button>`).join("")}</div>
      <section class="eqc-card eqc-pane" id="eqPane"></section>
      <div class="eqc-access">${EQI.info}<span>${money ? "Доступ к стоимости и амортизации: директор и учредитель (право «Бухгалтерия»). Остальные сотрудники видят карточку без денег." : "Стоимость и амортизацию видят директор и учредитель (право «Бухгалтерия»)."}</span></div>
    </div>
    <aside class="eqc-side">
      ${acts.length ? `<section class="eqc-card"><h3>Быстрые действия</h3><div class="eqc-acts">${acts.map(([k, ic, t]) => `<button data-act="${k}">${ic}<span>${t}</span>${EQI.chev}</button>`).join("")}</div></section>` : ""}
      <button class="eqc-card eqc-next ${e.service_due ? "due" : ""}" id="eqNext"><i>${EQI.cal}</i><span><small>Ближайшее ТО</small><b>${e.next_service ? eqLongDate(e.next_service) : "Не назначено"}</b>${e.service_due ? `<em>пора на ТО</em>` : ""}</span>${EQI.chev}</button>
      <section class="eqc-card eqc-docs"><h3>Документы <span class="muted">(${e.doc_count}/${e.doc_total})</span>${c.edit ? `<button class="linkbtn" id="eqUp">${EQI.up}Загрузить</button>` : ""}</h3>
        ${docsShown.map(k => `<button class="eqc-doc" data-dk="${k.kind}">${EQI.doc}<span><b>${esc(k.title)}</b><small>${k.count ? `${k.count} ${plural(k.count, "файл", "файла", "файлов")}` : k.kind === "photo" && photos.length ? `${photos.length} фото` : "Не загружен"}</small></span></button>`).join("")}
        <button class="linkbtn eqc-all" id="eqAll">${EQ.allDocs ? "Свернуть" : `Показать все (${mainKinds.length})`}<i class="${EQ.allDocs ? "up" : ""}">${EQI.chevd}</i></button></section>
    </aside></div></div>`;
  const on = (s, f) => { const el = $(s, body); if (el) el.onclick = f; };
  on("#eqBack", eqClose); on("#eqBack2", eqClose);
  on("#eqPrintQr", () => eqPrintLabel(e)); on("#eqEdit", () => editEquipment(e));
  on("#eqMore", ev => eqMoreMenu(ev.currentTarget, e, r));
  on("#eqNext", () => eqTab("service")); on("#eqUp", () => eqUpload("")); on("#eqPh0", () => eqUpload("photo"));
  on("#eqAll", () => { EQ.allDocs = !EQ.allDocs; eqCard(); });
  $$("[data-gal]", body).forEach(b => b.onclick = () => { EQ.gal = +b.dataset.gal; eqCard(); });
  $$("[data-dk]", body).forEach(b => b.onclick = () => { EQ.docKind = b.dataset.dk; eqTab("docs"); });
  $$("#eqTabs button", body).forEach(b => b.onclick = () => eqTab(b.dataset.t));
  $$("[data-act]", body).forEach(b => b.onclick = () => eqAction(b.dataset.act));
  eqPane();
  const big = $("#eqPhoto", body);
  if (big && big.dataset.big) {
    try { const ph = await api.stock_photo(big.dataset.big); big.insertAdjacentHTML("afterbegin", `<img src="${ph.url}" alt="">`); big.classList.add("has");
      const ex = $("#eqExp", body); if (ex) ex.onclick = () => eqViewer(ph.url, e.name); big.onclick = ev => { if (ev.target === big || ev.target.tagName === "IMG") eqViewer(ph.url, e.name); };
    } catch (x) { /* the photo did not come from the other computer yet */ }
  }
}
const eqMoney0 = v => money(Math.round(+v || 0));
const eqPct = v => `${(+v || 0).toLocaleString("ru-RU", {minimumFractionDigits: 1, maximumFractionDigits: 1})} %`;
function eqTab(t) { EQ.tab = t; $$("#eqTabs button").forEach(b => b.classList.toggle("on", b.dataset.t === t)); eqPane(); const p = $("#eqPane"); if (p && t !== "main") p.scrollIntoView({block: "nearest", behavior: "smooth"}); }
function eqViewer(url, title) {
  modal(`<div class="m-h"><h3>${esc(title)}</h3><button class="x" data-close>×</button></div><div class="m-b eqc-view"><img src="${url}" alt=""></div>`, {wide: true});
}

/* ------------------------------------------------------------ tabs */
function eqPane() {
  const el = $("#eqPane"); if (!el || !EQ.data) return;
  const r = EQ.data, e = r.e, c = r.can;
  const kv = rows => `<table class="eqc-kv">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
  const nz = (v, t = "Не указан") => v ? esc(v) : `<span class="muted">${t}</span>`;
  const evRow = x => `<div class="ev-row"><span class="mv mv-${esc(x.kind)}">${esc(x.kind_title)}</span><b>${fmtDate(x.date)}</b><span class="grow">${esc(x.text || "")}</span>${x.cost ? `<span>${money(x.cost)}</span>` : ""}<small class="muted">${esc(x.user_name || "")}</small></div>`;
  const opts = (o, cur) => Object.entries(o).map(([k, t]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${t}</option>`).join("");
  const dis = c.edit ? "" : "disabled";
  if (EQ.tab === "main") {
    el.innerHTML = `<div class="eqc-main-pane"><div><h3>Общие сведения</h3>${kv([["Наименование", esc(e.name)], ["Инвентарный номер", nz(e.inv_number)],
        ["Категория", nz(e.category, "Не указана")], ["Производитель", nz(e.manufacturer)], ["Модель", nz(e.model, "Не указана")], ["Серийный номер", nz(e.serial)],
        ["Дата ввода в эксплуатацию", e.in_service || e.purchase_date ? eqMonth((e.in_service || e.purchase_date).slice(0, 7)) : nz("", "Не указана")],
        ["Ответственный", nz(e.responsible)]])}</div>
      <div class="eqc-label"><h4>Инвентарная этикетка</h4><div class="eqc-label-in"><div class="eqc-qr" id="eqQr"></div><div><b>${esc(e.inv_number || "")}</b><span>${esc(e.name)}</span><small>${esc(e.location_name || "")}</small>
        <button class="btn ghost small eqc-dl" id="eqQrDl">${EQI.down}Скачать QR</button></div></div><small class="muted" id="eqQrNote"></small></div></div>
      <div class="eqc-sels">
        <label class="eqc-sel"><span>${EQI.pin}Местонахождение</span><select class="input" id="eqLoc" ${dis}><option value="">${e.location_id ? "— не указано —" : esc(e.location || "— не указано —")}</option>${r.places.map(p => `<option value="${esc(p.id)}" ${p.id === e.location_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <label class="eqc-sel"><span>${EQI.heart}Техническое состояние</span><select class="input eqc-cond ${eqCondCls(e.condition)}" id="eqCond" ${dis}>${opts(r.conditions, e.condition)}</select></label>
        <label class="eqc-sel"><span>${EQI.layers}Принадлежность</span><select class="input" id="eqOwn" ${dis}>${opts(r.ownerships, e.ownership)}</select></label></div>
      ${e.comment ? `<div class="muted eqc-com">${esc(e.comment)}</div>` : ""}`;
    eqLoadQr();
    const set = async (f, msg) => { try { await api.equipment_set({id: e.id, ...f}); toast(msg); eqCard(); } catch (x) { toast(errText(x), true); eqCard(); } };
    $("#eqLoc").onchange = ev => { if (ev.target.value || e.location_id) set({location_id: ev.target.value}, "Место сохранено"); };
    $("#eqCond").onchange = ev => set({condition: ev.target.value}, "Состояние сохранено");
    $("#eqOwn").onchange = ev => set({ownership: ev.target.value}, "Принадлежность сохранена");
    $("#eqQrDl").onclick = () => eqQrDownload(e);
    return;
  }
  if (EQ.tab === "finance") {
    const a = e.amort || {};
    const yrs = n => n ? (n % 12 ? `${n} мес.` : `${n / 12} ${plural(n / 12, "год", "года", "лет")}`) : "—";
    el.innerHTML = `<div class="eqc-two"><div><h3>Стоимость и амортизация</h3>${kv([["Первоначальная стоимость", money(e.price)], ["Ликвидационная стоимость", money(e.salvage || 0)],
        ["Срок полезного использования", yrs(e.useful_months)], ["Способ", "Линейный"], ["Амортизация в месяц", a.on ? money(a.monthly) : "—"],
        ["Накопленная амортизация", a.on ? `${money(a.accumulated)} · ${a.months_done} мес.` : "—"], ["Остаточная стоимость", a.on ? `<b>${money(a.residual)}</b>` : money(e.price)],
        ["Остаток срока", a.on ? yrs(a.months_left) || "самортизировано" : "—"],
        ["Амортизация на кресло-час", a.on ? `${money(e.chair_hour_cost)} <span class="muted">· ${e.chair_hours} ч в месяц</span> <button class="linkbtn" id="eqHours">изменить</button>` : "—"]])}</div>
      <div><h3>Замена оборудования</h3>${kv([["Рыночная стоимость сейчас", e.market_value ? money(e.market_value) : nz("", "Не указана")], ["Стоимость замены (новое)", e.replace_cost ? money(e.replace_cost) : nz("", "Не указана")],
        ["Плановая дата замены", e.replace_date ? fmtDate(e.replace_date) : nz("", "Не запланирована")], ["Резерв на обновление в месяц", e.reserve_monthly ? `<b>${money(e.reserve_monthly)}</b>` : "—"]])}
        ${c.edit ? `<button class="btn ghost small" id="eqRepl">${EQI.cal}Запланировать замену</button>` : ""}</div></div>
      ${["lease", "owner"].includes(e.ownership) ? `<div class="note-box">${esc(e.ownership_title)}: это не имущество клиники, поэтому амортизация и выбытие не идут в финансовый отчёт. Платежи по аренде вносятся расходами.</div>` : ""}
      ${amortBlock(e)}`;
    const h = $("#eqHours"); if (h) h.onclick = async () => { const v = await askInput("Часы работы кресла в месяц", [{label: "Часов в месяц", type: "number", value: e.chair_hours}], {text: "Например, 154 = 22 рабочих дня × 7 часов. Амортизация в месяц делится на это число.", ok: "Сохранить"});
      if (v) { try { await api.equipment_settings_save({chair_hours: v[0]}); toast("Сохранено"); eqCard(); } catch (x) { toast(errText(x), true); } } };
    const rp = $("#eqRepl"); if (rp) rp.onclick = () => eqAction("replace");
    return;
  }
  if (EQ.tab === "service") {
    const work = e.events.filter(x => ["service", "repair"].includes(x.kind));
    el.innerHTML = `<div class="eqc-stats"><div><span>Ближайшее ТО</span><b class="${e.service_due ? "bad-t" : ""}">${e.next_service ? fmtDate(e.next_service) : "—"}</b></div><div><span>Гарантия до</span><b>${e.warranty_until ? fmtDate(e.warranty_until) : "—"}</b></div>
        <div><span>ТО и ремонтов за 12 мес.</span><b>${e.service_count_year}</b></div><div><span>Расходы на обслуживание за 12 мес.</span><b>${money(e.service_cost_year)}</b></div></div>
      ${c.edit ? `<h3>Записать обслуживание или ремонт</h3><div class="eqc-form"><select class="input" id="evK"><option value="service">Плановое ТО</option><option value="repair" ${e.status === "repair" ? "selected" : ""}>Ремонт</option><option value="note">Заметка</option></select>
        <input class="input" type="date" id="evD" value="${iso(new Date())}"><input class="input grow" id="evT" placeholder="Что сделано: замена фильтров, ремонт мотора…">
        <input class="input" id="evC" type="number" min="0" step="any" placeholder="Стоимость, ₽"><label class="fl inline">Следующее ТО<input class="input" type="date" id="evN" value="${esc(e.next_service || "")}"></label>
        ${e.status === "repair" ? `<label class="dx-doc"><input type="checkbox" id="evBack" checked>Вернуть в работу</label>` : ""}<button class="btn" id="evOk">Записать</button></div>` : ""}
      <h3>Журнал ТО и ремонтов</h3><div class="ev-list">${work.map(evRow).join("") || '<div class="muted">Записей пока нет</div>'}</div>`;
    const ok = $("#evOk"); if (ok) ok.onclick = async () => {
      try { await api.equipment_event({equipment_id: e.id, kind: $("#evK").value, date: $("#evD").value, text: $("#evT").value, cost: $("#evC").value, next_service: $("#evN").value, back_in_use: !!($("#evBack") && $("#evBack").checked)});
        toast("Записано"); eqCard(); } catch (x) { toast(errText(x), true); } };
    return;
  }
  if (EQ.tab === "docs") {
    const by = {}; e.docs.forEach(d => (by[d.kind] ||= []).push(d));
    el.innerHTML = `<h3>Документы <span class="muted">${e.doc_count} из ${e.doc_total}</span></h3><div class="muted eqc-hint">PDF или фото документа. Файлы хранятся в программе и расходятся по компьютерам клиники вместе с карточкой.</div>
      <div class="eqc-dk">${r.e.doc_kinds.map(k => { const list = by[k.kind] || [];
        const extra = k.kind === "photo" && e.photo_id && !list.some(d => d.file_id === e.photo_id) ? `<div class="eqc-file"><button class="linkbtn" data-ph-open="${esc(e.photo_id)}">${EQI.ph}Главное фото</button></div>` : "";
        return `<div class="eqc-dkrow ${EQ.docKind === k.kind ? "hl" : ""}" data-kind="${k.kind}"><div class="eqc-dkh">${EQI.doc}<b>${esc(k.title)}</b><span class="grow"></span>${c.edit ? `<button class="btn ghost small" data-up="${k.kind}">${EQI.up}Загрузить</button>` : ""}</div>
          ${list.map(d => `<div class="eqc-file"><button class="linkbtn" data-open="${esc(d.id)}">${d.image ? EQI.ph : EQI.doc}${esc(d.title)}</button><small class="muted">${fmtDT(d.created_at)} · ${esc(d.created_by || "")}${d.size ? ` · ${Math.max(1, Math.round(d.size / 1024))} КБ` : ""}</small>${c.edit ? `<button class="linkbtn danger-t" data-del="${esc(d.id)}">убрать</button>` : ""}</div>`).join("")}${extra}
          ${!list.length && !extra ? `<div class="muted eqc-none">Не загружен</div>` : ""}</div>`; }).join("")}</div>`;
    $$("[data-up]", el).forEach(b => b.onclick = () => eqUpload(b.dataset.up));
    $$("[data-open]", el).forEach(b => b.onclick = async () => { try { const f = await api.equipment_doc_open(b.dataset.open); eqOpenFile(f); } catch (x) { toast(errText(x), true); } });
    $$("[data-ph-open]", el).forEach(b => b.onclick = async () => { try { const f = await api.stock_photo(b.dataset.phOpen); eqViewer(f.url, e.name); } catch (x) { toast(errText(x), true); } });
    $$("[data-del]", el).forEach(b => b.onclick = async () => { if (!await ask("Убрать документ из карточки?", {danger: true, ok: "Убрать", text: "Запись об этом останется в истории."})) return;
      try { await api.equipment_doc_delete(b.dataset.del); toast("Убрано"); eqCard(); } catch (x) { toast(errText(x), true); } });
    const hl = $(".eqc-dkrow.hl", el); if (hl) { hl.scrollIntoView({block: "center"}); EQ.docKind = null; }
    return;
  }
  if (EQ.tab === "inventory") {
    const li = e.last_inventory, list = e.events.filter(x => x.kind === "inventory");
    el.innerHTML = `<div class="eqc-stats"><div><span>Последняя инвентаризация</span><b>${li ? fmtDate(li.date) : "Не проводилась"}</b></div><div><span>Результат</span><b class="${li && !li.found ? "bad-t" : li && li.diffs.length ? "warn-t" : ""}">${li ? (li.found ? (li.diffs.length ? "Есть расхождения" : "Найдено, всё совпадает") : "Не найдено") : "—"}</b></div>
        <div><span>Проверил</span><b>${esc(li ? li.user_name || "—" : "—")}</b></div></div>
      ${c.edit ? `<h3>Провести инвентаризацию</h3><div class="eqc-inv-form"><div class="seg" id="ivFound"><button data-f="1" class="on">Найдено</button><button data-f="0">Не найдено</button></div>
        <label class="fl">Где находится<select class="input" id="ivLoc"><option value="">${esc(e.location_id ? "— как в карточке —" : e.location || "— как в карточке —")}</option>${r.places.map(p => `<option value="${esc(p.id)}" ${p.id === e.location_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <label class="fl">Состояние<select class="input" id="ivCond">${opts(r.conditions, e.condition)}</select></label>
        <label class="fl grow">Комментарий<input class="input" id="ivCom" placeholder="например: царапина на корпусе, нет наклейки"></label><button class="btn" id="ivOk">${EQI.check}Провести</button></div>
        <div class="muted eqc-hint">Если место или состояние отличаются от карточки, это запишется как расхождение, и карточка обновится.</div>` : ""}
      <h3>История инвентаризаций</h3><div class="ev-list">${list.map(evRow).join("") || '<div class="muted">Пока не проводилась</div>'}</div>`;
    let found = true;
    $$("#ivFound button", el).forEach(b => b.onclick = () => { found = b.dataset.f === "1"; $$("#ivFound button", el).forEach(x => x.classList.toggle("on", x === b)); $("#ivLoc").disabled = $("#ivCond").disabled = !found; });
    const ok = $("#ivOk"); if (ok) ok.onclick = async () => {
      const f = {id: e.id, found, comment: $("#ivCom").value};
      if (found) { if ($("#ivLoc").value) f.location_id = $("#ivLoc").value; f.condition = $("#ivCond").value; }
      try { const x = await api.equipment_inventory(f); const li2 = x.last_inventory; toast(!li2.found ? "Записано: не найдено" : li2.diffs.length ? `Расхождений: ${li2.diffs.length}` : "Расхождений нет"); eqCard(); } catch (x) { toast(errText(x), true); } };
    return;
  }
  el.innerHTML = `<h3>История</h3><div class="ev-list">${e.events.map(evRow).join("") || '<div class="muted">Записей нет</div>'}</div>`;
}

/* ------------------------------------------------------------ QR and the label */
async function eqLoadQr() {
  const box = $("#eqQr"); if (!box) return;
  try {
    const q = await api.equipment_qr(EQ.id); EQ.qr = q;
    box.innerHTML = q.png ? `<img src="${q.png}" alt="QR ${esc(q.inv_number)}">` : `<span class="muted">QR недоступен</span>`;
    const n = $("#eqQrNote"); if (n) n.textContent = q.link ? "QR открывает карточку в приложении склада на телефоне" : "Камера телефона покажет номер, название, модель и место";
  } catch (e) { box.innerHTML = `<span class="muted">QR недоступен</span>`; }
}
async function eqQrDownload(e) {
  const q = EQ.qr && EQ.id === e.id ? EQ.qr : await api.equipment_qr(e.id);
  if (!q.png) return toast("QR недоступен", true);
  await saveDataUrl(`QR ${String(e.inv_number || e.name).replace(/[\\/:*?"<>|]/g, "-")}.png`, q.png);
}
/** The sticker 40 × 30 mm (a label printer): the QR, the number, the name and the clinic. */
async function eqPrintLabel(e) {
  const q = await api.equipment_qr(e.id);
  $("#printArea").innerHTML = `<div class="eq-sticker"><img src="${q.png}" alt=""><div><b>${esc(q.inv_number || "")}</b><span>${esc(q.name)}</span><small>${esc(q.clinic || "")}</small></div></div>`;
  window.print();
}
function eqOpenFile(f) {
  if ((f.mime || "").startsWith("image/")) return eqViewer(f.url, f.title || "");
  saveDataUrl(`${(f.title || "документ").replace(/[\\/:*?"<>|]/g, "-")}.pdf`, f.url);
}

/* ------------------------------------------------------------ actions */
function eqUpload(kind) {
  const r = EQ.data; if (!r) return;
  const go = k => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = k === "photo" ? "image/*" : "application/pdf,image/*"; inp.multiple = k === "photo";
    inp.onchange = async () => {
      const files = [...(inp.files || [])]; if (!files.length) return;
      for (const f of files) {
        if (f.size > 15 * 1024 * 1024) { toast(`${f.name}: больше 15 МБ`, true); continue; }
        let data;
        try { data = f.type.startsWith("image/") ? await shrinkImage(f, 1600) : await new Promise((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = bad; rd.readAsDataURL(f); }); }
        catch (x) { data = await new Promise((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = bad; rd.readAsDataURL(f); }); }
        try { await api.equipment_doc_add(r.e.id, k, f.name, data, k === "photo" ? "" : r.doc_kinds[k]); } catch (x) { toast(errText(x), true); return; }
      }
      toast(files.length > 1 ? `Загружено: ${files.length}` : "Загружено"); if (k !== "photo") EQ.docKind = k; eqCard();
    };
    inp.click();
  };
  if (kind) return go(kind);
  const box = modal(`<div class="m-h"><h3>Загрузить документ</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="eqc-pick">${Object.entries(r.doc_kinds).map(([k, t]) => `<button class="btn ghost" data-k="${k}">${k === "photo" ? EQI.camera : EQI.doc}${esc(t)}</button>`).join("")}</div></div>`);
  $$("[data-k]", box).forEach(b => b.onclick = () => { closeModal(); go(b.dataset.k); });
}

function eqAction(k) {
  const r = EQ.data; if (!r) return;
  const e = r.e;
  const placeOpts = cur => `<option value="">— другое место (впишите) —</option>${r.places.map(p => `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>${esc(p.name)}</option>`).join("")}`;
  if (k === "photo") return eqUpload("photo");
  if (k === "inventory") return eqTab("inventory");
  if (k === "fixed") return eqTab("service");
  if (k === "move") {
    const box = modal(`<div class="m-h"><h3>Переместить: ${esc(e.name)}</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><div class="muted">Сейчас: <b>${esc(e.location_name || "место не указано")}</b></div>
        <label class="fl">Куда<select class="input" id="mvP">${placeOpts(e.location_id)}</select></label>
        <label class="fl" id="mvTW">Место (текстом)<input class="input" id="mvT" value="${esc(e.location_id ? "" : e.location || "")}" placeholder="Кабинет 2 · кресло 1"></label>
        <label class="fl">Комментарий<input class="input" id="mvC" placeholder="например: временно, на время ремонта кабинета"></label><div class="auth-err" id="mvE"></div></div>
      <div class="m-f"><span class="muted">Кабинеты берутся из «Мест хранения»</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="mvOk">Переместить</button></div>`);
    const sync = () => { $("#mvTW", box).hidden = !!$("#mvP", box).value; }; $("#mvP", box).onchange = sync; sync();
    $("#mvOk", box).onclick = async () => { const p = $("#mvP", box).value;
      try { await api.equipment_set(p ? {id: e.id, location_id: p, text: $("#mvC", box).value} : {id: e.id, location: $("#mvT", box).value, text: $("#mvC", box).value}); closeModal(); toast("Перемещено"); eqCard(); }
      catch (x) { $("#mvE", box).textContent = errText(x); } };
    return;
  }
  if (k === "repair") {
    const box = modal(`<div class="m-h"><h3>Отправить на ремонт</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><label class="fl">Что случилось*<input class="input" id="rpT" placeholder="например: не включается, течёт вода" autofocus></label><div class="auth-err" id="rpE"></div></div>
      <div class="m-f"><span class="muted">Статус станет «В ремонте». Когда вернут — «Обслуживание» → «Записать» с отметкой «Вернуть в работу».</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rpOk">Отправить</button></div>`);
    $("#rpOk", box).onclick = async () => { const t = $("#rpT", box).value.trim(); if (!t) { $("#rpE", box).textContent = "Опишите неисправность"; return; }
      try { await api.equipment_set({id: e.id, status: "repair", text: t}); closeModal(); toast("Отправлено на ремонт"); eqCard(); } catch (x) { $("#rpE", box).textContent = errText(x); } };
    return;
  }
  if (k === "replace") {
    const m = !!e.money;
    const box = modal(`<div class="m-h"><h3>Запланировать замену</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><label class="fl">Плановая дата замены*<input class="input" type="date" id="rlD" value="${esc(e.replace_date || "")}"></label>
        ${m ? `<div class="grid3"><label class="fl">Рыночная стоимость сейчас, ₽<input class="input" type="number" min="0" step="any" id="rlM" value="${e.market_value || ""}"></label>
          <label class="fl">Стоимость нового, ₽<input class="input" type="number" min="0" step="any" id="rlC" value="${e.replace_cost || ""}"></label>
          <label class="fl">Резерв в месяц, ₽<input class="input" type="number" min="0" step="any" id="rlR" value="${e.reserve_monthly || ""}" placeholder="посчитается"></label></div><div class="muted" id="rlH"></div>` : ""}
        <label class="fl">Комментарий<input class="input" id="rlT"></label><div class="auth-err" id="rlE"></div></div>
      <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rlOk">Сохранить</button></div>`);
    const hint = () => { const h = $("#rlH", box); if (!h) return; const d = $("#rlD", box).value, c = +$("#rlC", box).value || 0, mv = +$("#rlM", box).value || 0;
      if (!d || !c) { h.textContent = "Пустой резерв посчитается сам: (стоимость нового − рыночная) / месяцы до замены"; return; }
      const n = Math.max(1, (+d.slice(0, 4) * 12 + +d.slice(5, 7)) - (new Date().getFullYear() * 12 + new Date().getMonth() + 1));
      h.textContent = `До замены ${n} мес. · откладывать по ${money(Math.max(0, c - mv) / n)} в месяц`; };
    ["#rlD", "#rlC", "#rlM"].forEach(s => { const x = $(s, box); if (x) x.oninput = hint; }); hint();
    $("#rlOk", box).onclick = async () => { const f = {id: e.id, replace_date: $("#rlD", box).value, comment: $("#rlT", box).value};
      if (m) Object.assign(f, {market_value: $("#rlM", box).value, replace_cost: $("#rlC", box).value, reserve_monthly: $("#rlR", box).value});
      try { await api.equipment_replace_plan(f); closeModal(); toast("Замена запланирована"); eqCard(); } catch (x) { $("#rlE", box).textContent = errText(x); } };
    return;
  }
  if (k === "dispose") return eqDispose(e);
}

function eqDispose(e) {
  const r = EQ.data, m = !!e.money;
  let kind = "writeoff";
  const box = modal(`<div class="m-h"><h3>Выбытие: ${esc(e.name)}, инв. № ${esc(e.inv_number)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="seg" id="dsK">${Object.entries(r.disposals).map(([k, t]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${t}</button>`).join("")}</div>
      <div class="grid3"><label class="fl">Дата<input class="input" type="date" id="dsD" value="${iso(new Date())}"></label><label class="fl" id="dsNW">Номер акта<input class="input" id="dsN" placeholder="присвоится сам"></label>
        ${m ? `<label class="fl">Остаточная стоимость, ₽<input class="input" type="number" min="0" step="any" id="dsR" placeholder="${e.amort && e.amort.on ? "по амортизации на дату выбытия" : money(e.price || 0)}" title="Пусто — посчитается по амортизации на дату выбытия"></label>` : ""}</div>
      <label class="fl" id="dsWL"><span id="dsWT">Причина списания*</span><input class="input" id="dsW" list="dsWo"></label>
      <datalist id="dsWo"><option value="Физический износ, ремонт экономически нецелесообразен"><option value="Неисправность, не подлежит восстановлению"><option value="Моральный износ, замена на новое"><option value="Повреждение в результате аварии"></datalist>
      ${m ? `<label class="fl" id="dsAW" hidden>Сумма продажи, ₽<input class="input" type="number" min="0" step="any" id="dsA"></label>` : ""}
      <div id="dsCom"><label class="fl">Председатель комиссии*<input class="input" id="dsC0" placeholder="ФИО, должность"></label>
        <div class="grid2"><label class="fl">Член комиссии*<input class="input" id="dsC1" placeholder="ФИО, должность"></label><label class="fl">Член комиссии<input class="input" id="dsC2" placeholder="ФИО, должность"></label></div></div>
      <div class="warn-line">После выбытия карточку нельзя изменить; она останется в реестре («Показать выбывшее»).</div><div class="auth-err" id="dsE"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="dsOk">Оформить</button></div>`, {wide: true});
  const draw = () => {
    $$("#dsK button", box).forEach(b => b.classList.toggle("on", b.dataset.k === kind));
    $("#dsCom", box).hidden = $("#dsNW", box).hidden = kind !== "writeoff";
    const aw = $("#dsAW", box); if (aw) aw.hidden = kind !== "sale";
    $("#dsWT", box).textContent = {writeoff: "Причина списания*", sale: "Покупатель и основание*", return: "Кому возвращено, по какому документу*"}[kind];
    $("#dsW", box).placeholder = {writeoff: "например: неисправность, ремонт нецелесообразен", sale: "ООО «…», договор № …", return: "арендодателю по акту № …"}[kind];
    $("#dsW", box).setAttribute("list", kind === "writeoff" ? "dsWo" : "");
    $("#dsOk", box).textContent = kind === "writeoff" ? "Списать и распечатать акт" : "Оформить";
  };
  $$("#dsK button", box).forEach(b => b.onclick = () => { kind = b.dataset.k; draw(); }); draw();
  $("#dsOk", box).onclick = async () => {
    const f = {id: e.id, kind, date: $("#dsD", box).value, reason: $("#dsW", box).value, act_number: $("#dsN", box).value,
      commission: [$("#dsC0", box).value, $("#dsC1", box).value, $("#dsC2", box).value]};
    if (m) { f.residual = $("#dsR", box).value; if ($("#dsA", box)) f.amount = $("#dsA", box).value; }
    try { const x = await api.equipment_dispose(f); closeModal(); toast(x.status_title); eqCard(); if (kind === "writeoff") printEquipmentAct(x); }
    catch (err) { $("#dsE", box).textContent = errText(err); }
  };
}

function eqMoreMenu(btn, e, r) {
  const items = [["qr", "Скачать QR (PNG)"], ["label", "Печать наклейки 40×30 мм"]];
  if (e.status === "written_off" && (e.disposal_kind || "writeoff") === "writeoff") items.push(["act", "Печать акта списания"]);
  if (r.can.edit) items.push(["dispose", "Оформить выбытие"]);
  if (e.money) items.push(["amort", "Амортизация всего оборудования"]);
  const old = $(".eqc-menu"); if (old) { old.remove(); return; }
  const m = document.createElement("div"); m.className = "eqc-menu";
  m.innerHTML = items.map(([k, t]) => `<button data-m="${k}">${t}</button>`).join("");
  btn.parentElement.appendChild(m);
  const close = () => { m.remove(); document.removeEventListener("click", out, true); };
  const out = ev => { if (!m.contains(ev.target) && ev.target !== btn) close(); };
  setTimeout(() => document.addEventListener("click", out, true));
  $$("[data-m]", m).forEach(b => b.onclick = () => { close();
    ({qr: () => eqQrDownload(e), label: () => eqPrintLabel(e), act: () => printEquipmentAct(e), dispose: () => eqDispose(e), amort: () => openAmortReport()})[b.dataset.m](); });
}

/* ------------------------------------------------------------ the form «Карточка оборудования» */
async function editEquipment(e) {
  const isNew = !e.id;
  const money = isNew ? !!STK.eq_money : !!e.money;
  let places = [], nextInv = "";
  try { [places, nextInv] = await Promise.all([api.stock_locations(), isNew ? api.equipment_next_inv() : Promise.resolve("")]); } catch (x) { /* the form works without them */ }
  places = (places || []).filter(p => p.id);
  const R = (EQ.data && EQ.data.ownerships) ? EQ.data : {ownerships: {own: "Собственность клиники", lease: "Аренда", leasing: "Лизинг", owner: "Имущество учредителя"},
    conditions: {ok: "Исправно", service: "Требует обслуживания", faulty: "Неисправно"}};
  const opts = (o, cur) => Object.entries(o).map(([k, t]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${t}</option>`).join("");
  const box = modal(`<div class="m-h"><h3>${isNew ? "Карточка оборудования" : "Редактировать: " + esc(e.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b eqc-edit">
      <div class="grid3"><label class="fl" style="grid-column:span 2">Наименование*<input class="input" id="eN" value="${esc(e.name || "")}" autofocus placeholder="Стоматологическая установка"></label>
        <label class="fl">Инвентарный номер<input class="input" id="eInv" value="${esc(e.inv_number || "")}" placeholder="${esc(nextInv ? nextInv + " — присвоится сам" : "присвоится сам")}"></label></div>
      <div class="grid3"><label class="fl">Категория<input class="input" id="eC" value="${esc(e.category || "")}" list="eCats" placeholder="Медицинское оборудование"></label>
        <label class="fl">Производитель<input class="input" id="eMf" value="${esc(e.manufacturer || "")}"></label><label class="fl">Модель<input class="input" id="eM" value="${esc(e.model || "")}"></label></div>
      <datalist id="eCats">${["Медицинское оборудование", "Стерилизация", "Рентген и визиография", "Мебель", "Компьютеры и оргтехника", "Инструменты"].map(x => `<option value="${x}">`).join("")}</datalist>
      <div class="grid3"><label class="fl">Серийный номер<input class="input" id="eS" value="${esc(e.serial || "")}"></label>
        <label class="fl">Местонахождение<select class="input" id="eLoc"><option value="">— другое (впишите ниже) —</option>${places.map(p => `<option value="${esc(p.id)}" ${p.id === e.location_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <label class="fl" id="eLW">Место текстом<input class="input" id="eL" value="${esc(e.location_id ? "" : e.location || "")}" placeholder="Кабинет 1 · кресло 1"></label></div>
      <div class="grid3"><label class="fl">Ответственный<input class="input" id="eR" value="${esc(e.responsible || "")}" placeholder="Медсестра кабинета № 1"></label>
        <label class="fl">Принадлежность<select class="input" id="eOwn">${opts(R.ownerships, e.ownership || "own")}</select></label>
        <label class="fl">Техническое состояние<select class="input" id="eCond">${opts(R.conditions, e.condition || "ok")}</select></label></div>
      <div class="grid3"><label class="fl">Статус<select class="input" id="eSt">${Object.entries(STK.eq_status || {}).filter(([k]) => k !== "written_off").map(([k, t]) => `<option value="${k}" ${k === (e.status || "in_use") ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <label class="fl">Дата покупки<input class="input" type="date" id="eP" value="${esc(e.purchase_date || "")}"></label><label class="fl">Ввод в эксплуатацию<input class="input" type="date" id="eIn" value="${esc(e.in_service || "")}" title="Пусто — с даты покупки"></label></div>
      <div class="grid3"><label class="fl">Гарантия до<input class="input" type="date" id="eW" value="${esc(e.warranty_until || "")}"></label><label class="fl">Следующее ТО<input class="input" type="date" id="eNx" value="${esc(e.next_service || "")}"></label></div>
      ${money ? `<h4 class="sub-h">Стоимость и амортизация (линейный способ)</h4>
      <div class="grid3"><label class="fl">Стоимость, ₽<input class="input" type="number" min="0" step="any" id="ePr" value="${e.price ?? ""}"></label>
        <label class="fl">Срок полезного использования, мес.<input class="input" type="number" min="0" max="600" step="1" id="eLife" list="eLifes" value="${e.useful_months || ""}" placeholder="например, 60 = 5 лет"></label>
        <label class="fl">Ликвидационная стоимость, ₽<input class="input" type="number" min="0" step="any" id="eSalv" value="${e.salvage || ""}" placeholder="0"></label></div>
      <datalist id="eLifes">${[12, 24, 36, 60, 84, 120, 180].map(x => `<option value="${x}">${x / 12} ${plural(x / 12, "год", "года", "лет")}</option>`).join("")}</datalist>
      <div class="muted" id="eLifeT" style="margin-top:-4px"></div>
      ${isNew ? `<div class="grid3"><label class="fl" style="grid-column:span 2" title="Расход запишется датой покупки в статью «Покупка оборудования»: в движении денег он есть, а в прибыль оборудование идёт амортизацией">Записать оплату в расходы<select class="input" id="ePay"><option value="">— не записывать (оплата уже внесена или будет позже) —</option>${["Безналичный перевод", "Наличные", "Карта"].map(m => `<option>${m}</option>`).join("")}</select></label></div>` : ""}` : `<div class="muted">Стоимость и амортизацию вносит директор (право «Бухгалтерия»).</div>`}
      <label class="fl">Комментарий<input class="input" id="eCom" value="${esc(e.comment || "")}"></label><div class="auth-err" id="eErr"></div></div>
    <div class="m-f"><span class="muted">${isNew ? "После сохранения откроется карточка: фото, документы, QR-этикетка" : ""}</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="eOk">${isNew ? "Создать карточку" : "Сохранить"}</button></div>`, {wide: true});
  const syncLoc = () => { $("#eLW", box).style.visibility = $("#eLoc", box).value ? "hidden" : ""; }; $("#eLoc", box).onchange = syncLoc; syncLoc();
  $("#eOk", box).onclick = async () => {
    const f = {id: e.id, name: $("#eN").value, inv_number: $("#eInv").value, model: $("#eM").value, serial: $("#eS").value, category: $("#eC").value,
      manufacturer: $("#eMf").value, responsible: $("#eR").value, status: $("#eSt").value, purchase_date: $("#eP").value, warranty_until: $("#eW").value,
      next_service: $("#eNx").value, comment: $("#eCom").value, in_service: $("#eIn").value, ownership: $("#eOwn").value, condition: $("#eCond").value};
    if ($("#eLoc").value) f.location_id = $("#eLoc").value; else { f.location_id = ""; f.location = $("#eL").value; }
    if (money) Object.assign(f, {price: $("#ePr").value, useful_months: $("#eLife").value, salvage: $("#eSalv").value});
    const pay = $("#ePay"); if (pay && pay.value) f.pay = pay.value;  // 3.14: «Покупка оборудования»
    try { const id = await api.save_equipment(f); closeModal(); toast(isNew ? "Карточка создана" : "Сохранено"); openEquipment(id); }
    catch (err) { $("#eErr").textContent = errText(err); }
  };
  if (money) {
    const lifeT = () => { const n = +$("#eLife").value || 0, p = +$("#ePr").value || 0, sv = +$("#eSalv").value || 0;
      $("#eLifeT").textContent = n > 0 ? `${n % 12 ? n + " мес." : n / 12 + " " + plural(n / 12, "год", "года", "лет")}${p > 0 ? ` · в месяц ${money(Math.max(0, p - sv) / n)}` : ""}` : "Без срока амортизация не считается"; };
    ["#eLife", "#ePr", "#eSalv"].forEach(s => $(s, box).oninput = lifeT); lifeT();
  }
}
