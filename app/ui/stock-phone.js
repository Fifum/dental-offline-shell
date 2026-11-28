"use strict";
/* 3.13: «Телефон и облако склада» — the stock and the equipment for the phones of the staff (stock_cloud.py).
   3.18.2: nothing to type — the tab connects this computer by itself (to the cloud of its clinic, a new one only for the
   director; in the demo a demo clinic of this computer) and shows the QR at once. A computer outside the clinic's network
   joins by a code a connected one makes.
   3.18.3: «Подключить мой телефон» first — a one-time QR of the employee signed in here: the camera of the phone opens it, the
   person makes up a PIN of their own, and that phone is theirs. The clinic's QR with a PIN made at the computer is second. */
const SP_PIN = "«Мой профиль» → «Телефон: склад и сканер» → «ПИН для общего QR клиники»";
const SP_STOCK = ["stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment"];
const spMine = () => !!(ME && ME.login && (ME.perms || []).some(p => SP_STOCK.includes(p)));

/* the personal QR in `box`: 15 minutes, one phone; «Новый QR-код» replaces it (a forgotten PIN, another phone) */
async function spPair(box) {
  box.innerHTML = `<p class="hint">Готовим ваш QR-код…</p>`;
  let r;
  try { r = await api.stock_cloud_pair(); } catch (e) {
    box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div><div class="row"><button class="btn" data-again>Повторить</button></div>`;
    $("[data-again]", box).onclick = () => spPair(box);
    return;
  }
  if (!box.isConnected) return;
  const until = Date.now() + (r.minutes || 15) * 60000;
  box.innerHTML = `<div class="sp-qr sp-mine"><img src="${r.qr}" alt="Ваш QR-код для телефона">
    <div><ol class="sp-steps">
        <li>Откройте <b>обычную камеру</b> телефона, наведите на этот QR-код и нажмите на ссылку.</li>
        <li>Придумайте <b>свой ПИН из 6 цифр</b> и повторите его. Телефон запомнит, что он ваш${r.name ? ` (${esc(r.name)})` : ""}.</li>
        <li>Дальше склад на этом телефоне открывается только вашим ПИН-кодом. «Поделиться» → «На экран Домой» — как приложение.</li></ol>
      <p class="hint sp-left" data-left></p>
      <div class="row"><button class="btn ghost small" data-new>Новый QR-код</button></div></div></div>`;
  const left = $("[data-left]", box), img = $("img", box);
  const tick = () => {
    if (!left.isConnected) return clearInterval(t);
    const s = Math.max(0, Math.round((until - Date.now()) / 1000));
    left.textContent = s ? `QR-код ваш и одноразовый — не показывайте его другим. Действует ещё ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}.`
      : "QR-код устарел — нажмите «Новый QR-код».";
    img.classList.toggle("sp-old", !s);
    if (!s) clearInterval(t);
  };
  const t = setInterval(tick, 1000); tick();
  $("[data-new]", box).onclick = () => spPair(box);
}

/* «Мой профиль» and the tab: the block «Подключить мой телефон» (one press — the QR) */
function spMyPhoneHtml(id) {
  return `<p class="hint">Наведите камеру телефона на ваш личный QR-код и придумайте свой ПИН из 6 цифр — больше ничего не нужно.
    Забыли ПИН или новый телефон — подключите ещё раз.</p>
    <div id="${id}"><div class="row"><button class="btn" data-pair>Подключить мой телефон</button></div></div>`;
}
function spBindMyPhone(root, id) {
  const b = $(`#${id} [data-pair]`, root);
  if (b) b.onclick = () => spPair($(`#${id}`, root));
}

