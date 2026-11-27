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

/* ------------------------------------------------------------ helpers of the screens */
const EQX = {
  box: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/></svg>',
  coins: '<svg viewBox="0 0 24 24"><ellipse cx="9" cy="7" rx="5.5" ry="2.5"/><path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5S14.5 12.4 14.5 11V7"/><path d="M9.5 15.5c.6 1 2.6 1.8 5 1.8 3 0 5.5-1.1 5.5-2.5v-4c0-1.2-1.8-2.2-4.3-2.5"/></svg>',
  pie: '<svg viewBox="0 0 24 24"><path d="M12 3.5v8.5h8.5A8.5 8.5 0 1 1 12 3.5z"/><path d="M15 3.8A8.5 8.5 0 0 1 20.2 9H15z"/></svg>',
  calc: '<svg viewBox="0 0 24 24"><rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M8.5 7.5h7M8.5 12h.01M12 12h.01M15.5 12h.01M8.5 15.5h.01M12 15.5h.01M15.5 15.5h.01"/></svg>',
  ok: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.8 2.7L16.2 9.5"/></svg>',
  wrench: '<svg viewBox="0 0 24 24"><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-5 4 4 0 0 1 0 3z"/></svg>',
  gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  cal: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  cycle: '<svg viewBox="0 0 24 24"><path d="M19.5 12a7.5 7.5 0 0 1-13 5M4.5 12a7.5 7.5 0 0 1 13-5"/><path d="M17.5 3.5V7H14M6.5 20.5V17H10"/></svg>',
  cart: '<svg viewBox="0 0 24 24"><path d="M3 4.5h2.4l2.3 10.3h10.5l2.3-7.3H6.3"/><circle cx="9.3" cy="18.8" r="1.4"/><circle cx="16.8" cy="18.8" r="1.4"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  qr: '<svg viewBox="0 0 24 24"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><path d="M8 8h3v3H8zM13 13h3v3h-3zM13 8h3M8 13v3"/></svg>',
  check: '<svg viewBox="0 0 24 24"><rect x="4.5" y="4.5" width="15" height="16" rx="2.5"/><path d="M9 3v3h6V3M8.5 13l2.5 2.5 4.5-5"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17h.01"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 12.5h6M9 16h6"/></svg>',
  chev: '<svg viewBox="0 0 24 24"><path d="m9.5 6 6 6-6 6"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/></svg>',
  grid: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg>',
};
const eqTile = (ic, t, v, cls = "") => `<div class="eqs-tile ${cls}"><i>${ic}</i><span>${t}</span><b>${v}</b></div>`;
const eqMoney = v => money(Math.round(+v || 0));
const eqShortDate = s => { if (!s) return "—"; const [y, m, d] = s.split("-").map(Number); return `${d} ${["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"][m - 1]} ${y}`; };
/** A ring of shares (SVG, explicit arcs): [{value, cls}] with the total in the middle. */
function eqRing(parts, center, sub) {
  const tot = parts.reduce((s, p) => s + p.value, 0) || 1, R = 52, C = 2 * Math.PI * R;
  let off = 0;
  const arcs = parts.filter(p => p.value > 0).map(p => { const len = p.value / tot * C, a = `<circle r="${R}" cx="70" cy="70" class="${p.cls}" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}"/>`; off += len; return a; }).join("");
  return `<div class="eqs-ring"><svg viewBox="0 0 140 140"><circle r="${R}" cx="70" cy="70" class="bg"/>${arcs}</svg><div><b>${center}</b><small>${sub}</small></div></div>`;
}

