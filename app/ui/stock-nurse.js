"use strict";
/* 3.10 «Склад — главная»: tiles «Принять поставку · Выдать в кабинет · Зафиксировать расход · Создать заявку», search with a
   barcode scanner, balances with photos, cabinets, lots and requests; on the right — tasks, critical balances, expiry dates
   and quick numbers. The four screens open in place of the home screen. A nurse's consumption or write-off waits for a
   manager (the server decides; the screen only says so). Photos of materials and equipment, depreciation of equipment. */
const SN = {sub: "balance", cat: "", low: false, q: "", place: null, days: 30, home: null, rows: []};
const SN_PRI = {normal: "Обычный", urgent: "Срочный", critical: "Критический"};
const PHOTO = {};  // photo id → data: URL of its preview (kept while the program is open)
const SN_ICON = {
  receive: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/><circle cx="18.5" cy="17.5" r="3.6" class="fill-bg"/><path d="M18.5 15.6v3.8M16.6 17.5h3.8"/></svg>',
  issue: '<svg viewBox="0 0 24 24"><path d="M4 8.5h15l-3.5-3.5M20 15.5H5l3.5 3.5"/></svg>',
  use: '<svg viewBox="0 0 24 24"><path d="M8 3.5c-2.7 0-4.2 2-4.2 4.7 0 2.6 1.2 4.3 1.8 6.5.7 2.5 1 5.8 2.6 5.8 1.7 0 1.6-4.4 3.8-4.4s2.1 4.4 3.8 4.4c1.6 0 1.9-3.3 2.6-5.8.6-2.2 1.8-3.9 1.8-6.5 0-2.7-1.5-4.7-4.2-4.7-1.8 0-2.8 1.1-4 1.1S9.8 3.5 8 3.5z"/></svg>',
  request: '<svg viewBox="0 0 24 24"><path d="M3 4.5h2.4l2.3 10.3h10.5l2.3-7.3H6.3"/><circle cx="9.3" cy="18.8" r="1.4"/><circle cx="16.8" cy="18.8" r="1.4"/></svg>',
  scan: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5v-3h3M17.5 4.5h3v3M20.5 16.5v3h-3M6.5 19.5h-3v-3"/><path d="M7.5 8v8M10 8v8M12.5 8v8M15.5 8v8"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>',
  task: '<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="17" rx="2.5"/><path d="M9 4V3h6v1M8.5 11l2 2 4-4M8.5 16.5h7"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17h.01"/></svg>',
  cal: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  chev: '<svg viewBox="0 0 24 24"><path d="m9.5 6 6 6-6 6"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M12 5v14M6 13l6 6 6-6"/></svg>',
  stack: '<svg viewBox="0 0 24 24"><path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12l9 4.5 9-4.5M3 16l9 4.5 9-4.5"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/></svg>',
  ph: '<svg viewBox="0 0 24 24"><rect x="7.5" y="3" width="9" height="4" rx="1"/><path d="M8.5 7v12.5a1.5 1.5 0 0 0 1.5 1.5h4a1.5 1.5 0 0 0 1.5-1.5V7"/><path d="M8.5 11.5h7"/></svg>',
  camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l1.6-2.5h6.8L17 8h3v11H4z"/><circle cx="12" cy="13.2" r="3.4"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 5.5 8.5 12l6.5 6.5"/></svg>',
  ok: '<svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
};
const snCan = () => (SN.home && SN.home.can) || {};
const snPlaces = () => (STK.locations || []);
const snCabinets = () => snPlaces().filter(l => l.id);
const snPlaceName = id => (snPlaces().find(l => l.id === (id || "")) || {}).name || "Основной склад";
const snNum = v => Math.round((+String(v ?? "").replace(",", ".") || 0) * 1000) / 1000;
const snLS = (k, v) => { try { if (v === undefined) return localStorage.getItem("dd.sn." + k); localStorage.setItem("dd.sn." + k, v); } catch (e) { return null; } };

/* ------------------------------------------------------------- photos */
/** `def` (3.18): the picture shown while the piece or the material has no photo of its own — eqPic() / matPic(). */
function phHtml(photoId, cls = "", def = "") {
  const url = photoId && PHOTO[photoId];
  return `<span class="sn-ph ${cls} ${url ? "has" : def ? "def" : ""}" ${photoId ? `data-ph="${esc(photoId)}"` : ""}>${url ? `<img src="${url}" alt="">` : def ? `<img src="${def}" alt="" title="Картинка по названию — своё фото можно добавить в карточке">` : SN_ICON.ph}</span>`;
}

/* 3.18: pictures of the usual equipment and materials (img/stock, cut out — fit the dark theme too) for what has no photo of
   its own: the first rule whose words are in the name wins, then the category; the order matters (a panoramic X-ray before
   an X-ray, an ultrasonic bath before a scaler, a stool before a chair). */
const STOCK_PIC_DIR = "img/stock/";
const EQ_PIC_RULES = [
  ["apex", ["апекс"]], ["opg", ["ортопантомограф", "опг", "томограф", "панорамн", "кт "]], ["sensor", ["визиограф", "датчик", "сенсор"]],
  ["xray", ["рентген"]], ["ultrasonic-bath", ["мойк", "ванн"]], ["scaler", ["скалер", "ультразвук", "пьезо"]],
  ["handpiece", ["наконечник", "турбин", "микромотор"]], ["recirculator", ["рециркулятор", "облучател", "бактерицид"]],
  ["curing", ["полимериз", "лампа", "фотополимер"]],
  ["implant-motor", ["физиодиспенсер", "имплантолог", "хирургический мотор"]], ["sealer", ["запайщик", "упаковочн"]],
  ["autoclave", ["автоклав", "стерилизатор", "сухожар"]],
  ["compressor", ["компрессор", "аспиратор", "аспирационн", "отсос"]], ["microscope", ["микроскоп"]],
  ["fridge", ["холодильник"]], ["cabinet", ["шкаф", "стеллаж", "тумб"]], ["stool", ["стул", "табурет", "седло", "кресло врача", "кресло ассистента"]],
  ["printer", ["принтер", "мфу", "копир", "сканер документ", "ламинатор"]], ["computer", ["моноблок", "компьютер", "ноутбук", "монитор", "пк ", "планшет"]],
  ["chair", ["установк", "кресло", "стоматологическ"]],
];
const EQ_PIC_CATS = {"стоматологическое оборудование": "chair", "диагностическое оборудование": "xray", "стерилизационное оборудование": "autoclave",
  "стерилизация": "autoclave", "рентген и визиография": "xray", "инженерное оборудование": "compressor", "медицинские инструменты": "handpiece",
  "инструменты": "handpiece", "компьютерная техника": "computer", "компьютеры и оргтехника": "computer", "оргтехника": "printer", "мебель": "cabinet",
  "медицинское оборудование": "chair", "бытовая техника": "fridge"};
const MAT_PIC_RULES = [
  ["carpule", ["карпул", "анестет", "артикаин", "ультракаин", "убистезин", "септанест", "мепивака", "лидокаин", "скандонест"]],
  ["syringe", ["шприц", "композит", "flow", "флоу", "пломбир"]], ["disinfectant", ["дез", "антисепт", "спрей", "хлоргекс", "гипохлор"]],
  ["gloves", ["перчат"]], ["napkins", ["салфет", "полотен", "бумаг", "туалет"]], ["tube", ["тюбик", "паст", "гель", "крем"]],
  ["bottle", ["флакон", "бонд", "адгез", "жидкост", "праймер", "капл"]], ["jar", ["баноч", "порош", "альгинат", "слепоч", "гипс", "силикон"]],
];
const MAT_PIC_CATS = {"пломбировочные материалы": "syringe", "анестезия": "carpule", "эндодонтия": "bottle", "ортопедия и слепочные материалы": "jar",
  "гигиена и профилактика": "tube", "дезинфекция и стерилизация": "disinfectant", "расходные одноразовые": "gloves", "хозяйственные товары": "napkins"};
function stockPicBy(rules, cats, name, category, fallback) {
  const n = ` ${String(name || "").toLowerCase().replace(/ё/g, "е")} `, c = String(category || "").trim().toLowerCase();
  const r = rules.find(([, words]) => words.some(w => n.includes(w)));
  const key = r ? r[0] : cats[c] || (c.startsWith("хоз") && cats["хозяйственные товары"]) || fallback;
  return key ? STOCK_PIC_DIR + key + ".webp" : "";
}
/** The picture of a piece of equipment by its name and category («» — nothing fits: the usual placeholder). */
const eqPic = (name, category) => stockPicBy(EQ_PIC_RULES, EQ_PIC_CATS, name, category, "");
/** The picture of a material by its name and category; anything else — a plain carton box. */
const matPic = (name, category) => stockPicBy(MAT_PIC_RULES, MAT_PIC_CATS, name, category, "box");
/** Previews of the photos on the screen: the ones not loaded yet are fetched in one call. */
async function loadThumbs(root = document) {
  const els = [...root.querySelectorAll("[data-ph]")];
  const want = [...new Set(els.map(e => e.dataset.ph).filter(id => !PHOTO[id]))];
  if (want.length) { try { Object.assign(PHOTO, await api.stock_photos(want)); } catch (e) { /* previews are not worth an error */ } }
  els.forEach(e => { const u = PHOTO[e.dataset.ph]; if (u && !e.classList.contains("has")) { e.classList.add("has"); e.innerHTML = `<img src="${u}" alt="">`; } });
}
/** A picture from the computer, made smaller here before it goes over the network (the server makes it smaller again). */
function photoPick(kind, id, onDone) {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = "image/*";
  inp.onchange = async () => {
    const f = inp.files && inp.files[0];
    if (!f) return;
    if (f.size > 15 * 1024 * 1024) { toast("Фото больше 15 МБ — выберите снимок поменьше", true); return; }
    let data;
    try { data = await shrinkImage(f, 1600); } catch (e) { data = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(f); }); }
    try {
      const r = await api.stock_photo_set(kind, id, f.name, data);
      if (r.thumb) PHOTO[r.photo_id] = r.thumb;
      toast("Фото сохранено"); if (onDone) onDone(r);
    } catch (e) { toast(errText(e), true); }
  };
  inp.click();
}
async function shrinkImage(file, side) {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, side / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.88);
}
/** The photo of a card (material or equipment): the picture and «Загрузить / Заменить / Убрать». */
function photoBlock(kind, obj, editable) {
  return `<div class="sn-photo-box" id="phBox"><div class="sn-photo-big" ${obj.photo_id ? `data-big="${esc(obj.photo_id)}"` : ""}>${SN_ICON.ph}</div>
    ${editable ? `<div class="sn-photo-acts"><button class="btn ghost small" id="phSet">${SN_ICON.camera}${obj.photo_id ? "Заменить фото" : "Загрузить фото"}</button>
      ${obj.photo_id ? `<button class="linkbtn" id="phDel">убрать</button>` : ""}</div>` : ""}</div>`;
}
async function bindPhotoBlock(box, kind, obj, reopen) {
  const big = $(".sn-photo-big[data-big]", box);
  if (big) { try { const r = await api.stock_photo(big.dataset.big); big.innerHTML = `<img src="${r.url}" alt="">`; big.classList.add("has"); big.onclick = () => window.open(r.url); } catch (e) { /* the file did not come yet */ } }
  const set = $("#phSet", box); if (set) set.onclick = () => photoPick(kind, obj.id, () => { reopen(); if (S.stockTab === "home") stockHomeSub(); });
  const del = $("#phDel", box); if (del) del.onclick = async () => { await api.stock_photo_clear(kind, obj.id); toast("Фото убрано"); reopen(); };
}

