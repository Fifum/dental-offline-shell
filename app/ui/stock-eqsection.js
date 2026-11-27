"use strict";
/* 3.15 «Оборудование» by the clinic's mockups (media/client-refs/oborudovanie-2026-11-27): the bar of the section's tabs with
   «Ещё», and its screens — the overview, the register, receipts, moves, service and repair, depreciation, disposal, the
   purchase plan, someone else's equipment, documents, analytics, the log and the references. The card of a piece stays in
   stock-eqcard.js; the money is sent by the server only to «Бухгалтерия». */
const EQS = {refs: null};
const EQN = {  // the icons of the section's tabs
  eq_overview: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></svg>',
  equipment: '<svg viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/></svg>',
  eq_receipts: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8.5v7M8.5 12h7"/></svg>',
  eq_moves: '<svg viewBox="0 0 24 24"><path d="M4 8.5h15l-3.5-3.5M20 15.5H5l3.5 3.5"/></svg>',
  service: '<svg viewBox="0 0 24 24"><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-5 4 4 0 0 1 0 3z"/></svg>',
  amort: '<svg viewBox="0 0 24 24"><path d="M4 19.5h16M6.5 16v-4M10.5 16V9M14.5 16v-5M18.5 16V6"/></svg>',
  more: '<svg viewBox="0 0 24 24"><path d="m6 9.5 6 6 6-6"/></svg>',
};

/** The bar of the section «Оборудование»: big tabs with icons, the rest under «Ещё» (stockHead draws it). */
function eqNavHtml(a) {
  const cur = S.stockTab, inMore = (a.more || []).some(t => t[0] === cur);
  const more = (a.more || []).find(t => t[0] === cur);
  return a.tabs.map(([k, t, tip]) => `<button data-k="${k}" ${tip ? `title="${esc(tip)}"` : ""}>${EQN[k] || ""}<span>${t}</span></button>`).join("")
    + `<span class="eqnav-more"><button class="eqnav-mb ${inMore ? "on" : ""}" id="eqMoreBtn" type="button"><span>${inMore ? esc(more[1]) : "Ещё"}</span>${EQN.more}</button>
      <span class="eqnav-menu" id="eqMoreMenu" hidden>${a.more.map(([k, t]) => `<button data-k="${k}" class="${k === cur ? "on" : ""}">${t}</button>`).join("")}</span></span>`;
}
function eqNavWire() {
  const b = $("#eqMoreBtn"), m = $("#eqMoreMenu"); if (!b || !m) return;
  b.onclick = ev => { ev.stopPropagation(); m.hidden = !m.hidden; if (!m.hidden) setTimeout(() => document.addEventListener("click", () => { m.hidden = true; }, {once: true})); };
}

/* ------------------------------------------------------------ «Справочники и настройки» */
async function eqRefsTab() {
  const body = $("#stockBody");
  const r = EQS.refs = await api.equipment_refs();
  const edit = can("equipment");
  const yrs = n => n ? (n % 12 ? `${n} мес.` : `${n / 12} ${plural(n / 12, "год", "года", "лет")}`) : "—";
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Справочники и настройки</h2><span class="muted">Категории имущества, нормативы срока службы, способы учёта</span></div></div>
    <div class="eqs-grid2">
      <section class="eqs-card"><h3>Категории имущества</h3>
        <div class="muted eqs-hint">Категория не задаёт учёт: у каждой единицы в карточке свой способ — с амортизацией или количественный без амортизации. Норматив срока службы — подсказка в карточке, срок всегда ставится вручную.</div>
        <table class="tbl compact eqs-t"><thead><tr><th>Категория</th><th class="num">Единиц</th><th class="num">Норматив, мес.</th>${edit ? "<th></th>" : ""}</tr></thead><tbody id="eqCats">${r.categories.map((c, i) => `<tr data-i="${i}">
          <td>${edit ? `<input class="input" data-cn value="${esc(c.name)}">` : esc(c.name)}</td><td class="num muted">${c.count || "—"}</td>
          <td class="num">${edit ? `<input class="input num" type="number" min="0" max="600" step="1" data-cl value="${c.life || ""}" placeholder="—">` : yrs(c.life)}</td>
          ${edit ? `<td><button class="linkbtn danger-t" data-cdel ${c.count ? `disabled title="Есть оборудование этой категории"` : ""}>убрать</button></td>` : ""}</tr>`).join("")}</tbody></table>
        ${edit ? `<div class="eqs-row"><button class="btn ghost small" id="eqCatAdd">+ Категория</button><span class="grow"></span><button class="btn" id="eqCatSave">Сохранить</button></div>` : ""}</section>
      <section class="eqs-card"><h3>Способы учёта и принадлежность</h3>
        <dl class="eqs-dl">${Object.entries(r.accounting).map(([k, t]) => `<dt>${esc(t)}</dt><dd>${k === "amort" ? "Стоимость переходит в расходы помесячно амортизацией (линейно, срок — в карточке)." : "Учитывается штуками; стоимость не амортизируется и не попадает в ОПиУ амортизацией."}</dd>`).join("")}</dl>
        <h3>Чьё оборудование</h3><dl class="eqs-dl">${Object.entries(r.ownership).map(([k, t]) => `<dt>${esc(t)}</dt><dd>${k === "own" ? "Имущество клиники — амортизация и выбытие в финотчёте." : k === "leasing" ? "Учитывается как имущество клиники." : "Стороннее: не амортизируется, в разделе «Стороннее оборудование»."}</dd>`).join("")}</dl>
        ${can("accounting") ? `<h3>Часы работы кресла в месяц</h3><div class="eqs-row"><input class="input num" type="number" min="1" max="744" id="eqChairH" value="${r.chair_hours}" style="width:120px"><span class="muted">для «амортизации на кресло-час»</span><span class="grow"></span><button class="btn ghost" id="eqChairSave">Сохранить</button></div>` : ""}</section>
    </div></div>`;
  if (edit) {
    $("#eqCatAdd").onclick = () => { $("#eqCats").insertAdjacentHTML("beforeend", `<tr><td><input class="input" data-cn placeholder="Новая категория"></td><td class="num muted">—</td><td class="num"><input class="input num" type="number" min="0" max="600" data-cl placeholder="—"></td><td><button class="linkbtn danger-t" data-cdel>убрать</button></td></tr>`); wireDel(); $("#eqCats tr:last-child [data-cn]").focus(); };
    const wireDel = () => $$("[data-cdel]", body).forEach(b => b.onclick = () => b.closest("tr").remove());
    wireDel();
    $("#eqCatSave").onclick = async () => {
      const rows = $$("#eqCats tr", body).map(tr => [$("[data-cn]", tr).value.trim(), $("[data-cl]", tr).value]).filter(x => x[0]);
      try { await api.equipment_refs_save({categories: rows.map(x => x[0]), life: Object.fromEntries(rows.map(x => [x[0], x[1] || 0]))}); toast("Сохранено"); eqRefsTab(); }
      catch (e) { toast(errText(e), true); }
    };
  }
  const ch = $("#eqChairSave"); if (ch) ch.onclick = async () => { try { await api.equipment_settings_save({chair_hours: $("#eqChairH").value}); toast("Сохранено"); } catch (e) { toast(errText(e), true); } };
}
