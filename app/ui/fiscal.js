"use strict";
/* Fiscal receipts: shift, X/Z reports, receipts of the day, returns, register settings. */
const RCPT_ST = {done: ["Пробит", "st-ok"], test: ["Тестовый", "st-come"], error: ["Ошибка", "st-cancel"], pending: ["Печатается…", ""],
  refunded: ["Возвращён", ""], not_required: ["Не нужен", ""]};

function receiptPill(p) {
  if (!S.settings.fiscal_enabled) return "";
  const r = p.receipt;
  if (!r) return /Безнал/.test(p.method || "") ? `<span class="pill">чек не нужен</span>` : (canAny("fiscal", "payments") ? `<button class="linkbtn" data-print-pay="${esc(p.id)}">пробить чек</button>` : `<span class="pill st-cancel">без чека</span>`);
  const [t, c] = RCPT_ST[r.status] || [r.status, ""];
  return `<button class="pill ${c} pill-btn-lite" data-rcpt="${esc(r.id)}" title="Открыть чек">чек: ${t.toLowerCase()}</button>`;
}

function receiptToast(r, okText) {
  if (!r) return toast(okText);
  if (r.status === "error") return toast(`${okText}, но чек не пробит: ${r.error}. Повторите в разделе «Касса».`, true);
  if (r.status === "not_required") return toast(`${okText}. ${r.message}`);
  toast(`${okText}. ${r.status === "test" ? "Тестовый чек" : "Чек пробит"}${r.fd ? ", ФД № " + r.fd : ""}`);
}

async function renderFiscal(day) {
  const el = $("#fiscalPanel"); if (!el) return;
  if (!S.settings.fiscal_enabled) {
    el.innerHTML = `<div class="warn-line">Касса не подключена: оплаты в программе не являются кассовыми чеками. ${can("settings") ? "Подключите кассу в Настройках → «Касса (ККТ)»." : "Подключить кассу может директор в Настройках."}</div>`;
    return;
  }
  el.innerHTML = `<div class="fiscal-bar"><div class="scan"><i></i>Связываемся с кассой…</div></div>`;
  const [st, rows] = await Promise.all([api.fiscal_status(), api.fiscal_receipts(day)]);
  const sh = st.shift || {};
  const shiftTxt = st.error ? `<span class="bad-t">${esc(st.error)}</span>`
    : sh.state === "opened" ? `Смена № ${esc(sh.number ?? "")} открыта${sh.opened_at ? " с " + fmtDT(sh.opened_at) : ""}`
    : sh.state === "expired" ? `<span class="bad-t">Смена № ${esc(sh.number ?? "")} открыта больше 24 часов — закройте её (Z-отчёт)</span>`
    : "Смена закрыта — откроется сама с первым чеком";
  const f = can("fiscal");
  const paid = new Set(rows.filter(r => r.kind === "sell" && ["done", "test"].includes(r.status)).map(r => r.payment_id));
  const noReceipt = ((S.cash || {}).payments || []).filter(p => !paid.has(p.id) && !/Безнал/.test(p.method) && !rows.some(r => r.payment_id === p.id && r.status === "error"));
  el.innerHTML = `<div class="fiscal-bar ${st.test ? "test" : ""}">
      <div class="fb-main"><b>${esc(st.driver_title)}</b>${st.test ? '<span class="pill st-come">чеки не фискальные</span>' : ""}<span class="muted">${shiftTxt}</span></div>
      ${f ? `<div class="fb-acts">${sh.state === "opened" || sh.state === "expired" ? "" : `<button class="btn ghost small" id="fOpen">Открыть смену</button>`}
        <button class="btn ghost small" id="fX">X-отчёт</button>${sh.state === "opened" || sh.state === "expired" ? `<button class="btn small" id="fZ">Закрыть смену (Z-отчёт)</button>` : ""}</div>` : ""}</div>
    ${st.failed ? `<div class="warn-line bad">Не пробито чеков: ${st.failed}. Проверьте кассу (бумага, связь, смена) и нажмите «Повторить».</div>` : ""}
    ${noReceipt.length ? `<div class="warn-line">Оплаты за день без чека: ${noReceipt.length}. ${noReceipt.map(p => `<button class="linkbtn" data-print-pay="${esc(p.id)}">${hm(p.created_at)} · ${esc(p.patient_name || "")} · ${money(p.amount)}</button>`).join(" ")}</div>` : ""}
    <div class="pbody" style="margin-top:12px"><div class="pb-head"><b>Чеки за день</b></div>
      ${rows.length ? `<table class="tbl"><thead><tr><th>Время</th><th>Чек</th><th>Пациент</th><th>Расчёт</th><th class="num">Сумма</th><th>Статус</th><th>ФД / ФП</th><th>Кассир</th><th></th></tr></thead><tbody>${
        rows.map(r => { const [t, c] = r.refunded ? RCPT_ST.refunded : (RCPT_ST[r.status] || [r.status, ""]);
          return `<tr data-r="${esc(r.id)}"><td>${hm(r.created_at)}</td><td><b>${r.kind === "refund" ? "Возврат прихода" : "Приход"}</b></td><td>${esc(r.patient_name || "")}</td>
          <td class="muted">${esc(r.payments.map(x => x.type === "cash" ? "наличные" : "безналичные").join(", "))}</td><td class="num"><b>${money(r.total)}</b></td>
          <td><span class="pill ${c}">${t}</span>${r.status === "error" ? `<small class="bad-t" style="display:block;max-width:260px">${esc(r.error || "")}</small>` : ""}</td>
          <td class="muted">${r.fd ? `${esc(r.fd)} / ${esc(r.fp)}` : "—"}</td><td class="muted">${esc(r.user_name || "")}</td>
          <td class="acts">${r.status === "error" && canAny("fiscal", "payments") ? `<button class="btn ghost small" data-retry="${esc(r.id)}">Повторить</button>` : ""}</td></tr>`; }).join("")}</tbody></table>`
        : `<div class="empty"><b>Чеков за этот день нет</b></div>`}</div>`;
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  const act = (fn, ok) => async () => { try { await fn(); toast(ok); } catch (e) { toast(errText(e), true); } renderFiscal(day); };
  on("#fOpen", act(() => api.fiscal_open_shift(), "Смена открыта"));
  on("#fX", act(() => api.fiscal_x_report(), "X-отчёт напечатан"));
  on("#fZ", async () => { if (await ask("Закрыть смену?", {icon: "print", ok: "Закрыть смену", text: "Касса напечатает Z-отчёт. Новая смена откроется сама с первым чеком."})) act(() => api.fiscal_close_shift(), "Смена закрыта, Z-отчёт напечатан")(); });
  $$("#fiscalPanel [data-retry]").forEach(b => b.onclick = async e => { e.stopPropagation(); try { receiptToast(await api.fiscal_retry(b.dataset.retry), "Повтор"); } catch (x) { toast(errText(x), true); } renderFiscal(day); });
  $$("#fiscalPanel [data-print-pay]").forEach(b => b.onclick = async () => { try { receiptToast(await api.fiscal_for_payment(b.dataset.printPay, ""), "Готово"); } catch (x) { toast(errText(x), true); } renderFiscal(day); });
  $$("#fiscalPanel tr[data-r]").forEach(tr => tr.onclick = () => openReceipt(tr.dataset.r, () => renderFiscal(day)));
}

