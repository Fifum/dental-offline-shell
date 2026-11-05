"use strict";
/* Templates (documents, record phrases), price list, clinic requisites */
const PHRASE_CATS = {complaints: "Жалобы", anamnesis: "Анамнез", objective: "Объективно", treatment: "Лечение", recommendations: "Рекомендации"};
const CLINIC_FIELDS = [["name", "Название (как в документах)", "ООО «...»"], ["address", "Адрес", ""], ["phone", "Телефон", ""],
  ["inn", "ИНН", ""], ["ogrn", "ОГРН", ""], ["license", "Лицензия (номер и дата)", "№ ... от ..."], ["director", "Руководитель (в лице...)", "генерального директора ..."]];
const PLACEHOLDERS = ["patient.fio", "patient.birth", "patient.phone", "patient.address", "patient.card", "doctor.fio", "doctor.position",
  "clinic.name", "clinic.address", "clinic.inn", "clinic.ogrn", "clinic.license", "clinic.director", "clinic.phone", "today", "visit.date",
  "record.complaints", "record.anamnesis", "record.objective", "record.diagnoses", "record.treatment", "record.recommendations",
  "table:services", "table:records", "invoice.total", "invoice.total_words", "input:Название поля|значение"];
let REF_TAB = "docs";
function setRefTab(t) { REF_TAB = t; $$("#refTabs button").forEach(b => b.classList.toggle("on", b.dataset.r === t)); loadRefs(); }
$$("#refTabs button").forEach(b => b.onclick = () => setRefTab(b.dataset.r));

async function loadRefs() {
  const body = $("#refsBody");
  if (REF_TAB === "docs") {
    const list = await api.templates("document");
    body.innerHTML = `<div class="pb-head" style="padding:0 0 10px"><span class="muted">Встроенные тексты — общие черновики. Проверьте их с юристом клиники и поправьте под себя.</span>
      <button class="btn small" id="tNew">+ Новый шаблон</button></div>
      <div class="pbody"><table class="tbl"><thead><tr><th>Раздел</th><th>Название</th><th></th></tr></thead><tbody>${
      list.map(t => `<tr data-t="${esc(t.id)}"><td class="muted">${esc(t.category)}</td><td><b>${esc(t.title)}</b></td><td class="muted">${t.builtin ? "встроенный" : "свой"}</td></tr>`).join("")}</tbody></table></div>`;
    $("#tNew").onclick = () => editDocTemplate({kind: "document", category: "Прочее", title: "Новый документ", body: "<h2 style=\"text-align:center\">Заголовок</h2>\n<p>Пациент: {{patient.fio}}</p>"});
    $$("#refsBody tr[data-t]").forEach(tr => tr.onclick = () => editDocTemplate(list.find(x => x.id === tr.dataset.t)));
  } else if (REF_TAB === "phrases") {
    const list = await api.templates("phrase");
    body.innerHTML = Object.entries(PHRASE_CATS).map(([k, title]) => `<div class="pbody ph-group"><div class="pb-head"><b>${title}</b><button class="linkbtn" data-add="${k}">+ добавить фразу</button></div>
      ${list.filter(x => x.category === k).map(x => `<div class="ph"><span>${esc(x.body)}</span><button class="linkbtn" data-ed="${esc(x.id)}">изменить</button><button class="linkbtn danger" data-del="${esc(x.id)}">удалить</button></div>`).join("") || '<div class="muted" style="padding:8px 16px">Нет фраз</div>'}</div>`).join("");
    $$("#refsBody [data-add]").forEach(b => b.onclick = async () => { const t = prompt(`Новая фраза — ${PHRASE_CATS[b.dataset.add]}`); if (!t) return;
      await api.save_template({kind: "phrase", category: b.dataset.add, title: t.slice(0, 60), body: t}); REF = null; loadRefs(); });
    $$("#refsBody [data-ed]").forEach(b => b.onclick = async () => { const x = list.find(y => y.id === b.dataset.ed); const t = prompt("Фраза", x.body); if (!t) return;
      await api.save_template({...x, title: t.slice(0, 60), body: t}); REF = null; loadRefs(); });
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { if (confirm("Удалить фразу?")) { await api.delete_template(b.dataset.del); REF = null; loadRefs(); } });
  } else if (REF_TAB === "price") {
    const list = await api.services("");
    body.innerHTML = `<div class="pb-head" style="padding:0 0 10px"><span class="muted">${list.length} услуг. Если Dentist Plus отдаёт прайс через API, он подтянется сам; иначе импортируйте выгрузку из Excel (CSV: код; название; цена; раздел).</span>
      <label class="btn ghost small">Импорт CSV<input type="file" id="pCsv" accept=".csv,.txt" hidden></label><button class="btn small" id="pNew">+ Услуга</button></div>
      <div class="pbody"><table class="tbl compact"><thead><tr><th>Раздел</th><th>Код</th><th>Название</th><th>Цена</th><th></th></tr></thead><tbody>${
      list.map(s => `<tr><td class="muted">${esc(s.category)}</td><td>${esc(s.code)}</td><td>${esc(s.title)}</td><td><b>${money(s.price)}</b></td>
        <td><button class="linkbtn" data-ed="${esc(s.id)}">изменить</button> <button class="linkbtn danger" data-del="${esc(s.id)}">убрать</button></td></tr>`).join("")}</tbody></table></div>`;
    const edit = s => {
      const box = modal(`<div class="m-h"><h3>${s.id ? "Услуга" : "Новая услуга"}</h3><button class="x" data-close>×</button></div><div class="m-b">
        <label class="fl">Название<input class="input" id="sT" value="${esc(s.title || "")}" autofocus></label>
        <div class="grid3"><label class="fl">Код<input class="input" id="sC" value="${esc(s.code || "")}"></label>
        <label class="fl">Цена, ₽<input class="input" id="sP" type="number" value="${esc(s.price || 0)}"></label>
        <label class="fl">Раздел<input class="input" id="sG" value="${esc(s.category || "")}"></label></div></div>
        <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="sSave">Сохранить</button></div>`);
      $("#sSave", box).onclick = async () => { if (!$("#sT", box).value.trim()) return toast("Укажите название", true);
        await api.save_service({id: s.id, title: $("#sT", box).value.trim(), code: $("#sC", box).value.trim(), price: +$("#sP", box).value, category: $("#sG", box).value.trim(), source: s.source || "local"});
        closeModal(); loadRefs(); };
    };
    $("#pNew").onclick = () => edit({});
    $$("#refsBody [data-ed]").forEach(b => b.onclick = () => edit(list.find(x => x.id === b.dataset.ed)));
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { if (confirm("Убрать услугу из прайса?")) { await api.delete_service(b.dataset.del); loadRefs(); } });
    $("#pCsv").onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      const buf = await f.arrayBuffer();
      let text = new TextDecoder("utf-8").decode(buf);
      if (text.includes("�")) text = new TextDecoder("windows-1251").decode(buf);  // Excel CSV in Russian Windows
      const n = await api.import_services(text); toast(`Импортировано услуг: ${n}`); loadRefs();
    };
  } else if (REF_TAB === "clinic") {
    const s = await api.get_settings();
    const c = s.clinic || {};
    body.innerHTML = `<div class="panel" style="max-width:760px"><h3>Реквизиты клиники</h3><p class="hint">Подставляются в договоры, согласия, акты и выписки.</p>
      <div class="form">${CLINIC_FIELDS.map(([k, t, ph]) => `<label class="${k === "name" || k === "address" || k === "director" ? "wide" : ""}">${t}<input class="input" data-k="${k}" value="${esc(c[k] || "")}" placeholder="${esc(ph)}"></label>`).join("")}</div>
      <div class="row"><button class="btn" id="cSave">Сохранить</button></div></div>`;
    $("#cSave").onclick = async () => { const clinic = {}; $$("#refsBody [data-k]").forEach(i => clinic[i.dataset.k] = i.value.trim());
      await api.save_settings({clinic}); REF = null; toast("Реквизиты сохранены"); };
  }
}

