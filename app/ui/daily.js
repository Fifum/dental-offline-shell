"use strict";
/* 2.14: expenses of the day in «Касса» (an administrator sees only today's own entries, «Бухгалтерия» sees all)
   and the day report by e-mail: preview, «Отправить сейчас», settings of the mailbox. */
const DX = {data: null};

async function dayExpensesPanel(host) {
  if (!host || !canAny("expenses_day", "accounting")) return;
  let r;
  try { r = await api.day_expenses(); } catch (e) { host.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  DX.data = r;
  const st = r.report;
  const stTxt = st ? (st.status === "sent" ? `<span class="pill st-ok" title="${esc(st.sent_to || "")}">отчёт отправлен ${esc((st.sent_at || "").slice(11, 16))}</span>`
    : `<span class="pill st-cancel" title="${esc(st.error || "")}">отчёт не ушёл — повторю сам</span>`) : "";
  host.innerHTML = `<div class="pbody dx"><div class="pb-head"><b>Расходы за сегодня</b>
      <span class="muted">${r.all ? "все сотрудники" : "ваши записи — завтра список начнётся заново"}</span><span class="grow"></span>${stTxt}
      <button class="btn ghost small" id="dxRep">Отчёт за день</button></div>
    <form class="dx-add" id="dxForm">
      <input class="input" id="dxSum" inputmode="decimal" placeholder="Сумма, ₽" autocomplete="off">
      <select class="input" id="dxCat">${r.categories.map(c => `<option>${esc(c)}</option>`).join("")}</select>
      <input class="input" id="dxCom" placeholder="На что (вода, курьер, такси…)" maxlength="300">
      <select class="input" id="dxMet">${r.methods.map(m => `<option>${esc(m)}</option>`).join("")}</select>
      <label class="dx-doc"><input type="checkbox" id="dxDoc" checked>есть чек или документ</label>
      <button class="btn" type="submit">Записать</button></form>
    ${r.rows.length ? `<table class="tbl compact dx-t"><thead><tr><th>Время</th><th>Статья</th><th>На что</th><th>Как оплачено</th><th>Документ</th>${r.all ? "<th>Кто внёс</th>" : ""}<th class="num">Сумма</th><th></th></tr></thead><tbody>${
      r.rows.map(x => `<tr><td>${esc(x.created_at.slice(11, 16))}</td><td>${esc(x.category)}</td><td>${esc(x.comment || "")}</td><td class="muted">${esc(x.method)}</td>
        <td>${x.doc ? '<span class="muted">есть</span>' : '<span class="pill dx-nodoc">без документа</span>'}</td>${r.all ? `<td class="muted">${esc(x.user_name || "")}</td>` : ""}
        <td class="num"><b>${money(x.amount)}</b></td><td class="row-acts"><button class="linkbtn" data-dxdel="${esc(x.id)}" title="Удалить">×</button></td></tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="${r.all ? 6 : 5}">Итого${r.nodoc ? ` · без документов ${money(r.nodoc)}` : ""}</td><td class="num">${money(r.total)}</td><td></td></tr></tfoot></table>`
      : `<div class="muted dx-empty">Сегодня расходов пока нет. Наличные «из кассы» сразу уменьшают кассу в открытой смене.</div>`}</div>`;
  $("#dxForm", host).onsubmit = async e => {
    e.preventDefault();
    try {
      await api.day_expense_save({amount: $("#dxSum", host).value, category: $("#dxCat", host).value, comment: $("#dxCom", host).value,
        method: $("#dxMet", host).value, doc: $("#dxDoc", host).checked});
      toast("Расход записан");
      if (S.view === "cash") loadCash(); else dayExpensesPanel(host);
    } catch (err) { toast(errText(err), true); }
  };
  $$("[data-dxdel]", host).forEach(b => b.onclick = async () => {
    const x = r.rows.find(y => y.id === b.dataset.dxdel);
    if (!(await ask("Удалить расход?", {danger: true, ok: "Удалить", text: `${x.category}: ${money(x.amount)}${x.comment ? " — " + x.comment : ""}`}))) return;
    try { await api.day_expense_delete(x.id); toast("Удалено"); if (S.view === "cash") loadCash(); else dayExpensesPanel(host); } catch (err) { toast(errText(err), true); }
  });
  $("#dxRep", host).onclick = () => openDayReport();
}

async function openDayReport(day) {
  let r;
  try { r = await api.day_report(day || null); } catch (e) { return toast(errText(e), true); }
  const st = r.state;
  const box = modal(`<div class="m-h"><h3>Отчёт за ${esc(fmtDate(r.day))}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><pre class="dx-text">${esc(r.text)}</pre>
      ${st ? `<div class="${st.status === "sent" ? "ok-line" : "warn-line"}">${st.status === "sent" ? `Отправлен ${esc(fmtDT(st.sent_at))} на ${esc(st.sent_to)}` : `Не отправлен: ${esc(st.error || "")}`}</div>` : ""}</div>
    <div class="m-f"><span class="muted">Отчёт уходит на почту владельца с файлом Excel</span><button class="btn ghost" data-close>Закрыть</button>
      <button class="btn ghost" id="drPrint">Печать</button><button class="btn" id="drSend">${st && st.status === "sent" ? "Отправить ещё раз" : "Отправить на почту"}</button></div>`, {wide: true});
  $("#drPrint", box).onclick = () => { $("#printArea").innerHTML = `<pre style="font:13px/1.5 inherit;white-space:pre-wrap">${esc(r.text)}</pre>`; window.print(); };
  $("#drSend", box).onclick = async () => {
    const b = $("#drSend", box); b.disabled = true; b.textContent = "Отправляю…";
    try { const s = await api.day_report_send(r.day, true); toast(`Отчёт отправлен на ${s.sent_to}`); closeModal(); if (S.view === "cash") loadCash(); }
    catch (e) { toast(errText(e), true); b.disabled = false; b.textContent = "Отправить на почту"; }
  };
}

/* ------------------------------------------------ settings: the day report by e-mail */
async function loadDaySettings() {
  const box = $("#dayRepBody"); if (!box) return;
  let s;
  try { s = await api.day_report_settings(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const PRESET = {"smtp.yandex.ru": "Яндекс", "smtp.mail.ru": "Mail.ru", "smtp.gmail.com": "Gmail"};
  box.innerHTML = `<label class="switch-row"><input type="checkbox" id="drOn" ${s.enabled ? "checked" : ""}><span class="sw"></span>Отправлять отчёт за день на почту</label>
    <div class="form">
      <label class="wide">Куда отправлять (можно несколько через запятую)<input class="input" id="drTo" value="${esc(s.to)}" placeholder="owner@yandex.ru"></label>
      <label>Почта-отправитель<select class="input" id="drProv">${Object.entries(PRESET).map(([h, t]) => `<option value="${h}" ${s.host === h ? "selected" : ""}>${t}</option>`).join("")}<option value="" ${PRESET[s.host] ? "" : "selected"}>Другая</option></select></label>
      <label>Сервер SMTP<input class="input" id="drHost" value="${esc(s.host)}"></label>
      <label>Порт<input class="input" id="drPort" value="${esc(s.port)}" inputmode="numeric"></label>
      <label>Ящик-отправитель (логин)<input class="input" id="drLogin" value="${esc(s.login)}" placeholder="clinic.reports@yandex.ru" autocomplete="off"></label>
      <label>Пароль приложения<input class="input" id="drPass" type="password" placeholder="${s.has_pass ? "сохранён — оставьте пустым" : ""}" autocomplete="new-password"></label>
      <label>Время отправки<input class="input" id="drTime" type="time" value="${esc(s.time)}"></label>
    </div>
    <label class="switch-row"><input type="checkbox" id="drClose" ${s.on_close ? "checked" : ""}><span class="sw"></span>Отправлять сразу при закрытии кассовой смены</label>
    <p class="hint">Отчёт: поступления по способам оплаты, все расходы дня (с документами и без), кассовая смена; во вложении — файл Excel. Без интернета отчёт подождёт и уйдёт, когда связь появится. Отправляет компьютер, на котором включена эта настройка (обычно ресепшен).<br>
      Пароль приложения: Яндекс — id.yandex.ru → «Безопасность» → «Пароли приложений» → «Почта»; Mail.ru — «Безопасность» → «Пароли для внешних приложений». Обычный пароль ящика почтовые сервисы не принимают. Пароль хранится зашифрованным на этом компьютере.</p>
    <div class="row"><button class="btn" id="drSave">Сохранить</button><button class="btn ghost" id="drTest">Сохранить и отправить отчёт за сегодня</button><span class="msg" id="drMsg"></span></div>`;
  const msgD = (t, ok) => { $("#drMsg").textContent = t; $("#drMsg").className = "msg " + (ok ? "ok" : "bad"); };
  $("#drProv").onchange = e => { if (e.target.value) { $("#drHost").value = e.target.value; $("#drPort").value = 465; } };
  const save = () => api.day_report_settings_save({enabled: $("#drOn").checked, to: $("#drTo").value, host: $("#drHost").value, port: $("#drPort").value,
    login: $("#drLogin").value, password: $("#drPass").value, time: $("#drTime").value, on_close: $("#drClose").checked, security: "ssl"});
  $("#drSave").onclick = async () => { try { await save(); $("#drPass").value = ""; msgD("Сохранено", true); } catch (e) { msgD(errText(e), false); } };
  $("#drTest").onclick = async () => {
    msgD("Отправляю…", true);
    try { await save(); $("#drPass").value = ""; const r = await api.day_report_send(null, true); msgD(`Отчёт отправлен на ${r.sent_to}`, true); }
    catch (e) { msgD(errText(e), false); }
  };
}
