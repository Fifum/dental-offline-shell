"use strict";
/* Templates (documents, record phrases), price list, clinic requisites */
const PHRASE_CATS = {complaints: "Жалобы", anamnesis: "Анамнез", objective: "Объективно", treatment: "Лечение", recommendations: "Рекомендации"};
const CLINIC_FIELDS = [["name", "Название (как в документах)", "ООО «...»"], ["address", "Адрес", ""], ["phone", "Телефон", ""],
  ["inn", "ИНН", ""], ["kpp", "КПП (для организации)", ""], ["ogrn", "ОГРН", ""], ["license", "Лицензия (номер и дата)", "№ ... от ..."], ["director", "Руководитель (в лице...)", "генерального директора ..."]];
const PLACEHOLDERS = ["patient.fio", "patient.birth", "patient.phone", "patient.address", "patient.card", "doctor.fio", "doctor.position",
  "clinic.name", "clinic.address", "clinic.inn", "clinic.ogrn", "clinic.license", "clinic.director", "clinic.phone", "today", "visit.date",
  "record.complaints", "record.anamnesis", "record.objective", "record.diagnoses", "record.treatment", "record.recommendations",
  "table:services", "table:records", "table:rx", "rp:rx", "invoice.total", "invoice.total_words", "input:Название поля|значение"];
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
      ${list.filter(x => x.category === k).map(x => `<div class="ex-row"><span>${esc(x.body)}</span><button class="linkbtn" data-ed="${esc(x.id)}">изменить</button><button class="linkbtn danger" data-del="${esc(x.id)}">удалить</button></div>`).join("") || '<div class="muted" style="padding:8px 16px">Нет фраз</div>'}</div>`).join("");
    $$("#refsBody [data-add]").forEach(b => b.onclick = async () => { const v = await askInput(`Новая фраза — ${PHRASE_CATS[b.dataset.add]}`, [{label: "Текст фразы"}], {ok: "Добавить"}); if (!v) return; const t = v[0];
      await api.save_template({kind: "phrase", category: b.dataset.add, title: t.slice(0, 60), body: t}); REF = null; loadRefs(); });
    $$("#refsBody [data-ed]").forEach(b => b.onclick = async () => { const x = list.find(y => y.id === b.dataset.ed); const v = await askInput("Изменить фразу", [{label: "Текст фразы", value: x.body}]); if (!v) return; const t = v[0];
      await api.save_template({...x, title: t.slice(0, 60), body: t}); REF = null; loadRefs(); });
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { if (await ask("Удалить фразу?", {danger: true, ok: "Удалить"})) { await api.delete_template(b.dataset.del); REF = null; loadRefs(); } });
  } else if (REF_TAB === "exams") {
    const [list, R] = [await api.templates("exam"), await ref(true)];
    const parse = t => { try { return JSON.parse(t.body || "{}"); } catch (e) { return {}; } };
    const specs = [...new Set(["Терапия", "Хирургия", "Ортопедия", "Ортодонтия", "Пародонтология", "Детская", ...list.map(x => x.category)])];
    body.innerHTML = `<div class="pb-head" style="padding:0 0 10px"><span class="muted">Шаблон заполняет запись медкарты: поля, диагноз, состояние зуба и назначения. {зуб} в тексте заменяется номером выбранного зуба. Встроенные тексты — черновики, проверьте их с врачами.</span>
      <button class="btn ghost small" id="exBack">Вернуть встроенные</button><button class="btn small" id="exNew">+ Новый шаблон</button></div>
      ${specs.filter(sp => list.some(x => x.category === sp)).map(sp => `<div class="pbody ph-group"><div class="pb-head"><b>${esc(sp)}</b></div>
        ${list.filter(x => x.category === sp).map(x => { const d = parse(x); return `<div class="ex-row"><span><b>${esc(x.title)}</b>
          <small class="muted" style="display:block">${esc([(d.diagnoses || []).join(", "), d.tooth ? "зуб: " + d.tooth : "", (d.rx || []).length ? "назначений: " + d.rx.length : ""].filter(Boolean).join(" · "))}</small></span>
          <button class="linkbtn" data-ed="${esc(x.id)}">изменить</button><button class="linkbtn danger" data-del="${esc(x.id)}">${x.builtin ? "скрыть" : "удалить"}</button></div>`; }).join("")}</div>`).join("")
        || '<div class="empty"><b>Шаблонов нет</b><span>Нажмите «Вернуть встроенные» или создайте свой</span></div>'}`;
    const edit = x => {
      const d = x.id ? parse(x) : {fields: {}, diagnoses: [], tooth: "", rx: []};
      const rxNames = (d.rx || []).map(r => typeof r === "string" ? r : r.name);
      const own = (d.rx || []).filter(r => typeof r !== "string" && !R.drugs.some(y => y.data.name === r.name));
      const box = modal(`<div class="m-h"><h3>${x.id ? "Шаблон приёма" : "Новый шаблон приёма"}</h3><button class="x" data-close>×</button></div>
        <div class="m-b"><div class="grid2"><label class="fl">Раздел (специальность)<input class="input" id="exC" list="exSpecs" value="${esc(x.category || "Терапия")}"></label>
          <label class="fl">Название<input class="input" id="exT" value="${esc(x.title || "")}" placeholder="Например: Кариес дентина — пломба"></label></div>
          <datalist id="exSpecs">${specs.map(sp => `<option value="${esc(sp)}">`).join("")}</datalist>
          ${[...Object.entries(PHRASE_CATS)].map(([k, t]) => `<label class="fl">${t}<textarea class="input" rows="2" data-f="${k}">${esc((d.fields || {})[k] || "")}</textarea></label>`).join("")}
          <div class="grid2"><label class="fl">Диагнозы МКБ-10 (коды через запятую)<input class="input" id="exD" value="${esc((d.diagnoses || []).join(", "))}" placeholder="K02.1"></label>
          <label class="fl">Состояние зуба после приёма<input class="input" id="exS" value="${esc(d.tooth || "")}" placeholder="Пломба" list="exTs"></label></div>
          <datalist id="exTs">${R.tooth_statuses.map(t => `<option value="${esc(t)}">`).join("")}</datalist>
          <div class="fl">Назначения<div class="ex-rx">${R.drugs.map(y => `<label class="chk"><input type="checkbox" data-rx="${esc(y.data.name)}" ${rxNames.includes(y.data.name) ? "checked" : ""}> ${esc(y.data.name)}</label>`).join("")}</div>
            ${own.length ? `<span class="muted" style="font-size:12px">Ещё в шаблоне: ${esc(own.map(r => r.name).join(", "))}</span>` : ""}</div></div>
        <div class="m-f">${x.id ? `<button class="btn ghost small danger" id="exDel">${x.builtin ? "Скрыть" : "Удалить"}</button>` : ""}<span class="muted"></span>
          <button class="btn ghost" data-close>Отмена</button><button class="btn" id="exSave">Сохранить</button></div>`, {wide: true});
      $("#exSave", box).onclick = async () => {
        const fields = {}; $$("[data-f]", box).forEach(t => { if (t.value.trim()) fields[t.dataset.f] = t.value.trim(); });
        const codes = $("#exD", box).value.split(/[\s,;]+/).map(c => c.trim().toUpperCase().replace("К", "K")).filter(Boolean);
        const bad = codes.filter(c => !R.mkb.some(([m]) => m === c));
        if (bad.length) return toast(`Нет в справочнике МКБ-10: ${bad.join(", ")}`, true);
        const rx = $$("[data-rx]", box).filter(c => c.checked).map(c => c.dataset.rx).concat(own);
        try {
          await api.save_template({id: x.id || null, kind: "exam", category: $("#exC", box).value.trim() || "Мои шаблоны", title: $("#exT", box).value.trim(),
            body: JSON.stringify({fields, diagnoses: codes, tooth: $("#exS", box).value.trim(), rx})});
          closeModal(); REF = null; toast("Шаблон сохранён"); loadRefs();
        } catch (e) { toast(errText(e), true); }
      };
      const del = $("#exDel", box); if (del) del.onclick = async () => { if (await ask(x.builtin ? "Скрыть встроенный шаблон?" : "Удалить шаблон?", {danger: true, ok: x.builtin ? "Скрыть" : "Удалить", text: x.builtin ? "Вернуть его можно кнопкой «Вернуть встроенные»." : ""})) { await api.delete_template(x.id); closeModal(); REF = null; loadRefs(); } };
    };
    $("#exNew").onclick = () => edit({});
    $("#exBack").onclick = async () => { const n = await api.restore_templates("exam"); REF = null; toast(n ? `Возвращено шаблонов: ${n}` : "Все встроенные шаблоны на месте"); loadRefs(); };
    $$("#refsBody [data-ed]").forEach(b => b.onclick = () => edit(list.find(x => x.id === b.dataset.ed)));
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { const x = list.find(y => y.id === b.dataset.del);
      if (await ask(x.builtin ? "Скрыть встроенный шаблон?" : "Удалить шаблон?", {danger: true, ok: x.builtin ? "Скрыть" : "Удалить"})) { await api.delete_template(x.id); REF = null; loadRefs(); } });
  } else if (REF_TAB === "drugs") {
    const list = await api.templates("drug");
    const parse = t => { try { return JSON.parse(t.body || "{}"); } catch (e) { return {}; } };
    body.innerHTML = `<div class="pb-head" style="padding:0 0 10px"><span class="muted">Лекарства для назначений в медкарте, рецепта и памятки пациенту. Доза и способ приёма подставляются как заготовка — врач правит их на приёме.</span>
      <button class="btn ghost small" id="drBack">Вернуть встроенные</button><button class="btn small" id="drNew">+ Лекарство</button></div>
      <div class="pbody"><table class="tbl compact"><thead><tr><th>Лекарство</th><th>Доза</th><th>Как принимать</th><th>Сколько</th><th></th></tr></thead><tbody>${
      list.map(x => { const d = parse(x); return `<tr><td><b>${esc(d.name || x.title)}</b></td><td>${esc(d.dose || "")}</td><td>${esc(d.how || "")}</td><td>${esc(d.days || "")}</td>
        <td><button class="linkbtn" data-ed="${esc(x.id)}">изменить</button> <button class="linkbtn danger" data-del="${esc(x.id)}">${x.builtin ? "скрыть" : "удалить"}</button></td></tr>`; }).join("")
        || '<tr><td colspan="5" class="muted" style="padding:14px">Список пуст</td></tr>'}</tbody></table></div>`;
    const edit = async x => {
      const d = x.id ? parse(x) : {};
      const v = await askInput(x.id ? "Лекарство" : "Новое лекарство", [{label: "Название, форма, дозировка", value: d.name || ""}, {label: "Доза на приём", value: d.dose || "", required: false},
        {label: "Как принимать", value: d.how || "", required: false}, {label: "Сколько дней", value: d.days || "", required: false}], {ok: "Сохранить"});
      if (!v) return;
      try { await api.save_template({id: x.id || null, kind: "drug", category: "", title: v[0].trim(), body: JSON.stringify({name: v[0].trim(), dose: v[1].trim(), how: v[2].trim(), days: v[3].trim()})});
        REF = null; loadRefs(); } catch (e) { toast(errText(e), true); }
    };
    $("#drNew").onclick = () => edit({});
    $("#drBack").onclick = async () => { const n = await api.restore_templates("drug"); REF = null; toast(n ? `Возвращено: ${n}` : "Все встроенные лекарства на месте"); loadRefs(); };
    $$("#refsBody [data-ed]").forEach(b => b.onclick = () => edit(list.find(x => x.id === b.dataset.ed)));
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { const x = list.find(y => y.id === b.dataset.del);
      if (await ask(x.builtin ? "Скрыть лекарство из списка?" : "Удалить лекарство?", {danger: true, ok: x.builtin ? "Скрыть" : "Удалить", text: "В уже сделанных записях назначения останутся."})) { await api.delete_template(x.id); REF = null; loadRefs(); } });
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
    $$("#refsBody [data-del]").forEach(b => b.onclick = async () => { if (await ask("Убрать услугу из прайса?", {danger: true, ok: "Убрать", text: "В выставленных счетах услуга останется."})) { await api.delete_service(b.dataset.del); loadRefs(); } });
    $("#pCsv").onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      const buf = await f.arrayBuffer();
      let text = new TextDecoder("utf-8").decode(buf);
      if (text.includes("�")) text = new TextDecoder("windows-1251").decode(buf);  // Excel CSV in Russian Windows
      const n = await api.import_services(text); toast(`Импортировано услуг: ${n}`); loadRefs();
    };
  } else if (REF_TAB === "clinic") {
    const c = (await ref(true)).clinic || {};
    body.innerHTML = `<div class="panel" style="max-width:760px"><h3>Реквизиты клиники</h3><p class="hint">Подставляются в договоры, согласия, акты и выписки.</p>
      <div class="form">${CLINIC_FIELDS.map(([k, t, ph]) => `<label class="${k === "name" || k === "address" || k === "director" ? "wide" : ""}">${t}<input class="input" data-k="${k}" value="${esc(c[k] || "")}" placeholder="${esc(ph)}"></label>`).join("")}</div>
      <div class="row"><button class="btn" id="cSave">Сохранить</button></div></div>`;
    $("#cSave").onclick = async () => { const clinic = {}; $$("#refsBody [data-k]").forEach(i => clinic[i.dataset.k] = i.value.trim());
      await api.save_clinic(clinic); REF = null; toast("Реквизиты сохранены"); };
  }
}

/* editDocTemplate lives in tpl-editor.js (visual editor) */
