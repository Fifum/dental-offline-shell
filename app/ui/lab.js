"use strict";
/* Dental lab orders: the «Лаборатория» view, the patient card tab and the order form with a printable заказ-наряд. */
S.labFilter = "open";
let LABO = null;
const LAB_ST_CLS = {new: "", sent: "st-come", fitting: "st-come", redo: "st-cancel", ready: "st-ok", delivered: "st-done", cancelled: "st-cancel"};
const labOpts = async (force) => (LABO && !force ? LABO : (LABO = await api.lab_options()));

function labTable(rows, withPatient, payable) {
  if (!rows.length) return `<div class="empty"><b>Заказ-нарядов нет</b><span>${can("lab") ? "Создайте заказ-наряд, когда отправляете работу в лабораторию." : ""}</span></div>`;
  return `<div class="tbl-scroll"><table class="tbl" id="labT"><thead><tr>${payable ? '<th class="no-print"></th>' : ""}<th>№</th>${withPatient ? "<th>Пациент</th>" : ""}<th>Работа</th><th>Зубы</th><th>Цвет</th><th>Лаборатория</th><th>Врач</th><th>Примерка</th><th>Срок</th><th>Статус</th><th class="num">Стоимость</th></tr></thead><tbody>
    ${rows.map(o => `<tr class="lnk-row ${o.overdue ? "neg" : ""}" data-o="${esc(o.id)}">${payable ? `<td class="no-print">${!o.paid && o.price > 0 && o.status !== "cancelled" ? `<input type="checkbox" class="lab-ch" data-id="${esc(o.id)}" data-lab="${esc(o.lab_id || "")}">` : ""}</td>` : ""}
      <td>${o.number}</td>${withPatient ? `<td><b>${esc(o.patient_name || "")}</b></td>` : ""}<td>${esc(o.work)}</td><td>${esc(o.teeth || "")}</td><td>${esc(o.shade || "")}</td>
      <td>${esc(o.lab_name || "—")}</td><td>${esc(o.doctor_name || "")}</td><td class="nowrap">${o.fitting_date ? esc(fmtDate(o.fitting_date)) : ""}${o.fitting_today ? ' <span class="pill st-come">сегодня</span>' : ""}</td>
      <td class="nowrap">${o.due_date ? esc(fmtDate(o.due_date)) : "—"}${o.overdue ? ' <span class="pill st-cancel">просрочен</span>' : ""}</td>
      <td><span class="pill ${LAB_ST_CLS[o.status] || ""}">${esc(o.status_text)}</span></td>
      <td class="num">${o.price ? money(o.price) : "—"}${o.paid ? '<small class="muted" style="display:block">оплачено</small>' : ""}</td></tr>`).join("")}</tbody></table></div>`;
}

