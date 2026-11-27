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
  bell: '<svg viewBox="0 0 24 24"><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/></svg>',
};

/** The bar of the section «Оборудование»: big tabs with icons, the rest under «Ещё» (stockHead draws it). */
function eqNavHtml(a) {
  const cur = S.stockTab, inMore = (a.more || []).some(t => t[0] === cur);
  const more = (a.more || []).find(t => t[0] === cur);
  return a.tabs.map(([k, t, tip]) => `<button data-k="${k}" ${tip ? `title="${esc(tip)}"` : ""}>${EQN[k] || ""}<span>${t}</span></button>`).join("")
    + `<span class="eqnav-more"><button class="eqnav-mb ${inMore ? "on" : ""}" id="eqMoreBtn" type="button"><span>${inMore ? esc(more[1]) : "Ещё"}</span>${EQN.more}</button>
      <span class="eqnav-menu" id="eqMoreMenu" hidden>${a.more.map(([k, t]) => `<button data-k="${k}" class="${k === cur ? "on" : ""}">${t}</button>`).join("")}</span></span>
    <span class="eqnav-bell" id="eqBellW" hidden><button class="eqnav-mb" id="eqBell" type="button" title="Сроки ТО, поверок и осмотров">${EQN.bell}<i id="eqBellN" hidden></i></button>
      <span class="eqnav-menu eqbell-menu" id="eqBellMenu" hidden></span></span>`;
}
function eqNavWire() {
  const b = $("#eqMoreBtn"), m = $("#eqMoreMenu"); if (!b || !m) return;
  b.onclick = ev => { ev.stopPropagation(); m.hidden = !m.hidden; if (!m.hidden) setTimeout(() => document.addEventListener("click", () => { m.hidden = true; }, {once: true})); };
  const bb = $("#eqBell"), bm = $("#eqBellMenu");
  if (bb) bb.onclick = ev => { ev.stopPropagation(); bm.hidden = !bm.hidden; if (!bm.hidden) setTimeout(() => document.addEventListener("click", e => { if (!bm.contains(e.target)) bm.hidden = true; }, {once: true})); };
  eqBellDraw();
}
/** 3.16 «Контроль сроков ТО и уведомления»: the bell of the section — what is overdue and what comes within the set days. */
async function eqBellDraw() {
  const w = $("#eqBellW"); if (!w) return;
  if (!canAny("equipment", "stock_view", "equipment_approve", "stock_ops")) { w.hidden = true; return; }
  let d; try { d = await api.equipment_due(); } catch (e) { w.hidden = true; return; }
  w.hidden = !d.on;
  const n = d.items.length, cnt = $("#eqBellN"), menu = $("#eqBellMenu");
  cnt.hidden = !n; cnt.textContent = n > 99 ? "99+" : n; cnt.className = d.overdue ? "bad" : "";
  menu.innerHTML = `<div class="eqbell-h"><b>Сроки ТО</b><small>${d.overdue ? `просрочено: ${d.overdue}` : "просроченного нет"} · на ${d.days} ${plural(d.days, "день", "дня", "дней")} вперёд: ${d.soon}</small></div>
    ${n ? d.items.slice(0, 12).map(x => `<button data-e="${esc(x.equipment_id)}" class="${x.overdue ? "late" : ""}"><span><b>${esc(x.name)}${x.inv_number ? " · " + esc(x.inv_number) : ""}</b><small>${esc(x.title)}</small></span><em>${x.overdue ? "просрочено · " : ""}${eqShortDate(x.date)}</em></button>`).join("")
      : `<div class="muted eqbell-e">Ничего не горит</div>`}${n > 12 ? `<div class="muted eqbell-e">И ещё ${n - 12}</div>` : ""}
    <button class="eqbell-all" data-all="1">Обслуживание и ремонт ${EQX.chev}</button>`;
  $$("[data-e]", menu).forEach(b => b.onclick = () => { menu.hidden = true; openEquipment(b.dataset.e, "service"); });
  $("[data-all]", menu).onclick = () => { menu.hidden = true; stockGo("equipment", "service"); };
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
// 3.16 «Округление сумм» of the module's settings: whole roubles (as before) or with the kopecks
const eqMoney = v => ((typeof STK !== "undefined" && STK.eq_module) || {}).round === "kop"
  ? (Math.round((+v || 0) * 100) / 100).toLocaleString("ru-RU", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " ₽" : money(Math.round(+v || 0));
const eqShortMoney = v => { v = +v || 0; return v >= 1e6 ? `${(v / 1e6).toLocaleString("ru-RU", {maximumFractionDigits: 2})} млн ₽` : v >= 1e4 ? `${Math.round(v / 1e3).toLocaleString("ru-RU")} тыс. ₽` : eqMoney(v); };
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

/* ------------------------------------------------------------ the year of a journal, steps */
const eqYearSel = (id, y) => { const now = new Date().getFullYear(); return `<label class="eqs-period">${EQX.cal}<span>Период:</span><select class="input" id="${id}">${[now + 1, now, now - 1, now - 2, now - 3].map(v => `<option value="${v}" ${v === y ? "selected" : ""}>${v} год</option>`).join("")}</select></label>`; };
const eqStages = (title, items, cur) => `<section class="eqs-card eqs-stages"><h3>${title}</h3><ol>${items.map(([t, s], i) => `<li class="${i + 1 < cur ? "done" : i + 1 === cur ? "cur" : ""}"><i>${i + 1 < cur ? EQX.ok : ""}</i><span><b>${i + 1}. ${t}</b><small>${s}</small></span></li>`).join("")}</ol></section>`;
const eqUseful = links => `<section class="eqs-card eqs-useful"><h3>Полезные действия</h3>${links.map(([k, ic, t, s]) => `<button data-u="${k}">${ic}<span><b>${t}</b>${s ? `<small>${s}</small>` : ""}</span>${EQX.chev}</button>`).join("")}</section>`;
const eqPill = (cls, t) => `<span class="eqs-st ${cls}">${cls === "ok" ? EQX.ok : cls === "late" || cls === "bad" ? EQX.warn : EQX.clock}${esc(t)}</span>`;

/* ------------------------------------------------------------ «Поступление» */
const RC_STEPS = [["Регистрация документов", "Договор, накладная, счёт-фактура"], ["Приёмка оборудования", "Проверка комплектации и состояния"],
  ["Постановка на учёт", "Инвентарный номер, категория, стоимость"], ["Ввод в эксплуатацию", "Дата ввода, кабинет, ответственный"]];
async function eqReceiptsTab() {
  const body = $("#stockBody");
  EQS.rcYear = EQS.rcYear || new Date().getFullYear();
  const [r, sups, places, refs] = await Promise.all([api.equipment_receipts(EQS.rcYear), api.suppliers(), api.stock_locations(), EQS.refs ? EQS.refs : api.equipment_refs()]);
  EQS.refs = refs;
  const mon = r.total !== undefined, edit = can("equipment");
  let rc = EQS.rc;  // the receipt in the wizard: {id?, step, ...}
  if (rc && rc.id) { const fresh = r.receipts.find(x => x.id === rc.id); rc = EQS.rc = fresh && fresh.status === "process" ? {...fresh, step: Math.min(rc.step || fresh.step, 4), _step: rc._step || fresh.step} : null; }
  if (!rc) rc = EQS.rc = {step: 1, _step: 1, lines: [], doc_kind: "contract", doc_date: iso(new Date())};
  const st = rc._step || 1, live = places.filter(p => p.id);
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Поступление оборудования</h2><span class="muted">Регистрация приобретения, приёмки и ввода в эксплуатацию</span></div><span class="grow"></span>
      ${eqYearSel("rcYear", EQS.rcYear)}${edit ? `<button class="btn" id="rcNew">${EQX.plus}Новое поступление</button>` : ""}</div>
    <div class="eqs-tiles">${eqTile(EQX.box, "Поступлений за период", r.count)}${mon ? eqTile(EQX.coins, "Общая стоимость", eqMoney(r.total)) : ""}${eqTile(EQX.ok, "Принято в эксплуатацию", r.accepted)}${eqTile(EQX.clock, "В процессе приёмки", r.process, r.process ? "warn" : "")}</div>
    ${edit ? `<div class="eqs-g2r"><section class="eqs-card" id="rcWiz"><h3>Регистрация поступления${rc.number ? ` <span class="eqs-chip">${esc(rc.number)}</span>` : ""}</h3>
        <div class="eqs-steps">${Object.values(r.steps).map((t, i) => `<button data-st="${i + 1}" class="${i + 1 === st ? "on" : i + 1 < st ? "done" : ""}" ${i + 1 > (rc.step || 1) ? "disabled" : ""}><i>${i + 1 < st ? EQX.ok : i + 1}</i>${t}</button>`).join("<u></u>")}</div>
        <div id="rcStep"></div><div class="auth-err" id="rcErr"></div></section>
      ${eqStages("Этапы поступления", RC_STEPS, st)}</div>` : ""}
    <div class="eqs-g2r"><section class="eqs-card eqs-tcard"><h3 class="eqs-tch">${EQN.eq_receipts}Журнал поступлений</h3>
        ${r.receipts.length ? `<table class="tbl eqs-reg" id="rcJ"><thead><tr><th>№ поступления</th><th>Дата</th><th>Поставщик</th><th>Документ</th><th class="num">Позиций</th>${mon ? '<th class="num">Сумма</th>' : ""}<th>Статус</th></tr></thead><tbody>${r.receipts.map(x => `<tr data-rc="${esc(x.id)}">
          <td><b>${esc(x.number)}</b></td><td>${fmtDateShort(x.doc_date)}</td><td>${esc(x.supplier_name || "—")}</td><td class="muted">${esc(x.doc_kind_title)} № ${esc(x.doc_number)}</td><td class="num">${x.positions}</td>
          ${mon ? `<td class="num"><b>${eqMoney(x.amount || x.lines_total)}</b></td>` : ""}<td>${x.status === "accepted" ? eqPill("ok", "Принято") : eqPill("wait", `${x.status_title} · шаг ${x.step}`)}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty"><b>Поступлений ещё не было</b><span>Начните с документов поставщика — «Новое поступление»</span></div>`}</section>
      ${eqUseful([["sup", EQX.box, "Справочник поставщиков", ""], ["print", EQX.doc, "Отчёт по поступлениям", "Журнал за год — на печать"], ["reg", EQX.list, "Реестр оборудования", ""]])}</div></div>`;
  const ys = $("#rcYear"); ys.onchange = () => { EQS.rcYear = +ys.value; eqReceiptsTab(); };
  const nw = $("#rcNew"); if (nw) nw.onclick = () => { EQS.rc = null; eqReceiptsTab(); };
  $$("[data-rc]", body).forEach(tr => tr.onclick = () => { const x = r.receipts.find(y => y.id === tr.dataset.rc);
    if (x.status === "process" && edit) { EQS.rc = {...x, _step: x.step}; eqReceiptsTab().then(() => $("#rcWiz").scrollIntoView({block: "start", behavior: "smooth"})); }
    else eqReceiptView(x); });
  $$("[data-u]", body).forEach(b => b.onclick = () => ({sup: () => stockGo("stock", "suppliers"), reg: () => stockGo("equipment", "equipment"),
    print: () => { const t = $("#rcJ"); if (!t) return toast("Журнал пуст"); $("#printArea").innerHTML = `<h2>Журнал поступлений оборудования, ${EQS.rcYear} год</h2>${t.outerHTML}`; window.print(); }})[b.dataset.u]());
  if (edit) { $$("[data-st]", body).forEach(b => b.onclick = () => { EQS.rc._step = +b.dataset.st; eqReceiptStep(sups, live, mon); }); eqReceiptStep(sups, live, mon); }
}
function eqReceiptStep(sups, places, mon) {
  const rc = EQS.rc, st = rc._step || 1, el = $("#rcStep"), err = m => { $("#rcErr").textContent = m || ""; };
  $$("#rcWiz [data-st]").forEach(b => { const n = +b.dataset.st; b.className = n === st ? "on" : n < st ? "done" : ""; b.disabled = n > (rc.step || 1); });
  const lines = rc.lines || [], cats = (EQS.refs.categories || []).map(c => c.name), lifeOf = c => ((EQS.refs.categories || []).find(x => x.name === c) || {}).life || "";
  const save = async (next, extra = {}) => {
    err("");
    try { const r = await api.equipment_receipt_save({id: rc.id, step: next, ...extra}); EQS.rc = {...r, _step: next}; return true; } catch (e) { err(errText(e)); return false; }
  };
  const nav = (back, nextT, onNext) => `<div class="eqs-wfoot">${back ? `<button class="btn ghost" id="rcBack">Назад</button>` : `<button class="btn ghost" id="rcCancel">${rc.id ? "Отменить поступление" : "Очистить"}</button>`}<span class="grow"></span><button class="btn" id="rcNext">${nextT} →</button></div>`;
  if (st === 1) {
    el.innerHTML = `<div class="eqs-form2"><label class="fl">Поставщик *<select class="input" id="rcSup"><option value="">Выберите поставщика</option>${sups.map(s => `<option value="${esc(s.id)}" ${s.id === rc.supplier_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
      <label class="fl">Дата документа *<input class="input" type="date" id="rcDate" value="${esc(rc.doc_date || iso(new Date()))}"></label>
      <label class="fl">Документ-основание *<select class="input" id="rcKind">${Object.entries(EQS.refs.receipt_docs).map(([k, t]) => `<option value="${k}" ${k === (rc.doc_kind || "contract") ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      ${mon ? `<label class="fl">Сумма по документу *<input class="input num" type="number" min="0" step="any" id="rcSum" value="${rc.amount || ""}" placeholder="0,00 ₽"></label>` : `<span></span>`}
      <label class="fl">Номер документа *<input class="input" id="rcNum" value="${esc(rc.doc_number || "")}" placeholder="№ ДП-056/26"></label>
      <label class="fl">Примечание<input class="input" id="rcCom" value="${esc(rc.comment || "")}" placeholder="Например: поставка по плану развития"></label></div>${nav(false, "Далее: Оборудование")}`;
    $("#rcNext").onclick = async () => { const f = {supplier_id: $("#rcSup").value, doc_date: $("#rcDate").value, doc_kind: $("#rcKind").value, doc_number: $("#rcNum").value, comment: $("#rcCom").value};
      if (mon) f.amount = $("#rcSum").value; if (await save(2, f)) eqReceiptsTab(); };
  } else if (st === 2) {
    const row = (l, i) => `<tr data-i="${i}"><td><input class="input" data-k="name" value="${esc(l.name || "")}" placeholder="Наименование"></td><td><input class="input" data-k="category" value="${esc(l.category || "")}" list="rcCats"></td>
      <td><input class="input" data-k="manufacturer" value="${esc(l.manufacturer || "")}"></td><td><input class="input" data-k="model" value="${esc(l.model || "")}"></td><td><input class="input" data-k="serial" value="${esc(l.serial || "")}"></td>
      <td><input class="input num" type="number" min="1" step="1" data-k="qty" value="${l.qty || 1}"></td>${mon ? `<td><input class="input num" type="number" min="0" step="any" data-k="price" value="${l.price || ""}"></td>` : ""}<td><button class="linkbtn danger-t" data-del="${i}">${EQX.x}</button></td></tr>`;
    el.innerHTML = `<div class="eqs-lines"><table class="tbl compact"><thead><tr><th>Наименование *</th><th>Категория</th><th>Производитель</th><th>Модель</th><th>Серийный №</th><th class="num">Кол-во</th>${mon ? '<th class="num">Цена за ед., ₽</th>' : ""}<th></th></tr></thead><tbody id="rcLines">${(lines.length ? lines : [{}]).map(row).join("")}</tbody></table>
      <datalist id="rcCats">${cats.map(c => `<option value="${esc(c)}">`).join("")}</datalist><button class="btn ghost small" id="rcAdd">+ Строка</button>
      <div class="muted eqs-hint">Проверьте комплектацию и состояние. Каждая единица получит свою карточку; при количественном учёте — одна карточка на всё количество.</div></div>${nav(true, "Далее: Учёт")}`;
    const read = () => $$("#rcLines tr").map(tr => ({...(lines[+tr.dataset.i] || {}), ...Object.fromEntries($$("[data-k]", tr).map(i => [i.dataset.k, i.value]))})).filter(l => (l.name || "").trim());
    $("#rcAdd").onclick = () => { EQS.rc.lines = [...read(), {}]; eqReceiptStep(sups, places, mon); };
    $$("[data-del]", el).forEach(b => b.onclick = () => { const all = read(); all.splice(+b.dataset.del, 1); EQS.rc.lines = all; eqReceiptStep(sups, places, mon); });
    $("#rcBack").onclick = () => { EQS.rc.lines = read(); EQS.rc._step = 1; eqReceiptStep(sups, places, mon); };
    $("#rcNext").onclick = async () => { const l = read(); if (!l.length) return err("Добавьте хотя бы одну позицию"); if (await save(3, {lines: l})) eqReceiptsTab(); };
  } else if (st === 3) {
    el.innerHTML = `<div class="eqs-lines"><table class="tbl compact"><thead><tr><th>Позиция</th><th>Инв. номер</th>${mon ? "<th>Способ учёта</th><th class=\"num\">Срок, мес.</th>" : ""}<th>Ответственный</th></tr></thead><tbody id="rcLines">${lines.map((l, i) => `<tr data-i="${i}">
      <td><b>${esc(l.name)}</b><small class="muted" style="display:block">${esc([l.category, l.qty > 1 ? `${l.qty} шт.` : ""].filter(Boolean).join(" · "))}</small></td>
      <td><input class="input" data-k="inv_number" value="${esc(l.inv_number || "")}" placeholder="присвоится сам"></td>
      ${mon ? `<td><select class="input" data-k="accounting">${Object.entries(EQS.refs.accounting).map(([k, t]) => `<option value="${k}" ${k === (l.accounting || "amort") ? "selected" : ""}>${t}</option>`).join("")}</select></td>
        <td><input class="input num" type="number" min="0" max="600" step="1" data-k="useful_months" value="${l.useful_months || ""}" placeholder="${lifeOf(l.category) ? "норматив " + lifeOf(l.category) : "—"}"></td>` : ""}
      <td><input class="input" data-k="responsible" value="${esc(l.responsible || "")}"></td></tr>`).join("")}</tbody></table>
      <div class="muted eqs-hint">Номер продолжит префикс последнего инвентарного номера. Срок полезного использования ставится вручную; пустой — без амортизации.</div></div>${nav(true, "Далее: Ввод в эксплуатацию")}`;
    const read = () => $$("#rcLines tr").map(tr => ({...lines[+tr.dataset.i], ...Object.fromEntries($$("[data-k]", tr).map(i => [i.dataset.k, i.value]))}));
    $("#rcBack").onclick = () => { EQS.rc.lines = read(); EQS.rc._step = 2; eqReceiptStep(sups, places, mon); };
    $("#rcNext").onclick = async () => { if (await save(4, {lines: read()})) eqReceiptsTab(); };
  } else {
    el.innerHTML = `<div class="eqs-lines"><table class="tbl compact"><thead><tr><th>Позиция</th><th>Кабинет / место</th><th>Дата ввода</th></tr></thead><tbody id="rcLines">${lines.map((l, i) => `<tr data-i="${i}">
      <td><b>${esc(l.name)}</b><small class="muted" style="display:block">${esc([l.inv_number, l.qty > 1 ? `${l.qty} шт.` : ""].filter(Boolean).join(" · "))}</small></td>
      <td><select class="input" data-k="location_id"><option value="">— не указано —</option>${places.map(p => `<option value="${esc(p.id)}" ${p.id === l.location_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></td>
      <td><input class="input" type="date" data-k="in_service" value="${esc(l.in_service || rc.doc_date || "")}"></td></tr>`).join("")}</tbody></table>
      ${mon ? `<label class="fl eqs-pay" title="Расход запишется датой документа в статью «Покупка оборудования»: в движении денег он есть, а в прибыль оборудование идёт амортизацией">Записать оплату<select class="input" id="rcPay"><option value="">— не записывать —</option>${["Наличные", "Безналичный перевод", "Карта"].map(k => `<option value="${k}">${k}</option>`).join("")}</select></label>` : ""}</div>
      <div class="eqs-wfoot"><button class="btn ghost" id="rcBack">Назад</button><span class="grow"></span><button class="btn" id="rcNext">${EQX.ok}Ввести в эксплуатацию</button></div>`;
    const read = () => $$("#rcLines tr").map(tr => ({...lines[+tr.dataset.i], ...Object.fromEntries($$("[data-k]", tr).map(i => [i.dataset.k, i.value]))}));
    $("#rcBack").onclick = () => { EQS.rc.lines = read(); EQS.rc._step = 3; eqReceiptStep(sups, places, mon); };
    $("#rcNext").onclick = async () => {
      if (!(await save(4, {lines: read()}))) return;
      try { const x = await api.equipment_receipt_accept(EQS.rc.id, $("#rcPay") ? $("#rcPay").value : ""); toast(`Принято: ${x.equipment_ids.length} ${plural(x.equipment_ids.length, "карточка", "карточки", "карточек")}`); EQS.rc = null; eqReceiptsTab(); }
      catch (e) { err(errText(e)); }
    };
  }
  const c = $("#rcCancel"); if (c) c.onclick = async () => {
    if (!rc.id) { EQS.rc = null; return eqReceiptsTab(); }
    if (!await ask(`Отменить поступление ${rc.number}?`, {danger: true, ok: "Отменить", cancel: "Не отменять"})) return;
    try { await api.equipment_receipt_cancel(rc.id); EQS.rc = null; toast("Отменено"); eqReceiptsTab(); } catch (e) { err(errText(e)); }
  };
}
function eqReceiptView(x) {
  const mon = x.amount !== undefined;
  const box = modal(`<div class="m-h"><h3>Поступление ${esc(x.number)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted">${esc(x.doc_kind_title)} № ${esc(x.doc_number)} от ${fmtDate(x.doc_date)} · ${esc(x.supplier_name || "поставщик не указан")}${mon ? ` · ${eqMoney(x.amount || x.lines_total)}` : ""}</div>
      <table class="tbl compact"><thead><tr><th>Позиция</th><th class="num">Кол-во</th>${mon ? '<th class="num">Цена</th>' : ""}<th>Инв. №</th></tr></thead><tbody>${x.lines.map(l => `<tr><td>${esc(l.name)}<small class="muted" style="display:block">${esc([l.category, l.model].filter(Boolean).join(" · "))}</small></td><td class="num">${l.qty}</td>${mon ? `<td class="num">${eqMoney(l.price)}</td>` : ""}<td>${esc(l.inv_number || "—")}</td></tr>`).join("")}</tbody></table>
      ${x.equipment_ids.length ? `<div class="muted eqs-hint">Карточки: ${x.equipment_ids.length}. Откройте их в «Реестре оборудования».</div>` : ""}</div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Закрыть</button>${x.equipment_ids.length ? `<button class="btn" id="rvOpen">Открыть первую карточку</button>` : ""}</div>`);
  const o = $("#rvOpen", box); if (o) o.onclick = () => { closeModal(); openEquipment(x.equipment_ids[0]); };
}

/* ------------------------------------------------------------ «Перемещения» */
const MV_STAGES = [["Создание заявки", "Формирование перемещения"], ["Подготовка к перемещению", "Утверждение, проверка состояния, отключение"],
  ["Физическое перемещение", "Транспортировка и установка"], ["Подтверждение", "Фиксация нового местонахождения в учёте"]];
async function eqMovesTab() {
  const body = $("#stockBody");
  EQS.mvYear = EQS.mvYear || new Date().getFullYear();
  const [r, list, places] = await Promise.all([api.equipment_moves(EQS.mvYear, EQS.mvEq || null), api.equipment_list("", false), api.stock_locations()]);
  const edit = can("equipment"), appr = can("equipment_approve"), live = places.filter(p => p.id);
  const sel = EQS.mvSel ? r.moves.find(m => m.id === EQS.mvSel) : null;
  const flt = EQS.mvFlt === "planned" ? r.moves.filter(m => m.planned) : r.moves;
  const pill = m => m.status === "done" ? eqPill("ok", m.status_title) : m.status === "rejected" ? eqPill("bad", m.status_title) : m.planned ? eqPill("plan", m.status_title) : eqPill("wait", m.status_title);
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Перемещения оборудования</h2><span class="muted">Передача оборудования между кабинетами, подразделениями и местами хранения</span></div><span class="grow"></span>
      ${eqYearSel("mvYear", EQS.mvYear)}${edit ? `<button class="btn" id="mvNew">${EQX.plus}Новое перемещение</button>` : ""}</div>
    <div class="eqs-tiles">${eqTile(EQN.eq_moves, "Перемещений за период", r.count)}${eqTile(EQX.ok, "Завершено", r.done)}${eqTile(EQX.clock, "В процессе", r.process, r.process ? "warn" : "")}${eqTile(EQX.cal, "Запланировано", r.planned)}</div>
    <div class="eqs-g2r">${edit ? `<section class="eqs-card" id="mvForm"><h3>${EQN.eq_moves}Создать перемещение</h3>
        <div class="eqs-form2"><label class="fl">Оборудование *<select class="input" id="mvEqS"><option value="">Выберите оборудование</option>${list.map(e => `<option value="${esc(e.id)}" data-from="${esc(e.location_name || e.location || "")}" data-lid="${esc(e.location_id || "")}">${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}</option>`).join("")}</select></label>
          <label class="fl">Куда (новое местонахождение) *<select class="input" id="mvTo"><option value="">Выберите место</option>${live.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select></label>
          <label class="fl">Откуда (текущее местонахождение)<input class="input" id="mvFrom" disabled placeholder="—"></label>
          <label class="fl">Дата перемещения *<input class="input" type="date" id="mvDate" value="${iso(new Date())}"></label>
          <label class="fl">Основание *<input class="input" id="mvReason" list="mvReasons" placeholder="Перераспределение нагрузки"></label>
          <label class="fl">Ответственный *<input class="input" id="mvResp" value="${esc(ME ? ME.name || "" : "")}"></label>
          <label class="fl eqs-span2">Комментарий<input class="input" id="mvCom" maxlength="250" placeholder="Например: перенос из-за ремонта кабинета № 3"></label></div>
        <datalist id="mvReasons">${r.reasons.map(x => `<option value="${esc(x)}">`).join("")}</datalist>
        ${appr ? `<label class="dx-doc"><input type="checkbox" id="mvNow">Сразу провести — оборудование уже перенесли</label>` : `<div class="muted eqs-hint">Перемещение утверждает директор или учредитель (право «Оборудование: согласование»).</div>`}
        <div class="auth-err" id="mvErr"></div><div class="eqs-wfoot"><span class="grow"></span><button class="btn ghost" id="mvClear">Отмена</button><button class="btn" id="mvOk">Создать перемещение →</button></div></section>` : ""}
      ${eqStages(sel ? `Этапы ${esc(sel.number)}` : "Этапы перемещения", MV_STAGES, sel ? (sel.status === "done" ? 5 : sel.stage) : 1)}</div>
    <div class="eqs-g2r"><section class="eqs-card eqs-tcard"><h3 class="eqs-tch">${EQN.eq_moves}Журнал перемещений${EQS.mvEq || EQS.mvFlt ? ` <button class="linkbtn" id="mvAll">${EQX.x}все</button>` : ""}</h3>
        ${flt.length ? `<table class="tbl eqs-reg" id="mvJ"><thead><tr><th>№</th><th>Дата</th><th>Оборудование</th><th>Откуда</th><th>Куда</th><th>Основание</th><th>Статус</th><th></th></tr></thead><tbody>${flt.map(m => `<tr data-mv="${esc(m.id)}" class="${m.id === EQS.mvSel ? "sel" : ""}">
          <td><b>${esc(m.number)}</b></td><td>${fmtDateShort(m.date)}</td><td><div class="sn-mat sm">${phHtml(m.photo_id)}<span>${esc(m.equipment_name)}</span></div></td><td>${esc(m.from_name)}</td><td>${esc(m.to_name)}</td>
          <td class="muted">${esc(m.reason)}</td><td>${pill(m)}</td><td class="eqs-acts2">${[
            appr && m.status === "requested" && `<button class="linkbtn" data-a="approve">утвердить</button><button class="linkbtn danger-t" data-a="reject">отклонить</button>`,
            edit && m.status === "approved" && !m.planned && `<button class="linkbtn" data-a="moving">начать</button>`,
            edit && ["approved", "moving"].includes(m.status) && `<button class="linkbtn" data-a="done">подтвердить</button>`,
            (edit || appr) && ["requested", "approved"].includes(m.status) && `<button class="linkbtn danger-t" data-a="cancel">отменить</button>`,
            `<button class="linkbtn" data-a="print">акт</button>`].filter(Boolean).join("")}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty"><b>Перемещений нет</b><span>${edit ? "Выберите оборудование и место выше" : ""}</span></div>`}</section>
      ${eqUseful([["hist", EQN.eq_moves, "История по оборудованию", "Все перемещения выбранной единицы"], ["plan", EQX.cal, "Планируемые перемещения", "Запланированные на будущее"],
        ["print", EQX.doc, "Печать акта перемещения", "Форма внутреннего документа"], ["reasons", EQX.list, "Шаблоны оснований", "Справочник причин перемещений"]])}</div></div>`;
  loadThumbs(body);
  $("#mvYear").onchange = e => { EQS.mvYear = +e.target.value; eqMovesTab(); };
  const all = $("#mvAll"); if (all) all.onclick = () => { EQS.mvEq = null; EQS.mvFlt = null; eqMovesTab(); };
  const nw = $("#mvNew"); if (nw) nw.onclick = () => { $("#mvForm").scrollIntoView({block: "start", behavior: "smooth"}); $("#mvEqS").focus(); };
  const es = $("#mvEqS"); if (es) {
    es.onchange = () => { const o = es.selectedOptions[0]; $("#mvFrom").value = o ? o.dataset.from || "" : ""; $$("#mvTo option").forEach(x => { x.disabled = !!x.value && o && x.value === o.dataset.lid; }); };
    $("#mvClear").onclick = () => { EQS.mvSel = null; eqMovesTab(); };
    $("#mvOk").onclick = async () => {
      try { const id = await api.equipment_move_save({equipment_id: es.value, to_location_id: $("#mvTo").value, date: $("#mvDate").value, reason: $("#mvReason").value,
        responsible: $("#mvResp").value, comment: $("#mvCom").value, now: $("#mvNow") ? $("#mvNow").checked : false});
        EQS.mvSel = id; toast(appr ? "Перемещение утверждено" : "Перемещение отправлено на утверждение"); eqMovesTab(); } catch (e) { $("#mvErr").textContent = errText(e); }
    };
    if (EQS.mvPreset) { es.value = EQS.mvPreset; es.onchange(); EQS.mvPreset = null; $("#mvForm").scrollIntoView({block: "start"}); }
  }
  $$("tr[data-mv]", body).forEach(tr => tr.onclick = async ev => {
    const m = r.moves.find(x => x.id === tr.dataset.mv), a = ev.target.dataset && ev.target.dataset.a;
    if (!a) { EQS.mvSel = m.id; return eqMovesTab(); }
    try {
      if (a === "print") return eqMovePrint(m);
      if (a === "approve") await api.equipment_move_decide(m.id, "approve");
      if (a === "reject") { const why = await promptText("Почему отклонено?"); if (!why) return; await api.equipment_move_decide(m.id, "reject", why); }
      if (a === "moving" || a === "done") await api.equipment_move_step(m.id, a);
      if (a === "cancel") { if (!await ask(`Отменить ${m.number}?`, {danger: true, ok: "Отменить", cancel: "Не отменять"})) return; await api.equipment_move_cancel(m.id); }
      EQS.mvSel = m.id; toast(a === "done" ? "Место в карточке обновлено" : "Сохранено"); eqMovesTab();
    } catch (e) { toast(errText(e), true); }
  });
  $$("[data-u]", body).forEach(b => b.onclick = () => ({
    hist: () => { const id = (sel && sel.equipment_id) || (es && es.value); if (!id) return toast("Выберите оборудование в форме или строку журнала"); EQS.mvEq = id; eqMovesTab(); },
    plan: () => { EQS.mvFlt = "planned"; eqMovesTab(); },
    print: () => sel ? eqMovePrint(sel) : toast("Выберите перемещение в журнале"),
    reasons: () => modal(`<div class="m-h"><h3>Шаблоны оснований</h3><button class="x" data-close>×</button></div><div class="m-b"><ul class="eqs-ul">${r.reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul><div class="muted">В поле «Основание» можно выбрать шаблон или написать своё.</div></div><div class="m-f"><span class="grow"></span><button class="btn" data-close>Закрыть</button></div>`)})[b.dataset.u]());
}
async function promptText(title) {
  return new Promise(ok => { const box = modal(`<div class="m-h"><h3>${esc(title)}</h3><button class="x" data-close>×</button></div><div class="m-b"><input class="input" id="ptT" autofocus></div><div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="ptOk">OK</button></div>`);
    $("#ptOk", box).onclick = () => { const v = $("#ptT", box).value.trim(); closeModal(); ok(v); }; });
}
async function eqMovePrint(m) {
  const head = await clinicHead();
  $("#printArea").innerHTML = `${head}<h2 style="text-align:center">Акт перемещения оборудования № ${esc(m.number)}</h2><p style="text-align:center">от ${fmtDate(m.date)}</p>
    <table><tr><th>Оборудование</th><th>Инв. №</th><th>Откуда</th><th>Куда</th><th>Основание</th></tr><tr><td>${esc(m.equipment_name)}</td><td>${esc(m.inv_number)}</td><td>${esc(m.from_name)}</td><td>${esc(m.to_name)}</td><td>${esc(m.reason)}</td></tr></table>
    ${m.comment ? `<p>Комментарий: ${esc(m.comment)}</p>` : ""}<p>Статус: ${esc(m.status_title)}${m.approved_name ? `, утвердил: ${esc(m.approved_name)}` : ""}</p>
    ${signLines([{role: "Передал", name: m.responsible || ""}, {role: "Принял", name: ""}, {role: "Утвердил", name: m.approved_name || ""}])}`;
  window.print();
}

/* ------------------------------------------------------------ «Обслуживание и ремонт» */
async function eqRequestsTab() {
  const body = $("#stockBody");
  EQS.rqYear = EQS.rqYear || new Date().getFullYear();
  const [r, list, refs] = await Promise.all([api.equipment_requests(EQS.rqYear), api.equipment_list("", false), EQS.refs ? Promise.resolve(EQS.refs) : api.equipment_refs()]);
  EQS.refs = refs;
  const edit = can("equipment"), kind = EQS.rqKind || "", q = (EQS.rqQ || "").toLowerCase();
  const rows = r.requests.filter(x => (!kind || x.kind === kind) && (!q || `${x.number} ${x.equipment_name} ${x.description}`.toLowerCase().includes(q)));
  const cnt = k => r.requests.filter(x => x.kind === k).length;
  const pill = x => x.status === "done" ? eqPill("ok", x.status_title) : x.overdue ? eqPill("late", x.status_title) : x.status === "work" ? eqPill("wait", x.status_title) : eqPill("plan", x.status_title);
  const kcls = k => k === "repair" ? "bad" : k === "service" ? "ok" : "plan";
  const pr = EQS.rqPr || "mid";
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Обслуживание и ремонт</h2><span class="muted">Плановые ТО, заявки на ремонт, учёт неисправностей и расходов</span></div><span class="grow"></span>
      ${eqYearSel("rqYear", EQS.rqYear)}<button class="btn" id="rqNew">${EQX.plus}${edit ? "Создать заявку" : "Сообщить о неисправности"}</button></div>
    <div class="eqs-tiles">${eqTile(EQX.wrench, "Всего заявок", r.total)}${eqTile(EQX.ok, "Выполнено", r.done, "ok")}${eqTile(EQX.gear, "В работе", r.work, r.work ? "warn" : "")}${eqTile(EQX.warn, "Просрочено", r.overdue, r.overdue ? "bad" : "")}${eqTile(EQX.cal, "Ближайшее ТО", r.next_service ? eqShortDate(r.next_service) : "—")}</div>
    <div class="eqs-g2r eqs-g2r-wide"><section class="eqs-card" id="rqForm"><h3>${EQN.eq_receipts}${edit ? "Новая заявка" : "Сообщить о неисправности"}</h3>
        <div class="eqs-form2"><label class="fl">Оборудование *<select class="input" id="rqEq"><option value="">Выберите оборудование</option>${list.map(e => `<option value="${esc(e.id)}">${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}${e.location_name ? " · " + esc(e.location_name) : ""}</option>`).join("")}</select></label>
          <div class="fl"><span>Приоритет</span><div class="eqs-prio" id="rqPr">${Object.entries(r.priorities).map(([k, t]) => `<button type="button" data-p="${k}" class="${k} ${k === pr ? "on" : ""}">${t}</button>`).join("")}</div></div>
          ${edit ? `<label class="fl">Тип заявки *<select class="input" id="rqKind">${Object.entries(r.kinds).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>` : `<span></span>`}
          <label class="fl">Желаемая дата выполнения<input class="input" type="date" id="rqDue"></label>
          ${edit && (refs.works || []).length ? `<label class="fl eqs-span2">Вид работ<select class="input" id="rqWork"><option value="">— выберите из справочника или опишите ниже —</option>${refs.works.map(w => `<option value="${esc(w.name)}" data-kind="${w.kind}">${esc(w.name)} · ${esc(refs.req_kinds[w.kind] || "")}</option>`).join("")}</select></label>` : ""}
          <label class="fl">Описание проблемы *<textarea class="input" id="rqText" rows="2" maxlength="500" placeholder="Повышенный шум при работе"></textarea></label>
          <label class="fl">Ответственный<input class="input" id="rqResp" value="${edit ? esc(ME ? ME.name || "" : "") : ""}" placeholder="Менеджер"></label></div>
        <div class="auth-err" id="rqErr"></div><div class="eqs-wfoot"><span class="grow"></span><button class="btn ghost" id="rqClear">Отмена</button><button class="btn" id="rqOk">Создать заявку →</button></div></section>
      <section class="eqs-card"><h3>${EQX.cal}График технического обслуживания (ТО)</h3><span class="muted eqs-sub">Ближайшие плановые работы</span>
        ${r.schedule.length ? `<div class="eqs-ev">${r.schedule.slice(0, 5).map(x => `<button data-e="${esc(x.equipment_id)}" class="${x.overdue ? "late" : ""}">${EQX.cal}<span><b>${esc(x.name)}${x.inv_number ? " " + esc(x.inv_number) : ""}</b><small>${esc(x.kind_title)}${x.every ? ` · раз в ${x.every} мес.` : ""}</small></span><em>${x.overdue ? "просрочено · " : ""}${eqShortDate(x.date)}</em></button>`).join("")}</div>`
          : `<div class="muted">Плановых работ нет. Добавьте регламент ТО — «Весь график ТО».</div>`}
        <button class="linkbtn eqs-more-l" id="rqPlans">Весь график ТО ${EQX.chev}</button></section></div>
    <div class="eqs-g2r eqs-g2r-wide"><section class="eqs-card eqs-tcard">
        <div class="eqs-jt"><div class="eqs-seg">${[["", `Все заявки (${r.requests.length})`], ["service", `Плановое ТО (${cnt("service")})`], ["repair", `Ремонт (${cnt("repair")})`], ["diag", `Диагностика (${cnt("diag")})`]].map(([k, t]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${t}</button>`).join("")}</div>
          <span class="grow"></span><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="rqQ" placeholder="Поиск по заявкам…" value="${esc(EQS.rqQ || "")}"></div></div>
        ${rows.length ? `<table class="tbl eqs-reg" id="rqJ"><thead><tr><th>№</th><th>Дата</th><th>Оборудование</th><th>Тип</th><th>Описание</th><th>Статус</th><th class="num">Сумма</th><th></th></tr></thead><tbody>${rows.map(x => `<tr data-rq="${esc(x.id)}">
          <td><b>${esc(x.number)}</b></td><td>${fmtDateShort((x.done_at || x.created_at || "").slice(0, 10))}</td><td><div class="sn-mat sm">${phHtml(x.photo_id)}<span>${esc(x.equipment_name)}${x.inv_number ? `<small class="muted" style="display:block">${esc(x.inv_number)}</small>` : ""}</span></div></td>
          <td><span class="eqs-kind ${kcls(x.kind)}">${esc(x.kind_title)}</span></td><td class="muted">${esc(x.result || x.description)}${x.due && x.status !== "done" ? `<small style="display:block">до ${fmtDateShort(x.due)} · ${esc(x.priority_title.toLowerCase())}</small>` : ""}</td>
          <td>${pill(x)}</td><td class="num">${x.cost ? eqMoney(x.cost) : "—"}</td>
          <td class="eqs-acts2">${edit && x.status === "new" ? `<button class="linkbtn" data-a="work">в работу</button>` : ""}${edit && ["new", "work"].includes(x.status) ? `<button class="linkbtn" data-a="done">выполнено</button><button class="linkbtn danger-t" data-a="cancel">отменить</button>` : ""}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty"><b>Заявок нет</b><span>Создайте заявку на ремонт, ТО или диагностику</span></div>`}</section>
      <div class="eqs-side2"><section class="eqs-card eqs-costc"><h3>${EQX.coins}Расходы на обслуживание и ремонт</h3>
          <div class="eqs-cost"><b>${eqMoney(r.cost)}</b>${r.cost_change != null ? `<em class="${r.cost_change <= 0 ? "ok" : "bad"}">${r.cost_change > 0 ? "+" : ""}${r.cost_change.toLocaleString("ru-RU")} %<small>к ${r.year - 1} году</small></em>` : ""}</div><small class="muted">за ${r.year} год</small></section>
        ${eqUseful([["plans", EQX.cal, "Планировать ТО", ""], ["faults", EQX.wrench, "Журнал неисправностей", ""], ["report", EQX.doc, "Отчёт по расходам", ""], ["regs", EQX.gear, "Настройки регламентов ТО", ""]])}</div></div></div>`;
  loadThumbs(body);
  $("#rqYear").onchange = e => { EQS.rqYear = +e.target.value; eqRequestsTab(); };
  $("#rqNew").onclick = () => { $("#rqForm").scrollIntoView({block: "start", behavior: "smooth"}); $("#rqEq").focus(); };
  $$("#rqPr button", body).forEach(b => b.onclick = () => { EQS.rqPr = b.dataset.p; $$("#rqPr button", body).forEach(x => x.classList.toggle("on", x === b)); });
  $("#rqClear").onclick = () => { EQS.rqPr = null; eqRequestsTab(); };
  const rw = $("#rqWork");  // 3.16: a kind of work of the reference fills the type and the description
  if (rw) rw.onchange = () => { const o = rw.selectedOptions[0]; if (!rw.value) return; if ($("#rqKind") && o.dataset.kind) $("#rqKind").value = o.dataset.kind;
    const t = $("#rqText"); t.value = t.value.trim() ? `${rw.value}. ${t.value.trim()}` : rw.value; };
  $("#rqOk").onclick = async () => {
    try { await api.equipment_request_save({equipment_id: $("#rqEq").value, kind: $("#rqKind") ? $("#rqKind").value : "repair", description: $("#rqText").value,
      priority: EQS.rqPr || "mid", due: $("#rqDue").value, responsible: $("#rqResp").value});
      EQS.rqPr = null; toast(edit ? "Заявка создана" : "Сообщение о неисправности отправлено"); eqRequestsTab(); } catch (e) { $("#rqErr").textContent = errText(e); }
  };
  if (EQS.rqPreset) { $("#rqEq").value = EQS.rqPreset; EQS.rqPreset = null; $("#rqForm").scrollIntoView({block: "start"}); $("#rqText").focus(); }
  $$(".eqs-jt .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.rqKind = b.dataset.k; eqRequestsTab(); });
  let t; $("#rqQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { EQS.rqQ = e.target.value; eqRequestsTab().then(() => { const i = $("#rqQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 250); };
  $$("[data-e]", body).forEach(b => b.onclick = () => openEquipment(b.dataset.e));
  $$("tr[data-rq]", body).forEach(tr => tr.onclick = async ev => {
    const x = r.requests.find(y => y.id === tr.dataset.rq), a = ev.target.dataset && ev.target.dataset.a;
    if (!a) return openEquipment(x.equipment_id, "service");
    try {
      if (a === "done") return eqRequestDone(x);
      if (a === "cancel" && !await ask(`Отменить заявку ${x.number}?`, {danger: true, ok: "Отменить", cancel: "Не отменять"})) return;
      await api.equipment_request_status(x.id, a === "cancel" ? "cancelled" : a); toast("Сохранено"); eqRequestsTab();
    } catch (e) { toast(errText(e), true); }
  });
  $("#rqPlans").onclick = () => eqPlansDlg(list);
  $$("[data-u]", body).forEach(b => b.onclick = () => ({plans: () => eqPlansDlg(list), regs: () => eqPlansDlg(list), faults: () => { EQS.rqKind = "repair"; eqRequestsTab(); },
    report: () => eqServiceTab()})[b.dataset.u]());
}
function eqRequestDone(x) {
  const box = modal(`<div class="m-h"><h3>Выполнено: ${esc(x.number)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted">${esc(x.equipment_name)} · ${esc(x.kind_title)}: ${esc(x.description)}</div>
      <div class="grid3"><label class="fl">Дата<input class="input" type="date" id="rdD" value="${iso(new Date())}"></label><label class="fl">Сумма, ₽<input class="input num" type="number" min="0" step="any" id="rdC" placeholder="0"></label></div>
      <label class="fl">Что сделано<input class="input" id="rdR" value="${esc(x.description)}"></label>
      ${(x.checklist || []).length ? `<div class="eqs-check"><b>Чек-лист: ${esc(x.reg_name)}</b>${x.checklist.map((t, i) => `<label><input type="checkbox" data-ck="${i}" checked><span>${esc(t)}</span></label>`).join("")}</div>` : ""}<div class="auth-err" id="rdE"></div>
      <div class="muted eqs-hint">Запись попадёт в историю карточки с суммой. ${x.kind === "repair" ? "Оборудование вернётся в работу и станет «Исправно»." : x.plan_id ? "Следующая дата по графику ТО сдвинется на период." : ""}</div></div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rdOk">Выполнено</button></div>`);
  $("#rdOk", box).onclick = async () => { try { await api.equipment_request_status(x.id, "done", {date: $("#rdD").value, cost: $("#rdC").value, result: $("#rdR").value,
    checklist: (x.checklist || []).map((t, i) => ({t, ok: $(`[data-ck="${i}"]`, box).checked}))}); closeModal(); toast("Выполнено"); eqRequestsTab(); } catch (e) { $("#rdE").textContent = errText(e); } };
}
async function eqPlansDlg(list) {
  const plans = await api.equipment_plans(), refs = EQS.refs || (EQS.refs = await api.equipment_refs()), edit = can("equipment");
  const box = modal(`<div class="m-h"><h3>График ТО и регламенты</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted eqs-hint">Плановое ТО, поверка и технический осмотр с периодичностью. «Создать заявку» по строке графика — после её выполнения следующая дата сдвинется на период.</div>
      <table class="tbl compact"><thead><tr><th>Оборудование</th><th>Вид</th><th class="num">Раз в, мес.</th><th>Следующая дата</th><th>Регламент, примечание</th><th></th></tr></thead><tbody>${plans.map(p => `<tr data-p="${esc(p.id)}"><td>${esc(p.equipment_name)} <small class="muted">${esc(p.inv_number)}</small></td><td>${esc(p.kind_title)}</td><td class="num">${p.every_months}</td><td>${fmtDate(p.next_date)}</td><td class="muted">${p.reg_name ? `<b>${esc(p.reg_name)}</b> ` : ""}${esc(p.note || "")}</td>
        <td>${edit ? `<button class="linkbtn" data-req="${esc(p.id)}">заявка</button> <button class="linkbtn danger-t" data-del="${esc(p.id)}">убрать</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">Регламентов пока нет</td></tr>`}</tbody></table>
      ${edit ? `<h4 class="sub-h">Добавить в график</h4>${(refs.regs || []).length ? `<label class="fl">Регламент обслуживания<select class="input" id="plR"><option value="">— без регламента —</option>${refs.regs.map(g => `<option value="${esc(g.id)}">${esc(g.name)} · раз в ${g.every_months} мес.${g.checklist.length ? ` · чек-лист ${g.checklist.length}` : ""}</option>`).join("")}</select></label>` : ""}<div class="grid3"><label class="fl">Оборудование<select class="input" id="plE">${list.map(e => `<option value="${esc(e.id)}">${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}</option>`).join("")}</select></label>
        <label class="fl">Вид<select class="input" id="plK">${Object.entries(refs.plan_kinds).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>
        <label class="fl">Периодичность, мес.<input class="input num" type="number" min="1" max="120" id="plN" value="6"></label>
        <label class="fl">Следующая дата<input class="input" type="date" id="plD"></label><label class="fl" style="grid-column:span 2">Примечание<input class="input" id="plC" placeholder="например: по паспорту производителя"></label></div><div class="auth-err" id="plErr"></div>` : ""}</div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Закрыть</button>${edit ? `<button class="btn" id="plOk">Добавить</button>` : ""}</div>`, {wide: true});
  const ok = $("#plOk", box); if (ok) ok.onclick = async () => { try { await api.equipment_plan_save({equipment_id: $("#plE").value, kind: $("#plK").value, every_months: $("#plN").value, next_date: $("#plD").value, note: $("#plC").value, reg_id: $("#plR") ? $("#plR").value : ""}); closeModal(); toast("Добавлено в график"); eqRequestsTab().then(() => eqPlansDlg(list)); } catch (e) { $("#plErr").textContent = errText(e); } };
  $$("[data-del]", box).forEach(b => b.onclick = async () => { await api.equipment_plan_delete(b.dataset.del); closeModal(); eqRequestsTab().then(() => eqPlansDlg(list)); });
  const pr = $("#plR", box);  // 3.16: the regulation sets the kind and the period; its category picks the equipment
  if (pr) pr.onchange = () => { const g = refs.regs.find(x => x.id === pr.value); if (!g) return; $("#plK", box).value = g.kind; $("#plN", box).value = g.every_months;
    if (g.category) { const e = list.find(y => y.category === g.category); if (e && !list.find(y => y.id === $("#plE", box).value && y.category === g.category)) $("#plE", box).value = e.id; } };
  $$("[data-req]", box).forEach(b => b.onclick = async () => { const p = plans.find(x => x.id === b.dataset.req);
    try { await api.equipment_request_save({equipment_id: p.equipment_id, kind: p.kind === "service" ? "service" : "diag", description: `${p.kind_title} по графику`, due: p.next_date, plan_id: p.id, priority: "mid"});
      closeModal(); toast("Заявка создана"); eqRequestsTab(); } catch (e) { toast(errText(e), true); } });
}

/* ------------------------------------------------------------ «Амортизация» */
async function eqAmortYear() {
  const body = $("#stockBody");
  EQS.amYear = EQS.amYear || new Date().getFullYear();
  const r = await api.equipment_amort_year(EQS.amYear), grp = EQS.amGrp || "on";
  const mon = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
  const top = Math.max(1, ...r.charge), topR = Math.max(1, ...r.running), minR = Math.min(...r.running), lo = Math.max(0, minR - (topR - minR) * .4 - 1);
  const W = 560, H = 190, bw = W / 12;
  const bars = r.charge.map((v, i) => `<rect x="${i * bw + bw * .22}" y="${H - v / top * (H - 14)}" width="${bw * .56}" height="${v / top * (H - 14)}" rx="3" class="eqbar"><title>${mon[i]}: ${eqMoney(v)}</title></rect>`).join("");
  const yR = v => H - 8 - (v - lo) / Math.max(1, topR - lo) * (H - 24), pts = r.running.map((v, i) => `${i * bw + bw / 2},${yR(v)}`).join(" ");
  const list = r.rows.filter(x => x.group === grp), cnt = g => r.rows.filter(x => x.group === g).length;
  const yrs = n => n ? (n % 12 ? `${n} мес.` : `${n / 12} ${plural(n / 12, "год", "года", "лет")}`) : "—";
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Амортизация</h2><span class="muted">Расчёт, учёт и контроль амортизации имущества${r.year === new Date().getFullYear() ? " · на сегодня" : ` · на конец ${r.year} года`}</span></div><span class="grow"></span>
      ${eqYearSel("amYear", r.year)}<button class="btn ghost" id="amOld" title="Помесячный отчёт за период, амортизация в ОПиУ, перенос покупок оборудования">${EQX.doc}Отчёт и ОПиУ</button></div>
    <div class="eqs-tiles eqs-tiles5">${eqTile(EQX.box, "Общая стоимость", eqMoney(r.cost))}${eqTile(EQX.pie, "Остаточная стоимость", eqMoney(r.residual))}${eqTile(EQN.amort, "Накопленная амортизация", eqMoney(r.accumulated))}${eqTile(EQX.calc, "Амортизация в месяц", eqMoney(r.monthly))}${eqTile('<svg viewBox="0 0 24 24"><path d="M6 18 18 6"/><circle cx="7.5" cy="7.5" r="2.5"/><circle cx="16.5" cy="16.5" r="2.5"/></svg>', "Степень износа", `${r.wear.toLocaleString("ru-RU")} %`)}</div>
    ${r.in_pnl ? "" : `<div class="warn-line">Амортизация сейчас не входит в ОПиУ — включите её в «Отчёт и ОПиУ».</div>`}
    <div class="eqs-g3">
      <section class="eqs-card"><h3>Динамика амортизации</h3><svg class="eqs-chart" viewBox="0 -6 ${W} ${H + 26}">${bars}<polyline points="${pts}" class="eqline"/>${r.running.map((v, i) => `<circle cx="${i * bw + bw / 2}" cy="${yR(v)}" r="3.5" class="dot"><title>${mon[i]}: накоплено ${eqMoney(v)}</title></circle>`).join("")}
          ${mon.map((m, i) => `<text x="${i * bw + bw / 2}" y="${H + 17}" text-anchor="middle">${m}</text>`).join("")}</svg>
        <div class="mtc-legend eqs-leg2"><span class="eqbar">Амортизация в месяц</span><span class="eqline">Накопленная амортизация (итогом)</span></div></section>
      <section class="eqs-card"><h3>Структура стоимости</h3><div class="eqs-ringrow">${eqRing(r.by_category.slice(0, 6).map((g, i) => ({value: g.cost, cls: "c" + (i + 1)})), eqShortMoney(r.cost), "общая стоимость")}
        <ul class="eqs-legend">${r.by_category.slice(0, 6).map((g, i) => `<li class="c${i + 1}"><span>${esc(g.name)}</span><b>${g.share.toLocaleString("ru-RU")} %</b></li>`).join("") || '<li class="muted">Нет оборудования с амортизацией</li>'}</ul></div></section>
      <section class="eqs-card"><h3>Ключевые показатели</h3><dl class="eqs-kpi">
        <dt>${EQX.cal}Объектов с амортизацией</dt><dd>${r.count_on}</dd><dt>${EQX.ok}Полностью амортизировано</dt><dd>${r.count_done}</dd>
        <dt>${EQX.clock}В процессе амортизации</dt><dd>${r.count_running}</dd><dt>${EQX.cycle}Средний срок службы</dt><dd>${r.avg_life.toLocaleString("ru-RU")} ${plural(Math.round(r.avg_life), "год", "года", "лет")}</dd>
        <dt>%&nbsp;Средняя степень износа</dt><dd>${r.avg_wear.toLocaleString("ru-RU")} %</dd></dl></section></div>
    <div class="eqs-bar2"><div class="eqs-seg">${[["on", `Реестр с амортизацией (${cnt("on")})`], ["done", `Полностью амортизировано (${cnt("done")})`], ["off", `Без амортизации (${cnt("off")})`]].map(([k, t]) => `<button data-g="${k}" class="${k === grp ? "on" : ""}">${t}</button>`).join("")}</div>
      <span class="grow"></span><button class="btn ghost small" data-xls="#amReg" data-xls-name="Амортизация ${r.year}">${EQX.down}Excel</button></div>
    <section class="eqs-card eqs-tcard">${list.length ? `<table class="tbl eqs-reg" id="amReg"><thead><tr><th>Инв. номер</th><th>Наименование</th><th>Категория</th><th class="num">Первоначальная стоимость</th><th class="num">Срок службы</th><th>Начало амортизации</th><th class="num">Накопленная амортизация</th><th class="num">Остаточная стоимость</th><th class="num">Степень износа</th><th class="num">${grp === "off" ? "Почему" : "Амортизация в месяц"}</th></tr></thead><tbody>${list.map(x => `<tr data-e="${esc(x.id)}">
        <td><b>${esc(x.inv_number || "—")}</b></td><td><div class="sn-mat sm">${phHtml(x.photo_id)}<span>${esc(x.name)}</span></div></td><td>${x.category ? `<span class="eqs-cat">${esc(x.category)}</span>` : "—"}</td>
        <td class="num"><b>${eqMoney(x.cost)}</b></td><td class="num">${yrs(x.useful_months)}</td><td>${x.first ? eqMonth(x.first) : "—"}</td><td class="num">${grp === "off" ? "—" : eqMoney(x.accumulated)}</td><td class="num">${eqMoney(x.residual)}</td>
        <td class="num">${grp === "off" ? "—" : `<span class="eqs-wear ${x.percent >= 100 ? "full" : x.percent >= 75 ? "hi" : ""}">${x.percent.toLocaleString("ru-RU")} %</span>`}</td>
        <td class="num">${grp === "off" ? `<span class="muted">${esc(x.why)}</span>` : x.monthly ? eqMoney(x.monthly) : "—"}</td></tr>`).join("")}</tbody></table><div class="eqs-foot muted">Показано: ${list.length}</div>`
      : `<div class="empty"><b>Здесь пусто</b><span>${grp === "off" ? "У всего оборудования клиники указан срок" : "Укажите стоимость и срок полезного использования в карточках"}</span></div>`}</section></div>`;
  loadThumbs(body);
  $("#amYear").onchange = e => { EQS.amYear = +e.target.value; eqAmortYear(); };
  $("#amOld").onclick = () => eqAmortTab();
  $$(".eqs-bar2 .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.amGrp = b.dataset.g; eqAmortYear(); });
  $$("tr[data-e]", body).forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e));
}

/* ------------------------------------------------------------ «Выбытие и списание» */
const EQ_DISP_REASONS = ["Непригодно к эксплуатации", "Сильный износ", "Неисправно, ремонт экономически нецелесообразен", "Морально устарело",
  "Передано партнёру по договору", "Продано", "Утрата или хищение"];
async function eqDisposalTab() {
  const body = $("#stockBody");
  EQS.dsYear = EQS.dsYear || new Date().getFullYear();
  const [r, list] = await Promise.all([api.equipment_disposals(EQS.dsYear), can("equipment") ? api.equipment_list("", false) : Promise.resolve([])]);
  if (!EQS.refs) { try { EQS.refs = await api.equipment_refs(); } catch (x) { /* the reasons by default */ } }
  const mon = r.sum !== undefined, edit = can("equipment"), tab = EQS.dsTab || "";
  const rows = r.rows.filter(x => !tab || x.kind === tab);
  const pill = x => x.kind === "utilize" ? eqPill("ok", x.status_title) : x.kind === "transfer" ? eqPill("plan", x.status_title) : x.kind === "sale" ? eqPill("plan", x.status_title) : eqPill("wait", x.status_title);
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Выбытие и списание</h2><span class="muted">Списание, утилизация, продажа и передача оборудования</span></div><span class="grow"></span>${eqYearSel("dsYear", EQS.dsYear)}</div>
    <div class="eqs-tiles eqs-tiles5">${eqTile(EQX.box, "Выбыло за период", `${r.count} ед.`)}${mon ? eqTile(EQX.coins, "Сумма списания", eqMoney(r.sum)) : eqTile(EQX.doc, "Списано", `${r.writeoff} ед.`)}${eqTile(EQX.cycle, "Утилизировано", `${r.utilize} ед.`)}${eqTile(EQX.cart, "Реализовано", `${r.sale} ед.`)}${eqTile(EQN.eq_moves, "Передано", `${r.transfer + r.return} ед.`)}</div>
    <div class="eqs-g2r eqs-g2r-wide">${edit ? `<section class="eqs-card" id="dsForm"><h3>${EQX.doc}Создать списание (выбытие)</h3>
        <div class="eqs-form2"><label class="fl">Оборудование *<select class="input" id="dsEq"><option value="">Выберите оборудование</option>${list.map(e => `<option value="${esc(e.id)}">${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}</option>`).join("")}</select></label>
          <label class="fl">Способ выбытия *<select class="input" id="dsKind">${Object.entries(r.kinds).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>
          <label class="fl">Причина выбытия *<input class="input" id="dsReason" list="dsReasons" placeholder="Непригодно к эксплуатации"></label>
          <label class="fl">Дата *<input class="input" type="date" id="dsDate" value="${iso(new Date())}"></label>
          <label class="fl">Ответственный *<input class="input" id="dsResp" value="${esc(ME ? ME.name || "" : "")}"></label>
          <label class="fl">Основание (документ)${EQS.refs && EQS.refs.module && EQS.refs.module.no_doc_disposal ? " *" : ""}<input class="input" id="dsBasis" placeholder="Акт технического состояния № 14"></label>
          <div class="eqs-span2 eqs-form2" id="dsCom"><label class="fl">Председатель комиссии *<input class="input" id="dsC1"></label><label class="fl">Член комиссии *<input class="input" id="dsC2"></label></div>
          ${mon ? `<label class="fl" id="dsAmW" hidden>Сумма продажи, ₽<input class="input num" type="number" min="0" step="any" id="dsAmount"></label>` : ""}</div>
        <datalist id="dsReasons">${((EQS.refs && EQS.refs.disp_reasons) ? EQS.refs.disp_reasons.map(x => x.name) : EQ_DISP_REASONS).map(x => `<option value="${esc(x)}">`).join("")}</datalist>
        <div class="auth-err" id="dsErr"></div><div class="eqs-wfoot"><span class="grow"></span><button class="btn ghost" id="dsClear">Отмена</button><button class="btn" id="dsOk">Сформировать акт →</button></div></section>` : ""}
      <section class="eqs-card"><h3>${EQX.doc}Последние документы выбытия</h3>${r.rows.length ? `<div class="eqs-ev eqs-docs">${r.rows.slice(0, 5).map(x => `<button data-e="${esc(x.id)}">${EQX.doc}<span><b>${esc(x.doc)}</b><small>${esc([x.inv_number, x.name].filter(Boolean).join(" · "))}</small></span><em>${fmtDateShort(x.date)}</em>${mon ? `<strong>${eqMoney(x.residual)}</strong>` : ""}</button>`).join("")}</div>` : `<div class="muted">Оборудование ещё не выбывало</div>`}</section></div>
    <div class="eqs-bar2"><div class="eqs-seg">${[["", `Реестр (${r.rows.length})`], ["writeoff", "Списано"], ["utilize", "Утилизировано"], ["sale", "Реализовано"], ["transfer", "Передано"], ["return", "Возвращено"]].map(([k, t]) => `<button data-t="${k}" class="${k === tab ? "on" : ""}">${t}${k ? ` (${r.rows.filter(x => x.kind === k).length})` : ""}</button>`).join("")}</div></div>
    <section class="eqs-card eqs-tcard">${rows.length ? `<table class="tbl eqs-reg" id="dsReg"><thead><tr><th>№ документа</th><th>Дата</th><th>Оборудование</th><th>Инв. номер</th>${mon ? '<th class="num">Первоначальная стоимость</th><th class="num">Остаточная стоимость</th>' : ""}<th>Способ выбытия</th><th>Причина</th><th>Статус</th></tr></thead><tbody>${rows.map(x => `<tr data-e="${esc(x.id)}">
      <td><b>${esc(x.doc)}</b></td><td>${fmtDateShort(x.date)}</td><td><div class="sn-mat sm">${phHtml(x.photo_id)}<span>${esc(x.name)}</span></div></td><td>${esc(x.inv_number || "—")}</td>
      ${mon ? `<td class="num">${eqMoney(x.cost)}</td><td class="num"><b>${eqMoney(x.residual)}</b>${x.amount ? `<small class="muted" style="display:block">продажа ${eqMoney(x.amount)}</small>` : ""}</td>` : ""}
      <td><span class="eqs-kind ${x.kind === "writeoff" ? "bad" : x.kind === "utilize" ? "plan" : "ok"}">${esc(x.kind_title)}</span></td><td class="muted">${esc(x.reason)}</td><td>${pill(x)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>Здесь пусто</b><span>Выбывшее оборудование появится после оформления акта</span></div>`}</section></div>`;
  loadThumbs(body);
  $("#dsYear").onchange = e => { EQS.dsYear = +e.target.value; eqDisposalTab(); };
  $$(".eqs-bar2 .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.dsTab = b.dataset.t; eqDisposalTab(); });
  $$("[data-e]", body).forEach(b => b.onclick = () => openEquipment(b.dataset.e));
  const k = $("#dsKind"); if (!k) return;
  const sync = () => { $("#dsCom").hidden = !["writeoff", "utilize"].includes(k.value); const w = $("#dsAmW"); if (w) w.hidden = k.value !== "sale"; };
  k.onchange = sync; sync();
  $("#dsClear").onclick = () => eqDisposalTab();
  $("#dsOk").onclick = async () => {
    const id = $("#dsEq").value; if (!id) return ($("#dsErr").textContent = "Выберите оборудование");
    const f = {id, kind: k.value, reason: $("#dsReason").value, date: $("#dsDate").value, responsible: $("#dsResp").value, basis: $("#dsBasis").value,
      commission: [$("#dsC1").value, $("#dsC2").value].filter(x => x.trim())};
    if ($("#dsAmount")) f.amount = $("#dsAmount").value;
    if (!await ask("Оформить выбытие?", {danger: true, ok: "Оформить", text: "Оборудование уйдёт из работы, карточка станет только для просмотра."})) return;
    try { const e = await api.equipment_dispose(f); toast("Выбытие оформлено"); if (["writeoff", "utilize", "transfer"].includes(f.kind) && e) printEquipmentAct(e); eqDisposalTab(); }
    catch (x) { $("#dsErr").textContent = errText(x); }
  };
}

/* ------------------------------------------------------------ «Планирование закупок» */
const QN = ["I", "II", "III", "IV"];
async function eqPurchasesTab() {
  const body = $("#stockBody");
  EQS.puYear = EQS.puYear || new Date().getFullYear();
  const r = await api.equipment_purchases(EQS.puYear), view = EQS.puView || "plan", edit = can("equipment"), appr = can("equipment_approve");
  const pill = x => x.status === "approved" || x.status === "bought" ? eqPill("ok", x.status_title) : x.status === "pending" ? eqPill("wait", x.status_title) : x.status === "rejected" ? eqPill("bad", x.status_title) : eqPill("plan", x.status_title);
  const prio = x => `<span class="eqs-kind ${x.priority === "high" ? "bad" : x.priority === "mid" ? "warn" : "plan"}">${esc(x.priority_title)}</span>`;
  const bs = r.by_status, tot = r.total || 1;
  const sh = v => `${(v * 100 / tot).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
  const acts = x => [edit && ["draft", "rejected"].includes(x.status) && ["edit", "изменить"], edit && ["draft", "rejected"].includes(x.status) && ["send", "на согласование"],
    appr && x.status === "pending" && ["approve", "согласовать"], appr && x.status === "pending" && ["reject", "отклонить"], edit && x.status === "approved" && ["bought", "куплено"],
    edit && ["pending", "approved"].includes(x.status) && ["draft", "в черновик"], edit && ["draft", "rejected"].includes(x.status) && ["delete", "удалить"]].filter(Boolean);
  const plan = r.rows.length ? `<table class="tbl eqs-reg" id="puJ"><thead><tr><th>Оборудование / наименование</th><th>Причина закупки</th><th>Категория</th><th class="num">Бюджет</th><th>Период</th><th>Приоритет</th><th>Статус</th><th></th></tr></thead><tbody>${r.rows.map(x => `<tr data-pu="${esc(x.id)}">
      <td><b>${esc(x.name)}</b><small class="muted" style="display:block">${esc([x.number, x.replace_name && "замена: " + x.replace_name, x.offers.length && `КП: ${x.offers.length}`].filter(Boolean).join(" · "))}</small></td>
      <td class="muted">${esc(x.reason || "")}</td><td>${x.category ? `<span class="eqs-cat">${esc(x.category)}</span>` : "—"}</td><td class="num"><b>${eqMoney(x.budget)}</b></td><td>${QN[(x.quarter || 1) - 1]} квартал</td>
      <td>${prio(x)}</td><td>${pill(x)}${x.answer && x.status === "rejected" ? `<small class="muted" style="display:block">${esc(x.answer)}</small>` : ""}</td>
      <td class="eqs-acts2">${acts(x).map(([k, t]) => `<button class="linkbtn ${["reject", "delete"].includes(k) ? "danger-t" : ""}" data-a="${k}">${t}</button>`).join("")}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="3"><b>Итого по плану:</b></td><td class="num"><b>${eqMoney(r.total)}</b></td><td colspan="4"></td></tr></tfoot></table>`
    : `<div class="empty"><b>План закупок на ${r.year} год пуст</b><span>${edit ? "«Добавить закупку» — что купить, зачем, за сколько и когда" : ""}</span></div>`;
  const cal = `<table class="tbl eqs-cal"><thead><tr><th>Оборудование</th>${QN.map(q => `<th>${q} квартал</th>`).join("")}</tr></thead><tbody>${r.rows.filter(x => x.status !== "rejected").map(x => `<tr data-pu="${esc(x.id)}"><td>${esc(x.name)}</td>${[1, 2, 3, 4].map(q => `<td>${x.quarter === q ? `<span class="eqs-calchip ${x.status}">${eqMoney(x.budget)}</span>` : ""}</td>`).join("")}</tr>`).join("") || '<tr><td colspan="5" class="muted">Нет закупок</td></tr>'}
    <tr class="eqs-caltot"><td><b>Итого</b></td>${r.by_quarter.map(v => `<td><b>${v ? eqMoney(v) : "—"}</b></td>`).join("")}</tr></tbody></table>`;
  const by = (k, dict) => Object.entries(dict).map(([key, t]) => [t, r.rows.filter(x => x.status !== "rejected" && x[k] === key).reduce((s, x) => s + (x.budget || 0), 0)]).filter(x => x[1]);
  const ana = `<div class="eqs-g2"><div><h3>По источникам финансирования</h3><div class="eqs-bars">${by("funding", r.funding).map(([t, v]) => `<div class="eqs-bar"><span>${esc(t)}</span><i><u style="width:${v / tot * 100}%"></u></i><b>${eqMoney(v)}</b><small>${sh(v)}</small></div>`).join("") || '<div class="muted">—</div>'}</div></div>
    <div><h3>По приоритету</h3><div class="eqs-bars">${by("priority", r.priorities).map(([t, v]) => `<div class="eqs-bar"><span>${esc(t)}</span><i><u style="width:${v / tot * 100}%"></u></i><b>${eqMoney(v)}</b><small>${sh(v)}</small></div>`).join("") || '<div class="muted">—</div>'}</div></div></div>`;
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Планирование закупок</h2><span class="muted">План приобретения и замены оборудования</span></div><span class="grow"></span>${eqYearSel("puYear", r.year)}</div>
    <div class="eqs-tiles eqs-tiles5">${eqTile(EQX.coins, "Плановый бюджет", eqMoney(r.total))}${eqTile(EQX.cart, "Планируемых закупок", r.count)}${eqTile(EQX.ok, "Согласовано", r.approved, "ok")}${eqTile(EQX.clock, "На согласовании", r.pending, r.pending ? "warn" : "")}${eqTile(EQX.doc, "Черновики", r.draft)}</div>
    <div class="eqs-g2r eqs-g2r-wide"><div class="eqs-col"><div class="eqs-bar2"><div class="eqs-seg">${[["plan", EQX.list, "План закупок"], ["cal", EQX.cal, "Календарный план"], ["ana", EQN.amort, "Аналитика"]].map(([k, ic, t]) => `<button data-v="${k}" class="${k === view ? "on" : ""}">${ic}${t}</button>`).join("")}</div>
        <span class="grow"></span>${edit ? `<button class="btn" id="puAdd">${EQX.plus}Добавить закупку</button>` : ""}</div>
      <section class="eqs-card ${view === "ana" ? "" : "eqs-tcard"}">${view === "plan" ? plan : view === "cal" ? cal : ana}</section></div>
      <div class="eqs-side2"><section class="eqs-card"><h3>Исполнение бюджета ${r.year} года</h3><div class="eqs-ringrow">${eqRing([{value: bs.approved, cls: "ok"}, {value: bs.pending, cls: "warn"}, {value: bs.draft, cls: "c4"}], eqShortMoney(r.total), "план")}
          <ul class="eqs-legend"><li class="ok"><span>Согласовано</span><b>${eqMoney(bs.approved)}</b></li><li class="warn"><span>На согласовании</span><b>${eqMoney(bs.pending)}</b></li><li class="c4"><span>Черновики</span><b>${eqMoney(bs.draft)}</b></li></ul></div></section>
        <section class="eqs-card"><h3>План закупок по категориям</h3>${r.by_category.length ? `<div class="eqs-bars eqs-bars-v">${r.by_category.map(g => `<div class="eqs-bar"><span>${esc(g.name)}</span><i><u style="width:${g.share}%"></u></i><b>${eqMoney(g.budget)}</b><small>${g.share.toLocaleString("ru-RU")} %</small></div>`).join("")}</div>` : '<div class="muted">—</div>'}</section>
        <section class="eqs-card"><h3>Ближайшие действия</h3>${r.actions.length ? `<div class="eqs-ev">${r.actions.map(x => `<button data-pa="${esc(x.id)}">${x.kind === "approve" ? EQX.cal : x.kind === "buy" ? EQX.cart : EQX.doc}<span><b>${esc(x.title)}</b></span>${EQX.chev}</button>`).join("")}</div>` : '<div class="muted">Нет действий</div>'}</section></div></div></div>`;
  $("#puYear").onchange = e => { EQS.puYear = +e.target.value; eqPurchasesTab(); };
  $$(".eqs-bar2 .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.puView = b.dataset.v; eqPurchasesTab(); });
  const add = $("#puAdd"); if (add) add.onclick = () => eqPurchaseEdit({year: r.year, quarter: 1, priority: "mid", funding: "own", offers: []}, r);
  $$("[data-pa]", body).forEach(b => b.onclick = () => eqPurchaseEdit(r.rows.find(x => x.id === b.dataset.pa), r));
  $$("tr[data-pu]", body).forEach(tr => tr.onclick = async ev => {
    const x = r.rows.find(y => y.id === tr.dataset.pu), a = ev.target.dataset && ev.target.dataset.a;
    if (!a || a === "edit") return eqPurchaseEdit(x, r);
    try {
      let why = "";
      if (a === "reject") { why = await promptText("Почему отклонено?"); if (!why) return; }
      if (a === "delete" && !await ask(`Удалить «${x.name}» из плана?`, {danger: true, ok: "Удалить"})) return;
      await api.equipment_purchase_status(x.id, a, why); toast("Сохранено"); eqPurchasesTab();
    } catch (e) { toast(errText(e), true); }
  });
}
async function eqPurchaseEdit(x, r) {
  const refs = EQS.refs || (EQS.refs = await api.equipment_refs()), list = await api.equipment_list("", false);
  const ro = !can("equipment") || !["draft", "rejected"].includes(x.status || "draft");
  const offerRow = (o, i) => `<tr data-o="${i}"><td><input class="input" data-k="supplier" value="${esc(o.supplier || "")}" placeholder="Поставщик" ${ro ? "disabled" : ""}></td><td><input class="input num" type="number" min="0" step="any" data-k="price" value="${o.price || ""}" ${ro ? "disabled" : ""}></td>
    <td><input class="input num" type="number" min="0" step="1" data-k="days" value="${o.days || ""}" placeholder="дн." ${ro ? "disabled" : ""}></td><td><input class="input" data-k="note" value="${esc(o.note || "")}" ${ro ? "disabled" : ""}><input type="hidden" data-k="file_id" value="${esc(o.file_id || "")}"><input type="hidden" data-k="file_name" value="${esc(o.file_name || "")}"></td>
    <td>${o.file_id ? `<button class="linkbtn" data-of="${esc(o.file_id)}">${EQX.doc}${esc(o.file_name || "файл")}</button>` : ""}${ro ? "" : ` <button class="linkbtn danger-t" data-od="${i}">убрать</button>`}</td></tr>`;
  const box = modal(`<div class="m-h"><h3>${x.id ? `${esc(x.number)} · ${esc(x.name)}` : "Новая закупка"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${x.id ? `<div class="muted eqs-hint">${esc(x.status_title)}${x.decided_name ? ` · ${esc(x.decided_name)} ${fmtDT(x.decided_at)}` : ""}${x.answer ? ` · ${esc(x.answer)}` : ""}</div>` : ""}
      <div class="grid3"><label class="fl" style="grid-column:span 2">Что закупить *<input class="input" id="puN" value="${esc(x.name || "")}" placeholder="Микроскоп" ${ro ? "disabled" : ""}></label>
        <label class="fl">Категория<input class="input" id="puC" list="puCats" value="${esc(x.category || "")}" ${ro ? "disabled" : ""}></label>
        <label class="fl">Причина *<input class="input" id="puR" list="puReasons" value="${esc(x.reason || "")}" placeholder="Плановая замена" ${ro ? "disabled" : ""}></label>
        <label class="fl">Бюджет, ₽ *<input class="input num" type="number" min="0" step="any" id="puB" value="${x.budget || ""}" ${ro ? "disabled" : ""}></label>
        <label class="fl">Источник финансирования<select class="input" id="puF" ${ro ? "disabled" : ""}>${Object.entries(refs.funding).map(([k, t]) => `<option value="${k}" ${k === x.funding ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <label class="fl">Год<input class="input num" type="number" min="2020" max="2100" id="puY" value="${x.year || new Date().getFullYear()}" ${ro ? "disabled" : ""}></label>
        <label class="fl">Квартал<select class="input" id="puQ" ${ro ? "disabled" : ""}>${[1, 2, 3, 4].map(q => `<option value="${q}" ${q === x.quarter ? "selected" : ""}>${QN[q - 1]} квартал</option>`).join("")}</select></label>
        <label class="fl">Приоритет<select class="input" id="puP" ${ro ? "disabled" : ""}>${Object.entries(refs.priorities).map(([k, t]) => `<option value="${k}" ${k === x.priority ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
      <label class="fl">Заменяет оборудование<select class="input" id="puX" ${ro ? "disabled" : ""}><option value="">— новое, ничего не заменяет —</option>${list.map(e => `<option value="${esc(e.id)}" ${e.id === x.replace_id ? "selected" : ""}>${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}</option>`).join("")}</select></label>
      <label class="fl">Обоснование *<textarea class="input" id="puJ" rows="3" ${ro ? "disabled" : ""} placeholder="Зачем клинике эта покупка: развитие терапии, износ, срок службы истёк…">${esc(x.justification || "")}</textarea></label>
      <h4 class="sub-h">Коммерческие предложения</h4><table class="tbl compact eqs-lines"><thead><tr><th>Поставщик</th><th class="num">Цена, ₽</th><th class="num">Срок</th><th>Примечание</th><th>Файл</th></tr></thead><tbody id="puO">${(x.offers || []).map(offerRow).join("")}</tbody></table>
      ${ro ? "" : `<div class="eqs-row"><button class="btn ghost small" id="puOA">+ Предложение</button>${x.id ? `<button class="btn ghost small" id="puOF">${EQX.doc}Загрузить КП (PDF, фото)</button>` : `<span class="muted">Файлы КП — после первого сохранения</span>`}</div>`}
      <datalist id="puCats">${refs.categories.map(c => `<option value="${esc(c.name)}">`).join("")}</datalist><datalist id="puReasons">${["Плановая замена", "Развитие терапии", "Износ", "Обновление", "Новое направление", "Требование надзора"].map(v => `<option value="${v}">`).join("")}</datalist>
      <div class="auth-err" id="puErr"></div></div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>${ro ? "Закрыть" : "Отмена"}</button>${ro ? "" : `<button class="btn ghost" id="puSave">Сохранить черновик</button><button class="btn" id="puSend">На согласование</button>`}</div>`, {wide: true});
  const read = () => ({id: x.id, name: $("#puN").value, category: $("#puC").value, reason: $("#puR").value, budget: $("#puB").value, funding: $("#puF").value, year: $("#puY").value,
    quarter: $("#puQ").value, priority: $("#puP").value, replace_id: $("#puX").value, justification: $("#puJ").value,
    offers: $$("#puO tr", box).map(tr => Object.fromEntries($$("[data-k]", tr).map(i => [i.dataset.k, i.value])))});
  const wire = () => { $$("[data-od]", box).forEach(b => b.onclick = () => b.closest("tr").remove());
    $$("[data-of]", box).forEach(b => b.onclick = async () => { try { eqOpenFile({...(await api.equipment_purchase_offer_open(b.dataset.of)), title: b.textContent}); } catch (e) { toast(errText(e), true); } }); };
  wire();
  const oa = $("#puOA", box); if (oa) oa.onclick = () => { $("#puO", box).insertAdjacentHTML("beforeend", offerRow({}, $$("#puO tr", box).length)); wire(); };
  const save = async () => { const id = await api.equipment_purchase_save(read()); x.id = id; return id; };
  const of = $("#puOF", box); if (of) of.onclick = () => { const inp = document.createElement("input"); inp.type = "file"; inp.accept = "application/pdf,image/*";
    inp.onchange = async () => { const f = inp.files[0]; if (!f) return; try { await save(); const data = await new Promise((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = bad; rd.readAsDataURL(f); });
      await api.equipment_purchase_offer_add(x.id, f.name, data); closeModal(); toast("КП загружено"); const rr = await api.equipment_purchases(EQS.puYear); eqPurchasesTab(); eqPurchaseEdit(rr.rows.find(y => y.id === x.id) || x, rr); } catch (e) { $("#puErr", box).textContent = errText(e); } };
    inp.click(); };
  const sv = $("#puSave", box); if (sv) sv.onclick = async () => { try { await save(); closeModal(); toast("Сохранено"); eqPurchasesTab(); } catch (e) { $("#puErr", box).textContent = errText(e); } };
  const sd = $("#puSend", box); if (sd) sd.onclick = async () => { try { const id = await save(); await api.equipment_purchase_status(id, "send"); closeModal(); toast("Отправлено на согласование"); eqPurchasesTab(); } catch (e) { $("#puErr", box).textContent = errText(e); } };
}

/* ------------------------------------------------------------ «Стороннее оборудование» */
async function eqThirdTab() {
  const body = $("#stockBody");
  const r = await api.equipment_third_party(), tab = EQS.tpTab || "", q = (EQS.tpQ || "").toLowerCase();
  const grp = x => ["other", "owner"].includes(x.ownership) ? "other" : x.ownership;
  let rows = r.rows.filter(x => (!tab || grp(x) === tab) && (!q || `${x.name} ${x.contractor} ${x.inv_number}`.toLowerCase().includes(q)));
  if (EQS.tpSort === "end") rows = rows.slice().sort((a, b) => (a.end || "9999") < (b.end || "9999") ? -1 : 1);
  const k = r.kinds, cls = {doctor: "ok", lease: "warn", leasing: "c3", other: "c4", owner: "c4"};
  const tot = r.total || 1, pc = n => `${(n * 100 / tot).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %`;
  const chip = x => `<span class="eqs-kind ${x.ownership === "doctor" ? "ok" : x.ownership === "lease" ? "warn" : "plan"}">${esc(x.ownership === "doctor" ? "Имущество врача" : x.ownership_title)}</span>`;
  const st = x => x.status === "ended" ? eqPill("bad", x.status_title) : x.status === "soon" ? eqPill("wait", x.status_title) : x.status === "active" ? eqPill("ok", x.status_title) : eqPill("plan", x.status_title);
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Стороннее оборудование</h2><span class="muted">Оборудование, не находящееся в собственности клиники (врачи, аренда, лизинг, иное пользование)</span></div><span class="grow"></span>
      ${can("equipment") ? `<button class="btn" id="tpAdd">${EQX.plus}Добавить оборудование</button>` : ""}</div>
    <div class="eqs-tiles eqs-tiles5">${eqTile(EQX.box, "Всего единиц", r.total)}${eqTile('<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/></svg>', "Имущество врачей", k.doctor)}${eqTile(EQX.wrench, "Аренда", k.lease)}${eqTile(EQX.doc, "Лизинг", k.leasing)}${STK.eq_money ? eqTile(EQX.coins, "Стоимость в учёте", eqMoney(r.cost)) : eqTile(EQX.list, "Иное пользование", k.other + k.owner)}</div>
    <div class="eqs-g3">
      <section class="eqs-card"><h3>Структура стороннего оборудования</h3><div class="eqs-ringrow">${eqRing([{value: k.doctor, cls: "ok"}, {value: k.lease, cls: "warn"}, {value: k.leasing, cls: "c3"}, {value: k.other + k.owner, cls: "c4"}], r.total, plural(r.total, "единица", "единицы", "единиц"))}
        <ul class="eqs-legend"><li class="ok"><span>Имущество врачей</span><b>${k.doctor} (${pc(k.doctor)})</b></li><li class="warn"><span>Аренда</span><b>${k.lease} (${pc(k.lease)})</b></li><li class="c3"><span>Лизинг</span><b>${k.leasing} (${pc(k.leasing)})</b></li><li class="c4"><span>Иное пользование</span><b>${k.other + k.owner} (${pc(k.other + k.owner)})</b></li></ul></div></section>
      <section class="eqs-card"><h3>${EQX.cal}Ближайшие события</h3>${r.events.length ? `<div class="eqs-ev">${r.events.map(x => `<button data-e="${esc(x.id)}" class="${x.overdue ? "late" : ""}">${x.title.includes("лизинг") ? EQX.doc : EQX.cycle}<span><b>${esc(x.title)}</b><small>${esc(x.name)}</small></span><em>${x.overdue ? "окончено · " : ""}${eqShortDate(x.date)}</em></button>`).join("")}</div>` : `<div class="muted">Сроки договоров в ближайшие полгода не истекают</div>`}</section>
      ${eqUseful([["docs", EQX.doc, "Договоры и документы", ""], ["terms", EQX.clock, "Контроль сроков", ""], ["cond", EQX.list, "Условия пользования", ""], ["print", EQX.doc, "Отчёт по стороннему оборудованию", ""]])}</div>
    <div class="eqs-bar2"><div class="eqs-seg">${[["", `Все (${r.total})`], ["doctor", `Имущество врачей (${k.doctor})`], ["lease", `Аренда (${k.lease})`], ["leasing", `Лизинг (${k.leasing})`], ["other", `Иное (${k.other + k.owner})`]].map(([kk, t]) => `<button data-t="${kk}" class="${kk === tab ? "on" : ""}">${t}</button>`).join("")}</div>
      <span class="grow"></span><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="tpQ" placeholder="Поиск по наименованию, владельцу…" value="${esc(EQS.tpQ || "")}"></div></div>
    <section class="eqs-card eqs-tcard">${rows.length ? `<table class="tbl eqs-reg" id="tpReg"><thead><tr><th>Наименование</th><th>Тип использования</th><th>Владелец / контрагент</th><th>Кабинет / место</th><th>Начало использования</th><th>Окончание</th><th>Статус</th></tr></thead><tbody>${rows.map(x => `<tr data-e="${esc(x.id)}">
      <td><div class="sn-mat sm">${phHtml(x.photo_id)}<span><b>${esc(x.name)}</b>${x.inv_number ? `<small class="muted" style="display:block">${esc(x.inv_number)}</small>` : ""}</span></div></td><td>${chip(x)}</td>
      <td>${esc(x.contractor || "—")}${x.contract_no ? `<small class="muted" style="display:block">договор № ${esc(x.contract_no)}</small>` : ""}</td><td>${esc(x.place || "—")}</td><td>${x.start ? fmtDateShort(x.start) : "—"}</td><td>${x.end ? fmtDateShort(x.end) : "—"}</td><td>${st(x)}</td></tr>`).join("")}</tbody></table><div class="eqs-foot muted">Показано: ${rows.length} из ${r.total}</div>`
      : `<div class="empty"><b>Стороннего оборудования нет</b><span>В карточке укажите принадлежность: имущество врача, аренда, лизинг или иное пользование</span></div>`}</section></div>`;
  loadThumbs(body);
  $$("[data-e]", body).forEach(b => b.onclick = () => openEquipment(b.dataset.e));
  $$(".eqs-bar2 .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.tpTab = b.dataset.t; eqThirdTab(); });
  let t; $("#tpQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { EQS.tpQ = e.target.value; eqThirdTab().then(() => { const i = $("#tpQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 250); };
  const add = $("#tpAdd"); if (add) add.onclick = () => editEquipment({ownership: tab && tab !== "other" ? tab : "doctor"});
  $$("[data-u]", body).forEach(b => b.onclick = () => ({
    docs: () => { EQS.docKind = "contract"; stockGo("equipment", typeof eqDocsTab === "function" ? "eq_docs" : "equipment"); },
    terms: () => { EQS.tpSort = EQS.tpSort === "end" ? "" : "end"; toast(EQS.tpSort ? "Сначала то, что заканчивается раньше" : "Обычный порядок"); eqThirdTab(); },
    cond: () => modal(`<div class="m-h"><h3>Условия пользования</h3><button class="x" data-close>×</button></div><div class="m-b"><table class="tbl compact"><thead><tr><th>Оборудование</th><th>Тип</th><th>Владелец</th><th>Договор</th><th>Срок</th></tr></thead><tbody>${r.rows.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.ownership_title)}</td><td>${esc(x.contractor || "—")}</td><td>${esc(x.contract_no || "—")}</td><td>${x.start ? fmtDateShort(x.start) : "…"} — ${x.end ? fmtDateShort(x.end) : "бессрочно"}</td></tr>`).join("")}</tbody></table><div class="muted eqs-hint">Стороннее оборудование не амортизируется (лизинг — по правилам клиники) и не попадает в выбытие в финотчёте. Платежи по аренде вносятся расходами.</div></div><div class="m-f"><span class="grow"></span><button class="btn" data-close>Закрыть</button></div>`, {wide: true}),
    print: () => { const tb = $("#tpReg"); if (!tb) return toast("Нет данных"); $("#printArea").innerHTML = `<h2>Стороннее оборудование на ${fmtDate(iso(new Date()))}</h2>${tb.outerHTML}`; window.print(); }})[b.dataset.u]());
}

/* ------------------------------------------------------------ «Документы» */
async function eqDocsTab() {
  const body = $("#stockBody");
  const r = await api.equipment_all_docs(), kind = EQS.docKind || "", q = (EQS.docQ || "").toLowerCase();
  const rows = r.docs.filter(d => (!kind || d.kind === kind) && (!q || `${d.title} ${d.equipment_name} ${d.inv_number}`.toLowerCase().includes(q)));
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Документы</h2><span class="muted">Паспорта, договоры, акты, гарантии — все документы оборудования клиники</span></div></div>
    <div class="eqs-tiles">${eqTile(EQX.doc, "Документов", r.docs.length)}${eqTile(EQX.list, "Паспортов", r.counts.passport || 0)}${eqTile(EQX.doc, "Договоров", r.counts.contract || 0)}${eqTile(EQX.warn, "Гарантия истекает", r.warranty.filter(w => !w.ended).length, r.warranty.some(w => !w.ended) ? "warn" : "")}</div>
    <div class="eqs-g2r"><div class="eqs-col"><div class="eqs-bar2"><div class="eqs-seg eqs-wrap">${[["", `Все (${r.docs.length})`], ...Object.entries(r.kinds).filter(([k]) => r.counts[k]).map(([k, t]) => [k, `${t} (${r.counts[k]})`])].map(([k, t]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${esc(t)}</button>`).join("")}</div>
        <span class="grow"></span><div class="search-row mini"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input id="docQ" placeholder="Документ или оборудование" value="${esc(EQS.docQ || "")}"></div></div>
      <section class="eqs-card eqs-tcard">${rows.length ? `<table class="tbl eqs-reg"><thead><tr><th>Документ</th><th>Вид</th><th>Оборудование</th><th>Добавлен</th><th>Кто</th></tr></thead><tbody>${rows.map(d => `<tr data-d="${esc(d.id)}">
          <td><button class="linkbtn" data-open="${esc(d.id)}">${d.image ? EQI.ph : EQI.doc}${esc(d.title)}</button></td><td><span class="eqs-cat">${esc(d.kind_title)}</span></td>
          <td><button class="linkbtn" data-e="${esc(d.equipment_id)}">${esc(d.equipment_name)}</button>${d.inv_number ? ` <small class="muted">${esc(d.inv_number)}</small>` : ""}</td><td>${fmtDT(d.created_at)}</td><td class="muted">${esc(d.created_by || "")}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty"><b>Документов нет</b><span>Загружайте их в карточке оборудования, вкладка «Документы»</span></div>`}</section></div>
      <div class="eqs-side2"><section class="eqs-card"><h3>${EQX.warn}Гарантии</h3>${r.warranty.length ? `<div class="eqs-ev">${r.warranty.map(w => `<button data-e="${esc(w.id)}" class="${w.ended ? "late" : ""}">${EQX.cal}<span><b>${esc(w.name)}</b><small>${esc(w.inv_number)}</small></span><em>${w.ended ? "истекла · " : "до "}${eqShortDate(w.date)}</em></button>`).join("")}</div>` : `<div class="muted">Гарантии в ближайший месяц не истекают</div>`}</section>
        <section class="eqs-card"><h3>${EQX.doc}Не хватает документов</h3>${r.missing.length ? `<div class="eqs-ev">${r.missing.slice(0, 8).map(m => `<button data-e="${esc(m.id)}">${EQX.doc}<span><b>${esc(m.name)}</b><small>нет: ${esc(m.lack.join(", ").toLowerCase())}</small></span>${EQX.chev}</button>`).join("")}</div>${r.missing.length > 8 ? `<div class="muted eqs-hint">И ещё ${r.missing.length - 8}</div>` : ""}` : `<div class="muted">У всего оборудования есть техпаспорт и договор</div>`}</section></div></div></div>`;
  $$(".eqs-bar2 .eqs-seg button", body).forEach(b => b.onclick = () => { EQS.docKind = b.dataset.k; eqDocsTab(); });
  let t; $("#docQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { EQS.docQ = e.target.value; eqDocsTab().then(() => { const i = $("#docQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 250); };
  $$("[data-e]", body).forEach(b => b.onclick = ev => { ev.stopPropagation(); openEquipment(b.dataset.e, "docs"); });
  $$("[data-open]", body).forEach(b => b.onclick = async ev => { ev.stopPropagation(); try { eqOpenFile(await api.equipment_doc_open(b.dataset.open)); } catch (x) { toast(errText(x), true); } });
}

/* ------------------------------------------------------------ «Аналитика и отчёты» */
async function eqAnalyticsTab() {
  const body = $("#stockBody");
  EQS.anYear = EQS.anYear || new Date().getFullYear();
  const r = await api.equipment_analytics(EQS.anYear), mon = r.amort !== undefined;
  const ms = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
  const top = Math.max(1, ...r.by_month.map(m => m.service + m.repair + m.diag)), maxA = Math.max(1, ...r.ages.map(a => a.count));
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Аналитика и отчёты</h2><span class="muted">Стоимость содержания и эффективность оборудования</span></div><span class="grow"></span>${eqYearSel("anYear", r.year)}
      <button class="btn ghost" id="anPrint">${EQX.doc}Печать отчёта</button></div>
    <div class="eqs-tiles eqs-tiles5">${eqTile(EQX.wrench, "Содержание за год", eqMoney(r.keep))}${eqTile(EQX.gear, "Ремонтов", r.repairs, r.repairs ? "warn" : "")}${eqTile(EQX.check, "Работ всего", r.works)}
      ${mon ? eqTile(EQN.amort, "Амортизация за год", eqMoney(r.amort)) + eqTile(EQX.clock, "Кресло-час (амортизация и содержание)", eqMoney(r.chair_hour)) : eqTile(EQX.coins, "ТО", eqMoney(r.service))}</div>
    <div class="eqs-g2"><section class="eqs-card"><h3>Стоимость содержания по месяцам</h3><div class="mtc-bars eqs-anbars">${r.by_month.map((m, i) => { const s = m.service + m.repair + m.diag;
        return `<div class="mtc-bar" title="${ms[i]}: ${eqMoney(s)} — ТО ${eqMoney(m.service)}, ремонт ${eqMoney(m.repair)}, диагностика ${eqMoney(m.diag)}"><i>${["service", "repair", "diag"].map(k => m[k] ? `<u class="${k === "repair" ? "writeoff" : k === "diag" ? "treatment" : "service"}" style="height:${m[k] / top * 100}%"></u>` : "").join("")}</i><b>${s ? eqShortMoney(s).replace(" ₽", "") : ""}</b><small>${ms[i].toLowerCase()}</small></div>`; }).join("")}</div>
        <div class="mtc-legend"><span class="service">ТО</span><span class="writeoff">Ремонт</span><span class="treatment">Диагностика</span></div></section>
      <section class="eqs-card"><h3>Возраст парка</h3><div class="eqs-bars">${r.ages.map(a => `<div class="eqs-bar"><span>${esc(a.name)}</span><i><u style="width:${a.count / maxA * 100}%"></u></i><b>${a.count} шт.</b></div>`).join("")}</div>
        <h3>Дороже всего в содержании</h3>${r.top.length ? `<div class="eqs-ev">${r.top.slice(0, 5).map(g => `<button data-e="${esc(g.id)}">${EQX.wrench}<span><b>${esc(g.name)}</b><small>${esc([g.inv_number, `работ: ${g.works}`, g.repairs ? `ремонтов: ${g.repairs}` : ""].filter(Boolean).join(" · "))}</small></span><em>${eqMoney(g.cost)}</em></button>`).join("")}</div>` : `<div class="muted">Работ с суммой за год не было</div>`}</section></div>
    <section class="eqs-card eqs-tcard"><h3 class="eqs-tch">${EQX.list}По категориям</h3><table class="tbl eqs-reg" id="anCat"><thead><tr><th>Категория</th><th class="num">Единиц</th><th class="num">Работ (ремонтов)</th><th class="num">Содержание за год</th>${mon ? '<th class="num">Амортизация за год</th><th class="num">Итого затрат</th>' : ""}</tr></thead><tbody>${r.by_category.map(c => `<tr>
      <td><b>${esc(c.name)}</b></td><td class="num">${c.count}</td><td class="num">${c.repairs}</td><td class="num">${eqMoney(c.keep)}</td>${mon ? `<td class="num">${eqMoney(c.amort)}</td><td class="num"><b>${eqMoney(c.keep + c.amort)}</b></td>` : ""}</tr>`).join("")}</tbody></table></section></div>`;
  $("#anYear").onchange = e => { EQS.anYear = +e.target.value; eqAnalyticsTab(); };
  $$("[data-e]", body).forEach(b => b.onclick = () => openEquipment(b.dataset.e));
  $("#anPrint").onclick = () => { $("#printArea").innerHTML = `<h2>Оборудование: стоимость содержания за ${r.year} год</h2><p>Содержание: ${eqMoney(r.keep)} (ТО ${eqMoney(r.service)}, ремонт ${eqMoney(r.repair)}, диагностика ${eqMoney(r.diag)})${mon ? `; амортизация: ${eqMoney(r.amort)}` : ""}</p>${$("#anCat").outerHTML}`; window.print(); };
}

/* ------------------------------------------------------------ «Журнал действий» */
async function eqLogTab() {
  const body = $("#stockBody");
  const f = EQS.logF = EQS.logF || {};
  const r = await api.equipment_log(f);
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head"><div><h2>Журнал действий</h2><span class="muted">История операций сотрудников с оборудованием</span></div><span class="grow"></span>
      <button class="btn ghost" data-xls="#logT" data-xls-name="Журнал действий с оборудованием">${EQX.down}Excel</button></div>
    <section class="eqs-card eqs-filters">
      <label class="eqs-f"><span>Событие</span><select class="input" id="lgK"><option value="">Все события</option>${Object.entries(r.kinds).map(([k, t]) => `<option value="${k}" ${k === f.kind ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
      <label class="eqs-f"><span>С</span><input class="input" type="date" id="lgF" value="${esc(f.from || "")}"></label><label class="eqs-f"><span>По</span><input class="input" type="date" id="lgT" value="${esc(f.to || "")}"></label>
      <label class="eqs-f"><span>Сотрудник</span><select class="input" id="lgU"><option value="">Все</option>${r.users.map(u => `<option ${u === f.user ? "selected" : ""}>${esc(u)}</option>`).join("")}</select></label>
      <button class="linkbtn eqs-reset" id="lgX" ${Object.values(f).some(Boolean) ? "" : "hidden"}>${EQX.x}Сбросить</button></section>
    <section class="eqs-card eqs-tcard">${r.rows.length ? `<table class="tbl eqs-reg" id="logT"><thead><tr><th>Дата</th><th>Оборудование</th><th>Событие</th><th>Описание</th><th class="num">Сумма</th><th>Сотрудник</th></tr></thead><tbody>${r.rows.map(x => `<tr data-e="${esc(x.equipment_id)}">
        <td>${fmtDateShort(x.date)}</td><td><b>${esc(x.name || "—")}</b>${x.inv_number ? ` <small class="muted">${esc(x.inv_number)}</small>` : ""}</td><td><span class="eqs-cat">${esc(x.kind_title)}</span></td>
        <td class="muted eqs-wraptd">${esc(x.text || "")}</td><td class="num">${x.cost ? eqMoney(x.cost) : "—"}</td><td>${esc(x.user_name || "—")}</td></tr>`).join("")}</tbody></table><div class="eqs-foot muted">Показано: ${r.rows.length}${r.rows.length >= 500 ? " (последние 500)" : ""}</div>`
      : `<div class="empty"><b>Событий нет</b><span>Измените фильтры</span></div>`}</section></div>`;
  const set = (k, v) => { f[k] = v; eqLogTab(); };
  $("#lgK").onchange = e => set("kind", e.target.value); $("#lgF").onchange = e => set("from", e.target.value);
  $("#lgT").onchange = e => set("to", e.target.value); $("#lgU").onchange = e => set("user", e.target.value);
  $("#lgX").onclick = () => { EQS.logF = {}; eqLogTab(); };
  $$("tr[data-e]", body).forEach(tr => tr.onclick = () => openEquipment(tr.dataset.e, "history"));
}

/* ------------------------------------------------------------ «Справочники и настройки» (3.16, mockup 10) */
const EQR = {
  chair: '<svg viewBox="0 0 24 24"><path d="M6 20.5h7M9.5 20.5V16M4.5 12.5c0-1.7 1.3-3 3-3h2l1.5 2h5.5a3 3 0 0 1 3 3v.5H8a3.5 3.5 0 0 1-3.5-2.5z"/><path d="M9.5 9.5V5.5a1.5 1.5 0 0 1 3 0v6"/></svg>',
  tag: '<svg viewBox="0 0 24 24"><path d="M3.5 12.5V4.5h8l9 9-8 8z"/><circle cx="8" cy="9" r="1.5"/></svg>',
  tools: '<svg viewBox="0 0 24 24"><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-5 4 4 0 0 1 0 3z"/><path d="m4 4 5.5 5.5M4 8l4-4"/></svg>',
  place: '<svg viewBox="0 0 24 24"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.5"/></svg>',
  house: '<svg viewBox="0 0 24 24"><path d="M4 20.5h16M6 20.5V8.5l6-4.5 6 4.5v12"/><path d="M10 20.5v-5h4v5M9.5 11h.01M14.5 11h.01"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4.5 6.5h15M9.5 6.5V4h5v2.5M6.5 6.5l1 14h9l1-14M10 10.5v6M14 10.5v6"/></svg>',
  sliders: '<svg viewBox="0 0 24 24"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></svg>',
  user: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.9-3.6 3.6-5.5 7-5.5s6.1 1.9 7 5.5"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  history: '<svg viewBox="0 0 24 24"><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v3.7h3.7"/><path d="M12 8v4.5l3 2"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="m12 3.5 8.5 4.5-8.5 4.5L3.5 8z"/><path d="m3.5 12 8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M12 6.5c-2-1.5-5-2-8-1.5v13c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5V5c-3-.5-6 0-8 1.5zM12 6.5v13"/></svg>',
  pen: '<svg viewBox="0 0 24 24"><path d="M4 20l1-4.5L15.5 5a2.1 2.1 0 0 1 3 3L8 18.5z"/><path d="m13.5 7 3 3"/></svg>',
  io: '<svg viewBox="0 0 24 24"><path d="M12 15V4M8 7.5 12 4l4 3.5M5 14.5v5h14v-5"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/></svg>',
};
const EQ_REF_TILES = [["cats", EQR.chair, "Виды оборудования", "Категории и группы"], ["models", EQR.tag, "Модели и производители", "Бренды, модели, артикулы"],
  ["groups", EQX.grid, "Инвентарные группы", "Классификатор, коды"], ["works", EQR.tools, "Виды работ (ТО)", "Осмотр, ремонт, калибровка"],
  ["regs", EQX.cal, "Регламенты обслуживания", "Периодичность и чек-листы"], ["norms", EQN.amort, "Нормы амортизации", "Сроки, методы, ставки"],
  ["places", EQR.place, "Места эксплуатации", "Кабинеты, помещения"], ["use", EQR.house, "Типы использования", "Собственное, аренда, лизинг"],
  ["reasons", EQR.trash, "Причины выбытия", "Износ, поломка, утилизация"]];

async function eqRefsTab() {
  const body = $("#stockBody");
  const r = EQS.refs = await api.equipment_refs();
  EQS.round = r.module.round;
  const subs = [["refs", EQR.sliders, "Справочники"], ["sys", EQX.gear, "Настройки системы"], canAny("staff", "equipment_approve") && ["users", EQR.user, "Пользователи и права"],
    canAny("equipment", "equipment_approve", "settings") && ["int", EQR.link, "Интеграции"], canAny("equipment", "equipment_approve", "staff") && ["log", EQR.history, "Журнал изменений"]].filter(Boolean);
  const sub = subs.some(s => s[0] === EQS.refSub) ? EQS.refSub : "refs";
  body.innerHTML = `<div class="eqs">
    <div class="eqs-head eqs-hico"><i>${EQX.gear}</i><div><h2>Справочники и настройки</h2><span class="muted">Управление основными данными, параметрами учёта и работой модуля «Оборудование»</span></div></div>
    <div class="eqs-subs">${subs.map(([k, ic, t]) => `<button data-sub="${k}" class="${k === sub ? "on" : ""}">${ic}<span>${t}</span></button>`).join("")}</div>
    <div id="eqRefBody" class="eqs-col"></div></div>`;
  $$("[data-sub]", body).forEach(b => b.onclick = () => { EQS.refSub = b.dataset.sub; eqRefsTab(); });
  await ({refs: eqRefsMain, sys: eqRefsSys, users: eqRefsUsers, int: eqRefsInt, log: eqRefsLog}[sub])(r);
}

function eqRefsMain(r) {
  const el = $("#eqRefBody"), edit = can("equipment");
  const mfs = r.manufacturers.map(n => ({name: n, models: r.models.filter(x => x.manufacturer === n).length, count: r.models.filter(x => x.manufacturer === n).reduce((s, x) => s + (x.count || 0), 0)}));
  const keyRefs = [["cats", EQR.chair, "Виды оборудования", r.categories.length, "eqXc"], ["models", EQR.tag, "Производители", mfs.length, "eqXf"],
    ["models", EQR.tag, "Модели", r.models.length, "eqXm"], ["regs", EQX.cal, "Регламенты ТО", r.regs.length, "eqXr"], ["reasons", EQR.trash, "Причины выбытия", r.disp_reasons.length, "eqXd"]];
  const xt = (id, head, rows) => `<table id="${id}"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(x => `<tr>${x.map(v => `<td>${esc(v ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const qa = [["add", EQX.plus, "Добавить оборудование", edit], ["cat", EQR.sliders, "Добавить категорию", edit], ["reg", EQX.cal, "Создать регламент ТО", edit],
    ["norms", EQN.amort, "Настроить амортизацию", edit], ["io", EQR.io, "Импорт / экспорт справочников", true]].filter(x => x[3]);
  el.innerHTML = `<div class="eqs-g2q">
      <section class="eqs-card"><h3>${EQR.layers}Справочники оборудования</h3><div class="eqs-rtiles">${EQ_REF_TILES.map(([k, ic, t, s]) => `<button data-ref="${k}"><i>${ic}</i><span><b>${t}</b><small>${s}</small></span>${EQX.chev}</button>`).join("")}</div></section>
      <section class="eqs-card"><h3>${EQR.bolt}Быстрые действия</h3><div class="eqs-qa">${qa.map(([k, ic, t], i) => `<button data-qa="${k}" class="${i ? "" : "on"}">${ic}<span>${t}</span>${EQX.chev}</button>`).join("")}</div></section></div>
    <div class="eqs-g3b">
      <section class="eqs-card"><h3>${EQR.layers}Ключевые справочники</h3><table class="tbl compact eqs-keyt"><thead><tr><th>Справочник</th><th class="num">Записей</th><th class="num">Действия</th></tr></thead>
        <tbody>${keyRefs.map(([k, ic, t, n, tid]) => `<tr><td><span class="eqs-kr">${ic}${t}</span></td><td class="num"><b>${n}</b></td><td class="num eqs-kacts"><button class="icon-btn" data-ref="${k}" title="${edit ? "Открыть и изменить" : "Открыть"}">${EQR.pen}</button><button class="icon-btn" data-xls="#${tid}" data-xls-name="${t}" title="Скачать в Excel">${EQX.down}</button></td></tr>`).join("")}</tbody></table>
        <div hidden>${xt("eqXc", ["Вид оборудования", "Единиц", "Норматив, мес."], r.categories.map(c => [c.name, c.count, c.life || ""]))}
          ${xt("eqXf", ["Производитель", "Моделей", "Единиц"], mfs.map(x => [x.name, x.models, x.count]))}
          ${xt("eqXm", ["Производитель", "Модель", "Артикул", "Категория", "Единиц"], r.models.map(x => [x.manufacturer, x.model, x.article, x.category, x.count]))}
          ${xt("eqXr", ["Регламент", "Вид", "Раз в, мес.", "Категория", "Чек-лист"], r.regs.map(g => [g.name, r.plan_kinds[g.kind] || g.kind, g.every_months, g.category, g.checklist.join("; ")]))}
          ${xt("eqXd", ["Причина выбытия", "Случаев"], r.disp_reasons.map(x => [x.name, x.count]))}</div></section>
      <section class="eqs-card"><h3>${EQX.gear}Основные настройки модуля</h3>${eqModuleRows(r, true)}</section>
      <section class="eqs-card"><h3>${EQR.book}Справочная информация</h3><div class="eqs-qa">${[["guide", EQX.doc, "Инструкция по учёту оборудования"], ["inv", EQX.check, "Порядок проведения инвентаризации"],
        ["calc", EQX.calc, "Методики амортизации (пример расчёта)"], ["tpl", EQX.doc, "Шаблоны документов"]].map(([k, ic, t]) => `<button data-info="${k}">${ic}<span>${t}</span>${EQX.chev}</button>`).join("")}</div></section></div>`;
  $$("[data-ref]", el).forEach(b => b.onclick = () => eqRefEdit(b.dataset.ref));
  $$("[data-qa]", el).forEach(b => b.onclick = () => ({add: () => editEquipment({}), cat: () => eqRefEdit("cats", true), reg: () => eqRefEdit("regs", true),
    norms: () => eqRefEdit("norms"), io: eqRefsIO})[b.dataset.qa]());
  $$("[data-info]", el).forEach(b => b.onclick = () => ({guide: eqGuide, inv: eqInvGuide, calc: eqAmortCalc, tpl: () => eqTemplates()})[b.dataset.info]());
  eqModuleWire(el);
}

/** The module's settings: compact (the main tab of the mockup) or with explanations («Настройки системы»). They are saved at once. */
function eqModuleRows(r, compact) {
  const m = r.module, acc = can("accounting"), edit = can("equipment");
  const tips = {auto_amort: "Амортизация оборудования каждый месяц входит в ОПиУ (Бухгалтерия → прибыль). Включает и выключает сотрудник с правом «Бухгалтерия».",
    control_to: `Просроченное ТО, поверки, осмотры и то, что наступит в ближайшие ${m.to_days} дн.: счётчик на «Оборудовании» в меню и колокольчик раздела${m.to_report ? ", строка в отчёте за день" : ""}.`,
    no_doc_disposal: "Выбытие — списание, утилизацию, продажу, передачу, возврат — нельзя оформить без документа-основания (акт технического состояния, договор).",
    third_party: "Раздел «Стороннее оборудование» и выбор аренды, лизинга, имущества врача или учредителя в карточке.",
    to_report: "Просроченное и ближайшее ТО уходит владельцу вместе с отчётом за день в Telegram или на почту (Настройки → «Касса и оплаты» → «Отчёт за день»).",
    method: "Стоимость за вычетом ликвидационной равномерно по месяцам срока службы, начиная с месяца после ввода в эксплуатацию.",
    round: "Как раздел показывает суммы: целыми рублями или с копейками. Расчёты всегда идут с копейками."};
  const sw = (k, t, dis) => `<label class="eqs-swr ${compact ? "" : "full"}" ${dis ? `title="${dis}"` : ""}><span>${t}${compact ? `<i class="eqs-i" title="${esc(tips[k])}">${EQR.info}</i>` : `<small>${esc(tips[k])}</small>`}</span><input type="checkbox" data-mod="${k}" ${m[k] ? "checked" : ""} ${dis ? "disabled" : ""}><em class="eqs-tg"></em></label>`;
  const sel = (k, t, opts, dis) => `<label class="eqs-swr ${compact ? "" : "full"}" ${dis ? `title="${dis}"` : ""}><span>${t}${compact ? "" : `<small>${esc(tips[k])}</small>`}</span><select class="input" data-mod="${k}" ${dis ? "disabled" : ""}>${Object.entries(opts).map(([v, x]) => `<option value="${v}" ${v === m[k] ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>`;
  const noAcc = acc ? "" : "Меняет сотрудник с правом «Бухгалтерия»", noEd = edit ? "" : "Меняет сотрудник с правом «Оборудование»";
  if (compact) return `<div class="eqs-mod">${sel("method", "Метод амортизации по умолчанию", r.methods, noAcc)}${sel("round", "Округление сумм", r.rounds, noEd)}
    ${sw("auto_amort", "Автоматический расчёт амортизации", noAcc)}${sw("control_to", "Контроль сроков ТО и уведомления", noEd)}
    ${sw("no_doc_disposal", "Запрет списания без документа", noEd)}${sw("third_party", "Учёт стороннего оборудования", noEd)}</div>`;
  return `<div class="eqs-g2"><section class="eqs-card"><h3>${EQN.amort}Учёт и амортизация</h3><div class="eqs-mod">${sel("method", "Метод амортизации по умолчанию", r.methods, noAcc)}
      ${sw("auto_amort", "Автоматический расчёт амортизации", noAcc)}${sel("round", "Округление сумм", r.rounds, noEd)}
      ${acc ? `<label class="eqs-swr full"><span>Часы работы кресла в месяц<small>Норматив для кресло-часа и загрузки оборудования в «Аналитике»</small></span><input class="input num" type="number" min="1" max="744" id="eqChairH" value="${r.chair_hours}"></label>` : ""}
      ${sw("third_party", "Учёт стороннего оборудования", noEd)}</div></section>
    <section class="eqs-card"><h3>${EQX.cal}Контроль и уведомления</h3><div class="eqs-mod">${sw("control_to", "Контроль сроков ТО и уведомления", noEd)}
      <label class="eqs-swr full"><span>Предупреждать заранее, дней<small>Что наступит за это время, уже попадает в колокольчик</small></span><input class="input num" type="number" min="1" max="90" data-mod="to_days" value="${m.to_days}" ${edit ? "" : "disabled"}></label>
      ${sw("to_report", "ТО в отчёте за день", noEd)}${sw("no_doc_disposal", "Запрет списания без документа", noEd)}</div></section></div>`;
}
function eqModuleWire(el) {
  $$("[data-mod]", el).forEach(x => x.onchange = async () => {
    const v = x.type === "checkbox" ? x.checked : x.value;
    try {
      const m = await api.equipment_module_save({[x.dataset.mod]: v});
      EQS.refs.module = m; EQS.round = m.round; if (STK) STK.eq_module = m;
      toast("Сохранено"); stockTabsByRights(); refreshStatus(); eqBellDraw();
    } catch (e) { toast(errText(e), true); if (x.type === "checkbox") x.checked = !x.checked; }
  });
  const ch = $("#eqChairH", el); if (ch) ch.onchange = async () => { try { await api.equipment_settings_save({chair_hours: ch.value}); toast("Сохранено"); } catch (e) { toast(errText(e), true); } };
}

/** A reference in a dialog: a table of rows to change, add and remove. */
function eqListDlg(o) {
  const edit = o.edit !== false && can("equipment");
  const cell = (c, v) => {
    if (c.ro || !edit) return `<td class="${c.num ? "num " : ""}${c.ro ? "muted" : ""}">${c.fmt ? c.fmt(v) : esc(Array.isArray(v) ? v.join(", ") : (v ?? "") === "" ? "—" : v)}</td>`;
    if (c.type === "select") return `<td><select class="input" data-k="${c.k}">${Object.entries(c.opts).map(([k, t]) => `<option value="${esc(k)}" ${k === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></td>`;
    if (c.type === "chips") return `<td><div class="eqs-chips" data-k="${c.k}" data-chips="1">${c.opts.map(x => `<button type="button" class="${(v || []).includes(x) ? "on" : ""}" data-v="${esc(x)}">${esc(x)}</button>`).join("")}</div></td>`;
    if (c.type === "lines") return `<td><textarea class="input" data-k="${c.k}" data-lines="1" rows="3" placeholder="${esc(c.ph || "")}">${esc((v || []).join("\n"))}</textarea></td>`;
    return `<td class="${c.num ? "num" : ""}"><input class="input ${c.num ? "num" : ""}" data-k="${c.k}" ${c.num ? `type="number" min="0" max="${c.max || 9999}" step="1"` : `maxlength="${c.max || 120}"`} ${c.list ? `list="${c.list}"` : ""} value="${esc(v ?? "")}" placeholder="${esc(c.ph || "")}"></td>`;
  };
  const rows = o.rows.map(x => ({...x}));
  const row = (x, i) => `<tr data-i="${i}" class="${x.from_cards ? "eqs-fromc" : ""}">${o.cols.map(c => cell(c, x[c.k])).join("")}${edit && !o.fixed ? `<td><button class="linkbtn danger-t" data-del="1" ${o.locked && o.locked(x) ? `disabled title="${esc(o.locked(x))}"` : ""} title="Убрать">${EQX.x}</button></td>` : ""}</tr>`;
  const box = modal(`<div class="m-h"><h3>${esc(o.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">${o.hint ? `<div class="muted eqs-hint">${o.hint}</div>` : ""}
      <div class="eqs-etw"><table class="tbl compact eqs-et" id="eqLT"><thead><tr>${o.cols.map(c => `<th class="${c.num ? "num" : ""}">${c.t}</th>`).join("")}${edit && !o.fixed ? "<th></th>" : ""}</tr></thead><tbody>${rows.map(row).join("")}</tbody></table></div>
      ${rows.length ? "" : `<div class="muted eqs-hint" id="eqLEmpty">${o.empty || "Записей пока нет"}</div>`}${o.lists || ""}
      ${edit && !o.fixed ? `<div class="eqs-row"><button class="btn ghost small" id="eqLAdd">+ ${o.addT || "Строка"}</button></div>` : ""}<div class="auth-err" id="eqLErr"></div></div>
    <div class="m-f">${o.foot || '<span class="grow"></span>'}<button class="btn ghost" data-close>${edit && o.save ? "Отмена" : "Закрыть"}</button>${edit && o.save ? `<button class="btn" id="eqLOk">Сохранить</button>` : ""}</div>`, {wide: true});
  const wire = () => {
    $$("[data-del]", box).forEach(b => b.onclick = () => b.closest("tr").remove());
    $$("[data-chips] button", box).forEach(b => b.onclick = () => b.classList.toggle("on"));
  };
  wire();
  const read = () => $$("#eqLT tbody tr", box).map(tr => {
    const out = {...(rows[+tr.dataset.i] || {})};
    $$("[data-k]", tr).forEach(x => { out[x.dataset.k] = x.dataset.chips ? $$("button.on", x).map(b => b.dataset.v) : x.dataset.lines ? x.value.split("\n").map(s => s.trim()).filter(Boolean) : x.value; });
    return out;
  });
  const add = $("#eqLAdd", box);
  if (add) add.onclick = () => { const i = rows.length; rows.push({...(o.blank || {})}); $("#eqLT tbody", box).insertAdjacentHTML("beforeend", row(rows[i], i)); const em = $("#eqLEmpty", box); if (em) em.remove(); wire(); const f = $("#eqLT tbody tr:last-child [data-k]", box); if (f) f.focus(); };
  const ok = $("#eqLOk", box);
  if (ok) ok.onclick = async () => { try { await o.save(read()); closeModal(); toast("Сохранено"); EQS.refs = null; eqRefsTab(); } catch (e) { $("#eqLErr", box).textContent = errText(e); } };
  if (o.addNow && add) add.click();
  if (o.wire) o.wire(box);
  return box;
}
function eqRefEdit(k, addNow) {
  const r = EQS.refs, cats = r.categories.map(c => c.name);
  const catList = `<datalist id="eqLCats">${cats.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`;
  const life = n => n ? (n % 12 ? `${n} мес.` : `${n / 12} ${plural(n / 12, "год", "года", "лет")}`) : "—";
  const D = {
    cats: {title: "Виды оборудования", addT: "Категория", hint: "Категория не задаёт учёт: у каждой единицы в карточке свой способ — с амортизацией или количественный без амортизации. Норматив срока службы — подсказка в карточке.",
      cols: [{k: "name", t: "Категория", max: 100}, {k: "count", t: "Единиц", ro: 1, num: 1}, {k: "life", t: "Норматив, мес.", num: 1, max: 600}], rows: r.categories, blank: {name: "", count: 0, life: ""},
      locked: x => x.count ? "Есть оборудование этой категории" : "",
      save: rows => api.equipment_refs_save({categories: rows.map(x => x.name.trim()).filter(Boolean), life: Object.fromEntries(rows.filter(x => x.name.trim()).map(x => [x.name.trim(), x.life || 0]))})},
    models: {title: "Модели и производители", addT: "Модель", hint: "Список подсказывает производителя и модель в карточке и при поступлении. Серые строки — модели из карточек: при сохранении они войдут в справочник.",
      cols: [{k: "manufacturer", t: "Производитель", list: "eqLMf", max: 100}, {k: "model", t: "Модель", max: 100}, {k: "article", t: "Артикул", max: 60}, {k: "category", t: "Категория", list: "eqLCats", max: 100}, {k: "count", t: "Единиц", ro: 1, num: 1}],
      rows: r.models, blank: {count: 0}, lists: catList + `<datalist id="eqLMf">${r.manufacturers.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`,
      save: rows => api.equipment_ref_save("eq_models", rows.map(({manufacturer, model, article, category, id}) => ({id, manufacturer, model, article, category})))},
    groups: {title: "Инвентарные группы", addT: "Группа", hint: "Код группы — начало инвентарного номера: новая карточка категории из группы получит номер вида СТ-001, СТ-002… ОКОФ — код по классификатору основных фондов (для бухгалтерии).",
      cols: [{k: "code", t: "Код", ph: "СТ", max: 6}, {k: "name", t: "Группа", ph: "Стоматологическое оборудование", max: 120}, {k: "okof", t: "ОКОФ", ph: "330.32.50", max: 40}, {k: "categories", t: "Категории", type: "chips", opts: cats}, {k: "count", t: "Единиц", ro: 1, num: 1}],
      rows: r.groups, blank: {categories: [], count: 0}, save: rows => api.equipment_ref_save("eq_groups", rows)},
    works: {title: "Виды работ (ТО)", addT: "Вид работ", hint: "Подсказки в заявке на обслуживание: выбранный вид работ подставляется в описание.",
      cols: [{k: "name", t: "Вид работ", max: 120}, {k: "kind", t: "Тип заявки", type: "select", opts: r.req_kinds}], rows: r.works, blank: {kind: "service"},
      save: rows => api.equipment_ref_save("eq_works", rows)},
    regs: {title: "Регламенты обслуживания", addT: "Регламент", hint: "Регламент выбирают при добавлении в график ТО: он задаёт вид и периодичность, а его чек-лист отмечают, когда заявка по графику выполнена — отметки попадают в историю карточки.",
      cols: [{k: "name", t: "Регламент", max: 120}, {k: "kind", t: "Вид", type: "select", opts: r.plan_kinds}, {k: "every_months", t: "Раз в, мес.", num: 1, max: 120}, {k: "category", t: "Категория", list: "eqLCats", max: 100},
        {k: "checklist", t: "Чек-лист (пункт в строке)", type: "lines", ph: "Проверить давление\nЗаменить фильтр"}, {k: "plans", t: "В графике", ro: 1, num: 1}],
      rows: r.regs, blank: {kind: "service", every_months: 6, checklist: [], plans: 0}, lists: catList, locked: x => x.plans ? "Регламент стоит в графике ТО" : "",
      save: rows => api.equipment_ref_save("eq_regs", rows.map(({plans, ...x}) => x))},
    norms: {title: "Нормы амортизации", fixed: 1, hint: "Норматив срока службы по категории подставляется в новую карточку подсказкой; срок каждой единицы ставится в карточке. Метод — линейный: годовая норма = 100 % ÷ срок в годах.",
      cols: [{k: "name", t: "Категория", ro: 1}, {k: "count", t: "Единиц", ro: 1, num: 1}, {k: "life", t: "Срок, мес.", num: 1, max: 600}, {k: "y", t: "Срок", ro: 1}, {k: "m", t: "Метод", ro: 1}, {k: "rate", t: "Норма в год", ro: 1, num: 1}],
      rows: r.categories.map(c => ({...c, y: life(c.life), m: r.methods[r.module.method] || "Линейный", rate: c.life ? `${(1200 / c.life).toLocaleString("ru-RU", {maximumFractionDigits: 1})} %` : "—"})),
      save: rows => api.equipment_refs_save({life: Object.fromEntries(rows.map(x => [x.name, x.life || 0]))})},
    places: {title: "Места эксплуатации", fixed: 1, hint: "Кабинеты и помещения — это «Места хранения» склада. Кресло Dentist Plus в кабинете даёт наработку оборудованию кабинета: часы приёмов этого кресла («Аналитика → Эффективность использования»). Оборудование без кресла получает часы работы клиники.",
      cols: [{k: "name", t: "Место", ro: 1}, {k: "kind_title", t: "Вид", ro: 1}, {k: "chair", t: "Кресло Dentist Plus", list: "eqLCh", ph: "Кресло 1", max: 100}, {k: "count", t: "Оборудования", ro: 1, num: 1}],
      rows: r.places, lists: `<datalist id="eqLCh">${r.chairs.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`, empty: "Мест хранения пока нет — добавьте кабинеты в «Склад → Места хранения»",
      foot: `<button class="btn ghost" id="eqLPl">Все места хранения</button><span class="grow"></span>`,
      wire: box => { $("#eqLPl", box).onclick = () => { closeModal(); stockGo("stock", "places"); }; },
      save: async rows => { for (const x of rows) { const o = r.places.find(p => p.id === x.id); if (o && (o.chair || "") !== (x.chair || "").trim()) await api.equipment_place_chair(x.id, x.chair.trim()); } }},
    use: {title: "Типы использования", edit: false, hint: "Принадлежность задаёт учёт: собственность клиники и лизинг амортизируются и выбывают в финотчёте; аренда, имущество учредителя, врача и иное пользование — стороннее, без амортизации.",
      cols: [{k: "t", t: "Тип"}, {k: "a", t: "Учёт"}, {k: "n", t: "Единиц", num: 1}],
      rows: Object.entries(r.ownership).map(([k, t]) => ({t, a: r.off_books.includes(k) ? "Стороннее, без амортизации" : "Имущество клиники, с амортизацией", n: r.ownership_counts[k] || 0}))},
    reasons: {title: "Причины выбытия", addT: "Причина", hint: "Подсказки причины в акте выбытия (раздел «Выбытие и списание» и карточка).",
      cols: [{k: "name", t: "Причина", max: 150}, {k: "count", t: "Случаев", ro: 1, num: 1}], rows: r.disp_reasons, blank: {count: 0},
      save: rows => api.equipment_ref_save("eq_disp_reasons", rows.map(x => x.name))},
  };
  return eqListDlg({...D[k], addNow});
}

function eqRefsIO() {
  const box = modal(`<div class="m-h"><h3>Импорт и экспорт справочников</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted eqs-hint">Один файл со всеми справочниками и настройками раздела: виды оборудования и нормативы, модели, инвентарные группы, виды работ, регламенты с чек-листами, причины выбытия. Его можно перенести в другую клинику или сохранить как копию.</div>
      <div class="eqs-qa"><button id="ioEx">${EQX.down}<span>Экспорт в файл</span>${EQX.chev}</button>${can("equipment") ? `<button id="ioIm">${EQR.io}<span>Импорт из файла</span>${EQX.chev}</button>` : ""}</div><div class="auth-err" id="ioErr"></div></div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Закрыть</button></div>`);
  $("#ioEx", box).onclick = async () => { try { const x = await api.equipment_refs_export(); await saveDataUrl(`Справочники оборудования ${iso(new Date())}.json`, "data:application/json;base64," + btoa(unescape(encodeURIComponent(JSON.stringify(x, null, 1))))); } catch (e) { $("#ioErr", box).textContent = errText(e); } };
  const im = $("#ioIm", box);
  if (im) im.onclick = () => {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = ".json,application/json";
    inp.onchange = async () => {
      const f = inp.files && inp.files[0]; if (!f) return;
      try { const data = JSON.parse(await f.text()); if (!await ask("Заменить справочники раздела данными из файла?", {ok: "Заменить", cancel: "Отмена"})) return;
        const x = await api.equipment_refs_import(data); closeModal(); toast(`Загружено: ${x.imported.join(", ")}`); eqRefsTab(); }
      catch (e) { $("#ioErr", box).textContent = e instanceof SyntaxError ? "Файл повреждён или это не JSON" : errText(e); }
    };
    inp.click();
  };
}

function eqInfoDlg(title, html, foot = "") {
  return modal(`<div class="m-h"><h3>${title}</h3><button class="x" data-close>×</button></div><div class="m-b eqs-info">${html}</div>
    <div class="m-f">${foot || '<span class="grow"></span>'}<button class="btn ghost" data-close>Закрыть</button></div>`, {wide: true});
}
function eqGuide() {
  eqInfoDlg("Инструкция по учёту оборудования", `<ol class="eqs-steps2">
    <li><b>Поступление.</b> «Поступление» → документы поставщика → позиции → инвентарный номер, способ учёта и срок → ввод в эксплуатацию: кабинет и дата. Каждая единица получает карточку; оплату можно сразу записать в «Покупку оборудования».</li>
    <li><b>Карточка.</b> Категория, производитель и модель, серийный номер, место, ответственный, документы и фото. Деньги — стоимость, срок службы, амортизацию — видит и меняет сотрудник с правом «Бухгалтерия». Каждое изменение попадает в «Журнал действий» как «было → стало».</li>
    <li><b>Учёт.</b> С амортизацией (линейно, с месяца после ввода) или количественный без амортизации — для недорогого инструмента. Стороннее (аренда, имущество врача или учредителя) не амортизируется.</li>
    <li><b>Обслуживание.</b> График ТО, поверок и осмотров с регламентами и чек-листами; заявки на ремонт, ТО и диагностику. Медсестра сообщает о неисправности, менеджер берёт заявку в работу и закрывает с суммой.</li>
    <li><b>Перемещение.</b> Заявка → утверждение директором или учредителем → перемещение → подтверждение; место в карточке меняется само, акт — на печать.</li>
    <li><b>Инвентаризация.</b> «Инвентаризация → Оборудование»: по инвентарным номерам или QR-этикеткам.</li>
    <li><b>Выбытие.</b> Списание и утилизация — актом комиссии; продажа, передача, возврат владельцу — с документом-основанием. Остаточная стоимость считается на дату выбытия.</li></ol>`);
}
function eqInvGuide() {
  eqInfoDlg("Порядок проведения инвентаризации", `<ol class="eqs-steps2">
    <li><b>Комиссия.</b> Приказом руководителя — председатель и не меньше двух членов; материально ответственные лица присутствуют.</li>
    <li><b>Подготовка.</b> Распечатайте опись с QR («Реестр → Карточки → Печать описи») или инвентаризационную ведомость («Аналитика и отчёты → Отчёты»).</li>
    <li><b>Проверка.</b> По каждому кабинету: есть ли единица на месте, совпадают ли инвентарный и серийный номер, состояние. QR-этикетку можно сканировать телефоном.</li>
    <li><b>Отметки.</b> «Инвентаризация → Оборудование»: найдено или нет, где и в каком состоянии. Расхождения записываются в историю карточки.</li>
    <li><b>Итоги.</b> Недостача и излишки — в акт; неисправное — в заявку на ремонт или на выбытие.</li></ol>`,
  can("equipment") ? `<button class="btn" id="igGo">${EQX.check}Открыть инвентаризацию оборудования</button><span class="grow"></span>` : "");
  const b = $("#igGo"); if (b) b.onclick = () => { closeModal(); stockGo("inventory", "inv_eq"); };
}
function eqAmortCalc() {
  const box = eqInfoDlg("Методики амортизации: пример расчёта", `<div class="muted eqs-hint">Линейный метод: (стоимость − ликвидационная стоимость) ÷ срок службы в месяцах. Начисление — с месяца после ввода в эксплуатацию до конца срока или до выбытия.</div>
    <div class="grid3"><label class="fl">Стоимость, ₽<input class="input num" type="number" min="0" id="acP" value="1200000"></label><label class="fl">Ликвидационная, ₽<input class="input num" type="number" min="0" id="acS" value="0"></label>
      <label class="fl">Срок службы, мес.<input class="input num" type="number" min="1" max="600" id="acN" value="120"></label></div><div id="acOut"></div>`);
  const draw = () => {
    const p = +$("#acP", box).value || 0, s = Math.min(+$("#acS", box).value || 0, p), n = Math.max(1, Math.round(+$("#acN", box).value || 1)), base = p - s, mon = base / n;
    const yrs = Math.ceil(n / 12), rows = [];
    for (let y = 1; y <= Math.min(yrs, 12); y++) { const k = Math.min(12, n - (y - 1) * 12), acc = Math.min(base, mon * Math.min(n, y * 12)); rows.push(`<tr><td>${y}-й год</td><td class="num">${money(mon * k)}</td><td class="num">${money(acc)}</td><td class="num">${money(p - acc)}</td></tr>`); }
    $("#acOut", box).innerHTML = `<dl class="eqs-kpi"><dt>В месяц</dt><dd>${money(mon)}</dd><dt>В год</dt><dd>${money(mon * 12)}</dd><dt>Годовая норма</dt><dd>${(1200 / n).toLocaleString("ru-RU", {maximumFractionDigits: 2})} %</dd></dl>
      <table class="tbl compact"><thead><tr><th>Год</th><th class="num">Амортизация</th><th class="num">Накоплено</th><th class="num">Остаточная</th></tr></thead><tbody>${rows.join("")}</tbody></table>${yrs > 12 ? `<div class="muted eqs-hint">И ещё ${yrs - 12} ${plural(yrs - 12, "год", "года", "лет")}</div>` : ""}`;
  };
  $$("#acP,#acS,#acN", box).forEach(i => i.oninput = draw); draw();
}

/* ---- the templates of documents: a printed act filled from a card */
const EQ_TPL = [["in_service", "Акт о приёме-передаче и вводе в эксплуатацию"], ["tech", "Акт технического состояния"], ["card", "Инвентарная карточка учёта"],
  ["move", "Акт перемещения"], ["writeoff", "Акт о списании (бланк для комиссии)"]];
async function eqTemplates(tpl, eid) {
  const list = await api.equipment_list("", false);
  const box = modal(`<div class="m-h"><h3>Шаблоны документов</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted eqs-hint">Документ заполнится данными карточки; подписи и даты — от руки. Готовый подписанный документ сохраните в «Документы» карточки.</div>
      <div class="eqs-tpl">${EQ_TPL.map(([k, t]) => `<button data-t="${k}" class="${k === (tpl || "in_service") ? "on" : ""}">${EQX.doc}<span>${t}</span></button>`).join("")}</div>
      <label class="fl">Оборудование<select class="input" id="tpE">${list.map(e => `<option value="${esc(e.id)}" ${e.id === eid ? "selected" : ""}>${esc(e.name)}${e.inv_number ? " · " + esc(e.inv_number) : ""}</option>`).join("")}</select></label></div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="tpGo" ${list.length ? "" : "disabled"}>Печать</button></div>`, {wide: true});
  let cur = tpl || "in_service";
  $$("[data-t]", box).forEach(b => b.onclick = () => { cur = b.dataset.t; $$("[data-t]", box).forEach(x => x.classList.toggle("on", x === b)); });
  $("#tpGo", box).onclick = async () => { const e = await api.equipment($("#tpE", box).value); closeModal(); eqPrintTpl(cur, e); };
}
async function eqPrintTpl(k, e) {
  const c = (await ref()).clinic || {}, m = !!e.money, a = e.amort || {};
  const life = n => n ? (n % 12 ? `${n} мес.` : `${n / 12} ${plural(n / 12, "год", "года", "лет")}`) : "";
  const blank = "____________________";
  const row = (t, v) => `<tr><th style="width:38%;text-align:left">${t}</th><td>${v ? esc(v) : blank}</td></tr>`;
  const head = `${await clinicHead()}<div class="pr-approve">УТВЕРЖДАЮ<br>Руководитель ____________ ${esc(c.director || "")}<br>«___» ____________ 20__ г.</div>`;
  const obj = `<table>${row("Наименование", e.name)}${row("Инвентарный номер", e.inv_number)}${row("Производитель, модель", [e.manufacturer, e.model].filter(Boolean).join(" "))}${row("Заводской (серийный) номер", e.serial)}
    ${row("Категория", e.category)}${row("Место (кабинет)", e.location_name)}${row("Ответственный", e.responsible)}${m ? row("Первоначальная стоимость", e.price ? money(e.price) : "") : ""}</table>`;
  const T = {
    in_service: `<h2 style="text-align:center">АКТ № _____<br>о приёме-передаче и вводе в эксплуатацию объекта основных средств</h2><p style="text-align:center">«___» ____________ 20__ г.</p>${obj}
      <table>${row("Дата покупки", e.purchase_date ? fmtDate(e.purchase_date) : "")}${row("Дата ввода в эксплуатацию", e.in_service ? fmtDate(e.in_service) : "")}${m ? row("Срок полезного использования", life(e.useful_months)) + row("Метод амортизации", e.useful_months ? "Линейный" : "") : ""}${row("Гарантия до", e.warranty_until ? fmtDate(e.warranty_until) : "")}</table>
      <p>Объект проверен: комплектность и техническое состояние соответствуют документации производителя, объект пригоден к эксплуатации и введён в эксплуатацию.</p>${signLines([{role: "Сдал"}, {role: "Принял"}, {role: "Председатель комиссии"}, {role: "Член комиссии"}])}`,
    tech: `<h2 style="text-align:center">АКТ № _____<br>технического состояния оборудования</h2><p style="text-align:center">«___» ____________ 20__ г.</p>${obj}
      <table>${row("Дата ввода в эксплуатацию", e.in_service ? fmtDate(e.in_service) : "")}${row("Текущее состояние в учёте", e.condition_title || "")}${m && a.on ? row("Износ (амортизация)", `${a.percent} %`) : ""}</table>
      <p><b>Результаты осмотра:</b></p><p>${"_".repeat(95)}</p><p>${"_".repeat(95)}</p><p><b>Заключение:</b> ☐ исправно, пригодно к эксплуатации ☐ требует ремонта ☐ ремонт экономически нецелесообразен, подлежит списанию</p>
      ${signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Член комиссии"}, {role: "Сервисный специалист"}])}`,
    card: `<h2 style="text-align:center">ИНВЕНТАРНАЯ КАРТОЧКА<br>учёта объекта основных средств № ${esc(e.inv_number || "")}</h2>${obj}
      <table>${row("Принадлежность", e.ownership_title)}${row("Способ учёта", e.accounting_title)}${row("Дата покупки", e.purchase_date ? fmtDate(e.purchase_date) : "")}${row("Дата ввода", e.in_service ? fmtDate(e.in_service) : "")}
        ${m ? row("Срок полезного использования", life(e.useful_months)) + row("Амортизация в месяц", a.on ? money(a.monthly) : "") + row("Накопленная амортизация", a.on ? money(a.accumulated) : "") + row("Остаточная стоимость", a.on ? money(a.residual) : "") : ""}</table>
      <h3>Движение и обслуживание</h3><table><tr><th>Дата</th><th>Событие</th><th>Описание</th></tr>${(e.events || []).slice(0, 25).map(v => `<tr><td>${fmtDate(v.date)}</td><td>${esc(v.kind_title)}</td><td>${esc(v.text || "")}</td></tr>`).join("")}</table>
      ${signLines([{role: "Карточку заполнил"}, {role: "Главный бухгалтер"}])}`,
    move: `<h2 style="text-align:center">АКТ № _____<br>о внутреннем перемещении объекта основных средств</h2><p style="text-align:center">«___» ____________ 20__ г.</p>${obj}
      <table>${row("Откуда", e.location_name)}${row("Куда", "")}${row("Основание", "")}</table>${signLines([{role: "Сдал"}, {role: "Принял"}, {role: "Утвердил"}])}`,
    writeoff: `<h2 style="text-align:center">АКТ № _____<br>о списании объекта основных средств</h2><p style="text-align:center">«___» ____________ 20__ г.</p>
      <p>Комиссия в составе: председатель — ${blank}; члены комиссии — ${blank}, ${blank} — осмотрела указанный ниже объект.</p>${obj}
      <table>${row("Дата ввода в эксплуатацию", e.in_service ? fmtDate(e.in_service) : "")}${m && a.on ? row("Накопленная амортизация", money(a.accumulated)) + row("Остаточная стоимость", money(a.residual)) : ""}${row("Причина списания", "")}</table>
      <p><b>Заключение комиссии:</b> ${"_".repeat(80)}</p>${signLines([{role: "Председатель комиссии"}, {role: "Член комиссии"}, {role: "Член комиссии"}])}`,
  };
  $("#printArea").innerHTML = head + T[k];
  window.print();
}

/* ---- «Настройки системы», «Пользователи и права», «Интеграции», «Журнал изменений» */
function eqRefsSys(r) {
  const el = $("#eqRefBody");
  el.innerHTML = eqModuleRows(r, false);
  eqModuleWire(el);
}
async function eqRefsUsers() {
  const el = $("#eqRefBody"), x = await api.equipment_rights();
  const cell = on => on ? `<span class="eqs-yes">${EQX.ok}</span>` : `<span class="muted">—</span>`;
  const head = `<tr><th></th>${x.keys.map(k => `<th class="num" title="${esc(x.titles[k])}">${esc({equipment: "Учёт", equipment_approve: "Согласование", stock_ops: "Медсестра", stock_view: "Просмотр", accounting: "Деньги"}[k])}</th>`).join("")}</tr>`;
  el.innerHTML = `<section class="eqs-card"><h3>${EQR.user}Кто что может в разделе</h3><dl class="eqs-dl">${x.keys.map(k => `<dt>${esc({equipment: "Учёт", equipment_approve: "Согласование", stock_ops: "Медсестра", stock_view: "Просмотр", accounting: "Деньги"}[k])}</dt><dd>${esc(x.titles[k])}${{equipment: " — карточки, поступление, ремонт, перемещения, выбытие, справочники.", equipment_approve: " — согласует закупки и утверждает перемещения.", stock_ops: " — видит оборудование, сообщает о неисправности, подтверждает наличие.", stock_view: " — видит реестр и карточки без денег.", accounting: " — стоимость, амортизация, остаточная стоимость, суммы работ."}[k]}</dd>`).join("")}</dl></section>
    <div class="eqs-g2"><section class="eqs-card eqs-tcard"><h3 class="eqs-tch">Должности</h3><table class="tbl eqs-reg"><thead>${head}</thead><tbody>${x.positions.map(p => `<tr><td><b>${esc(p.title)}</b></td>${x.keys.map(k => `<td class="num">${cell(p.perms[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></section>
      <section class="eqs-card eqs-tcard"><h3 class="eqs-tch">Сотрудники с доступом</h3>${x.users.length ? `<table class="tbl eqs-reg"><thead>${head}</thead><tbody>${x.users.map(u => `<tr><td><b>${esc(u.name)}</b><small class="muted" style="display:block">${esc(u.position)}${u.own ? " · свои права" : ""}</small></td>${x.keys.map(k => `<td class="num">${cell(u.perms[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>` : `<div class="empty"><b>Входов по паролю пока нет</b><span>Права действуют, когда сотрудники входят под своими логинами</span></div>`}</section></div>
    ${can("staff") ? `<div class="eqs-row"><span class="grow"></span><button class="btn" id="eqToStaff">${EQR.user}Изменить в «Сотрудниках»</button></div>` : `<div class="muted eqs-hint">Права меняет директор в разделе «Сотрудники».</div>`}`;
  const b = $("#eqToStaff"); if (b) b.onclick = () => show("staff");
}
async function eqRefsInt() {
  const el = $("#eqRefBody"), x = await api.equipment_integrations();
  const st = (ok, t) => `<span class="eqs-st ${ok ? "ok" : ""}">${ok ? EQX.ok : EQX.clock}${esc(t)}</span>`;
  const card = (ic, t, status, text, btn) => `<section class="eqs-card eqs-intc"><h3>${ic}${t}</h3>${status}<p class="muted">${text}</p>${btn ? `<button class="btn ghost small" data-go="${btn[0]}">${btn[1]} ${EQX.chev}</button>` : ""}</section>`;
  el.innerHTML = `<div class="eqs-intg">
    ${card(EQR.chair, "Dentist Plus: кресла и приёмы", st(x.dp.linked > 0, x.dp.linked ? `Кресла привязаны: ${x.dp.linked} из ${x.dp.places} мест` : "Кресла не привязаны"), `За 30 дней — ${x.dp.visits} приёмов в ${x.dp.chairs} ${plural(x.dp.chairs, "кресле", "креслах", "креслах")}. Часы приёмов кресла — наработка оборудования его кабинета в «Аналитике».`, can("equipment") ? ["places", "Привязать кресла"] : null)}
    ${card(EQN.amort, "Финансы: ОПиУ", st(x.pnl.amort, x.pnl.amort ? "Амортизация в ОПиУ" : "Амортизация не в ОПиУ"), `Покупки оборудования — отдельная статья «Покупка оборудования» (записей: ${x.pnl.capex}); в прибыль оборудование идёт амортизацией и выбытием.`, can("accounting") ? ["pnl", "Бухгалтерия"] : null)}
    ${card(EQX.cal, "Отчёт за день: Telegram и почта", st(x.report.channels.length > 0, x.report.channels.length ? `Отправляется: ${x.report.channels.map(c => c === "tg" ? "Telegram" : "почта").join(", ")}` : "Не настроен"), x.report.to_report ? "Просроченное и ближайшее ТО уходит владельцу вместе с отчётом за день." : "Строка о ТО в отчёте за день выключена в «Настройках системы».", can("settings") ? ["report", "Настроить отчёт"] : null)}
    ${card(EQX.qr, "Телефон склада и QR-этикетки", st(!!x.phone.url, x.phone.url ? "Подключён" : "Не подключён"), x.phone.url ? `QR-этикетка ведёт в карточку на телефоне: ${esc(x.phone.url)}` : "QR-этикетка содержит инвентарный номер текстом: сканер или камера телефона находят карточку по номеру.", null)}
    ${card(EQX.down, "Excel", st(x.excel, x.excel ? "Доступно" : "Нет права «Выгрузка в Excel»"), "Реестр, амортизация, журнал действий, документы и отчёты раздела выгружаются в Excel кнопкой над таблицей.", null)}</div>`;
  $$("[data-go]", el).forEach(b => b.onclick = () => ({places: () => eqRefEdit("places"), pnl: () => show("accounting"),
    report: () => { show("settings"); setTimeout(() => settingsGo("dayRepPanel"), 80); }})[b.dataset.go]());
}
async function eqRefsLog() {
  const el = $("#eqRefBody"), x = await api.equipment_log({kind: "settings"});
  el.innerHTML = `<section class="eqs-card eqs-tcard">${x.rows.length ? `<table class="tbl eqs-reg" id="eqRlT"><thead><tr><th>Дата и время</th><th>Сотрудник</th><th>Что</th><th>Изменения</th></tr></thead><tbody>${x.rows.map(v => `<tr>
      <td>${fmtDT(v.created_at || v.date)}</td><td>${esc(v.user_name || "—")}</td><td><b>${esc((v.data && v.data.object) || "Настройки")}</b><small class="muted" style="display:block">${esc((v.data && v.data.module) || "")}</small></td>
      <td class="eqs-wraptd">${((v.data && v.data.changes) || []).map(c => `<div>${esc(c.t)}: <span class="muted">${esc(c.old)}</span> → <b>${esc(c.new)}</b></div>`).join("") || esc(v.text)}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty"><b>Изменений ещё не было</b><span>Здесь появятся правки справочников и настроек раздела: кто, когда, что было и что стало</span></div>`}</section>
    ${x.rows.length ? `<div class="eqs-row"><span class="grow"></span><button class="btn ghost" data-xls="#eqRlT" data-xls-name="Журнал изменений справочников оборудования">${EQX.down}Excel</button></div>` : ""}`;
}
