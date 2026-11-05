"use strict";
/* Documents from templates: pick -> fill (auto data + few inputs) -> preview -> save / print */

function numWords(n) {
  n = Math.floor(Math.abs(+n || 0));
  if (n === 0) return "ноль рублей";
  const ones = [["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"], ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]];
  const teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"];
  const tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"];
  const hund = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"];
  const groups = [["", "", "", 0], ["тысяча", "тысячи", "тысяч", 1], ["миллион", "миллиона", "миллионов", 0]];
  const out = [];
  let g = 0;
  while (n > 0 && g < 3) {
    const x = n % 1000; n = Math.floor(n / 1000);
    if (x) {
      const w = [hund[Math.floor(x / 100)]], t = x % 100;
      if (t >= 10 && t < 20) w.push(teens[t - 10]); else { w.push(tens[Math.floor(t / 10)]); w.push(ones[groups[g][3]][t % 10]); }
      if (g) w.push(plural(x, groups[g][0], groups[g][1], groups[g][2]));
      out.unshift(w.filter(Boolean).join(" "));
    }
    g++;
  }
  const total = Math.floor(Math.abs(arguments[0]));
  return out.join(" ") + " " + plural(total, "рубль", "рубля", "рублей");
}

function servicesTable(inv) {
  if (!inv || !inv.items || !inv.items.length) return `<p><i>Услуги не выбраны — выставьте счёт или план лечения.</i></p>`;
  return `<table class="dtab"><tr><th>№</th><th>Код</th><th>Услуга</th><th>Зуб</th><th>Кол-во</th><th>Цена, ₽</th><th>Скидка</th><th>Сумма, ₽</th></tr>${
    inv.items.map((it, i) => `<tr><td>${i + 1}</td><td>${esc(it.code || "")}</td><td>${esc(it.title)}</td><td>${esc(it.tooth || "")}</td><td>${esc(it.qty || 1)}</td>
      <td>${(+it.price).toLocaleString("ru-RU")}</td><td>${it.discount ? esc(it.discount) + "%" : ""}</td><td>${(+it.sum || 0).toLocaleString("ru-RU")}</td></tr>`).join("")}
    ${inv.discount ? `<tr><td colspan="7" style="text-align:right">Скидка на счёт</td><td>${esc(inv.discount)}%</td></tr>` : ""}
    <tr><td colspan="7" style="text-align:right"><b>Итого</b></td><td><b>${(+inv.total).toLocaleString("ru-RU")}</b></td></tr></table>`;
}

function renderDoc(body, ctx, inputs) {
  const rec = ctx.record || {};
  const diag = (rec.diagnoses || []).map(x => `${x.tooth ? "зуб " + x.tooth + " — " : ""}${x.code} ${x.title}`).join("; ");
  const vals = {
    "patient.fio": ctx.patient.fio, "patient.birth": ctx.patient.birth ? fmtDate(ctx.patient.birth).replace(/ \d{4}$/, m => m) : "",
    "patient.phone": ctx.patient.phone, "patient.address": ctx.patient.address, "patient.card": ctx.patient.card,
    "doctor.fio": ctx.doctor.fio, "doctor.position": ctx.doctor.position,
    "today": fmtDate(iso(new Date())), "visit.date": ctx.visit.date ? fmtDate(ctx.visit.date) : fmtDate(iso(new Date())),
    "record.complaints": rec.complaints, "record.anamnesis": rec.anamnesis, "record.objective": rec.objective,
    "record.diagnoses": diag, "record.treatment": rec.treatment, "record.recommendations": rec.recommendations,
    "invoice.total": ctx.invoice ? (+ctx.invoice.total).toLocaleString("ru-RU") : "0",
    "invoice.total_words": numWords(ctx.invoice ? ctx.invoice.total : 0),
  };
  for (const [k, v] of Object.entries(ctx.clinic || {})) vals["clinic." + k] = v;
  let i = 0;
  const recTable = () => !(ctx.records_full || []).length ? `<p><i>Записей в медкарте пока нет.</i></p>` :
    `<table class="dtab"><tr><th style="width:90px">Дата</th><th>Жалобы, анамнез, осмотр, диагноз, лечение</th><th style="width:130px">Врач</th></tr>${
      ctx.records_full.slice().reverse().map(r => { const d = r.data || {}; const dg = (d.diagnoses || []).map(x => `${x.tooth ? "зуб " + x.tooth + " — " : ""}${x.code} ${x.title}`).join("; ");
        return `<tr><td>${esc(fmtDate(r.date))}</td><td>${[["Жалобы", d.complaints], ["Анамнез", d.anamnesis], ["Объективно", d.objective], ["Диагноз", dg], ["Лечение", d.treatment], ["Рекомендации", d.recommendations]]
          .filter(x => x[1]).map(([k, v]) => `<b>${k}:</b> ${esc(v)}`).join("<br>")}</td><td>${esc(r.doctor_name || "")}</td></tr>`; }).join("")}</table>`;
  return body
    .replace(/\{\{table:records\}\}/g, recTable)
    .replace(/\{\{table:services\}\}/g, () => servicesTable(ctx.invoice))
    .replace(/\{\{input:([^|}]+)\|?([^}]*)\}\}/g, (_, label) => { const v = inputs[i++]; return v ? esc(v) : `<span class="blank">${"&nbsp;".repeat(18)}</span>`; })
    .replace(/\{\{([\w.]+)\}\}/g, (_, k) => { const v = vals[k]; return v ? esc(v) : `<span class="blank">${"&nbsp;".repeat(18)}</span>`; });
}

