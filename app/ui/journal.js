"use strict";
/* Everything done in this app, to re-enter into Dentist Plus. */
const J_ICON = {patient: "Пациент", patient_edit: "Пациент", visit: "Запись", record: "Медкарта", document: "Документ", invoice: "Счёт", payment: "Оплата"};

/* 3.3: tabs — «Всё» (everything to re-enter, «Перенос в Dentist Plus»), «Медкарта: не перенесено» (a doctor sees own
   records), «Сверка» («Отчёты» / «Перенос») */
const J_TABS = {all: () => can("transfer"), med: () => canAny("transfer", "reports", "medcard_edit"), check: () => canAny("reports", "transfer")};
const J_SUB = {all: "Всё, что сделано в этой программе. Внесите в Dentist Plus и отметьте галочкой",
  med: "Записи медкарты: скопируйте для Dentist Plus, вставьте и отметьте «перенесено»",
  check: "Что есть в программе, что отмечено перенесённым и что известно из Dentist Plus"};
$$("#jTabs [data-jt]").forEach(b => b.onclick = () => { S.jTab = b.dataset.jt; loadJournal(); });
async function loadJournal() {
  if (!S.jTab || !(J_TABS[S.jTab] || (() => false))()) S.jTab = Object.keys(J_TABS).find(k => J_TABS[k]()) || "med";
  $$("#jTabs [data-jt]").forEach(b => b.classList.toggle("on", b.dataset.jt === S.jTab));
  $("#jAllTools").hidden = S.jTab !== "all";
  $("#jSub").textContent = J_SUB[S.jTab];
  if (S.jTab === "med") return dpLoadPending($("#journalBody"));
  if (S.jTab === "check") return dpLoadCheck($("#journalBody"));
  const items = await api.journal($("#jDone").checked);
  S.journal = items;
  if (!items.length) {
    $("#journalBody").innerHTML = `<div class="empty"><svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg><b>Всё перенесено</b><span>Здесь появится всё, что вы сделаете в программе без связи: записи, медкарты, документы, счета и оплаты</span></div>`;
    return;
  }
  const byPat = new Map();
  items.forEach(x => { const k = x.patient_id || "_"; if (!byPat.has(k)) byPat.set(k, {name: x.patient_name || "Без пациента", id: x.patient_id, items: []}); byPat.get(k).items.push(x); });
  const pending = items.filter(x => !x.transferred).length;
  const auto = S.status.transfer_mode === "auto";
  $("#journalBody").innerHTML = `<div class="j-mode ${auto ? "auto" : ""}">${auto
      ? `<b>Автоматическая отправка включена.</b> Пациенты, изменения карточек, записи на приём и записи медкарты, привязанные к визиту, уходят в Dentist Plus сами при подключении к интернету. Документы, счета и оплаты — вручную.`
      : `<b>Перенос вручную.</b> Внесите изменения в Dentist Plus и отметьте галочкой.`} <button class="linkbtn" id="jMode">изменить режим</button></div>
    <div class="j-sum">${pending ? `Осталось перенести: <b>${pending}</b>` : "Всё отмечено как перенесённое"}
      <span class="muted">Порядок: сначала новые пациенты, затем записи, медкарты, счета и оплаты.</span></div>` +
    [...byPat.values()].map(g => `<div class="pbody j-group">
      <div class="pb-head"><b class="j-pat" data-p="${esc(g.id || "")}">${esc(g.name)}</b>${g.id && g.id.startsWith("L-") ? '<span class="pill st-cancel">новый пациент — завести карту в DP</span>' : ""}
        <button class="linkbtn j-all" data-p="${esc(g.id || "_")}">отметить всё</button></div>
      ${g.items.map(x => `<label class="j-row ${x.transferred ? "done" : ""}">
        <input type="checkbox" data-t="${esc(x.table)}" data-id="${esc(x.id)}" ${x.transferred ? "checked" : ""}>
        <span class="j-kind k-${x.kind}">${J_ICON[x.kind]}</span>
        <span class="j-what"><b>${esc(x.what)}</b><span>${esc(x.details)}</span>${pushLine(x, auto)}</span>
        <span class="muted j-at">${fmtDT(x.at)}</span>
        ${x.kind === "document" ? `<button class="linkbtn" data-open-doc="${esc(x.id)}">открыть</button>` : ""}
        ${x.kind === "record" ? `<button class="linkbtn" data-open-rec="${esc(x.id)}" data-p="${esc(x.patient_id)}">открыть</button>` : ""}
      </label>`).join("")}</div>`).join("");
  $$("#journalBody input[type=checkbox]").forEach(cb => cb.onchange = async () => {
    await api.mark_transferred(cb.dataset.t, [cb.dataset.id], cb.checked);
    cb.closest(".j-row").classList.toggle("done", cb.checked);
    refreshStatus();
  });
  $$("#journalBody .j-all").forEach(b => b.onclick = async e => {
    e.preventDefault();
    const rows = S.journal.filter(x => (x.patient_id || "_") === b.dataset.p && !x.transferred);
    const by = {}; rows.forEach(x => (by[x.table] ||= []).push(x.id));
    for (const [t, ids] of Object.entries(by)) await api.mark_transferred(t, ids, true);
    loadJournal(); refreshStatus();
  });
  const jm = $("#jMode"); if (jm) jm.onclick = e => { e.preventDefault(); show("settings"); if (typeof settingsGo === "function") settingsGo("dp"); };
  $$("#journalBody [data-retry]").forEach(b => b.onclick = async e => { e.preventDefault(); await api.retry_push(b.dataset.t, b.dataset.retry); toast("Отправим ещё раз при следующей синхронизации"); loadJournal(); });
  $$("#journalBody [data-open-visit]").forEach(b => b.onclick = e => { e.preventDefault(); openVisit(b.dataset.openVisit); });
  $$("#journalBody [data-force]").forEach(b => b.onclick = async e => {
    e.preventDefault();
    if (!(await ask("Отправить запись несмотря на двойную запись?", {icon: "warn", ok: "Отправить", text: "У врача на это время в Dentist Plus уже есть другой пациент. Отправляйте, только если это действительно нужно (например, короткая консультация)."}))) return;
    await api.force_push(b.dataset.force); toast("Отправим при следующей синхронизации"); loadJournal();
  });
  $$("#journalBody [data-open-doc]").forEach(b => b.onclick = e => { e.preventDefault(); openDocument(b.dataset.openDoc); });
  $$("#journalBody [data-open-rec]").forEach(b => b.onclick = e => { e.preventDefault(); openRecord({patient_id: b.dataset.p, id: b.dataset.openRec}); });
  $$("#journalBody .j-pat").forEach(b => b.onclick = () => b.dataset.p && openPatient(b.dataset.p, "patients"));
}
function pushLine(x, auto) {
  if (!x.auto) return auto ? `<small class="pl manual">вносится вручную</small>` : "";
  const st = x.push_status, err = x.push_error ? esc(x.push_error) : "";
  const openBtn = x.kind === "visit" ? ` <button class="linkbtn" data-open-visit="${esc(x.id)}">открыть запись</button>` : "";
  if (st === "conflict") return `<small class="pl conflict">⚠ ${err}${openBtn} · <button class="linkbtn" data-force="${esc(x.id)}">отправить всё равно</button></small>`;
  const clash = x.conflict_text ? `<small class="pl conflict">⚠ Двойная запись: ${esc(x.conflict_text)}. ${auto ? "Не уйдёт в Dentist Plus, пока не решите." : "Перед переносом в Dentist Plus решите, кого перенести."}${openBtn}</small>` : "";
  if (clash && !st) return clash;
  if (st === "manual") return `<small class="pl manual">${err || "вносится вручную"}</small>`;
  if (st === "wait") return `<small class="pl wait">ждёт отправки${err ? ": " + err : ""}</small>`;
  if (st === "sent") return `<small class="pl ok">✓ отправлено автоматически${err ? " · " + err : ""}</small>`;
  if (st === "warn") return `<small class="pl warn">⚠ ${err}</small>`;
  if (st === "unknown") return `<small class="pl warn">⚠ ${err || "результат неизвестен"} — проверьте в Dentist Plus и отметьте галочкой, или <button class="linkbtn" data-retry="${esc(x.id)}" data-t="${esc(x.table)}">отправить ещё раз</button></small>`;
  if (st === "error") return `<small class="pl bad">✕ не отправлено: ${err} <button class="linkbtn" data-retry="${esc(x.id)}" data-t="${esc(x.table)}">повторить</button></small>`;
  return auto ? `<small class="pl wait">ждёт отправки при подключении</small>` : "";
}
$("#jDone").onchange = loadJournal;
$("#jPrint").onclick = () => {
  const items = (S.journal || []).filter(x => !x.transferred);
  $("#printArea").innerHTML = `<h2>Перенести в Dentist Plus</h2><p>Сформировано ${fmtDT(nowLocal())}. Всего: ${items.length}</p>
    <table><tr><th>✓</th><th>Пациент</th><th>Что</th><th>Подробности</th><th>Когда</th></tr>${
      items.map(x => `<tr><td>☐</td><td>${esc(x.patient_name || "")}</td><td>${esc(x.what)}</td><td>${esc(x.details)}</td><td>${fmtDT(x.at)}</td></tr>`).join("")}</table>`;
  window.print();
};
