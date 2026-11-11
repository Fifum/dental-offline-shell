"use strict";
/* 3.5: «Склад» → «По приёмам» (materials of finished Dentist Plus visits by the norms: drafts to confirm or automatic),
   «Места хранения» (cabinets, branches, transfers); «Бухгалтерия» → «Себестоимость» (materials + lab + doctor's percent). */
S.svState = "draft";
S.svF = null;
S.costMonth = iso(new Date()).slice(0, 7);
const SV_SRC = {dp: "из Dentist Plus", title: "по названию записи", manual: "вручную", none: ""};
const SV_PILL = {draft: "st-come", done: "st-ok", invoice: "st-ok", no_services: "st-cancel", no_norms: "", skipped: "", reverted: ""};
const NO_DP_TEXT = "нет данных из Dentist Plus";

function stockAutoStatus(st) {
  const el = $("#stVisitsCnt");
  if (!el) return;
  const n = st.stock_visits || 0;
  el.hidden = !n; el.textContent = n || "";
  el.title = n ? `Приёмов ждут списания материалов: ${n}` : "";
}

/* ------------------------------------------------------------ «По приёмам» */
async function stockVisits() {
  const body = $("#stockBody");
  const f = S.svF || {from: "", to: ""};
  let r;
  try { r = await api.stock_visits({from: f.from || null, to: f.to || null, status: S.svState === "all" ? null : S.svState}); }
  catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  S.svF = {from: r.from, to: r.to};
  const edit = can("stock_edit"), c = r.counts, s = r.settings;
  const states = [["draft", "К списанию", c.draft], ["no_services", "Нет услуг", c.no_services], ["done", "Списано", c.done],
    ["invoice", "По счёту", c.invoice], ["no_norms,skipped,reverted", "Прочие", c.no_norms + c.skipped + c.reverted], ["all", "Все", null]];
  const modeLine = s.mode === "auto"
    ? `<b>Сразу:</b> завершённые приёмы с ${fmtDate(s.auto_since)} списываются сами (раз в 5 минут). Отменить списание можно в любой момент.`
    : `<b>Черновик:</b> материалы списываются, когда вы подтвердите приём. Ничего не уходит со склада само.`;
  body.innerHTML = `<div class="tab-tools"><input type="date" class="input" id="svFrom" value="${r.from}"> — <input type="date" class="input" id="svTo" value="${r.to}">
      <div class="seg sm" id="svState">${states.map(([k, t, n]) => `<button data-k="${k}" class="${S.svState === k ? "on" : ""}">${t}${n ? ` <i class="cnt ${k === "draft" ? "bad" : ""}">${n}</i>` : ""}</button>`).join("")}</div>
      <span class="grow"></span>
      ${edit ? `<button class="btn ghost" id="svSet">Настройки</button>${r.rows.some(x => x.status === "draft") ? `<button class="btn" id="svAll">Списать отмеченные</button>` : ""}` : ""}</div>
    <div class="note-box sv-mode">${modeLine} Материалы берутся из норм списания услуг (вкладка «Нормы списания»); приём, на который выставлен счёт в программе, уже списан по счёту и не списывается второй раз.</div>
    ${r.has_dp ? "" : `<div class="warn-line">Приёмы из Dentist Plus ещё не загружены — ${NO_DP_TEXT}. Списать материалы по счёту можно, как и раньше.</div>`}
    <div class="pbody" style="margin-top:8px">${r.rows.length ? `<table class="tbl sv-tbl"><thead><tr>${edit ? `<th style="width:28px"><input type="checkbox" id="svChkAll" title="Отметить все к списанию"></th>` : ""}<th>Приём</th><th>Пациент · врач</th><th>Услуги</th><th>Материалы</th><th>Место</th><th class="num">Сумма</th><th>Состояние</th><th></th></tr></thead><tbody>${
      r.rows.map(x => svRow(x, edit)).join("")}</tbody></table>`
      : `<div class="empty"><b>${S.svState === "draft" ? "Нет приёмов, ждущих списания" : "Приёмов нет"}</b><span>Показаны завершённые приёмы Dentist Plus за ${fmtShort(r.from)} — ${fmtShort(r.to)}</span></div>`}</div>
    ${r.total_draft ? `<div class="muted note-line">К списанию материалов на ${money(r.total_draft)}.</div>` : ""}`;
  const upd = () => { S.svF = {from: $("#svFrom").value, to: $("#svTo").value}; stockVisits(); };
  $("#svFrom").onchange = upd; $("#svTo").onchange = upd;
  $$("#svState button").forEach(b => b.onclick = () => { S.svState = b.dataset.k; stockVisits(); });
  const on = (s2, fn) => { const el = $(s2); if (el) el.onclick = fn; };
  on("#svSet", visitSettings);
  on("#svAll", async () => {
    const ids = $$("[data-sv-chk]:checked").map(i => i.dataset.svChk);
    if (!ids.length) return toast("Отметьте приёмы для списания", true);
    await svConfirm(ids);
  });
  const all = $("#svChkAll"); if (all) all.onchange = () => $$("[data-sv-chk]").forEach(i => { i.checked = all.checked; });
  $$("#stockBody [data-sv-open]").forEach(el => el.onclick = () => openVisitUse(r.rows.find(x => x.id === el.dataset.svOpen), r));
  $$("#stockBody [data-sv-act]").forEach(b => b.onclick = async e => {
    e.stopPropagation();
    const row = r.rows.find(x => x.id === b.dataset.id);
    await svAction(b.dataset.svAct, row, r);
  });
}