async function openDocPicker(ctx) {
  const list = await api.templates("document");
  const cats = {};
  list.forEach(t => (cats[t.category || "Прочее"] ||= []).push(t));
  const box = modal(`<div class="m-h"><h3>Создать документ</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${Object.entries(cats).map(([c, ts]) => `<div class="doc-cat"><div class="muted">${esc(c)}</div>${
      ts.map(t => `<button class="doc-pick" data-t="${esc(t.id)}"><svg viewBox="0 0 24 24"><path d="M6 3.5h9l4 4v13H6z"/><path d="M14.5 3.5V8H19"/></svg>${esc(t.title)}</button>`).join("")}</div>`).join("")}</div>
    <div class="m-f"><span class="muted">Шаблоны редактируются в разделе «Шаблоны и прайс»</span><button class="btn ghost" data-close>Закрыть</button></div>`);
  $$(".doc-pick", box).forEach(b => b.onclick = () => { closeModal(); openDocFill({...ctx, template_id: b.dataset.t}); });
}

async function openDocFill(o) {
  const [tpls, R] = await Promise.all([api.templates("document"), ref()]);
  const tpl = tpls.find(t => t.id === o.template_id);
  if (!tpl) return toast("Шаблон не найден", true);
  let ctx = await api.doc_context(o.patient_id, o.doctor_id || null, o.record_id || null, o.invoice_id || null, o.visit_id || null);
  const inputs = [...tpl.body.matchAll(/\{\{input:([^|}]+)\|?([^}]*)\}\}/g)].map(m => ({label: m[1].trim(), def: m[2]}));
  const usesRec = /record\./.test(tpl.body), usesInv = /table:services|invoice\./.test(tpl.body);
  const missingClinic = /clinic\./.test(tpl.body) && !(ctx.clinic && ctx.clinic.name);
  const box = modal(`<div class="m-h"><h3>${esc(tpl.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b doc-fill">
      <div class="df-form">
        <div class="muted">Данные пациента, врача и клиники подставлены автоматически.</div>
        ${missingClinic ? `<div class="warn-line">Не заполнены реквизиты клиники — <button class="linkbtn" id="dfClinic">заполнить</button></div>` : ""}
        <label class="fl">Врач<select class="input" id="dfDoc"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.name === ctx.doctor.fio ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        ${usesRec ? `<label class="fl">Запись медкарты<select class="input" id="dfRec">${ctx.records.map(r => `<option value="${esc(r.id)}" ${r.id === ctx.record_id ? "selected" : ""}>${fmtDate(r.date)} · ${esc(r.doctor_name || "")}</option>`).join("") || '<option value="">нет записей — заполните медкарту</option>'}</select></label>` : ""}
        ${usesInv ? `<label class="fl">Счёт / план (услуги)<select class="input" id="dfInv">${ctx.invoices.map(i => `<option value="${esc(i.id)}" ${ctx.invoice && i.id === ctx.invoice.id ? "selected" : ""}>${fmtDT(i.created_at)} · ${money(i.total)}</option>`).join("") || '<option value="">нет счетов</option>'}</select>
          <button class="linkbtn" id="dfNewInv">+ составить список услуг</button></label>` : ""}
        ${inputs.map((x, i) => `<label class="fl">${esc(x.label)}<input class="input df-in" data-i="${i}" value="${esc(x.def)}"></label>`).join("")}
        <div class="muted" style="font-size:12px">Текст можно поправить прямо в предпросмотре справа — щёлкните по нему.</div>
      </div>
      <div class="df-prev"><div class="doc-page" id="dfPage" contenteditable="true"></div></div>
    </div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button>
      <button class="btn ghost" id="dfPrint">Печать</button><button class="btn" id="dfSave">Сохранить в карту</button></div>`, {wide: true});
  let edited = false;
  const page = $("#dfPage", box);
  page.oninput = () => edited = true;
  const draw = () => {
    if (edited && !confirm("Текст был изменён вручную. Пересобрать документ из шаблона? Ручные правки пропадут.")) return;
    edited = false;
    page.innerHTML = renderDoc(tpl.body, ctx, $$(".df-in", box).map(x => x.value.trim()));
  };
  const reload = async () => {
    ctx = await api.doc_context(o.patient_id, $("#dfDoc", box).value || null, $("#dfRec", box) ? $("#dfRec", box).value || null : null,
      $("#dfInv", box) ? $("#dfInv", box).value || null : null, o.visit_id || null);
    draw();
  };
  $$(".df-in", box).forEach(x => x.oninput = draw);
  ["#dfDoc", "#dfRec", "#dfInv"].forEach(s => { const el = $(s, box); if (el) el.onchange = reload; });
  const ni = $("#dfNewInv", box); if (ni) ni.onclick = () => { const doc = $("#dfDoc", box).value; closeModal();
    openInvoice({patient_id: o.patient_id, visit_id: o.visit_id, doctor_id: doc, after: id => openDocFill({...o, doctor_id: doc, invoice_id: id}) }); };
  const cl = $("#dfClinic", box); if (cl) cl.onclick = () => { closeModal(); show("refs"); setRefTab("clinic"); };
  draw();
  $("#dfPrint", box).onclick = () => printDoc(page.innerHTML);
  $("#dfSave", box).onclick = async () => {
    await api.save_document({patient_id: o.patient_id, template_id: tpl.id, title: tpl.title, html: page.innerHTML,
      data: {inputs: $$(".df-in", box).map(x => x.value)}});
    closeModal(); toast("Документ сохранён в карту пациента"); afterChange();
  };
}

