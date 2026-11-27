"use strict";
/* 3.13: «Телефон и облако склада» — the stock and the equipment for the phones of the staff (stock_cloud.py). */
async function stockPhone() {
  const body = $("#stockBody");
  let st;
  try { st = await api.stock_cloud_status(); } catch (e) { body.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const dir = isDirector();
  if (!st.configured) {
    body.innerHTML = `<div class="panel sp-panel">
      <h3>Телефон и облако склада</h3>
      <p class="hint">Сотрудники открывают склад на своём телефоне: сканируют QR и штрихкоды, принимают поставки, списывают, отправляют заявки
        и согласуют расход. Для этого склад и оборудование клиники хранятся в облаке склада — <b>без пациентов</b>: фамилии и карточки пациентов туда не попадают.
        Права проверяет облако — по должности сотрудника, вход по личному ПИН-коду (Мой профиль → «ПИН для телефона»).</p>
      <div class="form"><label class="wide">Код подключения склада<input class="input mono" id="spCode" placeholder="DDS-XXXX-XXXX-XXXX-XXXX" autocomplete="off"></label></div>
      <p class="hint">Код даёт поставщик программы. Его вводят один раз на каждом компьютере, который должен видеть операции с телефонов. ${dir ? "" : "<b>Подключить может только директор.</b>"}</p>
      <div class="row"><button class="btn" id="spJoin" ${dir ? "" : "disabled"}>Подключить</button><span class="msg" id="spMsg"></span></div></div>`;
    $("#spJoin").onclick = async () => {
      const m = $("#spMsg"), b = $("#spJoin"), code = $("#spCode").value.trim();
      if (!code) { m.className = "msg bad"; m.textContent = "Введите код подключения"; return; }
      b.disabled = true; m.className = "msg ok"; m.textContent = "Подключаемся…";
      try {
        await api.stock_cloud_join(code);
        m.textContent = "Подключено. Отправляем склад в облако…";
        await api.stock_cloud_sync().catch(() => null);
        toast("Склад подключён к облаку — теперь можно подключить телефоны");
        stockPhone();
      } catch (e) { b.disabled = false; m.className = "msg bad"; m.textContent = errText(e); }
    };
    return;
  }
  const state = st.error ? `<span class="pill st-cancel">${esc(st.error)}</span>` : st.last_ok ? `<span class="pill st-ok">Синхронизировано ${esc(st.last_ok.slice(11, 16))}</span>` : `<span class="pill">Ждёт первой синхронизации</span>`;
  body.innerHTML = `<div class="sp-grid">
    <div class="panel sp-panel">
      <h3>Облако склада</h3>
      <div class="sp-state">${state}</div>
      <dl class="sp-dl">
        <dt>Клиника</dt><dd>${esc(st.name || "—")}</dd>
        <dt>Ждёт отправки</dt><dd>${st.pending ? `${st.pending} строк` : "ничего"}</dd>
        <dt>Компьютеров</dt><dd>${st.laptops || 0}</dd>
        <dt>Телефонов</dt><dd>${st.phones || 0}</dd>
        <dt>Могут войти</dt><dd>${st.staff ? `${st.staff} сотр. с ПИН-кодом` : "никто: задайте ПИН в «Мой профиль»"}</dd>
      </dl>
      <p class="hint">Склад, оборудование, заявки и списания на согласовании ходят туда и обратно раз в минуту. Пациентов в облаке нет.</p>
      <div class="row"><button class="btn" id="spSync">Синхронизировать</button>${dir ? `<button class="btn ghost" id="spLeave">Отключить этот компьютер</button>` : ""}<span class="msg" id="spMsg"></span></div>
    </div>
    <div class="panel sp-panel" id="spPhone"><h3>Подключить телефон</h3><p class="hint">Загружаем код клиники…</p></div></div>`;
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
    if (!(await ask("Отключить этот компьютер от облака склада?", {danger: true, ok: "Отключить", text: "Операции с телефонов перестанут приходить сюда. На других подключённых компьютерах они останутся."}))) return;
    try { await api.stock_cloud_leave(); toast("Компьютер отключён от облака склада"); stockPhone(); } catch (e) { toast(errText(e), "bad"); }
  };
  try {
    const p = await api.stock_cloud_phone();
    $("#spPhone").innerHTML = `<h3>Подключить телефон</h3>
      <div class="sp-qr">${p.qr ? `<img src="${p.qr}" alt="QR для телефона">` : ""}
        <div><p class="hint">Сотрудник наводит камеру телефона на QR — откроется склад клиники. Дальше он выбирает себя и вводит свой ПИН из 6 цифр.</p>
          <p class="hint">Или откройте на телефоне <b>${esc(p.app.replace(/^https?:\/\//, ""))}</b> и введите код клиники:</p>
          <div class="sp-code mono">${esc(p.code)}</div>
          <p class="hint">На телефоне: «Поделиться» → «На экран Домой» — склад откроется как приложение.</p></div></div>`;
  } catch (e) { $("#spPhone").innerHTML = `<h3>Подключить телефон</h3><div class="warn-line bad">${esc(errText(e))}</div>`; }
}