/* ------------------------------------------------------------ «Обзор» */
async function eqOverview() {
  const body = $("#stockBody");
  const o = await api.equipment_overview();
  const m = o.money, edit = can("equipment"), c = o.condition, tot = c.ok + c.service + c.faulty;
  const pct = n => tot ? `${(n * 100 / tot).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %` : "0 %";
  const maxCat = Math.max(1, ...o.by_category.map(g => m ? g.cost : g.count));
  const acts = [edit && ["add", EQX.plus, "Добавить оборудование"], edit && ["qr", EQX.qr, "Печать QR-этикеток"], can("equipment") && ["repair", EQX.wrench, "Создать заявку на ремонт"],
    can("equipment") && ["inv", EQX.check, "Провести инвентаризацию"], can("equipment") && ["plan", EQX.cal, "Запланировать ТО"]].filter(Boolean);
  const at = o.attention;
  body.innerHTML = `<div class="eqs">
    <div class="eqs-tiles">${m ? eqTile(EQX.box, "Всего единиц", o.total) + eqTile(EQX.coins, "Первоначальная стоимость", eqMoney(m.cost)) + eqTile(EQX.pie, "Остаточная стоимость", eqMoney(m.residual)) + eqTile(EQX.calc, "Амортизация в месяц", eqMoney(m.monthly))
      : eqTile(EQX.box, "Всего единиц", o.total) + eqTile(EQX.ok, "Исправно", c.ok, "ok") + eqTile(EQX.gear, "На обслуживании", c.service, c.service ? "warn" : "") + eqTile(EQX.wrench, "Требует ремонта", c.faulty, c.faulty ? "bad" : "")}</div>
    <div class="eqs-attn">${[["service_soon", EQX.cal, "Предстоящее ТО (30 дней)"], ["service_overdue", EQX.warn, "Просроченное обслуживание"], ["repairs_open", EQX.wrench, "Открытые заявки на ремонт"], ["to_replace", EQX.cart, "К плановой замене"]]
      .map(([k, ic, t]) => `<button data-attn="${k}" class="${at[k] ? (k === "service_overdue" ? "bad" : "warn") : ""}">${ic}<span>${t}</span><b>${at[k]}</b></button>`).join("")}${m ? `<div class="eqs-attn-x"><span>Полностью амортизировано</span><b>${o.full_amort}</b></div>` : ""}</div>
    <div class="eqs-g2">
      <section class="eqs-card"><h3>Состояние оборудования</h3><div class="eqs-ringrow">${eqRing([{value: c.ok, cls: "ok"}, {value: c.service, cls: "warn"}, {value: c.faulty, cls: "bad"}], tot, plural(tot, "единица", "единицы", "единиц"))}
        <ul class="eqs-legend"><li class="ok"><span>Исправно</span><b>${c.ok} (${pct(c.ok)})</b></li><li class="warn"><span>На обслуживании</span><b>${c.service} (${pct(c.service)})</b></li><li class="bad"><span>Требует ремонта</span><b>${c.faulty} (${pct(c.faulty)})</b></li></ul></div></section>
      <section class="eqs-card"><h3>${m ? "Стоимость по категориям" : "Оборудование по категориям"}</h3>${o.by_category.length ? `<div class="eqs-bars">${o.by_category.map(g => `<div class="eqs-bar"><span>${esc(g.name)}</span><i><u style="width:${Math.max(2, (m ? g.cost : g.count) / maxCat * 100)}%"></u></i><b>${m ? eqMoney(g.cost) : g.count + " шт."}</b>${m ? `<small>${g.share.toLocaleString("ru-RU")} %</small>` : ""}</div>`).join("")}</div>` : `<div class="muted">Оборудования пока нет</div>`}</section>
    </div>
    <div class="eqs-g2">
      <section class="eqs-card"><h3>${EQX.cal}Ближайшие события</h3>${o.events.length ? `<div class="eqs-ev">${o.events.slice(0, 6).map(x => `<button data-e="${esc(x.equipment_id)}" class="${x.overdue ? "late" : ""}">${x.kind === "replace" ? EQX.cart : x.kind === "use_end" ? EQX.doc : x.kind.startsWith("plan_v") ? EQX.cycle : EQX.wrench}<span><b>${esc(x.title)}</b><small>${esc(x.name)}</small></span><em>${x.overdue ? "просрочено · " : ""}${eqShortDate(x.date)}</em></button>`).join("")}</div>` : `<div class="muted">На ближайшие два месяца ничего не запланировано</div>`}</section>
      <section class="eqs-card"><h3>Быстрые действия</h3><div class="eqs-acts">${acts.map(([k, ic, t]) => `<button data-act="${k}">${ic}<span>${t}</span></button>`).join("")}</div></section>
    </div>
    <div class="eqs-g2">
      <section class="eqs-card"><h3>${EQX.warn}Оборудование к замене ${o.to_replace.length ? `<i class="eqs-cnt">${o.to_replace.length}</i>` : ""}</h3>${o.to_replace.length ? `<div class="eqs-repl">${o.to_replace.slice(0, 5).map(x => `<button data-e="${esc(x.id)}"><span class="sn-mat sm">${phHtml(x.photo_id)}</span><span><b>${esc(x.name)}</b><small>${esc([x.inv_number, x.why].filter(Boolean).join(" · "))}</small></span><em class="${x.urgent ? "bad" : "warn"}">${x.urgent ? "Замена" : "План"}</em></button>`).join("")}</div>` : `<div class="muted">${m ? "Нет оборудования с истекающим сроком службы" : "Нет оборудования с запланированной заменой"}</div>`}</section>
      <section class="eqs-card"><h3>${EQX.doc}Последние заявки и работы</h3>${o.requests.length ? `<table class="tbl compact eqs-t2"><thead><tr><th>№</th><th>Оборудование</th><th>Тип</th><th>Статус</th>${m ? '<th class="num">Сумма</th>' : ""}</tr></thead><tbody>${o.requests.map(r => `<tr data-e="${esc(r.equipment_id)}"><td><b>${esc(r.number)}</b></td><td>${esc(r.equipment_name || "—")}</td><td>${esc(r.kind_title)}</td><td><span class="pill ${r.status === "done" ? "st-ok" : r.overdue ? "st-cancel" : "st-come"}">${r.overdue ? "Просрочено" : esc(r.status_title)}</span></td>${m ? `<td class="num">${r.cost ? eqMoney(r.cost) : "—"}</td>` : ""}</tr>`).join("")}</tbody></table>` : `<div class="muted">Заявок на ремонт и ТО ещё не было</div>`}</section>
    </div></div>`;
  loadThumbs(body);
  $$("[data-e]", body).forEach(b => b.onclick = () => openEquipment(b.dataset.e));
  $$("[data-attn]", body).forEach(b => b.onclick = () => { const k = b.dataset.attn; if (k === "to_replace") { S.eqF = {}; S.eqSort = "residual"; } stockGo("equipment", k === "to_replace" ? "equipment" : "service"); });
  $$("[data-act]", body).forEach(b => b.onclick = () => ({add: () => editEquipment({}), qr: () => { S.eqView = "cards"; stockGo("equipment", "equipment"); },
    repair: () => stockGo("equipment", "service"), plan: () => stockGo("equipment", "service"), inv: () => stockGo("inventory", "inv_eq")})[b.dataset.act]());
}