async function openDocument(did) {
  const d = await api.document(did);
  if (!d) return;
  const box = modal(`<div class="m-h"><h3>${esc(d.title)} <span class="muted" style="font-weight:400;font-size:13px">от ${fmtDT(d.created_at)}</span></h3><button class="x" data-close>×</button></div>
    <div class="m-b doc-view"><div class="doc-page" id="dvPage" contenteditable="true">${d.html}</div></div>
    <div class="m-f"><button class="btn ghost small danger" id="dvDel">Удалить</button><span class="muted">Можно поправить текст и сохранить</span>
      <button class="btn ghost" id="dvSave">Сохранить правки</button><button class="btn" id="dvPrint">Печать</button></div>`, {wide: true});
  $("#dvPrint", box).onclick = () => printDoc($("#dvPage", box).innerHTML);
  $("#dvSave", box).onclick = async () => { await api.save_document({id: d.id, patient_id: d.patient_id, title: d.title, html: $("#dvPage", box).innerHTML}); toast("Сохранено"); afterChange(); };
  $("#dvDel", box).onclick = async () => { if (confirm("Удалить документ?")) { await api.delete_document(d.id); closeModal(); afterChange(); } };
}

function printDoc(html) {
  $("#printArea").innerHTML = `<div class="doc-page print">${html}</div>`;
  window.print();
}