async function openReceipt(id, after) {
  const r = await api.fiscal_receipt(id);
  const st = await api.fiscal_status().catch(() => ({method_titles: {}}));
  const mt = st.method_titles || {};
  const [t, c] = r.refunded ? RCPT_ST.refunded : (RCPT_ST[r.status] || [r.status, ""]);
  const box = modal(`<div class="m-h"><h3>${r.kind === "refund" ? "Чек возврата прихода" : "Кассовый чек (приход)"} · ${money(r.total)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="receipt" id="rcptBody">
      ${r.status === "test" ? `<div class="rc-test">ТЕСТОВЫЙ ЧЕК — НЕ ФИСКАЛЬНЫЙ ДОКУМЕНТ</div>` : ""}
      <div class="rc-h">${esc(((REF || {}).clinic || {}).name || (S.status.brand || {}).name || "")}</div>
      <div class="rc-row"><span>${r.kind === "refund" ? "ВОЗВРАТ ПРИХОДА" : "ПРИХОД"}</span><span>${fmtDT(r.fiscal_at || r.created_at)}</span></div>
      ${r.items.map(it => `<div class="rc-item"><div>${esc(it.name)}</div><div class="rc-row"><span>${it.quantity} × ${money(it.price)}</span><b>${money(it.amount)}</b></div>
        <div class="rc-row muted"><span>${esc(mt[it.paymentMethod] || it.paymentMethod)}</span><span>${it.tax === "none" ? "Без НДС" : esc(it.tax)}</span></div></div>`).join("")}
      <div class="rc-row rc-total"><span>ИТОГ</span><b>${money(r.total)}</b></div>
      ${r.payments.map(p => `<div class="rc-row"><span>${p.type === "cash" ? "Наличными" : "Безналичными"}</span><span>${money(p.sum)}</span></div>`).join("")}
      <div class="rc-row"><span>Кассир</span><span>${esc(r.user_name || "")}</span></div>
      ${r.contact ? `<div class="rc-row"><span>Эл. адрес покупателя</span><span>${esc(r.contact)}</span></div>` : ""}
      ${r.fd ? `<div class="rc-f">ФН ${esc(r.fn)} · ФД № ${esc(r.fd)} · ФП ${esc(r.fp)}${r.shift ? " · смена " + esc(r.shift) : ""}${r.number ? " · чек " + esc(r.number) : ""}</div>` : ""}
    </div>
    <div><span class="pill ${c}">${t}</span> ${r.status === "error" ? `<span class="bad-t">${esc(r.error || "")}</span>` : ""}</div></div>
    <div class="m-f"><span class="muted">${r.patient_name ? esc(r.patient_name) : ""}</span>
      ${r.kind === "sell" && ["done", "test"].includes(r.status) && !r.refunded && can("fiscal") ? `<button class="btn ghost danger" id="rcRefund">Чек возврата</button>` : ""}
      ${r.status === "error" && canAny("fiscal", "payments") ? `<button class="btn ghost" id="rcRetry">Повторить</button>` : ""}
      <button class="btn ghost" id="rcPrint">Печать копии</button><button class="btn" data-close>Закрыть</button></div>`);
  const on = (s, f) => { const el = $(s, box); if (el) el.onclick = f; };
  on("#rcPrint", () => { $("#printArea").innerHTML = `<div class="receipt print">${$("#rcptBody").innerHTML}<div class="rc-f">Копия, не является кассовым чеком</div></div>`; window.print(); });
  on("#rcRetry", async () => { try { receiptToast(await api.fiscal_retry(r.id), "Повтор"); closeModal(); if (after) after(); } catch (e) { toast(errText(e), true); } });
  on("#rcRefund", async () => {
    if (!(await ask(`Пробить чек возврата на ${money(r.total)}?`, {danger: true, ok: "Пробить возврат", text: "Деньги пациенту нужно вернуть тем же способом, каким он платил."}))) return;
    try { receiptToast(await api.fiscal_refund(r.id), "Возврат оформлен"); closeModal(); afterChange(); if (after) after(); } catch (e) { toast(errText(e), true); }
  });
}

