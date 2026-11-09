"use strict";
/* CRM: tasks for the front desk, requests (leads) on a board and their funnel, patient segments with a WhatsApp
   mailing, the after-visit survey (NPS) with links to review the clinic on the maps, and the CRM settings.
   Tabs live in the «CRM» section next to the call lists, birthdays and sources from marketing.js. */
S.mkTab = "tasks";
S.crmScope = "my";
S.crmLeadMode = "board";
S.crmRvMode = "ask";
const CRM_RES_CLS = {"Сделано": "st-done", "Записался": "st-done", "Дозвонились": "st-ok", "Не дозвонились": "", "Перезвонить позже": "st-come", "Отказ": "st-cancel"};
const XLS_ICON = '<svg viewBox="0 0 24 24"><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="m8.5 8.5 7 7M15.5 8.5l-7 7"/></svg>';
const xlsBtn = title => `<button class="icon-btn" title="Скачать в Excel" data-xls="#mkBody table.tbl" data-xls-title="${esc(title)}">${XLS_ICON}</button>`;
const crmDay = d => { if (!d) return "—"; const t = iso(new Date()); if (d === t) return "сегодня"; if (d === addDays(t, 1)) return "завтра"; if (d === addDays(t, -1)) return "вчера"; return fmtShort(d); };

async function crmClinic() { if (!S.rmTpl) S.rmTpl = await api.reminder_template(); return S.rmTpl.clinic; }
async function crmSettings(force) { if (!S.crmSet || force) S.crmSet = await api.crm_settings(); return S.crmSet; }
async function openUrl(url) { const pw = window.pywebview && window.pywebview.api; if (pw && pw.open_url) await pw.open_url(url); else window.open(url, "_blank", "noopener"); }
/** WhatsApp with the text ready; the message is marked in the call log of the patient. */
async function crmWhatsApp(x, tpl, extra = {}, list = "segment", comment = "WhatsApp") {
  const phone = rmPhone(x.phone);
  if (!phone) { toast("У пациента не указан телефон", true); return false; }
  let text = tpl;
  for (const [k, v] of Object.entries(extra)) text = text.split(`{${k}}`).join(v);
  text = rmText(text, x, await crmClinic());
  await openUrl(`https://wa.me/${phone}?text=${encodeURIComponent(text)}`);
  try { await api.log_call({patient_id: x.patient_id, list, result: "Написали", comment, no_calls: false}); } catch (e) { /* not critical */ }
  return true;
}
function patPick(box, inputSel, listSel, onPick) {
  let t;
  const q = $(inputSel, box);
  q.oninput = () => { onPick(null); clearTimeout(t); t = setTimeout(async () => {
    const rows = q.value.trim() ? await api.search(q.value) : [];
    $(listSel, box).innerHTML = rows.slice(0, 6).map(p => `<div class="pp-row" data-id="${esc(p.id)}" data-n="${esc(p.name)}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}</small></span></div>`).join("");
    $$(`${listSel} .pp-row`, box).forEach(r => r.onclick = () => { onPick({id: r.dataset.id, name: r.dataset.n}); q.value = r.dataset.n; $(listSel, box).innerHTML = ""; });
  }, 150); };
}

