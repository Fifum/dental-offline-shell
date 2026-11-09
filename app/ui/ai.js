"use strict";
/* 2.13 «ИИ»: the assistant in the corner of the screen, drafts of documents, translation, the record check,
   the tooth chart and notes by voice, the patient's consent to a visit recording, the director's weekly summary,
   the clinic's own local model and its quality check. Every change is proposed and done only after «Да». */
const AI_ICON = '<svg viewBox="0 0 24 24"><path d="M12 3.5l1.6 4.4 4.4 1.6-4.4 1.6L12 15.5l-1.6-4.4L6 9.5l4.4-1.6z"/><path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/></svg>';
const AI_DO = {save_visit: "save_visit", crm_task_save: "crm_task_save", add_note: "add_note"};  // what a proposal may call
const AI = {open: false, msgs: [], busy: false, langs: null};

async function aiLangs() { if (!AI.langs) AI.langs = await api.ai_langs(); return AI.langs; }

/* ------------------------------------------------------------------ assistant */
function aiStart() {
  if ($("#aiFab")) { $("#aiFab").hidden = false; return; }
  const fab = document.createElement("button");
  fab.id = "aiFab"; fab.className = "tb-btn ai-fab"; fab.title = "Помощник (Ctrl+J): спросите о записях, деньгах, пациентах";
  fab.innerHTML = `${AI_ICON}<span class="tb-l">Помощник</span>`;
  fab.onclick = e => { e.stopPropagation(); aiToggle(); };
  $(".topbar").insertBefore(fab, $("#syncCard"));  // in the top bar: never covers the buttons of a window
  const pn = document.createElement("section");
  pn.id = "aiPanel"; pn.className = "ai-panel"; pn.hidden = true;
  pn.setAttribute("aria-label", "Помощник");
  pn.innerHTML = `<header><b>${AI_ICON}Помощник</b><span class="muted" id="aiCtx"></span><button class="x" id="aiClose" title="Закрыть (Esc)">×</button></header>
    <div class="ai-log" id="aiLog"></div>
    <form class="ai-in" id="aiForm"><button class="icon-btn" type="button" id="aiMic" title="Спросить голосом">${MIC}</button>
      <input class="input" id="aiQ" placeholder="Например: кто у меня завтра?" autocomplete="off" maxlength="500">
      <button class="btn" id="aiSend" type="submit">Спросить</button></form>`;
  document.body.appendChild(pn);
  $("#aiClose").onclick = () => aiToggle(false);
  $("#aiForm").onsubmit = e => { e.preventDefault(); const q = $("#aiQ").value.trim(); if (q) aiAsk(q); };
  $("#aiMic").onclick = aiVoice;
  pn.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); aiToggle(false); } });
  document.addEventListener("keydown", e => { if (e.ctrlKey && (e.key === "j" || e.key === "J" || e.code === "KeyJ") && ME) { e.preventDefault(); aiToggle(); } });
}
function aiStop() { const f = $("#aiFab"); if (f) f.hidden = true; aiToggle(false); AI.msgs = []; }
function aiCtx() { return S.view === "patient" && P ? {patient_id: P.id} : {}; }
function aiToggle(on) {
  const pn = $("#aiPanel"); if (!pn) return;
  AI.open = on === undefined ? pn.hidden : on;
  pn.hidden = !AI.open; $("#aiFab").classList.toggle("on", AI.open);
  if (!AI.open) return;
  $("#aiCtx").textContent = S.view === "patient" && P ? `· ${P.name.split(" ").slice(0, 2).join(" ")}` : "";
  if (!AI.msgs.length) aiAsk("", true);
  setTimeout(() => $("#aiQ").focus(), 30);
}
function aiDraw() {
  const log = $("#aiLog");
  log.innerHTML = AI.msgs.map((m, i) => m.me ? `<div class="ai-me">${esc(m.text)}</div>` : aiAnswer(m, i)).join("")
    + (AI.busy ? `<div class="ai-bot"><span class="dict-spin"></span><span class="muted">${esc(AI.busy)}</span></div>` : "");
  log.scrollTop = log.scrollHeight;
  $$("[data-ex]", log).forEach(b => b.onclick = () => aiAsk(b.dataset.ex));
  $$("[data-go]", log).forEach(b => b.onclick = () => aiGo(JSON.parse(b.dataset.go)));
  $$("[data-act]", log).forEach(b => b.onclick = () => aiAct(+b.dataset.act, b.dataset.yes === "1"));
  $$("[data-copy]", log).forEach(b => b.onclick = () => { const m = AI.msgs[+b.dataset.copy]; navigator.clipboard.writeText(m.copy).then(() => toast("Скопировано — вставьте в сообщение"), () => toast("Не удалось скопировать", true)); });
}
function aiAnswer(m, i) {
  const rows = (m.rows || []).map(r => `<button class="ai-row" ${r.go ? `data-go='${esc(JSON.stringify(r.go))}'` : "disabled"}><b>${esc(r.label)}</b>${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</button>`).join("");
  const act = m.action && !m.done ? `<div class="ai-act"><button class="btn small" data-act="${i}" data-yes="1">${esc(m.action.ok || "Да")}</button><button class="btn ghost small" data-act="${i}">Отмена</button></div>`
    : m.done ? `<div class="ai-done ${m.done === "no" ? "muted" : "ok-t"}">${m.done === "no" ? "Отменено" : esc(m.done)}</div>` : "";
  return `<div class="ai-bot${m.denied ? " denied" : ""}">${m.heard ? `<small class="muted">Услышал: «${esc(m.heard)}»</small>` : ""}
    <div class="ai-t">${esc(m.text || "")}</div>
    ${(m.lines || []).length ? `<ul class="ai-lines">${m.lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
    ${m.copy ? `<div class="ai-copy">${esc(m.copy)}</div><button class="linkbtn" data-copy="${i}">Скопировать</button>` : ""}
    ${rows ? `<div class="ai-rows">${rows}</div>` : ""}${act}
    ${(m.examples || []).length ? `<div class="ai-ex">${m.examples.map(e => `<button class="chip" data-ex="${esc(e)}">${esc(e)}</button>`).join("")}</div>
      <small class="muted">${m.ai ? "ИИ включён: можно спрашивать своими словами." : "ИИ выключен — помощник понимает вопросы, похожие на примеры. Включить ИИ: Настройки → «Голос и ИИ»."}</small>` : ""}
    ${m.more ? `<button class="linkbtn" data-go='${esc(JSON.stringify(m.more))}'>Открыть весь список в CRM →</button>` : ""}
    ${m.ai_answer ? `<small class="ai-mark">${AI_ICON}ответ ИИ — проверьте</small>` : ""}</div>`;
}
async function aiAsk(q, greet) {
  if (AI.busy) return;
  if (!greet) { AI.msgs.push({me: true, text: q}); $("#aiQ").value = ""; }
  AI.busy = greet ? "…" : "Думаю…"; aiDraw();
  try { AI.msgs.push(await api.assistant_ask(q, aiCtx())); }
  catch (e) { AI.msgs.push({text: errText(e), denied: true}); }
  AI.busy = false; aiDraw();
}
let aiMicRec = null;
async function aiVoice() {
  const b = $("#aiMic");
  if (aiMicRec) { aiMicRec.stop(); return; }
  try { aiMicRec = await micRecorder(); } catch (e) { return toast(e.message, true); }
  b.classList.add("rec"); b.title = "Нажмите, когда договорите";
  AI.busy = "Слушаю… нажмите микрофон ещё раз, когда договорите"; aiDraw();
  const blob = await aiMicRec.done; aiMicRec = null; b.classList.remove("rec"); b.title = "Спросить голосом";
  if (blob.size < 2000) { AI.busy = false; aiDraw(); return toast("Слишком коротко — скажите вопрос ещё раз", true); }
  AI.busy = "Распознаю вопрос на этом компьютере…"; aiDraw();
  try { const r = await api.assistant_voice(await blobB64(blob), blob.type, aiCtx()); AI.msgs.push({me: true, text: r.heard || "…"}); AI.msgs.push(r); }
  catch (e) { AI.msgs.push({text: errText(e), denied: true}); }
  AI.busy = false; aiDraw();
}
function aiGo(g) {
  aiToggle(false);  // the panel would cover the screen it opens
  if (g.patient) return openPatient(g.patient, S.view === "patient" ? S.prevView : S.view);
  if (g.visit) return openVisit(g.visit);
  if (g.day) { S.day = g.day; return show("schedule"); }
  if (g.view === "marketing" && g.segment) { S.mkTab = "segments"; S.crmSegF = {...g.segment}; S.crmSegTitle = "Список из помощника"; S.crmSegId = null; return show("marketing"); }
  if (g.view) show(g.view);
}
async function aiAct(i, yes) {
  const m = AI.msgs[i], a = m.action;
  if (!yes) { m.done = "no"; return aiDraw(); }
  if (!AI_DO[a.method]) return toast("Это действие помощник не выполняет", true);
  try {
    await api[AI_DO[a.method]](...a.args);
    m.done = a.done || "Готово"; toast(m.done);
    if (a.method === "save_visit" && S.view === "schedule") loadDay();
    if (S.view === "patient" && P && typeof openPatient === "function" && a.method !== "save_visit") openPatient(P.id, S.prevView, S.patientTab);
  } catch (e) { toast(errText(e), true); }
  aiDraw();
}

/* ------------------------------------------------------- texts in seconds */
/** A draft (recommendations, extract, letter to the insurer) in an editable window: copy, translate, save to the card. */
async function aiWriteDoc(kind, pid, opt = {}) {
  let r;
  toast("Готовлю черновик…");
  try { r = await api.ai_write(kind, opt.record_id || null, pid, opt.invoice_id || null, opt.data || null); } catch (e) { return toast(errText(e), true); }
  const title = r.title;
  const L = await aiLangs();
  const el = document.createElement("div");
  el.className = "ask-wrap";
  el.innerHTML = `<div class="ask ai-draft"><div class="ask-ic edit">${AI_ICON}</div>
    <div class="ask-c"><h3>${esc(title)}</h3>
      <p>${r.engine === "ai" ? "Черновик написал ИИ по записи медкарты (без имени и телефона пациента)." : "Черновик составлен программой по записи медкарты."} Проверьте и поправьте текст.${r.ai_error ? `<br><span class="bad-t">ИИ недоступен (${esc(r.ai_error)}) — черновик по правилам.</span>` : ""}</p>
      <textarea class="input" id="adText" rows="11">${esc(r.text)}</textarea>
      <div class="row ai-tr">${L.enabled ? `<label class="muted">Перевести:</label><select class="input sm-sel" id="adLang"><option value="">— язык —</option>${Object.entries(L.langs).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}</select>` : `<span class="muted">Перевод — при включённом ИИ</span>`}</div></div>
    <div class="ask-b">${opt.insert ? `<button class="btn ghost" data-a="ins">${esc(opt.insert)}</button>` : ""}<span style="flex:1"></span><button class="btn ghost" data-a="no">Закрыть</button>
      <button class="btn ghost" data-a="print">Печать</button>${can("docs") ? `<button class="btn" data-a="save">Сохранить в карту</button>` : ""}</div></div>`;
  document.body.appendChild(el);
  let lang = "";
  const close = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), 140); document.removeEventListener("keydown", onKey, true); };
  const onKey = e => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  const html = () => `<h2 style="text-align:center">${esc(title)}${lang ? ` (${esc(L.langs[lang])})` : ""}</h2>` +
    $("#adText", el).value.split(/\n{2,}/).map(p => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
  $('[data-a="no"]', el).onclick = close;
  $('[data-a="print"]', el).onclick = () => printDoc(html());
  const sv = $('[data-a="save"]', el); if (sv) sv.onclick = async () => {
    try { await api.save_document({patient_id: pid, template_id: "", title: title + (lang ? ` (${L.langs[lang]})` : ""), html: html(), data: {ai: r.engine === "ai", kind}});
      close(); toast("Документ сохранён в карту пациента"); if (typeof afterChange === "function") afterChange(); } catch (e) { toast(errText(e), true); } };
  const ins = $('[data-a="ins"]', el); if (ins) ins.onclick = () => { opt.onInsert($("#adText", el).value); close(); };
  const ls = $("#adLang", el); if (ls) ls.onchange = async () => {
    if (!ls.value) return;
    ls.disabled = true; toast("Перевожу…");
    try { const t = await api.ai_translate($("#adText", el).value.split("\n"), ls.value, pid); $("#adText", el).value = t.lines.join("\n"); lang = ls.value; toast(`Переведено: ${t.title}`); }
    catch (e) { toast(errText(e), true); ls.value = ""; }
    ls.disabled = false;
  };
}

/** Translate a document page in place: every text piece keeps its place in the layout. → language title or "" */
async function aiTranslateEl(page, pid, lang) {
  const nodes = [], walk = document.createTreeWalker(page, NodeFilter.SHOW_TEXT, {acceptNode: n => /[A-Za-zА-Яа-яЁё]/.test(n.nodeValue) ? 1 : 2});
  while (walk.nextNode()) nodes.push(walk.currentNode);
  if (!nodes.length) return "";
  toast("Перевожу документ… на этом компьютере это может занять минуту");
  const r = await api.ai_translate(nodes.map(n => n.nodeValue.replace(/\s+/g, " ").trim()), lang, pid);
  nodes.forEach((n, i) => { const lead = /^\s/.test(n.nodeValue) ? " " : "", tail = /\s$/.test(n.nodeValue) ? " " : ""; n.nodeValue = lead + r.lines[i] + tail; });
  return r.title;
}
/** «Перевести ▾» next to a document: pick(langTitle) after the page is translated. */
async function aiTranslateMenu(btn, page, pid, done) {
  const L = await aiLangs();
  if (!L.enabled) return toast("Перевод делает ИИ — включите его: Настройки → «Голос и ИИ»", true);
  recDocMenu(btn, Object.entries(L.langs), async lang => {
    btn.disabled = true;
    try { const t = await aiTranslateEl(page, pid, lang); if (t) { toast(`Документ переведён: ${t}`); done(t); } }
    catch (e) { toast(errText(e), true); }
    btn.disabled = false;
  });
}

/* ------------------------------------------------- the patient card (hooks) */
async function aiPatientCard(p, tab) {
  const card = $("#patientCard");
  let al = $(".alerts", card);
  const pill = (cls, html, title) => { if (!al) { al = document.createElement("div"); al.className = "alerts"; $(".phead2", card).after(al); }
    const b = document.createElement("button"); b.className = "alert ai-alert " + cls; b.innerHTML = html; b.title = title || ""; al.appendChild(b); return b; };
  const c = p.consent_recording;
  if (c && c.active) pill("ok", `${MIC}Согласие на запись приёма · ${fmtDT(c.given_at).slice(0, 10)}`, `${c.method_text}, отметил(а) ${c.given_by || "—"}`).onclick = async () => {
    if (!canAny("medcard_edit", "patients_edit")) return;
    if (await ask("Отозвать согласие на запись приёма?", {danger: true, ok: "Отозвать", text: `Дано ${fmtDT(c.given_at)}: ${c.method_text}. После отзыва приём этого пациента записывать нельзя.`})) {
      await api.consent_revoke(p.id); openPatient(p.id, S.prevView, S.patientTab); }
  };
  if (canAny("medcard_view", "patients_view")) {
    try {
      const mc = await api.medcheck_patient(p.id);
      if (P !== p) return;
      if (mc.items.length) pill(mc.warn ? "w" : "info", `${ADV_ICON_AI}Проверка карты: ${mc.warn ? `${mc.warn} ${plural(mc.warn, "замечание", "замечания", "замечаний")}` : "подсказки"}`,
        "Чего не хватает для проверки и страховой").onclick = () => aiMedcheck(p, mc);
    } catch (e) { /* not critical */ }
  }
  if (tab === "notes" && canAny("patients_edit", "marketing")) {
    const add = $("#noteAdd", card);
    if (add) { const b = document.createElement("button"); b.className = "btn ghost"; b.innerHTML = `${MIC}Голосовая заметка`; b.style.marginLeft = "8px"; add.after(b); b.onclick = () => aiVoiceNote(p, b); }
  }
  if (tab === "docs" && can("docs")) {
    const tools = $(".tab-tools", card);
    if (tools && p.records.length) {
      const b = document.createElement("button"); b.className = "btn ghost small"; b.innerHTML = `${AI_ICON}Написать за секунды ▾`;
      tools.insertBefore(b, tools.children[1] || null);
      b.onclick = async e => { e.stopPropagation(); const L = await aiLangs(); recDocMenu(b, [["recommendations", "Рекомендации пациенту простыми словами"], ["explain", "Объяснение диагноза и лечения"], ["extract", "Выписка из медкарты"], ["insurance", "Письмо в страховую компанию"]].filter(([k]) => L.kinds[k]), k => aiWriteDoc(k, p.id)); };
    }
  }
}
const ADV_ICON_AI = '<svg viewBox="0 0 24 24"><path d="M9 4.5h6M9.5 3h5v3h-5zM6.5 5.5h11v15h-11z"/><path d="m9 13 2 2 4-4"/></svg>';
function aiMedcheck(p, mc) {
  const box = modal(`<div class="m-h"><h3>Проверка карты · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Чего не хватает для проверки качества и для страховой компании. Проверяют простые правила программы — без ИИ.</p>
      <ul class="advice mc-list">${mc.items.map((x, i) => `<li class="adv-${x.level === "warn" ? "warn" : "info"}" data-i="${i}" role="button" tabindex="0"><span class="adv-ic">${x.level === "warn" ? ADV_ICON.warn : ADV_ICON.info}</span><span>${esc(x.text)}</span></li>`).join("")}</ul></div>
    <div class="m-f"><span class="muted">Щёлкните по строке, чтобы исправить</span><button class="btn ghost" data-close>Закрыть</button></div>`);
  $$("[data-i]", box).forEach(li => li.onclick = () => {
    const g = mc.items[+li.dataset.i].go || {}; closeModal();
    if (g.record) openRecord({patient_id: p.id, id: g.record});
    else if (g.invoice) openInvoice({patient_id: p.id, id: g.invoice});
    else if (g.doc) openDocFill({patient_id: p.id, template_id: g.doc});
    else if (g.anketa) { if (typeof openQuestionnaire === "function") openQuestionnaire(p); }
  });
}
async function aiVoiceNote(p, btn) {
  if (btn._rec) { btn._rec.stop(); return; }
  try { btn._rec = await micRecorder(); } catch (e) { return toast(e.message, true); }
  btn.classList.add("danger-fill"); btn.innerHTML = `${MIC}Готово`;
  const blob = await btn._rec.done; btn._rec = null; btn.classList.remove("danger-fill"); btn.innerHTML = `${MIC}Голосовая заметка`;
  if (blob.size < 2000) return toast("Запись слишком короткая", true);
  btn.disabled = true; toast("Распознаю заметку на этом компьютере…");
  let r;
  try { r = await api.voice_note(await blobB64(blob), blob.type); } catch (e) { btn.disabled = false; return toast(errText(e), true); }
  btn.disabled = false;
  if (!r.text) return toast("Речь не распознана — говорите ближе к микрофону", true);
  const ta = $("#noteText"); if (ta) { ta.value = (ta.value.trim() ? ta.value.trim() + " " : "") + r.text; ta.focus(); }
  if (r.task && can("marketing") && await ask("Поставить задачу в CRM?", {ok: "Поставить", text: `«${r.task.title}» — ${fmtDate(r.task.due)}. Задача появится у вас в CRM → «Задачи».`})) {
    try { await api.crm_task_save({title: r.task.title, patient_id: p.id, due: r.task.due, assignee: ME.login, comment: "Голосовая заметка"}); toast("Задача поставлена"); }
    catch (e) { toast(errText(e), true); }
  } else toast("Текст заметки вставлен — проверьте и нажмите «Добавить примечание»");
}

/* ------------------------------------------------------- the record form (hooks) */
/** o = {box, st, patient_id, drawTeeth, form()} — voice tooth chart, live check, a memo for the patient. */
function aiRecordTools(o) {
  const {box, st} = o;
  st.source = st.source || new Set();
  const head = $("#rTeeth", box).previousElementSibling;
  const vb = document.createElement("button"); vb.className = "linkbtn ai-vf"; vb.type = "button"; vb.innerHTML = `${MIC}Формула голосом`;
  vb.title = "Скажите: «восемнадцать отсутствует, семнадцать коронка, шестнадцать кариес»"; head.appendChild(vb);
  vb.onclick = async () => {
    if (vb._rec) { vb._rec.stop(); return; }
    try { vb._rec = await micRecorder(); } catch (e) { return toast(e.message, true); }
    vb.classList.add("rec"); vb.innerHTML = `<i class="dict-dot"></i>Говорите зубы и состояния, затем нажмите здесь`;
    const blob = await vb._rec.done; vb._rec = null; vb.classList.remove("rec"); vb.innerHTML = `${MIC}Формула голосом`;
    if (blob.size < 2000) return toast("Запись слишком короткая", true);
    vb.disabled = true; toast("Распознаю формулу на этом компьютере…");
    let r;
    try { r = await api.teeth_voice(await blobB64(blob), blob.type); } catch (e) { vb.disabled = false; return toast(errText(e), true); }
    vb.disabled = false;
    const list = Object.entries(r.teeth);
    if (!list.length) return toast(`Не нашёл зубов и состояний в «${r.text || "…"}». Говорите: «тридцать шесть пломба»`, true);
    if (!(await ask("Отметить на формуле?", {ok: "Отметить", text: list.map(([t, s]) => `${t} — ${s}`).join("\n") + `\n\nУслышано: «${r.text}»`}))) return;
    for (const [t, s] of list) st.teeth[t] = s;
    st.source.add("voice_formula"); o.drawTeeth(); toast(`Отмечено зубов: ${list.length} — проверьте и сохраните`);
  };
  // a memo for the patient in plain words from what is written now
  const recLbl = $("#rf_recommendations", box).closest(".rf").querySelector(".rf-h");
  const mb = document.createElement("button"); mb.className = "linkbtn ai-memo"; mb.type = "button"; mb.innerHTML = `${AI_ICON}Памятка пациенту`;
  mb.title = "Рекомендации простыми словами по этой записи — распечатать, сохранить или вставить"; recLbl.appendChild(mb);
  mb.onclick = () => aiWriteDoc("recommendations", o.patient_id, {data: o.form(), insert: "Вставить в «Рекомендации»",
    onInsert: t => { const ta = $("#rf_recommendations", box); ta.value = t.replace(/^—\s*/gm, "").replace(/\n+/g, " ").trim(); st.source.add("ai"); }});
  // live check of what is missing (14.4)
  const strip = document.createElement("div"); strip.className = "mc-strip"; strip.hidden = true;
  $(".m-f", box).before(strip);
  let t;
  const check = () => { clearTimeout(t); t = setTimeout(async () => {
    try {
      const items = await api.medcheck_record(o.form());
      const warn = items.filter(x => x.level === "warn");
      strip.hidden = !items.length;
      strip.className = "mc-strip" + (warn.length ? " w" : "");
      strip.innerHTML = items.length ? `${ADV_ICON_AI}<span><b>Проверка записи:</b> ${items.map(x => esc(x.short || x.text)).join(" · ")}</span>` : "";
      strip.title = items.map(x => x.text).join("\n");
    } catch (e) { strip.hidden = true; }
  }, 700); };
  box.addEventListener("input", check); box.addEventListener("click", check);
  check();
}

/* ----------------------------------------------- consent to record the visit */
/** → true when the patient agreed (now or before), false when the recording must not start. */
async function aiConsent(pid) {
  if (!pid) return true;
  let c = null;
  try { c = await api.consent_get(pid); } catch (e) { return true; }
  if (c && c.active) return true;
  return new Promise(resolve => {
    const el = document.createElement("div");
    el.className = "ask-wrap";
    el.innerHTML = `<div class="ask"><div class="ask-ic question">${MIC}</div>
      <div class="ask-c"><h3>Согласие пациента на запись приёма</h3>
        <p>Запишите приём, только если пациент согласен. Звук распознаётся на этом компьютере и удаляется сразу после распознавания.
        Согласие сохранится в карте — в следующий раз программа не спросит.</p>
        <div class="consent-opts"><button class="btn" data-m="verbal">Пациент согласен (устно)</button><button class="btn ghost" data-m="paper">Подписал согласие на бумаге</button>
          <button class="linkbtn" data-m="print">Распечатать бланк согласия</button></div></div>
      <div class="ask-b"><span style="flex:1"></span><button class="btn ghost" data-m="no">Не записывать</button></div></div>`;
    document.body.appendChild(el);
    const done = v => { el.classList.add("leaving"); setTimeout(() => el.remove(), 140); resolve(v); };
    $$("[data-m]", el).forEach(b => b.onclick = async () => {
      const m = b.dataset.m;
      if (m === "no") return done(false);
      if (m === "print") {
        try { const [tpl, ctx] = await Promise.all([api.templates("document"), api.doc_context(pid, null, null, null, null)]);
          const t = tpl.find(x => x.id === "doc_consent_recording"); if (t) printDoc(renderDoc(t.body, ctx, [])); } catch (e) { toast(errText(e), true); }
        return;
      }
      try { await api.consent_give(pid, m, ""); toast("Согласие отмечено в карте"); done(true); } catch (e) { toast(errText(e), true); }
    });
  });
}

/* ---------------------------------------------------- the director's week */
async function aiWeeklyCard(col) {
  if (!col || !can("reports")) return;
  const card = document.createElement("div"); card.className = "pbody ai-week";
  const first = col.querySelector(".pbody");  // under «На что обратить внимание»
  if (first) first.after(card); else col.prepend(card);
  const draw = w => {
    card.innerHTML = `<div class="pb-head"><b>${AI_ICON}Сводка за неделю</b><span class="muted">${esc(w.title.replace(/^Неделя /, ""))}</span></div>
      ${w.ai_text ? `<div class="ai-week-t">${esc(w.ai_text)}</div><small class="ai-mark">${AI_ICON}пересказ ИИ — цифры ниже</small>` : ""}
      <ul class="ai-lines">${w.lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul>
      <div class="row">${w.ai ? `<button class="linkbtn" id="awAi">${w.ai_text ? "Пересказать заново" : "Пересказать коротко (ИИ)"}</button>` : ""}<button class="linkbtn" id="awPrint">Печать</button></div>
      ${w.ai_error ? `<div class="bad-t">${esc(w.ai_error)}</div>` : ""}`;
    const b = $("#awAi", card); if (b) b.onclick = async () => { b.disabled = true; b.textContent = "ИИ пишет…"; try { draw(await api.director_weekly(null, true)); } catch (e) { toast(errText(e), true); b.disabled = false; } };
    $("#awPrint", card).onclick = () => { $("#printArea").innerHTML = `<h2>Сводка за неделю</h2><p>${esc(w.title)}</p>${w.ai_text ? `<p>${esc(w.ai_text)}</p>` : ""}<ul>${w.lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul>`; window.print(); };
  };
  card.innerHTML = `<div class="pb-head"><b>${AI_ICON}Сводка за неделю</b></div><div class="scan"><i></i>Считаю…</div>`;
  try { draw(await api.director_weekly()); } catch (e) { card.remove(); }
}

/* --------------------------------- settings: the clinic's own local model and its check */
function aiLocalExtra(box, st, ai) {
  const ready = st.installed || st.external, cu = st.custom || {}, used = ai.provider === "local" && ai.model === cu.name && cu.ready;
  const ev = st.eval, busyEval = String(st.task || "").startsWith("eval:");
  const div = document.createElement("div"); div.className = "ai-local-extra";
  div.innerHTML = `<div class="la-step"><div class="grow"><b>3. Модель клиники «Dental Desk»</b>
      <small class="muted">${cu.base ? `строится на скачанной модели ${esc(cu.base)}: инструкции программы, стоматологические термины и настройки, проверенные на задачах программы — за несколько секунд, без скачивания` : "сначала скачайте модель выше"}</small></div>
      ${used ? '<span class="pill st-ok">используется</span>' : cu.ready ? `<button class="btn ghost small" data-lause="${esc(cu.name)}">Использовать</button>`
        : `<button class="btn small" id="laCustom" ${cu.base && ready && !st.task ? "" : "disabled"}>Подготовить</button>`}</div>
    <div class="la-step"><div class="grow"><b>4. Проверка качества</b><small class="muted">11 рабочих задач программы: диктовка в медкарту, памятка, объяснение, вариант плана, перевод, вопросы помощнику. Оценка точности, русского языка и скорости.</small></div>
      ${busyEval ? `<div class="la-prog"><div class="vm-bar"><i style="width:${st.progress}%"></i></div><small>${st.progress}%</small></div>`
        : `<button class="btn ghost small" id="laEval" ${ai.provider === "local" && ai.model && !st.task ? "" : "disabled title=\"Выберите модель на этом компьютере\""}>Проверить${ai.model ? " " + esc(ai.model) : ""}</button>`}</div>
    ${ev ? `<div class="ai-eval"><div class="ae-sum"><span>Модель <b>${esc(ev.model)}</b> · ${esc(ev.at)}</span><span>Точность <b>${ev.accuracy} %</b></span><span>Русский язык <b>${ev.russian} %</b></span>
        <span>Ответ в среднем <b>${String(ev.seconds).replace(".", ",")} с</b>${ev.tok_s ? ` · ${String(ev.tok_s).replace(".", ",")} слов-токенов/с` : ""}</span><span>Итог <b>${ev.score} из 100</b></span></div>
      <details><summary>Подробно по задачам</summary><table class="tbl compact"><thead><tr><th>Задача</th><th class="num">Точность</th><th class="num">Русский</th><th class="num">Время</th></tr></thead><tbody>${
        ev.cases.map(c => `<tr title="${esc(c.error || c.answer)}"><td>${esc(c.title)}</td><td class="num ${c.accuracy < 0.6 ? "bad-t" : ""}">${Math.round(c.accuracy * 100)} %</td><td class="num">${c.russian == null ? "—" : Math.round(c.russian * 100) + " %"}</td><td class="num">${String(c.seconds).replace(".", ",")} с</td></tr>`).join("")}</tbody></table></details></div>` : ""}`;
  const hint = box.querySelector(":scope > p.hint");
  if (hint) box.insertBefore(div, hint); else box.appendChild(div);
  const mk = $("#laCustom", div); if (mk) mk.onclick = async () => { mk.disabled = true; try { await api.local_ai_custom(); toast("Модель клиники готова и включена"); loadVoiceSettings(); } catch (e) { toast(errText(e), true); mk.disabled = false; } };
  const ue = $("[data-lause]", div); if (ue) ue.onclick = async () => { await api.local_ai_use(ue.dataset.lause); loadVoiceSettings(); };
  const evb = $("#laEval", div); if (evb) evb.onclick = async () => { try { await api.local_ai_eval(ai.model); loadLocalAi(); } catch (e) { toast(errText(e), true); } };
}
