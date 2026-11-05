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
  const st = {diagnoses: (data.diagnoses || []).slice(), teeth: {...(pat.teeth_local || {}), ...(data.teeth || {})}};
  const doctor = rec ? rec.doctor_id : o.doctor_id;
  const phr = cat => R.phrases.filter(x => x.category === cat);
  const field = ([k, title]) => `<div class="rf"><div class="rf-h"><label>${title}</label>
      <div class="chips">${phr(k).map(x => `<button class="chip" data-f="${k}" data-t="${esc(x.body)}" title="${esc(x.body)}">${esc(x.title)}</button>`).join("")}</div></div>
      <textarea class="input" id="rf_${k}" rows="${k === "treatment" ? 4 : 2}">${esc(data[k] || "")}</textarea></div>`;
  const box = modal(`
    <div class="m-h"><h3>Запись в медкарту · ${esc(pat.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b rec-grid">
      <div class="grid3">
        <label class="fl">Дата приёма<input class="input" type="date" id="rDate" value="${esc((rec && rec.date) || o.date || iso(new Date()))}"></label>
        <label class="fl">Врач<select class="input" id="rDoc"><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === doctor ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        <span></span>
      </div>
      ${REC_FIELDS.map(field).join("")}
      <div class="rf"><div class="rf-h"><label>Зубная формула</label><span class="muted">Щёлкните по зубу, чтобы указать состояние</span></div>
        <div class="tf" id="rTeeth"></div></div>
      <div class="rf"><div class="rf-h"><label>Диагноз (МКБ-10)</label></div>
        <div id="rDiag"></div>
        <div class="diag-add"><input class="input" id="rDiagQ" placeholder="Код или название, например K02.1 или кариес" list="rMkb" autocomplete="off">
          <input class="input" id="rDiagT" placeholder="Зуб" style="width:80px">
          <button class="btn ghost small" id="rDiagAdd">Добавить</button></div>
        <datalist id="rMkb">${R.mkb.map(([c, t]) => `<option value="${esc(c + " " + t)}">`).join("")}</datalist>
      </div>
      ${REC_FIELDS2.map(field).join("")}
      <label class="fl">Следующий визит / план<input class="input" id="rf_next_visit" value="${esc(data.next_visit || "")}" placeholder="Например: через 7 дней, продолжение эндолечения 36"></label>
    </div>
    <div class="m-f">${rec ? '<button class="btn ghost small danger" id="rDel">Удалить</button>' : ""}<span class="muted"></span>
      <button class="btn ghost" data-close>Отмена</button>
      <button class="btn ghost" id="rSavePrint">Сохранить и выписка</button>
      <button class="btn" id="rSave">Сохранить</button></div>`, {wide: true});

  $$(".chip", box).forEach(c => c.onclick = () => {
    const ta = $("#rf_" + c.dataset.f, box); const v = ta.value.trim();
    ta.value = v ? v + (/[.!?]$/.test(v) ? " " : ". ") + c.dataset.t : c.dataset.t; ta.focus();
  });

  const drawTeeth = () => {
    const row = qs => `<div class="jaw">${qs.map((q, qi) => (qi ? '<span class="gap"></span>' : "") + q.map(n => {
      const s = st.teeth[n] || ""; return `<button class="tooth ${toothCls(s)}" data-n="${n}" title="${esc(s || "не указано")}"><b>${n}</b><small>${esc(s ? s.slice(0, 6) : "")}</small></button>`; }).join("")).join("")}</div>`;
    $("#rTeeth", box).innerHTML = row(UPPER) + row(LOWER);
    $$("#rTeeth .tooth", box).forEach(b => b.onclick = e => toothMenu(b, e));
  };
  const toothMenu = (b, e) => {
    $$(".tmenu", box).forEach(x => x.remove());
    const n = b.dataset.n, m = document.createElement("div");
    m.className = "tmenu";
    m.innerHTML = `<b>Зуб ${n}</b>` + R.tooth_statuses.map(s => `<button data-s="${esc(s)}">${esc(s)}</button>`).join("") + `<button data-s="" class="muted">Очистить</button>`;
    b.parentElement.appendChild(m);
    m.style.left = (b.offsetLeft) + "px"; m.style.top = (b.offsetTop + b.offsetHeight + 4) + "px";
    m.onclick = ev => { const x = ev.target.closest("button"); if (!x) return; if (x.dataset.s) st.teeth[n] = x.dataset.s; else delete st.teeth[n]; m.remove(); drawTeeth();
      if (x.dataset.s && !$("#rDiagT", box).value) $("#rDiagT", box).value = n; };
    e.stopPropagation();
    setTimeout(() => document.addEventListener("click", function h(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("click", h); } }), 0);
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
  drawTeeth(); drawDiag();
  if (o.tooth) { $("#rDiagT", box).value = o.tooth; const tb = $(`#rTeeth .tooth[data-n="${o.tooth}"]`, box); if (tb) setTimeout(() => { tb.scrollIntoView({block: "center"}); tb.click(); }, 50); }

  const save = async () => {
    if ($("#rDiagQ", box).value.trim()) $("#rDiagAdd", box).click();
    const f = {id: rec ? rec.id : null, patient_id: o.patient_id, visit_id: rec ? rec.visit_id : o.visit_id, doctor_id: $("#rDoc", box).value,
      date: $("#rDate", box).value, diagnoses: st.diagnoses, teeth: st.teeth, next_visit: $("#rf_next_visit", box).value.trim()};
    [...REC_FIELDS, ...REC_FIELDS2].forEach(([k]) => f[k] = $("#rf_" + k, box).value.trim());
    return api.save_record(f);
  };
  $("#rSave", box).onclick = async () => { try { await save(); closeModal(); toast("Запись в медкарту сохранена"); afterChange(); } catch (e) { toast(errText(e), true); } };
  $("#rSavePrint", box).onclick = async () => {
    try { const doc = $("#rDoc", box).value; const rid = await save(); closeModal(); afterChange();
      openDocFill({patient_id: o.patient_id, template_id: "doc_extract", record_id: rid, doctor_id: doc, visit_id: o.visit_id}); }
    catch (e) { toast(errText(e), true); }
  };
  const del = $("#rDel", box); if (del) del.onclick = async () => { if (confirm("Удалить запись из медкарты?")) { await api.delete_record(rec.id); closeModal(); afterChange(); } };
}
