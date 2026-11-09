"use strict";
/* Dictation in the medical-record form: record → recognize on this computer → review → insert. */
const MIC = '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/></svg>';

function dictationBar() {
  return `<div class="dict-bar" id="dictBar">
    <button class="btn dict-btn" id="dictGo" type="button">${MIC}<span>Диктовать</span></button>
    <button class="btn ghost dict-btn" id="dictVisit" type="button" title="Запишите весь приём: программа узнает врача и ассистента по голосу, остальное — слова пациента">${MIC}<span>Запись приёма</span></button>
    <button class="btn ghost small" id="dictPause" type="button" hidden>Пауза</button>
    <span class="dict-state muted" id="dictState">Продиктуйте приём или запишите весь разговор с пациентом — программа разложит его по полям медкарты</span>
  </div>`;
}

/** Microphone → one recording. opts.bitrate keeps long recordings small. */
async function micRecorder(opts = {}) {
  if (!navigator.mediaDevices || !window.MediaRecorder)
    throw new Error("Микрофон недоступен в этом окне. Перезапустите программу — после подключения к серверу доступ к микрофону включается при следующем запуске.");
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}}); }
  catch (e) { throw new Error("Нет доступа к микрофону. Проверьте, что микрофон подключён и разрешён для программы (Параметры Windows → Конфиденциальность → Микрофон)."); }
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(m => MediaRecorder.isTypeSupported(m)) || "";
  const rec = new MediaRecorder(stream, {...(mime ? {mimeType: mime} : {}), ...(opts.bitrate ? {audioBitsPerSecond: opts.bitrate} : {})});
  const chunks = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  const done = new Promise(ok => { rec.onstop = () => { stream.getTracks().forEach(t => t.stop()); ok(new Blob(chunks, {type: rec.mimeType || "audio/webm"})); }; });
  rec.start(1000);
  return {rec, done, stop: () => { if (rec.state !== "inactive") rec.stop(); return done; }};
}
const blobB64 = blob => new Promise((ok, fail) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = fail; r.readAsDataURL(blob); });

