"use strict";
/* Stock: materials (balances, supplier invoices, write-offs, stock count, norms per service) and equipment. */
S.stockTab = "balance";
let STK = {units: [], move_kinds: {}, eq_status: {}};
const qtyFmt = (n, u) => `${(Math.round((+n || 0) * 1000) / 1000).toLocaleString("ru-RU")}${u ? " " + u : ""}`;
const DOC_KIND = {receipt: "Приходная накладная", writeoff: "Акт списания материалов", inventory: "Инвентаризация"};

$$("#stockTabs button").forEach(b => b.onclick = () => {
  S.stockTab = b.dataset.k;
  $$("#stockTabs button").forEach(x => x.classList.toggle("on", x === b));
  loadStock();
});

function stockTabsByRights() {
  const vis = {balance: canAny("stock_view", "stock_edit"), docs: canAny("stock_view", "stock_edit"), moves: canAny("stock_view", "stock_edit"),
    equipment: canAny("equipment", "stock_view"), norms: canAny("stock_view", "stock_edit"), suppliers: can("stock_edit"),
    steril: canAny("sterilization", "equipment")};
  $$("#stockTabs button").forEach(b => b.hidden = !vis[b.dataset.k]);
  if (!vis[S.stockTab]) S.stockTab = Object.keys(vis).find(k => vis[k]) || "equipment";
  $$("#stockTabs button").forEach(b => b.classList.toggle("on", b.dataset.k === S.stockTab));
}

async function loadStock() {
  stockTabsByRights();
  if (S.stockTab === "steril") return sterilJournal();  // the journal is also for those without stock rights
  STK = await api.stock_summary();
  const fn = {balance: stockBalance, docs: stockDocs, moves: stockMoves, equipment: stockEquipment, norms: stockNorms, suppliers: stockSuppliers}[S.stockTab];
  await fn();
}

function statRow() {
  return `<div class="stat-row">
    <div class="stat"><span>Материалов</span><b>${STK.materials}</b></div>
    <div class="stat ${STK.low ? "warn" : ""}"><span>Заканчиваются</span><b>${STK.low}</b></div>
    <div class="stat ${STK.expired ? "bad" : STK.expiring ? "warn" : ""}" title="Партии с истёкшим сроком или сроком до 30 дней"><span>Истекает срок</span><b>${(STK.expired || 0) + (STK.expiring || 0)}</b></div>
    <div class="stat"><span>Сумма остатков</span><b>${money(STK.value)}</b></div>
    <div class="stat"><span>Оборудование в работе</span><b>${STK.equipment}</b></div>
    <div class="stat ${STK.service_due ? "warn" : ""}"><span>Пора на ТО</span><b>${STK.service_due}</b></div></div>`;
}

