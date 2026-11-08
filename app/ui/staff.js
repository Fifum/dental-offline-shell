"use strict";
/* Staff: registration requests, roles and permissions, action journal (director only). */
S.staffTab = "people";
$$("#staffTabs button").forEach(b => b.onclick = () => {
  S.staffTab = b.dataset.s;
  $$("#staffTabs button").forEach(x => x.classList.toggle("on", x === b));
  loadStaff();
});

async function refreshStaffBadge() {
  try {
    const r = await authApi.staff_list();
    const n = r.staff.filter(u => u.status === "pending").length;
    const b = $("#staffBadge"); b.hidden = !n; b.textContent = n || "";
  } catch (e) {}
}

const roleSelect = (id, val, withEmpty) => `<select class="input" id="${id}">${withEmpty ? `<option value="">— выберите —</option>` : ""}${
  AUTH_STATE.roles.map(r => `<option value="${r.key}" ${r.key === val ? "selected" : ""}>${esc(r.title)}</option>`).join("")}</select>`;
const statusLbl = {active: "Работает", blocked: "Заблокирован", pending: "Ждёт одобрения"};

async function loadStaff() {
  const body = $("#staffBody");
  if (S.staffTab === "audit") return loadAudit();
  const {staff, doctors} = await authApi.staff_list();
  S.staffDoctors = doctors;
  const pending = staff.filter(u => u.status === "pending");
  const rest = staff.filter(u => u.status !== "pending");
  body.innerHTML = (pending.length ? `<div class="staff-req"><h4>Заявки на доступ: ${pending.length}</h4>${pending.map(u => `
      <div class="req-row" data-u="${u.id}"><div class="grow"><b>${esc(u.name)}</b> <span class="muted">· ${esc(u.login)} · ${esc(u.position || "должность не указана")} · ${fmtDT(u.created_at)}</span></div>
        ${roleSelect("rr" + u.id, u.role, true)}
        <button class="btn small" data-approve="${u.id}">Одобрить</button><button class="btn ghost small" data-reject="${u.id}">Отклонить</button></div>`).join("")}</div>` : "") +
    `<table class="tbl"><thead><tr><th>Сотрудник</th><th>Логин</th><th>Роль</th><th>Права</th><th>Статус</th><th>Последний вход</th></tr></thead><tbody>${
      rest.map(u => `<tr data-edit="${u.id}"><td class="lnk"><b>${esc(u.name)}</b><small class="muted" style="display:block">${esc(u.position || "")}</small></td>
        <td>${esc(u.login)}</td><td><span class="role-pill ${u.role}">${esc(u.role_title || "—")}</span></td>
        <td class="muted">${u.role === "director" ? "все" : u.custom_perms ? `своя настройка (${u.perms.length})` : "по роли"}</td>
        <td class="st-${u.status}">${statusLbl[u.status] || u.status}</td><td>${u.last_login ? fmtDT(u.last_login) : "—"}</td></tr>`).join("")}</tbody></table>
    <p class="muted" style="padding:10px 4px;font-size:12.5px">Новый сотрудник открывает программу на своём компьютере и нажимает «Подать заявку». Заявка появится здесь.</p>`;
  $$("[data-approve]", body).forEach(b => b.onclick = async () => {
    const id = +b.dataset.approve, role = $("#rr" + id).value;
    if (!role) return toast("Выберите роль сотрудника", true);
    const u = staff.find(x => x.id === id);
    await authApi.staff_save({id, role, status: "active", position: u.position});
    toast(`${u.name}: доступ открыт`); loadStaff(); refreshStaffBadge();
  });
  $$("[data-reject]", body).forEach(b => b.onclick = async () => {
    const u = staff.find(x => x.id === +b.dataset.reject);
    if (!(await ask(`Отклонить заявку: ${u.name}?`, {danger: true, ok: "Отклонить", text: "Сотрудник сможет подать заявку заново."}))) return;
    await authApi.staff_reject(u.id); loadStaff(); refreshStaffBadge();
  });
  $$("tr[data-edit]", body).forEach(tr => tr.onclick = () => editStaff(staff.find(x => x.id === +tr.dataset.edit)));
}

