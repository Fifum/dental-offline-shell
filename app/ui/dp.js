"use strict";
/* 3.3 «Без двойного ввода»: a record of the medical card made here goes to Dentist Plus by copy and paste.
   - «Скопировать для DP» — the whole record in the order of the Dentist Plus form; «По разделам» — one field at a time;
   - the mark «перенесено в Dentist Plus» (who and when; synced between the clinic's computers; in the action journal);
   - «Перенос» → «Медкарта» — what is not transferred, by day and doctor, a counter for the last 30 days, the reminder
     at the end of the day; «Сверка» — the program against the marks and against the visits of Dentist Plus.
   A doctor sees only own records; the director and «Отчёты» / «Перенос» — everyone's. */

/** Put text on the clipboard; true when it worked (the old way when the browser refuses the new one). */
async function dpClip(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* not allowed here — the old way */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}
const dpCanMark = () => canAny("transfer", "medcard_edit");
const dpWho = (by, at) => [by, at ? fmtDT(at) : ""].filter(Boolean).join(", ");

/** The whole saved record → clipboard (one click). `after(r)` gets the answer (marked automatically or not). */
async function dpCopyRecord(rid, after) {
  try {
    const r = await api.dp_copy(rid);
    if (r.empty) return toast("В записи нет текста для разделов Dentist Plus", true);
    if (!(await dpClip(r.text))) return dpShowText(r.text);
    toast(r.marked ? "Скопировано и отмечено «перенесено в Dentist Plus»" : "Скопировано — вставьте в медкарту Dentist Plus и отметьте «перенесено»");
    if (after) after(r);
  } catch (e) { toast(errText(e), true); }
}
/** When the clipboard is closed to the program: the text in a box to copy by hand. */
function dpShowText(text) {
  const box = modal(`<div class="m-h"><h3>Текст для Dentist Plus</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><p class="muted">Не удалось скопировать автоматически. Выделите текст (Ctrl+A) и скопируйте (Ctrl+C).</p>
      <textarea class="input dp-raw" rows="14" readonly>${esc(text)}</textarea></div>
    <div class="m-f"><span></span><button class="btn" data-close>Готово</button></div>`);
  const ta = $(".dp-raw", box); setTimeout(() => { ta.focus(); ta.select(); }, 40);
}

