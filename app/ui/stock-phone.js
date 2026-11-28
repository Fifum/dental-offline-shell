"use strict";
/* 3.13: «Телефон и облако склада» — the stock and the equipment for the phones of the staff (stock_cloud.py).
   3.18.2: nothing to type — the tab connects this computer by itself (to the cloud of its clinic, a new one only for the
   director; in the demo a demo clinic of this computer) and shows the QR at once. A computer outside the clinic's network
   joins by a code a connected one makes. */
const SP_PIN = "«Мой профиль» → «Телефон: склад и сканер» → «Создать ПИН»";

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
      <div class="row"><button class="btn" id="spAgain" ${dir ? "" : "disabled"}>Подключить снова</button></div>${dir ? spCodeForm() : ""}</div>`;
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
  api.stock_cloud_sync().then(() => { if ($("#spPhone")) spRefreshState(); }).catch(() => null);
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
  body.innerHTML = `<div class="sp-grid">
    <div class="panel sp-panel" id="spPhone"><h3>Подключить телефон</h3><p class="hint">Загружаем QR-код…</p></div>
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
        <dt>Могут войти</dt><dd>${st.staff ? `${st.staff} сотр. с ПИН-кодом` : `никто: ПИН создают в ${SP_PIN}`}</dd>
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
  spLoadQr();
}

const spStatePill = (st) => st.error ? `<span class="pill st-cancel">${esc(st.error)}</span>` : st.last_ok ? `<span class="pill st-ok">Синхронизировано ${esc(st.last_ok.slice(11, 16))}</span>` : `<span class="pill">Ждёт первой синхронизации</span>`;

async function spRefreshState() {
  try {
    const st = await api.stock_cloud_status();
    if ($("#spState")) $("#spState").innerHTML = spStatePill(st);
    if ($("#spPending")) $("#spPending").textContent = st.pending ? `${st.pending} строк` : "ничего";
  } catch (e) { /* the next opening shows it */ }
}

async function spLoadQr() {
  try {
    const p = await api.stock_cloud_phone();
    if (!$("#spPhone")) return;
    $("#spPhone").innerHTML = `<h3>Подключить телефон</h3>
      <div class="sp-qr">${p.qr ? `<img src="${p.qr}" alt="QR-код склада клиники для телефона">` : ""}
        <div><ol class="sp-steps">
            <li>Сотрудник наводит <b>обычную камеру телефона</b> на QR-код и открывает ссылку — откроется склад клиники.</li>
            <li>Выбирает себя и вводит свой <b>ПИН из 6 цифр</b>. ПИН каждый создаёт себе в программе: ${SP_PIN}.</li>
            <li>«Поделиться» → «На экран Домой» — склад откроется как приложение.</li></ol>
          <p class="hint">Камера не открывает ссылку? Откройте на телефоне <b>${esc(p.app.replace(/^https?:\/\//, ""))}</b> и введите код клиники:</p>
          <div class="sp-code mono">${esc(p.code)}</div></div></div>`;
  } catch (e) { if ($("#spPhone")) $("#spPhone").innerHTML = `<h3>Подключить телефон</h3><div class="warn-line bad">${esc(errText(e))}</div>`; }
}