function svServices(x) {
  if (!x.services.length) return `<span class="muted">${x.source === "none" ? NO_DP_TEXT : "—"}</span>`;
  return x.services.map(s => `<span class="chip ${s.service_id ? "" : "chip-warn"}" title="${esc(s.service_id ? (s.dp_title && s.dp_title !== s.title ? "В Dentist Plus: " + s.dp_title : "") : "Нет в прайсе программы")}">${esc(s.title)}${s.qty !== 1 ? ` × ${qtyFmt(s.qty)}` : ""}</span>`).join(" ")
    + (SV_SRC[x.source] ? ` <small class="muted">${SV_SRC[x.source]}</small>` : "");
}

function svRow(x, edit) {
  const canDo = edit && (x.status === "draft" || ((x.status === "skipped" || x.status === "reverted") && x.base_status === "draft"));
  const acts = !edit ? "" : x.status === "done" ? `<button class="linkbtn" data-sv-act="revert" data-id="${esc(x.id)}">отменить</button>`
    : x.status === "invoice" ? ""
    : `${canDo ? `<button class="btn small" data-sv-act="confirm" data-id="${esc(x.id)}">Списать</button>` : ""}
       <button class="linkbtn" data-sv-act="edit" data-id="${esc(x.id)}">${x.services.length ? "услуги" : "указать услуги"}</button>
       ${x.status === "skipped" || x.status === "reverted" ? `<button class="linkbtn" data-sv-act="restore" data-id="${esc(x.id)}">в черновики</button>`
         : `<button class="linkbtn" data-sv-act="skip" data-id="${esc(x.id)}">не списывать</button>`}`;
  return `<tr data-sv-open="${esc(x.id)}" class="lnk-row ${x.status === "done" ? "" : x.status === "draft" ? "" : "muted-row"}">
    ${edit ? `<td>${x.status === "draft" ? `<input type="checkbox" data-sv-chk="${esc(x.id)}" onclick="event.stopPropagation()">` : ""}</td>` : ""}
    <td><b>${fmtDT(x.start)}</b>${x.chair ? `<small class="muted" style="display:block">${esc(x.chair)}</small>` : ""}</td>
    <td>${esc(x.patient_name || "—")}<small class="muted" style="display:block">${esc(x.doctor_name || "")}</small></td>
    <td class="sv-svc">${svServices(x)}</td>
    <td>${x.lines.length ? `<span class="muted">${x.lines.length} поз.</span>` : `<span class="muted">${x.status === "no_norms" ? "нормы не заданы" : "—"}</span>`}</td>
    <td>${esc(x.location_name || "")}</td>
    <td class="num">${x.total ? money(x.total) : "—"}</td>
    <td><span class="pill ${SV_PILL[x.status] || ""}">${esc(x.status_title)}</span>${x.auto ? ` <small class="muted">авто</small>` : ""}${x.gone ? ` <small class="muted" title="Приёма уже нет в загруженных данных Dentist Plus">нет в DP</small>` : ""}</td>
    <td class="sv-acts">${acts}</td></tr>`;
}

async function svConfirm(ids) {
  try {
    const res = await api.stock_visit_confirm(ids);
    toast(res.count ? `Списано по приёмам: ${res.count}` + (res.left.length ? `. Не списано: ${res.left.length} (${[...new Set(res.left.map(l => l.why))].join(", ")})` : "")
      : `Не списано: ${[...new Set(res.left.map(l => l.why))].join(", ")}`, !res.count);
  } catch (e) { toast(errText(e), true); }
  if (S.stockTab === "visits") stockVisits();
}

