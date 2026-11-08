"use strict";
/* Waiting list: patients who asked to be called if an earlier or a suitable time frees up. */

async function refreshWaitBadge() {
  const b = $("#waitBadge"); if (!b || !canAny("schedule_view", "schedule_edit")) return;
  try { const n = await api.waitlist_count(); b.hidden = !n; b.textContent = n || ""; } catch (e) { /* not critical */ }
}

/** After a visit is cancelled: tell the administrator if someone waits for that doctor on that day. */
async function waitlistHint(v) {
  try {
    const n = await api.waitlist_count(v.doctor_id || null, (v.start || "").slice(0, 10) || null);
    if (n) toast(`Освободилось время. В листе ожидания ${n} ${plural(n, "пациент", "пациента", "пациентов")} к этому врачу — кнопка «Ожидание» над расписанием.`);
  } catch (e) { /* not critical */ }
}

async function openWaitlist() {
  const R = await ref();
  const edit = can("schedule_edit");
  const box = modal(`
    <div class="m-h"><h3>Лист ожидания</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <p class="hint">Пациенты, которые хотят записаться раньше или на определённое время. Когда кто-то отменяет визит, программа напомнит, что есть кому позвонить.</p>
      <div class="seg" id="wlTabs"><button data-s="wait" class="on">Ждут</button><button data-s="booked">Записаны</button><button data-s="all">Все</button></div>
      <div id="wlList" class="wl-list"></div>
      ${edit ? `<details class="wl-add" id="wlAddBox"><summary>+ Добавить в лист ожидания</summary>
        <div class="pat-pick" id="wlPat"><input class="input" id="wlQ" placeholder="Пациент: ФИО или телефон" autocomplete="off"><div class="pp-list" id="wlRes"></div></div>
        <div class="grid3">
          <label class="fl">Врач<select class="input" id="wlDoc"><option value="">любой врач</option>${R.doctors.map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("")}</select></label>
          <label class="fl">Подходит с<input class="input" type="date" id="wlFrom"></label>
          <label class="fl">по<input class="input" type="date" id="wlTo"></label>
        </div>
        <label class="fl">Что нужно и когда удобно<input class="input" id="wlWish" placeholder="Например: чистка, только утром"></label>
        <label class="fl">Комментарий<input class="input" id="wlNote"></label>
        <div class="row"><button class="btn" id="wlSave">Добавить</button></div>
      </details>` : ""}
    </div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
  let status = "wait", pid = null;
  const draw = async () => {
    const rows = await api.waitlist(status);
    const period = w => w.date_from || w.date_to ? `${w.date_from ? "с " + fmtDate(w.date_from) : ""}${w.date_to ? " по " + fmtDate(w.date_to) : ""}`.trim() : "любые даты";
    $("#wlList", box).innerHTML = rows.length ? `<div class="tbl-scroll"><table class="tbl compact"><thead><tr><th>Пациент</th><th>Врач</th><th>Что и когда</th><th>Добавлен</th><th></th></tr></thead><tbody>
      ${rows.map((w, i) => `<tr><td><b>${esc(w.patient_name || "—")}</b><small class="muted" style="display:block">${esc(w.patient_phone || "")}</small></td>
        <td>${esc(w.doctor_name || "любой")}</td>
        <td>${esc(w.wish || "")}<small class="muted" style="display:block">${esc(period(w))}${w.note ? " · " + esc(w.note) : ""}</small></td>
        <td class="nowrap">${esc(fmtDT(w.created_at))}${w.status !== "wait" ? `<small class="muted" style="display:block">${esc(w.status_text)}</small>` : ""}</td>
        <td class="row-acts">${edit && w.status === "wait" ? `<button class="btn small" data-book="${i}">Записать</button><button class="btn ghost small" data-rm="${i}">Убрать</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`
      : `<div class="empty"><b>${status === "wait" ? "Никто не ждёт" : "Пусто"}</b><span>${status === "wait" ? "Добавьте пациента, который хочет записаться, если освободится время." : ""}</span></div>`;
    $$("[data-book]", box).forEach(b => b.onclick = () => {
      const w = rows[+b.dataset.book];
      closeModal();
      openBooking({patient_id: w.patient_id, patient_name: w.patient_name, doctor_id: w.doctor_id || "",
        start: `${w.date_from && w.date_from > S.day ? w.date_from : S.day} 10:00`,
        onSaved: async id => { await api.waitlist_done(w.id, id); refreshWaitBadge(); }});
    });
    $$("[data-rm]", box).forEach(b => b.onclick = async () => {
      const w = rows[+b.dataset.rm];
      if (!(await ask("Убрать из листа ожидания?", {ok: "Убрать", text: w.patient_name || ""}))) return;
      await api.waitlist_remove(w.id); toast("Убрано из листа ожидания"); draw(); refreshWaitBadge();
    });
  };
  $$("#wlTabs button", box).forEach(b => b.onclick = () => { status = b.dataset.s; $$("#wlTabs button", box).forEach(x => x.classList.toggle("on", x === b)); draw(); });
  if (edit) {
    let t;
    const q = $("#wlQ", box);
    q.oninput = () => { pid = null; clearTimeout(t); t = setTimeout(async () => {
      const rows = q.value.trim() ? await api.search(q.value) : [];
      $("#wlRes", box).innerHTML = rows.slice(0, 6).map(p => `<div class="pp-row" data-id="${esc(p.id)}" data-n="${esc(p.name)}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}</small></span></div>`).join("");
      $$("#wlRes .pp-row", box).forEach(r => r.onclick = () => { pid = r.dataset.id; q.value = r.dataset.n; $("#wlRes", box).innerHTML = ""; });
    }, 150); };
    $("#wlSave", box).onclick = async () => {
      if (!pid) return toast("Выберите пациента из списка", true);
      try {
        await api.waitlist_save({patient_id: pid, doctor_id: $("#wlDoc", box).value, date_from: $("#wlFrom", box).value, date_to: $("#wlTo", box).value,
          wish: $("#wlWish", box).value, note: $("#wlNote", box).value});
        toast("Добавлено в лист ожидания");
        pid = null; ["#wlQ", "#wlWish", "#wlNote", "#wlFrom", "#wlTo"].forEach(s => $(s, box).value = "");
        status = "wait"; $$("#wlTabs button", box).forEach(x => x.classList.toggle("on", x.dataset.s === "wait"));
        draw(); refreshWaitBadge();
      } catch (e) { toast(errText(e), true); }
    };
  }
  draw();
}

(() => { const b = $("#waitBtn"); if (b) b.onclick = openWaitlist; })();