async function stockPhone(again) {
  const body = $("#stockBody");
  let st;
  try { st = await api.stock_cloud_status(); } catch (e) { body.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  if (!st.configured) return spConnect(body, st, again === true);
  spConnected(body, st);
}

/* ---- not connected yet: connect by itself, then the QR */
async function spConnect(body, st, again) {
  const dir = isDirector();
  if (st.off && !again) {
    body.innerHTML = `<div class="panel sp-panel"><h3>Телефон и облако склада</h3>
      <p class="hint">Этот компьютер отключили от облака склада: операции с телефонов сюда не приходят. ${dir ? "" : "<b>Подключить снова может директор.</b>"}</p>
      <div class="row"><button class="btn" id="spAgain" ${dir ? "" : "disabled"}>Подключить снова</button></div>${dir && !st.demo ? spCodeForm() : ""}</div>`;
    $("#spAgain").onclick = () => stockPhone(true);
    spBindCode(false);
    return;
  }
  body.innerHTML = `<div class="panel sp-panel"><h3>Телефон и облако склада</h3>
    <p class="hint">${st.demo ? "Готовим демо-склад для телефона…" : "Подключаем склад к облаку…"}</p></div>`;
  let r;
  const here = () => S.stockTab === "phone" && $("#stockBody") === body;  // the user may have gone to another tab meanwhile
  try { r = await api.stock_cloud_connect(again); } catch (e) {
    if (!here()) return;
    body.innerHTML = `<div class="panel sp-panel"><h3>Телефон и облако склада</h3>
      <div class="warn-line bad">${esc(errText(e))}</div>
      <div class="row"><button class="btn" id="spRetry">Повторить</button></div>${dir && !st.demo ? spCodeForm() : ""}</div>`;
    $("#spRetry").onclick = () => stockPhone(again);
    spBindCode(false);
    return;
  }
  if (!here()) return;
  if (r.off) return stockPhone();
  if (!r.ok) {  // the clinic has no cloud yet, and only the director makes one
    body.innerHTML = `<div class="panel sp-panel"><h3>Телефон и облако склада</h3>
      <p class="hint">${spAbout()}</p>
      <div class="warn-line">Облако склада для клиники ещё не создано. Попросите директора открыть эту вкладку — QR-код для телефонов появится сам.</div></div>`;
    return;
  }
  if (r.created && !r.demo) toast("Склад подключён к облаку — наведите камеру телефона на QR-код");
  api.stock_cloud_sync().catch(() => null);
  // the first sync (here or of the worker, whichever runs) takes a few seconds: the state follows it while the tab is open
  [4, 12, 30].forEach((s) => setTimeout(() => { if ($("#spPhone")) spRefreshState(); }, s * 1000));
  stockPhone();
}

const spAbout = () => `Сотрудники открывают склад на своём телефоне: сканируют QR и штрихкоды, принимают поставки, списывают, отправляют заявки
  и согласуют расход. Для этого склад и оборудование клиники хранятся в облаке склада — <b>без пациентов</b>: фамилии и карточки пациентов туда не попадают.`;

/* a code from another computer of the clinic (one that is not in the clinic's network) */
const spCodeForm = (switching) => `<details class="sp-more" id="spCodeBox"><summary>${switching ? "Подключить этот компьютер к облаку другого компьютера клиники" : "Есть код с другого компьютера клиники?"}</summary>
  <p class="hint">На компьютере, который уже подключён: Склад → Телефон → «Код для другого компьютера». Код действует сутки.${switching ? " Этот компьютер перейдёт в облако того компьютера, QR-код станет общим." : ""}</p>
  <div class="row"><input class="input mono" id="spCode" placeholder="DDS-XXXX-XXXX-XXXX" autocomplete="off" spellcheck="false">
    <button class="btn" id="spJoin">Подключить</button></div><span class="msg" id="spJoinMsg"></span></details>`;

function spBindCode(switching) {
  const b = $("#spJoin");
  if (!b) return;
  b.onclick = async () => {
    const m = $("#spJoinMsg"), code = $("#spCode").value.trim();
    if (!code) { m.className = "msg bad"; m.textContent = "Введите код с другого компьютера"; return; }
    if (switching && !(await ask("Перейти в облако другого компьютера?", {ok: "Перейти", text: "Телефоны, подключённые к QR-коду этого компьютера, нужно будет подключить заново — к общему QR-коду."}))) return;
    b.disabled = true; m.className = "msg ok"; m.textContent = "Подключаемся…";
    try {
      await api.stock_cloud_join(code, "", !!switching);
      toast("Компьютер подключён к облаку склада клиники");
      api.stock_cloud_sync().catch(() => null);
      stockPhone();
    } catch (e) { b.disabled = false; m.className = "msg bad"; m.textContent = errText(e); }
  };
}

/* ---- connected: the QR first */
function spConnected(body, st) {
  const dir = isDirector();
  const others = Math.max(0, (st.laptops || 0) - 1);
  const mine = spMine();
  body.innerHTML = `<div class="sp-grid">
    <div class="sp-col">
    ${mine ? `<div class="panel sp-panel" id="spMy"><h3>Подключить мой телефон</h3>${spMyPhoneHtml("spMyBox")}</div>` : ""}
    <div class="panel sp-panel" id="spPhone"><h3>${mine ? "Общий QR-код клиники" : "Подключить телефон"}</h3><p class="hint">Загружаем QR-код…</p></div>
    <div class="panel sp-panel" id="spWifi"><h3>Без интернета — через Wi-Fi клиники</h3><p class="hint">Загружаем…</p></div></div>
    <div class="panel sp-panel">
      <h3>Облако склада</h3>
      ${st.demo ? `<div class="warn-line sp-demo"><b>Демо-режим.</b> Телефон увидит тестовый склад этого компьютера — это отдельная демо-клиника облака, настоящего склада в ней нет.
        Когда программа выйдет из демо-режима, демо-клиника отключится, а настоящий склад подключится сам.</div>` : ""}
      <div class="sp-state" id="spState">${spStatePill(st)}</div>
      <dl class="sp-dl">
        <dt>Клиника</dt><dd>${esc(st.name || "—")}</dd>
        <dt>Ждёт отправки</dt><dd id="spPending">${st.pending ? `${st.pending} строк` : "ничего"}</dd>
        <dt>Компьютеров</dt><dd>${st.laptops || 1}</dd>
        <dt>Телефонов</dt><dd>${st.phones || 0}</dd>
        <dt>С правами склада</dt><dd>${st.staff ? `${st.staff} сотр.` : "никого"}</dd>
      </dl>
      <p class="hint">Склад, оборудование, заявки и списания на согласовании ходят туда и обратно раз в минуту. Пациентов в облаке нет.</p>
      <div class="row"><button class="btn" id="spSync">Синхронизировать</button>${dir ? `<button class="btn ghost" id="spLeave">Отключить этот компьютер</button>` : ""}<span class="msg" id="spMsg"></span></div>
      ${st.demo ? "" : `<h4 class="sp-h4">Другие компьютеры клиники</h4>
      <p class="hint">${others ? `Подключено ещё ${others}. ` : ""}Компьютеры из сети клиники подключаются к этому облаку сами — на них ничего вводить не нужно.
        Компьютер не в сети клиники подключают кодом: он действует сутки.</p>
      ${dir ? `<div class="row"><button class="btn ghost" id="spInvite">Код для другого компьютера</button></div><div id="spInviteOut"></div>
        ${spCodeForm(true)}` : ""}`}
    </div></div>`;
  $("#spSync").onclick = async () => {
    const m = $("#spMsg"); m.className = "msg ok"; m.textContent = "Синхронизация…";
    try {
      const r = await api.stock_cloud_sync();
      if (r.ok === false) throw new Error(r.message);
      toast(`Склад синхронизирован: отправлено ${r.pushed || 0}, получено ${r.pulled || 0}`);
      stockPhone();
    } catch (e) { m.className = "msg bad"; m.textContent = errText(e); }
  };
  if ($("#spLeave")) $("#spLeave").onclick = async () => {
    if (!(await ask("Отключить этот компьютер от облака склада?", {danger: true, ok: "Отключить", text: "Операции с телефонов перестанут приходить сюда, и сам компьютер больше не подключится. На других подключённых компьютерах всё останется."}))) return;
    try { await api.stock_cloud_leave(); toast("Компьютер отключён от облака склада"); stockPhone(); } catch (e) { toast(errText(e), "bad"); }
  };
  if ($("#spInvite")) $("#spInvite").onclick = async () => {
    const out = $("#spInviteOut");
    try {
      const r = await api.stock_cloud_invite();
      out.innerHTML = `<div class="sp-invite"><div class="sp-code mono">${esc(r.code)}</div>
        <p class="hint">На другом компьютере: Склад → Телефон → «Есть код с другого компьютера клиники?» → введите этот код. Он действует ${esc(String(r.hours || 24))} ч.</p></div>`;
    } catch (e) { out.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; }
  };
  spBindCode(true);
  spBindMyPhone(body, "spMyBox");
  spLoadQr(mine);
  spLoadWifi();
}

/* 3.19: the stock of a phone without the internet — straight to this computer over the clinic's Wi-Fi (phone_lan.py): the simple
   address (http, no camera scanner) always; «Со сканером» — https with the clinic's own certificate (clinic_ca.py), which each
   phone installs once from the page behind the QR. The same words as the phone (phone/app.js WHY) and its certificate page. */
const SP_WHY = [
  "Камеру для сканера телефон даёт только защищённой странице — с адресом на https.",
  "Сайтам в интернете такой «паспорт» выдают специальные центры. Компьютеру внутри Wi-Fi клиники его не выдают — поэтому клиника выдаёт его себе сама.",
  "Один раз вы говорите телефону «доверяй клинике» — и склад со сканером открывается по Wi-Fi даже без интернета.",
  "Ключ сертификата хранится только на этом компьютере, а сам сертификат годится только для адресов внутри сети клиники — не для сайтов в интернете. Сайты, почту и переписку сотрудников он не открывает.",
  "Android после установки покажет «Сеть может отслеживаться» — это обычное предупреждение для любого своего сертификата. Для установки Android попросит блокировку экрана (ПИН, графический ключ или отпечаток).",
  "Убрать сертификат можно в любой момент в настройках телефона.",
];
const spWhyHtml = () => `<details class="sp-more sp-why"><summary>Зачем устанавливать сертификат клиники</summary>
  <ul class="sp-steps">${SP_WHY.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>`;

async function spLoadWifi() {
  const box = $("#spWifi");
  if (!box) return;
  let w;
  try { w = await api.phone_wifi_state(); } catch (e) {
    box.innerHTML = `<h3>Без интернета — через Wi-Fi клиники</h3><div class="warn-line bad">${esc(errText(e))}</div>`;
    return;
  }
  if (!$("#spWifi")) return;
  const ca = w.ca || {};
  box.innerHTML = `<h3>Без интернета — через Wi-Fi клиники</h3>
    <p class="hint">Когда в клинике нет интернета, склад на телефоне работает прямо с этим компьютером по Wi-Fi клиники. Телефон один раз
      подключают через интернет (свой QR-код выше), дальше в приложении склада: <b>Профиль → «Склад через Wi-Fi клиники»</b> —
      или плашка, когда облако не отвечает. Вход тем же ПИН-кодом.</p>
    ${w.http ? `<dl class="sp-dl">
        <dt>Без сканера</dt><dd class="mono">${esc(w.http)}</dd>
        ${w.full && w.https ? `<dt>Со сканером</dt><dd class="mono">${esc(w.https)}</dd>` : ""}
        <dt>Телефонов знает</dt><dd>${w.phones || 0}${w.cloud ? "" : " · нет облака склада"}</dd></dl>`
      : `<div class="warn-line">Этот компьютер не в сети клиники: нет адреса, по которому телефон его найдёт. Подключите его к Wi-Fi или кабелю клиники.</div>`}
    ${w.firewall === false ? `<div class="warn-line bad">Брандмауэр Windows не пускает телефоны к этому компьютеру (нужны порты ${esc(String(w.http ? new URL(w.http).port : 8765))} и ${esc(String(w.https ? new URL(w.https).port : 8767))}).
      <div class="row"><button class="btn small" id="spFw">Разрешить</button><span class="msg" id="spFwMsg"></span></div></div>` : ""}
    <label class="switch-row sp-switch"><input type="checkbox" id="spFull" ${w.want_full ? "checked" : ""} ${w.director ? "" : "disabled"}><span class="sw"></span>
      <span><b>Со сканером</b> — сертификат клиники</span></label>
    <p class="hint">${w.full ? "Включено: телефон, на котором установлен сертификат клиники, открывает склад по защищённому адресу — со сканером камерой."
      : "Без сертификата склад по Wi-Fi работает без сканера: код вводится вручную или по фото. Со сканером — один раз установить на телефон сертификат клиники."}
      ${w.director ? "" : " Включает директор."}</p>
    ${w.full && w.ca_qr ? `<div class="sp-qr"><img src="${w.ca_qr}" alt="QR-код страницы сертификата клиники">
      <div><ol class="sp-steps">
        <li>Наведите <b>камеру телефона</b> на этот QR-код — откроется страница «Склад со сканером».</li>
        <li>Android: «Скачать сертификат для Android», iPhone: «Скачать профиль для iPhone» — шаги установки на той же странице.</li>
        <li>Нажмите «Открыть склад со сканером» и войдите своим ПИН-кодом.</li></ol>
        <p class="hint">Сертификат «${esc(ca.title || "")}», отпечаток <span class="mono">${esc(ca.short || "")}</span> — такой же покажет страница на телефоне.
          Без интернета сканер на iPhone работает, если склад со сканером хотя бы раз открывали при интернете.</p></div></div>` : ""}
    ${spWhyHtml()}`;
  const f = $("#spFull");
  f.onchange = async () => {
    f.disabled = true;
    try { await api.phone_wifi_full(f.checked); toast(f.checked ? "Склад со сканером по Wi-Fi включён" : "Склад со сканером по Wi-Fi выключен"); }
    catch (e) { toast(errText(e), "bad"); }
    spLoadWifi();
  };
  const fw = $("#spFw");
  if (fw) fw.onclick = async () => {
    const pw = window.pywebview && window.pywebview.api, m = $("#spFwMsg");
    if (!pw || !pw.allow_firewall || !/^(127\.0\.0\.1|localhost)$/.test(location.hostname)) { m.className = "msg bad"; m.textContent = "Разрешить можно в программе на этом компьютере"; return; }
    m.className = "msg ok"; m.textContent = "Windows попросит подтвердить…";
    let r;
    try { r = await pw.allow_firewall(); } catch (e) { r = {ok: false, err: errText(e)}; }
    m.className = "msg " + (r.ok ? "ok" : "bad");
    m.textContent = r.ok ? "Готово: телефоны могут подключаться" : r.err ? "Не получилось: " + r.err : "Не получилось — подтвердите запрос Windows";
    if (r.ok) setTimeout(spLoadWifi, 1500);
  };
}

const spStatePill = (st) => st.error ? `<span class="pill st-cancel">${esc(st.error)}</span>` : st.last_ok ? `<span class="pill st-ok">Синхронизировано ${esc(st.last_ok.slice(11, 16))}</span>` : `<span class="pill">Ждёт первой синхронизации</span>`;

async function spRefreshState() {
  try {
    const st = await api.stock_cloud_status();
    if ($("#spState")) $("#spState").innerHTML = spStatePill(st);
    if ($("#spPending")) $("#spPending").textContent = st.pending ? `${st.pending} строк` : "ничего";
  } catch (e) { /* the next opening shows it */ }
}

/* the clinic's QR (before 3.18.3 the only way): for whoever has no own QR — the person chooses themselves on the phone and
   types a PIN made at the computer. Each employee connects their own phone easier at their own computer session. */
async function spLoadQr(mine) {
  const h = mine ? "Общий QR-код клиники" : "Подключить телефон";
  try {
    const p = await api.stock_cloud_phone();
    if (!$("#spPhone")) return;
    const qr = `<div class="sp-qr">${p.qr ? `<img src="${p.qr}" alt="QR-код склада клиники для телефона">` : ""}
        <div><p class="hint"><b>Проще всего:</b> каждый сотрудник входит в программу под своим именем и нажимает «Подключить мой телефон»
          (здесь или в «Мой профиль») — свой QR-код, свой ПИН.</p>
          <ol class="sp-steps">
            <li>Общий QR-код: сотрудник наводит камеру телефона, выбирает себя и вводит ПИН из 6 цифр, созданный в программе: ${SP_PIN}.</li></ol>
          <p class="hint">Камера не открывает ссылку? Откройте на телефоне <b>${esc(p.app.replace(/^https?:\/\//, ""))}</b> и введите код клиники:</p>
          <div class="sp-code mono">${esc(p.code)}</div></div></div>`;
    $("#spPhone").innerHTML = mine ? `<details class="sp-more sp-clinic"><summary>${h}: для тех, кто создал ПИН на компьютере</summary>${qr}</details>` : `<h3>${h}</h3>${qr}`;
  } catch (e) { if ($("#spPhone")) $("#spPhone").innerHTML = `<h3>${h}</h3><div class="warn-line bad">${esc(errText(e))}</div>`; }
}
