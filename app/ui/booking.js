"use strict";
/* New appointment / move / edit. v = existing visit (from api.visit / day) or prefill {doctor_id, start, patient_id} */
async function openBooking(v = {}) {
  const R = await ref();
  const editing = !!v.id;
  const start = v.start || `${S.day} 10:00`;
  const dur = v.end ? Math.max(15, mins(v.end) - mins(v.start)) : 30;
  const docOpts = `<option value="">— врач —</option>` + R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === v.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("");
  const docBranch = id => (R.doctors.find(d => d.id === id) || {}).branch_id;
  const brSel = v.branch_id || docBranch(v.doctor_id) || S.branch;
  const brOpts = R.branches.map(b => `<option value="${esc(b.id)}" ${b.id === brSel ? "selected" : ""}>${esc(b.name)}</option>`).join("");
  const box = modal(`
    <div class="m-h"><h3>${editing ? "Перенос / изменение записи" : "Новая запись"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <label class="fl">Пациент</label>
      <div class="pat-pick" id="bkPat">
        ${v.patient_id ? `<div class="chosen"><span class="av">${esc(initials(v.patient_name))}</span><b>${esc(v.patient_name || v.patient_id)}</b>${editing ? "" : '<button class="linkbtn" id="bkChange">изменить</button>'}</div>` : ""}
        <div class="pp-search" ${v.patient_id ? "hidden" : ""}>
          <input class="input" id="bkQ" placeholder="ФИО или телефон" autocomplete="off" ${v.patient_id ? "" : "autofocus"}>
          <div class="pp-list" id="bkList"></div>
          <button class="linkbtn" id="bkNewP">+ Новый пациент</button>
          <div class="pp-new" id="bkNewForm" hidden>
            <div class="grid3"><input class="input" id="npL" placeholder="Фамилия"><input class="input" id="npF" placeholder="Имя"><input class="input" id="npM" placeholder="Отчество"></div>
            <div class="grid3"><input class="input" id="npPh" placeholder="Телефон"><input class="input" id="npB" type="date" title="Дата рождения"><select class="input" id="npG"><option value="">Пол</option><option>М</option><option>Ж</option></select></div>
          </div>
        </div>
      </div>
      <div class="grid3">
        <label class="fl">Дата<input class="input" type="date" id="bkDate" value="${start.slice(0, 10)}"></label>
        <label class="fl">Начало<input class="input" type="time" id="bkTime" step="300" value="${start.slice(11, 16)}"></label>
        <label class="fl">Длительность<select class="input" id="bkDur">${[15, 30, 45, 60, 75, 90, 120, 150, 180].map(m => `<option value="${m}" ${m === dur ? "selected" : ""}>${m < 60 ? m + " мин" : (m / 60) + " ч" + (m % 60 ? "" : "")}</option>`).join("")}${[15, 30, 45, 60, 75, 90, 120, 150, 180].includes(dur) ? "" : `<option value="${dur}" selected>${dur} мин</option>`}</select></label>
      </div>
      <div class="grid2">
        <label class="fl">Врач<select class="input" id="bkDoc">${docOpts}</select></label>
        ${R.branches.length > 1 ? `<label class="fl">Филиал<select class="input" id="bkBr">${brOpts}</select></label>` : `<span></span>`}
      </div>
      <div class="grid2"><label class="fl">Кресло / кабинет<input class="input" id="bkChair" value="${esc(v.chair || "")}" placeholder="необязательно"></label><span></span></div>
      <label class="fl">Услуга / цель визита<input class="input" id="bkTitle" list="bkSvc" value="${esc(v.title || "")}" placeholder="Например: Лечение кариеса"></label>
      <datalist id="bkSvc"></datalist>
      <label class="fl">Комментарий<input class="input" id="bkCom" value="${esc(v.comment || "")}"></label>
      ${editing ? "" : `<div class="grid3 bk-rep"><label class="fl">Повторять<select class="input" id="bkRep"><option value="">не повторять</option>
        <option value="week">каждую неделю</option><option value="2weeks">каждые 2 недели</option><option value="4weeks">каждые 4 недели</option><option value="month">каждый месяц</option></select></label>
        <label class="fl" id="bkRepNL" hidden>Сколько раз всего<input class="input" id="bkRepN" type="number" min="2" max="24" value="4"></label><span class="muted bk-rep-hint" id="bkRepHint"></span></div>`}
      <div class="warn-line" id="bkWarn" hidden></div>
    </div>
    <div class="m-f"><span class="muted">Запись появится в расписании с пометкой «перенести в Dentist Plus»</span>
      <button class="btn ghost" data-close>Отмена</button><button class="btn" id="bkSave">${editing ? "Сохранить" : "Записать"}</button></div>`);
  let patientId = v.patient_id || null;
  api.services("").then(sv => $("#bkSvc", box).innerHTML = sv.map(s => `<option value="${esc(s.title)}">`).join(""));
  const q = $("#bkQ", box);
  let t;
  const search = async () => {
    const rows = await api.search(q.value);
    $("#bkList", box).innerHTML = rows.slice(0, 7).map(p => `<div class="pp-row" data-id="${esc(p.id)}" data-n="${esc(p.name)}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}${p.birth ? " · " + fmtDate(p.birth) : ""}</small></span></div>`).join("")
      || `<div class="muted" style="padding:8px">Не найдено — создайте нового пациента</div>`;
    $$(".pp-row", box).forEach(r => r.onclick = () => choose(r.dataset.id, r.dataset.n));
  };
  const choose = (id, name) => {
    patientId = id;
    $("#bkPat", box).innerHTML = `<div class="chosen"><span class="av">${esc(initials(name))}</span><b>${esc(name)}</b></div>`;
  };
  if (q) { q.oninput = () => { clearTimeout(t); t = setTimeout(search, 150); }; if (!v.patient_id) search(); }
  const ch = $("#bkChange", box); if (ch) ch.onclick = () => { patientId = null; $(".chosen", box).remove(); $(".pp-search", box).hidden = false; q.focus(); search(); };
  $("#bkNewP", box).onclick = () => { $("#bkNewForm", box).hidden = false; $("#bkList", box).hidden = true; patientId = null; $("#npL", box).focus();
    const parts = q.value.trim().split(/\s+/); if (parts[0] && !/\d/.test(parts[0])) { $("#npL", box).value = parts[0] || ""; $("#npF", box).value = parts[1] || ""; $("#npM", box).value = parts[2] || ""; }
    else if (parts[0]) $("#npPh", box).value = q.value; };

  const checkOverlap = () => {
    const doc = $("#bkDoc", box).value, d = $("#bkDate", box).value, tm = $("#bkTime", box).value, du = +$("#bkDur", box).value;
    const w = $("#bkWarn", box); w.hidden = true;
    if (!doc || !d || !tm || d !== S.day || !S.dayData) return;
    const s = mins(`${d} ${tm}`), e = s + du;
    const clash = S.dayData.visits.find(x => x.doctor_id === doc && x.id !== v.id && stClass(x.status) !== "st-cancel" && mins(x.start) < e && (mins(x.end) || mins(x.start) + 30) > s);
    if (clash) { w.hidden = false; w.textContent = `У врача в это время уже есть запись: ${hm(clash.start)}–${hm(clash.end)} ${clash.patient_name || ""}. Можно записать всё равно.`; }
  };
  ["#bkDoc", "#bkDate", "#bkTime", "#bkDur"].forEach(s => $(s, box).onchange = checkOverlap);
  $("#bkDoc", box).addEventListener("change", () => { const b = docBranch($("#bkDoc", box).value); if (b && $("#bkBr", box)) $("#bkBr", box).value = b; });
  checkOverlap();
  const rep = $("#bkRep", box);
  const repHint = () => {
    const on = !!rep.value; $("#bkRepNL", box).hidden = !on;
    const n = Math.max(2, Math.min(24, +$("#bkRepN", box).value || 0)), d = $("#bkDate", box).value;
    if (!on || !d) { $("#bkRepHint", box).textContent = ""; return; }
    const last = new Date(`${d}T12:00`);
    if (rep.value === "month") last.setMonth(last.getMonth() + n - 1); else last.setDate(last.getDate() + {week: 7, "2weeks": 14, "4weeks": 28}[rep.value] * (n - 1));
    $("#bkRepHint", box).textContent = `${n} ${plural(n, "запись", "записи", "записей")}, последняя ${fmtDate(iso(last))}`;
  };
  if (rep) { rep.onchange = repHint; $("#bkRepN", box).oninput = repHint; $("#bkDate", box).addEventListener("change", repHint); }

  $("#bkSave", box).onclick = async () => {
    try {
      if (!patientId) {
        const nf = $("#bkNewForm", box);
        if (nf && !nf.hidden) {
          if (!$("#npL", box).value.trim() || !$("#npF", box).value.trim()) return toast("Укажите фамилию и имя нового пациента", true);
          const np = await api.create_patient({lname: $("#npL", box).value, fname: $("#npF", box).value, mname: $("#npM", box).value,
            phone: $("#npPh", box).value, birth_date: $("#npB", box).value, gender: $("#npG", box).value});
          patientId = np.id;
        } else return toast("Выберите пациента", true);
      }
      const d = $("#bkDate", box).value, tm = $("#bkTime", box).value;
      if (!d || !tm) return toast("Укажите дату и время", true);
      const s = new Date(`${d}T${tm}`); const e = new Date(s.getTime() + (+$("#bkDur", box).value) * 60000);
      const fmt = x => `${iso(x)} ${pad(x.getHours())}:${pad(x.getMinutes())}`;
      const moved = editing && (fmt(s) !== v.start || $("#bkDoc", box).value !== (v.doctor_id || ""));
      const fv = {id: v.id || null, patient_id: patientId, doctor_id: $("#bkDoc", box).value, branch_id: $("#bkBr", box) ? $("#bkBr", box).value : (v.branch_id || S.branch || ""),
        start: fmt(s), end: fmt(e), title: $("#bkTitle", box).value.trim(), comment: $("#bkCom", box).value.trim(), chair: $("#bkChair", box).value.trim(),
        status: v.status && stClass(v.status) !== "st-cancel" ? v.status : "Запланирован",
        action: editing ? (v.local && v.action === "create" ? "create" : moved ? "move" : "edit") : "create"};
      let newId;
      if (rep && rep.value) {
        const r = await api.save_visit_series(fv, rep.value, +$("#bkRepN", box).value);
        newId = r.ids[0];
        closeModal();
        toast(`Записано ${r.ids.length} ${plural(r.ids.length, "визит", "визита", "визитов")} ${r.every}` +
          (r.clashes.length ? `. У врача уже есть записи в это время: ${r.clashes.map(x => fmtDate(x)).join(", ")}` : ""), !!r.clashes.length);
      } else {
        newId = await api.save_visit(fv);
        closeModal();
        toast(editing ? "Запись изменена" : "Пациент записан");
      }
      if (v.onSaved) try { await v.onSaved(newId); } catch (e) { /* the visit itself is saved */ }
      if (d !== S.day && S.view === "schedule") S.day = d;
      afterChange();
    } catch (e) { toast(errText(e), true); }
  };
}
