"use strict";
/* Money extras: certificate / bonus / SBP payments, selling gift certificates, bonuses and family in the patient
   card, the family discount in invoices, settings for bonuses, certificates and the SBP QR code. */

/* ---------------------------------------------------------------- payment form */
function payExtraInit(box, inv, pat) {
  const sel = $("#payM", box), ex = $("#payExtra", box); if (!sel || !ex) return;
  const draw = async () => {
    const m = sel.value;
    if (m === "Сертификат") {
      ex.innerHTML = `<div class="pay-x"><input class="input" id="pxCode" placeholder="Номер сертификата, например AB12-CD34" autocomplete="off"><button class="btn ghost small" id="pxCheck" type="button">Проверить</button><span class="muted" id="pxInfo"></span></div>`;
      $("#pxCheck", ex).onclick = async () => {
        try { const c = await api.cert_info($("#pxCode", ex).value);
          $("#pxInfo", ex).innerHTML = c.usable ? `<span class="ok-t">Остаток ${money(c.balance)}, действует до ${esc(fmtDate(c.expires))}</span>` : `<span class="bad-t">${c.expired ? "Срок истёк" : c.status !== "active" ? "Аннулирован" : "Остаток 0"}</span>`;
          if (c.usable && +$("#payAmt", box).value > c.balance) $("#payAmt", box).value = c.balance;
        } catch (e) { $("#pxInfo", ex).innerHTML = `<span class="bad-t">${esc(errText(e))}</span>`; }
      };
    } else if (m === "Бонусы") {
      try { const b = await api.bonus_info(pat.id);
        const limit = Math.round(inv.total * b.settings.bonus_max_share) / 100;
        ex.innerHTML = `<div class="pay-x muted">Бонусов у пациента${b.family ? " (семья «" + esc(b.family.name) + "»)" : ""}: <b>${money(b.balance)}</b>. Бонусами можно оплатить до ${b.settings.bonus_max_share}% счёта — ${money(limit)}.</div>`;
        const can_ = Math.min(b.balance, limit, inv.total - inv.paid);
        if (can_ > 0) $("#payAmt", box).value = Math.floor(can_ * 100) / 100;
      } catch (e) { ex.innerHTML = ""; }
    } else if (m === "СБП") {
      ex.innerHTML = `<div class="pay-x"><button class="btn ghost small" id="pxQr" type="button">Показать QR-код</button><button class="btn ghost small" id="pxQrT" type="button">QR на планшет</button>
        <input class="input" id="pxRef" placeholder="№ операции (необязательно)"></div>`;
      $("#pxQr", ex).onclick = () => showSbpQr(+$("#payAmt", box).value);
      $("#pxQrT", ex).onclick = async () => {
        const tablets = await api.tablets_list().catch(() => []);
        if (!tablets.length) return toast("Планшет не подключён — Настройки → «Планшет для пациентов»", true);
        try { await api.sbp_to_tablet(tablets[0].id, +$("#payAmt", box).value, pat.id); toast(`QR-код показан на «${tablets[0].name}». После оплаты нажмите «Принять оплату».`); } catch (e) { toast(errText(e), true); }
      };
    } else if (m === "Карта") {
      ex.innerHTML = `<div class="pay-x"><input class="input" id="pxRef" placeholder="№ операции или код авторизации с чека терминала (необязательно)"></div>`;
    } else ex.innerHTML = "";
  };
  sel.addEventListener("change", draw); draw();
}
function payExtraValues(box) {
  const code = $("#pxCode", box), ref_ = $("#pxRef", box);
  const out = {};
  if (code) out.cert_code = code.value.trim();
  if (ref_ && ref_.value.trim()) out.comment = `операция № ${ref_.value.trim()}`;
  return out;
}

/* ---------------------------------------------------------------- SBP */
async function showSbpQr(amount) {
  const s = await api.sbp_settings();
  if (!s.qr) return toast("Загрузите QR-код СБП: Настройки → «Бонусы, сертификаты и СБП»", true);
  modal(`<div class="m-h"><h3>Оплата по СБП</h3><button class="x" data-close>×</button></div>
    <div class="m-b sbp-show"><img alt="QR-код СБП" src="${s.qr}"><div class="sbp-sum">${money(amount || 0)}</div>
      <p class="muted">${esc(s.label || "Наведите камеру телефона на QR-код и оплатите в приложении банка")}</p></div>
    <div class="m-f"><span class="muted">Когда деньги придут, нажмите «Принять оплату» в счёте</span><button class="btn" data-close>Закрыть</button></div>`);
}