/** apply({fields, diagnoses, teeth}) puts the result into the form. opts.doctor() — the record's doctor id. */
function attachDictation(box, patientId, apply, opts = {}) {
  const btnD = $("#dictGo", box), btnV = $("#dictVisit", box), btnP = $("#dictPause", box), state = $("#dictState", box);
  const bar = box.querySelector(".dict-bar");
  let cur = null, timer = null;
  const setState = (html, cls = "") => { state.innerHTML = html; state.className = "dict-state " + cls; };
  const MODES = {
    dictation: {btn: btnD, idle: "Диктовать", busy: "Готово", max: 15 * 60, bitrate: 0,
      tip: "говорите, затем нажмите «Готово»", wait: "Распознаю речь на этом компьютере… обычно это быстрее, чем длилась диктовка"},
    visit: {btn: btnV, idle: "Запись приёма", busy: "Закончить приём", max: 60 * 60, bitrate: 24000,
      tip: "ведите приём как обычно, в конце нажмите «Закончить приём»", wait: "Распознаю разговор и узнаю голоса на этом компьютере… это займёт несколько минут"},
  };

  const start = async mode => {
    const M = MODES[mode];
    if (cur) { if (cur.mode === mode) cur.stop(); return; }
    let st;
    try { st = await api.speech_status(); } catch (e) { return setState(esc(errText(e)), "bad-t"); }
    if (!st.engine) return setState("Модуль распознавания речи не установлен в этой сборке программы.", "bad-t");
    if (!Object.values(st.models).some(m => m.ready)) {
      setState(can("settings") ? `Модель распознавания речи ещё не скачана. <button class="linkbtn" id="dictSet" type="button">Открыть настройки</button>`
        : "Модель распознавания речи ещё не скачана — попросите директора скачать её в Настройках.", "bad-t");
      const l = $("#dictSet", box); if (l) l.onclick = () => { closeModal(); show("settings"); if (typeof settingsGo === "function") settingsGo("ai"); };
      return;
    }
    // 13.7: a visit is recorded only with the patient's consent (noted once, kept in the card)
    if (mode === "visit" && typeof aiConsent === "function" && !(await aiConsent(patientId)))
      return setState("Приём не записывается: пациент не дал согласие. Можно продиктовать запись после приёма — кнопка «Диктовать».", "bad-t");
    let mic;
    try { mic = await micRecorder({bitrate: M.bitrate}); } catch (e) { return setState(esc(e.message), "bad-t"); }
    cur = {mode, ...mic};
    let t0 = Date.now(), paused = 0, pausedAt = 0;
    bar.classList.add("rec");
    M.btn.querySelector("span").textContent = M.busy;
    (mode === "visit" ? btnD : btnV).disabled = true;
    btnP.hidden = mode !== "visit"; btnP.textContent = "Пауза";
    btnP.onclick = () => {
      if (mic.rec.state === "recording") { mic.rec.pause(); pausedAt = Date.now(); btnP.textContent = "Продолжить"; bar.classList.add("paused"); }
      else if (mic.rec.state === "paused") { mic.rec.resume(); paused += Date.now() - pausedAt; btnP.textContent = "Пауза"; bar.classList.remove("paused"); }
      tick();
    };
    const tick = () => {
      const s = Math.floor((Date.now() - t0 - paused - (mic.rec.state === "paused" ? Date.now() - pausedAt : 0)) / 1000);
      setState(mic.rec.state === "paused" ? `Пауза ${Math.floor(s / 60)}:${pad(s % 60)} — нажмите «Продолжить»`
        : `<i class="dict-dot"></i>Идёт запись ${Math.floor(s / 60)}:${pad(s % 60)} — ${M.tip}`, "rec-t");
      if (s >= M.max) mic.stop();
    };
    tick(); timer = setInterval(tick, 500);
    const blob = await mic.done;
    clearInterval(timer); cur = null;
    bar.classList.remove("rec", "paused"); btnP.hidden = true;
    M.btn.querySelector("span").textContent = M.idle;
    btnD.disabled = btnV.disabled = true;
    try {
      if (blob.size < 2000) return setState("Запись слишком короткая — попробуйте ещё раз", "bad-t");
      setState(`<span class="dict-spin"></span>${M.wait}`);
      const res = await api.dictate(await blobB64(blob), blob.type, patientId, mode, opts.doctor ? opts.doctor() : "");
      if (!(res.text || "").trim()) return setState("Речь не распознана. Говорите ближе к микрофону и попробуйте ещё раз.", "bad-t");
      const who = res.speakers && res.speakers.length ? ` · узнаны: ${res.speakers.map(esc).join(", ")}` : "";
      setState(`Распознано за ${res.seconds} с${res.engine === "ai" ? " · разобрано ИИ" : ""}${who}. Проверьте и вставьте в медкарту.`, "ok-t");
      if (res.auto_insert && !res.ai_error) {  // straight into the fields; the doctor still checks and saves
        const r = {...res};
        if (!Object.keys(r.fields).some(k => k !== "diagnosis_text") && r.text) r.fields = {objective: r.text};
        apply(r);
        setState(`Распознано за ${res.seconds} с${res.engine === "ai" ? " и оформлено ИИ" : ""}${who} — вставлено в поля, проверьте и сохраните. <button class="linkbtn" id="dictShow" type="button">показать распознанный текст</button>`, "ok-t");
        const sh = $("#dictShow", box); if (sh) sh.onclick = () => reviewDictation(res, patientId, () => toast("Уже вставлено в медкарту"));
      } else reviewDictation(res, patientId, apply);
    } catch (e) { setState(esc(errText(e)), "bad-t"); }
    finally { btnD.disabled = btnV.disabled = false; }
  };
  btnD.onclick = () => start("dictation");
  btnV.onclick = () => start("visit");
}

