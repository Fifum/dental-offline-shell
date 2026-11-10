"use strict";
/* Block 6, platform: Settings → «Облако и подписка», «Обновления программы», «Перенос базы пациентов»;
   PIN sign-in on a shared computer; «Доступна новая версия» for the director. */
const PL_STATE = {trial: "Пробный период", active: "Оплачено", grace: "Оплата просрочена", expired: "Подписка закончилась", blocked: "Отключено"};
const PL_DAYS = n => { n = Math.abs(n); const m10 = n % 10, m100 = n % 100; return n + " " + (m10 === 1 && m100 !== 11 ? "день" : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? "дня" : "дней"); };
const isDirector = () => !!(ME && ME.role === "director");
const PL_FIELDS = {comment: "Комментарий", phone: "Телефон", name: "ФИО", birth: "Дата рождения", start: "Начало", end: "Окончание",
  status: "Статус", title: "Название", items: "Строки счёта", total: "Сумма", amount: "Сумма", price: "Цена", note: "Заметка",
  text: "Текст", discount: "Скидка", doctor_id: "Врач", patient_id: "Пациент", detail: "Карточка пациента", data: "Данные",
  method: "Способ оплаты", qty: "Количество", date: "Дата", body: "Текст шаблона", html: "Текст документа", work: "Работа",
  teeth: "Зубы", shade: "Цвет", due_date: "Срок", min_qty: "Минимальный остаток", chair: "Кресло", plan_status: "Статус плана",
  role: "Роль", perms: "Права", pass_hash: "Пароль", pin_hash: "ПИН-код", position: "Должность", active: "Активен"};
const plField = f => PL_FIELDS[f] || f;

function loadPlatformSettings() { loadCloudPanel(); loadUpdatePanel(); loadImportPanel(); }