/* ---------------------------------------------------------------- certificates */
function sellCertificate(after) {
  askInput("Продажа подарочного сертификата", [{label: "Номинал, ₽", value: "5000", type: "number"}, {label: "Покупатель (необязательно)", value: "", required: false},
    {label: "Оплата: Наличные, Карта, СБП или Перевод", value: "Наличные"}], {ok: "Продать"}).then(async v => {
    if (!v) return;
    try {
      const c = await api.cert_sell({amount: v[0], buyer: v[1], method: v[2]});
      await ask(`Сертификат ${c.code}`, {icon: "edit", ok: "Распечатать", cancel: "Закрыть", text: `Номинал ${money(c.amount)}, действует до ${fmtDate(c.expires)}. Номер нужен при оплате — он напечатан на сертификате.`})
        .then(p => { if (p) printCertificate(c); });
      if (after) after();
    } catch (e) { toast(errText(e), true); }
  });
}
async function printCertificate(c) {
  const cl = (await ref()).clinic || {};
  printDoc(`<div style="border:3px double #6D0100;padding:40px;text-align:center;margin:40px">
    <div style="font-size:14pt">${esc(cl.name || "")}</div><h1 style="font-size:30pt;margin:24px 0">Подарочный сертификат</h1>
    <div style="font-size:26pt;font-weight:700">${money(c.amount)}</div><p style="font-size:16pt;letter-spacing:.15em;margin-top:24px">№ ${esc(c.code)}</p>
    <p>Действует до ${esc(fmtDate(c.expires))}${cl.phone ? ` · запись по телефону ${esc(cl.phone)}` : ""}</p></div>`);
}
async function openCertificates() {
  let status = "active";
  const box = modal(`<div class="m-h"><h3>Подарочные сертификаты</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="seg sm" id="ctF"><button data-s="active" class="on">Действующие</button><button data-s="all">Все</button></div><div id="ctL"></div></div>
    <div class="m-f"><span class="muted"></span>${can("payments") ? `<button class="btn ghost" id="ctSell">Продать сертификат</button>` : ""}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  const draw = async () => {
    const r = await api.cert_list(status);
    $("#ctL", box).innerHTML = (r.rows.length ? `<div class="tbl-scroll"><table class="tbl compact" id="ctT"><thead><tr><th>Номер</th><th>Продан</th><th>Покупатель</th><th class="num">Номинал</th><th class="num">Остаток</th><th>Действует до</th><th></th></tr></thead><tbody>
      ${r.rows.map(c => `<tr><td><b>${esc(c.code)}</b></td><td class="nowrap">${esc(fmtDT(c.sold_at))}</td><td>${esc(c.buyer || "")}</td><td class="num">${money(c.amount)}</td><td class="num">${money(c.balance)}</td>
        <td class="nowrap">${esc(fmtDate(c.expires))}${c.expired ? ' <span class="pill st-cancel">истёк</span>' : c.status !== "active" ? ' <span class="pill st-cancel">аннулирован</span>' : ""}</td>
        <td class="row-acts"><button class="linkbtn" data-pr="${esc(c.code)}">печать</button>${can("accounting") && c.status === "active" ? `<button class="linkbtn" data-cx="${esc(c.code)}">аннулировать</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty"><b>Сертификатов нет</b></div>`) + `<p class="muted">Неиспользованный остаток по действующим: <b>${money(r.balance)}</b></p>`;
    $$("[data-pr]", box).forEach(b => b.onclick = async () => printCertificate(await api.cert_info(b.dataset.pr)));
    $$("[data-cx]", box).forEach(b => b.onclick = async () => { if (await ask("Аннулировать сертификат?", {danger: true, ok: "Аннулировать", text: b.dataset.cx})) { await api.cert_cancel(b.dataset.cx); openCertificates(); } });
  };
  $$("#ctF button", box).forEach(b => b.onclick = () => { status = b.dataset.s; $$("#ctF button", box).forEach(x => x.classList.toggle("on", x === b)); draw(); });
  const sb = $("#ctSell", box); if (sb) sb.onclick = () => sellCertificate(() => openCertificates());
  draw();
}

/* ---------------------------------------------------------------- patient card: bonuses and family */
function loyaltyHeader(p) {
  const col = $("#patientCard .phead2 .ph-col:last-child"); if (!col || $(".ph-loyal", col)) return;
  if (!canAny("payments", "billing", "patients_edit")) return;
  const d = document.createElement("div"); d.className = "ph-loyal";
  d.innerHTML = `<dt>Бонусы</dt><dd><button class="linkbtn" id="aBonus">${money(p.bonus || 0)}</button></dd>
    <dt>Семья</dt><dd><button class="linkbtn" id="aFamily">${p.family ? esc(p.family.name) + (p.family.discount ? `, скидка ${p.family.discount}%` : "") : "добавить"}</button></dd>`;
  col.appendChild(d);
  $("#aBonus", d).onclick = () => openBonuses(p);
  $("#aFamily", d).onclick = () => openFamily(p);
}
async function openBonuses(p) {
  const b = await api.bonus_info(p.id);
  const KIND = {accrual: "начислено", spend: "оплата бонусами", manual: "вручную"};
  const box = modal(`<div class="m-h"><h3>Бонусы · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="stat-row"><div class="stat"><span>${b.family ? `Семейный счёт «${esc(b.family.name)}»` : "Баланс"}</span><b>${money(b.balance)}</b></div>
      <div class="stat"><span>Начисление</span><b>${b.settings.bonus_percent ? b.settings.bonus_percent + "% от оплаты" : "выключено"}</b></div></div>
      ${b.history.length ? `<table class="tbl compact"><thead><tr><th>Когда</th><th>Что</th><th>Пациент</th><th class="num">Сумма</th></tr></thead><tbody>${b.history.map(h => `<tr><td class="nowrap">${esc(fmtDT(h.at))}</td><td>${esc(KIND[h.kind] || h.kind)}${h.comment ? `<small class="muted" style="display:block">${esc(h.comment)}</small>` : ""}</td><td>${esc(h.patient_name || "")}</td><td class="num ${h.amount < 0 ? "bad-t" : "ok-t"}">${h.amount > 0 ? "+" : ""}${money(h.amount)}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Движений пока нет.${b.settings.bonus_percent ? "" : " Включить начисление можно в Настройках → «Бонусы и сертификаты»."}</p>`}</div>
    <div class="m-f"><span class="muted"></span>${can("settings") ? `<button class="btn ghost" id="bnAdj">Начислить или списать вручную</button>` : ""}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  const adj = $("#bnAdj", box);
  if (adj) adj.onclick = async () => {
    const v = await askInput("Изменить бонусы", [{label: "Сумма (минус — списать)", value: ""}, {label: "Причина", value: ""}]);
    if (!v) return openBonuses(p);
    try { await api.bonus_adjust(p.id, v[0], v[1]); toast("Бонусы изменены"); P = await api.patient(p.id); renderPatient(S.patientTab); } catch (e) { toast(errText(e), true); }
  };
}
async function openFamily(p) {
  const b = await api.bonus_info(p.id), f = b.family;
  const box = modal(`<div class="m-h"><h3>Семья · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="hint">Члены семьи копят и тратят бонусы с общего счёта; семейная скидка предлагается в каждом счёте.</p>
      <div class="grid2"><label class="fl">Название семьи<input class="input" id="fmN" value="${esc(f ? f.name : "Семья " + ((p.name || "").split(" ")[0] || ""))}"></label>
        <label class="fl">Семейная скидка, %<input class="input" id="fmD" type="number" min="0" max="50" value="${f ? f.discount : 0}"></label></div>
      ${f ? `<h4 class="sub-h">В семье</h4><div class="fm-list">${f.members.map(m => `<div>${esc(m.name)}${m.id === p.id ? ' <span class="muted">(этот пациент)</span>' : ""}</div>`).join("")}</div>` : ""}
      <label class="fl">Добавить члена семьи<div class="pat-pick"><input class="input" id="fmQ" placeholder="ФИО или телефон" autocomplete="off"><div class="pp-list" id="fmR"></div></div></label>
      <div id="fmAdd" class="muted"></div></div>
    <div class="m-f">${f ? `<button class="btn ghost small danger" id="fmLeave">Убрать из семьи</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="fmSave">Сохранить</button></div>`);
  const add = [], names = [];
  let t; $("#fmQ", box).oninput = e => { clearTimeout(t); t = setTimeout(async () => {
    const rows = e.target.value.trim() ? await api.search(e.target.value) : [];
    $("#fmR", box).innerHTML = rows.filter(r => r.id !== p.id).slice(0, 6).map(r => `<div class="pp-row" data-id="${esc(r.id)}" data-n="${esc(r.name)}"><span class="av">${esc(initials(r.name))}</span><span><b>${esc(r.name)}</b><small>${esc(r.phone || "")}</small></span></div>`).join("");
    $$("#fmR .pp-row", box).forEach(r => r.onclick = () => {
      if (!add.includes(r.dataset.id)) { add.push(r.dataset.id); names.push(r.dataset.n); }
      $("#fmAdd", box).textContent = "Будут добавлены: " + names.join(", ");
      $("#fmR", box).innerHTML = ""; e.target.value = "";
    });
  }, 150); };
  $("#fmSave", box).onclick = async () => {
    try { await api.family_save({id: f ? f.id : null, name: $("#fmN", box).value, discount: $("#fmD", box).value, add: [...(f ? [] : [p.id]), ...add]}); closeModal(); toast("Семья сохранена"); P = await api.patient(p.id); renderPatient(S.patientTab); }
    catch (e) { toast(errText(e), true); }
  };
  const lv = $("#fmLeave", box);
  if (lv) lv.onclick = async () => { if (await ask("Убрать пациента из семьи?", {ok: "Убрать", text: "Накопленные бонусы останутся у семьи."})) { await api.family_leave(p.id); closeModal(); P = await api.patient(p.id); renderPatient(S.patientTab); } };
}
/** Invoice editor: offer the family discount when the invoice has none. */
function familyDiscountHint(box, pat) {
  if (!pat || !pat.family || !pat.family.discount) return;
  const inp = $("#ivDisc", box); if (!inp || +inp.value) return;
  const hint = document.createElement("button"); hint.className = "linkbtn fam-disc"; hint.type = "button";
  hint.textContent = `Семейная скидка ${pat.family.discount}% — применить`;
  hint.onclick = () => { inp.value = pat.family.discount; inp.dispatchEvent(new Event("input")); hint.remove(); };
  inp.closest("label").appendChild(hint);
}

/* ---------------------------------------------------------------- settings */
async function loadMoneySettings() {
  const box = $("#loyalBody"); if (!box) return;
  const [s, q] = await Promise.all([api.loyalty_settings().catch(() => null), api.sbp_settings().catch(() => null)]);
  if (!s) return;
  box.innerHTML = `<div class="form"><label>Начислять бонусов, % от оплаты<input class="input" id="lyP" type="number" min="0" max="30" value="${s.bonus_percent}"></label>
      <label>Бонусами можно оплатить до, % счёта<input class="input" id="lyS" type="number" min="0" max="100" value="${s.bonus_max_share}"></label>
      <label>Сертификат действует, месяцев<input class="input" id="lyM" type="number" min="1" max="60" value="${s.cert_months}"></label></div>
    <p class="hint">0 % — бонусы не начисляются. Бонусы начисляются с оплат наличными, картой, переводом и по СБП.</p>
    <h4 class="sub-h">Оплата по СБП</h4>
    <div class="sbp-set">${q && q.qr ? `<img alt="QR-код СБП" src="${q.qr}">` : `<span class="muted">QR-код не загружен</span>`}
      <div><label class="btn ghost small">Загрузить QR-код (картинка из банка)<input type="file" id="sbpF" accept="image/png,image/jpeg" hidden></label>
      <label class="fl">Подпись под QR-кодом<input class="input" id="sbpL" value="${esc(q ? q.label : "")}" placeholder="Например: получатель ООО «…», банк …"></label></div></div>
    <p class="hint">Возьмите в банке статический QR-код СБП клиники. Программа показывает его пациенту на экране или на планшете вместе с суммой; после поступления денег нажмите «Принять оплату» со способом «СБП».</p>
    <div class="row"><button class="btn" id="lySave">Сохранить</button><span class="msg" id="lyMsg"></span></div>`;
  let qr = q ? q.qr : "";
  $("#sbpF", box).onchange = async e => { const f = e.target.files[0]; if (!f) return; if (f.size > 2e6) return toast("Картинка больше 2 МБ", true); qr = await blobB64(f); $(".sbp-set", box).firstElementChild.outerHTML = `<img alt="QR-код СБП" src="${qr}">`; };
  $("#lySave", box).onclick = async () => {
    try { await api.loyalty_settings_save({bonus_percent: $("#lyP", box).value, bonus_max_share: $("#lyS", box).value, cert_months: $("#lyM", box).value});
      await api.sbp_settings_save({qr, label: $("#sbpL", box).value}); toast("Сохранено"); }
    catch (e) { const m = $("#lyMsg", box); m.textContent = errText(e); m.className = "msg bad"; }
  };
}