/* ------------------------------------------------------------ balances */
async function stockBalance() {
  const body = $("#stockBody");
  const q = S.stockQ || "", low = !!S.stockLow, exp = !!S.stockExp;
  const rows = await api.materials(q, low, exp);
  S.stockRows = rows;
  const edit = can("stock_edit"), acc = can("accounting") && rows.some(m => m.balance_doc !== undefined);
  const docDiff = acc && rows.some(m => Math.abs(m.balance - m.balance_doc) > 1e-9);
  body.innerHTML = statRow() + `<div class="tab-tools">
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="stQ" placeholder="Материал, код, штрихкод" value="${esc(q)}"></div>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="stLow" ${low ? "checked" : ""}><span class="sw"></span>Только заканчиваются</label>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="stExp" ${exp ? "checked" : ""}><span class="sw"></span>Истекает срок</label>
      <span class="grow"></span>
      <button class="btn ghost" id="stOrder" title="Что и сколько заказать, у кого дешевле">Заказ поставщикам</button>
      ${edit && STK.expired ? `<button class="btn ghost danger-t" id="stExpOut">Списать просроченное</button>` : ""}
      ${edit ? `<button class="btn" id="stIn">Приход</button><button class="btn ghost" id="stOut">Списание</button><button class="btn ghost" id="stInv">Инвентаризация</button><button class="btn ghost" id="stNew">Новый материал</button>` : ""}
      <button class="icon-btn" id="stPrint" title="Печать остатков"><svg viewBox="0 0 24 24"><path d="M7 9V3.5h10V9M7 17H4.5V10.5a1.5 1.5 0 0 1 1.5-1.5h12a1.5 1.5 0 0 1 1.5 1.5V17H17"/><rect x="7" y="14" width="10" height="6.5" rx="1"/></svg></button>
      ${acc ? `<button class="btn ghost small" id="stPrintDoc" title="Остатки только по документам — для бухгалтерии">Печать по документам</button>` : ""}</div>
    ${docDiff ? `<div class="warn-line">Есть приход или списание без документов: остаток «по документам» отличается от фактического. Его видите только вы (право «Бухгалтерия»).</div>` : ""}
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Код</th><th>Материал</th><th>Раздел</th><th class="num">Остаток</th>${docDiff ? '<th class="num" title="Только движения с документами">По документам</th>' : ""}<th class="num">Минимум</th><th class="num">Цена</th><th class="num">Сумма</th><th></th></tr></thead><tbody>${
      rows.map(m => `<tr data-m="${esc(m.id)}" class="${m.balance < 0 ? "neg" : ""} ${m.exp_state ? "exp-" + m.exp_state : ""}"><td class="muted">${esc(m.code)}</td><td class="lnk"><b>${esc(m.name)}</b>${expLine(m)}</td><td>${esc(m.category)}</td>
        <td class="num"><b>${qtyFmt(m.balance, m.unit)}</b></td>${docDiff ? `<td class="num ${Math.abs(m.balance - m.balance_doc) > 1e-9 ? "warn-t" : "muted"}">${qtyFmt(m.balance_doc, m.unit)}</td>` : ""}<td class="num muted">${m.min_qty ? qtyFmt(m.min_qty) : "—"}</td><td class="num">${money(m.price)}</td><td class="num">${money(m.value)}</td>
        <td class="pills">${m.balance < 0 ? '<span class="pill st-cancel">меньше нуля</span>' : m.low ? '<span class="pill st-cancel">заканчивается</span>' : m.exp_state ? "" : '<span class="pill st-ok">есть</span>'}${m.exp_state === "expired" ? '<span class="pill exp-pill expired">просрочено</span>' : m.exp_state === "soon" ? '<span class="pill exp-pill soon">истекает срок</span>' : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>${q || low || exp ? "Ничего не найдено" : "Склад пока пуст"}</b><span>${edit ? "Добавьте материалы и оформите приход по накладной" : ""}</span></div>`}</div>`;
  let t; $("#stQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.stockQ = e.target.value; stockBalance().then(() => { const i = $("#stQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  $("#stLow").onchange = e => { S.stockLow = e.target.checked; stockBalance(); };
  $("#stExp").onchange = e => { S.stockExp = e.target.checked; stockBalance(); };
  $$("#stockBody tr[data-m]").forEach(tr => tr.onclick = () => openMaterial(tr.dataset.m));
  const on = (id, f) => { const el = $(id); if (el) el.onclick = f; };
  on("#stIn", () => openStockDoc("receipt")); on("#stOut", () => openStockDoc("writeoff")); on("#stInv", openInventory);
  on("#stNew", () => editMaterial({})); on("#stPrint", () => printBalance()); on("#stPrintDoc", () => printBalance(true));
  on("#stOrder", () => openPurchase()); on("#stExpOut", writeOffExpired);
}

function editMaterial(m, {onSaved} = {}) {
  const box = modal(`<div class="m-h"><h3>${m.id ? "Материал" : "Новый материал"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <label class="fl">Название*<input class="input" id="mName" value="${esc(m.name || "")}" autofocus></label>
      <div class="grid3"><label class="fl">Код / артикул<input class="input" id="mCode" value="${esc(m.code || "")}"></label>
        <label class="fl">Раздел<input class="input" id="mCat" value="${esc(m.category || "")}" list="mCats"></label>
        <label class="fl">Единица<input class="input" id="mUnit" value="${esc(m.unit || "шт")}" list="mUnits"></label></div>
      <div class="grid3"><label class="fl">Минимальный остаток<input class="input" id="mMin" type="number" step="any" min="0" value="${m.min_qty ?? ""}"></label>
        <label class="fl">Цена за единицу, ₽<input class="input" id="mPrice" type="number" step="any" min="0" value="${m.price ?? ""}"></label>
        ${m.id ? `<label class="fl">Штрихкод<input class="input" id="mBar" value="${esc(m.barcode || "")}"></label>` : `<label class="fl">Начальный остаток<input class="input" id="mStart" type="number" step="any" min="0"></label>`}</div>
      ${m.id ? "" : `<label class="fl">Штрихкод<input class="input" id="mBar" value="${esc(m.barcode || "")}"></label>`}
      <label class="fl">Комментарий<input class="input" id="mCom" value="${esc(m.comment || "")}"></label>
      <datalist id="mUnits">${STK.units.map(u => `<option value="${u}">`).join("")}</datalist>
      <datalist id="mCats">${[...new Set((S.stockRows || []).map(r => r.category).filter(Boolean))].map(c => `<option value="${esc(c)}">`).join("")}</datalist>
      <div class="auth-err" id="mErr"></div></div>
    <div class="m-f">${m.id ? `<button class="btn ghost small danger" id="mDel">Убрать из справочника</button>` : ""}<span class="muted">Когда остаток опустится до минимума, материал попадёт в «Заканчиваются»</span>
      <button class="btn ghost" data-close>Отмена</button><button class="btn" id="mOk">Сохранить</button></div>`);
  $("#mOk", box).onclick = async () => {
    try {
      const id = await api.save_material({id: m.id, name: $("#mName").value, code: $("#mCode").value, category: $("#mCat").value, unit: $("#mUnit").value,
        min_qty: $("#mMin").value, price: $("#mPrice").value, barcode: $("#mBar").value, comment: $("#mCom").value, start_qty: m.id ? null : $("#mStart").value});
      closeModal(); toast("Сохранено"); loadStock();
      if (onSaved) onSaved(id);
    } catch (e) { $("#mErr").textContent = errText(e); }
  };
  const del = $("#mDel", box);
  if (del) del.onclick = async () => { if (await ask(`Убрать «${m.name}» из справочника?`, {danger: true, ok: "Убрать", text: "История движения сохранится, нормы списания по услугам удалятся."})) { await api.delete_material(m.id); closeModal(); loadStock(); } };
}

async function openMaterial(id) {
  const m = await api.material(id);
  const edit = can("stock_edit");
  const box = modal(`<div class="m-h"><h3>${esc(m.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="stat-row"><div class="stat"><span>Остаток</span><b>${qtyFmt(m.balance, m.unit)}</b>${m.balance_doc !== undefined && Math.abs(m.balance - m.balance_doc) > 1e-9 ? `<small class="muted">по документам: ${qtyFmt(m.balance_doc, m.unit)}</small>` : ""}</div><div class="stat"><span>Минимум</span><b>${m.min_qty ? qtyFmt(m.min_qty, m.unit) : "—"}</b></div>
        <div class="stat"><span>Цена</span><b>${money(m.price)}</b></div><div class="stat"><span>Сумма</span><b>${money(m.value)}</b></div></div>
      <h4 class="sub-h">Партии и сроки годности</h4>
      ${lotsTable(m.lot_list, m.unit, edit)}
      <h4 class="sub-h">Списывается по услугам</h4>
      ${m.norms.length ? `<div class="chips">${m.norms.map(n => `<span class="chip">${esc(n.title)} · ${qtyFmt(n.qty, m.unit)}</span>`).join("")}</div>` : `<div class="muted">Не привязан к услугам. Нормы задаются во вкладке «Нормы списания».</div>`}
      <h4 class="sub-h">Движение</h4>
      ${movesTable(m.moves, false)}
    </div>
    <div class="m-f"><span class="muted">${esc(m.code || "")} ${m.barcode ? "· штрихкод " + esc(m.barcode) : ""}</span><button class="btn ghost" data-close>Закрыть</button>
      ${edit ? `<button class="btn ghost" id="mOutOne">Списать</button><button class="btn ghost" id="mInOne">Приход</button><button class="btn" id="mEdit">Изменить</button>` : ""}</div>`, {wide: true});
  const on = (s, f) => { const el = $(s, box); if (el) el.onclick = f; };
  on("#mEdit", () => editMaterial(m));
  on("#mInOne", () => openStockDoc("receipt", [{material_id: m.id, qty: "", price: m.price}]));
  on("#mOutOne", () => openStockDoc("writeoff", [{material_id: m.id, qty: ""}]));
  $$("[data-lot-out]", box).forEach(b => b.onclick = () => { const g = m.lot_list.lots.find(x => String(x.id) === b.dataset.lotOut);
    openStockDoc("writeoff", [{material_id: m.id, qty: g.left, lot_id: g.id, lot: g.lot, expires: g.expires}], {reason: g.state === "expired" ? "Истёк срок годности" : ""}); });
}

function movesTable(moves, withMaterial = true) {
  if (!moves.length) return `<div class="empty"><b>Движений нет</b></div>`;
  return `<table class="tbl compact"><thead><tr><th>Когда</th><th>Операция</th>${withMaterial ? "<th>Материал</th>" : ""}<th class="num">Кол-во</th><th>Основание</th><th>Сотрудник</th></tr></thead><tbody>${
    moves.map(x => `<tr><td>${fmtDT(x.at)}</td><td><span class="mv mv-${x.kind}">${esc(x.kind_title)}</span></td>${withMaterial ? `<td>${esc(x.name)}</td>` : ""}
      <td class="num ${x.qty < 0 ? "bad-t" : "ok-t"}"><b>${x.qty > 0 ? "+" : ""}${qtyFmt(x.qty, x.unit)}</b></td>
      <td class="muted">${esc([x.doc_number ? "№ " + x.doc_number : "", x.patient_name || "", x.reason || ""].filter(Boolean).join(" · "))}${x.nodoc ? " " + '<span class="pill dx-nodoc">без документа</span>' : ""}</td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody></table>`;
}

/* ---------------------------------------------- receipt and write-off */
async function openStockDoc(kind, preset, opts = {}) {
  let [mats, sups] = await Promise.all([api.materials(""), kind === "receipt" ? api.suppliers() : Promise.resolve([])]);
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
    try {
      const id = isIn ? await api.stock_receive({...f, supplier_id: $("#dSup").value, number: $("#dNum").value, pay})
        : await api.stock_write_off({...f, reason: $("#dReason").value});
      closeModal(); toast((isIn ? "Приход оформлен" : "Материалы списаны") + (nodoc ? " — без документов" : "") + (pay ? ", расход записан" : ""));
      loadStock();
      if (!isIn && !nodoc && await ask("Распечатать акт списания?", {icon: "print", ok: "Распечатать", cancel: "Не сейчас", text: "Акт можно распечатать и позже: «Склад» → «Документы»."})) printStockDoc(id);
    } catch (e) { $("#dErr").textContent = errText(e); }
  };
}

async function openInventory() {
  const mats = await api.materials("");
  const box = modal(`<div class="m-h"><h3>Инвентаризация</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="muted">Пересчитайте материалы и впишите фактический остаток. Пустые строки не меняются. Разница с учётом станет движением «Инвентаризация».</div>
      <table class="tbl compact"><thead><tr><th>Материал</th><th class="num">По учёту</th><th class="num" style="width:140px">Фактически</th><th class="num">Разница</th></tr></thead><tbody>${
        mats.map(m => `<tr><td>${esc(m.name)}<small class="muted" style="display:block">${esc(m.category)}</small></td><td class="num">${qtyFmt(m.balance, m.unit)}</td>
          <td><input class="input num" type="number" step="any" min="0" data-im="${esc(m.id)}" data-b="${m.balance}"></td><td class="num" data-d="${esc(m.id)}"></td></tr>`).join("")}</tbody></table>
      <label class="fl">Комментарий<input class="input" id="invCom"></label>
      <label class="dx-doc"><input type="checkbox" id="invNodoc">Внутренняя инвентаризация (без документов)</label><div class="auth-err" id="invErr"></div></div>
    <div class="m-f"><span class="muted" id="invCnt"></span><button class="btn ghost" id="invSheet">Печать бланка</button><button class="btn ghost" data-close>Отмена</button><button class="btn" id="invOk">Провести</button></div>`, {wide: true});
  const recount = () => { let n = 0;
    $$("[data-im]", box).forEach(i => { const d = $(`[data-d="${i.dataset.im}"]`, box); if (i.value === "") { d.textContent = ""; return; } n++;
      const diff = Math.round((+i.value - +i.dataset.b) * 1000) / 1000; d.textContent = diff ? (diff > 0 ? "+" : "") + diff.toLocaleString("ru-RU") : "0"; d.className = "num " + (diff < 0 ? "bad-t" : diff > 0 ? "ok-t" : "muted"); });
    $("#invCnt").textContent = n ? `Пересчитано: ${n}` : ""; };
  $$("[data-im]", box).forEach(i => i.oninput = recount);
  $("#invSheet", box).onclick = () => printInventorySheet(mats);
  $("#invOk", box).onclick = async () => {
    try {
      const r = await api.stock_inventory({comment: $("#invCom").value, nodoc: $("#invNodoc").checked, lines: $$("[data-im]", box).map(i => ({material_id: i.dataset.im, actual: i.value}))});
      closeModal(); toast(r.diffs.length ? `Проведено. Расхождений: ${r.diffs.length}` : "Проведено. Расхождений нет"); loadStock();
    } catch (e) { $("#invErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------------- documents */
async function stockDocs() {
  const kind = S.stockDocKind || "";
  const rows = await api.stock_docs(kind || null);
  $("#stockBody").innerHTML = `<div class="tab-tools"><div class="seg" id="sdKind">${[["", "Все"], ["receipt", "Приход"], ["writeoff", "Списание"], ["inventory", "Инвентаризация"]].map(([k, t]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${t}</button>`).join("")}</div></div>
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Документ</th><th>№</th><th>Поставщик / причина</th><th class="num">Строк</th><th class="num">Сумма</th><th>Сотрудник</th></tr></thead><tbody>${
      rows.map(d => `<tr data-d="${esc(d.id)}"><td>${fmtDate(d.date)}</td><td class="lnk"><b>${esc(DOC_KIND[d.kind] || d.kind)}</b>${d.nodoc ? " " + '<span class="pill dx-nodoc">без документа</span>' : ""}</td><td>${esc(d.number || "—")}</td>
        <td>${esc(d.supplier_name || d.reason || "")}</td><td class="num">${d.lines}</td><td class="num">${d.total ? money(d.total) : "—"}</td><td class="muted">${esc(d.user_name || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Документов пока нет</b></div>`}</div>`;
  $$("#sdKind button").forEach(b => b.onclick = () => { S.stockDocKind = b.dataset.k; stockDocs(); });
  $$("#stockBody tr[data-d]").forEach(tr => tr.onclick = () => openStockDocView(tr.dataset.d));
}

async function openStockDocView(id) {
  const d = await api.stock_doc(id);
  modal(`<div class="m-h"><h3>${esc(DOC_KIND[d.kind] || "Документ")} ${d.number ? "№ " + esc(d.number) : ""} от ${fmtDate(d.date)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${d.supplier_name ? `<div>Поставщик: <b>${esc(d.supplier_name)}</b></div>` : ""}${d.reason && d.kind === "writeoff" ? `<div>Причина: <b>${esc(d.reason)}</b></div>` : ""}
      <table class="tbl compact"><thead><tr><th>Материал</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${
        d.moves.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${x.qty > 0 && d.kind === "inventory" ? "+" : ""}${qtyFmt(d.kind === "writeoff" ? -x.qty : x.qty, x.unit)}</td><td class="num">${money(x.price)}</td><td class="num">${money(Math.abs(x.qty) * x.price)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Расхождений не было</td></tr>`}</tbody></table>
      ${d.comment ? `<div class="muted">${esc(d.comment)}</div>` : ""}</div>
    <div class="m-f"><span class="muted">Оформил: ${esc(d.user_name || "—")}, ${fmtDT(d.created_at)}${d.nodoc ? " · без документов, не печатается" : ""}</span><button class="btn ghost" data-close>Закрыть</button>${d.nodoc ? "" : `<button class="btn" id="sdPrint">Печать</button>`}</div>`, {wide: true});
  const sp = $("#sdPrint"); if (sp) sp.onclick = () => printStockDoc(id);
}

/* ------------------------------------------------------- moves */
async function stockMoves() {
  const f = S.moveF || {from: addDays(iso(new Date()), -30), to: iso(new Date()), kind: ""};
  S.moveF = f;
  const rows = await api.stock_moves(f);
  $("#stockBody").innerHTML = `<div class="tab-tools"><input type="date" class="input" id="mvFrom" value="${f.from}"> — <input type="date" class="input" id="mvTo" value="${f.to}">
      <select class="input sm-sel" id="mvKind"><option value="">Все операции</option>${Object.entries(STK.move_kinds).map(([k, t]) => `<option value="${k}" ${k === f.kind ? "selected" : ""}>${t}</option>`).join("")}</select>
      <span class="muted">Списание по услугам происходит само, когда выставлен счёт</span></div>
    <div class="pbody" style="margin-top:8px">${movesTable(rows)}</div>`;
  const upd = () => { S.moveF = {from: $("#mvFrom").value, to: $("#mvTo").value, kind: $("#mvKind").value}; stockMoves(); };
  $("#mvFrom").onchange = upd; $("#mvTo").onchange = upd; $("#mvKind").onchange = upd;
}

/* ------------------------------------------------------- norms */
async function stockNorms() {
  const [svc, norms] = await Promise.all([api.services(""), api.norms()]);
  const by = {}; norms.forEach(n => (by[n.service_id] ||= []).push(n));
  const q = (S.normQ || "").toLowerCase();
  const list = svc.filter(s => !q || `${s.code} ${s.title}`.toLowerCase().includes(q));
  $("#stockBody").innerHTML = `<div class="tab-tools"><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="nQ" placeholder="Услуга" value="${esc(S.normQ || "")}"></div>
      <span class="muted">Какие материалы и сколько уходит на одну услугу. Когда услуга попадает в счёт, материалы списываются со склада сами.</span></div>
    <div class="pbody" style="margin-top:8px"><table class="tbl"><thead><tr><th>Услуга</th><th>Материалы на одну услугу</th></tr></thead><tbody>${
      list.map(s => `<tr data-s="${esc(s.id)}"><td class="lnk"><b>${esc(s.title)}</b><small class="muted" style="display:block">${esc(s.code || "")}</small></td>
        <td>${(by[s.id] || []).map(n => `<span class="chip">${esc(n.name)} · ${qtyFmt(n.qty, n.unit)}</span>`).join(" ") || '<span class="muted">не заданы</span>'}</td></tr>`).join("")}</tbody></table></div>`;
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
async function stockEquipment() {
  const rows = await api.equipment_list(S.eqQ || "", !!S.eqAll);
  const edit = can("equipment");
  $("#stockBody").innerHTML = statRow() + `<div class="tab-tools">
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="eqQ" placeholder="Название, инв. №, серийный, кабинет" value="${esc(S.eqQ || "")}"></div>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="eqAll" ${S.eqAll ? "checked" : ""}><span class="sw"></span>Показать списанное</label>
      <span class="grow"></span>${edit ? `<button class="btn" id="eqNew">Добавить оборудование</button>` : ""}</div>
    <div class="pbody" style="margin-top:8px">${rows.length ? `<table class="tbl"><thead><tr><th>Инв. №</th><th>Оборудование</th><th>Где</th><th>Статус</th><th>Следующее ТО</th><th class="num">Стоимость</th></tr></thead><tbody>${
      rows.map(e => `<tr data-e="${esc(e.id)}" class="${e.status === "written_off" ? "muted-row" : ""}"><td><b>${esc(e.inv_number)}</b></td><td class="lnk"><b>${esc(e.name)}</b><small class="muted" style="display:block">${esc([e.model, e.serial && "S/N " + e.serial].filter(Boolean).join(" · "))}</small></td>
        <td>${esc(e.location)}</td><td><span class="pill ${e.status === "in_use" ? "st-ok" : e.status === "written_off" ? "" : "st-cancel"}">${esc(e.status_title)}</span></td>
        <td class="${e.service_due ? "bad-t" : ""}">${e.next_service ? fmtDate(e.next_service) + (e.service_due ? " · пора" : "") : "—"}</td><td class="num">${money(e.price)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Оборудования пока нет</b><span>${edit ? "Внесите кресла, автоклав, компрессор и другую технику с инвентарными номерами" : ""}</span></div>`}</div>`;
  let t; $("#eqQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.eqQ = e.target.value; stockEquipment().then(() => { const i = $("#eqQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  $("#eqAll").onchange = e => { S.eqAll = e.target.checked; stockEquipment(); };
  const n = $("#eqNew"); if (n) n.onclick = () => editEquipment({});
  $$("#stockBody tr[data-e]").forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e));
}

function editEquipment(e) {
  const box = modal(`<div class="m-h"><h3>${e.id ? "Изменить оборудование" : "Новое оборудование"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid3"><label class="fl" style="grid-column:span 2">Название*<input class="input" id="eN" value="${esc(e.name || "")}" autofocus></label><label class="fl">Инвентарный №<input class="input" id="eInv" value="${esc(e.inv_number || "")}" placeholder="присвоится сам"></label></div>
      <div class="grid3"><label class="fl">Модель<input class="input" id="eM" value="${esc(e.model || "")}"></label><label class="fl">Серийный №<input class="input" id="eS" value="${esc(e.serial || "")}"></label><label class="fl">Раздел<input class="input" id="eC" value="${esc(e.category || "")}"></label></div>
      <div class="grid3"><label class="fl">Где стоит<input class="input" id="eL" value="${esc(e.location || "")}" placeholder="Кабинет 1 · Кресло 1"></label><label class="fl">Ответственный<input class="input" id="eR" value="${esc(e.responsible || "")}"></label>
        <label class="fl">Статус<select class="input" id="eSt">${Object.entries(STK.eq_status).filter(([k]) => k !== "written_off").map(([k, t]) => `<option value="${k}" ${k === (e.status || "in_use") ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
      <div class="grid3"><label class="fl">Дата покупки<input class="input" type="date" id="eP" value="${esc(e.purchase_date || "")}"></label><label class="fl">Стоимость, ₽<input class="input" type="number" min="0" step="any" id="ePr" value="${e.price ?? ""}"></label><label class="fl">Гарантия до<input class="input" type="date" id="eW" value="${esc(e.warranty_until || "")}"></label></div>
      <div class="grid3"><label class="fl">Следующее ТО<input class="input" type="date" id="eNx" value="${esc(e.next_service || "")}"></label></div>
      <label class="fl">Комментарий<input class="input" id="eCom" value="${esc(e.comment || "")}"></label><div class="auth-err" id="eErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="eOk">Сохранить</button></div>`, {wide: true});
  $("#eOk", box).onclick = async () => {
    try {
      const id = await api.save_equipment({id: e.id, name: $("#eN").value, inv_number: $("#eInv").value, model: $("#eM").value, serial: $("#eS").value, category: $("#eC").value,
        location: $("#eL").value, responsible: $("#eR").value, status: $("#eSt").value, purchase_date: $("#eP").value, price: $("#ePr").value, warranty_until: $("#eW").value,
        next_service: $("#eNx").value, comment: $("#eCom").value});
      closeModal(); toast("Сохранено"); stockEquipment(); openEquipment(id);
    } catch (err) { $("#eErr").textContent = errText(err); }
  };
}

async function openEquipment(id) {
  const e = await api.equipment(id);
  const edit = can("equipment") && e.status !== "written_off";
  const kv = (k, v) => v ? `<dt>${k}</dt><dd>${v}</dd>` : "";
  const box = modal(`<div class="m-h"><h3>${esc(e.name)} · инв. № ${esc(e.inv_number)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      ${e.status === "written_off" ? `<div class="warn-line">Списано ${fmtDate(e.writeoff_date)} по акту № ${esc(e.writeoff_act)}: ${esc(e.writeoff_reason)}</div>` : ""}
      <dl class="kv eq-kv">${kv("Статус", esc(e.status_title))}${kv("Где стоит", esc(e.location))}${kv("Модель", esc(e.model))}${kv("Серийный №", esc(e.serial))}${kv("Раздел", esc(e.category))}
        ${kv("Ответственный", esc(e.responsible))}${kv("Куплено", e.purchase_date ? fmtDate(e.purchase_date) : "")}${kv("Стоимость", e.price ? money(e.price) : "")}
        ${kv("Гарантия до", e.warranty_until ? fmtDate(e.warranty_until) : "")}${kv("Следующее ТО", e.next_service ? fmtDate(e.next_service) : "")}${kv("Комментарий", esc(e.comment))}</dl>
      <h4 class="sub-h">История</h4>
      ${edit ? `<div class="ev-add"><select class="input sm-sel" id="evK"><option value="service">Обслуживание</option><option value="repair">Ремонт</option><option value="note">Заметка</option></select>
        <input class="input" id="evT" placeholder="Что сделано: замена фильтров, ремонт мотора…"><input class="input" id="evC" type="number" min="0" step="any" placeholder="Стоимость, ₽" style="width:130px">
        <label class="fl" style="flex-direction:row;align-items:center;gap:6px;white-space:nowrap">След. ТО <input class="input" type="date" id="evN" value="${esc(e.next_service || "")}"></label><button class="btn small" id="evOk">Добавить</button></div>` : ""}
      <div class="ev-list">${e.events.map(x => `<div class="ev-row"><span class="mv mv-${x.kind}">${esc(x.kind_title)}</span><b>${fmtDate(x.date)}</b><span class="grow">${esc(x.text)}</span>${x.cost ? `<span>${money(x.cost)}</span>` : ""}<small class="muted">${esc(x.user_name || "")}</small></div>`).join("") || '<div class="muted">Записей нет</div>'}</div>
    </div>
    <div class="m-f">${edit ? `<button class="btn ghost small danger" id="eWo">Списать</button>` : ""}<span class="muted"></span>
      ${e.status === "written_off" ? `<button class="btn ghost" id="eAct">Печать акта списания</button>` : ""}<button class="btn ghost" data-close>Закрыть</button>${edit ? `<button class="btn" id="eEd">Изменить</button>` : ""}</div>`, {wide: true});
  const on = (s, f) => { const el = $(s, box); if (el) el.onclick = f; };
  on("#eEd", () => editEquipment(e));
  on("#eWo", () => writeOffEquipment(e));
  on("#eAct", () => printEquipmentAct(e));
  on("#evOk", async () => {
    try { await api.equipment_event({equipment_id: e.id, kind: $("#evK").value, text: $("#evT").value, cost: $("#evC").value, next_service: $("#evN").value}); toast("Записано"); openEquipment(e.id); stockEquipment(); }
    catch (err) { toast(errText(err), true); }
  });
}

function writeOffEquipment(e) {
  const box = modal(`<div class="m-h"><h3>Списание: ${esc(e.name)}, инв. № ${esc(e.inv_number)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid3"><label class="fl">Дата<input class="input" type="date" id="woD" value="${iso(new Date())}"></label><label class="fl">Номер акта<input class="input" id="woN" placeholder="присвоится сам"></label>
        <label class="fl">Остаточная стоимость, ₽<input class="input" type="number" min="0" step="any" id="woR" value="0"></label></div>
      <label class="fl">Причина списания*<input class="input" id="woW" list="woEq" placeholder="например: неисправность, ремонт нецелесообразен"></label>
      <datalist id="woEq"><option value="Физический износ, ремонт экономически нецелесообразен"><option value="Неисправность, не подлежит восстановлению"><option value="Моральный износ, замена на новое"><option value="Повреждение в результате аварии"></datalist>
      <label class="fl">Председатель комиссии*<input class="input" id="woC0" placeholder="ФИО, должность"></label>
      <div class="grid2"><label class="fl">Член комиссии*<input class="input" id="woC1" placeholder="ФИО, должность"></label><label class="fl">Член комиссии<input class="input" id="woC2" placeholder="ФИО, должность"></label></div>
      <div class="warn-line">После списания оборудование нельзя изменить. Акт можно распечатать и подписать комиссией.</div><div class="auth-err" id="woErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="woOk">Списать и распечатать акт</button></div>`, {wide: true});
  $("#woOk", box).onclick = async () => {
    try {
      const r = await api.write_off_equipment({id: e.id, date: $("#woD").value, act_number: $("#woN").value, residual: $("#woR").value, reason: $("#woW").value,
        commission: [$("#woC0").value, $("#woC1").value, $("#woC2").value]});
      closeModal(); toast("Оборудование списано"); stockEquipment(); printEquipmentAct(r);
    } catch (err) { $("#woErr").textContent = errText(err); }
  };
}

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
  const rows = d.moves.map((x, i) => { const q = d.kind === "writeoff" ? -x.qty : x.qty;
    return `<tr><td>${i + 1}</td><td>${esc(x.name)}</td><td>${esc(x.unit)}</td><td>${qtyFmt(q)}</td><td>${money(x.price)}</td><td>${money(Math.abs(x.qty) * x.price)}</td></tr>`; }).join("");
  const total = d.moves.reduce((a, x) => a + Math.abs(x.qty) * x.price, 0);
  $("#printArea").innerHTML = `${head}<h2 style="text-align:center">${esc(DOC_KIND[d.kind])} № ${esc(d.number || "")} от ${fmtDate(d.date)}</h2>
    ${d.supplier_name ? `<p>Поставщик: ${esc(d.supplier_name)}${d.supplier_inn ? ", ИНН " + esc(d.supplier_inn) : ""}</p>` : ""}${d.kind === "writeoff" ? `<p>Причина списания: ${esc(d.reason)}</p>` : ""}
    <table><tr><th>№</th><th>Наименование</th><th>Ед.</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr>${rows}<tr><td colspan="5" style="text-align:right"><b>Итого</b></td><td><b>${money(total)}</b></td></tr></table>
    ${d.kind === "writeoff" ? signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Член комиссии"}, {role: "Утверждаю, руководитель", name: c.director || ""}])
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
async function printInventorySheet(mats) {
  $("#printArea").innerHTML = `${await clinicHead()}<h2>Инвентаризационная опись материалов от ${fmtDate(iso(new Date()))}</h2>
    <table><tr><th>№</th><th>Материал</th><th>Ед.</th><th>По учёту</th><th style="width:110px">Фактически</th><th style="width:110px">Разница</th></tr>${mats.map((m, i) => `<tr><td>${i + 1}</td><td>${esc(m.name)}</td><td>${esc(m.unit)}</td><td>${qtyFmt(m.balance)}</td><td></td><td></td></tr>`).join("")}</table>
    ${signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Материально ответственное лицо"}])}`;
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