/* ------------------------------------------------------------ cloud */
async function loadCloudPanel() {
  const box = $("#cloudBody"); if (!box) return;
  let st;
  try { st = await api.cloud_status(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  if (!st.configured) {
    box.innerHTML = `
      <div class="form">
        <label class="wide">Адрес облачного сервера<input class="input" id="clUrl" placeholder="https://cloud.example.ru" value="${esc(st.url || "")}"></label>
        <label class="wide">Код подключения<input class="input mono" id="clCode" placeholder="XXXX-XXXX-XXXX-XXXX или DD1-…" autocomplete="off"></label>
        <label>Название этого компьютера<input class="input" id="clName" value="${esc(st.computer || "")}"></label>
      </div>
      <p class="hint">Первый компьютер клиники подключается кодом от поставщика программы. Остальные — полным кодом с первого компьютера (он начинается с «DD1-», в нём уже есть адрес). ${isDirector() ? "" : "<b>Подключить может только директор.</b>"}</p>
      <div class="row"><button class="btn" id="clJoin" ${isDirector() ? "" : "disabled"}>Подключить</button><span class="msg" id="clMsg"></span></div>`;
    $("#clJoin").onclick = async () => {
      const b = $("#clJoin"), m = $("#clMsg");
      const code = $("#clCode").value.trim();
      if (!code) { m.className = "msg bad"; m.textContent = "Вставьте код подключения"; return; }
      if (!code.toUpperCase().startsWith("DD1-") && !$("#clUrl").value.trim()) { m.className = "msg bad"; m.textContent = "Укажите адрес сервера"; return; }
      b.disabled = true; m.className = "msg ok"; m.textContent = "Подключаемся…";
      try {
        const r = await api.cloud_join($("#clUrl").value.trim(), code, $("#clName").value.trim());
        toast(`Компьютер подключён к облаку «${r.name}». Первая синхронизация начнётся сама.`);
        loadCloudPanel();
      } catch (e) { m.className = "msg bad"; m.textContent = errText(e); b.disabled = false; }
    };
    return;
  }
  const sub = st.subscription || {};
  const bad = ["grace", "expired", "blocked"].includes(sub.state);
  const until = sub.until ? fmtDate(sub.until) : "";
  const subLine = sub.state ? `<div class="pl-sub ${bad ? "bad" : sub.state === "trial" ? "trial" : "ok"}">
      <div><b>${esc(sub.plan_title || "")}</b>${sub.state === "trial" ? "" : " · " + esc(PL_STATE[sub.state] || sub.state)}</div>
      <div class="muted">${sub.state === "expired" ? "синхронизация приостановлена, работа на компьютерах продолжается"
        : sub.days_left >= 0 ? `до ${esc(until)} · осталось ${PL_DAYS(sub.days_left)}` : `с ${esc(until)}`} · компьютеров ${sub.devices} из ${sub.max_devices}</div></div>` : "";
  const last = st.running ? "идёт синхронизация…" : st.last_ok ? `последняя синхронизация ${fmtDT(st.last_ok)}` : "ещё не синхронизировалось";
  const err = st.error ? `<div class="warn-line ${st.offline ? "" : "bad"}">${esc(st.offline ? "Нет связи с облаком — изменения сохраняются на этом компьютере и уйдут, когда появится интернет." : st.error)}</div>` : "";
  const devs = (st.devices || []).map(d => `<tr><td>${esc(d.name)}${d.id === st.device ? ' <span class="pl-tag">этот</span>' : ""}</td><td>${esc(d.version || "")}</td>
      <td>${esc(fmtDT(d.last_seen))}</td><td>${d.id !== st.device && isDirector() ? `<button class="linkbtn" data-rv="${esc(d.id)}">отключить</button>` : ""}</td></tr>`).join("");
  const plans = (sub.plans || []).map(p => `<span class="pl-plan"><b>${esc(p.title)}</b> ${money(p.price)}/мес, до ${p.devices} компьютеров</span>`).join("; ");
  box.innerHTML = `${subLine}${err}
    <div class="bk-state">Облако «${esc(st.name)}» · ${esc(last)} · ждут отправки: ${st.pending}${st.conflicts ? ` · <button class="linkbtn" id="clConf">спорных изменений: ${st.conflicts}</button>` : ""}</div>
    <div class="row">
      <button class="btn" id="clSync">Синхронизировать сейчас</button>
      ${isDirector() ? `<button class="btn ghost" id="clCodeBtn">Код для других компьютеров</button>` : ""}
      <button class="btn ghost" id="clConfAll">Журнал изменений</button>
      ${isDirector() ? `<button class="btn ghost danger-text" id="clLeave">Отключить от облака</button>` : ""}
      <span class="msg" id="clMsg"></span>
    </div>
    ${devs ? `<table class="tbl compact pl-devs"><thead><tr><th>Компьютер</th><th>Версия</th><th>Был на связи</th><th></th></tr></thead><tbody>${devs}</tbody></table>` : ""}
    ${plans ? `<p class="hint">Тарифы: ${plans}. Оплата — по счёту, продление ставит поставщик программы.</p>` : ""}`;
  $("#clSync").onclick = async () => {
    const b = $("#clSync"), m = $("#clMsg"); b.disabled = true; m.className = "msg ok"; m.textContent = "Синхронизируем…";
    try {
      const r = await api.cloud_sync();
      if (r.ok) toast(r.message || `Готово: отправлено ${r.pushed}, получено ${r.pulled}` + (r.conflicts ? `, спорных: ${r.conflicts}` : ""));
      else toast(r.message, true);
    } catch (e) { toast(errText(e), true); }
    loadCloudPanel(); refreshStatus();
  };
  const cc = $("#clCodeBtn"); if (cc) cc.onclick = showCloudCode;
  const cf = $("#clConf"); if (cf) cf.onclick = () => openConflicts(false);
  $("#clConfAll").onclick = () => openConflicts(true);
  const lv = $("#clLeave");
  if (lv) lv.onclick = async () => {
    if (!(await ask("Отключить этот компьютер от облака?", {danger: true, ok: "Отключить",
      text: "Данные на этом компьютере останутся, но перестанут сходиться с другими компьютерами клиники. Подключить снова можно кодом с другого компьютера."}))) return;
    try { await api.cloud_leave(); toast("Компьютер отключён от облака"); loadCloudPanel(); } catch (e) { toast(errText(e), true); }
  };
  $$("[data-rv]", box).forEach(b => b.onclick = async () => {
    if (!(await ask("Отключить этот компьютер от облака клиники?", {danger: true, ok: "Отключить", text: "Например, ноутбук потерян или больше не используется. Он перестанет получать и отправлять данные."}))) return;
    try { await api.cloud_revoke(b.dataset.rv); toast("Компьютер отключён"); loadCloudPanel(); } catch (e) { toast(errText(e), true); }
  });
}

async function showCloudCode() {
  if (!(await ask("Показать код подключения?", {icon: "warn", ok: "Показать",
    text: "В коде есть ключ шифрования данных клиники. Вводите его только на компьютерах своей клиники и не пересылайте в мессенджерах."}))) return;
  let r;
  try { r = await api.cloud_code(); } catch (e) { return toast(errText(e), true); }
  const box = modal(`<div class="m-h"><h3>Код для других компьютеров клиники</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">На другом компьютере: Настройки → «Облако и подписка» → вставьте этот код в поле «Код подключения» (адрес вписывать не нужно).</p>
    <textarea class="input mono pl-code" readonly rows="4">${esc(r.code)}</textarea>
    <p class="hint">Запишите код и храните его как пароль: без него данные из облака нельзя расшифровать, если все компьютеры клиники выйдут из строя.</p></div>
    <div class="m-f"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="clCopy">Скопировать</button></div>`);
  $("#clCopy", box).onclick = async () => { try { await navigator.clipboard.writeText(r.code); toast("Код скопирован"); } catch (e) { $(".pl-code", box).select(); } };
}

async function openConflicts(all) {
  let rows;
  try { rows = await api.cloud_conflicts(all); } catch (e) { return toast(errText(e), true); }
  const body = rows.length ? `<table class="tbl compact"><thead><tr><th>Когда</th><th>Что</th><th>Поле</th><th>Осталось</th><th>Было на другом компьютере</th><th></th></tr></thead><tbody>
    ${rows.map(r => `<tr class="${r.seen ? "muted" : ""}"><td>${esc(fmtDT(r.at))}</td><td>${esc(r.title)}</td>
      <td>${r.kind === "deleted" ? "удаление" : r.kind === "failed" ? "не применилось" : esc(plField(r.field))}</td>
      <td class="pl-val">${esc(r.kind === "deleted" ? "строка сохранена" : r.kept)}</td><td class="pl-val">${esc(r.kind === "deleted" ? "строку удалили" : r.other)}</td>
      <td>${r.kind === "field" || r.kind === "failed" ? `<button class="linkbtn" data-rs="${r.id}">вернуть</button>` : ""}${!r.seen ? ` <button class="linkbtn" data-sn="${r.id}">ок</button>` : ""}</td></tr>`).join("")}</tbody></table>`
    : `<p class="muted">${all ? "Журнал пуст." : "Спорных изменений нет."}</p>`;
  const box = modal(`<div class="m-h"><h3>Изменения с двух компьютеров</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Когда одно и то же поле поменяли на двух компьютерах без связи, остаётся более позднее изменение, а другое значение сохраняется здесь. «Вернуть» — поставить значение с другого компьютера. Удалённое на одном компьютере и изменённое на другом не удаляется.</p>${body}</div>
    <div class="m-f">${rows.some(r => !r.seen) ? `<button class="btn ghost" id="cfAll">Отметить все просмотренными</button>` : ""}<button class="btn" data-close>Закрыть</button></div>`, {wide: true});
  $$("[data-rs]", box).forEach(b => b.onclick = async () => {
    try { await api.cloud_conflict_restore(b.dataset.rs); toast("Значение возвращено — уйдёт на другие компьютеры при синхронизации"); openConflicts(all); loadCloudPanel(); }
    catch (e) { toast(errText(e), true); }
  });
  $$("[data-sn]", box).forEach(b => b.onclick = async () => { await api.cloud_conflict_seen(b.dataset.sn); openConflicts(all); loadCloudPanel(); });
  const ca = $("#cfAll", box); if (ca) ca.onclick = async () => { await api.cloud_conflict_seen(null); openConflicts(all); loadCloudPanel(); };
}

/* ------------------------------------------------------------ updates */
const PL_MB = n => (n / 1048576).toLocaleString("ru-RU", {maximumFractionDigits: 0}) + " МБ";
let updPoll = null;
async function loadUpdatePanel(check) {
  const box = $("#updateBody"); if (!box) return;
  let st;
  try { st = check ? await api.update_check() : await api.update_status(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  let client = false;
  const pw = window.pywebview && window.pywebview.api;
  if (pw && pw.is_client) { try { client = await pw.is_client(); } catch (e) {} }
  const head = !st.configured ? `<div class="bk-state">Сейчас установлена версия <b>${esc(st.current)}</b>. Адрес обновлений ещё не настроен — новые версии ставятся файлом-установщиком.</div>`
    : st.available ? `<div class="pl-sub ok"><div><b>Доступна версия ${esc(st.latest)}</b>${st.date ? " от " + esc(fmtDate(st.date)) : ""} · ${esc(PL_MB(st.size))}</div><div class="muted">Сейчас установлена ${esc(st.current)}</div></div>`
    : `<div class="bk-state">Установлена последняя версия <b>${esc(st.current)}</b>${st.checked_at ? ` · проверено ${esc(fmtDT(st.checked_at))}` : ""}</div>`;
  const notes = st.available && st.notes ? `<details class="pl-notes"><summary>Что нового</summary><pre>${esc(st.notes)}</pre></details>` : "";
  const err = st.error ? `<div class="warn-line">${esc(st.error)}</div>` : "";
  const prog = st.downloading ? `<div class="pl-prog"><i style="width:${st.progress}%"></i></div><div class="muted">Скачиваем… ${st.progress}%</div>` : "";
  const can = isDirector() && !client;
  const btn = !st.available ? "" : st.ready ? `<button class="btn" id="upInstall" ${can ? "" : "disabled"}>Обновить сейчас</button>`
    : `<button class="btn" id="upGet" ${can && !st.downloading ? "" : "disabled"}>Скачать обновление</button>`;
  box.innerHTML = `${head}${err}${notes}${prog}
    <div class="row">${btn}${st.configured ? `<button class="btn ghost" id="upCheck">Проверить сейчас</button>` : ""}<span class="msg" id="upMsg"></span></div>
    <p class="hint">${client ? "Этот компьютер подключён к серверу клиники: обновите программу на компьютере-сервере, а здесь — установщиком."
      : isDirector() ? "Файл обновления подписан разработчиком: программа проверяет подпись и контрольную сумму и не запустит чужой файл. Перед обновлением программа закроется и сохранит резервную копию."
      : "Обновлять программу может директор."}</p>`;
  const c = $("#upCheck"); if (c) c.onclick = () => loadUpdatePanel(true);
  const g = $("#upGet");
  if (g) g.onclick = async () => {
    try { await api.update_download(); } catch (e) { return toast(errText(e), true); }
    clearInterval(updPoll);
    updPoll = setInterval(async () => {
      const s = await api.update_status().catch(() => null);
      if (!s || !s.downloading) { clearInterval(updPoll); if (s && s.ready) toast("Обновление скачано и проверено"); }
      loadUpdatePanel();
    }, 700);
    loadUpdatePanel();
  };
  const i = $("#upInstall");
  if (i) i.onclick = async () => {
    if (!(await ask(`Обновить программу до версии ${st.latest}?`, {ok: "Обновить",
      text: "Программа закроется, сохранит резервную копию, установит новую версию и откроется снова. Это займёт до минуты. Предупредите коллег, если они работают с этим компьютером."}))) return;
    try { await api.update_install(); toast("Устанавливаем обновление — программа сейчас закроется"); }
    catch (e) { toast(errText(e), true); }
  };
}

/* ------------------------------------------------------------ 3.0: clinic network */
const NET_ASKED = {};
function netPairRequests(st) {
  for (const r of st.pair_requests || []) {
    if (NET_ASKED[r.node]) continue;
    NET_ASKED[r.node] = 1;
    (async () => {
      const yes = await ask(`Новый компьютер «${r.host || r.name}» просит подключиться — принять?`, {ok: "Принять", cancel: "Отклонить",
        text: `Код на экране нового компьютера: ${String(r.code).replace(/(\d{3})(\d{3})/, "$1 $2")}. Принимайте, только если код совпадает и это компьютер вашей клиники: он получит все данные клиники.`
          + (r.has_data ? "\n\nНа нём уже есть свои пациенты и записи — они объединятся с данными клиники." : "")});
      try {
        if (yes) { await api.p2p_accept(r.node); toast(`Компьютер «${r.host || r.name}» подключён к клинике. Данные начнут приходить на него через несколько секунд.`); }
        else { await api.p2p_reject(r.node); toast("Подключение отклонено"); }
      } catch (e) { toast(errText(e), true); }
    })();
  }
}
function netClinicHtml(c) {
  if (!c || !c.configured) return "";
  const ago = t => t ? fmtDT(t) : "ещё не было";
  const peers = (c.peers || []).map(p => `<li><b>${esc(p.host || p.name || p.node)}</b> — ${p.online ? '<span class="ok-t">в сети</span>' : "не в сети"}, обмен: ${esc(ago(p.last_sync))}${p.error && p.online ? ` <span class="bad-t">${esc(p.error)}</span>` : ""}</li>`).join("");
  const others = isDirector() && c.lone ? (c.others || []).map(o => `<div class="row" style="margin:6px 0"><span>В сети есть компьютер <b>${esc(o.host)}</b> (клиника «${esc(o.clinic_name)}»), ещё не объединённый с этим.</span><button class="btn small" data-join="${esc(o.clinic)}">Объединить с ним</button></div>`).join("") : "";
  const j = c.join && c.join.state === "wait" ? `<div class="warn-line" style="margin:6px 0">Запрос отправлен. Код для проверки: <b>${esc(c.join.code)}</b> — директор должен нажать «Принять» на том компьютере.</div>` : "";
  return `<div style="margin-bottom:8px">Клиника «<b>${esc(c.clinic_name)}</b>», этот компьютер: <b>${esc(c.computer)}</b>${c.paused ? ` <span class="bad-t">${esc(c.paused)}</span>` : ""}</div>
    ${peers ? `<ul style="margin:0 0 8px 18px;padding:0">${peers}</ul>` : `<div class="muted" style="margin-bottom:8px">Других компьютеров клиники пока нет.</div>`}
    ${others}${j}<div class="row" style="margin-bottom:8px"><button class="btn ghost small" id="netSyncNow">Обменяться сейчас</button></div>`;
}
function netClinicBind() {
  const b = $("#netSyncNow"); if (b) b.onclick = async () => { await api.p2p_sync(); toast("Обмен с компьютерами клиники запущен"); };
  document.querySelectorAll("[data-join]").forEach(x => x.onclick = async () => {
    if (!(await ask("Объединить этот компьютер с клиникой на другом компьютере?", {ok: "Отправить запрос",
      text: "Пациенты, записи, оплаты и сотрудники этого компьютера объединятся с данными клиники. Если логины совпадают, останется пароль, изменённый позже. Директор на том компьютере должен нажать «Принять»."}))) return;
    try { const r = await api.p2p_join_other(x.dataset.join); toast(`Запрос отправлен. Код для проверки: ${r.code}`); }
    catch (e) { toast(errText(e), true); }
  });
}

/* banner for the director and the cloud subscription warning (called from refreshStatus) */
function platformStatus(st) {
  netPairRequests(st);
  const u = st.update;
  if (u && u.available && isDirector() && S.updateShown !== u.latest) {
    S.updateShown = u.latest;
    showUpdateBanner(u.latest);
  }
  const c = st.cloud;
  if (c && isDirector()) {
    const warn = c.state === "expired" ? "Подписка на облако закончилась: компьютеры клиники перестали обмениваться данными. Работа на каждом компьютере продолжается."
      : c.state === "grace" ? "Оплата облака просрочена — через несколько дней синхронизация остановится."
      : (c.state === "trial" || c.state === "active") && c.days_left <= 5 ? `Облако оплачено ещё на ${PL_DAYS(c.days_left)}.` : "";
    if (warn && S.cloudWarned !== warn) { S.cloudWarned = warn; toast(warn + " Настройки → «Облако и подписка».", c.state !== "trial" && c.state !== "active"); }
  }
}
function showUpdateBanner(ver) {
  let el = $("#updBanner");
  if (!el) { el = document.createElement("div"); el.id = "updBanner"; el.className = "upd-banner"; document.body.appendChild(el); }
  el.innerHTML = `<span>Доступна новая версия программы <b>${esc(ver)}</b></span><button class="btn small" id="updOpen">Подробнее</button><button class="x" id="updClose" title="Скрыть">×</button>`;
  el.hidden = false;
  $("#updOpen").onclick = () => { el.hidden = true; show("settings"); if (typeof settingsGo === "function") settingsGo("updatePanel"); };
  $("#updClose").onclick = () => { el.hidden = true; };
}

/* ------------------------------------------------------------ import */
let IMP = null;
function loadImportPanel() {
  const box = $("#importBody"); if (!box) return;
  box.innerHTML = `
    <div class="row"><label class="btn ghost pl-file">Выбрать файл Excel или CSV…<input type="file" id="impFile" accept=".xlsx,.csv,.txt,.xls" hidden></label>
      <button class="btn ghost" id="impDp">Загрузить всех пациентов из Dentist Plus</button><span class="msg" id="impMsg"></span></div>
    <div id="impPrev"></div>`;
  $("#impFile").onchange = e => { const f = e.target.files[0]; if (f) readImport(f); e.target.value = ""; };
  $("#impDp").onclick = async () => {
    if (!(await ask("Загрузить всю базу пациентов из Dentist Plus?", {ok: "Загрузить", text: "Программа скачает всех пациентов, а не только тех, у кого есть записи. В большой клинике это займёт несколько минут; работать можно как обычно."}))) return;
    try { await api.import_dp_all(); toast("Загрузка пациентов из Dentist Plus началась"); } catch (e) { toast(errText(e), true); }
  };
}
function readImport(file) {
  if (file.size > 30 * 1024 * 1024) return toast("Файл больше 30 МБ", true);
  const rd = new FileReader();
  rd.onload = async () => {
    IMP = {name: file.name, data: String(rd.result).split(",")[1] || ""};
    try { IMP.pv = await api.import_preview(IMP.name, IMP.data); renderImport(); }
    catch (e) { $("#impPrev").innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; }
  };
  rd.readAsDataURL(file);
}
function renderImport() {
  const pv = IMP.pv, opts = f => `<option value="">— не загружать —</option>` + pv.fields.map(x => `<option value="${x.key}" ${x.key === f ? "selected" : ""}>${esc(x.title)}</option>`).join("");
  $("#impPrev").innerHTML = `
    <div class="bk-state">Файл «${esc(IMP.name)}» (${esc(pv.kind === "таблица" ? "колонки определены по названиям" : "похоже на выгрузку " + pv.kind)}): строк ${pv.total},
      новых пациентов <b>${pv.new}</b>, уже есть в программе ${pv.duplicates}${pv.empty ? `, пустых ${pv.empty}` : ""}.</div>
    ${pv.problems.map(p => `<div class="warn-line">${esc(p)}</div>`).join("")}
    <div class="pl-map">${pv.columns.map(c => `<label><span title="${esc(c.title)}">${esc(c.title || "колонка " + (c.index + 1))}</span><select class="input" data-ci="${c.index}">${opts(c.field)}</select></label>`).join("")}</div>
    <table class="tbl compact"><thead><tr><th>Пациент</th><th>Телефон</th><th>Дата рождения</th><th>Карта</th><th></th></tr></thead><tbody>
    ${pv.sample.map(p => `<tr class="${p.dup ? "muted" : ""}"><td>${esc(p.name)}</td><td>${esc(p.phone)}</td><td>${esc(p.birth_date ? fmtDate(p.birth_date) : "")}</td><td>${esc(p.card_number)}</td><td>${p.dup ? "уже есть" : ""}</td></tr>`).join("")}</tbody></table>
    <div class="row"><button class="btn" id="impRun" ${pv.new ? "" : "disabled"}>Загрузить пациентов: ${pv.new}</button><button class="btn ghost" id="impCancel">Отмена</button></div>`;
  $$("[data-ci]").forEach(s => s.onchange = async () => {
    const mapping = {}; $$("[data-ci]").forEach(x => { if (x.value) mapping[x.dataset.ci] = x.value; });
    try { IMP.pv = await api.import_preview(IMP.name, IMP.data, mapping); renderImport(); } catch (e) { toast(errText(e), true); }
  });
  $("#impCancel").onclick = () => { IMP = null; $("#impPrev").innerHTML = ""; };
  $("#impRun").onclick = async () => {
    const mapping = {}; $$("[data-ci]").forEach(x => { if (x.value) mapping[x.dataset.ci] = x.value; });
    const b = $("#impRun"); b.disabled = true; b.textContent = "Загружаем…";
    try {
      const r = await api.import_run(IMP.name, IMP.data, mapping);
      toast(`Загружено пациентов: ${r.added}` + (r.duplicates ? `, пропущено (уже были): ${r.duplicates}` : ""));
      IMP = null; $("#impPrev").innerHTML = "";
    } catch (e) { toast(errText(e), true); b.disabled = false; }
  };
}

/* ------------------------------------------------------------ PIN */
async function renderPinLogin(note) {
  let users = [];
  try { users = await authApi.pin_users(); } catch (e) {}
  if (!users.length) return renderAuth("login", note);
  const box = $("#authBox");
  $("#authScreen").hidden = false;
  box.innerHTML = brandHead() + `<h2>Кто работает?</h2><p class="lead">Выберите себя и введите ПИН-код.</p>
    <div class="pin-tiles">${users.map(u => `<button class="pin-tile" data-u="${u.id}" ${u.locked ? 'data-locked="1"' : ""}><span class="av">${esc(initials(u.name))}</span>
      <span class="pt-n">${esc(u.name)}</span><span class="pt-p">${esc(u.locked ? "ПИН заблокирован" : u.position)}</span></button>`).join("")}</div>
    <div class="auth-err" id="aErr">${esc(note || "")}</div>
    <div class="auth-switch">Нет ПИН-кода? <button id="toLogin">Войти по паролю</button></div>`;
  $("#toLogin", box).onclick = () => renderAuth("login");
  $$(".pin-tile", box).forEach(t => t.onclick = () => {
    if (t.dataset.locked) return renderAuth("login", "ПИН-код заблокирован после 5 ошибок — войдите по паролю, и он снова заработает");
    const u = users.find(x => String(x.id) === t.dataset.u);
    renderPinPad(u);
  });
}
function renderPinPad(u) {
  const box = $("#authBox");
  let pin = "";
  box.innerHTML = brandHead() + `<h2>${esc(u.name)}</h2><p class="lead">Введите ПИН-код</p>
    <div class="pin-dots" id="pinDots">${"<i></i>".repeat(6)}</div>
    <div class="pin-pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => `<button data-d="${n}">${n}</button>`).join("")}<button data-a="back" title="Стереть" aria-label="Стереть"><svg viewBox="0 0 24 24"><path d="M9 5h11v14H9l-6-7z"/><path d="m12.5 9.5 5 5m0-5-5 5"/></svg></button><button data-d="0">0</button><button data-a="ok" class="pp-ok">Войти</button></div>
    <div class="auth-err" id="aErr"></div>
    <div class="auth-switch"><button id="toTiles">← Другой сотрудник</button><button id="toLogin">Войти по паролю</button></div>`;
  const dots = () => $$("#pinDots i").forEach((d, i) => d.classList.toggle("on", i < pin.length));
  const go = async () => {
    if (pin.length < 4) { $("#aErr").textContent = "ПИН-код — от 4 до 6 цифр"; return; }
    try {
      const r = await authApi.pin_login(u.id, pin);
      document.removeEventListener("keydown", onKey, true);
      TOKEN = r.token; sessionStorage.setItem(SESSION_KEY, TOKEN);
      startApp(r.user);
    } catch (e) { pin = ""; dots(); $("#aErr").textContent = errText(e); const pd = $("#pinDots"); pd.classList.remove("shake"); void pd.offsetWidth; pd.classList.add("shake"); }
  };
  const press = d => { if (pin.length < 6) { pin += d; dots(); $("#aErr").textContent = ""; } };
  const onKey = e => {
    if ($("#authScreen").hidden || !$("#pinDots")) { document.removeEventListener("keydown", onKey, true); return; }
    if (/^\d$/.test(e.key)) { e.preventDefault(); press(e.key); }
    else if (e.key === "Backspace") { e.preventDefault(); pin = pin.slice(0, -1); dots(); }
    else if (e.key === "Enter") { e.preventDefault(); go(); }
    else if (e.key === "Escape") { document.removeEventListener("keydown", onKey, true); renderPinLogin(); }
  };
  document.addEventListener("keydown", onKey, true);
  $$(".pin-pad [data-d]", box).forEach(b => b.onclick = () => press(b.dataset.d));
  $('.pin-pad [data-a="back"]', box).onclick = () => { pin = pin.slice(0, -1); dots(); };
  $('.pin-pad [data-a="ok"]', box).onclick = go;
  $("#toTiles", box).onclick = () => { document.removeEventListener("keydown", onKey, true); renderPinLogin(); };
  $("#toLogin", box).onclick = () => { document.removeEventListener("keydown", onKey, true); renderAuth("login"); };
}

/* user menu: own PIN, switch employee */
$("#ucPin").onclick = () => {
  const has = ME && ME.has_pin;
  const box = modal(`<div class="m-h"><h3>ПИН-код для входа</h3><button class="x" data-close>×</button></div>
    <div class="m-b auth-form"><p class="hint">На общем компьютере (ресепшен, кабинет) можно входить коротким ПИН-кодом: выбрать себя и ввести 4–6 цифр. После 5 ошибок ПИН блокируется до входа по паролю.</p>
    <label>Ваш пароль<input class="input" type="password" id="pnPass" autofocus autocomplete="current-password"></label>
    <label>Новый ПИН-код (4–6 цифр)<input class="input" type="password" id="pnPin" inputmode="numeric" maxlength="6" autocomplete="off"></label>
    <label>Повторите ПИН-код<input class="input" type="password" id="pnPin2" inputmode="numeric" maxlength="6" autocomplete="off"></label><div class="auth-err" id="pnErr"></div></div>
    <div class="m-f">${has ? `<button class="btn ghost" id="pnOff">Отключить ПИН</button>` : ""}<button class="btn ghost" data-close>Отмена</button><button class="btn" id="pnOk">Сохранить</button></div>`);
  $("#pnOk", box).onclick = async () => {
    if ($("#pnPin").value !== $("#pnPin2").value) return $("#pnErr").textContent = "ПИН-коды не совпадают";
    try { await authApi.set_pin($("#pnPass").value, $("#pnPin").value); ME.has_pin = true; closeModal(); toast("ПИН-код сохранён"); }
    catch (e) { $("#pnErr").textContent = errText(e); }
  };
  const off = $("#pnOff", box);
  if (off) off.onclick = async () => { await authApi.clear_pin(); ME.has_pin = false; closeModal(); toast("Вход по ПИН-коду отключён"); };
};
$("#ucSwitch").onclick = async () => {
  try { await authApi.logout(); } catch (e) {}
  ME = null; TOKEN = ""; sessionStorage.removeItem(SESSION_KEY);
  closeModal();
  renderPinLogin();
};