/* review layer: editable transcript + what will be filled; nothing changes until «Вставить» */
function reviewDictation(res, patientId, apply) {
  const NAMES = {complaints: "Жалобы", anamnesis: "Анамнез", objective: "Объективно", treatment: "Лечение", recommendations: "Рекомендации", next_visit: "Следующий визит"};
  const el = document.createElement("div");
  el.className = "ask-wrap";
  const draw = r => `<div class="ask dict-review">
      <div class="ask-ic edit">${MIC}</div>
      <div class="ask-c"><h3>${r.mode === "visit" ? "Проверьте запись приёма" : "Проверьте диктовку"}</h3>
        <p>Можно поправить текст и нажать «Разобрать заново». В медкарту ничего не попадёт, пока вы не нажмёте «Вставить».${r.ai_error ? `<br><span class="bad-t">ИИ недоступен (${esc(r.ai_error)}), разобрано правилами программы.</span>` : ""}${r.voice_note ? `<br><span class="muted">${esc(r.voice_note)}</span>` : ""}</p>
        <textarea class="input dict-text" id="dtText" rows="${r.mode === "visit" ? 9 : 4}">${esc(r.text)}</textarea>
        <div class="dict-prev">
          ${Object.entries(r.fields).filter(([k]) => NAMES[k]).map(([k, v]) => `<div><b>${NAMES[k]}</b><span>${esc(v)}</span></div>`).join("") || '<div class="muted">Разделы не найдены — текст попадёт в «Объективно».</div>'}
          ${r.diagnoses.length ? `<div><b>Диагноз</b><span>${r.diagnoses.map(d => `${esc(d.code)} ${esc(d.title)}${d.tooth ? " · зуб " + esc(d.tooth) : ""}`).join("<br>")}</span></div>` : ""}
          ${Object.keys(r.teeth).length ? `<div><b>Формула</b><span>${Object.entries(r.teeth).map(([t, s]) => `${esc(t)} — ${esc(s)}`).join(", ")}</span></div>` : ""}
        </div></div>
      <div class="ask-b"><button class="btn ghost" data-a="re">Разобрать заново</button><span style="flex:1"></span><button class="btn ghost" data-a="no">Отмена</button><button class="btn" data-a="yes">Вставить в медкарту</button></div></div>`;
  let cur = res;
  el.innerHTML = draw(cur);
  document.body.appendChild(el);
  const close = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), 140); document.removeEventListener("keydown", onKey, true); };
  const onKey = e => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  const bind = () => {
    $('[data-a="no"]', el).onclick = close;
    $('[data-a="yes"]', el).onclick = () => {
      const r = {...cur};
      if (!Object.keys(r.fields).some(k => NAMES[k]) && r.text) r.fields = {objective: r.text};
      apply(r); close(); toast("Диктовка вставлена — проверьте и сохраните запись");
    };
    $('[data-a="re"]', el).onclick = async () => {
      const b = $('[data-a="re"]', el); b.disabled = true;
      try { cur = {...cur, ...(await api.parse_dictation($("#dtText", el).value, patientId))}; el.innerHTML = draw(cur); bind(); }
      catch (e) { toast(errText(e), true); b.disabled = false; }
    };
  };
  bind();
}

