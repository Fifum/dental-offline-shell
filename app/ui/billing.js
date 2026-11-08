"use strict";
/* Invoices (services from price list), payments, daily cash report */
const PAY_METHODS = ["Наличные", "Карта", "Перевод", "Безнал (организация)"];

async function openInvoice(o) {
  const R = await ref();
  const inv = o.id ? await api.invoice(o.id) : null;
  const st = {items: inv ? inv.items.map(x => ({...x})) : [], discount: inv ? inv.discount : 0};
  const pat = P && P.id === o.patient_id ? P : await api.patient(o.patient_id);
  const isPlan = inv ? inv.kind === "plan" : o.kind === "plan";
  const PLAN_ST = ["Предварительный", "Подтверждён", "Активен", "Лечение завершено", "Отказ"];
  const box = modal(`<div class="m-h"><h3>${isPlan ? (inv ? "План лечения" : "Новый план лечения") : (inv ? "Счёт" : "Новый счёт")} · ${esc(pat.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b inv">
      <div class="inv-left">
        <input class="input" id="ivQ" placeholder="Поиск услуги по названию или коду" autocomplete="off" autofocus>
        <div class="svc-list" id="ivList"></div>
        <button class="linkbtn" id="ivFree">+ услуга не из прайса</button>
      </div>
      <div class="inv-right">
        ${isPlan ? `<div class="grid2"><label class="fl">Название плана<input class="input" id="ivTitle" value="${esc((inv && inv.title) || "План лечения от " + fmtDate(iso(new Date())))}"></label>
          <label class="fl">Статус плана<select class="input" id="ivPSt">${PLAN_ST.map(s => `<option ${s === ((inv && inv.plan_status) || "Предварительный") ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>` : ""}
        <div class="grid2"><label class="fl">Врач<select class="input" id="ivDoc"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === ((inv && inv.doctor_id) || o.doctor_id) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
          <label class="fl">Скидка на счёт, %<input class="input" id="ivDisc" type="number" min="0" max="100" value="${st.discount || 0}"></label></div>
        <table class="tbl compact inv-items"><thead><tr><th>Услуга</th>${isPlan ? "<th>Этап</th>" : ""}<th>Зуб</th><th>Кол.</th><th>Цена</th><th>Скидка %</th><th>Сумма</th><th></th></tr></thead><tbody id="ivItems"></tbody></table>
        <div class="inv-total">Итого: <b id="ivTotal">0 ₽</b></div>
        <label class="fl">Комментарий<input class="input" id="ivCom" value="${esc((inv && inv.comment) || "")}"></label>
        ${isPlan && inv ? `<div class="pays"><div class="pb-head"><b>Лечение по плану</b></div>
          <div class="muted" style="font-size:12.5px">Отметьте, что сделано на этом приёме, и выставьте счёт — услуги перенесутся в счёт.</div>
          <div class="pay-add"><button class="btn" id="planBill">Выставить счёт по отмеченным</button><button class="btn ghost" id="planPrint">Печать плана</button></div></div>` : ""}
        ${inv && !isPlan ? `<div class="pays"><div class="pb-head"><b>Оплаты</b><span class="muted">Оплачено ${money(inv.paid)} из ${money(inv.total)}</span></div>
          ${inv.payments.map(p => `<div class="pay"><span>${fmtDT(p.created_at)}</span><span>${esc(p.method)}</span><b>${money(p.amount)}</b>${receiptPill(p)}${can("payments") ? `<button class="linkbtn" data-delpay="${esc(p.id)}">удалить</button>` : ""}</div>`).join("") || '<div class="muted">Оплат пока нет</div>'}
          ${inv.total - inv.paid > 0.009 ? (!can("payments") ? `<div class="muted">Оплату принимает администратор</div>` : `<div class="pay-add"><input class="input" id="payAmt" type="number" step="0.01" value="${Math.round((inv.total - inv.paid) * 100) / 100}">
            <select class="input" id="payM">${PAY_METHODS.map(m => `<option>${m}</option>`).join("")}</select><button class="btn" id="payGo">Принять оплату</button></div>${S.settings.fiscal_enabled ? `<div class="pay-fiscal"><label class="switch-row" style="margin:0"><input type="checkbox" id="payRcpt" ${S.settings.fiscal_auto ? "checked" : ""}><span class="sw"></span>Пробить чек${S.settings.fiscal_test ? " (тестовый режим)" : ""}</label><input class="input" id="payContact" placeholder="телефон или e-mail для электронного чека (необязательно)"></div>` : ""}`) : '<div class="ok-t">Счёт оплачен полностью</div>'}
          ${S.settings.fiscal_enabled ? "" : `<div class="muted" style="font-size:12px">Касса не подключена: оплата в программе — не кассовый чек. Пробейте чек на кассе отдельно (подключить кассу — в Настройках).</div>`}</div>` : ""}
      </div>
    </div>
    <div class="m-f">${inv ? `<button class="btn ghost small danger" id="ivDel">Удалить ${isPlan ? "план" : "счёт"}</button>` : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Закрыть</button>
      ${isPlan ? "" : '<button class="btn ghost" id="ivAct">Сохранить и акт</button>'}
      <button class="btn" id="ivSave">${inv ? "Сохранить" : isPlan ? "Сохранить план" : "Выставить счёт"}</button></div>`, {wide: true});

  const total = () => {
    let t = 0;
    st.items.forEach(it => { const s = (+it.price || 0) * (+it.qty || 1) * (1 - (+it.discount || 0) / 100); it.sum = Math.round(s * 100) / 100; t += s; });
    t = t * (1 - (+$("#ivDisc", box).value || 0) / 100);
    $("#ivTotal", box).textContent = money(t);
    return t;
  };
  const drawItems = () => {
    $("#ivItems", box).innerHTML = st.items.map((it, i) => `<tr>
      <td>${isPlan && inv ? `<input type="checkbox" class="pl-ch" data-i="${i}"> ` : ""}${esc(it.title)}<small class="muted" style="display:block">${esc(it.code || "")}</small></td>
      ${isPlan ? `<td><input class="input sm" data-i="${i}" data-k="stage" value="${esc(it.stage || "1")}" style="width:50px"></td>` : ""}
      <td><input class="input sm" data-i="${i}" data-k="tooth" value="${esc(it.tooth || "")}" style="width:56px"></td>
      <td><input class="input sm" data-i="${i}" data-k="qty" type="number" min="1" value="${esc(it.qty || 1)}" style="width:56px"></td>
      <td><input class="input sm" data-i="${i}" data-k="price" type="number" min="0" value="${esc(it.price)}" style="width:90px"></td>
      <td><input class="input sm" data-i="${i}" data-k="discount" type="number" min="0" max="100" value="${esc(it.discount || 0)}" style="width:60px"></td>
      <td class="sum">${money(it.sum || it.price)}</td><td><button class="linkbtn" data-del="${i}">×</button></td></tr>`).join("")
      || `<tr><td colspan="7" class="muted" style="padding:16px">Выберите услуги слева</td></tr>`;
    $$("#ivItems input:not(.pl-ch)", box).forEach(x => x.oninput = () => { st.items[+x.dataset.i][x.dataset.k] = x.value; total();
      $$("#ivItems .sum", box).forEach((td, i) => td.textContent = money(st.items[i].sum)); });
    $$("#ivItems [data-del]", box).forEach(b => b.onclick = () => { st.items.splice(+b.dataset.del, 1); drawItems(); });
    total();
  };
  const drawSvc = async () => {
    const rows = await api.services($("#ivQ", box).value);
    let cat = null;
    $("#ivList", box).innerHTML = rows.map(s => { const h = s.category !== cat ? `<div class="svc-cat">${esc(s.category || "Без раздела")}</div>` : ""; cat = s.category;
      return h + `<button class="svc" data-id="${esc(s.id)}"><span>${esc(s.title)}<small>${esc(s.code || "")}</small></span><b>${money(s.price)}</b></button>`; }).join("")
      || `<div class="muted" style="padding:10px">Прайс пуст. Добавьте услуги в разделе «Шаблоны и прайс» или импортируйте из Excel (CSV).</div>`;
    $$(".svc", box).forEach(b => b.onclick = () => { const s = rows.find(x => x.id === b.dataset.id);
      st.items.push({service_id: s.id, code: s.code, title: s.title, price: s.price, qty: 1, discount: 0, tooth: ""}); drawItems(); });
  };
  let t; $("#ivQ", box).oninput = () => { clearTimeout(t); t = setTimeout(drawSvc, 120); };
  $("#ivDisc", box).oninput = total;
  $("#ivFree", box).onclick = async () => { const v = await askInput("Услуга не из прайса", [{label: "Название услуги"}, {label: "Цена, ₽", type: "number", value: "0"}], {ok: "Добавить"}); if (!v) return; const [title, priceS] = v; const price = +(priceS || 0);
    st.items.push({title, price, qty: 1, discount: 0, code: ""}); drawItems(); };
  drawSvc(); drawItems();

  const save = async () => {
    if (!st.items.length) { toast("Добавьте хотя бы одну услугу", true); return null; }
    return api.save_invoice({id: inv ? inv.id : null, patient_id: o.patient_id, visit_id: inv ? inv.visit_id : o.visit_id,
      doctor_id: $("#ivDoc", box).value, items: st.items, discount: +$("#ivDisc", box).value || 0, comment: $("#ivCom", box).value.trim(),
      kind: isPlan ? "plan" : "invoice", title: isPlan ? $("#ivTitle", box).value.trim() : "", plan_status: isPlan ? $("#ivPSt", box).value : null});
  };
  $("#ivSave", box).onclick = async () => { const id = await save(); if (!id) return; toast(isPlan ? "План сохранён" : "Счёт сохранён");
    if (o.after) { closeModal(); o.after(id); return; }
    afterChange(); openInvoice({...o, id}); };
  const pb = $("#planBill", box); if (pb) pb.onclick = async () => {
    const idx = $$(".pl-ch", box).filter(c => c.checked).map(c => +c.dataset.i);
    if (!idx.length) return toast("Отметьте выполненные услуги", true);
    await save();
    const nid = await api.plan_to_invoice(inv.id, idx, o.visit_id || null);
    toast("Счёт выставлен по плану"); afterChange(); openInvoice({patient_id: o.patient_id, id: nid});
  };
  // read form values BEFORE closeModal() — it empties the dialog
  const pp = $("#planPrint", box); if (pp) pp.onclick = async () => { const doc = $("#ivDoc", box).value; const id = await save(); if (!id) return; closeModal();
    openDocFill({patient_id: o.patient_id, template_id: "doc_plan", invoice_id: id, doctor_id: doc}); };
  const act = $("#ivAct", box); if (act) act.onclick = async () => { const doc = $("#ivDoc", box).value; const id = await save(); if (!id) return; closeModal(); afterChange();
    openDocFill({patient_id: o.patient_id, template_id: "doc_act", invoice_id: id, doctor_id: doc, visit_id: o.visit_id}); };
  const pg = $("#payGo", box); if (pg) pg.onclick = async () => {
    const id = await save(); if (!id) return;
    const rc = $("#payRcpt", box), ct = $("#payContact", box);
    const r = await api.add_payment({invoice_id: id, amount: +$("#payAmt", box).value, method: $("#payM", box).value,
      receipt: rc ? rc.checked : false, contact: ct ? ct.value.trim() : ""});
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
  const c = await api.cash_day(day);
  S.cash = c;
  $("#cashBody").innerHTML = `
    <div class="stat-row">
      <div class="stat"><span>Всего за день</span><b>${money(c.total)}</b></div>
      ${PAY_METHODS.map(m => `<div class="stat"><span>${m}</span><b>${money(c.by_method[m] || 0)}</b></div>`).join("")}
    </div>
    <div id="fiscalPanel"></div>
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Оплаты</b></div>
      ${c.payments.length ? `<table class="tbl"><thead><tr><th>Время</th><th>Пациент</th><th>Способ</th><th>Сумма</th><th>В DP</th></tr></thead><tbody>${
        c.payments.map(p => `<tr data-p="${esc(p.patient_id)}"><td>${hm(p.created_at)}</td><td>${esc(p.patient_name || "")}</td><td>${esc(p.method)}</td><td><b>${money(p.amount)}</b></td>
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
  $$("#cashBody tr[data-inv]").forEach(tr => tr.onclick = () => openInvoice({patient_id: tr.dataset.p, id: tr.dataset.inv}));
  $$("#cashBody tr[data-p]:not([data-inv])").forEach(tr => tr.onclick = () => openPatient(tr.dataset.p, "patients", "billing"));
}
$("#cashDay").onchange = loadCash;
$("#cashPrint").onclick = () => {
  const c = S.cash; if (!c) return;
  $("#printArea").innerHTML = `<h2>Кассовый отчёт за ${fmtDate($("#cashDay").value)}</h2>
    <p>${PAY_METHODS.map(m => `${m}: <b>${money(c.by_method[m] || 0)}</b>`).join(" · ")} · Итого: <b>${money(c.total)}</b></p>
    <table><tr><th>Время</th><th>Пациент</th><th>Способ</th><th>Сумма</th></tr>${c.payments.map(p => `<tr><td>${hm(p.created_at)}</td><td>${esc(p.patient_name || "")}</td><td>${esc(p.method)}</td><td>${money(p.amount)}</td></tr>`).join("")}</table>
    <p style="margin-top:20px">Не является кассовым документом. Подпись ответственного: ______________</p>`;
  window.print();
};