async function loadLab() {
  const body = $("#labBody"); if (!body) return;
  const O = await labOpts();
  const [rows, sm] = await Promise.all([api.lab_orders(S.labFilter === "overdue" ? "open" : S.labFilter, S.labLab || null), api.lab_summary()]);
  const shown = S.labFilter === "overdue" ? rows.filter(o => o.overdue) : rows;
  const payable = can("accounting");
  body.innerHTML = `<div class="tab-tools rep-tools">
      <div class="seg sm" id="labF">${[["open", "В работе"], ["overdue", `Просрочены${sm.overdue ? " " + sm.overdue : ""}`], ["unpaid", "Не оплачены лаборатории"], ["all", "Все"]].map(([k, t]) => `<button data-k="${k}" class="${S.labFilter === k ? "on" : ""}">${t}</button>`).join("")}</div>
      <select class="input sm-sel" id="labL"><option value="">Все лаборатории</option>${O.labs.map(l => `<option value="${esc(l.id)}" ${l.id === S.labLab ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>
      <span class="grow"></span>${can("lab") ? `<button class="btn ghost small" id="labDir">Лаборатории</button><button class="btn" id="labNew">Новый заказ-наряд</button>` : ""}
      <button class="icon-btn" title="Скачать в Excel" data-xls="#labT" data-xls-name="Заказ-наряды"><svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg></button></div>
    <div class="stat-row"><div class="stat"><span>В работе</span><b>${sm.open}</b></div><div class="stat ${sm.overdue ? "warn" : ""}"><span>Просрочено</span><b>${sm.overdue}</b></div>
      <div class="stat"><span>Примерок сегодня</span><b>${sm.fitting_today}</b></div><div class="stat"><span>Долг лабораториям</span><b>${money(sm.unpaid)}</b></div></div>
    <div class="pbody">${labTable(shown, true, payable)}</div>
    ${payable ? `<div class="row lab-pay" id="labPayRow" hidden><span id="labPaySum"></span><button class="btn" id="labPay">Оплатить лаборатории отмеченные</button></div>` : ""}`;
  $$("#labF button", body).forEach(b => b.onclick = () => { S.labFilter = b.dataset.k; loadLab(); });
  $("#labL", body).onchange = e => { S.labLab = e.target.value; loadLab(); };
  $$("tr[data-o]", body).forEach(r => r.onclick = e => { if (e.target.closest(".lab-ch")) return; openLabOrder({id: r.dataset.o}, loadLab); });
  const nb = $("#labNew", body); if (nb) nb.onclick = () => openLabOrder({}, loadLab);
  const dir = $("#labDir", body); if (dir) dir.onclick = openLabsDir;
  const upd = () => {
    const ch = $$(".lab-ch:checked", body), sum = ch.reduce((s, c) => s + (shown.find(o => o.id === c.dataset.id) || {}).price || 0, 0);
    $("#labPayRow", body).hidden = !ch.length; $("#labPaySum", body).textContent = `Отмечено: ${ch.length} на ${money(sum)}`;
  };
  $$(".lab-ch", body).forEach(c => c.onchange = upd);
  const pay = $("#labPay", body);
  if (pay) pay.onclick = async () => {
    const ids = $$(".lab-ch:checked", body).map(c => c.dataset.id);
    const v = await askInput("Оплата лаборатории", [{label: "Способ оплаты", value: "Безналичный перевод"}], {ok: "Оплатить", text: "Сумма будет записана расходом «Зуботехническая лаборатория» в бухгалтерии."});
    if (!v) return;
    try { const r = await api.lab_pay(ids, v[0]); toast(`Оплачено ${r.count} на ${money(r.total)} — расход записан`); loadLab(); } catch (e) { toast(errText(e), true); }
  };
}

async function loadPatientLab(p) {
  const el = $("#labPBody"); if (!el) return;
  await labOpts();
  const rows = await api.lab_orders("all", null, p.id);
  el.innerHTML = `<div class="tab-tools">${can("lab") ? `<button class="btn ghost small" id="plNew">Новый заказ-наряд</button>` : ""}<span class="muted">Работы зуботехнической лаборатории для пациента</span></div>${labTable(rows, false, false)}`;
  $$("tr[data-o]", el).forEach(r => r.onclick = () => openLabOrder({id: r.dataset.o}, () => loadPatientLab(p)));
  const nb = $("#plNew", el); if (nb) nb.onclick = () => openLabOrder({patient_id: p.id, patient_name: p.name}, async () => { P = await api.patient(p.id); renderPatient("lab"); });
}

async function openLabOrder(o, after) {
  const O = await labOpts(), R = await ref();
  const x = o.id ? await api.lab_order(o.id) : {status: "new", patient_id: o.patient_id, patient_name: o.patient_name, doctor_id: o.doctor_id || "", plan_id: o.plan_id || "", sent_date: iso(new Date())};
  const edit = can("lab");
  let pid = x.patient_id || null;
  const plans = pid ? (await api.patient(pid)).invoices.filter(i => i.kind === "plan") : [];
  const dis = edit ? "" : "disabled";
  const box = modal(`<div class="m-h"><h3>${x.id ? `Заказ-наряд № ${x.number}` : "Новый заказ-наряд"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      ${pid ? `<div class="lab-pat"><b>${esc(x.patient_name || "")}</b></div>` : `<div class="pat-pick"><input class="input" id="loQ" placeholder="Пациент: ФИО или телефон" autocomplete="off"><div class="pp-list" id="loRes"></div></div>`}
      <div class="grid3">
        <label class="fl">Работа<input class="input" id="loW" list="loWl" value="${esc(x.work || "")}" ${dis}><datalist id="loWl">${O.works.map(w => `<option value="${esc(w)}">`).join("")}</datalist></label>
        <label class="fl">Зубы<input class="input" id="loT" value="${esc(x.teeth || "")}" placeholder="например 36 или 34–36" ${dis}></label>
        <label class="fl">Цвет (по шкале VITA)<input class="input" id="loS" list="loSl" value="${esc(x.shade || "")}" ${dis}><datalist id="loSl">${O.shades.map(s => `<option value="${esc(s)}">`).join("")}</datalist></label>
      </div>
      <div class="grid3">
        <label class="fl">Лаборатория<select class="input" id="loL" ${dis}><option value="">—</option>${O.labs.map(l => `<option value="${esc(l.id)}" ${l.id === x.lab_id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>
        <label class="fl">Врач<select class="input" id="loD" ${dis}><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === x.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        <label class="fl">Материал<input class="input" id="loM" value="${esc(x.material || "")}" ${dis}></label>
      </div>
      <div class="grid3">
        <label class="fl">Отправлен<input class="input" type="date" id="loSd" value="${esc(x.sent_date || "")}" ${dis}></label>
        <label class="fl">Примерка<input class="input" type="date" id="loFd" value="${esc(x.fitting_date || "")}" ${dis}></label>
        <label class="fl">Срок готовности<input class="input" type="date" id="loDd" value="${esc(x.due_date || "")}" ${dis}></label>
      </div>
      <div class="grid3">
        <label class="fl">Статус<select class="input" id="loSt" ${dis}>${Object.entries(O.statuses).map(([k, t]) => `<option value="${k}" ${k === x.status ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
        <label class="fl">Стоимость в лаборатории, ₽<input class="input" id="loP" inputmode="decimal" value="${esc(x.price || "")}" ${dis}></label>
        <label class="fl">План лечения<select class="input" id="loPl" ${dis}><option value="">—</option>${plans.map(pl => `<option value="${esc(pl.id)}" ${pl.id === x.plan_id ? "selected" : ""}>${esc(pl.title || "План от " + fmtDate(pl.created_at))}</option>`).join("")}</select></label>
      </div>
      <label class="fl">Комментарий для техника<input class="input" id="loN" value="${esc(x.note || "")}" ${dis}></label>
      ${x.paid ? `<div class="ok-t">Лаборатории оплачено ${esc(fmtDT(x.paid_at))}</div>` : ""}
    </div>
    <div class="m-f">${x.id ? `<button class="btn ghost small" id="loPrint">Печать заказ-наряда</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Закрыть</button>${edit ? `<button class="btn" id="loSave">Сохранить</button>` : ""}</div>`, {wide: true});
  const q = $("#loQ", box);
  if (q) { let t; q.oninput = () => { pid = null; clearTimeout(t); t = setTimeout(async () => {
    const rows = q.value.trim() ? await api.search(q.value) : [];
    $("#loRes", box).innerHTML = rows.slice(0, 6).map(p => `<div class="pp-row" data-id="${esc(p.id)}" data-n="${esc(p.name)}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}</small></span></div>`).join("");
    $$("#loRes .pp-row", box).forEach(r => r.onclick = () => { pid = r.dataset.id; q.value = r.dataset.n; $("#loRes", box).innerHTML = ""; });
  }, 150); }; q.focus(); }
  const sv = $("#loSave", box);
  if (sv) sv.onclick = async () => {
    if (!pid) return toast("Выберите пациента", true);
    const v = id => $(id, box).value.trim();
    try {
      const r = await api.lab_save({id: x.id || null, patient_id: pid, work: v("#loW"), teeth: v("#loT"), shade: v("#loS"), lab_id: v("#loL"), doctor_id: v("#loD"),
        material: v("#loM"), sent_date: v("#loSd"), fitting_date: v("#loFd"), due_date: v("#loDd"), status: v("#loSt"), price: v("#loP"), plan_id: v("#loPl"), note: v("#loN")});
      closeModal(); toast(`Заказ-наряд № ${r.number} сохранён`); if (after) after(r);
    } catch (e) { toast(errText(e), true); }
  };
  const pr = $("#loPrint", box);
  if (pr) pr.onclick = async () => {
    const c = (await ref()).clinic || {};
    const row = (k, v) => `<tr><td style="width:34%">${esc(k)}</td><td><b>${esc(v || "—")}</b></td></tr>`;
    printDoc(`<h2 style="text-align:center">Заказ-наряд № ${x.number}</h2><p style="text-align:center">${esc(c.name || "")}${c.phone ? ", тел. " + esc(c.phone) : ""}</p>
      <table border="1" cellspacing="0" cellpadding="6" style="width:100%;border-collapse:collapse">${row("Лаборатория", x.lab_name)}${row("Пациент", x.patient_name)}${row("Врач", x.doctor_name)}
      ${row("Работа", x.work)}${row("Зубы", x.teeth)}${row("Цвет", x.shade)}${row("Материал", x.material)}${row("Отправлено", x.sent_date ? fmtDate(x.sent_date) : "")}
      ${row("Примерка", x.fitting_date ? fmtDate(x.fitting_date) : "")}${row("Срок готовности", x.due_date ? fmtDate(x.due_date) : "")}${row("Комментарий", x.note)}</table>
      <p style="margin-top:28px">Врач ______________ &nbsp;&nbsp;&nbsp; Принял(а) в лаборатории ______________ &nbsp; «___» __________ 20__ г.</p>`);
  };
}

async function openLabsDir() {
  const O = await labOpts(true);
  const box = modal(`<div class="m-h"><h3>Лаборатории</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${O.labs.length ? `<table class="tbl compact"><thead><tr><th>Название</th><th>Телефон</th><th>Контакт</th><th></th></tr></thead><tbody>
      ${O.labs.map((l, i) => `<tr><td><b>${esc(l.name)}</b></td><td>${esc(l.phone || "")}</td><td>${esc(l.contact || "")}</td><td class="row-acts"><button class="linkbtn" data-e="${i}">изменить</button></td></tr>`).join("")}</tbody></table>` : `<p class="muted">Лабораторий пока нет.</p>`}</div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="ldAdd">Добавить лабораторию</button></div>`);
  const edit = async l => {
    const v = await askInput(l ? "Лаборатория" : "Новая лаборатория", [{label: "Название", value: l ? l.name : ""}, {label: "Телефон", value: l ? l.phone : "", required: false}, {label: "Контактное лицо", value: l ? l.contact : "", required: false}]);
    if (!v) return openLabsDir();
    try { await api.labs_save({id: l ? l.id : null, name: v[0], phone: v[1], contact: v[2]}); LABO = null; toast("Сохранено"); } catch (e) { toast(errText(e), true); }
    openLabsDir(); if (S.view === "lab") loadLab();
  };
  $("#ldAdd", box).onclick = () => edit(null);
  $$("[data-e]", box).forEach(b => b.onclick = () => edit(O.labs[+b.dataset.e]));
}

/** Treatment plan editor: lab works ordered for this plan, with their cost. */
async function planLabOrders(box, inv, pat) {
  if (!canAny("lab", "billing", "accounting")) return;
  const host = $(".inv-right", box); if (!host) return;
  const el = document.createElement("div"); el.className = "pays plan-lab"; host.appendChild(el);
  const draw = async () => {
    const rows = (await api.lab_orders("all", null, pat.id)).filter(o => o.plan_id === inv.id);
    const cost = rows.filter(o => o.status !== "cancelled").reduce((s, o) => s + (o.price || 0), 0);
    el.innerHTML = `<div class="pb-head"><b>Лаборатория по плану</b><span class="muted">${rows.length ? `себестоимость ${money(cost)}` : ""}</span></div>
      ${rows.map(o => `<div class="pay lnk" data-o="${esc(o.id)}"><span>№ ${o.number}</span><span>${esc(o.work)}${o.teeth ? " · " + esc(o.teeth) : ""}</span><span class="pill ${LAB_ST_CLS[o.status] || ""}">${esc(o.status_text)}</span><b>${o.price ? money(o.price) : ""}</b></div>`).join("") || '<div class="muted">Работ лаборатории по этому плану нет</div>'}
      ${can("lab") ? `<div class="pay-add"><button class="btn ghost small" id="plLab" type="button">Заказ-наряд по плану</button></div>` : ""}`;
    $$("[data-o]", el).forEach(r => r.onclick = () => openLabOrder({id: r.dataset.o}, () => openInvoice({patient_id: pat.id, id: inv.id})));
    const b = $("#plLab", el); if (b) b.onclick = () => openLabOrder({patient_id: pat.id, patient_name: pat.name, plan_id: inv.id, doctor_id: inv.doctor_id}, () => openInvoice({patient_id: pat.id, id: inv.id}));
  };
  draw();
}