/* ---------------------------------------------------------------- settings: voice and AI */
let speechPoll = null;
async function loadVoiceSettings() {
  const box = $("#voiceSettings"); if (!box) return;
  const st = await api.speech_status();
  const ai = st.ai;
  box.innerHTML = `${st.engine ? "" : '<div class="warn-line bad">Модуль распознавания речи не установлен в этой сборке программы.</div>'}
    <div class="voice-models">${Object.entries(st.models).map(([k, m]) => `<div class="vm ${st.size === k && m.ready ? "on" : ""}">
      <div><b>${k === "small" ? "Стандартная" : k === "base" ? "Быстрая" : "Точная"}</b><small class="muted">${esc(m.title)} · ≈${m.mb >= 1000 ? (m.mb / 1000).toFixed(1) + " ГБ" : m.mb + " МБ"}</small></div>
      ${st.downloading === k ? `<div class="vm-bar"><i style="width:${st.progress}%"></i></div><small>${st.progress}%</small>`
        : m.ready ? (st.size === k ? '<span class="pill st-ok">используется</span>' : `<button class="btn ghost small" data-use="${k}">Использовать</button>`)
        : `<button class="btn ghost small" data-dl="${k}" ${st.downloading ? "disabled" : ""}>Скачать</button>`}</div>`).join("")}</div>
    ${st.error ? `<div class="warn-line bad">${esc(st.error)}</div>` : ""}
    <p class="hint">Модель скачивается один раз на каждый компьютер и дальше работает без интернета. Можно скопировать папку <code>${esc(st.folder)}</code> с одного ноутбука на другой флешкой.</p>
    <h4 class="sub-h" style="margin-top:14px">Голоса сотрудников: кто говорит на записи приёма</h4>
    <div id="voiceStaff"></div>
    <h4 class="sub-h" style="margin-top:14px">ИИ: заполнение медкарты по диктовке (необязательно)</h4>
    <p class="hint">Без ИИ программа сама раскладывает диктовку по полям. С ИИ текст разбирается по разделам медкарты и оформляется медицинским языком, как в карте 043/у. Перед отправкой имя и телефон пациента убираются, звук никуда не отправляется — только распознанный текст.</p>
    <label class="switch-row"><input type="checkbox" id="aiOn" ${ai.enabled ? "checked" : ""}><span class="sw"></span>Заполнять медкарту с помощью ИИ</label>
    <div class="form">
      <label>Сервис<select class="input" id="aiProv">${Object.entries(ai.providers).map(([k, p]) => `<option value="${k}" ${k === ai.provider ? "selected" : ""}>${esc(p.title)}</option>`).join("")}</select></label>
      <label class="ai-f ai-models">Модель<select class="input" id="aiModelSel"></select></label>
      <label class="ai-f ai-openai">Модель<input class="input" id="aiModel" value="${esc(ai.model)}" placeholder="например qwen2.5:7b"></label>
      <label class="ai-f ai-openai wide">Адрес сервиса<input class="input" id="aiUrl" value="${esc(ai.base_url)}" placeholder="например http://127.0.0.1:11434/v1"></label>
      <label class="ai-f ai-yandex">Каталог Yandex Cloud (folder id)<input class="input" id="aiFolder" value="${esc(ai.folder)}" placeholder="b1g…"></label>
      <label class="ai-f ai-gigachat">Тип доступа<select class="input" id="aiScope">${[["GIGACHAT_API_CORP", "Юрлицо или ИП — оплата по факту"], ["GIGACHAT_API_B2B", "Юрлицо или ИП — пакеты токенов"], ["GIGACHAT_API_PERS", "Физлицо"]].map(([k, t]) => `<option value="${k}" ${k === ai.scope ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <label class="wide" id="aiKeyRow"><span id="aiKeyLbl">Ключ</span><input class="input" id="aiKey" type="password" placeholder="${ai.has_key ? "сохранён — оставьте пустым" : ""}" autocomplete="new-password"></label>
    </div>
    <div class="ai-f ai-local" id="aiLocal"></div>
    <div class="hint ai-help" id="aiHelp"></div>
    <label class="switch-row"><input type="checkbox" id="aiStyle" ${ai.style ? "checked" : ""}><span class="sw"></span>Оформлять текст медицинским языком (как в карте 043/у)</label>
    <label class="switch-row"><input type="checkbox" id="aiAuto" ${ai.auto_insert ? "checked" : ""}><span class="sw"></span>Сразу вставлять в поля медкарты, без окна проверки (врач всё равно проверяет и сохраняет)</label>
    <div class="net-box" id="aiCost"></div>
    <div class="row"><button class="btn" id="aiSave">Сохранить</button><button class="btn ghost" id="aiTest">Проверить ИИ</button><span class="msg" id="aiMsg"></span></div>`;
  $$("[data-dl]", box).forEach(b => b.onclick = async () => { try { await api.speech_download(b.dataset.dl); loadVoiceSettings(); } catch (e) { toast(errText(e), true); } });
  $$("[data-use]", box).forEach(b => b.onclick = async () => { await api.speech_use(b.dataset.use); loadVoiceSettings(); });
  const msgA = (t, ok) => { $("#aiMsg").textContent = t; $("#aiMsg").className = "msg " + (ok ? "ok" : "bad"); };
  const HELP = {
    yandex: "Яндекс: в консоли Yandex Cloud создайте сервисный аккаунт с ролью «ai.languageModels.user», выпустите для него API-ключ и вставьте сюда. Идентификатор каталога — на главной странице каталога. Оплата по факту.",
    gigachat: "Сбер: в личном кабинете developers.sber.ru создайте проект GigaChat API и скопируйте «Ключ авторизации». В Windows должен быть установлен сертификат «Russian Trusted Root CA» (Минцифры, есть на Госуслугах). Для юрлиц минимальный платёж 600 ₽ в месяц, если пользовались.",
    local: "Программа сама скачивает Ollama и открытую модель (Qwen или Gemma) и запускает её на этом компьютере, пока открыта программа. Текст никуда не отправляется, платить не нужно. Хватает компьютера с 8 ГБ памяти; видеокарта ускоряет работу, без неё медленнее.",
    openai: "Любой сервис с OpenAI-совместимым API или своя модель на компьютере клиники (например, Ollama: адрес http://127.0.0.1:11434/v1). Для медицинских данных выбирайте сервис с серверами в вашей стране."};
  const syncAi = () => {
    const prov = $("#aiProv").value, p = ai.providers[prov];
    $$(".ai-f", box).forEach(el => el.hidden = !(el.classList.contains("ai-" + prov) || (el.classList.contains("ai-models") && prov !== "openai" && prov !== "local")));
    $("#aiKeyRow").hidden = prov === "local";
    if (prov === "local") loadLocalAi();
    if (prov !== "openai" && prov !== "local") $("#aiModelSel").innerHTML = Object.entries(p.models).map(([k, t]) => `<option value="${k}" ${k === ai.model ? "selected" : ""}>${esc(t)}</option>`).join("");
    $("#aiKeyLbl").textContent = {yandex: "API-ключ сервисного аккаунта", gigachat: "Ключ авторизации GigaChat", openai: "Ключ API (если нужен)", local: ""}[prov];
    $("#aiHelp").textContent = HELP[prov];
    const c = ai.cost && prov === ai.provider ? ai.cost : null;
    $("#aiCost").innerHTML = c && c.per_dictation !== undefined ? `Примерная стоимость: <b>${c.per_1000_tokens} ₽</b> за 1000 токенов, одна диктовка ≈ <b>${c.per_dictation} ₽</b>, 10 врачей × 15 приёмов в день ≈ <b>${c.per_month_10_doctors.toLocaleString("ru-RU")} ₽</b> в месяц. Цены — с сайтов Яндекса и Сбера на октябрь 2026, сверяйте в кабинете.`
      : prov === "local" ? "Бесплатно: модель работает на этом компьютере, без интернета. Разбор одного приёма — от 20 секунд до 2 минут, в зависимости от компьютера."
      : prov === "openai" ? "Стоимость зависит от сервиса. Своя модель на компьютере клиники бесплатна, но нужен мощный компьютер." : "Сохраните, чтобы увидеть примерную стоимость для выбранной модели.";
  };
  $("#aiProv").onchange = () => { ai.model = ""; syncAi(); };
  $("#aiModelSel").onchange = () => { ai.model = $("#aiModelSel").value; };
  syncAi();
  const save = async () => {
    const prov = $("#aiProv").value;
    const r = await api.ai_settings_save({enabled: $("#aiOn").checked, provider: prov, model: prov === "openai" ? $("#aiModel").value : prov === "local" ? (ai.provider === "local" ? ai.model : "") : $("#aiModelSel").value,
      base_url: prov === "openai" ? $("#aiUrl").value : "", folder: $("#aiFolder").value, scope: $("#aiScope").value, key: $("#aiKey").value,
      style: $("#aiStyle").checked, auto_insert: $("#aiAuto").checked});
    Object.assign(ai, r); syncAi(); return r;
  };
  $("#aiSave").onclick = async () => { try { await save(); $("#aiKey").value = ""; msgA("Сохранено", true); } catch (e) { msgA(errText(e), false); } };
  $("#aiTest").onclick = async () => { msgA("Проверяем…", true); try { await save(); msgA(await api.ai_test(), true); } catch (e) { msgA(errText(e), false); } };
  loadVoiceStaff();
  clearTimeout(speechPoll);
  if (st.downloading) speechPoll = setTimeout(() => { if (S.view === "settings") loadVoiceSettings(); }, 1500);
}

/* ------------------------------------------------ settings: employees' voices (who speaks in a visit) */
const VOICE_TEXT = {
  "Врач": `Добрый день! Я врач-стоматолог, и сейчас я читаю этот текст обычным голосом — так, как разговариваю с пациентами на приёме.
Присаживайтесь, пожалуйста, в кресло. Что вас беспокоит? Давно болит? От холодного или от горячего? Ночью беспокоило?
Откройте рот пошире, я посмотрю. На тридцать шестом зубе кариозная полость средней глубины, зондирование болезненно по эмалево-дентинной границе, перкуссия безболезненная. На снимке изменений у верхушек корней нет.
Сейчас сделаем инфильтрационную анестезию ультракаином, это совсем не больно. Если что-то беспокоит, поднимите левую руку.
Проведём препарирование, медикаментозную обработку и поставим пломбу из светоотверждаемого композита. Закройте рот, сомкните зубы, пожуйте. Не мешает?
После приёма два часа не ешьте, чистите зубы два раза в день и пользуйтесь зубной нитью. Приходите на осмотр через полгода. Всего доброго, до свидания!`,
  "Ассистент": `Здравствуйте! Я ассистент стоматолога, и сейчас я читаю этот текст обычным голосом — так, как говорю на приёме.
Проходите, пожалуйста, вещи можно оставить на стуле. Садитесь в кресло, я надену вам салфетку. Голову чуть назад, вот так. Вам удобно?
Подаю зеркало, зонд и пинцет. Карпула ультракаина, игла тридцатого размера. Готовлю коффердам и кламмер, ставлю слюноотсос.
Сплюньте, пожалуйста, и прополощите рот. Подаю адгезив, композит оттенка А2 и полимеризационную лампу.
Полировочные диски и артикуляционная бумага готовы. Всё хорошо, потерпите ещё немного, осталось совсем чуть-чуть.
Можно вставать, аккуратно, не торопитесь. Следующий приём запишем у администратора. До свидания, хорошего вам дня!`,
};

let voicePoll = null;
async function loadVoiceStaff() {
  const box = $("#voiceStaff"); if (!box) return;
  let st;
  try { st = await api.voice_status(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const m = st.model;
  const qual = v => v.quality >= 0.75 ? "хороший образец" : v.quality >= 0.6 ? "образец средний" : "лучше перезаписать в тишине";
  box.innerHTML = `<p class="hint">На записи приёма программа узнаёт врача и ассистента по голосу, всё остальное считает словами пациента.
      Каждый сотрудник один раз читает вслух короткий текст (около минуты) в кабинете, с тем же микрофоном, что и на приёме.
      Сохраняется не звук, а «отпечаток» голоса — набор чисел; звук сразу удаляется. Образцы хранятся на этом компьютере.</p>
    <div class="vs-model">${m.ready ? `<span class="pill st-ok">модель различения голосов скачана</span>`
      : m.downloading ? `<span>Скачиваю модель различения голосов…</span><div class="vm-bar"><i style="width:${m.progress}%"></i></div><small>${m.progress}%</small>`
      : `<span>Модель различения голосов ≈${m.mb} МБ, скачивается один раз</span><button class="btn ghost small" id="vsDl">Скачать</button>`}</div>
    ${m.error ? `<div class="warn-line bad">${esc(m.error)}</div>` : ""}
    <div class="vs-list">${st.staff.map(u => `<div class="vs-row">
        <div class="grow"><b>${esc(u.name)}</b><small class="muted">${esc(u.position || u.label)}</small></div>
        ${u.voice ? `<span class="pill st-ok" title="${esc(u.voice.seconds)} с речи · ${fmtDT(u.voice.updated_at)}">голос записан · ${qual(u.voice)}</span>` : `<span class="muted">голос не записан</span>`}
        <button class="btn ${u.voice ? "ghost " : ""}small" data-vrec="${u.id}" ${m.ready ? "" : "disabled title=\"Сначала скачайте модель\""}>${u.voice ? "Перезаписать" : "Записать голос"}</button>
        ${u.voice ? `<button class="btn ghost small" data-vdel="${u.id}" title="Удалить образец голоса">×</button>` : ""}
      </div>`).join("") || '<div class="muted">Сотрудников пока нет.</div>'}</div>`;
  const dl = $("#vsDl", box); if (dl) dl.onclick = async () => { try { await api.voice_download(); loadVoiceStaff(); } catch (e) { toast(errText(e), true); } };
  $$("[data-vrec]", box).forEach(b => b.onclick = () => enrollVoice(st.staff.find(u => u.id === +b.dataset.vrec)));
  $$("[data-vdel]", box).forEach(b => b.onclick = async () => {
    const u = st.staff.find(x => x.id === +b.dataset.vdel);
    if (!(await ask(`Удалить образец голоса: ${u.name}?`, {danger: true, ok: "Удалить", text: "На записях приёма этот сотрудник будет считаться пациентом, пока голос не записан заново."}))) return;
    await api.voice_delete(u.id); loadVoiceStaff();
  });
  clearTimeout(voicePoll);
  if (m.downloading) voicePoll = setTimeout(() => { if (S.view === "settings") loadVoiceStaff(); }, 1200);
}

function enrollVoice(u) {
  const text = VOICE_TEXT[u.label] || VOICE_TEXT["Врач"];
  let mic = null, timer = null;
  const box = modal(`<div class="m-h"><h3>Голос: ${esc(u.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b vs-enroll">
      <p class="hint">Сядьте так же, как на приёме, микрофон — на своём месте (петличка на воротнике). В кабинете должно быть тихо.
        Нажмите «Начать запись» и прочитайте текст целиком обычным голосом, не торопясь. Ошиблись — просто читайте дальше.</p>
      <div class="vs-text">${esc(text).replace(/\n/g, "<br>")}</div>
      <div class="vs-rec"><button class="btn" id="veGo">${MIC}<span>Начать запись</span></button><span class="dict-state muted" id="veState">Нужно не меньше 20 секунд речи, лучше прочитать весь текст (около минуты)</span></div>
    </div>`, {onClose: () => { clearInterval(timer); if (mic) mic.stop(); }});
  const go = $("#veGo", box), state = $("#veState", box);
  const set = (h, c = "") => { state.innerHTML = h; state.className = "dict-state " + c; };
  go.onclick = async () => {
    if (mic) { mic.stop(); return; }
    try { mic = await micRecorder(); } catch (e) { return set(esc(e.message), "bad-t"); }
    const t0 = Date.now();
    go.querySelector("span").textContent = "Готово"; go.classList.add("danger-fill");
    const tick = () => { const s = Math.floor((Date.now() - t0) / 1000);
      set(`<i class="dict-dot"></i>Идёт запись ${Math.floor(s / 60)}:${pad(s % 60)} — ${s < 20 ? "читайте текст" : "дочитайте и нажмите «Готово»"}`, "rec-t");
      if (s >= 180) mic.stop(); };
    tick(); timer = setInterval(tick, 500);
    const blob = await mic.done;
    clearInterval(timer); mic = null;
    go.classList.remove("danger-fill"); go.querySelector("span").textContent = "Записать заново";
    if ($("#modal").hidden) return;
    go.disabled = true; set(`<span class="dict-spin"></span>Запоминаю голос…`);
    try {
      const r = await api.voice_enroll(u.id, await blobB64(blob), blob.type);
      set(`Голос записан: ${r.seconds} с речи${r.quality < 0.6 ? " — было шумно, лучше записать ещё раз в тишине" : ""}.`, r.quality < 0.6 ? "bad-t" : "ok-t");
      toast(`${u.name}: голос записан`);
      loadVoiceStaff();
    } catch (e) { set(esc(errText(e)), "bad-t"); }
    go.disabled = false;
  };
}

/* ------------------------------------------- settings: AI on this computer (Ollama + Qwen / Gemma) */
let localAiPoll = null, localAiBusy = false;
async function loadLocalAi() {
  const box = $("#aiLocal"); if (!box || box.hidden) return;
  let st;
  try { st = await api.local_ai_status(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const ai = (await api.speech_status()).ai;
  const busy = st.task, mb = n => n >= 1000 ? (n / 1000).toFixed(1).replace(".", ",") + " ГБ" : n + " МБ";
  const prog = () => `<div class="vm-bar"><i style="width:${st.progress}%"></i></div><small>${st.progress}%</small>`;
  box.innerHTML = `<div class="la-step">
      <div class="grow"><b>1. Программа ИИ (Ollama)</b><small class="muted">${st.installed ? "установлена в папку программы" : st.external ? "используется Ollama, уже установленная на компьютере" : `скачивается один раз, ≈${mb(st.ollama_mb)}`}</small></div>
      ${busy === "install" ? `<div class="la-prog">${prog()}</div>` : st.installed || st.external ? '<span class="pill st-ok">готово</span>'
        : `<button class="btn small" id="laInstall" ${busy ? "disabled" : ""}>Установить</button>`}</div>
    <div class="la-step"><div class="grow"><b>2. Модель</b><small class="muted">память этого компьютера: ${st.memory_gb ? String(st.memory_gb).replace(".", ",") + " ГБ" : "неизвестно"}</small></div></div>
    <div class="voice-models">${Object.entries(st.models).map(([k, m]) => {
      const used = ai.provider === "local" && ai.model === k && m.ready;
      const low = st.memory_gb && st.memory_gb < m.ram;
      return `<div class="vm ${used ? "on" : ""}">
        <div><b>${esc(m.title)}</b><small class="muted">${esc(m.desc)} · ≈${mb(m.mb)}</small>${low ? `<small class="bad-t">нужно от ${m.ram} ГБ памяти</small>` : ""}</div>
        ${busy === "pull:" + k ? prog()
          : m.ready ? (used ? '<span class="pill st-ok">используется</span>' : `<span class="row la-btns"><button class="btn ghost small" data-lause="${k}">Использовать</button><button class="btn ghost small" data-ladel="${k}" title="Удалить модель с компьютера">×</button></span>`)
          : `<button class="btn ghost small" data-lapull="${k}" ${busy || !(st.installed || st.external) ? "disabled" : ""}>Скачать</button>`}</div>`;
    }).join("")}</div>
    ${st.error ? `<div class="warn-line bad">${esc(st.error)}</div>` : ""}
    <p class="hint">Файлы лежат в <code>${esc(st.folder)}</code> (папки <code>ollama</code> и <code>models\\ollama</code>) — их можно скопировать на другой компьютер флешкой.</p>`;
  if (typeof aiLocalExtra === "function") aiLocalExtra(box, st, ai);  // 2.13: the clinic's own model and the quality check
  const act = (fn, refreshAll) => async () => {
    try { await fn(); } catch (e) { return toast(errText(e), true); }
    refreshAll ? loadVoiceSettings() : loadLocalAi();
  };
  const ins = $("#laInstall", box); if (ins) ins.onclick = act(() => api.local_ai_install());
  $$("[data-lapull]", box).forEach(b => b.onclick = act(() => api.local_ai_pull(b.dataset.lapull)));
  $$("[data-lause]", box).forEach(b => b.onclick = act(() => api.local_ai_use(b.dataset.lause), true));
  $$("[data-ladel]", box).forEach(b => b.onclick = async () => {
    if (!(await ask(`Удалить модель ${st.models[b.dataset.ladel].title} с компьютера?`, {danger: true, ok: "Удалить", text: "Её можно будет скачать заново."}))) return;
    act(() => api.local_ai_delete(b.dataset.ladel))();
  });
  clearTimeout(localAiPoll);
  if (busy) { localAiBusy = true; localAiPoll = setTimeout(() => { if (S.view === "settings") loadLocalAi(); }, 1500); }
  else if (localAiBusy) { localAiBusy = false; loadVoiceSettings(); }  // a model was just downloaded and switched on
}
