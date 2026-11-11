"use strict";
/* Invoices (services from price list), payments, daily cash report */
const PAY_METHODS = ["Наличные", "Карта", "СБП", "Перевод", "Безнал (организация)", "Сертификат", "Бонусы"];
const PAY_CORE = ["Наличные", "Карта", "СБП", "Перевод", "Безнал (организация)"];

async function openInvoice(o) {
  const R = await ref();
  const inv = o.id ? await api.invoice(o.id) : null;
  const st = {items: inv ? inv.items.map(x => ({...x})) : [], discount: inv ? inv.discount : 0,
    variants: inv && inv.variants ? inv.variants.map(v => ({...v})) : [], variant: (inv && inv.variant) || "", tab: ""};
  const pat = P && P.id === o.patient_id ? P : await api.patient(o.patient_id);
  const isPlan = inv ? inv.kind === "plan" : o.kind === "plan";
  const PLAN_ST = ["Предварительный", "Подтверждён", "Активен", "Лечение завершено", "Брошен", "Отказ"];  // 3.6: «Брошен»
  const box = modal(`<div class="m-h"><h3>${isPlan ? (inv ? "План лечения" : "Новый план лечения") : (inv ? "Счёт" : "Новый счёт")} · ${esc(pat.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b inv">
      <div class="inv-left">
        <input class="input" id="ivQ" placeholder="Поиск услуги по названию или коду" autocomplete="off" autofocus>
        <div class="svc-list" id="ivList"></div>
        <button class="linkbtn" id="ivFree">+ услуга не из прайса</button>
      </div>
      <div class="inv-right">
        <div class="allergy-bar" id="ivAllergy" hidden></div>
        ${isPlan ? `<div class="grid2"><label class="fl">Название плана<input class="input" id="ivTitle" value="${esc((inv && inv.title) || "План лечения от " + fmtDate(iso(new Date())))}"></label>
          <label class="fl">Статус плана<select class="input" id="ivPSt">${typeof pstOptions === "function" ? pstOptions(inv && inv.plan_status) : PLAN_ST.map(s => `<option ${s === ((inv && inv.plan_status) || "Предварительный") ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
          ${inv ? `<div id="ivPHist"></div>` : ""}
          <div class="pv-bar" id="pvBar"></div>` : ""}
        <div class="grid2"><label class="fl">Врач<select class="input" id="ivDoc"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === ((inv && inv.doctor_id) || o.doctor_id) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
          <label class="fl">Скидка на счёт, %<input class="input" id="ivDisc" type="number" min="0" max="100" value="${st.discount || 0}"></label></div>
        <table class="tbl compact inv-items"><thead><tr><th>Услуга</th>${isPlan ? "<th>Этап</th>" : ""}<th>Зуб</th><th>Кол.</th><th>Цена</th><th>Скидка %</th><th>Сумма</th><th></th></tr></thead><tbody id="ivItems"></tbody></table>
        <div class="inv-total">Итого: <b id="ivTotal">0 ₽</b></div>
        <label class="fl">Комментарий<input class="input" id="ivCom" value="${esc((inv && inv.comment) || "")}"></label>
        ${isPlan && inv ? `<div class="pays"><div class="pb-head"><b>Лечение по плану</b></div>
          <div class="muted" style="font-size:12.5px">Отметьте, что сделано на этом приёме, и выставьте счёт — услуги перенесутся в счёт.</div>
          <div class="pay-add"><button class="btn" id="planBill">Выставить счёт по отмеченным</button><button class="btn ghost" id="planPrint">Печать плана</button></div></div>` : ""}
        ${isPlan ? `<div class="pv-pres"><button class="btn ghost" id="planPres">Презентация для пациента</button><span class="muted">Формула, варианты и этапы — печать, PDF или на планшет</span></div>` : ""}
        ${inv && !isPlan ? `<div class="pays"><div class="pb-head"><b>Оплаты</b><span class="muted">Оплачено ${money(inv.paid)} из ${money(inv.total)}</span></div>
          ${inv.payments.map(p => `<div class="pay"><span>${fmtDT(p.created_at)}</span><span>${esc(typeof payLabel === "function" ? payLabel(p) : p.method)}</span><b class="${p.amount < 0 ? "bad-t" : ""}">${money(p.amount)}</b>${receiptPill(p)}${can("payments") ? `<button class="linkbtn" data-delpay="${esc(p.id)}">удалить</button>` : ""}</div>`).join("") || '<div class="muted">Оплат пока нет</div>'}
          ${inv.total - inv.paid > 0.009 ? (!can("payments") ? `<div class="muted">Оплату принимает администратор</div>` : `<div class="pay-add"><input class="input" id="payAmt" type="number" step="0.01" value="${Math.round((inv.total - inv.paid) * 100) / 100}">
            <select class="input" id="payM">${PAY_METHODS.map(m => `<option>${m}</option>`).join("")}</select><button class="btn" id="payGo">Принять оплату</button></div><div class="pay-extra" id="payExtra"></div>${S.settings.fiscal_enabled ? `<div class="pay-fiscal"><label class="switch-row" style="margin:0"><input type="checkbox" id="payRcpt" ${S.settings.fiscal_auto ? "checked" : ""}><span class="sw"></span>Пробить чек${S.settings.fiscal_test ? " (тестовый режим)" : ""}</label><input class="input" id="payContact" placeholder="телефон или e-mail для электронного чека (необязательно)"></div>` : ""}`) : '<div class="ok-t">Счёт оплачен полностью</div>'}
          ${S.settings.fiscal_enabled ? "" : `<div class="muted" style="font-size:12px">Касса не подключена: оплата в программе — не кассовый чек. Пробейте чек на кассе отдельно (подключить кассу — в Настройках).</div>`}</div>` : ""}
      </div>
    </div>
    <div class="m-f">${inv ? `<button class="btn ghost small danger" id="ivDel">Удалить ${isPlan ? "план" : "счёт"}</button>` : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Закрыть</button>
      ${isPlan ? "" : '<button class="btn ghost" id="ivAct">Сохранить и акт</button>'}
      <button class="btn" id="ivSave">${inv ? "Сохранить" : isPlan ? "Сохранить план" : "Выставить счёт"}</button></div>`, {wide: true});

  if (typeof familyDiscountHint === "function") familyDiscountHint(box, pat);
  if (typeof finPayerInit === "function") finPayerInit(box, inv, pat, isPlan);
  if (isPlan && inv && typeof planLabOrders === "function") planLabOrders(box, inv, pat);
  if (isPlan && inv && typeof planHistoryInto === "function") planHistoryInto($("#ivPHist", box), inv.id);  // 3.6
  const total = () => {
    let t = 0;
    st.items.forEach(it => { const s = (+it.price || 0) * (+it.qty || 1) * (1 - (+it.discount || 0) / 100); it.sum = Math.round(s * 100) / 100; t += s; });
    t = t * (1 - (+$("#ivDisc", box).value || 0) / 100);
    if (isPlan && st.variants.length) {
      const by = pvTotals();
      $("#ivTotal", box).innerHTML = st.variants.map(v => `<span class="pv-sum${v.key === st.variant ? " on" : ""}">${esc(v.name)} ${money(by[v.key])}</span>`).join("");
      $$("#pvBar [data-tab]", box).forEach(b => { const s = b.querySelector("small"); if (s && b.dataset.tab) s.textContent = money(by[b.dataset.tab]); });
      return t;
    }
    $("#ivTotal", box).textContent = money(t);
    return t;
  };
  /* sums of every option: common items + the option's own, after the plan discount */
  const pvTotals = () => {
    const k = 1 - (+$("#ivDisc", box).value || 0) / 100, keys = st.variants.map(v => v.key);
    const ls = it => (+it.price || 0) * (+it.qty || 1) * (1 - (+it.discount || 0) / 100);
    const common = st.items.filter(it => !keys.includes(it.opt || "")).reduce((a, it) => a + ls(it), 0);
    return Object.fromEntries(keys.map(key => [key, Math.round((common + st.items.filter(it => it.opt === key).reduce((a, it) => a + ls(it), 0)) * k * 100) / 100]));
  };
  const billableRow = it => !st.variants.length || !st.variants.some(v => v.key === it.opt) || it.opt === st.variant;
  /* «эконом / стандарт / премиум»: tabs, option details and the patient's choice */
  const drawVariants = () => {
    const bar = $("#pvBar", box); if (!bar) return;
    if (!st.variants.length) {
      bar.innerHTML = `<div class="pv-off"><button class="btn ghost small" id="pvOn">+ Несколько вариантов: эконом / стандарт / премиум</button><span class="muted">Пациент выберет один из них, счёт выставится по выбранному</span></div>`;
      $("#pvOn", bar).onclick = () => { st.variants = [{key: "a", name: "Эконом"}, {key: "b", name: "Стандарт"}, {key: "c", name: "Премиум"}]; st.tab = "a"; drawVariants(); drawItems(); };
      return;
    }
    const cur = st.variants.find(v => v.key === st.tab);
    bar.innerHTML = `<div class="pv-tabs" role="tablist"><button data-tab="" class="${st.tab ? "" : "on"}">Общее для всех<small>осмотр, гигиена…</small></button>
        ${st.variants.map(v => `<button data-tab="${esc(v.key)}" class="${st.tab === v.key ? "on" : ""}${st.variant === v.key ? " chosen" : ""}">${esc(v.name)}<small></small></button>`).join("")}
        ${st.variants.length < 4 ? `<button class="pv-add" id="pvAdd" title="Добавить вариант">+</button>` : ""}</div>
      ${cur ? `<div class="pv-det"><label class="fl">Название варианта<input class="input" data-v="name" value="${esc(cur.name)}" maxlength="40"></label>
        <label class="fl">Гарантия<input class="input" data-v="warranty" value="${esc(cur.warranty || "")}" placeholder="например 3 года"></label>
        <label class="fl">Срок лечения<input class="input" data-v="term" value="${esc(cur.term || "")}" placeholder="например 2 визита, 3 недели"></label>
        <label class="fl pv-note"><span>Для пациента: чем хорош вариант <button class="linkbtn ai-pv" id="pvAi" type="button" title="Описание для пациента по услугам, гарантии и сроку">написать за меня</button></span><textarea class="input" data-v="note" rows="2" placeholder="материалы, срок службы, эстетика">${esc(cur.note || "")}</textarea></label>
        <button class="linkbtn danger" id="pvDel">Убрать вариант</button></div>` : `<div class="muted pv-hint">Услуги, выбранные слева, попадают во вкладку, открытую сейчас. Общие услуги входят во все варианты.</div>`}
      <div class="pv-choice"><label class="fl">Пациент выбрал<select class="input" id="pvChosen"><option value="">— ещё не выбрал —</option>${st.variants.map(v => `<option value="${esc(v.key)}" ${v.key === st.variant ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>
        <button class="linkbtn" id="pvOff">Один вариант</button></div>`;
    $$("[data-tab]", bar).forEach(b => b.onclick = () => { st.tab = b.dataset.tab; drawVariants(); drawItems(); });
    $$("[data-v]", bar).forEach(x => x.oninput = () => { cur[x.dataset.v] = x.value; if (x.dataset.v === "name") { const t = $(`[data-tab="${cur.key}"]`, bar); if (t) t.firstChild.textContent = x.value; } });
    const pa = $("#pvAi", bar); if (pa) pa.onclick = async e => {  // 2.13 (14.3): the description for the patient
      e.preventDefault(); pa.disabled = true; pa.textContent = "пишу…";
      const items = st.items.filter(it => !st.variants.some(v => v.key === it.opt) || it.opt === cur.key).map(it => ({title: it.title, tooth: it.tooth || ""}));
      try { const r = await api.ai_plan_variant({...cur, items}); cur.note = r.text; $('[data-v="note"]', bar).value = r.text;
        toast(r.engine === "ai" ? "Описание написал ИИ — проверьте" : r.ai_error ? `ИИ недоступен — описание по правилам` : "Описание составлено по услугам — поправьте при необходимости"); }
      catch (err) { toast(errText(err), true); }
      pa.disabled = false; pa.textContent = "написать за меня";
    };
    const add = $("#pvAdd", bar); if (add) add.onclick = () => { const key = "abcdefgh".split("").find(k => !st.variants.some(v => v.key === k)); st.variants.push({key, name: "Вариант " + (st.variants.length + 1)}); st.tab = key; drawVariants(); drawItems(); };
    const del = $("#pvDel", bar); if (del) del.onclick = async () => {
      const n = st.items.filter(it => it.opt === cur.key).length;
      if (n && !await ask(`Убрать вариант «${cur.name}»?`, {danger: true, ok: "Убрать", text: `Его услуги (${n}) тоже удалятся из плана.`})) return;
      st.items = st.items.filter(it => it.opt !== cur.key); st.variants = st.variants.filter(v => v !== cur);
      if (st.variant === cur.key) st.variant = ""; st.tab = ""; drawVariants(); drawItems(); };
    $("#pvOff", bar).onclick = async () => {
      const extra = st.items.filter(it => st.variants.some(v => v.key === it.opt) && it.opt !== (st.variant || st.variants[0].key)).length;
      const keep = st.variants.find(v => v.key === st.variant) || st.variants[0];
      if (!await ask("Оставить один вариант?", {ok: "Оставить", text: `Останутся общие услуги и вариант «${keep.name}»${extra ? `, услуги других вариантов (${extra}) удалятся` : ""}.`})) return;
      st.items = st.items.filter(it => !st.variants.some(v => v.key === it.opt) || it.opt === keep.key).map(it => ({...it, opt: ""}));
      st.variants = []; st.variant = ""; st.tab = ""; drawVariants(); drawItems(); };
    $("#pvChosen", bar).onchange = e => { st.variant = e.target.value; if (st.variant && $("#ivPSt", box).value === "Предварительный") $("#ivPSt", box).value = "Подтверждён"; drawVariants(); drawItems(); };
  };
  const drawItems = () => {
    const pv = isPlan && st.variants.length;
    $("#ivItems", box).innerHTML = st.items.map((it, i) => `<tr class="${pv && st.tab && (it.opt || "") !== st.tab && st.variants.some(v => v.key === it.opt) ? "pv-dim" : ""}">
      <td>${isPlan && inv ? (billableRow(it) ? `<input type="checkbox" class="pl-ch" data-i="${i}"> ` : `<span class="pl-no" title="Вариант не выбран пациентом">—</span> `) : ""}${esc(it.title)}<small class="muted" style="display:block">${esc(it.code || "")}</small>
      ${pv ? `<select class="input sm pv-opt" data-i="${i}" title="В какой вариант входит услуга"><option value="">Во всех вариантах</option>${st.variants.map(v => `<option value="${esc(v.key)}" ${it.opt === v.key ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select>` : ""}</td>
      ${isPlan ? `<td><input class="input sm" data-i="${i}" data-k="stage" value="${esc(it.stage || "1")}" style="width:50px"></td>` : ""}
      <td><input class="input sm" data-i="${i}" data-k="tooth" value="${esc(it.tooth || "")}" style="width:56px"></td>
      <td><input class="input sm" data-i="${i}" data-k="qty" type="number" min="1" value="${esc(it.qty || 1)}" style="width:56px"></td>
      <td><input class="input sm" data-i="${i}" data-k="price" type="number" min="0" value="${esc(it.price)}" style="width:90px"></td>
      <td><input class="input sm" data-i="${i}" data-k="discount" type="number" min="0" max="100" value="${esc(it.discount || 0)}" style="width:60px"></td>
      <td class="sum">${money(Math.round((+it.price || 0) * (+it.qty || 1) * (1 - (+it.discount || 0) / 100) * 100) / 100)}</td><td><button class="linkbtn" data-del="${i}">×</button></td></tr>`).join("")
      || `<tr><td colspan="9" class="muted" style="padding:16px">Выберите услуги слева</td></tr>`;
    $$("#ivItems .pv-opt", box).forEach(x => x.onchange = () => { st.items[+x.dataset.i].opt = x.value; drawItems(); });
    $$("#ivItems input:not(.pl-ch)", box).forEach(x => x.oninput = () => { st.items[+x.dataset.i][x.dataset.k] = x.value; total();
      $$("#ivItems .sum", box).forEach((td, i) => td.textContent = money(st.items[i].sum)); });
    $$("#ivItems [data-del]", box).forEach(b => b.onclick = () => { st.items.splice(+b.dataset.del, 1); drawItems(); });
    if (typeof finItemsDecorate === "function") finItemsDecorate(box, st, pat, isPlan, drawItems);
    total();
    api.allergy_check(o.patient_id, st.items.map(x => x.title).join("\n")).then(r => allergyBar($("#ivAllergy", box), r)).catch(() => {});
  };
  const drawSvc = async () => {
    const rows = await api.services($("#ivQ", box).value);
    let cat = null;
    $("#ivList", box).innerHTML = rows.map(s => { const h = s.category !== cat ? `<div class="svc-cat">${esc(s.category || "Без раздела")}</div>` : ""; cat = s.category;
      return h + `<button class="svc" data-id="${esc(s.id)}"><span>${esc(s.title)}<small>${esc(s.code || "")}</small></span><b>${money(s.price)}</b></button>`; }).join("")
      || `<div class="muted" style="padding:10px">Прайс пуст. Добавьте услуги в разделе «Шаблоны и прайс» или импортируйте из Excel (CSV).</div>`;
    $$(".svc", box).forEach(b => b.onclick = () => { const s = rows.find(x => x.id === b.dataset.id);
      st.items.push({service_id: s.id, code: s.code, title: s.title, price: s.price, qty: 1, discount: 0, tooth: "", ...(isPlan && st.tab ? {opt: st.tab} : {})}); drawItems(); });
  };
  let t; $("#ivQ", box).oninput = () => { clearTimeout(t); t = setTimeout(drawSvc, 120); };
  $("#ivDisc", box).oninput = total;
  $("#ivFree", box).onclick = async () => { const v = await askInput("Услуга не из прайса", [{label: "Название услуги"}, {label: "Цена, ₽", type: "number", value: "0"}], {ok: "Добавить"}); if (!v) return; const [title, priceS] = v; const price = +(priceS || 0);
    st.items.push({title, price, qty: 1, discount: 0, code: "", ...(isPlan && st.tab ? {opt: st.tab} : {})}); drawItems(); };
  drawVariants(); drawSvc(); drawItems();

  const save = async () => {
    if (!st.items.length) { toast("Добавьте хотя бы одну услугу", true); return null; }
    return api.save_invoice({id: inv ? inv.id : null, patient_id: o.patient_id, visit_id: inv ? inv.visit_id : o.visit_id,
      doctor_id: $("#ivDoc", box).value, items: st.items, discount: +$("#ivDisc", box).value || 0, comment: $("#ivCom", box).value.trim(),
      kind: isPlan ? "plan" : "invoice", title: isPlan ? $("#ivTitle", box).value.trim() : "", plan_status: isPlan ? $("#ivPSt", box).value : null,
      ...(isPlan ? {variants: st.variants, variant: st.variant} : (typeof finPayerValues === "function" ? finPayerValues(box) : {}))});
  };
  $("#ivSave", box).onclick = async () => { const id = await save(); if (!id) return; toast(isPlan ? "План сохранён" : "Счёт сохранён");
    if (o.after) { closeModal(); o.after(id); return; }
    afterChange(); openInvoice({...o, id}); };
  const pb = $("#planBill", box); if (pb) pb.onclick = async () => {
    const idx = $$(".pl-ch", box).filter(c => c.checked).map(c => +c.dataset.i);
    if (!idx.length) return toast("Отметьте выполненные услуги", true);
    try {
      await save();
      const nid = await api.plan_to_invoice(inv.id, idx, o.visit_id || null);
      toast("Счёт выставлен по плану"); afterChange(); openInvoice({patient_id: o.patient_id, id: nid});
    } catch (e) { toast(errText(e), true); }
  };
  const ps = $("#planPres", box); if (ps) ps.onclick = async () => { const id = await save(); if (!id) return; closeModal(); afterChange();
    openPlanPresentation(id, () => openInvoice({...o, id})); };
  // read form values BEFORE closeModal() — it empties the dialog
  const pp = $("#planPrint", box); if (pp) pp.onclick = async () => { const doc = $("#ivDoc", box).value; const id = await save(); if (!id) return; closeModal();
    openDocFill({patient_id: o.patient_id, template_id: "doc_plan", invoice_id: id, doctor_id: doc}); };
  const act = $("#ivAct", box); if (act) act.onclick = async () => { const doc = $("#ivDoc", box).value; const id = await save(); if (!id) return; closeModal(); afterChange();
    openDocFill({patient_id: o.patient_id, template_id: "doc_act", invoice_id: id, doctor_id: doc, visit_id: o.visit_id}); };
  if ($("#payM", box) && typeof payExtraInit === "function") payExtraInit(box, inv, pat);
  if (inv && !isPlan && typeof finInvoicePays === "function") finInvoicePays(box, inv, pat, () => openInvoice({...o, id: inv.id}));
  const pg = $("#payGo", box); if (pg) pg.onclick = async () => {
    const id = await save(); if (!id) return;
    const rc = $("#payRcpt", box), ct = $("#payContact", box);
    const ex = typeof payExtraValues === "function" ? payExtraValues(box) : {};
    const r = await api.add_payment({invoice_id: id, amount: +$("#payAmt", box).value, method: $("#payM", box).value,
      receipt: rc ? rc.checked : false, contact: ct ? ct.value.trim() : "", ...ex});
    if (!r.ok) return toast(r.message, true);
    receiptToast(r.receipt, "Оплата принята"); afterChange(); openInvoice({...o, id});
  };
  $$("[data-delpay]", box).forEach(b => b.onclick = async () => { if (await ask("Удалить оплату?", {danger: true, ok: "Удалить", text: "Оплата исчезнет из счёта и кассового отчёта."})) { try { await api.delete_payment(b.dataset.delpay); afterChange(); openInvoice({...o, id: inv.id}); } catch (e) { toast(errText(e), true); } } });
  $$("[data-rcpt]", box).forEach(b => b.onclick = () => openReceipt(b.dataset.rcpt, () => openInvoice({...o, id: inv.id})));
  $$("[data-print-pay]", box).forEach(b => b.onclick = async () => { try { const r = await api.fiscal_for_payment(b.dataset.printPay, ""); receiptToast(r, "Готово"); openInvoice({...o, id: inv.id}); } catch (e) { toast(errText(e), true); } });
  const dl = $("#ivDel", box); if (dl) dl.onclick = async () => { if (await ask(isPlan ? "Удалить план лечения?" : "Удалить счёт вместе с оплатами?", {danger: true, ok: "Удалить", text: isPlan ? "План пропадёт из карточки пациента." : "Вместе со счётом удалятся его оплаты, а списанные по услугам материалы вернутся на склад."})) { try { await api.delete_invoice(inv.id); closeModal(); afterChange(); } catch (e) { toast(errText(e), true); } } };
}

/* -------------------------------------------------------------- cash */
async function loadCash() {
  const day = $("#cashDay").value || iso(new Date());
  $("#cashDay").value = day;
  // 2.14: without «Касса: отчёт за день» the screen is only the expenses of today (an administrator's clean list)
  $("#cashDay").hidden = $("#cashPrint").hidden = !can("cash_report");
  if (!can("cash_report")) {
    $("#cashBody").innerHTML = `<div id="dxHost"></div>`;
    if (typeof dayExpensesPanel === "function") dayExpensesPanel($("#dxHost"));
    return;
  }
  const c = await api.cash_day(day);
  S.cash = c;
  $("#cashBody").innerHTML = `
    <div class="stat-row">
      <div class="stat"><span>Деньги за день</span><b>${money(c.money_total ?? c.total)}</b></div>
      ${PAY_METHODS.filter(m => PAY_CORE.includes(m) || c.by_method[m]).map(m => `<div class="stat"><span>${m}</span><b>${money(c.by_method[m] || 0)}</b></div>`).join("")}
      ${c.cert_sold ? `<div class="stat"><span>Продано сертификатов</span><b>${money(c.cert_sold)}</b></div>` : ""}
      ${c.refunds ? `<div class="stat warn"><span>Возвраты</span><b>${money(c.refunds)}</b></div>` : ""}
    </div>
    <div id="cashShift"></div>
    ${day === iso(new Date()) ? `<div id="dxHost"></div>` : ""}
    <div class="cash-loyal">${can("payments") ? `<button class="btn ghost small" id="cashCert">Продать сертификат</button>` : ""}<button class="btn ghost small" id="cashCerts">Сертификаты</button><button class="btn ghost small" id="cashMs">Абонементы</button>${c.cert_sales && c.cert_sales.length ? `<span class="muted">За день: ${c.cert_sales.map(x => `${esc(x.code)} — ${money(x.amount)} (${esc(x.method)})`).join("; ")}</span>` : ""}</div>
    <div id="fiscalPanel"></div>
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Оплаты</b></div>
      ${c.payments.length ? `<table class="tbl"><thead><tr><th>Время</th><th>Пациент</th><th>Способ</th><th>Сумма</th><th>В DP</th></tr></thead><tbody>${
        c.payments.map(p => `<tr data-p="${esc(p.patient_id)}"><td>${hm(p.created_at)}</td><td>${esc(p.patient_name || "")}</td><td>${esc(typeof payLabel === "function" ? payLabel(p) : p.method)}</td><td><b class="${p.amount < 0 ? "bad-t" : ""}">${money(p.amount)}</b></td>
          <td>${p.transferred ? '<span class="pill st-done">перенесено</span>' : '<span class="pill st-cancel">нет</span>'}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty"><b>За этот день оплат нет</b></div>`}
    </div>
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Счета за день</b></div>
      ${c.invoices.length ? `<table class="tbl"><thead><tr><th>Время</th><th>Пациент</th><th>Врач</th><th>Сумма</th><th>Оплачено</th><th>Статус</th></tr></thead><tbody>${
        c.invoices.map(i => `<tr data-inv="${esc(i.id)}" data-p="${esc(i.patient_id)}"><td>${hm(i.created_at)}</td><td>${esc(i.patient_name || "")}</td><td>${esc(i.doctor_name || "")}</td><td><b>${money(i.total)}</b></td><td>${money(i.paid)}</td>
          <td><span class="pill ${i.status === "Оплачен" ? "st-ok" : "st-cancel"}">${esc(i.status)}</span></td></tr>`).join("")}</tbody></table>`
        : `<div class="empty"><b>Счетов за этот день нет</b></div>`}
    </div>`;
  renderFiscal(day);
  if (typeof finCashPanel === "function") finCashPanel(c);
  if (typeof dayExpensesPanel === "function" && $("#dxHost")) dayExpensesPanel($("#dxHost"));
  const ms = $("#cashMs"); if (ms && typeof openMembershipTypes === "function") ms.onclick = openMembershipTypes;
  const cs = $("#cashCert"); if (cs && typeof sellCertificate === "function") cs.onclick = () => sellCertificate(loadCash);
  const cl = $("#cashCerts"); if (cl && typeof openCertificates === "function") cl.onclick = openCertificates;
  $$("#cashBody tr[data-inv]").forEach(tr => tr.onclick = () => openInvoice({patient_id: tr.dataset.p, id: tr.dataset.inv}));
  $$("#cashBody tr[data-p]:not([data-inv])").forEach(tr => tr.onclick = () => openPatient(tr.dataset.p, "patients", "billing"));
}
$("#cashDay").onchange = loadCash;
$("#cashPrint").onclick = () => {
  const c = S.cash; if (!c) return;
  $("#printArea").innerHTML = `<h2>Кассовый отчёт за ${fmtDate($("#cashDay").value)}</h2>
    <p>${PAY_METHODS.filter(m => PAY_CORE.includes(m) || c.by_method[m]).map(m => `${m}: <b>${money(c.by_method[m] || 0)}</b>`).join(" · ")}${c.cert_sold ? ` · Продано сертификатов: <b>${money(c.cert_sold)}</b>` : ""} · Деньги за день: <b>${money(c.money_total ?? c.total)}</b></p>
    <table><tr><th>Время</th><th>Пациент</th><th>Способ</th><th>Сумма</th></tr>${c.payments.map(p => `<tr><td>${hm(p.created_at)}</td><td>${esc(p.patient_name || "")}</td><td>${esc(p.method)}</td><td>${money(p.amount)}</td></tr>`).join("")}</table>
    <p style="margin-top:20px">Не является кассовым документом. Подпись ответственного: ______________</p>`;
  window.print();
};
