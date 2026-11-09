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
  if (S.staffTab === "roles") return loadRoles();
  const {staff, doctors} = await authApi.staff_list();
  S.staffDoctors = doctors;
  const pending = staff.filter(u => u.status === "pending");
  const rest = staff.filter(u => u.status !== "pending");
  body.innerHTML = (pending.length ? `<div class="staff-req"><h4>Заявки на доступ: ${pending.length}</h4>${pending.map(u => `
      <div class="req-row" data-u="${u.id}"><div class="grow"><b>${esc(u.name)}</b> <span class="muted">· ${esc(u.login)} · ${esc(u.position || "должность не указана")} · ${fmtDT(u.created_at)}</span></div>
        ${roleSelect("rr" + u.id, u.role, true)}
        <button class="btn small" data-approve="${u.id}">Одобрить</button><button class="btn ghost small" data-reject="${u.id}">Отклонить</button></div>`).join("")}</div>` : "") +
    `<table class="tbl"><thead><tr><th>Сотрудник</th><th>Логин</th><th>Должность</th><th>Права</th><th>Статус</th><th>Последний вход</th></tr></thead><tbody>${
      rest.map(u => `<tr data-edit="${u.id}"><td class="lnk"><b>${esc(u.name)}</b><small class="muted" style="display:block">${esc(u.position || "")}</small></td>
        <td>${esc(u.login)}</td><td><span class="role-pill ${u.role}">${esc(u.role_title || "—")}</span></td>
        <td class="muted">${u.role === "director" ? "все" : u.custom_perms ? `своя настройка (${u.perms.length})` : "по должности"}</td>
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
      <div class="auth-row"><label>ФИО<input class="input" id="seName" value="${esc(u.name)}"></label><label>Должность в документах<input class="input" id="sePos" value="${esc(u.position || "")}" placeholder="например: врач-стоматолог-терапевт"></label></div>
      <div class="auth-row"><label>Должность и права${roleSelect("seRole", u.role)}</label>
        <label>Это врач в расписании<select class="input" id="seDoc"><option value="">— нет —</option>${(S.staffDoctors || []).map(d => `<option value="${esc(d.id)}" ${d.id === u.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label></div>
      <label class="switch-row" style="font-weight:400"><input type="checkbox" id="seCustom" ${u.custom_perms ? "checked" : ""}><span class="sw"></span>Права только этому сотруднику (не как у должности)</label>
      <div id="sePerms">${permGroupsHtml(u.perms)}</div>
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

/* -------------------------------------------- 2.14: positions and what each may see and do */
const permTitle = k => ((AUTH_STATE.perm_list || []).find(p => p.key === k) || {}).title || k;
function permGroupsHtml(have, opts = {}) {
  const groups = AUTH_STATE.perm_groups || [{title: "Права", keys: AUTH_STATE.perm_list.map(p => p.key)}];
  return `<div class="pg-wrap">${groups.map((g, gi) => `<fieldset class="pg"><legend>${esc(g.title)}${opts.groupBtns ? ` <button type="button" class="linkbtn" data-gall="${gi}">все</button> <button type="button" class="linkbtn" data-gnone="${gi}">ничего</button>` : ""}</legend>
    ${g.keys.map(k => `<label class="${opts.def && opts.def.includes(k) !== have.includes(k) ? "pg-ch" : ""}"><input type="checkbox" value="${k}" ${have.includes(k) ? "checked" : ""}>${esc(permTitle(k))}</label>`).join("")}</fieldset>`).join("")}</div>`;
}

async function loadRoles() {
  const body = $("#staffBody");
  let r;
  try { r = await authApi.roles_list(); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  AUTH_STATE.perm_groups = r.perm_groups; AUTH_STATE.perm_list = r.perm_list;
  const base = k => (r.roles.find(x => x.key === k) || {}).title || k;
  body.innerHTML = `<div class="tab-tools"><button class="btn" id="rlNew">+ Новая должность</button>
      <span class="muted">Щёлкните по должности, чтобы изменить, что она видит и делает. Изменения сразу действуют у всех сотрудников этой должности, на всех компьютерах клиники.</span></div>
    <table class="tbl roles-t"><thead><tr><th>Должность</th><th>Как встроенная</th><th class="num">Сотрудников</th><th class="num">Прав</th><th></th></tr></thead><tbody>${
      r.roles.map(x => `<tr data-role="${esc(x.key)}" class="${x.locked ? "" : "lnk-row"}"><td><b>${esc(x.title)}</b>${x.builtin ? "" : ' <span class="pill">своя</span>'}</td>
        <td class="muted">${x.builtin ? "встроенная" : esc(base(x.base))}</td><td class="num">${x.people}</td>
        <td class="num">${x.locked ? "все" : `${x.perms.length} из ${r.perm_list.length}`}</td>
        <td class="muted">${x.locked ? "у директора все права" : x.builtin && x.edited ? "изменена директором" : ""}</td></tr>`).join("")}</tbody></table>`;
  $("#rlNew", body).onclick = () => editRole(null, r);
  $$("tr[data-role]", body).forEach(tr => tr.onclick = () => { const x = r.roles.find(y => y.key === tr.dataset.role); if (!x.locked) editRole(x, r); });
}

function editRole(x, r) {
  const fresh = !x;
  const bases = r.roles.filter(y => r.bases.includes(y.key));
  x = x || {key: "", title: "", base: "admin", perms: [...(bases.find(y => y.key === "admin") || {perms: []}).perms], builtin: false, default: []};
  const box = modal(`<div class="m-h"><h3>${fresh ? "Новая должность" : esc(x.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b auth-form">
      <div class="auth-row"><label>Название<input class="input" id="rlTitle" value="${esc(x.title)}" placeholder="например: Старший администратор" maxlength="60" ${x.builtin ? "" : "autofocus"}></label>
        ${x.builtin ? `<label>Встроенная должность<input class="input" value="${esc(x.title)}" disabled></label>`
          : `<label>Похожа на (для голоса на записи приёма и связи с врачом)<select class="input" id="rlBase">${bases.map(b => `<option value="${b.key}" ${b.key === x.base ? "selected" : ""}>${esc(b.title)}</option>`).join("")}</select></label>`}</div>
      ${fresh ? `<label>Начать с прав должности<select class="input" id="rlFrom"><option value="">— отметить вручную —</option>${r.roles.filter(y => !y.locked).map(y => `<option value="${esc(y.key)}" ${y.key === "admin" ? "selected" : ""}>${esc(y.title)}</option>`).join("")}</select></label>` : ""}
      <div id="rlPerms">${permGroupsHtml(x.perms, {groupBtns: true, def: x.builtin ? x.default : null})}</div>
      ${x.builtin ? `<p class="muted" style="font-size:12px">Жёлтым отмечено то, что отличается от настройки программы.</p>` : ""}
      <div class="auth-err" id="rlErr"></div></div>
    <div class="m-f">${x.builtin && x.edited ? `<button class="btn ghost small" id="rlReset">Как в программе</button>` : ""}${!fresh && !x.builtin ? `<button class="btn ghost small danger" id="rlDel">Удалить</button>` : ""}
      <span class="muted">${x.people ? `Сотрудников на должности: ${x.people}` : ""}</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rlOk">Сохранить</button></div>`, {wide: true});
  const bind = () => {
    $$("[data-gall]", box).forEach(b => b.onclick = () => $$(`.pg:nth-of-type(${+b.dataset.gall + 1}) input`, box).forEach(i => i.checked = true));
    $$("[data-gnone]", box).forEach(b => b.onclick = () => $$(`.pg:nth-of-type(${+b.dataset.gnone + 1}) input`, box).forEach(i => i.checked = false));
  };
  bind();
  const from = $("#rlFrom", box);
  if (from) from.onchange = () => { const y = r.roles.find(z => z.key === from.value); $("#rlPerms", box).innerHTML = permGroupsHtml(y ? y.perms : [], {groupBtns: true}); if (y && $("#rlBase", box)) $("#rlBase", box).value = y.base; bind(); };
  $("#rlOk", box).onclick = async () => {
    const perms = $$("#rlPerms input:checked", box).map(i => i.value);
    try {
      await authApi.role_save({key: x.key, title: $("#rlTitle", box).value, base: $("#rlBase", box) ? $("#rlBase", box).value : x.base, perms});
      closeModal(); toast("Права должности сохранены"); await rolesChanged();
    } catch (e) { $("#rlErr", box).textContent = errText(e); }
  };
  const rs = $("#rlReset", box); if (rs) rs.onclick = async () => {
    if (!(await ask(`Вернуть права «${x.title}» как в программе?`, {ok: "Вернуть", text: "Отметки директора для этой должности пропадут."}))) return;
    await authApi.role_reset(x.key); closeModal(); toast("Права как в программе"); await rolesChanged();
  };
  const dl = $("#rlDel", box); if (dl) dl.onclick = async () => {
    if (!(await ask(`Удалить должность «${x.title}»?`, {danger: true, ok: "Удалить"}))) return;
    try { await authApi.role_delete(x.key); closeModal(); toast("Должность удалена"); await rolesChanged(); } catch (e) { $("#rlErr", box).textContent = errText(e); }
  };
}
async function rolesChanged() {
  try { const st = await authApi.state(); AUTH_STATE = st; if (st.user) { ME.perms = st.user.perms; applyPerms(); } } catch (e) { /* the list still reloads */ }
  loadStaff();
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