/* ------------------------------------------------------------ «Реестр оборудования» */
async function stockEquipment() {
  if (S.eqOpen) return openEquipment(S.eqOpen, EQ.tab);  // 3.13: the card is a screen of this tab
  const [rows, refs] = await Promise.all([api.equipment_list(S.eqQ || "", false), EQS.refs ? Promise.resolve(EQS.refs) : api.equipment_refs()]);
  EQS.refs = refs;
  const edit = can("equipment"), mon = !!STK.eq_money, f = S.eqF = S.eqF || {}, view = S.eqView || "list", sort = S.eqSort || "inv";
  const places = [...new Map(rows.map(e => [e.location_id || e.location || "", e.location_name || e.location || "Место не указано"])).entries()].sort((a, b) => a[1].localeCompare(b[1], "ru"));
  const cats = [...new Set([...refs.categories.filter(c => c.count).map(c => c.name), ...rows.map(e => e.category).filter(Boolean)])];
  const stat = e => e.third_party ? "third" : e.accounting === "qty" ? "qty" : e.status;
  const cond = e => e.status === "repair" ? "faulty" : e.condition;
  let list = rows.filter(e => (!f.cat || e.category === f.cat) && (f.place == null || f.place === "*" || (e.location_id || e.location || "") === f.place)
    && (!f.cond || cond(e) === f.cond) && (!f.stat || stat(e) === f.stat));
  const resid = e => e.amort && e.amort.on ? e.amort.residual : (e.price || 0);
  const by = {inv: (a, b) => (a.inv_number || "").localeCompare(b.inv_number || "", "ru", {numeric: true}), name: (a, b) => a.name.localeCompare(b.name, "ru"),
    place: (a, b) => (a.location_name || a.location || "").localeCompare(b.location_name || b.location || "", "ru"), cost: (a, b) => (b.price || 0) - (a.price || 0),
    residual: (a, b) => resid(a) - resid(b)}[sort] || (() => 0);
  list = list.slice().sort(by);
  const condPill = e => { const k = cond(e); return `<span class="eqs-cond ${k}">${k === "ok" ? EQX.ok : k === "service" ? EQX.wrench : EQX.warn}${esc(e.status === "repair" ? "В ремонте" : k === "service" ? "На обслуживании" : k === "faulty" ? "Требует ремонта" : "Исправно")}</span>`; };
  const sel = (id, label, opts, cur) => `<label class="eqs-f"><span>${label}</span><select class="input" id="${id}">${opts.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? "") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  const body = $("#stockBody");
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><h2>Реестр оборудования</h2><span class="eqs-chip">${rows.length} ${plural(rows.length, "позиция", "позиции", "позиций")}</span><span class="grow"></span>
      ${edit ? `<button class="btn" id="eqNew">${EQX.plus}Добавить оборудование</button>` : ""}<button class="btn ghost" data-xls="#eqReg" data-xls-name="Реестр оборудования">${EQX.down}Экспорт</button></div>
    <section class="eqs-card eqs-filters">
      <div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="eqQ" placeholder="Название, инв. №, серийный, кабинет или QR" value="${esc(S.eqQ || "")}"></div>
      ${sel("eqFc", "Категория", [["", "Все категории"], ...cats.map(c => [c, c])], f.cat)}
      ${sel("eqFp", "Кабинет / место", [["*", "Все кабинеты"], ...places], f.place ?? "*")}
      ${sel("eqFs", "Состояние", [["", "Все состояния"], ["ok", "Исправно"], ["service", "На обслуживании"], ["faulty", "Требует ремонта"]], f.cond)}
      ${sel("eqFa", "Статус учёта", [["", "Все"], ["in_use", "В работе"], ["repair", "В ремонте"], ["storage", "На складе"], ["qty", "Количественный учёт"], ["third", "Стороннее"]], f.stat)}
      <button class="linkbtn eqs-reset" id="eqFx" ${Object.values(f).some(v => v && v !== "*") ? "" : "hidden"}>${EQX.x}Сбросить</button></section>
    <div class="eqs-bar2"><div class="eqs-seg"><button data-v="list" class="${view === "list" ? "on" : ""}">${EQX.list}Список</button><button data-v="cards" class="${view === "cards" ? "on" : ""}">${EQX.grid}Карточки</button></div>
      <span class="grow"></span><label class="eqs-sort">Сортировка<select class="input" id="eqSort">${[["inv", "Инвентарный номер"], ["name", "Наименование"], ["place", "Кабинет / место"], ...(mon ? [["cost", "Стоимость"], ["residual", "Остаточная стоимость"]] : [])].map(([k, t]) => `<option value="${k}" ${k === sort ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      ${view === "cards" && list.length ? `<button class="btn ghost small" id="eqLabels" title="Опись с QR — на печать">${EQX.qr}Печать описи</button>` : ""}</div>
    ${!list.length ? `<div class="empty"><b>${rows.length ? "Ничего не найдено" : "Оборудования пока нет"}</b><span>${edit && !rows.length ? "Внесите кресла, автоклав, компрессор и другую технику с инвентарными номерами" : rows.length ? "Измените фильтры" : ""}</span></div>`
    : view === "cards" ? `<div class="eqs-cards">${list.map(e => `<button class="eqs-ecard" data-e="${esc(e.id)}"><span class="eqs-ph">${phHtml(e.photo_id)}</span><b>${esc(e.name)}</b><small>${esc([e.inv_number, e.location_name || e.location].filter(Boolean).join(" · "))}</small>${condPill(e)}${mon && e.price ? `<em>${eqMoney(e.price)}${e.amort && e.amort.on ? ` · ост. ${eqMoney(e.amort.residual)}` : ""}</em>` : ""}</button>`).join("")}</div>
      <table class="tbl" id="eqReg" hidden>${eqRegTable(list, mon, condPill)}</table>`
    : `<section class="eqs-card eqs-tcard"><table class="tbl eqs-reg" id="eqReg">${eqRegTable(list, mon, condPill)}</table><div class="eqs-foot muted">Показано: ${list.length} из ${rows.length}</div></section>`}</div>`;
  const eqq = $("#eqQ");
  let t; eqq.oninput = e => { clearTimeout(t); t = setTimeout(() => { S.eqQ = e.target.value; stockEquipment().then(() => { const i = $("#eqQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200); };
  eqq.onkeydown = async e => {  // 3.14: the QR of a label opens the card
    if (e.key !== "Enter" || !eqq.value.trim()) return;
    try { const r = await api.stock_scan(eqq.value.trim()); if (r.equipment_id) { clearTimeout(t); S.eqQ = ""; openEquipment(r.equipment_id); } } catch (x) { /* a word to search */ }
  };
  const on = (id, fn) => { const el = $(id, body); if (el) el.onchange = fn; };
  on("#eqFc", e => { f.cat = e.target.value; stockEquipment(); }); on("#eqFp", e => { f.place = e.target.value; stockEquipment(); });
  on("#eqFs", e => { f.cond = e.target.value; stockEquipment(); }); on("#eqFa", e => { f.stat = e.target.value; stockEquipment(); });
  on("#eqSort", e => { S.eqSort = e.target.value; stockEquipment(); });
  const x = $("#eqFx", body); if (x) x.onclick = () => { S.eqF = {}; stockEquipment(); };
  $$(".eqs-seg button", body).forEach(b => b.onclick = () => { S.eqView = b.dataset.v; stockEquipment(); });
  const n = $("#eqNew", body); if (n) n.onclick = () => editEquipment({});
  const lb = $("#eqLabels", body); if (lb) lb.onclick = () => printEquipmentSheet(list, "");
  $$("[data-e]", body).forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e));
  loadThumbs(body);
}
function eqRegTable(list, mon, condPill) {
  return `<thead><tr><th>Инв. номер</th><th>Наименование</th><th>Категория</th><th>Кабинет / место</th><th>Состояние</th>${mon ? `<th class="num">Первоначальная стоимость</th><th class="num">Остаточная стоимость</th><th class="num">Амортизация в месяц</th>` : ""}</tr></thead><tbody>${
    list.map(e => `<tr data-e="${esc(e.id)}"><td><b>${esc(e.inv_number || "—")}</b></td><td class="lnk"><div class="sn-mat sm">${phHtml(e.photo_id)}<span><b>${esc(e.name)}</b>${(e.qty || 1) > 1 ? ` <small class="muted">× ${e.qty}</small>` : ""}<small class="muted" style="display:block">${esc([e.manufacturer, e.model].filter(Boolean).join(" "))}${e.third_party ? `${e.manufacturer || e.model ? " · " : ""}${esc(e.ownership_title)}` : ""}</small></span></div></td>
      <td>${e.category ? `<span class="eqs-cat">${esc(e.category)}</span>` : '<span class="muted">—</span>'}</td><td>${esc(e.location_name || e.location || "—")}</td><td>${condPill(e)}</td>
      ${mon ? `<td class="num"><b>${e.price ? eqMoney(e.price) : "—"}</b></td><td class="num">${e.amort && e.amort.on ? eqMoney(e.amort.residual) : e.accounting === "qty" || e.third_party ? '<span class="muted">не амортизируется</span>' : '<span class="muted" title="Не указан срок полезного использования">—</span>'}</td>
        <td class="num">${e.amort && e.amort.on && !e.amort.done ? eqMoney(e.amort.monthly) : "—"}</td>` : ""}</tr>`).join("")}</tbody>`;
}
