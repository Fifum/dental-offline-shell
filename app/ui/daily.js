"use strict";
/* 2.14: expenses of the day in «Касса» (an administrator sees only today's own entries, «Бухгалтерия» sees all)
   and the day report by e-mail and Telegram (2.14.1): preview, «Отправить сейчас», settings of the bot and the mailbox. */
const DX = {data: null};

async function dayExpensesPanel(host) {
  if (!host || !canAny("expenses_day", "accounting")) return;
  let r;
  try { r = await api.day_expenses(); } catch (e) { host.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  DX.data = r;
  const st = r.report;
  const stTxt = st ? (st.status === "sent" ? `<span class="pill st-ok" title="${esc(st.where || "")}">отчёт отправлен ${esc((st.sent_at || "").slice(11, 16))}</span>`
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
      ${st ? `<div class="${st.status === "sent" ? "ok-line" : "warn-line"}">${st.status === "sent" ? `Отправлен ${esc(fmtDT(st.sent_at))} — ${esc(st.where || "")}` : `Не отправлен: ${esc(st.error || "")}`}</div>` : ""}</div>
    <div class="m-f"><span class="muted">Отчёт уходит владельцу в Telegram или на почту, с файлом Excel</span><button class="btn ghost" data-close>Закрыть</button>
      <button class="btn ghost" id="drPrint">Печать</button><button class="btn" id="drSend">${st && st.status === "sent" ? "Отправить ещё раз" : "Отправить владельцу"}</button></div>`, {wide: true});
  $("#drPrint", box).onclick = () => { $("#printArea").innerHTML = `<pre style="font:13px/1.5 inherit;white-space:pre-wrap">${esc(r.text)}</pre>`; window.print(); };
  $("#drSend", box).onclick = async () => {
    const b = $("#drSend", box); b.disabled = true; b.textContent = "Отправляю…";
    try { const s = await api.day_report_send(r.day, true); toast(`Отчёт отправлен: ${s.where}`); closeModal(); if (S.view === "cash") loadCash(); }
    catch (e) { toast(errText(e), true); b.disabled = false; b.textContent = "Отправить владельцу"; }
  };
}

/* ------------------------------------------------ settings: the day report in Telegram and by e-mail */
async function loadDaySettings() {
  const box = $("#dayRepBody"); if (!box) return;
  let s;
  try { s = await api.day_report_settings(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const PRESET = {"smtp.yandex.ru": "Яндекс", "smtp.mail.ru": "Mail.ru", "smtp.gmail.com": "Gmail"};
  let chats = (s.tg_chats || []).map(c => ({...c, on: true})), bot = s.tg_bot || "";
  const drawChats = () => {
    $("#tgChats", box).innerHTML = chats.length ? chats.map((c, i) => `<label class="dr-chat"><input type="checkbox" data-ci="${i}" ${c.on ? "checked" : ""}>${esc(c.name || c.id)}</label>`).join("")
      : `<span class="muted">Пока никто не выбран.</span>`;
    $$("[data-ci]", box).forEach(x => x.onchange = () => { chats[+x.dataset.ci].on = x.checked; });
  };
  box.innerHTML = `<div class="dr-ch">
      <label class="switch-row"><input type="checkbox" id="tgOn" ${s.tg_on ? "checked" : ""}><span class="sw"></span><b>Telegram</b> — отправлять отчёт владельцу в Telegram</label>
      <ol class="dr-steps">
        <li>В Telegram откройте <b>@BotFather</b>, отправьте <code>/newbot</code>, придумайте имя бота (например «Отчёты клиники») — BotFather пришлёт токен.</li>
        <li>Вставьте токен сюда и нажмите «Проверить бота».
          <div class="row dr-row"><input class="input" id="tgToken" type="password" autocomplete="new-password" placeholder="${s.has_tg_token ? "сохранён — оставьте пустым" : "1234567890:AA…"}">
            <button class="btn ghost small" id="tgCheck">Проверить бота</button><span class="muted" id="tgBot">${bot ? `бот <b>@${esc(bot)}</b>` : ""}</span></div></li>
        <li>Владелец открывает бота${bot ? ` — <a href="https://t.me/${esc(bot)}" id="tgLink">t.me/${esc(bot)}</a> —` : ""} и нажимает «Старт» (или пишет боту любое сообщение).</li>
        <li><button class="btn ghost small" id="tgFind">Найти, кто написал боту</button> и отметьте, кому отправлять отчёт:
          <div class="dr-chats" id="tgChats"></div></li>
      </ol></div>
    <div class="dr-ch">
      <label class="switch-row"><input type="checkbox" id="drOn" ${s.enabled ? "checked" : ""}><span class="sw"></span><b>Почта</b> — отправлять отчёт на электронную почту</label>
      <div class="form">
        <label class="wide">Куда отправлять (можно несколько через запятую)<input class="input" id="drTo" value="${esc(s.to)}" placeholder="owner@yandex.ru"></label>
        <label>Почта-отправитель<select class="input" id="drProv">${Object.entries(PRESET).map(([h, t]) => `<option value="${h}" ${s.host === h ? "selected" : ""}>${t}</option>`).join("")}<option value="" ${PRESET[s.host] ? "" : "selected"}>Другая</option></select></label>
        <label>Сервер SMTP<input class="input" id="drHost" value="${esc(s.host)}"></label>
        <label>Порт<input class="input" id="drPort" value="${esc(s.port)}" inputmode="numeric"></label>
        <label>Ящик-отправитель (логин)<input class="input" id="drLogin" value="${esc(s.login)}" placeholder="clinic.reports@yandex.ru" autocomplete="off"></label>
        <label>Пароль приложения<input class="input" id="drPass" type="password" placeholder="${s.has_pass ? "сохранён — оставьте пустым" : ""}" autocomplete="new-password"></label>
      </div>
      <p class="hint">Пароль приложения: Яндекс — id.yandex.ru → «Безопасность» → «Пароли приложений» → «Почта»; Mail.ru — «Безопасность» → «Пароли для внешних приложений». Обычный пароль ящика почта не принимает.</p></div>
    <div class="form"><label>Время отправки<input class="input" id="drTime" type="time" value="${esc(s.time)}"></label></div>
    <label class="switch-row"><input type="checkbox" id="drClose" ${s.on_close ? "checked" : ""}><span class="sw"></span>Отправлять сразу при закрытии кассовой смены</label>
    <label class="switch-row"><input type="checkbox" id="drWeek" ${s.week_on !== false ? "checked" : ""}><span class="sw"></span>Отчёт за неделю — по понедельникам: деньги, расходы, приёмы, табель${typeof openPeriodReport === "function" && can("accounting") ? ` <button class="linkbtn" type="button" id="drWeekSee">посмотреть</button>` : ""}</label>
    <label class="switch-row"><input type="checkbox" id="drMonth" ${s.month_on !== false ? "checked" : ""}><span class="sw"></span>Отчёт за месяц — 1-го числа: прибыль и убытки, движение денег, зарплата и мотивация, табель${typeof openPeriodReport === "function" && can("accounting") ? ` <button class="linkbtn" type="button" id="drMonthSee">посмотреть</button>` : ""}</label>
    <p class="hint">Отчёт: поступления по способам оплаты, все расходы дня (с документами и без), кассовая смена и файл Excel. Без интернета отчёт подождёт и уйдёт, когда связь появится. Отправляет компьютер, на котором включена эта настройка (обычно ресепшен). Токен бота и пароль почты хранятся зашифрованными на этом компьютере.</p>
    <div class="row"><button class="btn" id="drSave">Сохранить</button><button class="btn ghost" id="drTest">Сохранить и отправить отчёт за сегодня</button><span class="msg" id="drMsg"></span></div>`;
  drawChats();
  const lk = $("#tgLink", box);  // the program's window must not leave for t.me: open it in the browser
  if (lk) lk.onclick = e => { e.preventDefault(); const pw = window.pywebview && window.pywebview.api; if (pw && pw.open_url) pw.open_url(lk.href); else window.open(lk.href, "_blank"); };
  const msgD = (t, ok) => { $("#drMsg").textContent = t; $("#drMsg").className = "msg " + (ok ? "ok" : "bad"); };
  $("#drProv").onchange = e => { if (e.target.value) { $("#drHost").value = e.target.value; $("#drPort").value = 465; } };
  const tok = () => $("#tgToken").value.trim();
  $("#tgCheck").onclick = async () => {
    try { const b = await api.day_report_tg_check(tok()); bot = b.username; $("#tgBot").innerHTML = `бот <b>@${esc(bot)}</b> — работает`;
      toast(`Бот @${bot} на связи. Теперь владелец открывает t.me/${bot} и нажимает «Старт».`); }
    catch (e) { $("#tgBot").innerHTML = `<span class="bad-t">${esc(errText(e))}</span>`; }
  };
  $("#tgFind").onclick = async () => {
    try {
      const found = await api.day_report_tg_chats(tok());
      for (const f of found) if (!chats.some(c => c.id === f.id)) chats.push({...f, on: true});
      drawChats();
      toast(found.length ? `Нашлось: ${found.length}. Отметьте, кому отправлять, и нажмите «Сохранить».` : "Боту ещё никто не писал — откройте бота в Telegram и нажмите «Старт», затем повторите.", !found.length);
    } catch (e) { toast(errText(e), true); }
  };
  const save = async () => {
    const r = await api.day_report_settings_save({enabled: $("#drOn").checked, to: $("#drTo").value, host: $("#drHost").value, port: $("#drPort").value,
      login: $("#drLogin").value, password: $("#drPass").value, time: $("#drTime").value, on_close: $("#drClose").checked, security: "ssl",
      week_on: $("#drWeek").checked, month_on: $("#drMonth").checked,
      tg_on: $("#tgOn").checked, tg_token: tok(), tg_bot: bot, tg_chats: chats.filter(c => c.on).map(c => ({id: c.id, name: c.name}))});
    $("#drPass").value = ""; $("#tgToken").value = "";
    return r;
  };
  [["#drWeekSee", "week"], ["#drMonthSee", "month"]].forEach(([id, k]) => { const b = $(id, box); if (b) b.onclick = e => { e.preventDefault(); e.stopPropagation(); openPeriodReport(k); }; });
  $("#drSave").onclick = async () => { try { await save(); msgD("Сохранено", true); } catch (e) { msgD(errText(e), false); } };
  $("#drTest").onclick = async () => {
    msgD("Отправляю…", true);
    try { await save(); const r = await api.day_report_send(null, true); msgD(`Отчёт отправлен: ${r.where}`, true); }
    catch (e) { msgD(errText(e), false); }
  };
}