async function svAction(act, row, r) {
  try {
    if (act === "confirm") return svConfirm([row.id]);
    if (act === "edit") return editVisitServices(row, r);
    if (act === "revert") {
      if (!await ask("Отменить списание по этому приёму?", {danger: true, ok: "Отменить списание", text: "Материалы вернутся на склад. Автоматически этот приём больше не спишется — списать его снова можно вручную."})) return;
      await api.stock_visit_revert(row.id); toast("Списание отменено, материалы возвращены");
    }
    if (act === "skip") {
      const v = await askInput("Не списывать материалы по приёму?", [{label: "Причина (необязательно)", value: "", required: false}], {ok: "Не списывать"});
      if (!v) return;
      await api.stock_visit_skip(row.id, v[0]); toast("Приём не будет списываться");
    }
    if (act === "restore") { await api.stock_visit_restore(row.id); toast("Приём снова в черновиках"); }
  } catch (e) { toast(errText(e), true); }
  closeModal();
  stockVisits();
}

function openVisitUse(x, r) {
  if (!x) return;
  const edit = can("stock_edit");
  const box = modal(`<div class="m-h"><h3>Приём ${fmtDT(x.start)} · ${esc(x.patient_name || "")}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <dl class="kv eq-kv"><dt>Врач</dt><dd>${esc(x.doctor_name || "—")}</dd><dt>Кресло</dt><dd>${esc(x.chair || "—")}</dd><dt>Статус в Dentist Plus</dt><dd>${esc(x.visit_status || "—")}</dd>
        <dt>Место списания</dt><dd>${esc(x.location_name)}</dd><dt>Состояние</dt><dd>${esc(x.status_title)}${x.done_name ? ` · ${esc(x.done_name)}` : ""}${x.at ? `, ${fmtDT(x.at)}` : ""}</dd></dl>
      ${x.title ? `<div class="muted">В записи: ${esc(x.title)}</div>` : ""}
      ${x.note ? `<div class="note-box">${esc(x.note)}</div>` : ""}
      <h4 class="sub-h">Услуги ${SV_SRC[x.source] ? `<small class="muted">${SV_SRC[x.source]}</small>` : ""}</h4>
      ${x.services.length ? svServices(x) : `<div class="muted">Услуги приёма Dentist Plus не передал — ${NO_DP_TEXT}. Укажите их, чтобы списать материалы.</div>`}
      ${x.unknown.length ? `<div class="warn-line">Нет в прайсе программы: ${esc(x.unknown.join(", "))}. Их материалы не спишутся — выберите услугу из прайса вручную.</div>` : ""}
      <h4 class="sub-h">Материалы по нормам</h4>
      ${x.lines.length ? `<table class="tbl compact"><thead><tr><th>Материал</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th><th>По услугам</th></tr></thead><tbody>${
        x.lines.map(l => `<tr><td>${esc(l.name)}</td><td class="num">${qtyFmt(l.qty, l.unit)}</td><td class="num">${money(l.price)}</td><td class="num">${money(l.sum)}</td><td class="muted">${esc((l.services || []).join("; "))}</td></tr>`).join("")}</tbody>
        <tfoot><tr><td colspan="3">Итого</td><td class="num">${money(x.total)}</td><td></td></tr></tfoot></table>`
      : `<div class="muted">${x.status === "no_norms" ? "У услуг нет норм списания — задайте их во вкладке «Нормы списания»." : "Списывать нечего."}</div>`}
    </div>
    <div class="m-f"><span class="muted">${x.status === "invoice" ? "На этот приём выставлен счёт в программе: материалы списаны по счёту." : ""}</span><button class="btn ghost" data-close>Закрыть</button>
      ${edit && x.status === "done" ? `<button class="btn ghost danger-t" data-sv-act="revert">Отменить списание</button>` : ""}
      ${edit && x.status !== "done" && x.status !== "invoice" ? `<button class="btn ghost" data-sv-act="edit">Услуги и место</button>` : ""}
      ${edit && (x.status === "draft" || ((x.status === "skipped" || x.status === "reverted") && x.base_status === "draft")) ? `<button class="btn" data-sv-act="confirm">Списать</button>` : ""}</div>`, {wide: true});
  $$("[data-sv-act]", box).forEach(b => b.onclick = () => { closeModal(); svAction(b.dataset.svAct, x, r); });
}