/* --------------------------------------------------------------- home */
function snTile(key, title, sub, ok) {
  return `<button class="sn-tile sn-t-${key}" data-tile="${key}" ${ok ? "" : "disabled title='Нет прав — обратитесь к директору'"}><i>${SN_ICON[key]}</i><b>${title}</b><span>${sub}</span></button>`;
}
async function stockHome() {
  S.matOpen = null;  // 3.13: the home screen replaces an open material card
  const body = $("#stockBody");
  const h = await api.stock_home(SN.days);
  SN.home = h;
  const c = h.can, cnt = h.counts;
  const myTab = c.approve || c.edit ? "Заявки и списания" : "Мои заявки";
  const waiting = (cnt.to_approve || 0) + (cnt.to_issue || 0) || (cnt.my_requests || 0) + (cnt.my_pending || 0);
  body.innerHTML = `<div class="sn-home">
    <div class="sn-main">
      <div class="sn-tiles">${snTile("receive", "Принять поставку", "Поступление от поставщика", c.receive)}${snTile("issue", "Выдать в кабинет", "Перемещение материалов", c.issue)}
        ${snTile("use", "Зафиксировать расход", c.direct ? "Использование в лечении" : "Использование в лечении · на согласование", c.use)}${snTile("request", "Создать заявку", "Запрос материалов со склада", c.request)}</div>
      <div class="sn-search"><label class="sn-q">${SN_ICON.search}<input id="snQ" placeholder="Найти материал: название, артикул, штрихкод" value="${esc(SN.q)}" autocomplete="off"></label>
        <button class="icon-btn sn-scan" id="snScan" title="Сканер штрихкода: наведите сканер — код попадёт в поиск">${SN_ICON.scan}</button></div>
      <div class="seg sn-sub" id="snSub"><button data-s="balance">${SN_ICON.stack}Остатки</button><button data-s="places">Кабинеты</button><button data-s="lots">Партии и сроки</button>
        <button data-s="requests">${myTab}${waiting ? `<i class="cnt">${waiting}</i>` : ""}</button></div>
      <div id="snBody"></div>
    </div>
    <aside class="sn-side">
      <section class="sn-card"><h4>Мои задачи ${h.tasks.length ? `<i class="cnt">${h.tasks.length}</i>` : ""}</h4>
        ${h.tasks.length ? `<div class="sn-tasks">${h.tasks.map((t, i) => `<button class="sn-task" data-task="${i}"><i>${SN_ICON.task}</i><span><b>${esc(t.title)}</b><small>${esc(t.sub)}</small></span>${SN_ICON.chev}</button>`).join("")}</div>`
          : `<div class="muted sn-none">Задач нет — всё в порядке</div>`}</section>
      ${h.critical_count ? `<section class="sn-card sn-bad"><h4>${SN_ICON.alert}Критические остатки — ${h.critical_count}</h4>${h.critical.map(m => `<button class="sn-li" data-crit="${esc(m.id)}"><span>${esc(m.name)} — <b>${qtyFmt(m.balance)}</b> / ${qtyFmt(m.min_qty, m.unit)}</span>${SN_ICON.chev}</button>`).join("")}</section>` : ""}
      ${h.expiring_count ? `<section class="sn-card sn-warn"><h4>${SN_ICON.cal}Ближайшие сроки годности — ${h.expiring_count}</h4>${h.expiring.map(x => `<button class="sn-li" data-exp="${esc(x.material_id)}"><span>${esc(x.name)} — ${x.state === "expired" ? "<b>просрочено</b>" : "до " + fmtDateShort(x.expires)}</span>${SN_ICON.chev}</button>`).join("")}</section>` : ""}
      <section class="sn-card"><h4>Быстрая статистика <select class="input sm-sel" id="snDays">${h.stat_days.map(d => `<option value="${d}" ${d === h.stats.days ? "selected" : ""}>${d === 365 ? "За год" : "За " + d + " дн."}</option>`).join("")}</select></h4>
        <div class="sn-stats"><div class="sn-st in">${SN_ICON.up}<span>Приход</span><b>${money(h.stats.income)}</b></div><div class="sn-st out">${SN_ICON.down}<span>Расход</span><b>${money(h.stats.used)}</b></div>
          <div class="sn-st left">${SN_ICON.stack}<span>Остаток</span><b>${money(h.stats.value)}</b></div></div></section>
    </aside></div>`;
  $$("[data-tile]", body).forEach(b => b.onclick = () => ({receive: openReceiveScreen, issue: openIssueScreen, use: openUseScreen, request: openRequestScreen})[b.dataset.tile]());
  $$("#snSub button", body).forEach(b => { b.classList.toggle("on", b.dataset.s === SN.sub); b.onclick = () => { SN.sub = b.dataset.s; $$("#snSub button").forEach(x => x.classList.toggle("on", x === b)); stockHomeSub(); }; });
  $$("[data-task]", body).forEach(b => b.onclick = () => snTask(h.tasks[+b.dataset.task]));
  $$("[data-crit]", body).forEach(b => b.onclick = () => c.request ? openRequestScreen({lines: {[b.dataset.crit]: 1}}) : openMaterial(b.dataset.crit));
  $$("[data-exp]", body).forEach(b => b.onclick = () => openMaterial(b.dataset.exp));
  $("#snDays").onchange = e => { SN.days = +e.target.value; stockHome(); };
  let t; const q = $("#snQ");
  q.oninput = () => { clearTimeout(t); t = setTimeout(() => { SN.q = q.value; if (SN.sub !== "balance") { SN.sub = "balance"; $$("#snSub button").forEach(x => x.classList.toggle("on", x.dataset.s === "balance")); } stockHomeSub(); }, 180); };
  q.onkeydown = async e => {  // a scanner types the code and presses Enter
    if (e.key !== "Enter" || !q.value.trim()) return;
    e.preventDefault();
    const code = q.value.trim();
    try { const r = await api.stock_scan(code); if (r.material) { q.value = ""; SN.q = ""; stockHomeSub(); openMaterial(r.material.id); return; }
      if (r.equipment_id) { q.value = ""; SN.q = ""; openEquipment(r.equipment_id); return; } } catch (err) { /* not a barcode */ }  // 3.13: QR of a label
  };
  $("#snScan").onclick = () => { q.focus(); q.select(); toast("Наведите сканер на штрихкод — материал найдётся сам"); };
  await stockHomeSub();
}
const fmtDateShort = s => s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}` : "";
function snTask(t) {
  const k = t && t.key;
  if (k === "approve" || k === "my" || k === "drafts") { SN.sub = "requests"; return stockHome(); }
  if (k === "issue") return openIssueScreen();
  if (k === "expired") return can("stock_edit") ? writeOffExpired() : (SN.sub = "lots", stockHome());
  if (k === "order") return can("stock_edit") ? openPurchase() : (SN.low = true, SN.sub = "balance", stockHome());
  if (k === "service") return stockGo("equipment", "service");  // 3.14: «ТО и ремонт» of «Оборудование»
}
async function stockHomeSub() {
  const el = $("#snBody"); if (!el) return;
  if (SN.sub === "places") return snPlacesSub(el);
  if (SN.sub === "lots") return snLotsSub(el);
  if (SN.sub === "requests") return snRequestsSub(el);
  return snBalanceSub(el);
}
function balPill(m, bal = m.balance) {
  const cls = bal < 0 || (m.min_qty && bal <= m.min_qty) ? "bad" : m.min_qty && bal <= m.min_qty * 1.5 ? "warn" : "ok";
  return `<span class="sn-bal ${cls}">${qtyFmt(bal, m.unit)}</span>`;
}
async function snBalanceSub(el) {
  if (SN.place != null && !snPlaces().some(l => l.id === SN.place)) SN.place = null;
  const rows = await api.materials(SN.q, SN.low, false, SN.place);
  SN.rows = rows;
  const where = (SN.home && SN.home.where) || {};
  const cats = (SN.home && SN.home.categories) || [];
  const shown = rows.filter(m => !SN.cat || m.category === SN.cat);
  el.innerHTML = `<div class="sn-panel"><div class="sn-tools">
      <select class="input sm-sel" id="snCat"><option value="">Все материалы</option>${cats.map(c => `<option ${c === SN.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      ${hasPlaces() ? `<select class="input sm-sel" id="snPlace"><option value="*">Все места</option>${snPlaces().map(l => `<option value="${esc(l.id)}" ${l.id === SN.place ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>` : ""}
      <span class="grow"></span><label class="switch-row" style="margin:0"><input type="checkbox" id="snLow" ${SN.low ? "checked" : ""}><span class="sw"></span>Только низкие остатки</label></div>
    ${shown.length ? `<table class="tbl sn-tbl"><thead><tr><th>Материал</th><th>Остаток</th><th class="num">Минимум</th><th>Срок годности</th><th>Местонахождение</th><th></th></tr></thead><tbody>${shown.map(m => {
      const pct = m.min_qty ? Math.max(4, Math.min(100, m.balance / (m.min_qty * 2) * 100)) : (m.balance > 0 ? 100 : 0);
      const pl = (where[m.id] || []).slice(0, 2);
      return `<tr data-m="${esc(m.id)}"><td><div class="sn-mat">${phHtml(m.photo_id, "", matPic(m.name, m.category))}<span><b>${esc(m.name)}</b><small>${m.code ? "Арт. " + esc(m.code) : esc(m.category || "")}</small></span></div></td>
        <td>${balPill(m)}<i class="sn-prog ${m.low || m.balance < 0 ? "bad" : ""}"><i style="width:${pct}%"></i></i></td><td class="num">${m.min_qty ? qtyFmt(m.min_qty) : "—"}</td>
        <td class="${m.exp_state === "expired" ? "bad-t" : m.exp_state === "soon" ? "warn-t" : ""}">${m.expires ? "до " + fmtDateShort(m.expires) : '<span class="muted">—</span>'}</td>
        <td>${pl.length ? pl.map(p => `<span class="sn-place">${esc(p.name)}</span>`).join("") : '<span class="sn-place">' + esc(SN.place != null ? snPlaceName(SN.place) : "Основной склад") + "</span>"}${(where[m.id] || []).length > 2 ? `<small class="muted"> +${where[m.id].length - 2}</small>` : ""}</td>
        <td class="sn-more"><button class="icon-btn" data-more="${esc(m.id)}" title="Действия">⋯</button></td></tr>`; }).join("")}</tbody></table>`
      : `<div class="empty"><b>${SN.q || SN.low || SN.cat ? "Ничего не найдено" : "Склад пока пуст"}</b><span>${can("stock_edit") ? "Добавьте материалы во вкладке «Остатки» и примите поставку" : ""}</span></div>`}</div>`;
  $("#snCat").onchange = e => { SN.cat = e.target.value; snBalanceSub(el); };
  const sp = $("#snPlace"); if (sp) sp.onchange = e => { SN.place = e.target.value === "*" ? null : e.target.value; snBalanceSub(el); };
  $("#snLow").onchange = e => { SN.low = e.target.checked; snBalanceSub(el); };
  $$("tr[data-m]", el).forEach(tr => tr.onclick = e => { if (!e.target.closest("[data-more]")) openMaterial(tr.dataset.m); });
  $$("[data-more]", el).forEach(b => b.onclick = e => { e.stopPropagation(); snMoreMenu(b, rows.find(m => m.id === b.dataset.more)); });
  loadThumbs(el);
}
function snMoreMenu(btn, m) {
  document.querySelectorAll(".sn-menu").forEach(x => x.remove());
  const c = snCan();
  const items = [["open", "Карточка материала"], c.request && ["req", "В заявку"], c.use && ["use", "Зафиксировать расход"],
    c.issue && hasPlaces() && ["issue", "Выдать в кабинет"], (c.edit || c.use) && ["photo", m.photo_id ? "Заменить фото" : "Добавить фото"]].filter(Boolean);
  const menu = document.createElement("div");
  menu.className = "sn-menu dd-menu";
  menu.innerHTML = items.map(([k, t]) => `<button data-a="${k}">${t}</button>`).join("");
  document.body.appendChild(menu);
  const r = btn.getBoundingClientRect();
  menu.style.top = `${Math.min(window.innerHeight - menu.offsetHeight - 8, r.bottom + 4)}px`; menu.style.left = `${Math.max(8, r.right - menu.offsetWidth)}px`;
  const close = () => { menu.remove(); document.removeEventListener("mousedown", out, true); };
  const out = e => { if (!menu.contains(e.target)) close(); };
  setTimeout(() => document.addEventListener("mousedown", out, true), 0);
  menu.onclick = e => { const a = e.target.closest("[data-a]"); if (!a) return; close();
    ({open: () => openMaterial(m.id), req: () => openRequestScreen({lines: {[m.id]: 1}}), use: () => openUseScreen({lines: {[m.id]: 1}}),
      issue: () => openIssueScreen({lines: {[m.id]: 1}}), photo: () => photoPick("material", m.id, () => stockHomeSub())})[a.dataset.a](); };
}
async function snPlacesSub(el) {
  const locs = await api.stock_locations();
  el.innerHTML = `<div class="sn-panel"><div class="sn-places">${locs.map(l => `<button class="sn-placecard" data-pl="${esc(l.id)}"><b>${esc(l.name)}</b><small>${esc(l.kind_title || "")}</small>
      <span>${l.items} ${plural(l.items, "материал", "материала", "материалов")}</span><em>${money(l.value)}</em>${l.negative ? `<small class="bad-t">меньше нуля: ${l.negative}</small>` : ""}</button>`).join("")}</div>
    ${locs.length < 2 ? `<div class="note-box" style="margin-top:12px">Кабинеты ещё не заведены. ${can("stock_edit") ? "Добавьте их во вкладке «Места хранения» — тогда можно выдавать материалы в кабинет и видеть остатки каждого." : "Попросите кладовщика или администратора добавить кабинеты."}</div>` : ""}</div>`;
  $$("[data-pl]", el).forEach(b => b.onclick = () => { SN.place = b.dataset.pl; SN.sub = "balance"; $$("#snSub button").forEach(x => x.classList.toggle("on", x.dataset.s === "balance")); stockHomeSub(); });
}
async function snLotsSub(el) {
  const lots = (SN.home && SN.home.lots) || [];
  el.innerHTML = `<div class="sn-panel">${lots.length ? `<table class="tbl sn-tbl"><thead><tr><th>Материал</th><th>Партия</th><th>Годен до</th><th class="num">Осталось</th><th></th></tr></thead><tbody>${lots.map(x => `<tr data-m="${esc(x.material_id)}" class="${x.state === "expired" ? "exp-expired" : x.state === "soon" ? "exp-soon" : ""}">
      <td><div class="sn-mat">${phHtml(x.photo_id, "", matPic(x.name, x.category))}<span><b>${esc(x.name)}</b><small>${x.code ? "Арт. " + esc(x.code) : ""}</small></span></div></td><td>${esc(x.lot || "без номера")}</td>
      <td>${x.expires ? fmtDateShort(x.expires) : "—"}</td><td class="num">${qtyFmt(x.left, x.unit)}</td>
      <td>${x.state === "expired" ? '<span class="pill exp-pill expired">просрочено</span>' : x.state === "soon" ? `<span class="pill exp-pill soon">${x.days} ${plural(x.days, "день", "дня", "дней")}</span>` : ""}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty"><b>Партий со сроком годности нет</b><span>Срок годности и номер партии указываются при приёме поставки или считываются сканером с кода «Честный знак»</span></div>`}</div>`;
  $$("tr[data-m]", el).forEach(tr => tr.onclick = () => openMaterial(tr.dataset.m));
  loadThumbs(el);
}

/* ------------------------------------------- requests and approvals */
const REQ_PILL = {draft: "", new: "st-new", accepted: "st-come", partial: "st-come", done: "st-ok", rejected: "st-cancel", cancelled: "st-done"};
const APPR_PILL = {draft: "", pending: "st-come", approved: "st-ok", done: "st-ok", rejected: "st-cancel", cancelled: "st-done"};
async function snRequestsSub(el) {
  const c = snCan(), all = c.approve || c.edit;
  const [aps, reqs, drafts] = await Promise.all([api.stock_approvals({}), api.stock_requests({}), all ? api.stock_approvals({mine: true, status: "draft"}) : Promise.resolve([])]);
  const myDrafts = all ? [...drafts, ...(await api.stock_requests({mine: true, status: "draft"}))] : [];
  const pend = aps.filter(x => x.status === "pending");
  el.innerHTML = `<div class="sn-panel">
    ${all ? "" : `<div class="note-box">Расход и списание материалов уходят на согласование менеджеру склада или директору — остатки изменятся только после согласования. Заявку менеджер сначала принимает («Принята»), потом выдаёт в кабинет.</div>`}
    <h4 class="sn-h">${all ? "Списания на согласовании" : "Мои расходы и списания"}${pend.length ? ` <i class="cnt">${pend.length}</i>` : ""}</h4>
    ${aps.length ? `<table class="tbl sn-tbl compact"><thead><tr><th>Когда</th><th>Что и где</th><th>Материалы</th><th class="num">Сумма</th><th>Статус</th>${c.approve ? "<th></th>" : ""}</tr></thead><tbody>${aps.slice(0, 60).map(x => `<tr data-ap="${esc(x.id)}">
        <td class="nowrap">${fmtDT(x.sent_at || x.created_at)}${all ? `<small class="muted" style="display:block">${esc(x.created_name || x.created_by)}</small>` : ""}</td>
        <td><b>${esc(x.kind_title)}</b><small class="muted" style="display:block">${esc([x.location_name, x.patient_name].filter(Boolean).join(" · "))}</small></td>
        <td class="muted sn-sum">${esc(x.summary)}</td><td class="num nowrap">${money(x.total)}</td>
        <td><span class="pill ${APPR_PILL[x.status] || ""}">${esc(x.status_title)}</span>${x.answer && x.status === "rejected" ? `<small class="bad-t" style="display:block">${esc(x.answer)}</small>` : ""}</td>
        ${c.approve ? `<td class="sn-actcol">${x.status === "pending" ? `<button class="btn small" data-ok="${esc(x.id)}">Согласовать</button><button class="btn ghost small" data-no="${esc(x.id)}">Отклонить</button>` : ""}</td>` : ""}</tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>${all ? "Нет списаний на согласовании" : "Вы ещё ничего не списывали"}</b></div>`}
    <h4 class="sn-h">${all ? "Заявки из кабинетов" : "Мои заявки"}</h4>
    ${reqs.length ? `<table class="tbl sn-tbl compact"><thead><tr><th>№</th><th>Кабинет</th><th>Нужно к</th><th>Приоритет</th><th class="num">Позиций</th>${all ? "<th>Кто</th>" : ""}<th>Статус</th><th></th></tr></thead><tbody>${reqs.slice(0, 60).map(x => `<tr data-rq="${esc(x.id)}">
        <td><b>${x.number ? "№ " + esc(x.number) : "—"}</b><small class="muted" style="display:block">${fmtDT(x.sent_at || x.created_at)}</small></td><td>${esc(x.location_name)}</td><td>${x.need_date ? fmtDateShort(x.need_date) : "—"}</td>
        <td><span class="sn-pri ${x.priority}">${esc(x.priority_title)}</span></td><td class="num">${x.positions}</td>${all ? `<td class="muted">${esc(x.created_name || x.created_by)}</td>` : ""}
        <td><span class="pill ${REQ_PILL[x.status] || ""}">${esc(x.status_title)}</span>${x.answer && x.status === "rejected" ? `<small class="bad-t" style="display:block">${esc(x.answer)}</small>` : ""}</td>
        <td class="nowrap">${x.status === "new" && all ? `<button class="btn ghost small" data-acc="${esc(x.id)}">Принять</button>` : ""}${["new", "accepted", "partial"].includes(x.status) && c.issue && all ? `<button class="btn small" data-iss="${esc(x.id)}">Выдать</button>` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Заявок нет</b><span>${c.request ? "«Создать заявку» — запросить материалы со склада в кабинет" : ""}</span></div>`}
    ${myDrafts.length ? `<h4 class="sn-h">Мои черновики</h4><div class="chips">${myDrafts.map(x => `<button class="chip" data-draft="${esc(x.id)}" data-dk="${x.kind ? "use" : "req"}">${x.kind ? esc(x.kind_title) : "Заявка"} · ${esc(x.location_name)} · ${fmtDT(x.updated_at || x.created_at)}</button>`).join("")}</div>` : ""}
  </div>`;
  $$("tr[data-ap]", el).forEach(tr => tr.onclick = e => { if (!e.target.closest("button")) openApproval(tr.dataset.ap); });
  $$("tr[data-rq]", el).forEach(tr => tr.onclick = e => { if (!e.target.closest("button")) openRequestView(tr.dataset.rq); });
  $$("[data-ok]", el).forEach(b => b.onclick = () => busy(b, () => decideApproval(b.dataset.ok, "approve")));
  $$("[data-no]", el).forEach(b => b.onclick = () => busy(b, () => decideApproval(b.dataset.no, "reject")));
  $$("[data-iss]", el).forEach(b => b.onclick = () => openIssueScreen({requests: [b.dataset.iss]}));
  $$("[data-acc]", el).forEach(b => b.onclick = () => busy(b, () => acceptRequest(b.dataset.acc)));
  $$("[data-draft]", el).forEach(b => b.onclick = async () => b.dataset.dk === "use" ? openUseScreen({draft: await api.stock_approval(b.dataset.draft)}) : openRequestScreen({draft: await api.stock_request(b.dataset.draft)}));
  if (!all) {  // a nurse's own drafts are in her lists already: open them from there
    $$("tr[data-ap]", el).forEach(tr => { const x = aps.find(a => a.id === tr.dataset.ap); if (x && x.status === "draft") tr.onclick = async () => openUseScreen({draft: await api.stock_approval(x.id)}); });
    $$("tr[data-rq]", el).forEach(tr => { const x = reqs.find(a => a.id === tr.dataset.rq); if (x && x.status === "draft") tr.onclick = async () => openRequestScreen({draft: await api.stock_request(x.id)}); });
  }
}
/** 3.13 «Принята»: the stock manager takes a new request into work — the nurse sees it in her requests. */
async function acceptRequest(id) {
  try { const r = await api.stock_request_accept(id); toast(`Заявка${r.number ? " № " + r.number : ""} принята`); closeModal(); refreshStatus(); if (S.stockTab === "home") stockHome(); }
  catch (e) { toast(errText(e), true); }
}
async function decideApproval(id, action) {
  let answer = "";
  if (action === "reject") {
    const v = await askInput("Отклонить списание", [{label: "Причина — сотрудник увидит её", value: ""}], {ok: "Отклонить", danger: true});
    if (!v) return; answer = v[0];
  }
  try {
    await api.stock_approval_decide(id, action, answer);
    toast(action === "approve" ? "Согласовано — материалы списаны" : "Отклонено");
    closeModal(); refreshStatus(); if (S.stockTab === "home") stockHome();
  } catch (e) { toast(errText(e), true); }
}
async function openApproval(id) {
  const x = await api.stock_approval(id), f = x.form || {}, c = snCan();
  const box = modal(`<div class="m-h"><h3>${esc(x.kind_title)} · ${esc(x.status_title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <dl class="kv eq-kv">${[["Дата и время", `${fmtDateShort(f.date)} ${esc(f.time || "")}`], ["Кабинет", esc(x.location_name)], ["Пациент", esc(f.patient_name)], ["Услуга", esc(f.service_title)],
        ["Причина", esc(f.reason)], ["Комментарий", esc(f.comment)], ["Сотрудник", esc(x.created_name || x.created_by)], ["Отправлено", fmtDT(x.sent_at)],
        ["Решение", x.decided_at ? `${esc(x.decided_name || x.decided_by)}, ${fmtDT(x.decided_at)}` : ""], ["Ответ", esc(x.answer)]].filter(r => r[1] && r[1].trim()).map(r => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")}</dl>
      <table class="tbl sn-tbl compact"><thead><tr><th>Материал</th>${x.status === "pending" ? '<th class="num">Сейчас в кабинете</th>' : ""}<th class="num">Количество</th><th class="num">Сумма</th></tr></thead><tbody>${(f.lines || []).map(l => `<tr>
        <td><div class="sn-mat">${phHtml(l.photo_id, "", matPic(l.name, l.category))}<span><b>${esc(l.name)}</b><small>${l.code ? "Арт. " + esc(l.code) : ""}</small></span></div></td>
        ${x.status === "pending" ? `<td class="num ${l.balance < l.qty ? "bad-t" : ""}">${qtyFmt(l.balance, l.unit)}</td>` : ""}<td class="num"><b>${qtyFmt(l.qty, l.unit)}</b></td><td class="num">${money(l.qty * (l.price || 0))}</td></tr>`).join("")}</tbody></table>
      ${x.doc_id ? `<div class="muted">Акт списания: ${esc(x.doc_id)}</div>` : ""}</div>
    <div class="m-f">${x.status === "pending" && !c.approve && x.created_by === (ME && ME.login) ? `<button class="btn ghost small danger" id="apCancel">Отменить</button>` : ""}<span class="muted">Итого ${money(x.total)}</span>
      <button class="btn ghost" data-close>Закрыть</button>${x.status === "pending" && c.approve ? `<button class="btn ghost" id="apNo">Отклонить</button><button class="btn" id="apOk">Согласовать и списать</button>` : ""}
      ${x.doc_id ? `<button class="btn ghost" id="apPrint">Печать акта</button>` : ""}</div>`, {wide: true});
  loadThumbs(box);
  const on = (s, fn) => { const b = $(s, box); if (b) b.onclick = () => busy(b, fn); };
  on("#apOk", () => decideApproval(id, "approve")); on("#apNo", () => decideApproval(id, "reject"));
  on("#apPrint", () => printStockDoc(x.doc_id));
  on("#apCancel", async () => { if (!(await ask("Отменить это списание?", {danger: true, ok: "Отменить", cancel: "Не отменять"}))) return; await api.stock_approval_cancel(id); closeModal(); toast("Отменено"); stockHome(); });
}
async function openRequestView(id) {
  const x = await api.stock_request(id), c = snCan(), all = c.approve || c.edit;
  const box = modal(`<div class="m-h"><h3>Заявка ${x.number ? "№ " + esc(x.number) : "(черновик)"} · ${esc(x.location_name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <dl class="kv eq-kv">${[["Статус", `<span class="pill ${REQ_PILL[x.status] || ""}">${esc(x.status_title)}</span>`], ["Нужно к", x.need_date ? fmtDateShort(x.need_date) : ""],
        ["Приоритет", `<span class="sn-pri ${x.priority}">${esc(x.priority_title)}</span>`], ["Кто", esc(x.created_name || x.created_by)], ["Отправлена", fmtDT(x.sent_at)],
        ["Принята", x.accepted_at ? `${esc(x.accepted_name || x.accepted_by)}, ${fmtDT(x.accepted_at)}` : ""],
        ["Комментарий", esc(x.comment)], ["Ответ", esc(x.answer)]].filter(r => r[1] && String(r[1]).trim() && r[1] !== "—").map(r => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")}</dl>
      <table class="tbl sn-tbl compact"><thead><tr><th>Материал</th><th class="num">Нужно</th><th class="num">Выдано</th>${all ? '<th class="num">На складе</th><th class="num">В кабинете</th>' : ""}</tr></thead><tbody>${x.lines.map(l => `<tr>
        <td><div class="sn-mat">${phHtml(l.photo_id, "", matPic(l.name, l.category))}<span><b>${esc(l.name)}</b><small>${l.code ? "Арт. " + esc(l.code) : ""}</small></span></div></td><td class="num"><b>${qtyFmt(l.qty, l.unit)}</b></td>
        <td class="num ${l.issued >= l.qty ? "ok-t" : ""}">${l.issued ? qtyFmt(l.issued, l.unit) : "—"}</td>${all ? `<td class="num ${l.at_main < l.qty - l.issued ? "bad-t" : ""}">${qtyFmt(l.at_main, l.unit)}</td><td class="num">${qtyFmt(l.at_place, l.unit)}</td>` : ""}</tr>`).join("")}</tbody></table></div>
    <div class="m-f">${["draft", "new"].includes(x.status) && x.created_by === (ME && ME.login) ? `<button class="btn ghost small danger" id="rqCancel">Отменить заявку</button>` : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Закрыть</button>${x.status === "draft" ? `<button class="btn" id="rqEdit">Продолжить</button>` : ""}
      ${["new", "accepted", "partial"].includes(x.status) && all ? `<button class="btn ghost" id="rqNo">Отклонить</button>${x.status === "new" ? `<button class="btn ghost" id="rqAcc">Принять</button>` : ""}${c.issue ? `<button class="btn" id="rqIss">Выдать</button>` : ""}` : ""}</div>`, {wide: true});
  loadThumbs(box);
  const on = (s, fn) => { const b = $(s, box); if (b) b.onclick = () => busy(b, fn); };
  on("#rqEdit", () => { closeModal(); openRequestScreen({draft: x}); });
  on("#rqIss", () => { closeModal(); openIssueScreen({requests: [x.id]}); });
  on("#rqAcc", () => acceptRequest(x.id));
  on("#rqNo", async () => { const v = await askInput("Отклонить заявку", [{label: "Причина — медсестра увидит её", value: ""}], {ok: "Отклонить", danger: true}); if (!v) return;
    try { await api.stock_request_reject(x.id, v[0]); closeModal(); toast("Заявка отклонена"); stockHome(); } catch (e) { toast(errText(e), true); } });
  on("#rqCancel", async () => { if (!(await ask("Отменить заявку?", {danger: true, ok: "Отменить", cancel: "Не отменять"}))) return; await api.stock_request_cancel(x.id); closeModal(); toast("Заявка отменена"); stockHome(); });
}

/* ------------------------------------------ the screens: shared parts */
function snScreen(icon, title, sub, inner) {
  $("#stockBody").innerHTML = `<div class="sn-screen"><div class="sn-crumb"><button class="linkbtn" id="snBack">${SN_ICON.back}Склад</button><span>›</span><b>${title}</b></div>
    <div class="sn-head"><i class="sn-t-${icon}">${SN_ICON[icon]}</i><div><h2>${title}</h2><span class="muted">${sub}</span></div></div>${inner}</div>`;
  $("#snBack").onclick = () => stockHome();
  $("#stockBody").scrollTop = 0;
}
const snStep = (n, t) => `<h4 class="sn-num"><i>${n}</i>${t}</h4>`;
/** The material picker of every screen: search (a scanner too), categories, the table with − qty +. */
function pickerHtml(title, qtyTitle = "Кол-во", extraChip = "") {
  return `<section class="sn-card sn-pick">${title}
    <div class="sn-search"><label class="sn-q">${SN_ICON.search}<input id="pkQ" placeholder="Найти материал (название, артикул) или сканируйте штрихкод" autocomplete="off"></label>
      <button class="icon-btn sn-scan" id="pkScan" title="Сканер штрихкода">${SN_ICON.scan}</button></div>
    <div class="sn-chips" id="pkCats"></div><div class="muted sn-scanmsg" id="pkMsg"></div>
    <div class="sn-pick-tbl"><table class="tbl sn-tbl"><thead><tr><th style="width:30px"></th><th>Материал</th><th>Остаток</th><th class="sn-qty-h">${qtyTitle}</th><th></th></tr></thead><tbody id="pkRows"></tbody></table></div>${extraChip}</section>`;
}
/** st.rows — the materials with the balance to show; o.qty(mid) / o.set(mid, qty) / o.chips — extra filters; o.onScan(material, parsed). */
function bindPicker(st, o) {
  let cat = o.cat || "", q = "";
  const draw = () => {
    const chips = [["", "Все"], ...(o.chips ? o.chips() : []), ...[...new Set(st.rows.map(m => m.category).filter(Boolean))].map(c => [c, c])];
    $("#pkCats").innerHTML = chips.map(([k, t]) => `<button class="chip ${k === cat ? "on" : ""}" data-c="${esc(k)}">${esc(t)}</button>`).join("");
    $$("#pkCats [data-c]").forEach(b => b.onclick = () => { cat = b.dataset.c; draw(); });
    const ql = q.toLowerCase();
    const list = st.rows.filter(m => (!cat || m.category === cat || (o.chipFilter && o.chipFilter(cat, m))) &&
      (!ql || `${m.name} ${m.code} ${m.barcode} ${m.category}`.toLowerCase().includes(ql)));
    $("#pkRows").innerHTML = list.length ? list.map(m => { const n = o.qty(m.id);
      return `<tr data-pk="${esc(m.id)}" class="${n > 0 ? "on" : ""}"><td><input type="checkbox" ${n > 0 ? "checked" : ""} data-chk></td>
        <td><div class="sn-mat">${phHtml(m.photo_id, "", matPic(m.name, m.category))}<span><b>${esc(m.name)}</b><small>${m.code ? "Арт. " + esc(m.code) : esc(m.category || "")}</small></span></div></td>
        <td>${balPill(m, o.balance ? o.balance(m) : m.balance)}</td>
        <td><div class="sn-step"><button data-d="-1" ${n > 0 ? "" : "disabled"}>−</button><input class="num" value="${n || 0}" inputmode="decimal" data-q><button data-d="1">+</button></div></td>
        <td class="muted sn-unit">${esc(m.unit || "")}</td></tr>`; }).join("") : `<tr><td colspan="5"><div class="empty"><b>Ничего не найдено</b></div></td></tr>`;
    $$("#pkRows tr[data-pk]").forEach(tr => {
      const mid = tr.dataset.pk;
      $$("[data-d]", tr).forEach(b => b.onclick = () => { o.set(mid, Math.max(0, snNum(o.qty(mid) + +b.dataset.d))); draw(); });
      $("[data-q]", tr).onchange = e => { o.set(mid, Math.max(0, snNum(e.target.value))); draw(); };
      $("[data-chk]", tr).onchange = e => { o.set(mid, e.target.checked ? Math.max(1, o.qty(mid)) : 0); draw(); };
    });
    loadThumbs($("#pkRows"));
    if (o.after) o.after();
  };
  let t;
  const inp = $("#pkQ");
  inp.oninput = () => { clearTimeout(t); t = setTimeout(() => { q = inp.value.trim(); draw(); }, 150); };
  inp.onkeydown = async e => {  // a scanner types the code and presses Enter: +1 of that material
    if (e.key !== "Enter") return;
    e.preventDefault();
    const code = inp.value.trim(); if (!code) return;
    const msg = (s, bad) => { const m = $("#pkMsg"); if (m) { m.textContent = s; m.className = "sn-scanmsg " + (bad ? "bad-t" : "ok-t"); } };
    let p = null;
    try { p = await api.stock_scan(code); } catch (err) { p = null; }
    if (p && p.material) {
      if (!st.rows.some(m => m.id === p.material.id)) st.rows.push(p.material);
      if (o.onScan) o.onScan(p.material, p); else o.set(p.material.id, snNum(o.qty(p.material.id) + 1));
      inp.value = ""; q = ""; draw(); msg(`✓ ${p.material.name}${p.lot ? " · партия " + p.lot : ""}${p.expires ? " · годен до " + fmtDateShort(p.expires) : ""}`);
      return;
    }
    const one = st.rows.filter(m => `${m.name} ${m.code}`.toLowerCase().includes(code.toLowerCase()));
    if (one.length === 1) { o.set(one[0].id, snNum(o.qty(one[0].id) + 1)); inp.value = ""; q = ""; draw(); msg("✓ " + one[0].name); return; }
    if (o.onUnknown && p) return o.onUnknown(p, draw, msg);
    msg(`Штрихкод ${code} не найден в справочнике`, true);
  };
  $("#pkScan").onclick = () => { inp.focus(); inp.select(); const m = $("#pkMsg"); if (m) { m.textContent = "Наведите сканер на штрихкод — материал добавится сам"; m.className = "sn-scanmsg muted"; } };
  setTimeout(() => inp.focus(), 50);
  draw();
  return {draw, setCat: c => { cat = c; draw(); }};
}
const linesOf = obj => Object.entries(obj).filter(([, q]) => q > 0).map(([material_id, qty]) => ({material_id, qty}));
function cartHtml(lines, byId, {qtyCls = "", removable = true} = {}) {
  return lines.length ? lines.map(l => { const m = byId[l.material_id] || {name: l.name || "?", unit: l.unit || ""};
    return `<div class="sn-ci">${phHtml(m.photo_id, "", matPic(m.name, m.category))}<span><b>${esc(m.name)}</b><small>${m.code ? "Арт. " + esc(m.code) : ""}</small></span><em class="${qtyCls}">${qtyFmt(l.qty, m.unit)}</em>${removable ? `<button class="x" data-rm="${esc(l.material_id)}" title="Убрать">×</button>` : ""}</div>`; }).join("")
    : `<div class="muted sn-none">Отметьте материалы слева или сканируйте штрихкод</div>`;
}
const placeOptions = (cur, {withMain = true, onlyCab = false} = {}) => snPlaces().filter(l => (withMain || l.id) && (!onlyCab || l.id)).map(l => `<option value="${esc(l.id)}" ${l.id === (cur ?? "") ? "selected" : ""}>${esc(l.name)}</option>`).join("");
function defaultCabinet() { const saved = snLS("cab"); const cabs = snCabinets(); return cabs.some(l => l.id === saved) ? saved : (cabs[0] || {id: ""}).id; }
async function ensureStk() { if (!STK.locations || !STK.locations.length) STK = await api.stock_summary(); if (!SN.home) SN.home = await api.stock_home(SN.days); }

/* ------------------------------------------------------ «Создать заявку» */
async function openRequestScreen(preset = {}) {
  await ensureStk();
  const d = preset.draft;
  const st = {id: d ? d.id : "", location_id: d ? d.location_id : defaultCabinet(), need_date: d ? d.need_date || "" : addDays(iso(new Date()), 1),
    priority: d ? d.priority : "normal", comment: d ? d.comment || "" : "", lines: {}, mode: "catalog", rows: []};
  (d ? d.lines : []).forEach(l => st.lines[l.material_id] = l.qty);
  Object.assign(st.lines, preset.lines || {});
  const [rows, opts, mine] = await Promise.all([api.materials("", false, false, hasPlaces() ? "" : null), api.stock_use_options(""), api.stock_requests({mine: true})]);
  st.rows = rows;
  const byId = Object.fromEntries(rows.map(m => [m.id, m]));
  const tpls = opts.services.filter(s => s.norms.length);
  snScreen("request", "Создать заявку", "Запрос на выдачу материалов со склада в кабинет", `<div class="sn-cols">
    <section class="sn-card sn-c1">${snStep(1, "Основные данные")}
      <label class="fl">Кабинет *<select class="input" id="rqLoc">${placeOptions(st.location_id, {withMain: !snCabinets().length})}</select></label>
      <label class="fl">Дата потребности *<input class="input" type="date" id="rqDate" value="${esc(st.need_date)}"></label>
      <div class="fl">Приоритет<div class="sn-pris" id="rqPri">${Object.entries(SN_PRI).map(([k, t]) => `<button class="sn-pri-b ${k}" data-p="${k}">${t}</button>`).join("")}</div></div>
      <label class="fl">Комментарий<textarea class="input" id="rqCom" rows="4" placeholder="Например: подготовка к имплантации, плановый расход на неделю">${esc(st.comment)}</textarea></label></section>
    <div class="sn-c2">${pickerHtml(`<div class="sn-pick-h">${snStep(2, "Выбор материалов")}<div class="seg" id="rqMode"><button data-m="catalog" class="on">По каталогу</button><button data-m="template">Из шаблона</button></div></div>`, "К выдаче")}
      <section class="sn-card" id="rqTpl" hidden>${snStep(2, "Шаблоны")}<div class="muted">Набор материалов по нормам услуги или повтор прошлой заявки — количества можно поправить.</div>
        <div class="sn-tpls">${tpls.map(s => `<button class="sn-tpl" data-tpl="${esc(s.id)}"><b>${esc(s.title)}</b><small>${esc(s.code || "")} · ${s.norms.length} ${plural(s.norms.length, "материал", "материала", "материалов")}</small></button>`).join("")}
          ${mine.filter(r => r.status !== "draft").slice(0, 6).map(r => `<button class="sn-tpl" data-old="${esc(r.id)}"><b>Повторить заявку ${r.number ? "№ " + esc(r.number) : ""}</b><small>${esc(r.location_name)} · ${r.positions} поз. · ${fmtDateShort((r.sent_at || r.created_at).slice(0, 10))}</small></button>`).join("")}
          ${!tpls.length && !mine.length ? `<div class="empty"><b>Шаблонов пока нет</b><span>Шаблоны — это нормы расхода по услугам (вкладка «Нормы списания») и ваши прошлые заявки</span></div>` : ""}</div></section></div>
    <div class="sn-c3"><section class="sn-card">${snStep(3, "Состав заявки")}<button class="icon-btn sn-clear" id="rqClear" title="Очистить">${SN_ICON.trash}</button><div id="rqCart"></div>
        <div class="sn-total"><span>Итого позиций:</span><b id="rqN">0</b></div></section>
      <section class="sn-card sn-info"><h4>Ожидаемая выдача</h4><dl><dt>Дата потребности</dt><dd id="rqIDate"></dd><dt>Кабинет</dt><dd id="rqICab"></dd><dt>Приоритет</dt><dd id="rqIPri"></dd></dl></section>
      <div class="sn-acts"><button class="btn sn-big" id="rqSend">${SN_ICON.ok}Отправить заявку</button><button class="btn ghost" id="rqDraft">Сохранить как черновик</button></div>
      <div class="auth-err" id="rqErr"></div></div></div>`);
  const cartDraw = () => {
    const lines = linesOf(st.lines);
    $("#rqCart").innerHTML = cartHtml(lines, byId); $("#rqN").textContent = lines.length;
    $$("#rqCart [data-rm]").forEach(b => b.onclick = () => { delete st.lines[b.dataset.rm]; pk.draw(); });
    $("#rqIDate").textContent = $("#rqDate").value ? fmtDateShort($("#rqDate").value) : "—";
    $("#rqICab").textContent = snPlaceName($("#rqLoc").value); $("#rqIPri").textContent = SN_PRI[st.priority];
    $$("#rqPri [data-p]").forEach(b => b.classList.toggle("on", b.dataset.p === st.priority));
    loadThumbs($("#rqCart"));
  };
  const pk = bindPicker(st, {qty: id => st.lines[id] || 0, set: (id, q) => { if (q > 0) st.lines[id] = q; else delete st.lines[id]; }, after: cartDraw});
  $$("#rqPri [data-p]").forEach(b => b.onclick = () => { st.priority = b.dataset.p; cartDraw(); });
  $("#rqDate").onchange = cartDraw; $("#rqLoc").onchange = cartDraw;
  $("#rqClear").onclick = () => { st.lines = {}; pk.draw(); };
  $$("#rqMode [data-m]").forEach(b => b.onclick = () => { st.mode = b.dataset.m; $$("#rqMode [data-m]").forEach(x => x.classList.toggle("on", x === b));
    $("#rqTpl").hidden = st.mode !== "template"; $(".sn-c2 .sn-pick").classList.toggle("sn-collapsed", st.mode === "template"); });
  $$("[data-tpl]").forEach(b => b.onclick = () => { const s = tpls.find(x => x.id === b.dataset.tpl); s.norms.forEach(n => st.lines[n.material_id] = snNum((st.lines[n.material_id] || 0) + n.qty)); pk.draw(); toast("Добавлено: " + s.title); });
  $$("[data-old]").forEach(b => b.onclick = () => { const r = mine.find(x => x.id === b.dataset.old); r.lines.forEach(l => st.lines[l.material_id] = snNum((st.lines[l.material_id] || 0) + l.qty)); pk.draw(); toast("Добавлено из прошлой заявки"); });
  const save = send => async () => {
    const f = {id: st.id, location_id: $("#rqLoc").value, need_date: $("#rqDate").value, priority: st.priority, comment: $("#rqCom").value, lines: linesOf(st.lines), send};
    try {
      if (send && !f.need_date) throw new Error("Укажите дату потребности");
      const r = await api.stock_request_save(f); st.id = r.id; snLS("cab", f.location_id);
      toast(send ? `Заявка № ${r.number} отправлена` : "Черновик сохранён"); SN.sub = "requests"; refreshStatus(); stockHome();
    } catch (e) { $("#rqErr").textContent = errText(e); }
  };
  $("#rqSend").onclick = e => busy(e.currentTarget, save(true));
  $("#rqDraft").onclick = e => busy(e.currentTarget, save(false));
}

/* ------------------------------------------------- «Зафиксировать расход» */
async function openUseScreen(preset = {}) {
  await ensureStk();
  const d = preset.draft, f0 = (d && d.form) || {}, now = new Date();
  const c = snCan();
  const st = {id: d ? d.id : "", kind: f0.kind || preset.kind || "consume", location_id: d ? f0.location_id || "" : (SN.place ?? defaultCabinet()),
    date: f0.date || iso(now), time: f0.time || `${pad(now.getHours())}:${pad(now.getMinutes())}`, patient: f0.patient_id ? {id: f0.patient_id, name: f0.patient_name} : null,
    service_id: f0.service_id || "", reason: f0.reason && f0.kind === "writeoff" ? f0.reason : "", comment: f0.comment || "", lines: {}, rows: []};
  (f0.lines || []).forEach(l => st.lines[l.material_id] = l.qty);
  Object.assign(st.lines, preset.lines || {});
  const opts = await api.stock_use_options("");
  const load = async () => { st.rows = await api.materials("", false, false, hasPlaces() ? st.location_id : null); st.byId = Object.fromEntries(st.rows.map(m => [m.id, m])); };
  await load();
  const pat = c.patients;
  snScreen("use", "Зафиксировать расход", c.direct ? "Учёт использования материалов в лечении" : "Учёт использования материалов в лечении · списание после согласования менеджером", `${c.direct ? "" : snFlowHtml()}<div class="sn-cols">
    <div class="sn-c1"><section class="sn-card">${snStep(1, "Контекст расхода")}
      <div class="seg sn-kind" id="usKind"><button data-k="consume" title="Материалы, использованные при лечении">Расход</button><button data-k="writeoff" title="Брак, разбитая ампула, истёк срок">Списание</button></div>
      <div class="grid2"><label class="fl">Дата<input class="input" type="date" id="usDate" value="${esc(st.date)}"></label><label class="fl">Время<input class="input" type="time" id="usTime" value="${esc(st.time)}"></label></div>
      ${hasPlaces() ? `<label class="fl">Кабинет<select class="input" id="usLoc">${placeOptions(st.location_id)}</select></label>` : ""}
      <div id="usConsume">
        ${pat ? `<label class="fl">Пациент<div class="sn-pat"><input class="input" id="usPat" placeholder="Фамилия или телефон" autocomplete="off" value="${esc(st.patient ? st.patient.name : "")}"><button class="x" id="usPatX" title="Убрать" ${st.patient ? "" : "hidden"}>×</button><div class="sn-drop" id="usPatDrop" hidden></div></div></label>` : ""}
        <label class="fl">Услуга / процедура<select class="input" id="usSvc"><option value="">— не указана —</option>${opts.services.map(s => `<option value="${esc(s.id)}" ${s.id === st.service_id ? "selected" : ""}>${esc([s.code, s.title].filter(Boolean).join(" — "))}${s.norms.length ? " · нормы" : ""}</option>`).join("")}</select></label>
        <div class="muted sn-hint">У услуги с нормами списания материалы подставятся сами.</div></div>
      <div id="usWo" hidden><label class="fl">Причина списания *<input class="input" id="usReason" list="usReasons" value="${esc(st.reason)}" placeholder="например: повреждена упаковка"></label>
        <datalist id="usReasons"><option value="Истёк срок годности"><option value="Повреждение, брак"><option value="Разбита ампула / карпула"><option value="Использовано на общие нужды"><option value="Утеря"></datalist></div></section>
      <section class="sn-card">${snStep("✎", "Комментарий")}<textarea class="input" id="usCom" rows="3" placeholder="Например: имплантация 36 зуба, расход по протоколу">${esc(st.comment)}</textarea></section></div>
    <div class="sn-c2">${pickerHtml(snStep(2, "Добавьте использованные материалы"))}</div>
    <div class="sn-c3"><section class="sn-card">${snStep(3, "Расход по операции")}<div id="usCart"></div><div class="sn-total"><span>Итого позиций:</span><b id="usN">0</b></div></section>
      <section class="sn-card sn-info"><h4>Остатки после фиксации</h4><div id="usAfter"></div>${c.direct ? "" : `<div class="sn-note">Остатки изменятся после согласования менеджером или директором.</div>`}</section></div></div>
    <div class="sn-bar"><button class="btn ghost" id="usClear">${SN_ICON.trash}Очистить</button><span class="grow"></span><div class="auth-err" id="usErr"></div>
      <button class="btn ghost" id="usDraft">Сохранить черновик</button><button class="btn sn-big" id="usOk">${SN_ICON.ok}${c.direct ? "Зафиксировать расход" : "Отправить на согласование"}</button></div>`);
  const kindDraw = () => {
    $$("#usKind [data-k]").forEach(b => b.classList.toggle("on", b.dataset.k === st.kind));
    $("#usConsume").hidden = st.kind !== "consume"; $("#usWo").hidden = st.kind !== "writeoff";
    $("#usOk").innerHTML = SN_ICON.ok + (c.direct ? (st.kind === "consume" ? "Зафиксировать расход" : "Списать") : "Отправить на согласование");
  };
  const cartDraw = () => {
    const lines = linesOf(st.lines);
    $("#usCart").innerHTML = cartHtml(lines, st.byId); $("#usN").textContent = lines.length;
    $$("#usCart [data-rm]").forEach(b => b.onclick = () => { delete st.lines[b.dataset.rm]; pk.draw(); });
    $("#usAfter").innerHTML = lines.length ? lines.map(l => { const m = st.byId[l.material_id] || {}; const after = snNum((m.balance || 0) - l.qty);
      return `<div class="sn-after ${after < 0 ? "bad-t" : ""}"><span>${esc(m.name || "")}:</span><b>${qtyFmt(m.balance || 0)} → ${qtyFmt(after, m.unit)}</b></div>`; }).join("") : `<div class="muted">—</div>`;
    loadThumbs($("#usCart"));
  };
  const pk = bindPicker(st, {qty: id => st.lines[id] || 0, set: (id, q) => { if (q > 0) st.lines[id] = q; else delete st.lines[id]; }, after: cartDraw});
  kindDraw();
  $$("#usKind [data-k]").forEach(b => b.onclick = () => { st.kind = b.dataset.k; kindDraw(); });
  const ul = $("#usLoc"); if (ul) ul.onchange = async () => { st.location_id = ul.value; await load(); pk.draw(); };
  $("#usSvc").onchange = e => { st.service_id = e.target.value; const s = opts.services.find(x => x.id === st.service_id);
    if (s && s.norms.length) { s.norms.forEach(n => { if (!st.lines[n.material_id]) st.lines[n.material_id] = n.qty; }); pk.draw(); toast("Материалы по нормам услуги добавлены"); } };
  const pi = $("#usPat");
  if (pi) {
    let t; const drop = $("#usPatDrop");
    pi.oninput = () => { st.patient = null; $("#usPatX").hidden = true; clearTimeout(t); t = setTimeout(async () => {
      const q = pi.value.trim(); if (q.length < 2) { drop.hidden = true; return; }
      const r = await api.stock_use_options(q);
      drop.innerHTML = r.patients.length ? r.patients.map(p => `<button data-p="${esc(p.id)}" data-n="${esc(p.name)}"><b>${esc(p.name)}</b><small>${esc([p.birth ? fmtDateShort(p.birth) : "", p.phone].filter(Boolean).join(" · "))}</small></button>`).join("") : `<div class="muted">Не найдено</div>`;
      drop.hidden = false;
      $$("[data-p]", drop).forEach(b => b.onclick = () => { st.patient = {id: b.dataset.p, name: b.dataset.n}; pi.value = b.dataset.n; drop.hidden = true; $("#usPatX").hidden = false; });
    }, 220); };
    pi.onblur = () => setTimeout(() => { drop.hidden = true; }, 200);
    $("#usPatX").onclick = () => { st.patient = null; pi.value = ""; $("#usPatX").hidden = true; };
  }
  $("#usClear").onclick = async () => { if (linesOf(st.lines).length && !(await ask("Очистить список материалов?", {ok: "Очистить"}))) return; st.lines = {}; pk.draw(); };
  const send = draft => async () => {
    const f = {id: st.id, kind: st.kind, date: $("#usDate").value, time: $("#usTime").value, location_id: ul ? ul.value : "", comment: $("#usCom").value,
      patient_id: st.kind === "consume" && st.patient ? st.patient.id : "", service_id: st.kind === "consume" ? $("#usSvc").value : "", reason: $("#usReason").value,
      lines: linesOf(st.lines), draft};
    try {
      const r = await api.stock_use(f); st.id = r.id; if (f.location_id) snLS("cab", f.location_id);
      toast(r.status === "draft" ? "Черновик сохранён" : r.status === "pending" ? "Отправлено на согласование менеджеру" : (st.kind === "consume" ? "Расход зафиксирован" : "Материалы списаны"));
      if (r.status === "pending" || r.status === "draft") SN.sub = "requests";
      refreshStatus(); stockHome();
    } catch (e) { $("#usErr").textContent = errText(e); }
  };
  $("#usOk").onclick = e => busy(e.currentTarget, send(false));
  $("#usDraft").onclick = e => busy(e.currentTarget, send(true));
}

/** 3.13: how a nurse's consumption and write-off go — nothing leaves the stock until the stock manager checks it. */
function snFlowHtml() {
  return `<div class="sn-flow" role="note"><b>Списание через согласование</b>
    <ol><li><i>1</i><span>Вы отправляете расход или списание</span></li><li><i>2</i><span>Менеджер склада проверяет, что списано правомерно</span></li>
      <li><i>3</i><span>Только после согласования материал уходит со склада</span></li></ol><small>Отклонённое вернётся к вам с причиной — во вкладке «Мои заявки».</small></div>`;
}

/* ---------------------------------------------------- «Выдать в кабинет» */
async function openIssueScreen(preset = {}) {
  await ensureStk();
  if (!snCabinets().length) {
    snScreen("issue", "Выдать в кабинет", "Перемещение материалов из центрального склада в кабинет", `<div class="sn-card"><div class="empty"><b>Кабинеты ещё не заведены</b>
      <span>${can("stock_edit") ? "Добавьте кабинеты во вкладке «Места хранения» — и выдавайте материалы со склада в кабинет." : "Попросите кладовщика или администратора добавить кабинеты."}</span>
      ${can("stock_edit") ? `<button class="btn" id="isPlaces">Открыть «Места хранения»</button>` : ""}</div></div>`);
    const b = $("#isPlaces"); if (b) b.onclick = () => stockGo("stock", "places");
    return;
  }
  const st = {step: 1, from: "", to: defaultCabinet(), req: new Set(), lines: {}, comment: "", rows: [], reqs: [], doc: null};
  Object.assign(st.lines, preset.lines || {});
  const all = await api.stock_requests({status: "open"});
  st.reqs = all;
  if (preset.requests && preset.requests.length) { const r = all.find(x => x.id === preset.requests[0]); if (r) st.to = r.location_id || st.to; }
  const load = async () => { st.rows = await api.materials("", false, false, st.from); st.byId = Object.fromEntries(st.rows.map(m => [m.id, m])); };
  await load();
  const reqLeft = r => r.lines.map(l => ({material_id: l.material_id, qty: snNum(l.qty - (l.issued || 0))})).filter(l => l.qty > 0);
  const toggleReq = (id, on) => {
    const r = st.reqs.find(x => x.id === id); if (!r) return;
    if (on) { st.req.add(id); reqLeft(r).forEach(l => st.lines[l.material_id] = snNum((st.lines[l.material_id] || 0) + l.qty)); }
    else { st.req.delete(id); reqLeft(r).forEach(l => { const v = snNum((st.lines[l.material_id] || 0) - l.qty); if (v > 0) st.lines[l.material_id] = v; else delete st.lines[l.material_id]; }); }
  };
  (preset.requests || []).forEach(id => toggleReq(id, true));
  const fromReq = () => { const s = new Set(); st.reqs.filter(r => st.req.has(r.id)).forEach(r => r.lines.forEach(l => s.add(l.material_id))); return s; };
  const steps = () => `<div class="sn-steps">${["Выбор материалов", "Подтверждение", "Выдача завершена"].map((t, i) => `<div class="${st.step === i + 1 ? "on" : st.step > i + 1 ? "done" : ""}"><i>${st.step > i + 1 ? SN_ICON.ok : i + 1}</i>${t}</div>${i < 2 ? "<span>→</span>" : ""}`).join("")}</div>`;
  const step1 = () => {
    snScreen("issue", "Выдать в кабинет", "Перемещение материалов из центрального склада в кабинет", `${steps()}<div class="sn-cols">
      <div class="sn-c1"><section class="sn-card"><label class="fl">Откуда<select class="input" id="isFrom">${placeOptions(st.from)}</select></label>
          <label class="fl">Куда (кабинет)<select class="input" id="isTo">${placeOptions(st.to, {withMain: false})}</select></label></section>
        <section class="sn-card"><h4>Заявки из кабинета <i class="cnt" id="isRqN"></i></h4><div id="isReqs"></div><button class="btn ghost sn-wide" id="isNoReq">⊕ Выдать без заявки</button></section></div>
      <div class="sn-c2">${pickerHtml("", "К выдаче")}</div>
      <div class="sn-c3"><section class="sn-card"><h4>Корзина выдачи <i class="cnt" id="isN">0</i></h4><button class="icon-btn sn-clear" id="isClear" title="Очистить">${SN_ICON.trash}</button><div id="isCart"></div>
          <div class="sn-total"><span>Всего позиций:</span><b id="isPos">0</b></div><div class="sn-total"><span>Общее количество:</span><b id="isQty">0</b></div>
          <textarea class="input" id="isCom" rows="2" placeholder="Комментарий (например, для какой процедуры)">${esc(st.comment)}</textarea></section>
        <div class="sn-acts"><button class="btn sn-big" id="isNext">Перейти к подтверждению ›</button><button class="btn ghost" id="isCancel">Отмена</button></div><div class="auth-err" id="isErr"></div></div></div>`);
    const reqDraw = () => {
      const list = st.reqs.filter(r => (r.location_id || "") === st.to);
      $("#isRqN").textContent = list.length || "";
      $("#isReqs").innerHTML = list.length ? list.map(r => `<label class="sn-req ${st.req.has(r.id) ? "on" : ""}"><input type="checkbox" data-rq="${esc(r.id)}" ${st.req.has(r.id) ? "checked" : ""}>
          <span><b>Заявка № ${esc(r.number)}</b><small>от ${fmtDateShort((r.sent_at || r.created_at).slice(0, 10))} · ${r.positions} ${plural(r.positions, "позиция", "позиции", "позиций")}${r.need_date ? " · к " + fmtDateShort(r.need_date) : ""}</small><small>${esc(r.created_name || "")}</small></span>
          <em class="pill ${REQ_PILL[r.status]}">${esc(r.status_title)}</em>${r.priority !== "normal" ? `<em class="sn-pri ${r.priority}">${esc(r.priority_title)}</em>` : ""}</label>`).join("")
        : `<div class="muted sn-none">Открытых заявок из этого кабинета нет</div>`;
      $$("#isReqs [data-rq]").forEach(i => i.onchange = () => { toggleReq(i.dataset.rq, i.checked); reqDraw(); pk.draw(); });
    };
    const cartDraw = () => {
      const lines = linesOf(st.lines);
      $("#isCart").innerHTML = cartHtml(lines, st.byId); $("#isN").textContent = lines.length; $("#isPos").textContent = lines.length;
      $("#isQty").textContent = qtyFmt(lines.reduce((a, l) => a + l.qty, 0), "ед.");
      $$("#isCart [data-rm]").forEach(b => b.onclick = () => { delete st.lines[b.dataset.rm]; pk.draw(); });
      loadThumbs($("#isCart"));
    };
    const pk = bindPicker(st, {qty: id => st.lines[id] || 0, set: (id, q) => { if (q > 0) st.lines[id] = q; else delete st.lines[id]; }, after: cartDraw,
      chips: () => st.req.size ? [["__req", `Из заявки (${fromReq().size})`]] : [], chipFilter: (c, m) => c === "__req" && fromReq().has(m.id), cat: st.req.size ? "__req" : ""});
    reqDraw();
    $("#isFrom").onchange = async e => { st.from = e.target.value; await load(); pk.draw(); };
    $("#isTo").onchange = e => { st.to = e.target.value; [...st.req].forEach(id => toggleReq(id, false)); reqDraw(); pk.draw(); };
    $("#isNoReq").onclick = () => { [...st.req].forEach(id => toggleReq(id, false)); reqDraw(); pk.setCat(""); };
    $("#isClear").onclick = () => { st.lines = {}; st.req.clear(); reqDraw(); pk.draw(); };
    $("#isCancel").onclick = () => stockHome();
    $("#isNext").onclick = () => {
      st.comment = $("#isCom").value;
      const lines = linesOf(st.lines);
      if (!lines.length) { $("#isErr").textContent = "Добавьте хотя бы один материал"; return; }
      if (st.from === st.to) { $("#isErr").textContent = "Выберите разные места: откуда и куда"; return; }
      const short = lines.filter(l => l.qty > ((st.byId[l.material_id] || {}).balance || 0) + 1e-9);
      if (short.length) { $("#isErr").textContent = `Не хватает в месте «${snPlaceName(st.from)}»: ${short.map(l => st.byId[l.material_id].name).join(", ")}`; return; }
      st.step = 2; step2();
    };
  };
  const step2 = async () => {
    const lines = linesOf(st.lines);
    const atTo = Object.fromEntries((await api.materials("", false, false, st.to)).map(m => [m.id, m.balance]));
    snScreen("issue", "Выдать в кабинет", "Проверьте и подтвердите выдачу", `${steps()}<section class="sn-card">
      <div class="sn-route"><span>${esc(snPlaceName(st.from))}</span>${SN_ICON.issue}<b>${esc(snPlaceName(st.to))}</b>${st.req.size ? `<em>по ${st.req.size === 1 ? "заявке" : "заявкам"} ${st.reqs.filter(r => st.req.has(r.id)).map(r => "№ " + esc(r.number)).join(", ")}</em>` : ""}</div>
      <table class="tbl sn-tbl"><thead><tr><th>Материал</th><th class="num">К выдаче</th><th class="num">${esc(snPlaceName(st.from))}: было → станет</th><th class="num">${esc(snPlaceName(st.to))}: было → станет</th></tr></thead><tbody>${lines.map(l => { const m = st.byId[l.material_id];
        return `<tr><td><div class="sn-mat">${phHtml(m.photo_id, "", matPic(m.name, m.category))}<span><b>${esc(m.name)}</b><small>${m.code ? "Арт. " + esc(m.code) : ""}</small></span></div></td><td class="num"><b>${qtyFmt(l.qty, m.unit)}</b></td>
          <td class="num">${qtyFmt(m.balance)} → <b>${qtyFmt(snNum(m.balance - l.qty), m.unit)}</b></td><td class="num">${qtyFmt(atTo[l.material_id] || 0)} → <b>${qtyFmt(snNum((atTo[l.material_id] || 0) + l.qty), m.unit)}</b></td></tr>`; }).join("")}</tbody></table>
      ${st.comment ? `<div class="muted" style="margin-top:8px">Комментарий: ${esc(st.comment)}</div>` : ""}</section>
      <div class="sn-bar"><button class="btn ghost" id="isBack">${SN_ICON.back}Назад</button><span class="grow"></span><div class="auth-err" id="isErr"></div><button class="btn sn-big" id="isGo">${SN_ICON.ok}Выдать</button></div>`);
    loadThumbs($("#stockBody"));
    $("#isBack").onclick = () => { st.step = 1; step1(); };
    $("#isGo").onclick = e => busy(e.currentTarget, async () => {
      try {
        st.doc = await api.stock_transfer({from_id: st.from, to_id: st.to, comment: st.comment, lines, request_ids: [...st.req]});
        snLS("cab", st.to); st.step = 3; step3(lines); refreshStatus();
      } catch (err) { $("#isErr").textContent = errText(err); }
    });
  };
  const step3 = lines => {
    snScreen("issue", "Выдать в кабинет", "Выдача завершена", `${steps()}<section class="sn-card sn-done"><i>${SN_ICON.ok}</i><h3>Материалы выданы в «${esc(snPlaceName(st.to))}»</h3>
      <span class="muted">${lines.length} ${plural(lines.length, "позиция", "позиции", "позиций")} · ${qtyFmt(lines.reduce((a, l) => a + l.qty, 0), "ед.")}${st.req.size ? " · заявки отмечены выданными" : ""}</span>
      <div class="sn-acts row"><button class="btn ghost" id="isPrint">Печать накладной</button><button class="btn ghost" id="isMore">Новая выдача</button><button class="btn" id="isHome">К складу</button></div></section>`);
    $("#isPrint").onclick = () => printStockDoc(st.doc);
    $("#isMore").onclick = () => openIssueScreen();
    $("#isHome").onclick = () => stockHome();
  };
  step1();
}

/* ---------------------------------------------------- «Принять поставку» */
async function openReceiveScreen() {
  await ensureStk();
  const st = {lines: [], rows: [], to: hasPlaces() ? "" : null};
  const [sups] = await Promise.all([api.suppliers()]);
  const load = async () => { st.rows = await api.materials("", false, false, st.to); st.byId = Object.fromEntries(st.rows.map(m => [m.id, m])); };
  await load();
  const qtyOf = mid => snNum(st.lines.filter(l => l.material_id === mid).reduce((a, l) => a + (+l.qty || 0), 0));
  const setQty = (mid, q) => {
    const mine = st.lines.filter(l => l.material_id === mid), cur = qtyOf(mid);
    if (!mine.length) { if (q > 0) st.lines.push({material_id: mid, qty: q, price: (st.byId[mid] || {}).price || "", lot: "", expires: ""}); return; }
    const last = mine[mine.length - 1]; last.qty = snNum(+last.qty + q - cur);
    if (last.qty <= 0) st.lines.splice(st.lines.indexOf(last), 1);
  };
  snScreen("receive", "Принять поставку", "Поступление материалов от поставщика", `<div class="sn-cols">
    <div class="sn-c1"><section class="sn-card">${snStep(1, "Накладная")}
      <label class="fl">Поставщик<select class="input" id="rcSup"><option value="">—</option>${sups.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select></label>
      <label class="fl">Номер накладной<input class="input" id="rcNum"></label><label class="fl">Дата<input class="input" type="date" id="rcDate" value="${iso(new Date())}"></label>
      ${hasPlaces() ? `<label class="fl">Куда оприходовать<select class="input" id="rcTo">${placeOptions("")}</select></label>` : ""}
      <label class="dx-doc"><input type="checkbox" id="rcNodoc">Без накладной (без документов)</label>
      ${canAny("expenses_day", "accounting") ? `<label class="fl">Записать в расходы за день<select class="input" id="rcPay"><option value="">— не записывать —</option>${["Наличные из кассы", "Карта клиники", "Перевод", "Свои деньги сотрудника"].map(m => `<option>${m}</option>`).join("")}</select></label>` : ""}</section></div>
    <div class="sn-c2">${pickerHtml(snStep(2, "Что пришло"), "Пришло")}</div>
    <div class="sn-c3"><section class="sn-card">${snStep(3, "Состав поставки")}<div id="rcCart"></div><div class="sn-total"><span>На сумму:</span><b id="rcSum">0 ₽</b></div></section>
      <div class="sn-acts"><button class="btn sn-big" id="rcOk">${SN_ICON.ok}Оприходовать</button><button class="btn ghost" id="rcCancel">Отмена</button></div><div class="auth-err" id="rcErr"></div></div></div>`);
  const cartDraw = () => {
    $("#rcCart").innerHTML = st.lines.length ? st.lines.map((l, i) => { const m = st.byId[l.material_id] || {};
      return `<div class="sn-rc">${phHtml(m.photo_id, "", matPic(m.name, m.category))}<div><b>${esc(m.name)}</b><div class="sn-rc-f"><label>Кол-во<input class="input num" data-i="${i}" data-f="qty" value="${esc(l.qty)}"></label>
        <label>Цена, ₽<input class="input num" data-i="${i}" data-f="price" value="${esc(l.price)}"></label><label>Партия<input class="input" data-i="${i}" data-f="lot" value="${esc(l.lot)}"></label>
        <label>Годен до<input class="input" type="date" data-i="${i}" data-f="expires" value="${esc(l.expires)}"></label></div></div><button class="x" data-rmi="${i}" title="Убрать">×</button></div>`; }).join("")
      : `<div class="muted sn-none">Сканируйте штрихкоды или отметьте материалы — партия и срок годности с кода «Честный знак» заполнятся сами</div>`;
    $("#rcSum").textContent = money(st.lines.reduce((a, l) => a + (+l.qty || 0) * (+l.price || 0), 0));
    $$("#rcCart [data-f]").forEach(el => el.onchange = () => { const l = st.lines[+el.dataset.i]; l[el.dataset.f] = el.dataset.f === "qty" ? snNum(el.value) : el.value; if (l.qty <= 0) st.lines.splice(+el.dataset.i, 1); pk.draw(); });
    $$("#rcCart [data-rmi]").forEach(b => b.onclick = () => { st.lines.splice(+b.dataset.rmi, 1); pk.draw(); });
    loadThumbs($("#rcCart"));
  };
  const pk = bindPicker(st, {qty: qtyOf, set: setQty, after: cartDraw,
    onScan: (m, p) => {  // a GS1 code brings its lot and expiry: that lot gets its own line
      const same = st.lines.find(l => l.material_id === m.id && (l.lot || "") === (p.lot || "") && (l.expires || "") === (p.expires || ""));
      if (same) same.qty = snNum(+same.qty + 1); else st.lines.push({material_id: m.id, qty: 1, price: m.price || "", lot: p.lot || "", expires: p.expires || ""});
      st.byId[m.id] = st.byId[m.id] || m;
    },
    onUnknown: async (p, draw, msg) => {
      if (!can("stock_edit")) { msg(`Штрихкода ${p.barcode} нет в справочнике — попросите кладовщика добавить материал`, true); return; }
      const v = await askInput("Новый материал", [{label: "Название", value: ""}, {label: "Единица", value: "шт"}, {label: "Цена за единицу, ₽", type: "number", required: false}],
        {text: `Штрихкода ${p.barcode} нет в справочнике. Создать материал и добавить в поставку?`, ok: "Создать и добавить"});
      if (!v) return;
      try { const id = await api.save_material({name: v[0], unit: v[1], price: v[2], barcode: p.barcode}); await load();
        st.lines.push({material_id: id, qty: 1, price: v[2] || "", lot: p.lot || "", expires: p.expires || ""}); $("#pkQ").value = ""; draw(); msg("✓ " + v[0]); } catch (e) { msg(errText(e), true); }
    }});
  const to = $("#rcTo"); if (to) to.onchange = async () => { st.to = to.value; await load(); pk.draw(); };
  $("#rcCancel").onclick = () => stockHome();
  $("#rcOk").onclick = e => busy(e.currentTarget, async () => {
    const f = {supplier_id: $("#rcSup").value, number: $("#rcNum").value, date: $("#rcDate").value, nodoc: $("#rcNodoc").checked, pay: $("#rcPay") ? $("#rcPay").value : "",
      lines: st.lines.filter(l => l.qty > 0)};
    if (to) f.location_id = to.value;
    try { await api.stock_receive(f); toast("Поставка принята" + (f.nodoc ? " — без документов" : "")); stockHome(); } catch (err) { $("#rcErr").textContent = errText(err); }
  });
}

/* ----------------------------------------------- approvals tab helper */
function openApprovals() { SN.sub = "requests"; return stockGo("stock", "home"); }

/* ------------------------------------------------- equipment: depreciation */
function amortBlock(e) {
  const a = e.amort || {};
  if (!a.on) return `<h4 class="sub-h">Амортизация</h4><div class="muted">${e.price ? "Укажите срок полезного использования в «Изменить» — программа посчитает амортизацию по месяцам (линейный способ)." : "Укажите стоимость и срок полезного использования, чтобы считать амортизацию."}</div>`;
  const years = a.useful_months % 12 ? `${a.useful_months} мес.` : `${a.useful_months / 12} ${plural(a.useful_months / 12, "год", "года", "лет")}`;
  const sch = e.amort_schedule || [];
  return `<h4 class="sub-h">Амортизация · линейный способ</h4>
    <div class="stat-row sn-amort"><div class="stat"><span>Стоимость</span><b>${money(a.cost)}</b></div><div class="stat"><span>В месяц</span><b>${money(a.monthly)}</b></div>
      <div class="stat"><span>Начислено · ${a.months_done} мес.</span><b>${money(a.accumulated)}</b></div><div class="stat ${a.done ? "" : "ok"}"><span>Остаточная стоимость</span><b>${money(a.residual)}</b></div></div>
    <div class="sn-amort-bar"><i style="width:${Math.min(100, a.percent)}%"></i></div>
    <div class="muted sn-amort-t">Введено ${a.in_service ? fmtDate(a.in_service) : "—"} · срок ${years}${a.salvage ? ` · ликвидационная стоимость ${money(a.salvage)}` : ""} · начисление с ${monthTitle(a.first)} по ${monthTitle(a.stopped || a.last)}${a.done ? " · полностью самортизировано" : ""}</div>
    ${sch.length ? `<details class="sn-sched"><summary>График по месяцам (${sch.length})</summary><table class="tbl compact"><thead><tr><th>Месяц</th><th class="num">Начислено за месяц</th><th class="num">Накоплено</th><th class="num">Остаточная</th></tr></thead><tbody>${
      sch.map(x => `<tr class="${x.month <= iso(new Date()).slice(0, 7) ? "" : "muted-row"}"><td>${monthTitle(x.month)}</td><td class="num">${money(x.charge)}</td><td class="num">${money(x.accumulated)}</td><td class="num">${money(x.residual)}</td></tr>`).join("")}</tbody></table></details>` : ""}`;
}
const monthTitle = m => { if (!m) return ""; const [y, mo] = m.split("-").map(Number); return `${["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"][mo - 1]} ${y}`; };
/** 3.14: the depreciation is a tab of «Оборудование» (it was a dialog). */
function openAmortReport() { return stockGo("equipment", "amort"); }
async function eqAmortTab() {
  const f = S.amortF || {};
  const r = await api.equipment_amortization(f.from || null, f.to || null);
  const short = m => { const [y, mo] = m.split("-"); return `${mo}.${y.slice(2)}`; };
  const body = $("#stockBody");
  body.innerHTML = `<div class="eq-amort">
    <div class="stat-row"><div class="stat"><span>Стоимость</span><b>${money(r.cost)}</b></div><div class="stat"><span>Накоплено</span><b>${money(r.accumulated)}</b></div>
      <div class="stat ok"><span>Остаточная стоимость</span><b>${money(r.residual)}</b></div><div class="stat"><span>За этот месяц</span><b>${money(r.this_month)}</b></div></div>
    <div class="tab-tools"><label class="fl inline">С<input class="input" type="month" id="amF" value="${r.months[0]}"></label><label class="fl inline">по<input class="input" type="month" id="amT" value="${r.months[r.months.length - 1]}"></label>
      <span class="grow"></span>${r.can_pnl ? `<label class="switch-row" style="margin:0" title="Амортизация попадёт в «Бухгалтерия → ОПиУ» отдельной строкой постоянных расходов"><input type="checkbox" id="amPnl" ${r.in_pnl ? "checked" : ""}><span class="sw"></span>Учитывать в ОПиУ</label>` : ""}</div>
    <div id="amCapex"></div>
    ${r.without_life ? `<div class="warn-line">У ${r.without_life} ед. оборудования со стоимостью не указан срок полезного использования — они не амортизируются. Срок указывают в карточке → «Редактировать».</div>` : ""}
    ${r.rows.length ? `<div class="sn-amort-wrap"><table class="tbl compact"><thead><tr><th>Оборудование</th><th class="num">Стоимость</th>${r.months.map(m => `<th class="num">${short(m)}</th>`).join("")}<th class="num">Итого</th><th class="num">Остаточная</th></tr></thead><tbody>${
      r.rows.map(x => `<tr data-e="${esc(x.id)}" class="${x.status === "written_off" ? "muted-row" : ""}"><td class="lnk"><b>${esc(x.name)}</b><small class="muted" style="display:block">инв. № ${esc(x.inv_number)}${x.done ? " · самортизировано" : ""}${x.status === "written_off" ? " · выбыло" : ""}</small></td><td class="num">${money(x.cost)}</td>${x.values.map(v => `<td class="num">${v ? money(v) : '<span class="muted">—</span>'}</td>`).join("")}<td class="num"><b>${money(x.total)}</b></td><td class="num">${money(x.residual)}</td></tr>`).join("")}
      <tr class="sn-tot"><td><b>Итого</b></td><td class="num">${money(r.cost)}</td>${r.totals.map(v => `<td class="num"><b>${money(v)}</b></td>`).join("")}<td class="num"><b>${money(r.total)}</b></td><td class="num"><b>${money(r.residual)}</b></td></tr></tbody></table></div>`
      : `<div class="empty"><b>Амортизация пока не считается</b><span>Откройте оборудование → «Редактировать» и укажите дату ввода в эксплуатацию и срок полезного использования</span></div>`}
    <div class="muted eqc-hint">Линейный способ: (стоимость − ликвидационная) / срок, с месяца после ввода в эксплуатацию. В ОПиУ покупка оборудования не идёт целиком в расходы месяца — каждый месяц идёт амортизация, а при выбытии — остаточная стоимость.</div></div>`;
  const re = () => { S.amortF = {from: $("#amF").value, to: $("#amT").value}; eqAmortTab(); };
  $("#amF").onchange = re; $("#amT").onchange = re;
  const p = $("#amPnl"); if (p) p.onchange = async () => { try { await api.amort_settings_save({in_pnl: p.checked}); toast(p.checked ? "Амортизация учитывается в ОПиУ" : "Амортизация убрана из ОПиУ"); } catch (e) { toast(errText(e), true); p.checked = !p.checked; } };
  $$("tr[data-e]", body).forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e, "finance"));
  if (typeof eqCapexBox === "function") eqCapexBox($("#amCapex"));
  if (r.off_books) $("#amCapex").insertAdjacentHTML("afterend", `<div class="muted eqc-hint">Не амортизируются в ОПиУ: ${r.off_books} ед. в аренде или имущество учредителя — это не имущество клиники.</div>`);
}

/** 3.14: old purchases of equipment written down under another category (the same sum near the purchase date) — they would
    count the equipment twice next to its depreciation. One button moves them into «Покупка оборудования». */
async function eqCapexBox(el, after) {
  if (!el || !can("accounting")) return;
  let rows;
  try { rows = await api.equipment_capex_candidates(); } catch (e) { return; }
  if (!rows.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="capex-box"><div class="capex-h"><b>Похоже, покупка оборудования записана в расходы месяца: ${rows.length}</b>
      <span class="muted">Покупка не должна целиком уходить в расходы: в прибыль оборудование идёт амортизацией. Перенесите эти расходы в статью «Покупка оборудования» — в движении денег они останутся.</span></div>
    <table class="tbl compact"><thead><tr><th><input type="checkbox" id="cxAll" checked title="Все"></th><th>Расход</th><th>Статья сейчас</th><th class="num">Сумма</th><th>Похоже на покупку</th></tr></thead><tbody>${
      rows.map(x => `<tr><td><input type="checkbox" data-cx="${esc(x.expense_id)}" checked></td><td>${fmtDate(x.date)}${x.comment ? `<small class="muted" style="display:block">${esc(x.comment)}</small>` : ""}</td><td>${esc(x.category)}</td>
        <td class="num"><b>${money(x.amount)}</b></td><td>${esc(x.name)}${x.inv_number ? ` <span class="muted">· ${esc(x.inv_number)}</span>` : ""}<small class="muted" style="display:block">куплено ${fmtDate(x.purchase_date)}</small></td></tr>`).join("")}</tbody></table>
    <div class="capex-f"><button class="btn" id="cxGo">Перенести в «Покупку оборудования»</button><span class="muted">Можно и вручную: «Бухгалтерия → Расходы», статья «Покупка оборудования».</span></div></div>`;
  $("#cxAll", el).onchange = e => $$("[data-cx]", el).forEach(c => c.checked = e.target.checked);
  $("#cxGo", el).onclick = async () => {
    const ids = $$("[data-cx]", el).filter(c => c.checked).map(c => c.dataset.cx);
    if (!ids.length) return toast("Отметьте расходы", true);
    try { const r = await api.expenses_to_capex(ids); toast(`Перенесено: ${r.moved}`); if (after) after(); else eqCapexBox(el); }
    catch (e) { toast(errText(e), true); }
  };
}