/* ================================================================== tasks */
async function crmTasks(body) {
  const r = await api.crm_tasks({scope: S.crmScope});
  S.crmTasksR = r;
  const c = r.counts;
  const scopes = [["my", "Мои", c.my], ["all", "Все", c.all], ["overdue", "Просрочено", c.overdue], ["done", "Выполнено", 0]];
  body.innerHTML = `<div class="tab-tools rep-tools"><div class="seg sm" id="crmScope">${scopes.map(([k, t, n]) => `<button data-s="${k}" class="${k === S.crmScope ? "on" : ""}">${t}${n ? `<span class="cnt${k === "overdue" ? " bad" : ""}">${n}</span>` : ""}</button>`).join("")}</div>
      <button class="btn small" id="crmNewTask">Новая задача</button><span class="grow"></span>
      <button class="btn ghost small" id="crmRules" title="Какие задачи программа ставит сама">Правила задач</button>${xlsBtn("Задачи")}<button class="icon-btn" id="mkPrint" title="Печать">${PRINT_ICON}</button></div>
    <div class="pbody">${taskTable(r)}</div>
    <div class="muted note-line">${S.crmScope === "my" ? "Ваши задачи и общие (без исполнителя). " : ""}Программа сама ставит задачи после услуг (например, звонок на следующий день после удаления, профгигиена через полгода), по незавершённым планам лечения и после низкой оценки визита — правила можно поменять. Задачи видны на всех компьютерах клиники.</div>`;
  $$("#crmScope button").forEach(b => b.onclick = () => { S.crmScope = b.dataset.s; loadMarketing(); });
  $("#crmNewTask").onclick = () => editTask({}, loadMarketing);
  $("#crmRules").onclick = () => openCrmSettings("rules");
  bindTasks(body, r.rows, loadMarketing);
}
function taskTable(r, compact) {
  if (!r.rows.length) return `<div class="empty${compact ? " sm" : ""}"><b>${r.scope === "done" ? "За 30 дней выполненных задач нет" : "Задач нет"}</b><span>${r.scope === "done" ? "" : "Новые появятся сами по правилам или их можно поставить вручную"}</span></div>`;
  const done = r.scope === "done";
  return `<table class="tbl crm-tasks"><thead><tr><th>${done ? "Выполнена" : "Срок"}</th><th>Задача</th><th>Пациент</th><th>${done ? "Результат" : "Исполнитель"}</th><th></th></tr></thead><tbody>${
    r.rows.map((t, i) => `<tr class="${t.overdue ? "late-row" : ""}">
      <td class="nowrap">${done ? `${fmtDT(t.done_at)}<br><small class="muted">${esc(t.done_by || "")}</small>` : `<span class="due ${t.overdue ? "late" : t.today ? "now" : ""}">${crmDay(t.due)}</span>`}</td>
      <td><b>${esc(t.title)}</b>${t.kind !== "task" ? ' <span class="pill auto-pill" title="Задачу поставила программа по правилу">авто</span>' : ""}${t.comment ? `<br><small class="muted pre">${esc(t.comment)}</small>` : ""}</td>
      <td>${t.patient_id ? `<span class="lnk" data-p="${esc(t.patient_id)}"><b>${esc(t.patient_name || "—")}</b></span><br><small class="muted nowrap">${esc(t.phone || "")}</small>${t.booked && !done ? ' <span class="pill st-ok">есть запись</span>' : ""}` : `<span class="muted">—</span>`}</td>
      <td>${done ? `<span class="pill ${CRM_RES_CLS[t.result] || ""}">${esc(t.result || "Сделано")}</span>` : esc(t.assignee_name || "Все")}</td>
      <td class="row-acts">${done ? `<button class="btn ghost small" data-reopen="${i}">Вернуть</button>` : `${t.phone ? `<button class="btn ghost small" data-twa="${i}" title="Открыть WhatsApp">WhatsApp</button>` : ""}<button class="btn small" data-done="${i}">Готово</button><button class="icon-btn sm" data-edit="${i}" title="Изменить"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg></button>`}</td></tr>`).join("")}</tbody></table>`;
}
function bindTasks(root, rows, reload) {
  $$("[data-p]", root).forEach(el => el.onclick = () => openPatient(el.dataset.p, "marketing"));
  $$("[data-done]", root).forEach(b => b.onclick = () => taskDone(rows[+b.dataset.done], reload));
  $$("[data-edit]", root).forEach(b => b.onclick = () => editTask(rows[+b.dataset.edit], reload));
  $$("[data-reopen]", root).forEach(b => b.onclick = async () => { await api.crm_task_reopen(rows[+b.dataset.reopen].id); toast("Задача снова открыта"); reload(); refreshStatus(); });
  $$("[data-twa]", root).forEach(b => b.onclick = async () => { const t = rows[+b.dataset.twa]; await crmWhatsApp({...t, name: t.patient_name}, "Здравствуйте, {имя}! ", {}, "tasks", t.title); });
}
async function editTask(t, after) {
  const R = S.crmTasksR || await api.crm_tasks({scope: "my"});
  let pick = t.patient_id ? {id: t.patient_id, name: t.patient_name} : null;
  const box = modal(`<div class="m-h"><h3>${t.id ? "Задача" : "Новая задача"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Что сделать*<input class="input" id="tkT" value="${esc(t.title || "")}" placeholder="Позвонить, напомнить, отправить…" autofocus></label>
      <label class="fl">Пациент</label><div class="pat-pick"><input class="input" id="tkQ" value="${esc(t.patient_name || "")}" placeholder="ФИО или телефон (необязательно)" autocomplete="off"><div class="pp-list" id="tkRes"></div></div>
      <div class="grid2"><label class="fl">Срок<input class="input" type="date" id="tkD" value="${esc(t.due || iso(new Date()))}"></label>
        <label class="fl">Исполнитель<select class="input" id="tkA"><option value="">Все администраторы</option>${R.staff.map(s => `<option value="${esc(s.login)}" ${s.login === t.assignee ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label></div>
      <label class="fl">Комментарий<textarea class="input" id="tkC" rows="2">${esc(t.comment || "")}</textarea></label><div class="auth-err" id="tkErr"></div></div>
    <div class="m-f">${t.id ? `<button class="btn ghost small danger" id="tkDel">${t.kind === "task" ? "Удалить" : "Скрыть"}</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="tkOk">Сохранить</button></div>`);
  patPick(box, "#tkQ", "#tkRes", p => { pick = p; });
  $("#tkOk", box).onclick = async () => {
    if ($("#tkQ", box).value.trim() && !pick) { $("#tkErr").textContent = "Выберите пациента из списка или очистите поле"; return; }
    try {
      await api.crm_task_save({id: t.id, title: $("#tkT", box).value, patient_id: pick ? pick.id : null, lead_id: t.lead_id || null,
        due: $("#tkD", box).value, assignee: $("#tkA", box).value, comment: $("#tkC", box).value});
      closeModal(); toast("Задача сохранена"); refreshStatus(); if (after) after();
    } catch (e) { $("#tkErr").textContent = errText(e); }
  };
  const del = $("#tkDel", box);
  if (del) del.onclick = async () => {
    if (!(await ask(t.kind === "task" ? "Удалить задачу?" : "Скрыть задачу?", {danger: t.kind === "task", ok: t.kind === "task" ? "Удалить" : "Скрыть",
      text: t.kind === "task" ? t.title : "Задачу поставила программа по правилу. Скрытая задача больше не появится."}))) return;
    await api.crm_task_delete(t.id); closeModal(); toast(t.kind === "task" ? "Задача удалена" : "Задача скрыта"); refreshStatus(); if (after) after();
  };
}
function taskDone(t, after) {
  let pick = "";
  const results = (S.crmTasksR && S.crmTasksR.results) || ["Сделано", "Записался", "Дозвонились", "Не дозвонились", "Перезвонить позже", "Отказ"];
  const box = modal(`<div class="m-h"><h3>${esc(t.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${t.patient_id ? `<div class="call-phone">${esc(t.patient_name || "")} · ${esc(t.phone || "телефон не указан")}</div>` : ""}${t.comment ? `<p class="muted pre">${esc(t.comment)}</p>` : ""}
      <div class="call-res">${results.map(x => `<button class="pill-btn" data-r="${esc(x)}">${esc(x)}</button>`).join("")}</div>
      <label class="fl" id="tdLater" hidden>Когда перезвонить<input class="input" type="date" id="tdD" value="${addDays(iso(new Date()), 1)}"></label>
      <label class="fl">Комментарий<input class="input" id="tdC" placeholder="Что сказал пациент"></label><div class="auth-err" id="tdErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button>${t.patient_id && can("schedule_edit") ? `<button class="btn ghost" id="tdBook">Записать на приём</button>` : ""}<button class="btn" id="tdOk">Сохранить</button></div>`);
  $$(".call-res button", box).forEach(b => b.onclick = () => { pick = b.dataset.r; $$(".call-res button", box).forEach(y => y.classList.toggle("on", y === b)); $("#tdLater").hidden = pick !== "Перезвонить позже"; $("#tdErr").textContent = ""; });
  const save = async res => { await api.crm_task_done(t.id, res, $("#tdC", box).value, $("#tdD", box).value); refreshStatus(); };
  $("#tdOk", box).onclick = async () => {
    if (!pick) { $("#tdErr").textContent = "Выберите результат"; return; }
    try { await save(pick); closeModal(); toast(pick === "Перезвонить позже" ? "Задача перенесена" : "Задача выполнена"); if (after) after(); } catch (e) { $("#tdErr").textContent = errText(e); }
  };
  const bk = $("#tdBook", box);
  if (bk) bk.onclick = () => { closeModal(); openBooking({patient_id: t.patient_id, patient_name: t.patient_name, start: `${addDays(iso(new Date()), 1)} 10:00`,
    onSaved: async () => { try { await api.crm_task_done(t.id, "Записался", $("#tdC", box) ? $("#tdC", box).value : "", null); refreshStatus(); if (after) after(); } catch (e) { /* the visit is saved anyway */ } }}); };
}

/* ================================================================== leads */
async function crmLeads(body) {
  const tools = `<div class="seg sm" id="crmLm"><button data-m="board" class="${S.crmLeadMode === "board" ? "on" : ""}">Доска</button><button data-m="funnel" class="${S.crmLeadMode === "funnel" ? "on" : ""}">Воронка</button></div>`;
  if (S.crmLeadMode === "funnel") return crmFunnel(body, tools);
  const r = await api.crm_leads({q: S.crmLeadQ || "", open: true});
  S.crmLeadsR = r;
  body.innerHTML = `<div class="tab-tools rep-tools">${tools}<button class="btn small" id="crmNewLead">Новая заявка</button>
      <input class="input sm-sel crm-q" id="crmLeadQ" placeholder="Имя или телефон" value="${esc(S.crmLeadQ || "")}"><span class="grow"></span>
      <span class="muted">Заявки за 3 месяца и все незакрытые</span></div>
    <div class="lead-board">${r.stages.map(st => `<section class="lb-col" data-st="${st.key}"><header><b>${esc(st.title)}</b><span class="cnt">${st.count}</span></header>
      <div class="lb-list">${r.rows.filter(x => x.stage === st.key).map(x => leadCard(x, r.rows.indexOf(x))).join("") || `<div class="lb-empty">—</div>`}</div></section>`).join("")}</div>
    <div class="muted note-line">Заявка — человек, который позвонил, написал или пришёл, но ещё не стал пациентом. Когда заявка связана с карточкой, программа сама переводит её в «Записан» и «Пришёл» по расписанию.</div>`;
  bindLeadMode();
  $("#crmNewLead").onclick = () => openLead({}, loadMarketing);
  let t; const q = $("#crmLeadQ"); q.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.crmLeadQ = q.value; loadMarketing().then(() => { const n = $("#crmLeadQ"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }); }, 300); };
  $$(".lead-card", body).forEach(c => c.onclick = () => openLead(r.rows[+c.dataset.i], loadMarketing));
}
function bindLeadMode() { $$("#crmLm button").forEach(b => b.onclick = () => { S.crmLeadMode = b.dataset.m; loadMarketing(); }); }
function leadCard(x, i) {
  return `<button class="lead-card" data-i="${i}"><b>${esc(x.name || x.phone || "Без имени")}</b>${x.interest ? `<span>${esc(x.interest)}</span>` : ""}
    <small class="muted">${esc([x.channel, x.source].filter(Boolean).join(" · ") || "—")}</small>
    <small class="lc-foot"><span class="${x.late ? "bad-t" : "muted"}">${x.stage === "lost" ? esc(x.lost_reason || "отказ") : x.next_at ? "связаться " + crmDay(x.next_at) : fmtShort(x.created_at)}</span>${x.patient_id ? '<span class="pill st-ok">в базе</span>' : ""}</small></button>`;
}
async function openLead(x, after) {
  const R = S.crmLeadsR || await api.crm_leads({});
  const src = await mkSourceList();
  const full = x.id ? await api.crm_lead(x.id) : {stage: "new", matches: [], tasks: []};
  const stages = R.stages.map(s => [s.key, s.title]);
  const box = modal(`<div class="m-h"><h3>${x.id ? "Заявка" : "Новая заявка"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${x.id ? `<div class="seg sm lead-stage" id="ldSt">${stages.map(([k, t]) => `<button data-k="${k}" class="${k === full.stage ? "on" : ""}">${esc(t)}</button>`).join("")}</div>` : ""}
      ${full.stage === "lost" && full.lost_reason ? `<div class="warn-line">Причина отказа: ${esc(full.lost_reason)}</div>` : ""}
      <div class="grid2"><label class="fl">Имя<input class="input" id="ldN" value="${esc(full.name || "")}" placeholder="Фамилия Имя" autofocus></label>
        <label class="fl">Телефон<input class="input" id="ldP" value="${esc(full.phone || "")}" placeholder="+7 900 000-00-00"></label></div>
      <div id="ldMatch">${matchHtml(full)}</div>
      <div class="grid2"><label class="fl">Откуда обратился<select class="input" id="ldC">${R.channels.map(c => `<option ${c === full.channel ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
        <label class="fl">Как узнал о клинике${sourceSelect("ldS", full.source || "", src)}</label></div>
      <label class="fl">Что хочет<input class="input" id="ldI" value="${esc(full.interest || "")}" placeholder="Болит зуб, профгигиена, консультация по имплантации…"></label>
      <div class="grid2"><label class="fl">Когда связаться<input class="input" type="date" id="ldD" value="${esc(full.next_at || "")}"></label>
        <label class="fl">Кто ведёт<select class="input" id="ldA"><option value="">Все администраторы</option>${R.staff.map(s => `<option value="${esc(s.login)}" ${s.login === full.assignee ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label></div>
      <label class="fl">Комментарий<textarea class="input" id="ldT" rows="2">${esc(full.comment || "")}</textarea></label>
      ${full.created_at ? `<p class="muted small-note">Создана ${fmtDT(full.created_at)}${full.created_by ? " · " + esc(full.created_by) : ""}</p>` : ""}<div class="auth-err" id="ldErr"></div></div>
    <div class="m-f">${full.phone ? `<button class="btn ghost small" id="ldWa">WhatsApp</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Закрыть</button>
      ${can("schedule_edit") ? `<button class="btn ghost" id="ldBook">${full.patient_id ? "Записать на приём" : "Завести карточку и записать"}</button>` : ""}<button class="btn" id="ldOk">Сохранить</button></div>`);
  let linked = full.patient_id || null;
  const form = () => ({id: x.id || full.id, name: $("#ldN", box).value, phone: $("#ldP", box).value, channel: $("#ldC", box).value, source: $("#ldS", box).value,
    interest: $("#ldI", box).value, next_at: $("#ldD", box).value, assignee: $("#ldA", box).value, comment: $("#ldT", box).value, patient_id: linked});
  const save = async () => { const id = await api.crm_lead_save(form()); x.id = id; full.id = id; return id; };
  const bindMatch = () => $$("[data-link]", box).forEach(b => b.onclick = () => { linked = b.dataset.link; $("#ldMatch", box).innerHTML = `<div class="ok-line">Заявка будет связана с карточкой «${esc(b.dataset.n)}»</div>`; });
  bindMatch();
  $$("[data-open-p]", box).forEach(b => b.onclick = () => { closeModal(); openPatient(b.dataset.openP, "marketing"); });
  $("#ldP", box).onchange = async () => {
    if (linked) return;
    const m = await api.crm_match($("#ldP", box).value).catch(() => []);
    $("#ldMatch", box).innerHTML = matchHtml({matches: m}); bindMatch();
  };
  $("#ldOk", box).onclick = async () => { try { await save(); closeModal(); toast("Заявка сохранена"); if (after) after(); } catch (e) { $("#ldErr").textContent = errText(e); } };
  $$("#ldSt button", box).forEach(b => b.onclick = async () => {
    let reason = "";
    if (b.dataset.k === "lost") {
      const v = await askInput("Почему отказ?", [{label: `Причина (${R.reasons.join(", ").toLowerCase()})`, value: R.reasons[0]}], {ok: "Отметить отказ"});
      if (!v) return; reason = v[0];
    }
    try { await save(); await api.crm_lead_stage(full.id, b.dataset.k, reason); closeModal(); toast("Этап заявки изменён"); if (after) after(); } catch (e) { $("#ldErr").textContent = errText(e); }
  });
  const wa = $("#ldWa", box);
  if (wa) wa.onclick = async () => { const phone = rmPhone($("#ldP", box).value); if (!phone) return toast("Проверьте телефон", true);
    const first = ($("#ldN", box).value.trim().split(/\s+/)[1] || $("#ldN", box).value.trim().split(/\s+/)[0] || "");
    await openUrl(`https://wa.me/${phone}?text=${encodeURIComponent(`Здравствуйте${first ? ", " + first : ""}! `)}`); };
  const bk = $("#ldBook", box);
  if (bk) bk.onclick = async () => {
    try {
      const id = await save();
      const p = linked ? {id: linked} : await api.crm_lead_patient(id);
      const name = linked ? (full.patient_name || $("#ldN", box).value) : p.name, want = $("#ldI", box).value.trim();
      closeModal();
      openBooking({patient_id: p.id, patient_name: name, start: `${addDays(iso(new Date()), 1)} 10:00`, title: want,
        onSaved: async () => { try { await api.crm_lead_stage(id, "booked", ""); } catch (e) { /* the visit is saved */ } if (after) after(); }});
    } catch (e) { $("#ldErr").textContent = errText(e); }
  };
}
function matchHtml(full) {
  if (full.patient_id) return `<div class="ok-line">Связана с карточкой: <button class="linkbtn" data-open-p="${esc(full.patient_id)}">${esc(full.patient_name || "пациент")}</button></div>`;
  if (!full.matches || !full.matches.length) return "";
  return `<div class="warn-line">С этим телефоном уже есть пациент: ${full.matches.map(m => `<button class="linkbtn" data-link="${esc(m.id)}" data-n="${esc(m.name)}">${esc(m.name)}</button>`).join(", ")} — нажмите, чтобы связать заявку с его карточкой.</div>`;
}
async function crmFunnel(body, tools) {
  const r = await api.crm_funnel(S.period.from, S.period.to);
  const max = Math.max(1, ...r.steps.map(s => s.count));
  const grp = (rows, title) => rows.length ? `<table class="tbl"><thead><tr><th>${title}</th><th class="num">Заявок</th><th class="num">Записались</th><th class="num">Пришли</th><th class="num">Отказ</th><th class="num">Конверсия</th></tr></thead><tbody>${
    rows.map(x => `<tr><td><b>${esc(x.name || "Не указан")}</b></td><td class="num">${x.leads}</td><td class="num">${x.booked}</td><td class="num">${x.came}</td><td class="num">${x.lost || "—"}</td><td class="num">${x.conv} %</td></tr>`).join("")}</tbody></table>` : "";
  body.innerHTML = `<div class="tab-tools rep-tools">${tools}${periodBar()}<span class="grow"></span>${xlsBtn("Воронка заявок")}<button class="icon-btn" id="mkPrint" title="Печать">${PRINT_ICON}</button></div>
    ${r.total ? `<div class="panel crm-funnel">${r.steps.map((s, i) => `<div class="fn-row"><span class="fn-t">${esc(s.title)}</span><span class="fn-bar"><i style="width:${Math.max(2, s.count * 100 / max)}%"></i></span><b>${s.count}</b><small class="muted">${i ? Math.round(s.count * 100 / Math.max(1, r.total)) + " %" : ""}</small></div>`).join("")}
      <div class="fn-row lost"><span class="fn-t">Отказ</span><span class="fn-bar"><i style="width:${Math.max(r.lost ? 2 : 0, r.lost * 100 / max)}%"></i></span><b>${r.lost}</b><small class="muted">${r.reasons.map(x => `${esc(x.reason)} — ${x.count}`).join(", ")}</small></div></div>
      <div class="pbody">${grp(r.by_source, "Как узнали о клинике")}</div><div class="pbody">${grp(r.by_channel, "Откуда обратились")}</div>`
      : `<div class="pbody"><div class="empty"><b>За период заявок нет</b><span>Заявки добавляются на вкладке «Заявки» → «Доска»</span></div></div>`}
    <div class="muted note-line">Конверсия — доля заявок, по которым человек пришёл на приём.</div>`;
  bindLeadMode();
}

/* =============================================================== segments */
const SEG_LABELS = {months: "не были больше, мес.", no_future: "нет будущей записи", plan: "план лечения", birthday_days: "день рождения в ближайшие, дн.",
  source: "источник", age_min: "возраст от", age_max: "возраст до", service: "была услуга", service_months: "услуга больше, мес. назад",
  visits_min: "визитов не меньше", doctor_id: "врач", paid_min: "оплатил не меньше, ₽", debt: "есть долг", with_no_calls: "включая «не звонить»"};
async function crmSegments(body) {
  const [L, R] = await Promise.all([api.crm_segments(), ref()]);
  if (!S.crmSegF) { S.crmSegF = {...L.presets[0].filters}; S.crmSegTitle = L.presets[0].title; S.crmSegId = L.presets[0].id; }
  const f = S.crmSegF;
  const r = await api.crm_segment_run(f);
  S.crmSegR = r;
  const v = k => f[k] ?? "";
  body.innerHTML = `<div class="seg-wrap"><aside class="seg-side panel"><div class="ss-h">Готовые</div>${L.presets.map(p => `<button class="ss-item ${S.crmSegId === p.id ? "on" : ""}" data-pre="${esc(p.id)}">${esc(p.title)}</button>`).join("")}
      <div class="ss-h">Сохранённые</div>${L.saved.map(p => `<div class="ss-row"><button class="ss-item ${S.crmSegId === p.id ? "on" : ""}" data-sv="${esc(p.id)}">${esc(p.title)}</button><button class="icon-btn sm" data-svdel="${esc(p.id)}" title="Удалить сегмент">×</button></div>`).join("") || `<small class="muted ss-empty">Настройте фильтры и нажмите «Сохранить сегмент»</small>`}</aside>
    <div class="seg-main"><div class="panel seg-f">
      <label>Не были больше<span><input class="input" type="number" min="1" data-f="months" value="${v("months")}"> мес.</span></label>
      <label>План лечения<select class="input" data-f="plan"><option value="">—</option><option value="any" ${f.plan === "any" ? "selected" : ""}>не завершён (любой)</option><option value="not_started" ${f.plan === "not_started" ? "selected" : ""}>не начат</option><option value="unfinished" ${f.plan === "unfinished" ? "selected" : ""}>начат, не завершён</option></select></label>
      <label>Была услуга<input class="input" data-f="service" value="${esc(v("service"))}" placeholder="гигиена, имплант…"></label>
      <label>…последний раз больше<span><input class="input" type="number" min="1" data-f="service_months" value="${v("service_months")}"> мес. назад</span></label>
      <label>Источник<select class="input" data-f="source"><option value="">—</option>${L.sources.map(s => `<option ${s === f.source ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
      <label>Врач<select class="input" data-f="doctor_id"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === f.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
      <label>Возраст<span><input class="input" type="number" min="0" data-f="age_min" value="${v("age_min")}" placeholder="от"> — <input class="input" type="number" min="0" data-f="age_max" value="${v("age_max")}" placeholder="до"></span></label>
      <label>День рождения в ближайшие<span><input class="input" type="number" min="1" data-f="birthday_days" value="${v("birthday_days")}"> дн.</span></label>
      <label>Визитов не меньше<input class="input" type="number" min="1" data-f="visits_min" value="${v("visits_min")}"></label>
      <label>Оплатил не меньше, ₽<input class="input" type="number" min="1" data-f="paid_min" value="${v("paid_min")}"></label>
      <div class="seg-sw"><label class="switch-row"><input type="checkbox" data-f="no_future" ${f.no_future ? "checked" : ""}><span class="sw"></span>Нет будущей записи</label>
        <label class="switch-row"><input type="checkbox" data-f="debt" ${f.debt ? "checked" : ""}><span class="sw"></span>Есть долг</label>
        <label class="switch-row"><input type="checkbox" data-f="with_no_calls" ${f.with_no_calls ? "checked" : ""}><span class="sw"></span>Включая «не звонить»</label></div>
      <div class="seg-act"><button class="btn ghost small" id="sgClear">Сбросить</button><button class="btn ghost small" id="sgSave">Сохранить сегмент</button><button class="btn small" id="sgRun">Показать</button></div></div>
      <div class="tab-tools rep-tools"><b class="seg-count">${r.count} ${plural(r.count, "пациент", "пациента", "пациентов")}</b><span class="muted">с телефоном — ${r.with_phone}</span><span class="grow"></span>
        <button class="btn small" id="sgMail" ${r.with_phone ? "" : "disabled"}>Рассылка в WhatsApp</button>${xlsBtn(S.crmSegTitle || "Сегмент")}<button class="icon-btn" id="mkPrint" title="Печать">${PRINT_ICON}</button></div>
      <div class="pbody">${r.rows.length ? `<table class="tbl"><thead><tr><th>Пациент</th><th>Телефон</th><th class="num">Возраст</th><th>Почему в списке</th><th></th></tr></thead><tbody>${
        r.rows.slice(0, 500).map((x, i) => `<tr><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name || "—")}</b></td><td class="nowrap">${esc(x.phone || "—")}</td><td class="num">${x.age ?? "—"}</td><td>${esc(x.info)}</td><td class="row-acts">${x.phone ? `<button class="btn ghost small" data-swa="${i}">WhatsApp</button>` : ""}</td></tr>`).join("")}</tbody></table>${r.rows.length > 500 ? `<div class="muted note-line">Показаны первые 500 — в Excel и рассылку попадут все ${r.rows.length}.</div>` : ""}`
        : `<div class="empty"><b>Никто не подходит</b><span>Ослабьте фильтры</span></div>`}</div>
      <div class="muted note-line">Рассылка открывает WhatsApp по очереди с готовым текстом — администратор только нажимает «Отправить». Пациенты с отметкой «не звонить» не попадают в сегмент. Каждое сообщение отмечается в истории звонков пациента.</div></div></div>`;
  const read = () => { const o = {}; $$("[data-f]", body).forEach(el => { if (el.type === "checkbox") { if (el.checked) o[el.dataset.f] = true; } else if (el.value !== "") o[el.dataset.f] = el.value; }); return o; };
  const run = (nf, title, id) => { S.crmSegF = nf; S.crmSegTitle = title; S.crmSegId = id || null; loadMarketing(); };
  $("#sgRun").onclick = () => run(read(), "Свой сегмент", null);
  $$("[data-f]", body).forEach(el => el.onkeydown = e => { if (e.key === "Enter") run(read(), "Свой сегмент", null); });
  $("#sgClear").onclick = () => run({}, "Все пациенты", null);
  $$("[data-pre]", body).forEach(b => b.onclick = () => { const p = L.presets.find(x => x.id === b.dataset.pre); run({...p.filters}, p.title, p.id); });
  $$("[data-sv]", body).forEach(b => b.onclick = () => { const p = L.saved.find(x => x.id === b.dataset.sv); run({...p.filters}, p.title, p.id); });
  $$("[data-svdel]", body).forEach(b => b.onclick = async () => { const p = L.saved.find(x => x.id === b.dataset.svdel);
    if (await ask("Удалить сегмент?", {danger: true, ok: "Удалить", text: p.title})) { await api.crm_segment_delete(p.id); if (S.crmSegId === p.id) S.crmSegId = null; toast("Сегмент удалён"); loadMarketing(); } });
  $("#sgSave").onclick = async () => {
    const cur = L.saved.find(x => x.id === S.crmSegId);
    const v2 = await askInput("Сохранить сегмент", [{label: "Название", value: cur ? cur.title : ""}]);
    if (!v2) return;
    try { S.crmSegId = await api.crm_segment_save({id: cur ? cur.id : null, title: v2[0], filters: read()}); S.crmSegTitle = v2[0]; S.crmSegF = read(); toast("Сегмент сохранён"); loadMarketing(); } catch (e) { toast(errText(e), true); }
  };
  $$("[data-p]", body).forEach(el => el.onclick = () => openPatient(el.dataset.p, "marketing"));
  $$("[data-swa]", body).forEach(b => b.onclick = async () => { const s = await crmSettings(); await crmWhatsApp(r.rows[+b.dataset.swa], s.mail_text, {}, "segment", S.crmSegTitle || "Рассылка"); });
  $("#sgMail").onclick = () => openMailing(r.rows.filter(x => rmPhone(x.phone)), S.crmSegTitle || "Рассылка");
}
async function openMailing(rows, title) {
  const s = await crmSettings();
  let i = 0, sent = 0;
  const box = modal(`<div class="m-h"><h3>Рассылка: ${esc(title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><label class="fl">Текст сообщения<textarea class="input" id="mlT" rows="4">${esc(s.mail_text)}</textarea></label>
      <p class="hint">Подставляется само: <code>{имя}</code> <code>{фио}</code> <code>{клиника}</code> <code>{адрес}</code> <code>{телефон клиники}</code>.</p>
      <div class="ml-q" id="mlQ"></div></div>
    <div class="m-f"><button class="btn ghost small" id="mlSaveT">Запомнить текст</button><span class="muted" id="mlN"></span><button class="btn ghost" id="mlSkip">Пропустить</button><button class="btn" id="mlGo">Открыть WhatsApp</button></div>`, {wide: true});
  const draw = async () => {
    const x = rows[i];
    $("#mlN", box).textContent = `Отправлено ${sent} из ${rows.length}`;
    if (!x) { $("#mlQ", box).innerHTML = `<div class="ok-line">Готово: сообщения открыты для всех ${rows.length} пациентов.</div>`; $("#mlGo", box).disabled = $("#mlSkip", box).disabled = true; return; }
    $("#mlQ", box).innerHTML = `<div class="ml-cur"><span class="muted">${i + 1} из ${rows.length}</span><b>${esc(x.name)}</b><span>${esc(x.phone)}</span></div><div class="rm-prev"><small class="muted">Так увидит пациент:</small><div>${esc(rmText($("#mlT", box).value, x, await crmClinic()))}</div></div>`;
  };
  $("#mlT", box).oninput = draw;
  $("#mlGo", box).onclick = async () => { if (await crmWhatsApp(rows[i], $("#mlT", box).value, {}, "segment", title)) sent++; i++; draw(); };
  $("#mlSkip", box).onclick = () => { i++; draw(); };
  $("#mlSaveT", box).onclick = async () => { try { S.crmSet = await api.crm_settings_save({mail_text: $("#mlT", box).value}); toast("Текст рассылки сохранён"); } catch (e) { toast(errText(e), true); } };
  draw();
}

/* ================================================================ reviews */
async function crmReviews(body) {
  const tools = `<div class="seg sm" id="crmRv"><button data-m="ask" class="${S.crmRvMode === "ask" ? "on" : ""}">Кого спросить</button><button data-m="stats" class="${S.crmRvMode === "stats" ? "on" : ""}">Оценки</button></div>`;
  const bindMode = () => $$("#crmRv button").forEach(b => b.onclick = () => { S.crmRvMode = b.dataset.m; loadMarketing(); });
  const s = await crmSettings();
  if (S.crmRvMode === "stats") {
    const r = await api.crm_reviews(S.period.from, S.period.to);
    const dmax = Math.max(1, ...r.dist);
    body.innerHTML = `<div class="tab-tools rep-tools">${tools}${periodBar()}<span class="grow"></span>${xlsBtn("Оценки визитов")}<button class="icon-btn" id="mkPrint" title="Печать">${PRINT_ICON}</button></div>
      <div class="stat-row"><div class="stat"><span>Индекс лояльности (NPS)</span><b>${r.nps ?? "—"}</b><small class="muted">доля 9–10 минус доля 0–6</small></div>
        <div class="stat"><span>Средняя оценка</span><b>${r.avg ?? "—"}</b><small class="muted">${r.count} ${plural(r.count, "оценка", "оценки", "оценок")}</small></div>
        <div class="stat"><span>Довольны (9–10)</span><b>${r.promoters}</b></div><div class="stat"><span>Нейтральны (7–8)</span><b>${r.passives}</b></div><div class="stat"><span>Недовольны (0–6)</span><b class="${r.detractors ? "bad-t" : ""}">${r.detractors}</b></div></div>
      ${r.count ? `<div class="crm-rv-grid"><div class="panel nps-dist"><div class="pb-head"><b>Оценки от 0 до 10</b></div><div class="nd-bars">${r.dist.map((n, k) => `<div class="nd-c ${k <= 6 ? "det" : k >= 9 ? "pro" : ""}" title="${k}: ${n}"><span style="height:${n ? Math.max(4, n * 100 / dmax) : 0}%"></span><small>${k}</small></div>`).join("")}</div></div>
        <div class="pbody"><table class="tbl"><thead><tr><th>Врач</th><th class="num">Оценок</th><th class="num">Средняя</th><th class="num">NPS</th></tr></thead><tbody>${r.by_doctor.map(x => `<tr><td><b>${esc(x.name)}</b></td><td class="num">${x.count}</td><td class="num">${x.avg}</td><td class="num">${x.nps}</td></tr>`).join("")}</tbody></table></div></div>
        <div class="pbody"><table class="tbl"><thead><tr><th>Когда</th><th>Пациент</th><th>Врач</th><th class="num">Оценка</th><th>Комментарий</th><th>Как</th><th></th></tr></thead><tbody>${
          r.rows.map((x, i) => `<tr><td class="nowrap">${fmtDT(x.created_at)}</td><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.patient_name || "—")}</b></td><td>${esc(x.doctor_name || "—")}</td><td class="num"><span class="score ${x.score <= 6 ? "det" : x.score >= 9 ? "pro" : ""}">${x.score}</span></td><td>${esc(x.comment || "")}</td><td class="muted">${{tablet: "планшет", phone: "по телефону", message: "сообщение"}[x.channel] || ""}</td><td class="row-acts"><button class="icon-btn sm" data-rvdel="${i}" title="Удалить оценку">×</button></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="pbody"><div class="empty"><b>За период оценок нет</b><span>Спросите пациентов на вкладке «Кого спросить»</span></div></div>`}
      <div class="muted note-line">Оценка ${s.bad_score} и ниже ставит задачу директору — позвонить и разобраться. При оценке ${s.good_score}–10 программа предлагает отправить ссылку на отзыв в Яндекс Картах или 2ГИС${r.links.length ? "" : " (ссылки пока не указаны: «Кого спросить» → «Ссылки на отзывы»)"}.</div>`;
    bindMode();
    $$("[data-p]", body).forEach(el => el.onclick = () => openPatient(el.dataset.p, "marketing"));
    $$("[data-rvdel]", body).forEach(b => b.onclick = async () => { const x = r.rows[+b.dataset.rvdel];
      if (await ask("Удалить оценку?", {danger: true, ok: "Удалить", text: `${x.patient_name}: ${x.score}`})) { await api.crm_review_delete(x.id); toast("Оценка удалена"); loadMarketing(); } });
    return;
  }
  const day = S.crmRvDay || iso(new Date());
  const [q, tablets] = await Promise.all([api.crm_review_queue(day), api.tablets_list().catch(() => [])]);
  body.innerHTML = `<div class="tab-tools rep-tools">${tools}<label class="inline-f">Визиты за<input type="date" class="input" id="rvDay" value="${q.day}"></label><span class="grow"></span>
      <span class="muted">${q.rows.length ? `Не спросили: ${q.left} из ${q.rows.length}` : ""}</span><button class="btn ghost small" id="rvLinks">Ссылки на отзывы</button></div>
    <div class="pbody">${q.rows.length ? `<table class="tbl"><thead><tr><th>Пациент</th><th>Телефон</th><th>Визит</th><th>Оценка</th><th></th></tr></thead><tbody>${
      q.rows.map((x, i) => `<tr class="${x.rated ? "muted-row" : ""}"><td class="lnk" data-p="${esc(x.patient_id)}"><b>${esc(x.name || "—")}</b></td><td class="nowrap">${esc(x.phone || "—")}</td><td>${esc(x.info)}</td>
        <td>${x.rated ? '<span class="pill st-ok">оценил</span>' : x.no_calls ? '<span class="pill st-cancel">не звонить</span>' : '<span class="muted">—</span>'}</td>
        <td class="row-acts">${x.rated ? "" : `${tablets.length ? `<button class="btn ghost small" data-rtab="${i}" title="Пациент поставит оценку на планшете">На планшет</button>` : ""}${x.phone && !x.no_calls ? `<button class="btn ghost small" data-rwa="${i}" title="Спросить оценку в WhatsApp">WhatsApp</button>` : ""}<button class="btn small" data-rset="${i}">Записать оценку</button>`}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Визитов нет</b><span>На этот день нет состоявшихся визитов</span></div>`}</div>
    <div class="muted note-line">Спросите пациента после визита: «Насколько вероятно, что вы порекомендуете нас знакомым — от 0 до 10?». На планшете пациент ставит оценку сам; ответ из WhatsApp или по телефону запишите кнопкой «Записать оценку».</div>`;
  bindMode();
  $("#rvDay").onchange = e => { S.crmRvDay = e.target.value; loadMarketing(); };
  $("#rvLinks").onclick = () => openCrmSettings("reviews");
  $$("[data-p]", body).forEach(el => el.onclick = () => openPatient(el.dataset.p, "marketing"));
  $$("[data-rwa]", body).forEach(b => b.onclick = async () => { await crmWhatsApp(q.rows[+b.dataset.rwa], s.nps_text, {}, "reviews", "Попросили оценить визит"); });
  $$("[data-rset]", body).forEach(b => b.onclick = () => openScore(q.rows[+b.dataset.rset], loadMarketing));
  $$("[data-rtab]", body).forEach(b => b.onclick = async () => {
    const x = q.rows[+b.dataset.rtab];
    const t = tablets.length === 1 ? tablets[0] : await chooseTablet(tablets);
    if (t) sendToTablet(t, "nps", x.patient_id, null, () => loadMarketing(), {visit_id: x.visit_id});
  });
}
function openScore(x, after) {
  let score = null;
  const box = modal(`<div class="m-h"><h3>Оценка визита · ${esc(x.name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">${esc(x.info || "")}</p><div class="nps-pick">${[...Array(11).keys()].map(k => `<button class="${k <= 6 ? "det" : k >= 9 ? "pro" : ""}" data-s="${k}">${k}</button>`).join("")}</div>
      <label class="fl">Что сказал пациент<textarea class="input" id="scC" rows="2"></textarea></label><div class="auth-err" id="scErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="scOk">Сохранить</button></div>`);
  $$(".nps-pick button", box).forEach(b => b.onclick = () => { score = +b.dataset.s; $$(".nps-pick button", box).forEach(y => y.classList.toggle("on", y === b)); $("#scErr").textContent = ""; });
  $("#scOk", box).onclick = async () => {
    if (score === null) { $("#scErr").textContent = "Выберите оценку"; return; }
    try {
      const r = await api.crm_review_save({patient_id: x.patient_id, visit_id: x.visit_id || null, score, comment: $("#scC", box).value, channel: "phone"});
      closeModal(); refreshStatus();
      if (r.ask_review && r.links.length && x.phone) {
        const s = await crmSettings();
        const box2 = modal(`<div class="m-h"><h3>Пациент доволен — попросите отзыв</h3><button class="x" data-close>×</button></div>
          <div class="m-b"><p>Отправьте ссылку, по которой пациент оставит отзыв о клинике.</p><div class="tb-list">${r.links.map((l, i) => `<button class="btn ghost" data-l="${i}">${esc(l.title)} — WhatsApp</button>`).join("")}</div></div>
          <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Не сейчас</button></div>`);
        $$("[data-l]", box2).forEach(b => b.onclick = async () => { await crmWhatsApp(x, s.review_text, {"ссылка": r.links[+b.dataset.l].url}, "reviews", "Ссылка на отзыв: " + r.links[+b.dataset.l].title); closeModal(); });
      } else toast(score <= (S.crmSet ? S.crmSet.bad_score : 6) ? "Оценка сохранена. Директору поставлена задача разобраться" : "Оценка сохранена");
      if (after) after();
    } catch (e) { $("#scErr").textContent = errText(e); }
  };
}

/* =============================================================== settings */
async function openCrmSettings(focus) {
  const s = await crmSettings(true);
  const ruleRow = r => `<div class="rule-row" data-id="${esc(r.id || "")}"><label class="switch-row" title="Правило включено"><input type="checkbox" data-k="on" ${r.on !== false ? "checked" : ""}><span class="sw"></span></label>
    <input class="input" data-k="match" value="${esc(r.match || "")}" placeholder="Слова из названия услуги"><span class="muted">через</span><input class="input num" type="number" min="0" data-k="days" value="${r.days ?? 1}"><span class="muted">дн.</span>
    <input class="input" data-k="title" value="${esc(r.title || "")}" placeholder="Что сделать"><label class="switch-row" title="Не ставить задачу, если пациент уже записан"><input type="checkbox" data-k="skip_booked" ${r.skip_booked ? "checked" : ""}><span class="sw"></span>если не записан</label>
    <button class="icon-btn sm" data-rdel title="Убрать правило">×</button></div>`;
  const box = modal(`<div class="m-h"><h3>Настройки CRM</h3><button class="x" data-close>×</button></div>
    <div class="m-b crm-set">
      <section id="csRules"><h4>Задачи после услуг</h4><p class="hint">Когда в счёте или в завершённом визите есть услуга с этими словами, через указанное число дней появится задача.</p>
        <div id="csRuleList">${s.rules.map(ruleRow).join("")}</div><button class="btn ghost small" id="csAdd">Добавить правило</button>
        <div class="cs-line"><label class="switch-row"><input type="checkbox" id="csPlanOn" ${s.plan_on ? "checked" : ""}><span class="sw"></span>План лечения подтверждён или начат, но пациент не приходит</label>
          <span class="inline-f"><input class="input num" type="number" min="7" id="csPlanD" value="${s.plan_days}"> дн. — задача «пригласить продолжить»</span></div></section>
      <section id="csReviews"><h4>Оценка визита и отзывы</h4>
        <div class="grid3">${Object.entries({yandex: "Яндекс Карты", gis: "2ГИС", other: "Другая площадка"}).map(([k, t]) => `<label class="fl">${t}<input class="input" data-link="${k}" value="${esc(s.links[k] || "")}" placeholder="https://…"></label>`).join("")}</div>
        <p class="hint">Ссылка на страницу клиники, где пишут отзывы. На планшете после высокой оценки пациент увидит QR-код этой страницы.</p>
        <div class="grid2"><label class="fl">Задача директору при оценке не выше<input class="input" type="number" min="0" max="9" id="csBad" value="${s.bad_score}"></label>
          <label class="fl">Просить отзыв при оценке от<input class="input" type="number" min="1" max="10" id="csGood" value="${s.good_score}"></label></div>
        <label class="fl">Вопрос на планшете<input class="input" id="csQ" value="${esc(s.nps_question)}"></label>
        <label class="fl">Сообщение «оцените визит» (WhatsApp)<textarea class="input" id="csNps" rows="2">${esc(s.nps_text)}</textarea></label>
        <label class="fl">Сообщение со ссылкой на отзыв — <code>{ссылка}</code> подставится сама<textarea class="input" id="csRev" rows="2">${esc(s.review_text)}</textarea></label></section>
      <div class="auth-err" id="csErr"></div></div>
    <div class="m-f"><span class="muted">Настройки общие для всех компьютеров клиники</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="csOk">Сохранить</button></div>`, {wide: true});
  const bindDel = () => $$("[data-rdel]", box).forEach(b => b.onclick = () => b.closest(".rule-row").remove());
  bindDel();
  $("#csAdd", box).onclick = () => { $("#csRuleList", box).insertAdjacentHTML("beforeend", ruleRow({on: true, days: 1})); bindDel(); };
  if (focus === "reviews") setTimeout(() => { const el = $("#csReviews", box); if (el) el.scrollIntoView({block: "start"}); }, 40);
  $("#csOk", box).onclick = async () => {
    const rules = $$(".rule-row", box).map(r => ({id: r.dataset.id, on: $("[data-k=on]", r).checked, match: $("[data-k=match]", r).value, days: $("[data-k=days]", r).value,
      title: $("[data-k=title]", r).value, skip_booked: $("[data-k=skip_booked]", r).checked}));
    const links = {}; $$("[data-link]", box).forEach(i => links[i.dataset.link] = i.value.trim());
    try {
      S.crmSet = await api.crm_settings_save({rules, plan_on: $("#csPlanOn", box).checked, plan_days: $("#csPlanD", box).value, links,
        bad_score: $("#csBad", box).value, good_score: $("#csGood", box).value, nps_question: $("#csQ", box).value, nps_text: $("#csNps", box).value, review_text: $("#csRev", box).value});
      closeModal(); toast("Настройки CRM сохранены"); if (S.view === "marketing") loadMarketing();
    } catch (e) { $("#csErr").textContent = errText(e); }
  };
}

/* ========================================================== patient card */
async function loadPatientCrm(p) {
  const el = $("#crmPBody"); if (!el) return;
  const r = await api.crm_patient(p.id);
  const open = r.tasks.filter(t => t.status === "open"), done = r.tasks.filter(t => t.status === "done");
  el.innerHTML = `<div class="tab-tools"><button class="btn ghost small" id="pcTask">Новая задача</button><button class="btn ghost small" id="pcScore">Записать оценку визита</button><span class="muted">Задачи, звонки, сообщения, оценки и заявки этого пациента</span></div>
    <div class="crm-pc">
      <section><h4>Открытые задачи</h4>${open.length ? open.map((t, i) => `<div class="ev-row"><span class="due ${t.due < iso(new Date()) ? "late" : ""}">${crmDay(t.due)}</span><span class="grow"><b>${esc(t.title)}</b>${t.assignee_name ? ` <small class="muted">· ${esc(t.assignee_name)}</small>` : ""}</span><button class="btn small" data-pdone="${i}">Готово</button></div>`).join("") : `<p class="muted">Нет</p>`}</section>
      <section><h4>Звонки и сообщения</h4>${r.calls.length ? `<div class="ev-list">${r.calls.map(c => `<div class="ev-row"><span class="pill ${CALL_CLS[c.result] || ""}">${esc(c.result)}</span><span class="grow">${esc(c.comment || "")}</span><small class="muted">${fmtDT(c.at)} · ${esc(c.user_name || "")}</small></div>`).join("")}</div>` : `<p class="muted">Нет</p>`}</section>
      <section><h4>Оценки визитов</h4>${r.reviews.length ? r.reviews.map(x => `<div class="ev-row"><span class="score ${x.score <= 6 ? "det" : x.score >= 9 ? "pro" : ""}">${x.score}</span><span class="grow">${esc(x.comment || "")}${x.doctor_name ? ` <small class="muted">· ${esc(x.doctor_name)}</small>` : ""}</span><small class="muted">${fmtDT(x.created_at)}</small></div>`).join("") : `<p class="muted">Нет</p>`}</section>
      ${r.leads.length ? `<section><h4>Заявки</h4>${r.leads.map(x => `<div class="ev-row"><span class="pill">${esc(r.stages[x.stage] || x.stage)}</span><span class="grow">${esc(x.interest || x.channel || "")}${x.source ? ` <small class="muted">· ${esc(x.source)}</small>` : ""}</span><small class="muted">${fmtDT(x.created_at)}</small></div>`).join("")}</section>` : ""}
      ${done.length ? `<section><h4>Выполненные задачи</h4>${done.map(t => `<div class="ev-row"><span class="pill ${CRM_RES_CLS[t.result] || ""}">${esc(t.result || "Сделано")}</span><span class="grow">${esc(t.title)}</span><small class="muted">${fmtDT(t.done_at)} · ${esc(t.done_by || "")}</small></div>`).join("")}</section>` : ""}</div>`;
  const reload = async () => { P = await api.patient(p.id); renderPatient("crm"); refreshStatus(); };
  $$("[data-pdone]", el).forEach(b => b.onclick = () => taskDone({...open[+b.dataset.pdone], patient_name: p.name, phone: p.phone}, reload));
  $("#pcTask", el).onclick = () => editTask({patient_id: p.id, patient_name: p.name}, reload);
  $("#pcScore", el).onclick = () => openScore({patient_id: p.id, name: p.name, phone: p.phone}, reload);
}

/* menu badge: open tasks for today and earlier (mine and shared) */
function crmStatus(st) { const b = $("#crmBadge"); if (b) { b.hidden = !st.crm_due; b.textContent = st.crm_due || ""; b.title = st.crm_due ? `Задач на сегодня: ${st.crm_due}` : ""; } }
