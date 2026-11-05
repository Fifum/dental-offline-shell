"use strict";
/* Everything done in this app, to re-enter into Dentist Plus. */
const J_ICON = {patient: "Пациент", visit: "Запись", record: "Медкарта", document: "Документ", invoice: "Счёт", payment: "Оплата"};

async function loadJournal() {
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
      ? `<b>Автоматическая отправка включена.</b> Пациенты и записи уходят в Dentist Plus сами при подключении к интернету. Медкарты, документы, счета и оплаты — вручную.`
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
  const jm = $("#jMode"); if (jm) jm.onclick = e => { e.preventDefault(); show("settings"); };
  $$("#journalBody [data-retry]").forEach(b => b.onclick = async e => { e.preventDefault(); await api.retry_push(b.dataset.t, b.dataset.retry); toast("Отправим ещё раз при следующей синхронизации"); loadJournal(); });
  $$("#journalBody [data-open-doc]").forEach(b => b.onclick = e => { e.preventDefault(); openDocument(b.dataset.openDoc); });
  $$("#journalBody [data-open-rec]").forEach(b => b.onclick = e => { e.preventDefault(); openRecord({patient_id: b.dataset.p, id: b.dataset.openRec}); });
  $$("#journalBody .j-pat").forEach(b => b.onclick = () => b.dataset.p && openPatient(b.dataset.p, "patients"));
}
function pushLine(x, auto) {
  if (!x.auto) return auto ? `<small class="pl manual">вносится вручную</small>` : "";
  const st = x.push_status, err = x.push_error ? esc(x.push_error) : "";
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
