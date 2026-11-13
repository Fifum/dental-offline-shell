"use strict";
/* Money 2.12: the patient's advance and paying invoices from it, refunds, payment schedules (installments),
   memberships, the cash drawer by shifts with reconciliation, ДМС (insurers, policies and letters, registries),
   reminders about debts. Hooks are called from app.js (patient card), billing.js (invoice, cash), reports.js
   (debts), accounting.js (tab «ДМС») and crm.js (settings). */
const MONEY_M = ["Наличные", "Карта", "СБП", "Перевод"];
const SCH_ST = {paid: ["оплачен", "st-done"], part: ["частично", "st-come"], late: ["просрочен", "st-cancel"], wait: ["ожидается", ""]};
const finOpts = (arr, cur) => arr.map(x => `<option ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("");
const finFiscalBox = () => S.settings.fiscal_enabled ? `<label class="switch-row"><input type="checkbox" id="fxRcpt" ${S.settings.fiscal_auto ? "checked" : ""}><span class="sw"></span>Пробить чек${S.settings.fiscal_test ? " (тестовый режим)" : ""}</label>` : "";
function payLabel(p) {
  if (p.kind === "refund") return "Возврат · " + p.method;
  if (p.kind === "deposit_use") return p.amount < 0 ? "Аванс ушёл в оплату счёта" : "Из аванса";
  if (p.kind === "insurance") return "Страховая (реестр)";
  return !p.invoice_id && p.amount > 0 ? "Аванс · " + p.method : p.method;
}
async function finReloadPatient(pid) { if (P && P.id === pid) { P = await api.patient(pid); renderPatient(S.patientTab); } afterChange(); }

/* ================================================================ patient card */
function finHeader(p) {
  const col = $("#patientCard .phead2 .ph-col:last-child"); if (!col || $(".ph-fin", col) || !canAny("payments", "billing")) return;
  const d = document.createElement("div"); d.className = "ph-fin";
  const ms = (p.memberships || []).filter(m => m.active);
  d.innerHTML = `<dt>Аванс</dt><dd><button class="linkbtn ${p.deposit > 0 ? "ok-t" : p.deposit < 0 ? "bad-t" : ""}" id="fhDep">${p.deposit > 0 || p.deposit < 0 ? money(p.deposit) : can("payments") ? "внести" : "—"}</button></dd>`
    + (ms.length ? `<dt>Абонемент</dt><dd>${ms.map(m => `${esc(m.name)} <small class="muted">(${m.items.map(i => i.left).reduce((a, b) => a + b, 0)} усл.)</small>`).join("<br>")}</dd>` : "")
    + ((p.ins_docs || []).length ? `<dt>ДМС</dt><dd>${esc(p.ins_docs[0].insurer_name || "")}${p.ins_docs.length > 1 ? ` <small class="muted">+${p.ins_docs.length - 1}</small>` : ""}</dd>` : "");
  col.appendChild(d);
  $("#fhDep", d).onclick = () => p.deposit > 0 || p.deposit < 0 ? openPatient(p.id, S.view, "payments") : can("payments") && openDeposit(p);
}

async function finPatientTab(p) {
  const box = $("#finPatient"); if (!box) return;
  const m = await api.money_patient(p.id).catch(() => null); if (!m) return;
  const pay = can("payments"), bill = can("billing");
  const ms = m.memberships, sch = m.schedules.filter(s => s.left > 0.009), docs = m.ins_docs;
  box.innerHTML = `<div class="fin-bar">
      <span class="fin-dep">Аванс: <b class="${m.deposit > 0 ? "ok-t" : m.deposit < 0 ? "bad-t" : ""}">${money(m.deposit)}</b>${m.pockets.length > 1 ? ` <small class="muted">(${m.pockets.map(x => esc(x.title.toLowerCase()) + " " + money(x.amount)).join(", ")})</small>` : ""}${m.pockets.some(x => !x.invoice_id && x.amount < 0) ? ` <span class="bad-t">— аванс потратили дважды (на компьютерах без сети): пациент должен клинике</span>` : ""}</span>
      ${pay ? `<button class="btn ghost small" id="fpDep">Внести аванс</button>` : ""}
      ${pay && m.deposit > 0 ? `<button class="btn ghost small" id="fpRef">Вернуть деньги</button>` : ""}
      ${bill ? `<button class="btn ghost small" id="fpMs">Продать абонемент</button>` : ""}
      ${canAny("patients_edit", "billing") ? `<button class="btn ghost small" id="fpIns">Полис ДМС / гарантийное письмо</button>` : ""}</div>
    ${ms.length ? `<h4 class="sub-h">Абонементы</h4><table class="tbl compact"><thead><tr><th>Абонемент</th><th>Услуги: осталось из</th><th>Действует до</th><th>Оплата</th><th></th></tr></thead><tbody>${
      ms.map(x => `<tr><td><b>${esc(x.name)}</b><small class="muted" style="display:block">продан ${fmtDate(x.sold_at)} за ${money(x.price)}</small></td>
        <td>${x.items.map(i => `${esc(i.title)}: <b>${i.left}</b> из ${i.qty}`).join("<br>")}</td>
        <td class="nowrap">${fmtDate(x.expires)}${x.expired ? ' <span class="pill st-cancel">истёк</span>' : x.status !== "active" ? ' <span class="pill st-cancel">аннулирован</span>' : ""}</td>
        <td>${x.paid ? '<span class="pill st-ok">оплачен</span>' : `<button class="linkbtn" data-msinv="${esc(x.invoice_id)}">не оплачен — открыть счёт</button>`}</td>
        <td class="row-acts">${can("accounting") && x.status === "active" ? `<button class="linkbtn" data-mscx="${esc(x.id)}">аннулировать</button>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
    ${sch.length ? `<h4 class="sub-h">Рассрочка</h4>${sch.map(s => `<div class="sch-line" data-inv="${esc(s.invoice_id)}"><span>Счёт на ${money(s.total)}: оплачено ${money(s.paid)}, осталось <b>${money(s.left)}</b></span>
        ${s.overdue ? `<span class="pill st-cancel">просрочено ${money(s.overdue)} с ${fmtDate(s.late_since)}</span>` : s.next ? `<span class="muted">следующий платёж ${fmtDate(s.next.date)} — ${money(s.next.left)}</span>` : ""}</div>`).join("")}` : ""}
    ${docs.length ? `<h4 class="sub-h">ДМС</h4><table class="tbl compact"><thead><tr><th>Страховая</th><th>Документ</th><th>Действует до</th><th class="num">Лимит</th><th class="num">Использовано</th><th></th></tr></thead><tbody>${
      docs.map(x => `<tr><td>${esc(x.insurer_name || "")}</td><td>${esc(x.kind_title)} № ${esc(x.number)}${x.date ? ` от ${fmtDate(x.date)}` : ""}</td>
        <td class="nowrap">${x.valid_to ? fmtDate(x.valid_to) : "—"}${x.expired ? ' <span class="pill st-cancel">истёк</span>' : ""}</td>
        <td class="num">${x.limit_sum ? money(x.limit_sum) : "—"}</td><td class="num">${money(x.used)}</td>
        <td class="row-acts">${canAny("patients_edit", "billing") ? `<button class="linkbtn" data-insd="${esc(x.id)}">изменить</button>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}`;
  const on = (id, fn) => { const b = $(id, box); if (b) b.onclick = fn; };
  on("#fpDep", () => openDeposit(p));
  on("#fpRef", () => openRefund(p, {max: m.deposit}));
  on("#fpMs", () => openMembershipSell(p));
  on("#fpIns", () => openInsDoc(p, null, m.insurers));
  $$("[data-msinv]", box).forEach(b => b.onclick = () => openInvoice({patient_id: p.id, id: b.dataset.msinv}));
  $$("[data-mscx]", box).forEach(b => b.onclick = async () => { if (await ask("Аннулировать абонемент?", {danger: true, ok: "Аннулировать", text: "Оставшимися услугами больше нельзя будет воспользоваться. Деньги, если нужно, верните через «Вернуть деньги»."})) { try { await api.membership_cancel(b.dataset.mscx); finReloadPatient(p.id); } catch (e) { toast(errText(e), true); } } });
  $$(".sch-line", box).forEach(r => r.onclick = () => openInvoice({patient_id: p.id, id: r.dataset.inv}));
  $$("[data-insd]", box).forEach(b => b.onclick = () => openInsDoc(p, docs.find(x => x.id === b.dataset.insd), m.insurers));
  $$("#patientCard [data-delfree]").forEach(b => b.onclick = async e => { e.stopPropagation();
    if (!await ask("Удалить запись об авансе или возврате?", {danger: true, ok: "Удалить", text: "Удаляйте только ошибочные записи: деньги исчезнут из кассового отчёта."})) return;
    try { if (!await deletePayment(b.dataset.delfree)) return; toast("Удалено"); finReloadPatient(p.id); } catch (er) { toast(errText(er), true); } });
}

/* ------------------------------------------------------------ advance and refunds */
function openDeposit(p) {
  const box = modal(`<div class="m-h"><h3>Аванс · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Деньги вперёд, до выставления счёта — например, предоплата за имплантацию или ортодонтию. Потом в счёте нажмите «Оплатить из аванса».</p>
      <div class="grid2"><label class="fl">Сумма, ₽<input class="input" id="fxA" type="number" min="1" step="0.01" autofocus></label>
        <label class="fl">Способ<select class="input" id="fxM">${finOpts(MONEY_M, "Наличные")}</select></label></div>
      <label class="fl">Комментарий<input class="input" id="fxC" placeholder="например, предоплата за брекеты"></label>${finFiscalBox()}
      <div class="auth-err" id="fxErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="fxOk">Принять аванс</button></div>`);
  const rid = reqId(), ok = $("#fxOk", box);
  ok.onclick = () => busy(ok, async () => {
    const rc = $("#fxRcpt", box);
    const r = await api.add_payment({patient_id: p.id, amount: +$("#fxA", box).value, method: $("#fxM", box).value,
      comment: ("аванс " + $("#fxC", box).value.trim()).trim(), receipt: rc ? rc.checked : false, request_id: rid});
    if (!r.ok) { $("#fxErr", box).textContent = r.message; return; }
    closeModal(); receiptToast(r.receipt, "Аванс принят"); finReloadPatient(p.id);
  });
}
function openRefund(p, {invoice_id = null, max = 0, after} = {}) {
  const box = modal(`<div class="m-h"><h3>Вернуть деньги · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">${invoice_id ? "Переплата по этому счёту" : "Аванс пациента"}: <b>${money(max)}</b>. Отдайте деньги тем же способом, каким пациент платил.</p>
      <div class="grid2"><label class="fl">Сумма, ₽<input class="input" id="fxA" type="number" min="1" step="0.01" value="${Math.round(max * 100) / 100}" autofocus></label>
        <label class="fl">Как вернули<select class="input" id="fxM">${finOpts(MONEY_M, "Наличные")}</select></label></div>
      <label class="fl">Причина<input class="input" id="fxR" placeholder="например, отказ от лечения"></label>${finFiscalBox()}
      <div class="auth-err" id="fxErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn danger" id="fxOk">Вернуть</button></div>`);
  const rid = reqId(), ok = $("#fxOk", box);
  ok.onclick = () => busy(ok, async () => {
    const rc = $("#fxRcpt", box);
    try {
      const r = await api.refund({patient_id: p.id, invoice_id, amount: $("#fxA", box).value, method: $("#fxM", box).value, reason: $("#fxR", box).value,
        receipt: rc ? rc.checked : false, request_id: rid});
      closeModal(); receiptToast(r.receipt, `Возврат ${money(r.amount)} записан`);
      if (after) after(); else finReloadPatient(p.id);
    } catch (e) { $("#fxErr", box).textContent = errText(e); }
  });
}

/* ============================================================== invoice editor */
function finCovers(m, it) {
  return m.items.find(x => (it.service_id && x.service_id) ? it.service_id === x.service_id : String(x.title || "").trim().toLowerCase() === String(it.title || "").trim().toLowerCase());
}
function finItemsDecorate(box, st, pat, isPlan, redraw) {
  const ms = (pat.memberships || []).filter(m => m.active || st.items.some(it => it.membership === m.id));
  if (isPlan || !ms.length) return;
  const rows = $$("#ivItems tr", box);
  st.items.forEach((it, i) => {
    const td = rows[i] && rows[i].firstElementChild; if (!td) return;
    if (it.membership) {
      const m = ms.find(x => x.id === it.membership);
      td.insertAdjacentHTML("beforeend", `<span class="pill st-ok ms-pill">по абонементу${m ? " «" + esc(m.name) + "»" : ""} <button class="linkbtn" data-msoff="${i}" title="Не по абонементу">×</button></span>`);
      return;
    }
    const m = ms.find(x => x.active && finCovers(x, it) && finCovers(x, it).left > 0);
    if (m) td.insertAdjacentHTML("beforeend", `<button class="linkbtn ms-use" data-mson="${i}" data-m="${esc(m.id)}">по абонементу (осталось ${finCovers(m, it).left})</button>`);
  });
  $$("[data-mson]", box).forEach(b => b.onclick = () => { const it = st.items[+b.dataset.mson]; it.membership = b.dataset.m; it.discount = 100; redraw(); });
  $$("[data-msoff]", box).forEach(b => b.onclick = () => { const it = st.items[+b.dataset.msoff]; delete it.membership; it.discount = 0; redraw(); });
}
function finPayerInit(box, inv, pat, isPlan) {
  if (isPlan) return;
  const docs = (pat.ins_docs || []).slice();
  if (inv && inv.insurer_id && !docs.some(d => d.id === inv.ins_doc_id)) docs.push({id: inv.ins_doc_id || "", insurer_id: inv.insurer_id, insurer_name: inv.insurer_name, kind_title: "документ", number: ""});
  if (!docs.length) return;
  const cur = inv && inv.insurer_id ? `${inv.insurer_id}|${inv.ins_doc_id || ""}` : "";
  const grid = $("#ivDoc", box).closest(".grid2");
  grid.insertAdjacentHTML("afterend", `<label class="fl fin-payer">Кто платит<select class="input" id="ivPayer"><option value="">Пациент</option>${docs.map(d => { const v = `${d.insurer_id}|${d.id}`;
    return `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>Страховая: ${esc(d.insurer_name || "")} — ${esc(d.kind_title)} ${d.number ? "№ " + esc(d.number) : ""}${d.left != null ? ` (осталось ${money(d.left)})` : ""}</option>`; }).join("")}</select></label>`);
}
function finPayerValues(box) {
  const s = $("#ivPayer", box); if (!s) return {};
  const [ins, doc] = s.value.split("|");
  return {insurer_id: ins || null, ins_doc_id: doc || null};
}
function finInvoicePays(box, inv, pat, reopen) {
  const pays = $(".pays", box); if (!pays || !inv || inv.kind === "plan") return;
  const due = Math.round((inv.total - inv.paid) * 100) / 100;
  const el = document.createElement("div"); el.className = "fin-inv";
  let html = "";
  if (inv.insurer_id) html += `<div class="pill st-come ins-pill">Оплачивает страховая «${esc(inv.insurer_name || "")}» по реестру (Бухгалтерия → ДМС)</div>`;
  if (can("payments") && !inv.insurer_id && inv.deposit > 0.009 && due > 0.009)
    html += `<button class="btn ghost small" id="fiDep">Оплатить из аванса — есть ${money(inv.deposit)}</button>`;
  if (can("payments") && inv.overpaid > 0.009) html += `<button class="btn ghost small" id="fiRef">Вернуть переплату ${money(inv.overpaid)}</button>`;
  const s = inv.schedule;
  if (s) {
    html += `<div class="sch-box"><div class="pb-head"><b>График платежей</b><span>${s.overdue ? `<span class="pill st-cancel">просрочено ${money(s.overdue)}</span>` : ""}
      <button class="linkbtn" id="fiSch">изменить</button><button class="linkbtn" id="fiSchP">печать</button></span></div>
      <table class="tbl compact"><tbody>${s.items.map(x => `<tr><td class="nowrap">${fmtDate(x.date)}</td><td class="num">${money(x.amount)}</td><td><span class="pill ${SCH_ST[x.status][1]}">${SCH_ST[x.status][0]}</span>${x.status === "part" || x.status === "late" ? ` <small class="muted">осталось ${money(x.left)}</small>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  } else if (canAny("payments", "billing") && !inv.insurer_id && due > 0.009) html += `<button class="btn ghost small" id="fiSch">Рассрочка: график платежей</button>`;
  if (!html) return;
  el.innerHTML = html; pays.appendChild(el);
  const on = (id, fn) => { const b = $(id, el); if (b) b.onclick = fn; };
  on("#fiDep", async () => {
    const v = await askInput("Оплатить из аванса", [{label: `Сумма, ₽ (аванс ${money(inv.deposit)}, по счёту осталось ${money(due)})`, type: "number", value: String(Math.min(inv.deposit, due))}], {ok: "Оплатить"});
    if (!v) return;
    try { const r = await api.deposit_use(inv.id, v[0], S.settings.fiscal_enabled ? S.settings.fiscal_auto : false); receiptToast(r.receipt, `Из аванса оплачено ${money(r.amount)}`); afterChange(); reopen(); }
    catch (e) { toast(errText(e), true); }
  });
  on("#fiRef", () => openRefund(pat, {invoice_id: inv.id, max: inv.overpaid, after: () => { afterChange(); reopen(); }}));
  on("#fiSch", () => openSchedule(inv, pat, reopen));
  on("#fiSchP", () => printSchedule(inv, pat, s));
}

/* ------------------------------------------------------------ schedule */
async function openSchedule(inv, pat, reopen) {
  let rows = inv.schedule ? inv.schedule.items.map(x => ({date: x.date, amount: x.amount})) : await api.schedule_draft(inv.id, 3, null, "month");
  const box = modal(`<div class="m-h"><h3>Рассрочка · счёт на ${money(inv.total)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="sch-gen"><label class="fl">Платежей<input class="input num" id="sgN" type="number" min="2" max="60" value="${Math.max(2, rows.length)}"></label>
      <label class="fl">Как часто<select class="input" id="sgS"><option value="month">раз в месяц</option><option value="2w">раз в две недели</option></select></label>
      <label class="fl">Первый платёж после оплаченного<input class="input" id="sgF" type="date" value="${iso(new Date())}"></label><button class="btn ghost small" id="sgGo">Разбить поровну</button></div>
      <p class="hint">Уже оплачено ${money(inv.paid)} — это первая строка графика. Даты и суммы можно поправить; сумма всех платежей равна сумме счёта.</p>
      <table class="tbl compact sch-ed"><thead><tr><th>Дата</th><th>Сумма, ₽</th><th></th></tr></thead><tbody id="sgRows"></tbody></table>
      <button class="linkbtn" id="sgAdd">+ платёж</button><div class="sch-sum" id="sgSum"></div>
      <label class="fl">Примечание<input class="input" id="sgNote" value="${esc((inv.schedule && inv.schedule.note) || "")}" placeholder="например, по договору № …"></label>
      <div class="auth-err" id="sgErr"></div></div>
    <div class="m-f">${inv.schedule ? `<button class="btn ghost small danger" id="sgDel">Убрать график</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="sgOk">Сохранить график</button></div>`, {wide: true});
  const draw = () => {
    $("#sgRows", box).innerHTML = rows.map((r, i) => `<tr><td><input class="input sm" type="date" data-i="${i}" data-k="date" value="${esc(r.date)}"></td>
      <td><input class="input sm" type="number" step="0.01" min="0" data-i="${i}" data-k="amount" value="${r.amount}"></td><td><button class="linkbtn" data-del="${i}">×</button></td></tr>`).join("");
    $$("#sgRows input", box).forEach(x => x.oninput = () => { rows[+x.dataset.i][x.dataset.k] = x.dataset.k === "amount" ? +x.value : x.value; sum(); });
    $$("#sgRows [data-del]", box).forEach(b => b.onclick = () => { rows.splice(+b.dataset.del, 1); draw(); });
    sum();
  };
  const sum = () => { const s = Math.round(rows.reduce((a, r) => a + (+r.amount || 0), 0) * 100) / 100; const d = Math.round((inv.total - s) * 100) / 100;
    $("#sgSum", box).innerHTML = `Итого ${money(s)}${Math.abs(d) > 0.009 ? ` · <span class="bad-t">${d > 0 ? "не хватает" : "лишние"} ${money(Math.abs(d))}</span>` : ' · <span class="ok-t">совпадает с суммой счёта</span>'}`; };
  $("#sgGo", box).onclick = async () => { try { rows = await api.schedule_draft(inv.id, $("#sgN", box).value, $("#sgF", box).value, $("#sgS", box).value); draw(); } catch (e) { toast(errText(e), true); } };
  $("#sgAdd", box).onclick = () => { const last = rows[rows.length - 1]; rows.push({date: last ? addDays(last.date, 30) : iso(new Date()), amount: 0}); draw(); };
  $("#sgOk", box).onclick = async () => {
    try { const s = await api.schedule_save({invoice_id: inv.id, items: rows, note: $("#sgNote", box).value}); closeModal(); toast("График платежей сохранён");
      if (await ask("Распечатать график для пациента?", {icon: "edit", ok: "Печать", cancel: "Не нужно"})) printSchedule(inv, pat, s);
      afterChange(); reopen(); }
    catch (e) { $("#sgErr", box).textContent = errText(e); }
  };
  const dl = $("#sgDel", box); if (dl) dl.onclick = async () => { if (await ask("Убрать график платежей?", {danger: true, ok: "Убрать"})) { await api.schedule_delete(inv.id); closeModal(); afterChange(); reopen(); } };
  draw();
}
async function printSchedule(inv, pat, s) {
  const cl = (await ref()).clinic || {};
  printDoc(`<div style="font-family:Arial,sans-serif;font-size:11pt"><div>${esc(cl.name || "")}${cl.address ? ", " + esc(cl.address) : ""}</div>
    <h2 style="text-align:center;margin:24px 0 8px">График платежей</h2>
    <p>Пациент: <b>${esc(pat.name)}</b>. Счёт от ${fmtDate(inv.created_at)} на сумму <b>${money(inv.total)}</b>: ${esc(inv.items.map(x => x.title).join(", "))}.</p>
    <table style="width:100%;border-collapse:collapse" border="1" cellpadding="6"><tr><th>№</th><th>Дата платежа</th><th>Сумма</th><th>Отметка об оплате</th></tr>
      ${s.items.map((x, i) => `<tr><td>${i + 1}</td><td>${fmtDate(x.date)}</td><td>${money(x.amount)}</td><td>${x.status === "paid" ? "оплачено" : ""}</td></tr>`).join("")}
      <tr><td></td><td><b>Итого</b></td><td><b>${money(s.total)}</b></td><td></td></tr></table>
    ${s.note ? `<p>${esc(s.note)}</p>` : ""}
    <p style="margin-top:36px">Пациент: ____________ / ${esc(pat.name)} /&nbsp;&nbsp;&nbsp;&nbsp;Клиника: ____________</p></div>`);
}

/* ============================================================== memberships */
async function openMembershipSell(p) {
  const types = await api.membership_types();
  if (!types.length) {
    if (canAny("refs", "accounting") && await ask("Видов абонементов пока нет", {icon: "edit", ok: "Создать", text: "Сначала опишите абонемент: какие услуги, сколько раз, цена и срок."})) openMembershipTypes();
    else if (!canAny("refs", "accounting")) toast("Видов абонементов пока нет — их заводит директор в «Касса» → «Абонементы»", true);
    return;
  }
  const box = modal(`<div class="m-h"><h3>Продать абонемент · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Абонемент<select class="input" id="msT">${types.map(t => `<option value="${esc(t.id)}">${esc(t.name)} — ${money(t.price)}, ${t.months} мес.</option>`).join("")}</select></label>
      <div id="msInfo" class="muted"></div>
      <label class="fl">Цена, ₽<input class="input" id="msP" type="number" min="1" step="0.01"></label><div class="auth-err" id="msErr"></div></div>
    <div class="m-f"><span class="muted">Будет выставлен счёт — примите по нему оплату</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="msOk">Продать</button></div>`);
  const show = () => { const t = types.find(x => x.id === $("#msT", box).value); $("#msP", box).value = t.price;
    $("#msInfo", box).innerHTML = "Входит: " + t.items.map(i => `${esc(i.title)} × ${i.qty}`).join(", ") + (t.note ? `<br>${esc(t.note)}` : ""); };
  $("#msT", box).onchange = show; show();
  $("#msOk", box).onclick = async () => {
    try { const r = await api.membership_sell({type_id: $("#msT", box).value, patient_id: p.id, price: $("#msP", box).value}); closeModal(); toast("Абонемент продан — примите оплату по счёту");
      afterChange(); openInvoice({patient_id: p.id, id: r.invoice_id}); }
    catch (e) { $("#msErr", box).textContent = errText(e); }
  };
}
async function openMembershipTypes() {
  const types = await api.membership_types(true);
  const edit = canAny("refs", "accounting");
  const box = modal(`<div class="m-h"><h3>Абонементы</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Абонемент — несколько услуг на срок за одну цену (например, профгигиена дважды в год). Услуги по абонементу в счёте стоят 0 ₽, остаток виден в карточке пациента.</p>
      ${types.length ? `<table class="tbl compact"><thead><tr><th>Название</th><th>Услуги</th><th class="num">Цена</th><th>Срок</th><th></th></tr></thead><tbody>${types.map(t => `<tr class="${t.active ? "" : "muted"}">
        <td><b>${esc(t.name)}</b>${t.active ? "" : ' <span class="pill">не продаётся</span>'}</td><td>${t.items.map(i => `${esc(i.title)} × ${i.qty}`).join("<br>")}</td><td class="num">${money(t.price)}</td><td>${t.months} мес.</td>
        <td class="row-acts">${edit ? `<button class="linkbtn" data-mte="${esc(t.id)}">изменить</button>${t.active ? `<button class="linkbtn" data-mtd="${esc(t.id)}">убрать из продажи</button>` : ""}` : ""}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty"><b>Абонементов пока нет</b></div>`}</div>
    <div class="m-f"><span class="muted"></span>${edit ? `<button class="btn ghost" id="mtNew">Новый абонемент</button>` : ""}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  const nb = $("#mtNew", box); if (nb) nb.onclick = () => editMembershipType({});
  $$("[data-mte]", box).forEach(b => b.onclick = () => editMembershipType(types.find(t => t.id === b.dataset.mte)));
  $$("[data-mtd]", box).forEach(b => b.onclick = async () => { if (await ask("Убрать абонемент из продажи?", {ok: "Убрать", text: "Проданные абонементы продолжат действовать."})) { await api.membership_type_delete(b.dataset.mtd); openMembershipTypes(); } });
}
function editMembershipType(t) {
  const items = (t.items || []).map(x => ({...x}));
  const box = modal(`<div class="m-h"><h3>${t.id ? "Абонемент" : "Новый абонемент"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Название<input class="input" id="mtN" value="${esc(t.name || "")}" placeholder="Профгигиена 2 раза в год" autofocus></label>
      <div class="grid2"><label class="fl">Цена, ₽<input class="input" id="mtP" type="number" min="1" value="${t.price || ""}"></label>
        <label class="fl">Действует, месяцев<input class="input" id="mtM" type="number" min="1" max="60" value="${t.months || 12}"></label></div>
      <h4 class="sub-h">Услуги</h4><div id="mtItems"></div>
      <div class="pat-pick mt-pick"><input class="input" id="mtQ" placeholder="Добавить услугу из прайса: начните вводить название" autocomplete="off"><div class="pp-list" id="mtR"></div></div>
      <label class="fl">Для пациента (необязательно)<input class="input" id="mtNote" value="${esc(t.note || "")}"></label><div class="auth-err" id="mtErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="mtOk">Сохранить</button></div>`);
  const draw = () => {
    $("#mtItems", box).innerHTML = items.length ? items.map((x, i) => `<div class="mt-row"><span>${esc(x.title)}</span><input class="input num" type="number" min="1" max="100" data-i="${i}" value="${x.qty}"><span class="muted">раз</span><button class="linkbtn" data-d="${i}">×</button></div>`).join("")
      : `<div class="muted">Добавьте услуги ниже</div>`;
    $$("#mtItems input", box).forEach(x => x.oninput = () => items[+x.dataset.i].qty = +x.value);
    $$("#mtItems [data-d]", box).forEach(b => b.onclick = () => { items.splice(+b.dataset.d, 1); draw(); });
  };
  let tm; $("#mtQ", box).oninput = e => { clearTimeout(tm); tm = setTimeout(async () => {
    const rows = e.target.value.trim() ? (await api.services(e.target.value)).slice(0, 8) : [];
    $("#mtR", box).innerHTML = rows.map(s => `<div class="pp-row" data-id="${esc(s.id)}"><span><b>${esc(s.title)}</b><small>${money(s.price)}</small></span></div>`).join("");
    $$("#mtR .pp-row", box).forEach(r => r.onclick = () => { const s = rows.find(x => x.id === r.dataset.id); items.push({service_id: s.id, title: s.title, qty: 1}); e.target.value = ""; $("#mtR", box).innerHTML = ""; draw(); });
  }, 150); };
  $("#mtOk", box).onclick = async () => {
    try { await api.membership_type_save({id: t.id, name: $("#mtN", box).value, price: $("#mtP", box).value, months: $("#mtM", box).value, note: $("#mtNote", box).value, items, active: true});
      toast("Абонемент сохранён"); openMembershipTypes(); }
    catch (e) { $("#mtErr", box).textContent = errText(e); }
  };
  draw();
}

/* ============================================================== cash shifts */
async function finCashPanel(c) {
  const el = $("#cashShift"); if (!el) return;
  const r = await api.cash_shift().catch(() => null); if (!r) { el.innerHTML = ""; return; }
  const sh = r.shift, act = can("payments");
  if (!sh) {
    el.innerHTML = `<div class="sh-card off"><div><b>Кассовая смена не открыта</b><span class="muted">${r.last_closed ? `Прошлая закрыта ${fmtDT(r.last_closed)}, в кассе осталось ${money(r.last_left)}` : "Откройте смену в начале дня: программа посчитает, сколько наличных должно быть в кассе"}</span></div>
      <span class="grow"></span>${act ? `<button class="btn small" id="shOpen">Открыть смену</button>` : ""}<button class="btn ghost small" id="shHist">Смены</button></div>`;
  } else {
    el.innerHTML = `<div class="sh-card"><div><b>Смена открыта ${fmtDT(sh.opened_at)}${sh.opened_by ? " · " + esc(sh.opened_by) : ""}</b>
        <span>В кассе по расчёту: <b class="sh-exp">${money(sh.expected_cash)}</b></span></div><span class="grow"></span>
        ${act ? `<button class="btn ghost small" id="shIn">Внести</button><button class="btn ghost small" id="shOut">Изъять</button><button class="btn small" id="shClose">Закрыть смену</button>` : ""}<button class="btn ghost small" id="shHist">Смены</button></div>
      <div class="sh-chips"><span>На начало <b>${money(sh.open_cash)}</b></span><span>Наличные <b>+${money(sh.cash_in)}</b></span>${sh.refunds_cash ? `<span>Возвраты <b>−${money(sh.refunds_cash)}</b></span>` : ""}
        ${sh.cert_cash ? `<span>Сертификаты <b>+${money(sh.cert_cash)}</b></span>` : ""}${sh.moves_in ? `<span>Внесено <b>+${money(sh.moves_in)}</b></span>` : ""}${sh.moves_out ? `<span>Изъято <b>−${money(sh.moves_out)}</b></span>` : ""}
        <span class="sep">Карта <b>${money(sh.card)}</b></span><span>СБП <b>${money(sh.sbp)}</b></span></div>`;
  }
  if (r.last_warning) el.innerHTML += `<div class="warn-line">Прошлая смена (закрыта ${fmtDT(r.last_closed)}): ${esc(r.last_warning)}</div>`;  // М5
  // В10: more than one open shift (opened on two computers without the network): close the extra ones one by one
  if (r.extra && r.extra.length) el.innerHTML = `<div class="warn-line bad">${esc(r.warning)} ${r.extra.map(x => `Смена от ${fmtDT(x.opened_at)}${x.opened_by ? " · " + esc(x.opened_by) : ""}: по расчёту ${money(x.expected_cash)}${act ? ` <button class="linkbtn" data-shx="${esc(x.id)}">закрыть</button>` : ""}`).join("; ")}</div>` + el.innerHTML;
  $$("[data-shx]", el).forEach(b => b.onclick = () => closeShift(r.extra.find(x => x.id === b.dataset.shx)));
  const on = (id, fn) => { const b = $(id, el); if (b) b.onclick = fn; };
  on("#shOpen", async () => { const v = await askInput("Открыть смену", [{label: "Наличных в кассе сейчас, ₽", type: "number", value: String(r.last_left || 0)}], {ok: "Открыть"});
    if (!v) return; try { await api.cash_shift_open({open_cash: v[0]}); toast("Смена открыта"); loadCash(); } catch (e) { toast(errText(e), true); } });
  on("#shIn", () => cashMove("in", r, sh));
  on("#shOut", () => cashMove("out", r, sh));
  on("#shClose", () => closeShift(sh));
  on("#shHist", openShifts);
}
function cashMove(kind, r, sh) {
  const reasons = kind === "in" ? r.in_reasons : r.out_reasons;
  const box = modal(`<div class="m-h"><h3>${kind === "in" ? "Внести деньги в кассу" : "Изъять деньги из кассы"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${kind === "out" ? `<p class="hint">В кассе по расчёту ${money(sh.expected_cash)}.</p>` : ""}
      <div class="grid2"><label class="fl">Сумма, ₽<input class="input" id="cmA" type="number" min="1" step="0.01" autofocus></label>
        <label class="fl">Зачем<select class="input" id="cmR">${finOpts(reasons, reasons[0])}</select></label></div>
      <label class="fl">Комментарий<input class="input" id="cmC" placeholder="${kind === "in" ? "например, размен из банка" : "например, сдали в банк, купили воду"}"></label>
      ${kind === "out" ? `<div id="cmExp" hidden><label class="switch-row"><input type="checkbox" id="cmE" checked><span class="sw"></span>Записать в расходы клиники</label>
        <label class="fl">Статья расхода<select class="input" id="cmCat">${finOpts(["Прочее", "Материалы и закупки", "Ремонт и обслуживание", "Связь и интернет", "Реклама"], "Прочее")}</select></label></div>` : ""}
      <div class="auth-err" id="cmErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="cmOk">${kind === "in" ? "Внести" : "Изъять"}</button></div>`);
  const ex = $("#cmExp", box);
  if (ex) { const t = () => ex.hidden = $("#cmR", box).value !== "Расход из кассы"; $("#cmR", box).onchange = t; t(); }
  const rid = reqId(), ok = $("#cmOk", box);
  ok.onclick = () => busy(ok, async () => {
    const isExp = ex && !ex.hidden && $("#cmE", box).checked;
    try { await api.cash_move({kind, amount: $("#cmA", box).value, reason: $("#cmR", box).value, comment: $("#cmC", box).value, expense: isExp,
        category: isExp ? $("#cmCat", box).value : "", request_id: rid});
      closeModal(); toast(kind === "in" ? "Деньги внесены" : "Деньги изъяты"); loadCash(); }
    catch (e) { $("#cmErr", box).textContent = errText(e); }
  });
}
function closeShift(sh) {
  const box = modal(`<div class="m-h"><h3>Закрыть смену</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Пересчитайте наличные в кассе. Итог по карте возьмите из отчёта терминала («сверка итогов»), по СБП — из выписки или приложения банка.</p>
      <table class="tbl compact sh-close"><thead><tr><th></th><th class="num">По программе</th><th>Фактически</th><th class="num">Разница</th></tr></thead><tbody>
        <tr><td>Наличные в кассе</td><td class="num">${money(sh.expected_cash)}</td><td><input class="input sm" id="scC" type="number" step="0.01" min="0" autofocus></td><td class="num" id="sdC"></td></tr>
        <tr><td>Карта (терминал)</td><td class="num">${money(sh.card)}</td><td><input class="input sm" id="scK" type="number" step="0.01" min="0" placeholder="необязательно"></td><td class="num" id="sdK"></td></tr>
        <tr><td>СБП</td><td class="num">${money(sh.sbp)}</td><td><input class="input sm" id="scS" type="number" step="0.01" min="0" placeholder="необязательно"></td><td class="num" id="sdS"></td></tr></tbody></table>
      <label class="fl">Примечание<input class="input" id="scN" placeholder="например, недостача 100 ₽ — сдача без чека"></label><div class="auth-err" id="scErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="scOk">Закрыть смену</button></div>`);
  const diff = (inp, exp, out) => { const v = $(inp, box).value; const d = v === "" ? null : Math.round((+v - exp) * 100) / 100;
    $(out, box).innerHTML = d === null ? "" : Math.abs(d) < 0.009 ? '<span class="ok-t">совпадает</span>' : `<span class="bad-t">${d > 0 ? "излишек " : "недостача "}${money(Math.abs(d))}</span>`; };
  $("#scC", box).oninput = () => diff("#scC", sh.expected_cash, "#sdC");
  $("#scK", box).oninput = () => diff("#scK", sh.card, "#sdK");
  $("#scS", box).oninput = () => diff("#scS", sh.sbp, "#sdS");
  const ok = $("#scOk", box);
  ok.onclick = () => busy(ok, async () => {
    try { const r = await api.cash_shift_close({id: sh.id, counted_cash: $("#scC", box).value, card_terminal: $("#scK", box).value, sbp_bank: $("#scS", box).value, note: $("#scN", box).value});
      closeModal(); toast(Math.abs(r.diff_cash) < 0.009 ? "Смена закрыта, наличные сходятся" : `Смена закрыта: ${r.diff_cash > 0 ? "излишек" : "недостача"} ${money(Math.abs(r.diff_cash))}`, Math.abs(r.diff_cash) >= 0.009);
      loadCash(); if (await ask("Распечатать отчёт смены?", {icon: "edit", ok: "Печать", cancel: "Не нужно"})) printShift(r.id); }
    catch (e) { $("#scErr", box).textContent = errText(e); }
  });
}
async function openShifts() {
  const rows = await api.cash_shifts();
  const dcls = v => v == null ? "" : Math.abs(v) < 0.009 ? "ok-t" : "bad-t";
  const box = modal(`<div class="m-h"><h3>Кассовые смены</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${rows.length ? `<div class="tbl-scroll"><table class="tbl compact"><thead><tr><th>Открыта</th><th>Закрыта</th><th class="num">Наличные по расчёту</th><th class="num">Пересчитано</th><th class="num">Разница</th><th class="num">Карта: разница</th><th></th></tr></thead><tbody>${
      rows.map(s => `<tr><td class="nowrap">${fmtDT(s.opened_at)}<small class="muted" style="display:block">${esc(s.opened_by || "")}</small></td><td class="nowrap">${s.closed_at ? fmtDT(s.closed_at) + `<small class="muted" style="display:block">${esc(s.closed_by || "")}</small>` : '<span class="pill st-come">открыта</span>'}</td>
        <td class="num">${money(s.expected_cash)}</td><td class="num">${s.counted_cash == null ? "—" : money(s.counted_cash)}</td><td class="num ${dcls(s.diff_cash)}">${s.diff_cash == null ? "—" : money(s.diff_cash)}</td>
        <td class="num ${dcls(s.diff_card)}">${s.diff_card == null ? "—" : money(s.diff_card)}</td><td class="row-acts"><button class="linkbtn" data-shp="${esc(s.id)}">отчёт</button></td></tr>${s.late_warning ? `<tr><td colspan="7"><div class="warn-line">${esc(s.late_warning)}</div></td></tr>` : ""}`).join("")}</tbody></table></div>`
      : `<div class="empty"><b>Смен пока не было</b></div>`}</div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  $$("[data-shp]", box).forEach(b => b.onclick = () => printShift(b.dataset.shp));
}
async function printShift(sid) {
  const s = await api.cash_shift_info(sid), cl = (await ref()).clinic || {};
  const line = (t, v) => `<tr><td>${t}</td><td style="text-align:right">${v}</td></tr>`;
  printDoc(`<div style="font-family:Arial,sans-serif;font-size:11pt"><div>${esc(cl.name || "")}</div><h2>Отчёт кассовой смены</h2>
    <p>Открыта ${fmtDT(s.opened_at)} (${esc(s.opened_by || "—")})${s.closed_at ? `, закрыта ${fmtDT(s.closed_at)} (${esc(s.closed_by || "—")})` : ", не закрыта"}</p>
    <table style="border-collapse:collapse;min-width:60%" border="1" cellpadding="5">
      ${line("Наличные на начало", money(s.open_cash))}${line("Наличные оплаты", "+" + money(s.cash_in))}${line("Возвраты наличными", "−" + money(s.refunds_cash))}
      ${line("Сертификаты за наличные", "+" + money(s.cert_cash))}${line("Внесено", "+" + money(s.moves_in))}${line("Изъято", "−" + money(s.moves_out))}
      ${line("<b>Наличные по расчёту</b>", "<b>" + money(s.expected_cash) + "</b>")}${s.counted_cash != null ? line("Пересчитано", money(s.counted_cash)) + line("Разница", money(s.diff_cash)) : ""}
      ${line("Карта по программе", money(s.card_expected ?? s.card))}${s.card_terminal != null ? line("Карта по терминалу", money(s.card_terminal)) : ""}
      ${line("СБП по программе", money(s.sbp_expected ?? s.sbp))}${s.sbp_bank != null ? line("СБП по банку", money(s.sbp_bank)) : ""}</table>
    ${s.moves.length ? `<h3>Внесения и изъятия</h3><table style="border-collapse:collapse;width:100%" border="1" cellpadding="5"><tr><th>Время</th><th>Что</th><th>Сумма</th><th>Кто</th><th>Комментарий</th></tr>${s.moves.map(m => `<tr><td>${hm(m.at)}</td><td>${m.kind === "in" ? "Внесение" : "Изъятие"}: ${esc(m.reason)}</td><td>${money(m.amount)}</td><td>${esc(m.by || "")}</td><td>${esc(m.comment || "")}</td></tr>`).join("")}</table>` : ""}
    <h3>Оплаты за смену</h3><table style="border-collapse:collapse;width:100%" border="1" cellpadding="4"><tr><th>Время</th><th>Пациент</th><th>Способ</th><th>Сумма</th></tr>${s.payment_rows.map(p => `<tr><td>${hm(p.created_at)}</td><td>${esc(p.patient_name || "")}</td><td>${esc(payLabel(p))}</td><td>${money(p.amount)}</td></tr>`).join("")}</table>
    ${s.late_warning ? `<p><b>${esc(s.late_warning)}</b></p>` : ""}${s.note ? `<p>${esc(s.note)}</p>` : ""}<p style="margin-top:30px">Смену сдал: ____________&nbsp;&nbsp;&nbsp;&nbsp;Смену принял: ____________</p></div>`);
}

/* ============================================================== insurance (ДМС) */
async function openInsDoc(p, doc, insurers) {
  insurers = insurers || await api.insurers();
  const newIns = canAny("accounting", "refs");
  if (!insurers.length && !newIns) return toast("Страховые компании заводит директор: «Бухгалтерия» → «ДМС»", true);
  const box = modal(`<div class="m-h"><h3>${doc ? "Документ ДМС" : "Полис ДМС или гарантийное письмо"} · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Страховая компания<select class="input" id="idI">${insurers.map(s => `<option value="${esc(s.id)}" ${doc && doc.insurer_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}${newIns ? `<option value="+">+ новая страховая…</option>` : ""}</select></label>
      <div class="grid2"><label class="fl">Документ<select class="input" id="idK"><option value="policy">Полис ДМС</option><option value="letter" ${doc && doc.kind === "letter" ? "selected" : ""}>Гарантийное письмо</option></select></label>
        <label class="fl">Номер<input class="input" id="idN" value="${esc(doc ? doc.number : "")}"></label>
        <label class="fl">Дата<input class="input" id="idD" type="date" value="${esc(doc && doc.date || "")}"></label>
        <label class="fl">Действует до<input class="input" id="idV" type="date" value="${esc(doc && doc.valid_to || "")}"></label>
        <label class="fl">Лимит, ₽ (если есть)<input class="input" id="idL" type="number" min="0" value="${doc && doc.limit_sum ? doc.limit_sum : ""}"></label>
        <label class="fl">Примечание<input class="input" id="idT" value="${esc(doc && doc.note || "")}" placeholder="что покрывает письмо"></label></div><div class="auth-err" id="idErr"></div></div>
    <div class="m-f">${doc ? `<button class="btn ghost small danger" id="idDel">Удалить</button>` : ""}<span class="muted">Счёт за счёт страховой — поле «Кто платит» в счёте</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="idOk">Сохранить</button></div>`);
  $("#idI", box).onchange = async e => { if (e.target.value !== "+") return;
    const v = await askInput("Новая страховая компания", [{label: "Название"}, {label: "Договор (номер, дата)", required: false}], {ok: "Добавить"});
    if (!v) { e.target.selectedIndex = 0; return; }
    try { const s = await api.insurer_save({name: v[0], contract: v[1]}); insurers.push(s); e.target.insertAdjacentHTML("afterbegin", `<option value="${esc(s.id)}">${esc(s.name)}</option>`); e.target.value = s.id; }
    catch (er) { toast(errText(er), true); e.target.selectedIndex = 0; } };
  $("#idOk", box).onclick = async () => {
    try { await api.ins_doc_save({id: doc ? doc.id : null, patient_id: p.id, insurer_id: $("#idI", box).value, kind: $("#idK", box).value, number: $("#idN", box).value,
        date: $("#idD", box).value, valid_to: $("#idV", box).value, limit_sum: $("#idL", box).value, note: $("#idT", box).value});
      closeModal(); toast("Сохранено"); finReloadPatient(p.id); }
    catch (e) { $("#idErr", box).textContent = errText(e); }
  };
  const dl = $("#idDel", box); if (dl) dl.onclick = async () => { if (await ask("Удалить документ ДМС?", {danger: true, ok: "Удалить"})) { try { await api.ins_doc_delete(doc.id); closeModal(); finReloadPatient(p.id); } catch (e) { toast(errText(e), true); } } };
}

async function accInsurance(body) {
  const r = await api.ins_summary();
  body.innerHTML = `<div class="tab-tools rep-tools"><span class="muted">Счета, которые оплачивают страховые компании, и реестры для них</span><span class="grow"></span>
      <button class="btn ghost small" id="insNew">Добавить страховую</button><button class="btn small" id="insReg">Сформировать реестр</button></div>
    <div class="stat-row"><div class="stat ${r.total_due ? "warn" : ""}"><span>Страховые должны</span><b>${money(r.total_due)}</b></div>
      <div class="stat"><span>Страховых компаний</span><b>${r.insurers.filter(x => x.active).length}</b></div>
      <div class="stat"><span>Счетов не в реестре</span><b>${r.insurers.reduce((a, x) => a + x.free, 0)}</b></div></div>
    <div class="pbody"><div class="pb-head"><b>Страховые компании</b></div>${r.insurers.length ? `<table class="tbl compact"><thead><tr><th>Компания</th><th>Договор</th><th class="num">Выставлено</th><th class="num">Оплачено</th><th class="num">Долг</th><th class="num">Не в реестре</th><th></th></tr></thead><tbody>${
      r.insurers.map(s => `<tr class="${s.active ? "" : "muted"}"><td><b>${esc(s.name)}</b>${s.phone ? `<small class="muted" style="display:block">${esc(s.phone)}</small>` : ""}</td><td>${esc(s.contract || "")}</td><td class="num">${money(s.billed)}</td><td class="num">${money(s.paid)}</td>
        <td class="num ${s.due > 0 ? "bad-t" : ""}"><b>${money(s.due)}</b></td><td class="num">${s.free || "—"}</td><td class="row-acts"><button class="linkbtn" data-ise="${esc(s.id)}">изменить</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty sm"><span>Добавьте страховые компании, с которыми у клиники договор ДМС</span></div>`}</div>
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Реестры</b></div>${r.registries.length ? `<table class="tbl compact"><thead><tr><th>№</th><th>Страховая</th><th>Период</th><th class="num">Счетов</th><th class="num">Сумма</th><th>Статус</th></tr></thead><tbody>${
      r.registries.map(g => `<tr class="lnk-row" data-reg="${esc(g.id)}"><td><b>${esc(g.number)}</b></td><td>${esc(g.insurer_name || "")}</td><td class="nowrap">${fmtDate(g.date_from)} — ${fmtDate(g.date_to)}</td><td class="num">${g.count}</td><td class="num">${money(g.status === "paid" ? g.paid_total : g.total)}</td>
        <td><span class="pill ${g.status === "paid" ? "st-ok" : g.status === "sent" ? "st-come" : ""}">${esc(g.status_title)}</span></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty sm"><span>Реестров пока нет. Раз в месяц сформируйте реестр по каждой страховой и отправьте его в Excel.</span></div>`}</div>`;
  $("#insNew", body).onclick = () => editInsurer({});
  $$("[data-ise]", body).forEach(b => b.onclick = () => editInsurer(r.insurers.find(s => s.id === b.dataset.ise)));
  $("#insReg", body).onclick = () => makeRegistry(r.insurers.filter(s => s.active));
  $$("[data-reg]", body).forEach(tr => tr.onclick = () => openRegistry(tr.dataset.reg));
}
function editInsurer(s) {
  const box = modal(`<div class="m-h"><h3>${s.id ? "Страховая компания" : "Новая страховая компания"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Название<input class="input" id="isN" value="${esc(s.name || "")}" autofocus></label>
      <div class="grid2"><label class="fl">Договор<input class="input" id="isC" value="${esc(s.contract || "")}" placeholder="№ и дата"></label>
        <label class="fl">Телефон<input class="input" id="isP" value="${esc(s.phone || "")}"></label>
        <label class="fl">Электронная почта для реестров<input class="input" id="isE" value="${esc(s.email || "")}"></label>
        <label class="fl">Примечание<input class="input" id="isT" value="${esc(s.note || "")}"></label></div>
      ${s.id ? `<label class="switch-row"><input type="checkbox" id="isA" ${s.active !== 0 ? "checked" : ""}><span class="sw"></span>Работаем с этой компанией</label>` : ""}<div class="auth-err" id="isErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="isOk">Сохранить</button></div>`);
  $("#isOk", box).onclick = async () => {
    const a = $("#isA", box);
    try { await api.insurer_save({id: s.id, name: $("#isN", box).value, contract: $("#isC", box).value, phone: $("#isP", box).value, email: $("#isE", box).value, note: $("#isT", box).value, active: a ? a.checked : true});
      closeModal(); toast("Сохранено"); loadAccounting(); }
    catch (e) { $("#isErr", box).textContent = errText(e); }
  };
}
function makeRegistry(insurers) {
  if (!insurers.length) return toast("Сначала добавьте страховую компанию", true);
  const t = new Date(), first = iso(new Date(t.getFullYear(), t.getMonth() - 1, 1)), last = iso(new Date(t.getFullYear(), t.getMonth(), 0));
  const box = modal(`<div class="m-h"><h3>Сформировать реестр</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Страховая<select class="input" id="rgI">${insurers.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select></label>
      <div class="grid2"><label class="fl">С<input class="input" id="rgA" type="date" value="${first}"></label><label class="fl">По<input class="input" id="rgB" type="date" value="${last}"></label></div>
      <div id="rgC" class="muted"></div><div class="auth-err" id="rgErr"></div></div>
    <div class="m-f"><span class="muted">В реестр попадут неоплаченные счета страховой за период, которых нет в других реестрах</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rgOk">Сформировать</button></div>`);
  const cnt = async () => { const rows = await api.ins_candidates($("#rgI", box).value, $("#rgA", box).value, $("#rgB", box).value).catch(() => []);
    $("#rgC", box).textContent = rows.length ? `Счетов: ${rows.length} на ${money(rows.reduce((a, x) => a + x.total - x.paid, 0))}` : "За этот период счетов нет"; };
  ["#rgI", "#rgA", "#rgB"].forEach(id => $(id, box).onchange = cnt); cnt();
  $("#rgOk", box).onclick = async () => {
    try { const g = await api.registry_make({insurer_id: $("#rgI", box).value, date_from: $("#rgA", box).value, date_to: $("#rgB", box).value}); toast(`Реестр № ${g.number} сформирован`); openRegistry(g.id); loadAccounting(); }
    catch (e) { $("#rgErr", box).textContent = errText(e); }
  };
}
async function openRegistry(rid) {
  const g = await api.registry(rid), paid = g.status === "paid";
  const box = modal(`<div class="m-h"><h3>Реестр № ${esc(g.number)} · ${esc(g.insurer_name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">Период ${fmtDate(g.date_from)} — ${fmtDate(g.date_to)} · ${esc(g.status_title)}${g.sent_at ? `, отправлен ${fmtDT(g.sent_at)}` : ""}${g.paid_at ? `, оплачен ${fmtDT(g.paid_at)}` : ""}</p>
      <div class="tbl-scroll"><table class="tbl compact" id="rgT"><thead><tr>${paid ? "" : '<th title="Страховая отказала в оплате">Отказ</th>'}<th>Пациент</th><th>Документ</th><th>Дата</th><th>Услуги</th><th class="num">Сумма</th></tr></thead><tbody>${
        g.rows.map(x => `<tr>${paid ? "" : `<td><input type="checkbox" class="rg-rej" data-id="${esc(x.id)}"></td>`}<td>${esc(x.patient_name || "")}</td><td>${esc(x.doc_number || "")}</td><td class="nowrap">${fmtDate(x.created_at)}</td>
          <td>${esc(x.items.map(i => i.title).join(", ").slice(0, 120))}</td><td class="num">${money(x.total)}</td></tr>`).join("")}</tbody>
        <tfoot><tr>${paid ? "" : "<td></td>"}<td colspan="4">Итого</td><td class="num"><b>${money(g.rows.reduce((a, x) => a + x.total, 0))}</b></td></tr></tfoot></table></div>
      ${paid ? "" : `<p class="hint">Когда деньги от страховой придут, нажмите «Оплачен». Счета, по которым страховая отказала, отметьте галочкой — их оплатит пациент сам.</p>`}</div>
    <div class="m-f">${paid ? "" : `<button class="btn ghost small danger" id="rgDel">Удалить</button>`}<span class="muted"></span><button class="btn ghost" id="rgX">Excel</button><button class="btn ghost" id="rgPr">Печать</button>
      ${g.status === "draft" ? `<button class="btn ghost" id="rgSent">Отправлен</button>` : ""}${paid ? "" : `<button class="btn" id="rgPay">Оплачен</button>`}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  $("#rgX", box).onclick = async () => { try { const r = await api.registry_xlsx(rid); await saveDataUrl(r.name, r.url); } catch (e) { toast(errText(e), true); } };
  $("#rgPr", box).onclick = () => printTable(`Реестр № ${g.number} · ${g.insurer_name || ""}`, "#rgT");
  const on = (id, fn) => { const b = $(id, box); if (b) b.onclick = fn; };
  on("#rgSent", async () => { await api.registry_status(rid, "sent"); toast("Отмечено: реестр отправлен"); openRegistry(rid); loadAccounting(); });
  on("#rgPay", async () => {
    const rejected = $$(".rg-rej", box).filter(c => c.checked).map(c => c.dataset.id);
    if (!await ask("Страховая оплатила реестр?", {ok: "Оплачен", text: rejected.length ? `Отказано по ${rejected.length} счетам — их оплатят пациенты.` : "По каждому счёту запишется оплата «Страховая»."})) return;
    try { const r = await api.registry_pay(rid, {rejected}); toast(`Реестр оплачен: ${money(r.paid_total)}`); closeModal(); loadAccounting(); } catch (e) { toast(errText(e), true); }
  });
  on("#rgDel", async () => { if (await ask("Удалить реестр?", {danger: true, ok: "Удалить", text: "Счета вернутся в список для нового реестра."})) { await api.registry_delete(rid); closeModal(); loadAccounting(); } });
}

/* ============================================================== debts report */
async function finDebts(body, r) {
  const remind = can("marketing");
  const tbl = $("#debtTbl", body);
  if (tbl) {
    [...tbl.tBodies[0].rows].forEach((tr, i) => {
      const x = r.debts[i]; if (!x) return;
      if (x.not_due > 0.009) tr.cells[6].insertAdjacentHTML("beforeend", `<small class="muted" style="display:block">из них по графику позже ${money(x.not_due)}</small>`);
      if (remind && x.phone) tr.cells[0].insertAdjacentHTML("beforeend", `<button class="linkbtn rmd-btn no-print" data-rmd="${i}" title="Открыть WhatsApp с готовым текстом о долге">напомнить</button>`);
    });
    $$("[data-rmd]", tbl).forEach(b => b.onclick = async e => { e.stopPropagation(); const x = r.debts[+b.dataset.rmd]; const s = await crmSettings();
      if (await crmWhatsApp({patient_id: x.patient_id, name: x.name, phone: x.phone}, s.debt_text, {"сумма": money(x.total - (x.not_due || 0))}, "debts", "Напоминание о долге")) toast("Открыт WhatsApp с готовым текстом"); });
  }
  const anchor = body.querySelectorAll(".pbody")[1];
  if (r.overdue && r.overdue.length) {
    const el = document.createElement("div"); el.className = "pbody"; el.style.marginTop = "12px";
    el.innerHTML = `<div class="pb-head"><b>Просроченные платежи по рассрочке</b></div><table class="tbl compact"><thead><tr><th>Пациент</th><th>Телефон</th><th>Срок был</th><th class="num">Просрочено</th><th class="num">Осталось по счёту</th>${remind ? '<th class="row-acts"></th>' : ""}</tr></thead><tbody>${
      r.overdue.map((x, i) => `<tr><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name)}</b></td><td>${esc(x.phone || "—")}</td><td class="nowrap">${fmtDate(x.due)} <small class="muted">(${x.days} дн.)</small></td>
        <td class="num bad-t"><b>${money(x.amount)}</b></td><td class="num">${money(x.left)}</td>${remind ? `<td class="row-acts"><button class="linkbtn" data-rmp="${i}">Напомнить</button></td>` : ""}</tr>`).join("")}</tbody></table>`;
    body.insertBefore(el, anchor || null);
    $$("[data-p]", el).forEach(td => td.onclick = () => openPatient(td.dataset.p, "reports"));
    $$("[data-rmp]", el).forEach(b => b.onclick = async () => { const x = r.overdue[+b.dataset.rmp]; const s = await crmSettings();
      if (await crmWhatsApp({patient_id: x.patient_id, name: x.name, phone: x.phone}, s.pay_text, {"сумма": money(x.amount), "срок": fmtDate(x.due)}, "debts", "Напоминание о платеже по рассрочке")) toast("Открыт WhatsApp с готовым текстом"); });
  }
  const ins = r.insurance && r.insurance.insurers.filter(s => s.due > 0.009);
  if (ins && ins.length) {
    const el = document.createElement("div"); el.className = "pbody"; el.style.marginTop = "12px";
    el.innerHTML = `<div class="pb-head"><b>Долги страховых компаний (ДМС)</b>${can("accounting") ? `<button class="linkbtn" id="insGo">Реестры →</button>` : ""}</div><table class="tbl compact"><tbody>${
      ins.map(s => `<tr><td>${esc(s.name)}</td><td class="num"><b>${money(s.due)}</b></td><td class="muted">${s.free ? `счетов не в реестре: ${s.free}` : ""}</td></tr>`).join("")}</tbody></table>`;
    body.appendChild(el);
    const g = $("#insGo", el); if (g) g.onclick = () => { S.accTab = "insurance"; show("accounting"); };
  }
}