/* ------------------------------------------------------- settings panel */
async function loadFiscalSettings() {
  const box = $("#fiscalSettings"); if (!box) return;
  const r = await api.fiscal_settings(); const s = r.settings;
  const opt = (m, v) => Object.entries(m).map(([k, t]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(t)}</option>`).join("");
  box.innerHTML = `<label class="switch-row"><input type="checkbox" id="fsOn" ${s.enabled ? "checked" : ""}><span class="sw"></span>Пробивать чеки через кассу</label>
    <div class="form">
      <label>Касса<select class="input" id="fsDrv">${opt(r.drivers, s.driver)}</select></label>
      <label class="fs-atol">Адрес веб-сервера драйвера АТОЛ<input class="input" id="fsUrl" value="${esc(s.atol_url)}"></label>
      <label class="fs-shtrih">Пароль кассира Штрих-М<input class="input" id="fsPwd" type="number" value="${esc(s.shtrih_password)}"></label>
      <label>Система налогообложения<select class="input" id="fsTax">${opt(r.taxation, s.taxation)}</select></label>
      <label>НДС по услугам<select class="input" id="fsVat">${opt(r.taxes, s.tax)}</select></label>
      <label>ИНН кассира (необязательно)<input class="input" id="fsInn" value="${esc(s.cashier_inn)}"></label>
    </div>
    <label class="switch-row"><input type="checkbox" id="fsAuto" ${s.auto ? "checked" : ""}><span class="sw"></span>Пробивать чек сразу при приёме оплаты</label>
    <div class="hint fs-hint"></div>
    <div class="row"><button class="btn" id="fsSave">Сохранить</button><button class="btn ghost" id="fsCheck">Проверить связь с кассой</button><span class="msg" id="fsMsg"></span></div>`;
  const hints = {emulator: "Тестовый режим: всё работает как с кассой, но чеки не уходят в налоговую и помечены «тестовый». Удобно, чтобы научить администраторов.",
    atol: "Установите драйвер ДТО 10 АТОЛ на компьютер, к которому подключена касса, и включите в нём веб-сервер (порт 16732). Если касса подключена не к серверу, укажите адрес того компьютера, например http://192.168.1.15:16732.",
    shtrih: "Установите «Драйвер ККТ» Штрих-М на компьютер-сервер и настройте в нём подключение к кассе (USB, COM или сеть). Программа работает через этот драйвер."};
  const vis = () => { const d = $("#fsDrv").value; $(".fs-atol").hidden = d !== "atol"; $(".fs-shtrih").hidden = d !== "shtrih"; $(".fs-hint").textContent = hints[d]; };
  $("#fsDrv").onchange = vis; vis();
  const msgF = (t, ok) => { $("#fsMsg").textContent = t; $("#fsMsg").className = "msg " + (ok ? "ok" : "bad"); };
  const save = async () => {
      await api.fiscal_save_settings({enabled: $("#fsOn").checked, driver: $("#fsDrv").value, atol_url: $("#fsUrl").value.trim(), shtrih_password: +$("#fsPwd").value || 30,
        taxation: $("#fsTax").value, tax: $("#fsVat").value, cashier_inn: $("#fsInn").value.trim(), auto: $("#fsAuto").checked});
      Object.assign(S.settings, await api.ui_settings());
  };
  $("#fsSave").onclick = async () => {
    try { await save(); msgF("Сохранено", true); } catch (e) { msgF(errText(e), false); }
  };
  $("#fsCheck").onclick = async () => { msgF("Проверяем…", true); try { await save(); msgF(await api.fiscal_check(), true); } catch (e) { msgF(errText(e), false); } };
}