function editStaff(u) {
  const rolePerms = role => (AUTH_STATE.roles.find(r => r.key === role) || {}).perms || [];
  const box = modal(`<div class="m-h"><h3>${esc(u.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b auth-form">
      <div class="auth-row"><label>ФИО<input class="input" id="seName" value="${esc(u.name)}"></label><label>Должность<input class="input" id="sePos" value="${esc(u.position || "")}"></label></div>
      <div class="auth-row"><label>Роль${roleSelect("seRole", u.role)}</label>
        <label>Это врач в расписании<select class="input" id="seDoc"><option value="">— нет —</option>${(S.staffDoctors || []).map(d => `<option value="${esc(d.id)}" ${d.id === u.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label></div>
      <label class="switch-row" style="font-weight:400"><input type="checkbox" id="seCustom" ${u.custom_perms ? "checked" : ""}><span class="sw"></span>Настроить права вручную</label>
      <div class="perm-grid" id="sePerms">${AUTH_STATE.perm_list.map(p => `<label><input type="checkbox" value="${p.key}" ${u.perms.includes(p.key) ? "checked" : ""}>${esc(p.title)}</label>`).join("")}</div>
      <div class="auth-row"><label>Статус<select class="input" id="seStatus"><option value="active" ${u.status === "active" ? "selected" : ""}>Работает</option><option value="blocked" ${u.status === "blocked" ? "selected" : ""}>Заблокирован (не может войти)</option></select></label>
        <label>Новый пароль<input class="input" type="password" id="sePass" placeholder="оставьте пустым" autocomplete="new-password"></label></div>
      <div class="auth-err" id="seErr"></div>
    </div>
    <div class="m-f"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="seOk">Сохранить</button></div>`, {wide: true});
  const sync = () => {
    const custom = $("#seCustom").checked, director = $("#seRole").value === "director";
    $$("#sePerms input").forEach(i => { i.disabled = !custom || director; });
    if (!custom || director) {
      const keys = rolePerms($("#seRole").value);
      $$("#sePerms input").forEach(i => i.checked = keys.includes(i.value));
    }
  };
  $("#seRole", box).onchange = sync; $("#seCustom", box).onchange = sync; sync();
  $("#seOk", box).onclick = async () => {
    const custom = $("#seCustom").checked && $("#seRole").value !== "director";
    try {
      await authApi.staff_save({id: u.id, name: $("#seName").value, position: $("#sePos").value, role: $("#seRole").value,
        status: $("#seStatus").value, doctor_id: $("#seDoc").value, perms: custom ? $$("#sePerms input:checked").map(i => i.value) : null});
      if ($("#sePass").value) await authApi.staff_reset_password(u.id, $("#sePass").value);
      closeModal(); toast("Сохранено"); loadStaff();
      if (u.id === ME.id) { const st = await authApi.state(); if (st.user) startApp(st.user); }
    } catch (e) { $("#seErr").textContent = errText(e); }
  };
}

async function loadAudit() {
  const body = $("#staffBody");
  const day = S.auditDay || iso(new Date());
  const rows = await authApi.audit_list(day);
  body.innerHTML = `<div class="tab-tools"><input type="date" class="input" id="auDay" value="${day}"><span class="muted">Кто что делал в программе: входы, записи, оплаты, лечения, документы, изменения прав.</span></div>
    <table class="tbl compact"><thead><tr><th>Время</th><th>Сотрудник</th><th>Действие</th><th>Подробности</th><th>Компьютер</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${esc(r.at.slice(11, 19))}</td><td>${esc(r.user_name || "—")}</td><td><b>${esc(r.action)}</b></td><td class="muted">${esc(r.detail || "")}</td><td class="muted">${esc(r.ip || "")}</td></tr>`).join("")
      || `<tr><td colspan="5" class="muted">За этот день действий нет</td></tr>`}</tbody></table>`;
  $("#auDay").onchange = e => { S.auditDay = e.target.value; loadAudit(); };
}