function editDocTemplate(t) {
  const box = modal(`<div class="m-h"><h3>Шаблон документа</h3><button class="x" data-close>×</button></div>
    <div class="m-b tpl-ed">
      <div class="tpl-l">
        <div class="grid2"><label class="fl">Название<input class="input" id="teT" value="${esc(t.title)}"></label>
          <label class="fl">Раздел<input class="input" id="teC" value="${esc(t.category || "")}"></label></div>
        <label class="fl">Текст (HTML). Поля вставляются щелчком по подсказке ниже</label>
        <textarea class="input mono" id="teB" rows="18">${esc(t.body)}</textarea>
        <div class="chips">${PLACEHOLDERS.map(p => `<button class="chip" data-p="${esc(p)}">{{${esc(p)}}}</button>`).join("")}</div>
      </div>
      <div class="df-prev"><div class="doc-page" id="tePrev"></div></div>
    </div>
    <div class="m-f">${t.id && !t.builtin ? '<button class="btn ghost small danger" id="teDel">Удалить</button>' : ""}${t.builtin ? '<button class="btn ghost small" id="teReset">Вернуть исходный текст</button>' : ""}
      <span class="muted"></span><button class="btn ghost" data-close>Отмена</button>${t.id ? '<button class="btn ghost" id="teCopy">Сохранить как копию</button>' : ""}<button class="btn" id="teSave">Сохранить</button></div>`, {wide: true});
  const demoCtx = {patient: {fio: "Иванова Анна Сергеевна", birth: "1990-03-15", phone: "+7 900 000-00-00", address: "г. Москва, ул. Примерная, 1", card: "2026-001"},
    doctor: {fio: "Петров Пётр Петрович", position: "Стоматолог-терапевт"}, clinic: (REF && REF.clinic) || {}, visit: {date: iso(new Date())},
    record: {complaints: "Боль от холодного", diagnoses: [{code: "K02.1", title: "Кариес дентина", tooth: "36"}], treatment: "Пломба"},
    invoice: {items: [{code: "A16.07.002", title: "Лечение кариеса", qty: 1, price: 5500, sum: 5500}], total: 5500}};
  const ta = $("#teB", box);
  const prev = () => $("#tePrev", box).innerHTML = renderDoc(ta.value, demoCtx, []);
  ta.oninput = prev; prev();
  $$(".chip", box).forEach(c => c.onclick = () => { const s = ta.selectionStart; ta.value = ta.value.slice(0, s) + `{{${c.dataset.p}}}` + ta.value.slice(ta.selectionEnd); ta.focus(); prev(); });
  const save = async asCopy => { await api.save_template({id: asCopy ? null : t.id, kind: "document", title: $("#teT", box).value.trim() + (asCopy ? " (копия)" : ""),
    category: $("#teC", box).value.trim(), body: ta.value}); closeModal(); toast("Шаблон сохранён"); loadRefs(); };
  $("#teSave", box).onclick = () => save(false);
  const cp = $("#teCopy", box); if (cp) cp.onclick = () => save(true);
  const rs = $("#teReset", box); if (rs) rs.onclick = async () => { if (confirm("Вернуть исходный текст шаблона?")) { await api.reset_template(t.id); closeModal(); loadRefs(); } };
  const dl = $("#teDel", box); if (dl) dl.onclick = async () => { if (confirm("Удалить шаблон?")) { await api.delete_template(t.id); closeModal(); loadRefs(); } };
}
