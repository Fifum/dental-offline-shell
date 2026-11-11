"use strict";
/* Справка об оплате медицинских услуг для налогового вычета: from the patient card (Печать → «Справка для налоговой»). */
async function openTaxCert(p) {
  const y0 = new Date().getFullYear();
  let year = y0 - 1;
  const box = modal(`<div class="m-h"><h3>Справка для налогового вычета · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b tax-form">
      ${typeof addonDocKind === "function" && addonDocKind("taxcert") === "official" ? dpOfficial() : ""}
      <div class="grid3"><label class="fl">За год<select class="input" id="txY">${[0, 1, 2, 3].map(i => `<option ${y0 - i === year ? "selected" : ""}>${y0 - i}</option>`).join("")}</select></label>
        <span></span><button class="btn ghost small" id="txReg" type="button">Реестр справок за год</button></div>
      <div id="txPays" class="tax-pays">…</div>
      <h4 class="sub-h">Пациент</h4>
      <div class="grid3"><label class="fl">ФИО<input class="input" id="txPF" value="${esc(p.name)}"></label>
        <label class="fl">ИНН (12 цифр)<input class="input" id="txPI" inputmode="numeric"></label>
        <label class="fl">Дата рождения<input class="input" type="date" id="txPB" value="${esc(p.birth || "")}"></label></div>
      <label class="fl" id="txPDl">Паспорт (если нет ИНН): серия, номер, дата выдачи<input class="input" id="txPD"></label>
      <label class="switch-row"><input type="checkbox" id="txSame" checked><span class="sw"></span>Платил сам пациент (налогоплательщик и пациент — одно лицо)</label>
      <div id="txPayer" hidden><h4 class="sub-h">Налогоплательщик (кто оплатил, например родитель)</h4>
        <div class="grid3"><label class="fl">ФИО<input class="input" id="txF"></label><label class="fl">ИНН<input class="input" id="txI" inputmode="numeric"></label>
          <label class="fl">Дата рождения<input class="input" type="date" id="txB"></label></div>
        <label class="fl">Паспорт (если нет ИНН)<input class="input" id="txD"></label></div>
      <h4 class="sub-h">Суммы</h4>
      <div class="grid3"><label class="fl">Код услуги 1 (обычные), ₽<input class="input" id="txS1" inputmode="decimal"></label>
        <label class="fl">Код услуги 2 (дорогостоящие), ₽<input class="input" id="txS2" inputmode="decimal" value="0"></label>
        <label class="fl">Кто выдаёт справку<input class="input" id="txR" value="${esc((ME && ME.name) || "")}"></label></div>
      <p class="hint">Суммы взяты из оплат в этой программе за выбранный год. Оплаты, принятые в Dentist Plus, добавьте вручную. Код 2 — только для дорогостоящих видов лечения из перечня Правительства. Форму справки перед первой выдачей покажите бухгалтеру.</p>
    </div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="txGo">Выдать и распечатать</button></div>`, {wide: true});
  const load = async () => {
    year = +$("#txY", box).value;
    const d = await api.taxcert_data(p.id, year);
    $("#txS1", box).value = d.total ? String(d.total).replace(".", ",") : "";
    $("#txPays", box).innerHTML = (d.payments.length ? `Оплаты в программе за ${year} год: <b>${money(d.total)}</b> (${d.payments.length} ${plural(d.payments.length, "оплата", "оплаты", "оплат")})`
      : `<span class="muted">Оплат в программе за ${year} год нет — укажите сумму вручную.</span>`)
      + (d.issued.length ? `<div class="warn-line">За этот год уже выдано: ${d.issued.map(x => `№ ${x.number} от ${fmtDate(x.issued_at)} на ${money((x.sum1 || 0) + (x.sum2 || 0))}`).join("; ")}</div>` : "");
  };
  $("#txY", box).onchange = load;
  $("#txSame", box).onchange = e => { $("#txPayer", box).hidden = e.target.checked; };
  $("#txReg", box).onclick = () => openTaxRegister(+$("#txY", box).value);
  await load();
  $("#txGo", box).onclick = async () => {
    const v = id => $(id, box).value.trim();
    try {
      const r = await api.taxcert_issue({patient_id: p.id, year, patient_fio: v("#txPF"), patient_inn: v("#txPI"), patient_birth: v("#txPB"), patient_doc: v("#txPD"),
        payer_same: $("#txSame", box).checked, payer_fio: v("#txF"), payer_inn: v("#txI"), payer_birth: v("#txB"), payer_doc: v("#txD"),
        sum1: v("#txS1"), sum2: v("#txS2"), responsible: v("#txR")});
      closeModal(); toast(`Справка № ${r.number} за ${r.year} год выдана и сохранена в документах пациента`);
      printDoc(r.html, "taxcert");
      if (S.view === "patient" && P && P.id === p.id) { P = await api.patient(p.id); renderPatient(S.patientTab); }
    } catch (e) { toast(errText(e), true); }
  };
}

async function openTaxRegister(year) {
  const r = await api.taxcert_list(year);
  const box = modal(`<div class="m-h"><h3>Реестр справок для налогового вычета за ${year} год</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${r.rows.length ? `<div class="tbl-scroll"><table class="tbl compact" id="txRegT"><thead><tr><th>№</th><th>Дата</th><th>Налогоплательщик</th><th>ИНН</th><th>Пациент</th><th>Код 1, ₽</th><th>Код 2, ₽</th><th>Выдал</th></tr></thead><tbody>
      ${r.rows.map(x => `<tr><td>${x.number}</td><td class="nowrap">${esc(fmtDate(x.issued_at))}</td><td>${esc(x.payer_fio)}</td><td>${esc(x.payer_inn || "")}</td><td>${esc(x.payer_same ? "он же" : x.patient_fio)}</td>
        <td class="num">${money(x.sum1)}</td><td class="num">${money(x.sum2)}</td><td>${esc(x.issued_by || "")}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="5">Итого</td><td class="num">${money(r.total1)}</td><td class="num">${money(r.total2)}</td><td></td></tr></tfoot></table></div>`
      : `<div class="empty"><b>За ${year} год справок не выдавали</b></div>`}</div>
    <div class="m-f"><span class="muted"></span>${r.rows.length ? `<button class="btn ghost" data-xls="#txRegT" data-xls-name="Реестр справок для налогового вычета ${year}">Скачать в Excel</button>` : ""}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  return box;
}
