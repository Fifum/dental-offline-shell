"use strict";
/* Visit protocol / medical record editor. o = {patient_id, id?, visit_id?, doctor_id?, date?} */
const REC_FIELDS = [["complaints", "Жалобы"], ["anamnesis", "Анамнез"], ["objective", "Объективно (осмотр)"]];
const REC_FIELDS2 = [["treatment", "Проведённое лечение"], ["recommendations", "Рекомендации"]];
const UPPER = [[18, 17, 16, 15, 14, 13, 12, 11], [21, 22, 23, 24, 25, 26, 27, 28]];
const LOWER = [[48, 47, 46, 45, 44, 43, 42, 41], [31, 32, 33, 34, 35, 36, 37, 38]];

async function openRecord(o) {
  const R = await ref(true);
  const rec = o.id ? await api.record(o.id) : null;
  const pat = P && P.id === o.patient_id ? P : await api.patient(o.patient_id);
  const data = rec ? rec.data : {};
  const st = {diagnoses: (data.diagnoses || []).slice(), teeth: {...(pat.teeth_local || {}), ...(data.teeth || {})}, surf: {},
    rx: (data.rx || []).map(r => ({...r})), lastTooth: o.tooth || ""};
  for (const src of [pat.surf_local || {}, data.surf || {}]) for (const [t, ss] of Object.entries(src)) st.surf[t] = {...(st.surf[t] || {}), ...ss};
  const doctor = rec ? rec.doctor_id : o.doctor_id;
  const phr = cat => R.phrases.filter(x => x.category === cat);
  const field = ([k, title]) => `<div class="rf"><div class="rf-h"><label>${title}</label>
      <div class="chips">${phr(k).map(x => `<button class="chip" data-f="${k}" data-t="${esc(x.body)}" title="${esc(x.body)}">${esc(x.title)}</button>`).join("")}</div></div>
      <textarea class="input" id="rf_${k}" rows="${k === "treatment" ? 4 : 2}">${esc(data[k] || "")}</textarea></div>`;
  const box = modal(`
    <div class="m-h"><h3>Запись в медкарту · ${esc(pat.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b rec-grid">
      ${typeof dpDraft === "function" ? dpDraft("Диагнозы, лечение, рецепты и направления отсюда перенесите в медкарту Dentist Plus") : ""}
      <div class="allergy-bar" id="rAllergy" hidden></div>
      ${dictationBar()}
      <div class="ex-bar"><button class="btn ghost small" id="rExam">Шаблон приёма</button><span class="muted">Терапия, хирургия, ортопедия, ортодонтия, пародонтология, детская — заполнит поля, диагноз, зуб и назначения</span></div>
      <div class="ex-panel" id="rExamPanel" hidden></div>
      <div class="grid3">
        <label class="fl">Дата приёма<input class="input" type="date" id="rDate" value="${esc((rec && rec.date) || o.date || iso(new Date()))}"></label>
        <label class="fl">Врач<select class="input" id="rDoc"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === doctor ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        <span></span>
      </div>
      ${REC_FIELDS.map(field).join("")}
      <div class="rf"><div class="rf-h"><label>Зубная формула</label><span class="muted">Щёлкните по зубу: состояние и поверхности</span></div>
        <div class="tf" id="rTeeth"></div></div>
      <div class="rf"><div class="rf-h"><label>Диагноз (МКБ-10)</label></div>
        <div id="rDiag"></div>
        <div class="diag-add"><input class="input" id="rDiagQ" placeholder="Код или название, например K02.1 или кариес" list="rMkb" autocomplete="off">
          <input class="input" id="rDiagT" placeholder="Зуб" style="width:80px">
          <button class="btn ghost small" id="rDiagAdd">Добавить</button></div>
        <datalist id="rMkb">${R.mkb.map(([c, t]) => `<option value="${esc(c + " " + t)}">`).join("")}</datalist>
      </div>
      ${REC_FIELDS2.map(field).join("")}
      <div class="rf"><div class="rf-h"><label>Назначения</label><button class="linkbtn" id="rRxAdd">+ лекарство</button></div>
        <div id="rRx"></div><datalist id="rDrugs">${R.drugs.map(d => `<option value="${esc(d.data.name)}">`).join("")}</datalist></div>
      <label class="fl">Следующий визит / план<input class="input" id="rf_next_visit" value="${esc(data.next_visit || "")}" placeholder="Например: через 7 дней, продолжение эндолечения 36"></label>
    </div>
    <div class="m-f">${rec ? '<button class="btn ghost small danger" id="rDel">Удалить</button>' : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Отмена</button>
      <button class="btn ghost" id="rDpCopy" title="Текст по разделам формы Dentist Plus — вставьте в медкарту Dentist Plus">Скопировать для DP ▾</button>
      <button class="btn ghost" id="rSavePrint">Сохранить и документ ▾</button>
      <button class="btn" id="rSave">Сохранить</button></div>`, {wide: true});

  $$(".chip", box).forEach(c => c.onclick = () => {
    const ta = $("#rf_" + c.dataset.f, box); const v = ta.value.trim();
    ta.value = v ? v + (/[.!?]$/.test(v) ? " " : ". ") + c.dataset.t : c.dataset.t; ta.focus();
  });

  const drawTeeth = () => {
    const live = Object.fromEntries(Object.entries(st.surf).map(([t, ss]) => [t, Object.fromEntries(Object.entries(ss).filter(([, v]) => v))]));
    $("#rTeeth", box).innerHTML = formulaHtml(st.teeth, false, {sel: st.sel, surf: live});
    $$("#rTeeth .ft", box).forEach(b => b.onclick = e => toothMenu(b, e));
  };
  /* tooth editor: several states at once ("Имплант, Коронка") and marks on each of the five surfaces */
  const parts = v => String(v || "").split(/\s*[,;]\s*/).map(x => x.trim()).filter(Boolean);
  let paint = "Кариес";
  const toothMenu = (b, e) => {
    $$(".tmenu", box).forEach(x => x.remove());
    const n = b.dataset.n, m = document.createElement("div");
    m.className = "tmenu tedit";
    st.sel = n; st.lastTooth = n;
    const upper = [1, 2, 5, 6].includes(Math.floor(+n / 10));
    const place = () => {
      const tf = $("#rTeeth", box), cur = $(`#rTeeth .ft[data-n="${n}"]`, box);
      tf.appendChild(m);
      const fr = tf.getBoundingClientRect(), br = cur.getBoundingClientRect();
      m.style.left = Math.max(0, Math.min(br.left - fr.left, fr.width - m.offsetWidth)) + "px"; m.style.top = (br.bottom - fr.top + 4) + "px";
    };
    const draw = () => {
      const have = parts(st.teeth[n]), ss = st.surf[n] || {}, live = Object.fromEntries(Object.entries(ss).filter(([, v]) => v));
      m.innerHTML = `<b>Зуб ${n}</b>
        <div class="te-top"><div class="te-surf">${surfSvg(st.teeth[n] || "", upper, live, +n, true)}<small>${esc(surfText(live) || "Поверхности не отмечены")}</small></div>
          <div class="te-pick"><span class="muted" style="font-size:11.5px">Поверхность — щёлкните по схеме</span>
            ${SURF_STATES.map(x => `<button data-paint="${esc(x)}" class="${paint === x ? "on" : ""}">${esc(x)}</button>`).join("")}
            <button data-paint="" class="${paint === "" ? "on" : ""}">Стереть отметку</button></div></div>
        <span class="muted te-cap">Состояние зуба — можно выбрать несколько</span>
        <div class="te-sts">${R.tooth_statuses.map(x => `<button data-st="${esc(x)}" class="${have.includes(x) ? "on" : ""}">${esc(x)}</button>`).join("")}</div>
        <div class="te-foot"><button class="linkbtn" data-clear>Очистить зуб</button><button class="btn small" data-done>Готово</button></div>`;
      $$("[data-s]", m).forEach(el => el.addEventListener("click", ev => {
        ev.stopPropagation();
        const k = el.dataset.s, cur = (st.surf[n] ||= {});
        cur[k] = paint && cur[k] !== paint ? paint : "";
        changed();
      }));
    };
    const changed = () => {
      drawTeeth(); draw(); place();
      if ((st.teeth[n] || Object.values(st.surf[n] || {}).some(Boolean)) && !$("#rDiagT", box).value) $("#rDiagT", box).value = n;
    };
    m.onclick = ev => {
      ev.stopPropagation();
      const x = ev.target.closest("button"); if (!x) return;
      if (x.dataset.paint !== undefined) { paint = x.dataset.paint; draw(); return; }
      if (x.dataset.st) {
        let have = parts(st.teeth[n]);
        const v = x.dataset.st;
        if (have.includes(v)) have = have.filter(y => y !== v);
        else have = v === "Здоров" ? [v] : have.filter(y => y !== "Здоров").concat(v);
        if (have.length) st.teeth[n] = have.join(", "); else delete st.teeth[n];
        changed(); return;
      }
      if (x.dataset.clear !== undefined) { delete st.teeth[n]; if (st.surf[n]) Object.keys(st.surf[n]).forEach(k => st.surf[n][k] = ""); changed(); return; }
      if (x.dataset.done !== undefined) { m.remove(); st.sel = null; drawTeeth(); }
    };
    drawTeeth(); draw(); place();
    e.stopPropagation();
    setTimeout(() => document.addEventListener("click", function h(ev) { if (!m.isConnected || !m.contains(ev.target)) { if (m.isConnected) { m.remove(); st.sel = null; drawTeeth(); } document.removeEventListener("click", h); } }), 0);
  };
  const drawDiag = () => {
    $("#rDiag", box).innerHTML = st.diagnoses.map((x, i) => `<div class="dg"><b>${esc(x.code)}</b> ${esc(x.title)}${x.tooth ? ` <span class="pill">зуб ${esc(x.tooth)}</span>` : ""}<button data-i="${i}" title="Убрать">×</button></div>`).join("")
      || `<span class="muted">Диагноз не указан</span>`;
    $$("#rDiag button", box).forEach(b => b.onclick = () => { st.diagnoses.splice(+b.dataset.i, 1); drawDiag(); });
  };
  $("#rDiagAdd", box).onclick = () => {
    const v = $("#rDiagQ", box).value.trim(); if (!v) return;
    const m = v.match(/^([A-ZА-Я]\d{2}(?:\.\d{1,2})?)\s*(.*)$/i);
    let code = m ? m[1].toUpperCase().replace("К", "K") : "", title = m ? m[2] : v;
    const hit = R.mkb.find(([c, t]) => c === code) || (!code && R.mkb.find(([c, t]) => t.toLowerCase().includes(v.toLowerCase())));
    if (hit) { code = hit[0]; title = title || hit[1]; if (!m) title = hit[1]; }
    st.diagnoses.push({code, title, tooth: $("#rDiagT", box).value.trim()});
    $("#rDiagQ", box).value = ""; $("#rDiagT", box).value = ""; drawDiag();
  };
  $("#rDiagQ", box).onkeydown = e => { if (e.key === "Enter") $("#rDiagAdd", box).click(); };
  /* prescriptions: medicine (from the list or own), dose, how to take, how long */
  const drawRx = () => {
    $("#rRx", box).innerHTML = st.rx.length ? `<table class="tbl compact rx-t"><thead><tr><th>Лекарство</th><th>Доза</th><th>Как принимать</th><th>Сколько</th><th></th></tr></thead><tbody>${
      st.rx.map((r, i) => `<tr><td><input class="input sm" list="rDrugs" data-i="${i}" data-k="name" value="${esc(r.name || "")}" placeholder="Начните вводить название"></td>
        <td><input class="input sm" data-i="${i}" data-k="dose" value="${esc(r.dose || "")}"></td><td><input class="input sm" data-i="${i}" data-k="how" value="${esc(r.how || "")}"></td>
        <td><input class="input sm" data-i="${i}" data-k="days" value="${esc(r.days || "")}"></td><td><button class="linkbtn" data-rxdel="${i}" title="Убрать">×</button></td></tr>`).join("")}</tbody></table>`
      : `<span class="muted">Лекарства не назначены. Их можно выбрать из списка или вписать своё.</span>`;
    $$("#rRx input", box).forEach(x => x.oninput = () => { st.rx[+x.dataset.i][x.dataset.k] = x.value; if (x.dataset.k === "name") checkAllergy(); });
    $$("#rRx input[data-k=name]", box).forEach(x => x.onchange = () => {
      const r = st.rx[+x.dataset.i], d = R.drugs.find(y => y.data.name === x.value.trim());
      if (d && !r.dose && !r.how && !r.days) { Object.assign(r, d.data); drawRx(); }
    });
    $$("#rRx [data-rxdel]", box).forEach(b => b.onclick = () => { st.rx.splice(+b.dataset.rxdel, 1); drawRx(); checkAllergy(); });
  };
  $("#rRxAdd", box).onclick = () => { st.rx.push({name: "", dose: "", how: "", days: ""}); drawRx(); const l = $$("#rRx input[data-k=name]", box).pop(); if (l) l.focus(); };

  /* visit templates by speciality: fill the fields, diagnosis, tooth state and prescriptions in one click */
  const EX_SPECS = ["Терапия", "Хирургия", "Ортопедия", "Ортодонтия", "Пародонтология", "Детская"];
  let exSpec = "Терапия"; try { exSpec = localStorage.getItem("dd.exSpec") || exSpec; } catch (e) { /* private mode */ }
  const exTooth = () => st.lastTooth || $("#rDiagT", box).value.trim() || "";
  const drawExams = () => {
    const pn = $("#rExamPanel", box);
    const specs = [...new Set([...EX_SPECS, ...R.exams.map(x => x.category)])].filter(sp => R.exams.some(x => x.category === sp));
    if (!specs.includes(exSpec)) exSpec = specs[0] || "Терапия";
    const t = exTooth();
    pn.innerHTML = `<div class="seg ex-specs">${specs.map(sp => `<button data-sp="${esc(sp)}" class="${sp === exSpec ? "on" : ""}">${esc(sp)}</button>`).join("")}</div>
      <div class="ex-list">${R.exams.filter(x => x.category === exSpec).map(x => `<button class="ex-it" data-ex="${esc(x.id)}"><b>${esc(x.title)}</b>
        <small>${esc([(x.data.diagnoses || []).join(", "), (x.data.rx || []).length ? "назначений: " + x.data.rx.length : ""].filter(Boolean).join(" · "))}</small></button>`).join("")
        || `<span class="muted">В этом разделе шаблонов нет</span>`}</div>
      <div class="ex-foot"><span class="muted">${t ? `Зуб в тексте: <b>${esc(t)}</b> (выбран на формуле)` : "Сначала щёлкните по зубу на формуле — его номер подставится в текст"}</span>
        <button class="linkbtn" id="rExSave">Сохранить этот приём как шаблон</button></div>`;
    $$("[data-sp]", pn).forEach(b => b.onclick = () => { exSpec = b.dataset.sp; try { localStorage.setItem("dd.exSpec", exSpec); } catch (e) { /* ignore */ } drawExams(); });
    $$("[data-ex]", pn).forEach(b => b.onclick = () => applyExam(R.exams.find(x => x.id === b.dataset.ex)));
    $("#rExSave", pn).onclick = saveAsExam;
  };
  const applyExam = x => {
    const d = x.data || {}, tooth = exTooth();
    const fill = v => String(v || "").replace(/\{зуб\}/g, tooth || "____");
    for (const [k, v] of Object.entries(d.fields || {})) {
      const ta = $("#rf_" + k, box); if (!ta || !v) continue;
      const cur = ta.value.trim(), add = fill(v);
      if (cur.includes(add)) continue;
      ta.value = cur ? cur + (/[.!?]$/.test(cur) ? " " : ". ") + add : add;
      ta.classList.add("dict-filled"); setTimeout(() => ta.classList.remove("dict-filled"), 1600);
    }
    for (const code of d.diagnoses || []) {
      const hit = R.mkb.find(([c]) => c === code); if (!hit) continue;
      if (!st.diagnoses.some(y => y.code === code && String(y.tooth || "") === String(tooth))) st.diagnoses.push({code, title: hit[1], tooth});
    }
    if (tooth && d.tooth) (tooth.match(/\b[1-8][1-8]\b/g) || []).forEach(n => {
      /* the template says what the tooth is after the visit: treated diseases go, «Отсутствует» replaces everything */
      const add = String(d.tooth).split(/\s*,\s*/).filter(Boolean), cured = ["Здоров", "Кариес", "Пульпит", "Периодонтит", "Удалить", "Эндо-лечение", "Корень"];
      let have = String(st.teeth[n] || "").split(/\s*[,;]\s*/).filter(Boolean);
      have = add.includes("Отсутствует") ? [] : have.filter(y => !cured.includes(y) || add.includes(y));
      add.forEach(y => { if (!have.includes(y)) have.push(y); });
      st.teeth[n] = have.join(", ");
    });
    for (const r of d.rx || []) {
      const v = typeof r === "string" ? (R.drugs.find(y => y.data.name === r) || {data: {name: r}}).data : r;
      if (v && v.name && !st.rx.some(y => y.name === v.name)) st.rx.push({name: v.name, dose: v.dose || "", how: v.how || "", days: v.days || ""});
    }
    drawTeeth(); drawDiag(); drawRx(); checkAllergy();
    $("#rExamPanel", box).hidden = true;
    toast(`Шаблон «${x.title}» применён — проверьте текст${tooth ? "" : " и впишите номер зуба вместо «____»"}`);
  };
  const saveAsExam = async () => {
    const v = await askInput("Сохранить приём как шаблон", [{label: "Название шаблона", value: st.diagnoses[0] ? st.diagnoses[0].title : ""},
      {label: "Раздел (специальность)", value: exSpec}], {ok: "Сохранить"});
    if (!v) return;
    const tooth = exTooth(), re = tooth ? new RegExp(`\\b${tooth}\\b`, "g") : null;
    const fields = {};
    [...REC_FIELDS, ...REC_FIELDS2].forEach(([k]) => { const t = $("#rf_" + k, box).value.trim(); if (t) fields[k] = re ? t.replace(re, "{зуб}") : t; });
    if (!Object.keys(fields).length) return toast("Заполните хотя бы одно поле приёма", true);
    const body = {fields, diagnoses: [...new Set(st.diagnoses.map(y => y.code).filter(Boolean))],
      tooth: tooth && st.teeth[tooth] ? st.teeth[tooth] : "", rx: st.rx.filter(r => String(r.name || "").trim()).map(r => ({...r}))};
    try {
      const id = await api.save_template({kind: "exam", category: v[1].trim() || "Мои шаблоны", title: v[0].trim(), body: JSON.stringify(body)});
      R.exams.push({id, category: v[1].trim() || "Мои шаблоны", title: v[0].trim(), data: body}); REF = null;
      exSpec = v[1].trim() || "Мои шаблоны"; drawExams(); toast("Шаблон сохранён — он есть у всех врачей");
    } catch (e) { toast(errText(e), true); }
  };
  $("#rExam", box).onclick = () => { const pn = $("#rExamPanel", box); pn.hidden = !pn.hidden; if (!pn.hidden) drawExams(); };

  drawTeeth(); drawDiag(); drawRx();
  // allergy check: the patient's allergies against what is written in the treatment and recommendations
  let alT;
  const checkAllergy = () => { clearTimeout(alT); alT = setTimeout(async () => {
    const text = ["treatment", "recommendations", "objective"].map(k => $("#rf_" + k, box).value).join("\n") + "\n" + st.diagnoses.map(x => x.title).join("\n")
      + "\n" + st.rx.map(r => r.name).join("\n");
    try { allergyBar($("#rAllergy", box), await api.allergy_check(o.patient_id, text, $("#rf_anamnesis", box).value)); } catch (e) { /* not critical */ }
  }, 350); };
  ["treatment", "recommendations", "objective", "anamnesis"].forEach(k => $("#rf_" + k, box).addEventListener("input", checkAllergy));
  $$(".chip", box).forEach(c => c.addEventListener("click", checkAllergy));
  checkAllergy();
  attachDictation(box, o.patient_id, r => {
    setTimeout(checkAllergy, 50);
    st.source = st.source || new Set();  // 13.7: the record says it was made by dictation / with the AI
    st.source.add(r.mode === "visit" ? "visit" : "dictation"); if (r.engine === "ai") st.source.add("ai");
    for (const [k, v] of Object.entries(r.fields || {})) {
      const ta = $("#rf_" + k, box); if (!ta || !v) continue;
      const cur = ta.value.trim();
      ta.value = cur ? cur + (/[.!?]$/.test(cur) ? " " : ". ") + v : v;
      ta.classList.add("dict-filled"); setTimeout(() => ta.classList.remove("dict-filled"), 1600);
    }
    for (const d of r.diagnoses || []) if (!st.diagnoses.some(x => x.code === d.code && String(x.tooth || "") === String(d.tooth || ""))) st.diagnoses.push(d);
    Object.assign(st.teeth, r.teeth || {});
    drawTeeth(); drawDiag();
  }, {doctor: () => $("#rDoc", box).value});
  const formNow = () => {  // what the form says now (for the check and the memo), not saved
    const f = {patient_id: o.patient_id, visit_id: rec ? rec.visit_id : o.visit_id, date: $("#rDate", box).value, diagnoses: st.diagnoses,
      teeth: st.teeth, rx: st.rx, next_visit: $("#rf_next_visit", box).value.trim()};
    [...REC_FIELDS, ...REC_FIELDS2].forEach(([k]) => f[k] = $("#rf_" + k, box).value.trim());
    return f;
  };
  st.source = new Set((data.source || []));
  if (typeof aiRecordTools === "function") aiRecordTools({box, st, patient_id: o.patient_id, drawTeeth, form: formNow});
  if (o.tooth) { $("#rDiagT", box).value = o.tooth; const tb = $(`#rTeeth .ft[data-n="${o.tooth}"]`, box); if (tb) setTimeout(() => { tb.scrollIntoView({block: "center"}); tb.click(); }, 50); }

  const save = async () => {
    if ($("#rDiagQ", box).value.trim()) $("#rDiagAdd", box).click();
    const f = {id: rec ? rec.id : null, patient_id: o.patient_id, visit_id: rec ? rec.visit_id : o.visit_id, doctor_id: $("#rDoc", box).value,
      date: $("#rDate", box).value, diagnoses: st.diagnoses, teeth: st.teeth, surf: st.surf, rx: st.rx.filter(r => String(r.name || "").trim()), next_visit: $("#rf_next_visit", box).value.trim(),
      source: [...(st.source || [])]};
    [...REC_FIELDS, ...REC_FIELDS2].forEach(([k]) => f[k] = $("#rf_" + k, box).value.trim());
    return api.save_record(f);
  };
  $("#rDpCopy", box).onclick = e => { e.stopPropagation(); if (typeof dpEditorCopy === "function") dpEditorCopy(e.currentTarget, formNow); };  // 3.3
  const rSave = $("#rSave", box);
  rSave.onclick = () => busy(rSave, async () => { try { await save(); closeModal(); toast("Запись в медкарту сохранена"); afterChange(); } catch (e) { toast(errText(e), true); } });
  $("#rSavePrint", box).onclick = e => {
    e.stopPropagation();
    recDocMenu(e.currentTarget, [["doc_extract", "Выписка из медкарты"], ["doc_recipe", "Рецепт"], ["doc_referral", "Направление"], ["doc_memo", "Памятка пациенту"]], async tid => {
      try { const doc = $("#rDoc", box).value; const rid = await save(); closeModal(); afterChange();
        openDocFill({patient_id: o.patient_id, template_id: tid, record_id: rid, doctor_id: doc, visit_id: o.visit_id}); }
      catch (err) { toast(errText(err), true); }
    });
  };
  const del = $("#rDel", box); if (del) del.onclick = async () => { if (await ask("Удалить запись из медкарты?", {danger: true, ok: "Удалить", text: "Диагнозы и отметки на зубной формуле из этой записи тоже пропадут."})) { await api.delete_record(rec.id); closeModal(); afterChange(); } };
}


/* small menu above a button: [[value, label]] → pick(value) */
function recDocMenu(btn, items, pick) {
  $$(".rec-dmenu").forEach(x => x.remove());
  const m = document.createElement("div");
  m.className = "rec-dmenu";
  m.innerHTML = items.map(([v, t]) => `<button data-v="${esc(v)}">${esc(t)}</button>`).join("");
  document.body.appendChild(m);
  const r = btn.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  m.style.top = Math.max(8, r.top - m.offsetHeight - 6) + "px";
  m.onclick = e => { const b = e.target.closest("button"); if (!b) return; m.remove(); pick(b.dataset.v); };
  setTimeout(() => document.addEventListener("click", function h(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("click", h); } }), 0);
}