async function editVisitServices(x, r) {
  const [svc, set] = await Promise.all([api.services(""), api.stock_auto_settings()]);
  const st = {lines: x.services.filter(s => s.service_id).map(s => ({service_id: s.service_id, qty: s.qty}))};
  if (!st.lines.length) st.lines.push({service_id: "", qty: 1});
  const box = modal(`<div class="m-h"><h3>Услуги приёма ${fmtDT(x.start)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted">${x.source === "dp" ? "Dentist Plus передал услуги ниже — исправьте, если они другие." : `Dentist Plus не передал услуги этого приёма (${NO_DP_TEXT}). Укажите, что было сделано: материалы спишутся по нормам этих услуг.`}</div>
      ${x.unknown.length ? `<div class="warn-line">Нет в прайсе: ${esc(x.unknown.join(", "))}</div>` : ""}
      <table class="tbl compact"><thead><tr><th>Услуга</th><th class="num" style="width:110px">Кол-во</th><th></th></tr></thead><tbody id="svLines"></tbody></table>
      <div><button class="btn ghost small" id="svAdd">+ Услуга</button></div>
      <label class="fl">Списать с места<select class="input" id="svLoc">${set.locations.map(l => `<option value="${esc(l.id)}" ${l.id === (x.location_id || "") ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>
      <div class="auth-err" id="svErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="svOk">Сохранить</button></div>`, {wide: true});
  const draw = () => {
    $("#svLines").innerHTML = st.lines.map((l, i) => `<tr><td><select class="input" data-i="${i}" data-f="service_id"><option value="">— выберите услугу —</option>${svc.map(s => `<option value="${esc(s.id)}" ${s.id === l.service_id ? "selected" : ""}>${esc(s.title)}${s.code ? " · " + esc(s.code) : ""}</option>`).join("")}</select></td>
      <td><input class="input num" type="number" min="0" step="any" data-i="${i}" data-f="qty" value="${esc(l.qty)}"></td><td><button class="linkbtn" data-rm="${i}">убрать</button></td></tr>`).join("");
    $$("#svLines [data-f]").forEach(el => el.onchange = () => { st.lines[+el.dataset.i][el.dataset.f] = el.value; });
    $$("#svLines [data-rm]").forEach(b => b.onclick = () => { st.lines.splice(+b.dataset.rm, 1); if (!st.lines.length) st.lines.push({service_id: "", qty: 1}); draw(); });
  };
  draw();
  $("#svAdd", box).onclick = () => { st.lines.push({service_id: "", qty: 1}); draw(); };
  $("#svOk", box).onclick = async () => {
    try {
      await api.stock_visit_save(x.id, st.lines.filter(l => l.service_id), $("#svLoc").value);
      closeModal(); toast("Услуги сохранены — приём в черновиках списания"); stockVisits();
    } catch (e) { $("#svErr").textContent = errText(e); }
  };
}

async function visitSettings() {
  const s = await api.stock_auto_settings();
  const box = modal(`<div class="m-h"><h3>Списание по приёмам</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="fl">Как списывать</div>
      ${Object.entries(s.modes).map(([k, t]) => `<label class="radio-row"><input type="radio" name="svMode" value="${k}" ${s.mode === k ? "checked" : ""}> ${esc(t)}</label>`).join("")}
      <div class="muted">«Сразу» списывает только приёмы с дня включения${s.mode === "auto" && s.auto_since ? ` (сейчас — с ${fmtDate(s.auto_since)})` : ""}; более ранние остаются черновиками. Приём «в кресле» ждёт до завершения или до следующего дня.</div>
      <div class="grid2"><label class="fl">Место, если кабинет неизвестен<select class="input" id="svsLoc">${s.locations.map(l => `<option value="${esc(l.id)}" ${l.id === (s.location || "") ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>
        <label class="fl">Показывать приёмы за, дней<input class="input" type="number" min="1" max="62" id="svsDays" value="${esc(s.days)}"></label></div>
      <label class="dx-doc sv-wrap"><input type="checkbox" id="svsTitle" ${s.by_title === "1" ? "checked" : ""}>Если Dentist Plus не передал услуги — брать услугу, название которой совпадает с названием записи</label>
      <div class="muted">Кабинет определяется по креслу приёма (в «Местах хранения» у кабинета указывается кресло), затем по филиалу.</div>
      <div class="auth-err" id="svsErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="svsOk">Сохранить</button></div>`);
  $("#svsOk", box).onclick = async () => {
    const mode = ($("[name=svMode]:checked", box) || {}).value || "draft";
    if (mode === "auto" && s.mode !== "auto" && !await ask("Списывать материалы автоматически?", {ok: "Включить", text: "Завершённые приёмы Dentist Plus с сегодняшнего дня будут списываться сами по нормам услуг. Любое списание можно отменить."})) return;
    try {
      await api.stock_auto_settings_save({mode, location: $("#svsLoc").value, days: $("#svsDays").value, by_title: $("#svsTitle").checked});
      closeModal(); toast("Настройки сохранены"); stockVisits();
    } catch (e) { $("#svsErr").textContent = errText(e); }
  };
}

/* ------------------------------------------------------------ «Места хранения» */
async function stockPlaces() {
  const [locs, docs] = await Promise.all([api.stock_locations(), api.stock_docs("transfer")]);
  const edit = can("stock_edit");
  $("#stockBody").innerHTML = `<div class="tab-tools"><span class="muted">Основной склад, кабинеты и филиалы. Остаток каждого места — по его движениям; общий остаток клиники не меняется при перемещении.</span><span class="grow"></span>
      ${edit ? `<button class="btn ghost" id="plNew">Новое место</button>${locs.length > 1 ? `<button class="btn" id="plMove">Перемещение</button>` : ""}` : ""}</div>
    <div class="pbody" style="margin-top:8px"><table class="tbl"><thead><tr><th>Место</th><th>Вид</th><th>Кресло / филиал</th><th class="num">Позиций</th><th class="num">Сумма остатков</th><th></th></tr></thead><tbody>${
      locs.map(l => `<tr data-pl="${esc(l.id)}" class="lnk-row"><td><b>${esc(l.name)}</b>${l.comment ? `<small class="muted" style="display:block">${esc(l.comment)}</small>` : ""}</td><td>${esc(l.kind_title)}</td>
        <td class="muted">${esc([l.chair, l.branch_id ? "филиал " + l.branch_id : ""].filter(Boolean).join(" · ") || (l.kind === "main" ? "всё, что не в кабинетах" : "—"))}</td>
        <td class="num">${l.items}</td><td class="num">${money(l.value)}</td>
        <td class="pills">${l.negative ? `<span class="pill st-cancel" title="Списано больше, чем было перемещено сюда">меньше нуля: ${l.negative}</span>` : ""}<button class="linkbtn" data-pl-bal="${esc(l.id)}">остатки</button></td></tr>`).join("")}</tbody></table>
      ${locs.length === 1 ? `<div class="empty sm"><span>Пока всё хранится на основном складе. Добавьте кабинеты и филиалы, чтобы видеть остатки по местам и списывать по приёмам из нужного кабинета.</span></div>` : ""}</div>
    <h4 class="sub-h">Перемещения</h4>
    <div class="pbody">${docs.length ? `<table class="tbl compact"><thead><tr><th>Дата</th><th>№</th><th>Откуда → куда</th><th class="num">Строк</th><th class="num">Сумма</th><th>Сотрудник</th></tr></thead><tbody>${
      docs.map(x => `<tr data-d="${esc(x.id)}" class="lnk-row"><td>${fmtDate(x.date)}</td><td>${esc(x.number)}</td><td>${esc(x.location_name)} → ${esc(x.to_location_name)}</td><td class="num">${x.lines}</td><td class="num">${money(x.total)}</td><td class="muted">${esc(x.user_name || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty sm"><span>Перемещений пока не было</span></div>`}</div>`;
  const on = (s2, fn) => { const el = $(s2); if (el) el.onclick = fn; };
  on("#plNew", () => editPlace({kind: "cabinet"}));
  on("#plMove", () => openTransfer());
  $$("#stockBody tr[data-pl]").forEach(tr => tr.onclick = () => { const l = locs.find(x => x.id === tr.dataset.pl); if (l && l.kind !== "main" && edit) editPlace(l); });
  $$("#stockBody [data-pl-bal]").forEach(b => b.onclick = e => { e.stopPropagation(); S.stockLoc = b.dataset.plBal; S.stockTab = "balance"; loadStock(); });
  $$("#stockBody tr[data-d]").forEach(tr => tr.onclick = () => openStockDocView(tr.dataset.d));
}

async function editPlace(p) {
  const s = await api.stock_auto_settings();
  const box = modal(`<div class="m-h"><h3>${p.id ? "Место хранения" : "Новое место хранения"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid2"><label class="fl">Название*<input class="input" id="plN" value="${esc(p.name || "")}" placeholder="Кабинет 1" autofocus></label>
        <label class="fl">Вид<select class="input" id="plK">${Object.entries(STK.loc_kinds || {cabinet: "Кабинет", branch: "Филиал", store: "Склад"}).map(([k, t]) => `<option value="${k}" ${k === (p.kind || "cabinet") ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
      <div class="grid2"><label class="fl">Кресло (как в Dentist Plus)<input class="input" id="plC" value="${esc(p.chair || "")}" list="plChairs" placeholder="Кресло 1"></label>
        <label class="fl">Филиал<select class="input" id="plB"><option value="">—</option>${s.branches.map(b => `<option value="${esc(b.id)}" ${String(b.id) === String(p.branch_id || "") ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label></div>
      <datalist id="plChairs">${s.chairs.map(c => `<option value="${esc(c)}">`).join("")}</datalist>
      <label class="fl">Комментарий<input class="input" id="plCom" value="${esc(p.comment || "")}"></label>
      <div class="muted">По креслу приём Dentist Plus списывается из этого кабинета; место с филиалом, но без кресла, — для всех приёмов филиала.</div>
      <div class="auth-err" id="plErr"></div></div>
    <div class="m-f">${p.id ? `<button class="btn ghost small danger" id="plDel">Закрыть место</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="plOk">Сохранить</button></div>`);
  $("#plOk", box).onclick = async () => {
    try {
      await api.stock_location_save({id: p.id, name: $("#plN").value, kind: $("#plK").value, chair: $("#plC").value, branch_id: $("#plB").value, comment: $("#plCom").value});
      closeModal(); toast("Сохранено"); loadStock();
    } catch (e) { $("#plErr").textContent = errText(e); }
  };
  const del = $("#plDel", box);
  if (del) del.onclick = async () => {
    if (!await ask(`Закрыть «${p.name}»?`, {danger: true, ok: "Закрыть", text: "Закрыть можно только пустое место. История движений сохранится."})) return;
    try { await api.stock_location_delete(p.id); closeModal(); toast("Место закрыто"); loadStock(); } catch (e) { toast(errText(e), true); }
  };
}

async function openTransfer(preset = {}) {
  const locs = await api.stock_locations();
  if (locs.length < 2) return toast("Сначала добавьте кабинет или филиал во вкладке «Места хранения»", true);
  const st = {from: preset.from ?? "", to: preset.to ?? (locs[1] || {}).id ?? "", lines: [{material_id: "", qty: ""}]};
  const box = modal(`<div class="m-h"><h3>Перемещение материалов</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid3"><label class="fl">Откуда<select class="input" id="trF">${locs.map(l => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")}</select></label>
        <label class="fl">Куда<select class="input" id="trT">${locs.map(l => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")}</select></label>
        <label class="fl">Дата<input class="input" type="date" id="trD" value="${iso(new Date())}"></label></div>
      <table class="tbl compact doc-lines"><thead><tr><th>Материал</th><th class="num">Есть там</th><th class="num" style="width:120px">Переместить</th><th></th></tr></thead><tbody id="trLines"></tbody></table>
      <div><button class="btn ghost small" id="trAdd">+ Ещё материал</button> <button class="btn ghost small" id="trAllLow">Добавить, чего не хватает до минимума</button></div>
      <label class="fl">Комментарий<input class="input" id="trCom"></label><div class="auth-err" id="trErr"></div></div>
    <div class="m-f"><span class="muted" id="trTot"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="trOk">Переместить</button></div>`, {wide: true});
  $("#trF").value = st.from; $("#trT").value = st.to;
  let mats = [];
  const load = async () => { mats = await api.materials("", false, false, $("#trF").value); draw(); };
  const draw = () => {
    const by = Object.fromEntries(mats.map(m => [m.id, m]));
    $("#trLines").innerHTML = st.lines.map((l, i) => { const m = by[l.material_id];
      return `<tr><td><select class="input" data-i="${i}" data-f="material_id"><option value="">— выберите материал —</option>${mats.map(x => `<option value="${esc(x.id)}" ${x.id === l.material_id ? "selected" : ""}>${esc(x.name)} (${qtyFmt(x.balance, x.unit)})</option>`).join("")}</select></td>
        <td class="num muted">${m ? qtyFmt(m.balance, m.unit) : ""}</td><td><input class="input num" type="number" min="0" step="any" data-i="${i}" data-f="qty" value="${esc(l.qty)}"></td>
        <td><button class="linkbtn" data-rm="${i}">убрать</button></td></tr>`; }).join("");
    $$("#trLines [data-f]").forEach(el => el.onchange = () => { st.lines[+el.dataset.i][el.dataset.f] = el.value; draw(); });
    $$("#trLines [data-rm]").forEach(b => b.onclick = () => { st.lines.splice(+b.dataset.rm, 1); if (!st.lines.length) st.lines.push({material_id: "", qty: ""}); draw(); });
    const n = st.lines.filter(l => l.material_id && +l.qty > 0).length;
    $("#trTot").textContent = n ? `Строк: ${n} · на сумму ${money(st.lines.reduce((a, l) => a + (+l.qty || 0) * ((by[l.material_id] || {}).price || 0), 0))}` : "";
  };
  $("#trF").onchange = load;
  $("#trAdd", box).onclick = () => { st.lines.push({material_id: "", qty: ""}); draw(); };
  $("#trAllLow", box).onclick = async () => {  /* what the destination lacks to the material's minimum, from what the source has */
    const there = await api.materials("", false, false, $("#trT").value);
    const add = there.filter(m => m.min_qty > 0 && m.balance < m.min_qty).map(m => {
      const src = mats.find(x => x.id === m.id); const q = Math.min(m.min_qty - m.balance, src ? src.balance : 0);
      return q > 0 ? {material_id: m.id, qty: String(Math.round(q * 1000) / 1000)} : null; }).filter(Boolean);
    if (!add.length) return toast("Всего хватает или переместить нечего");
    st.lines = [...st.lines.filter(l => l.material_id), ...add]; draw();
  };
  $("#trOk", box).onclick = async () => {
    try {
      await api.stock_transfer({from_id: $("#trF").value, to_id: $("#trT").value, date: $("#trD").value, comment: $("#trCom").value,
        lines: st.lines.filter(l => l.material_id)});
      closeModal(); toast("Материалы перемещены"); loadStock();
    } catch (e) { $("#trErr").textContent = errText(e); }
  };
  load();
}

/* ------------------------------------------------------------ «Бухгалтерия» → «Себестоимость» */
async function accCost(body) {
  let r;
  try { r = await api.service_costs(S.costMonth); } catch (e) { body.innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
  S.costR = r;
  const q = (S.costQ || "").toLowerCase();
  const rows = r.rows.filter(x => (!q || `${x.code} ${x.title} ${x.category}`.toLowerCase().includes(q)) && (!S.costNoNorms || x.no_norms) && (!S.costMade || x.made));
  const pctSrc = {setting: "задан в настройках", schemes: "средний по схемам оплаты врачей", none: "схемы оплаты врачей не заданы"}[r.doctor_pct_src];
  const share = v => v == null ? "—" : `${(+v).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
  body.innerHTML = accTools(`<div class="month-nav"><button class="icon-btn" id="coPrev" title="Предыдущий месяц">‹</button><b>${monthName(r.month)}</b><button class="icon-btn" id="coNext" title="Следующий месяц">›</button></div>`, false) +
    `<div class="stat-row">
      <div class="stat"><span>Оказано услуг за месяц</span><b>${(r.made_from.invoices + r.made_from.visits).toLocaleString("ru-RU")}</b><small class="muted">по счетам ${r.made_from.invoices.toLocaleString("ru-RU")} · по приёмам DP ${r.made_from.visits.toLocaleString("ru-RU")}</small></div>
      <div class="stat"><span>По прайсу</span><b>${rub(r.revenue)}</b></div>
      <div class="stat"><span>Себестоимость</span><b>${rub(r.cost)}</b><small class="muted">материалы ${rub(r.materials)}</small></div>
      <div class="stat ${r.margin < 0 ? "warn" : ""}"><span>Маржа</span><b>${rub(r.margin)}</b><small class="muted">${share(r.margin_pct)}</small></div>
      <div class="stat ${r.no_norms ? "warn" : ""}"><span>Услуг без норм</span><b>${r.no_norms}</b></div></div>
    <div class="tab-tools"><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="coQ" placeholder="Услуга" value="${esc(S.costQ || "")}"></div>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="coMade" ${S.costMade ? "checked" : ""}><span class="sw"></span>Оказанные за месяц</label>
      <label class="switch-row" style="margin:0"><input type="checkbox" id="coNN" ${S.costNoNorms ? "checked" : ""}><span class="sw"></span>Без норм</label><span class="grow"></span>
      <button class="btn ghost" id="coSet">Настройки</button></div>
    <div class="note-box">Себестоимость = материалы по нормам × последняя цена закупки + лаборатория + прочие затраты + процент врача от цены (${share(r.doctor_pct)} — ${esc(pctSrc)}; у услуги можно задать свой). Материалы в ОПиУ: <b>${esc(r.pnl_modes[r.settings.pnl_materials])}</b>.</div>
    <div class="pbody"><div class="tbl-scroll"><table class="tbl compact co-tbl"><thead><tr><th>Услуга</th><th class="num">Цена</th><th class="num">Материалы</th><th class="num">Лаборатория</th><th class="num">Прочее</th><th class="num">Врач</th><th class="num">Себестоимость</th><th class="num">Маржа</th><th class="num">%</th><th class="num">Оказано</th></tr></thead><tbody>${
      rows.map(x => `<tr data-co="${esc(x.service_id)}" class="lnk-row ${x.margin < 0 ? "neg" : ""}"><td><b>${esc(x.title)}</b><small class="muted" style="display:block">${esc([x.code, x.category].filter(Boolean).join(" · "))}</small></td>
        <td class="num">${money(x.price)}</td><td class="num ${x.no_norms ? "warn-t" : ""}" title="${esc(x.lines.map(l => `${l.name}: ${l.qty} ${l.unit} × ${l.price} ₽`).join("\n"))}">${x.no_norms ? "нет норм" : money(x.materials)}</td>
        <td class="num">${x.lab ? money(x.lab) : "—"}</td><td class="num">${x.other ? money(x.other) : "—"}</td>
        <td class="num">${money(x.doctor)}<small class="muted" style="display:block">${share(x.doctor_pct)}${x.doctor_pct_own ? " свой" : ""}</small></td>
        <td class="num"><b>${money(x.cost)}</b></td><td class="num ${x.margin < 0 ? "bad-t" : ""}">${money(x.margin)}</td><td class="num muted">${share(x.margin_pct)}</td>
        <td class="num">${x.made ? x.made.toLocaleString("ru-RU") : "—"}</td></tr>`).join("") || `<tr><td colspan="10" class="muted">Ничего не найдено</td></tr>`}</tbody></table></div>
      <div class="muted note-line">«Оказано» — услуги из счетов, выставленных в программе, и из приёмов Dentist Plus, списанных во вкладке «Склад» → «По приёмам». Оплаты Dentist Plus в его API не передаются, поэтому выручка здесь — по ценам прайса.</div></div>`;
  $("#coPrev").onclick = () => { S.costMonth = shiftMonth(S.costMonth, -1); loadAccounting(); };
  $("#coNext").onclick = () => { S.costMonth = shiftMonth(S.costMonth, 1); loadAccounting(); };
  let t; $("#coQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.costQ = e.target.value; accCost(body).then(() => { const i = $("#coQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  $("#coMade").onchange = e => { S.costMade = e.target.checked; accCost(body); };
  $("#coNN").onchange = e => { S.costNoNorms = e.target.checked; accCost(body); };
  $("#coSet").onclick = () => costSettings(r);
  $$("#accBody tr[data-co]").forEach(tr => tr.onclick = () => editServiceCost(r.rows.find(x => x.service_id === tr.dataset.co)));
}

function editServiceCost(x) {
  const box = modal(`<div class="m-h"><h3>Себестоимость: ${esc(x.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted">Цена по прайсу ${money(x.price)}. Материалы по нормам списания — ${x.no_norms ? "нормы не заданы («Склад» → «Нормы списания»)" : money(x.materials)}.</div>
      ${x.lines.length ? `<table class="tbl compact"><tbody>${x.lines.map(l => `<tr><td>${esc(l.name)}</td><td class="num">${qtyFmt(l.qty, l.unit)}</td><td class="num">${money(l.price)}</td><td class="num">${money(l.sum)}</td></tr>`).join("")}</tbody></table>` : ""}
      <div class="grid3"><label class="fl">Лаборатория, ₽<input class="input" type="number" min="0" step="any" id="coL" value="${x.lab || ""}"></label>
        <label class="fl">Прочие затраты, ₽<input class="input" type="number" min="0" step="any" id="coO" value="${x.other || ""}"></label>
        <label class="fl">Процент врача, %<input class="input" type="number" min="0" max="100" step="any" id="coP" value="${x.doctor_pct_own ? x.doctor_pct : ""}" placeholder="как у клиники: ${S.costR ? S.costR.doctor_pct : ""}"></label></div>
      <label class="fl">Комментарий<input class="input" id="coN" value="${esc(x.note || "")}"></label><div class="auth-err" id="coErr"></div></div>
    <div class="m-f"><span class="muted">Пустой процент — процент клиники</span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="coOk">Сохранить</button></div>`);
  $("#coOk", box).onclick = async () => {
    try {
      await api.service_cost_save({service_id: x.service_id, lab: $("#coL").value, other: $("#coO").value, doctor_pct: $("#coP").value, note: $("#coN").value});
      closeModal(); toast("Сохранено"); loadAccounting();
    } catch (e) { $("#coErr").textContent = errText(e); }
  };
}

function costSettings(r) {
  const s = r.settings;
  const box = modal(`<div class="m-h"><h3>Себестоимость и ОПиУ</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <label class="fl">Процент врача в себестоимости, %<input class="input" type="number" min="0" max="100" step="any" id="csP" value="${esc(s.doctor_pct)}" placeholder="средний по схемам оплаты: ${r.doctor_pct_src === "schemes" ? r.doctor_pct : "—"}"></label>
      <div class="muted">Пусто — средний процент из схем оплаты врачей («Зарплата»).</div>
      <div class="fl">Материалы в ОПиУ и финмодели</div>
      ${Object.entries(r.pnl_modes).map(([k, t]) => `<label class="radio-row"><input type="radio" name="csM" value="${k}" ${s.pnl_materials === k ? "checked" : ""}> ${esc(t)}</label>`).join("")}
      <div class="muted">По закупкам — как было: расходы статьи «Материалы и закупки». По списанию — стоимость того, что ушло со склада за месяц (услуги, приёмы, списания); закупки тогда в ОПиУ не входят, чтобы не считать материалы дважды.</div>
      <div class="auth-err" id="csErr"></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="csOk">Сохранить</button></div>`);
  $("#csOk", box).onclick = async () => {
    try {
      await api.stock_cost_settings_save({doctor_pct: $("#csP").value, pnl_materials: ($("[name=csM]:checked", box) || {}).value || "expenses"});
      closeModal(); toast("Сохранено"); loadAccounting();
    } catch (e) { $("#csErr").textContent = errText(e); }
  };
}
