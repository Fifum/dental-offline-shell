"use strict";
/* Settings → «Резервные копии»: status, schedule, second folder, list of copies, restore. */
const BK_SIZE = n => n >= 1e6 ? (n / 1e6).toLocaleString("ru-RU", {maximumFractionDigits: 1}) + " МБ" : Math.max(1, Math.round(n / 1e3)) + " КБ";
const BK_AGO = h => h == null ? "" : h < 1 ? "меньше часа назад" : h < 24 ? `${Math.floor(h)} ч назад` : `${Math.floor(h / 24)} дн. назад`;

async function loadBackupSettings() {
  const box = $("#backupBody"); if (!box) return;
  let st;
  try { st = await api.backup_status(); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const s = st.settings, ex = st.extra;
  const pw = window.pywebview && window.pywebview.api;
  let local = !!(pw && pw.choose_folder);
  if (local && pw.is_client) { try { local = !(await pw.is_client()); } catch (e) { local = false; } }
  const last = st.last
    ? `Последняя копия: <b>${esc(fmtDT(st.last.created))}</b> (${esc(BK_AGO(st.age_hours))}, ${esc(st.last.reason_text)}) · всего ${st.count}, ${esc(BK_SIZE(st.total_bytes))}`
    : "Копий пока нет.";
  const exLine = !ex ? `<span class="muted">Вторая папка не выбрана — копии хранятся только на этом компьютере.</span>`
    : ex.error ? `<span class="bad-t">${esc(ex.error)}</span>`
    : ex.available ? `<span class="ok-t">Вторая папка: ${esc(ex.folder)} · копий: ${ex.count}${ex.last ? ", последняя " + esc(fmtDT(ex.last)) : ""}</span>`
    : `<span class="bad-t">Вторая папка сейчас недоступна (${esc(ex.dir)}). Вставьте флешку.</span>`;
  box.innerHTML = `
    ${st.warn ? `<div class="warn-line${st.error ? " bad" : ""}">${esc(st.warn)}</div>` : ""}
    <div class="bk-state">${last}<br>${exLine}</div>
    <label class="switch-row"><input type="checkbox" id="bkOn" ${s.enabled ? "checked" : ""}><span class="sw"></span>Делать копии автоматически</label>
    <div class="form">
      <label>Как часто, часов<input class="input" id="bkInt" type="number" min="1" max="24" value="${esc(s.interval_h)}"></label>
      <label>Хранить все копии, дней<input class="input" id="bkAll" type="number" min="1" max="14" value="${esc(s.keep_all_days)}"></label>
      <label>Хранить по одной в день, дней<input class="input" id="bkDays" type="number" min="3" max="365" value="${esc(s.keep_days)}"></label>
      <label class="wide">Вторая папка (флешка или другой диск)<span class="bk-dir"><input class="input" id="bkDir" value="${esc(s.extra_dir)}" placeholder="Например E:\\">${local ? `<button class="btn ghost small" id="bkPick" type="button">Выбрать…</button>` : ""}</span></label>
    </div>
    <div class="row">
      <button class="btn" id="bkSave">Сохранить</button>
      <button class="btn ghost" id="bkNow">Сделать копию сейчас</button>
      <button class="btn ghost" id="bkList">Восстановить из копии…</button>
      <span class="msg" id="bkMsg"></span>
    </div>
    <p class="hint">Папка с копиями: <code>${esc(st.folder)}</code></p>`;
  const msgB = (t, ok) => { const m = $("#bkMsg"); m.textContent = t; m.className = "msg " + (ok ? "ok" : "bad"); };
  const pick = $("#bkPick");
  if (pick) pick.onclick = async () => { const d = await pw.choose_folder(); if (d) $("#bkDir").value = d; };
  $("#bkSave").onclick = async () => {
    try {
      await api.backup_settings_save({enabled: $("#bkOn").checked, interval_h: $("#bkInt").value, keep_all_days: $("#bkAll").value,
        keep_days: $("#bkDays").value, extra_dir: $("#bkDir").value.trim()});
      toast("Настройки копий сохранены"); S.backupWarned = null; loadBackupSettings();
    } catch (e) { msgB(errText(e), false); }
  };
  $("#bkNow").onclick = async () => {
    const b = $("#bkNow"); b.disabled = true; msgB("Сохраняем копию…", true);
    try {
      const r = await api.backup_now();
      toast(`Копия сохранена: ${BK_SIZE(r.size)}`); S.backupWarned = null; loadBackupSettings();
    } catch (e) { msgB(errText(e), false); b.disabled = false; }
  };
  $("#bkList").onclick = openBackupList;
}

async function openBackupList() {
  let rows;
  try { rows = await api.backup_list(); } catch (e) { return toast(errText(e), true); }
  const director = !!(ME && ME.role === "director");
  const cnt = c => c && c.patients != null ? `${c.patients} пац., ${c.visits ?? 0} зап.` : "";
  const box = modal(`
    <div class="m-h"><h3>Восстановить базу из копии</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <p class="hint">Перед восстановлением программа сохранит текущую базу отдельной копией «перед восстановлением» — её можно вернуть так же. После восстановления программа перезапустится.${director ? "" : " <b>Восстанавливать может только директор.</b>"}</p>
      ${rows.length ? `<div class="tbl-scroll"><table class="tbl compact"><thead><tr><th>Когда</th><th>Как</th><th>Где</th><th>Данные</th><th class="num">Размер</th><th></th></tr></thead><tbody>
        ${rows.map((r, i) => `<tr><td class="nowrap">${esc(fmtDT(r.created))}</td><td>${esc(r.reason_text)}</td><td>${r.where === "extra" ? "вторая папка" : "этот компьютер"}</td>
          <td class="muted">${esc(cnt(r.counts))}</td><td class="num">${esc(BK_SIZE(r.size))}</td>
          <td class="row-acts">${director ? `<button class="btn ghost small" data-i="${i}">Восстановить</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><b>Копий пока нет</b><span>Нажмите «Сделать копию сейчас».</span></div>`}
    </div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  $$("[data-i]", box).forEach(b => b.onclick = async () => {
    const r = rows[+b.dataset.i];
    const ok = await ask("Восстановить базу из копии?", {danger: true, ok: "Восстановить",
      text: `Данные программы станут такими, какими были ${fmtDT(r.created)}. Всё, что внесено позже, пропадёт из базы, но останется в копии «перед восстановлением».\n\nКомпьютер в сети клиники или с облаком: после перезапуска программы восстановленные записи заменят их версии и на других компьютерах клиники. Записи, созданные позже копии на других компьютерах, сохранятся. До перезапуска обмен с другими компьютерами и облаком остановлен.`});
    if (!ok) return;
    b.disabled = true;
    try {
      await api.backup_restore(r.where, r.name);
      closeModal();
      const pw = window.pywebview && window.pywebview.api;
      let client = false;
      if (pw && pw.is_client) { try { client = await pw.is_client(); } catch (e) { client = false; } }
      if (pw && pw.restart_app && !client) { toast("База восстановлена. Программа перезапускается…"); setTimeout(() => pw.restart_app(), 900); }
      else { toast("База восстановлена. Перезапустите программу на компьютере, где хранится база, чтобы всё обновилось."); afterChange(); loadBackupSettings(); }
    } catch (e) { b.disabled = false; toast(errText(e), true); }
  });
}

async function loadSecuritySettings(force) {
  const box = $("#securityBody"); if (!box) return;
  let st;
  try { st = await api.security_status(!!force); } catch (e) { box.innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const cls = st.ok ? "ok-t" : st.state === "unknown" ? "muted" : "bad-t";
  box.innerHTML = `
    <div class="bk-state"><b class="${cls}">${esc(st.text)}</b> <span class="muted">(диск ${esc(st.drive)})</span></div>
    ${st.ok ? "" : `<div class="sec-how"><b>Как включить шифрование</b><ol>${st.how.map(x => `<li>${esc(x)}</li>`).join("")}</ol>
      <p class="hint">Включать нужно на каждом ноутбуке клиники. Шифрование идёт в фоне, работать можно сразу.</p></div>`}
    <div class="row"><button class="btn ghost small" id="secCheck">Проверить ещё раз</button></div>`;
  $("#secCheck").onclick = () => loadSecuritySettings(true);
}