/** «По разделам»: every section of the record with its own copy button, then the mark. */
async function dpTransferModal(rid, after) {
  let rec, b;
  try { rec = await api.record(rid); b = await api.dp_text(rec.data || {}); } catch (e) { return toast(errText(e), true); }
  const marked = !!rec.transferred;
  const box = modal(`<div class="m-h"><h3>Перенос в Dentist Plus · ${esc(fmtDate(rec.date))}</h3><button class="x" data-close>×</button></div>
    <div class="m-b dp-modal">
      <p class="muted">Откройте приём пациента в Dentist Plus. Нажимайте «Копировать» у раздела и вставляйте в то же поле Dentist Plus (Ctrl+V).
        Порядок разделов — как в форме Dentist Plus; его можно поменять в настройках.</p>
      ${b.sections.map(s => `<div class="dp-sec ${s.text ? "" : "empty"}"><div class="dp-sec-h"><b>${esc(s.title)}</b>
          ${s.text ? `<button class="btn ghost small" data-sec="${esc(s.key)}">Копировать</button>` : `<span class="muted">пусто</span>`}</div>
          ${s.text ? `<div class="dp-sec-t">${esc(s.text)}</div>` : ""}</div>`).join("")}
    </div>
    <div class="m-f"><span class="muted dp-mk-who">${marked ? "Перенесено: " + esc(dpWho(rec.transferred_by, rec.transferred_at)) : ""}</span>
      <button class="btn ghost" id="dpAll" ${b.empty ? "disabled" : ""}>Скопировать всё</button>
      ${dpCanMark() ? `<button class="btn ${marked ? "ghost" : ""}" id="dpMarkBtn">${marked ? "Снять отметку" : "Перенесено в Dentist Plus"}</button>` : ""}
      <button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  $$("[data-sec]", box).forEach(btn => btn.onclick = async () => {
    const s = b.sections.find(x => x.key === btn.dataset.sec);
    if (!(await dpClip(s.text))) return toast("Не удалось скопировать — выделите текст и нажмите Ctrl+C", true);
    btn.textContent = "Скопировано ✓"; btn.classList.add("done");
    toast(`«${s.title}» скопировано — вставьте в Dentist Plus`);
    api.dp_copy(rid, s.key).catch(() => {});
  });
  $("#dpAll", box).onclick = async () => {
    if (!(await dpClip(b.text))) return toast("Не удалось скопировать — выделите текст и нажмите Ctrl+C", true);
    const r = await api.dp_copy(rid).catch(() => ({}));
    toast(r.marked ? "Скопировано и отмечено «перенесено в Dentist Plus»" : "Вся запись скопирована — вставьте в Dentist Plus");
    if (r.marked) { closeModal(); if (after) after(); }
  };
  const mb = $("#dpMarkBtn", box);
  if (mb) mb.onclick = async () => {
    try { await api.dp_mark([rid], !marked); closeModal(); toast(marked ? "Отметка снята" : "Отмечено: перенесено в Dentist Plus"); if (after) after(); refreshStatus(); }
    catch (e) { toast(errText(e), true); }
  };
}

/** The tools under a record in the patient card («Лечения»). */
function dpRecTools(r) {
  const done = !!r.transferred;
  return `<div class="dp-rt" data-dp-r="${esc(r.id)}">
    <button class="linkbtn" data-dp-copy="${esc(r.id)}" title="Вся запись по разделам формы Dentist Plus">Скопировать для DP</button>
    <button class="linkbtn" data-dp-secs="${esc(r.id)}" title="Копировать по одному разделу">по разделам</button>
    ${dpCanMark() ? `<label class="dp-mk" title="${done ? esc("Перенесено: " + dpWho(r.transferred_by, r.transferred_at)) : "Отметьте, когда запись внесена в Dentist Plus"}">
      <input type="checkbox" data-dp-mark="${esc(r.id)}" ${done ? "checked" : ""}>перенесено в Dentist Plus</label>` : ""}
    ${done && r.transferred_by ? `<small class="muted">${esc(dpWho(r.transferred_by, r.transferred_at))}</small>` : ""}
  </div>`;
}
function dpBindRecTools(root, reload) {
  $$("[data-dp-r]", root).forEach(el => el.addEventListener("click", e => e.stopPropagation()));
  $$("[data-dp-copy]", root).forEach(b => b.onclick = e => { e.preventDefault(); dpCopyRecord(b.dataset.dpCopy, r => { if (r.marked && reload) reload(); }); });
  $$("[data-dp-secs]", root).forEach(b => b.onclick = e => { e.preventDefault(); dpTransferModal(b.dataset.dpSecs, reload); });
  $$("[data-dp-mark]", root).forEach(cb => cb.onchange = async () => {
    try { await api.dp_mark([cb.dataset.dpMark], cb.checked); toast(cb.checked ? "Отмечено: перенесено в Dentist Plus" : "Отметка снята"); refreshStatus(); if (reload) reload(); }
    catch (e) { cb.checked = !cb.checked; toast(errText(e), true); }
  });
}

/** In the record editor: copy what is in the form now (saved or not) — whole or one section. */
async function dpEditorCopy(btn, form) {
  let b;
  try { b = await api.dp_text(form()); } catch (e) { return toast(errText(e), true); }
  if (b.empty) return toast("Заполните запись — копировать пока нечего", true);
  const items = [["*", "Всю запись"], ...b.sections.filter(s => s.text).map(s => [s.key, s.title])];
  recDocMenu(btn, items, async k => {
    const text = k === "*" ? b.text : b.sections.find(s => s.key === k).text;
    if (!(await dpClip(text))) return dpShowText(text);
    toast(k === "*" ? "Скопировано — вставьте в медкарту Dentist Plus, затем сохраните и отметьте «перенесено»" : "Раздел скопирован — вставьте в Dentist Plus");
  });
}

/* ------------------------------------------------------------ «Перенос» → «Медкарта» */
const DP = {from: "", to: "", doctor: "", done: false};
const dpDay = s => { const d = parseDay(s); return `${WD[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`; };

async function dpLoadPending(body) {
  let r;
  try { r = await api.dp_pending(DP.from || null, DP.to || null, DP.doctor || null, DP.done); }
  catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  DP.from = r.from; DP.to = r.to;
  const cnt = $("#jMedCnt"); if (cnt) { cnt.hidden = !r.count; cnt.textContent = r.count || ""; }
  if (!r.linked) {
    body.innerHTML = `<div class="empty"><b>Учётная запись не связана с врачом</b><span>Директор указывает врача в разделе «Сотрудники» — после этого здесь появятся ваши записи</span></div>`;
    return;
  }
  const head = `<div class="pbody dp-filter">
      <label class="fl">С<input class="input" type="date" id="dpFrom" value="${esc(r.from)}"></label>
      <label class="fl">По<input class="input" type="date" id="dpTo" value="${esc(r.to)}"></label>
      ${r.all ? `<label class="fl">Врач<select class="input" id="dpDoc"><option value="">Все врачи</option>${r.doctors.map(d => `<option value="${esc(d.id)}" ${String(d.id) === String(DP.doctor) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>` : ""}
      <label class="switch-row"><input type="checkbox" id="dpDone" ${DP.done ? "checked" : ""}><span class="sw"></span>Показать перенесённые</label>
      <button class="linkbtn" id="dpReset">последние ${r.days_back} дн.</button>
    </div>
    <div class="j-sum">${r.count ? `Не перенесено за ${r.days_back} дн.: <b>${r.count}</b>` : `За ${r.days_back} дн. всё перенесено`}${r.left !== r.count ? ` · в выбранном периоде: <b>${r.left}</b>` : ""}
      <span class="muted">${r.remind ? `Напоминание врачу — в ${esc(r.remind_time)}.` : "Напоминание выключено."} Сначала скопируйте запись, вставьте в Dentist Plus, затем отметьте.</span></div>
    ${r.all && r.by_doctor.length > 1 ? `<div class="dp-docs">${r.by_doctor.map(x => `<button class="chip" data-dpdoc="${esc(x.doctor_id || "")}">${esc(x.doctor_name)} · ${x.n}</button>`).join("")}</div>` : ""}`;
  const list = r.groups.length ? r.groups.map(g => `<div class="pbody j-group dp-day"><div class="pb-head"><b>${esc(dpDay(g.day))}</b></div>
      ${g.doctors.map(dg => `<div class="dp-doc-h"><span>${esc(dg.doctor_name)}</span>${dpCanMark() && dg.items.some(x => !x.transferred) ? `<button class="linkbtn" data-dpall="${esc(dg.items.filter(x => !x.transferred).map(x => x.id).join(","))}">отметить все</button>` : ""}</div>
        ${dg.items.map(x => `<div class="j-row dp-row ${x.transferred ? "done" : ""}">
          ${dpCanMark() ? `<input type="checkbox" data-dp-mark="${esc(x.id)}" ${x.transferred ? "checked" : ""} title="Перенесено в Dentist Plus">` : "<span></span>"}
          <span class="j-kind k-record">Медкарта</span>
          <span class="j-what"><b class="lnk" data-dp-pat="${esc(x.patient_id)}">${esc(x.patient_name || "Пациент")}</b><span>${esc(x.brief || (x.empty ? "пустая запись" : ""))}</span>
            <small class="pl ${x.transferred ? "ok" : x.copied_at ? "wait" : "manual"}">${x.transferred ? "✓ перенесено: " + esc(dpWho(x.transferred_by, x.transferred_at))
              : x.copied_at ? "скопировано " + esc(dpWho(x.copied_by, x.copied_at)) + " — отметьте, если уже вставили" : "ещё не копировали"}</small></span>
          <span class="dp-acts"><button class="btn ghost small" data-dp-copy="${esc(x.id)}" ${x.empty ? "disabled" : ""}>Скопировать для DP</button>
            <button class="linkbtn" data-dp-secs="${esc(x.id)}">по разделам</button>
            <button class="linkbtn" data-open-rec="${esc(x.id)}" data-p="${esc(x.patient_id)}">открыть</button></span>
        </div>`).join("")}`).join("")}</div>`).join("")
    : `<div class="empty"><svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg><b>Всё перенесено</b><span>Записи медкарты, которые нужно внести в Dentist Plus, появятся здесь</span></div>`;
  body.innerHTML = head + list;
  const reload = () => dpLoadPending(body);
  $("#dpFrom", body).onchange = e => { DP.from = e.target.value; reload(); };
  $("#dpTo", body).onchange = e => { DP.to = e.target.value; reload(); };
  const dsel = $("#dpDoc", body); if (dsel) dsel.onchange = () => { DP.doctor = dsel.value; reload(); };
  $("#dpDone", body).onchange = e => { DP.done = e.target.checked; reload(); };
  $("#dpReset", body).onclick = e => { e.preventDefault(); DP.from = DP.to = ""; reload(); };
  $$("[data-dpdoc]", body).forEach(b => b.onclick = () => { DP.doctor = b.dataset.dpdoc; reload(); });
  $$("[data-dpall]", body).forEach(b => b.onclick = async e => {
    e.preventDefault();
    const ids = b.dataset.dpall.split(",").filter(Boolean);
    if (!(await ask(`Отметить перенесёнными: ${ids.length}?`, {text: "Отмечайте, только если все эти записи уже внесены в Dentist Plus.", ok: "Отметить"}))) return;
    try { await api.dp_mark(ids, true); reload(); refreshStatus(); } catch (err) { toast(errText(err), true); }
  });
  dpBindRecTools(body, reload);
  $$("[data-open-rec]", body).forEach(b => b.onclick = e => { e.preventDefault(); openRecord({patient_id: b.dataset.p, id: b.dataset.openRec}); });
  $$("[data-dp-pat]", body).forEach(b => b.onclick = () => b.dataset.dpPat && openPatient(b.dataset.dpPat, "journal", "records"));
}

/* ------------------------------------------------------------ «Перенос» → «Сверка» */
const DPC = {from: "", to: "", doctor: ""};
async function dpLoadCheck(body) {
  let r;
  try { r = await api.dp_reconcile(DPC.from || null, DPC.to || null, DPC.doctor || null); }
  catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  DPC.from = r.from; DPC.to = r.to;
  const num = v => v === null || v === undefined ? "—" : esc(v);
  const dpCell = (v, ok) => typeof v === "number" || ok ? esc(v) : `<span class="dp-nodata">${esc(v)}</span>`;
  const row = x => x.key === "visits"
    ? `<tr><td><b>${esc(x.title)}</b><small class="muted">${esc(x.note)}</small></td><td>${num(x.dd)} <small class="muted">с записью</small></td><td>—</td>
        <td>${x.left ? `<b class="bad-t">${x.left}</b> <small class="muted">без записи</small>` : num(x.left)}</td><td>${dpCell(x.dp)}</td></tr>`
    : `<tr><td><b>${esc(x.title)}</b><small class="muted">${esc(x.note)}</small></td><td>${num(x.dd)}${x.sum !== undefined && x.dd ? ` <small class="muted">${money(x.sum)}</small>` : ""}</td>
        <td>${num(x.marked)}</td><td>${x.left ? `<b class="bad-t">${x.left}</b>` : "0"}</td><td>${dpCell(x.dp, x.dp_ok)}</td></tr>`;
  body.innerHTML = `<div class="pbody dp-filter">
      <label class="fl">С<input class="input" type="date" id="dcFrom" value="${esc(r.from)}"></label>
      <label class="fl">По<input class="input" type="date" id="dcTo" value="${esc(r.to)}"></label>
      <label class="fl">Врач<select class="input" id="dcDoc"><option value="">Все врачи</option>${r.doctors.map(d => `<option value="${esc(d.id)}" ${String(d.id) === String(DPC.doctor) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
      <button class="btn ghost small" id="dcPrint">Распечатать</button>
    </div>
    <div class="pbody"><table class="tbl dp-check"><thead><tr><th>Что</th><th>В программе</th><th>Отмечено «перенесено»</th><th>Не перенесено</th><th>В Dentist Plus</th></tr></thead>
      <tbody>${r.rows.map(row).join("")}</tbody></table>
      <div class="muted note-line">Счетов Dentist Plus в его API нет — «${esc(r.no_dp)}». Оплаты Dentist Plus загружаются за период синхронизации; чеки сверьте с кассой вручную.
        ${r.dp_span ? `Приёмы из Dentist Plus сохранены за ${esc(fmtDate(r.dp_span.from))} — ${esc(fmtDate(r.dp_span.to))}.` : ""}</div></div>
    <div class="pbody j-group"><div class="pb-head"><b>Записи медкарты не перенесены</b><span class="muted">${r.not_transferred_total}</span></div>
      ${r.not_transferred.length ? r.not_transferred.map(x => `<div class="dp-line"><span>${esc(fmtDate(x.date))}</span><b class="lnk" data-dp-pat="${esc(x.patient_id)}">${esc(x.patient_name || "Пациент")}</b>
        <span class="muted">${esc(x.doctor_name)}</span><span class="muted">${esc(x.brief)}</span><button class="linkbtn" data-dp-secs="${esc(x.id)}">перенести</button></div>`).join("")
        : `<div class="muted dp-none">Нет — всё отмечено перенесённым</div>`}</div>
    <div class="pbody j-group"><div class="pb-head"><b>Приёмы в Dentist Plus без записи медкарты в программе</b><span class="muted">${r.visits_without_record_total}</span></div>
      <div class="muted dp-none">Завершённые приёмы по данным Dentist Plus, для которых здесь нет записи медкарты. Если врач вёл медкарту сразу в Dentist Plus — это нормально.</div>
      ${r.visits_without_record.length ? r.visits_without_record.map(x => `<div class="dp-line"><span>${esc(fmtDT(x.start))}</span><b class="lnk" data-dp-pat="${esc(x.patient_id)}">${esc(x.patient_name || "Пациент")}</b>
        <span class="muted">${esc(x.doctor_name)}</span><span class="pill">${esc(x.status || "")}</span><span></span></div>`).join("") : ""}</div>`;
  const reload = () => dpLoadCheck(body);
  $("#dcFrom", body).onchange = e => { DPC.from = e.target.value; reload(); };
  $("#dcTo", body).onchange = e => { DPC.to = e.target.value; reload(); };
  $("#dcDoc", body).onchange = e => { DPC.doctor = e.target.value; reload(); };
  $("#dcPrint", body).onclick = () => {
    $("#printArea").innerHTML = `<h2>Сверка с Dentist Plus</h2><p>${esc(fmtDate(r.from))} — ${esc(fmtDate(r.to))}. Сформировано ${fmtDT(nowLocal())}</p>
      <table><tr><th>Что</th><th>В программе</th><th>Отмечено</th><th>Не перенесено</th><th>В Dentist Plus</th></tr>${r.rows.map(x =>
        `<tr><td>${esc(x.title)}</td><td>${num(x.dd)}</td><td>${num(x.marked)}</td><td>${num(x.left)}</td><td>${esc(x.dp)}</td></tr>`).join("")}</table>
      <h3>Не перенесено</h3><table>${r.not_transferred.map(x => `<tr><td>☐</td><td>${esc(fmtDate(x.date))}</td><td>${esc(x.patient_name)}</td><td>${esc(x.doctor_name)}</td><td>${esc(x.brief)}</td></tr>`).join("")}</table>`;
    window.print();
  };
  $$("[data-dp-secs]", body).forEach(b => b.onclick = e => { e.preventDefault(); dpTransferModal(b.dataset.dpSecs, reload); });
  $$("[data-dp-pat]", body).forEach(b => b.onclick = () => b.dataset.dpPat && openPatient(b.dataset.dpPat, "journal", "records"));
}

/* ------------------------------------------------------------ the counter and the reminder (every 3 s with the status) */
function dpStatus(st) {
  const d = st && st.dp; if (!d) return;
  if (!can("transfer")) {  // a doctor: the badge of «Перенос» counts own records not transferred
    const pb = $("#pendingBadge"); if (pb) { pb.hidden = !d.pending; pb.textContent = d.pending || ""; pb.title = `Не перенесено в Dentist Plus за ${d.days} дн.`; }
  }
  const cnt = $("#jMedCnt"); if (cnt) { cnt.hidden = !d.pending; cnt.textContent = d.pending || ""; }
  if (!d.remind || !ME || S.dpAsking) return;
  const key = "dd.dpRemind." + ME.login, today = iso(new Date());
  let seen = ""; try { seen = localStorage.getItem(key) || ""; } catch (e) { /* private mode */ }
  const [day, until] = seen.split("|");
  if (day === today && (!until || Date.now() < +until)) return;
  if (!$("#modal").hidden) return;  // the doctor is filling something in — ask on the next status
  S.dpAsking = true;
  ask("Перенесите записи в Dentist Plus", {icon: "warn", ok: "Открыть список", cancel: "Напомнить через час",
    text: `Сегодня не перенесено в медкарту Dentist Plus: ${d.remind} ${plural(d.remind, "запись", "записи", "записей")}.\nСкопируйте каждую кнопкой «Скопировать для DP», вставьте в Dentist Plus и отметьте «перенесено».`})
    .then(yes => {
      S.dpAsking = false;
      try { localStorage.setItem(key, yes ? today : `${today}|${Date.now() + 3600e3}`); } catch (e) { /* ignore */ }
      if (yes) { S.jTab = "med"; show("journal"); }
    });
}

/* ------------------------------------------------------------ Settings → Dentist Plus → «Перенос медкарты» */
async function loadDpSettings() {
  const box = $("#dpSetBody"); if (!box) return;
  let s;
  try { s = await api.dp_transfer_settings(); } catch (e) { box.innerHTML = `<div class="muted">${esc(errText(e))}</div>`; return; }
  const secs = s.sections.map(x => ({...x}));
  const draw = () => {
    box.innerHTML = `<p class="hint">Кнопка «Скопировать для DP» у записи медкарты собирает текст по разделам в порядке формы Dentist Plus. Включите нужные разделы,
        расставьте их как в вашей форме и при желании переименуйте. Настройки одинаковые на всех компьютерах клиники.</p>
      <div class="dp-secs-set">${secs.map((x, i) => `<div class="dp-ss"><label class="switch-row"><input type="checkbox" data-on="${i}" ${x.on ? "checked" : ""}><span class="sw"></span></label>
        <input class="input" data-title="${i}" value="${esc(x.title)}" placeholder="${esc(s.titles[x.key])}">
        <button class="ia" data-up="${i}" title="Выше" ${i ? "" : "disabled"}>↑</button><button class="ia" data-down="${i}" title="Ниже" ${i < secs.length - 1 ? "" : "disabled"}>↓</button></div>`).join("")}</div>
      <label class="switch-row"><input type="checkbox" id="dpsAuto" ${s.auto_mark ? "checked" : ""}><span class="sw"></span>Отмечать «перенесено» сразу после «Скопировать для DP» (всю запись)</label>
      <div class="form">
        <label>Напоминать врачу в<span class="pair"><input class="input" type="time" id="dpsTime" value="${esc(s.remind_time)}"><label class="switch-row" style="margin:0"><input type="checkbox" id="dpsRemind" ${s.remind ? "checked" : ""}><span class="sw"></span>включено</label></span></label>
        <label>Счётчик «не перенесено», дней<input class="input" type="number" id="dpsDays" min="1" max="365" value="${esc(s.days)}"></label>
      </div>
      <div class="row"><button class="btn" id="dpsSave" ${can("settings") ? "" : "disabled"}>Сохранить</button><span class="msg" id="dpsMsg"></span></div>`;
    $$("[data-on]", box).forEach(c => c.onchange = () => { secs[+c.dataset.on].on = c.checked; });
    $$("[data-title]", box).forEach(c => c.oninput = () => { secs[+c.dataset.title].title = c.value; });
    const move = (i, j) => { [secs[i], secs[j]] = [secs[j], secs[i]]; draw(); };
    $$("[data-up]", box).forEach(b => b.onclick = () => move(+b.dataset.up, +b.dataset.up - 1));
    $$("[data-down]", box).forEach(b => b.onclick = () => move(+b.dataset.down, +b.dataset.down + 1));
    $("#dpsSave", box).onclick = async () => {
      try {
        s = await api.dp_transfer_settings_save({sections: secs.map(x => ({key: x.key, title: x.title.trim() || s.titles[x.key], on: x.on})),
          auto_mark: $("#dpsAuto", box).checked, remind: $("#dpsRemind", box).checked, remind_time: $("#dpsTime", box).value, days: +$("#dpsDays", box).value});
        secs.splice(0, secs.length, ...s.sections.map(x => ({...x})));
        draw(); toast("Настройки переноса сохранены");
      } catch (e) { $("#dpsMsg", box).textContent = errText(e); }
    };
  };
  draw();
}
