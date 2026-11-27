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
  const [r, list] = await Promise.all([api.equipment_requests(EQS.rqYear), api.equipment_list("", false)]);
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
      <label class="fl">Что сделано<input class="input" id="rdR" value="${esc(x.description)}"></label><div class="auth-err" id="rdE"></div>
      <div class="muted eqs-hint">Запись попадёт в историю карточки с суммой. ${x.kind === "repair" ? "Оборудование вернётся в работу и станет «Исправно»." : x.plan_id ? "Следующая дата по графику ТО сдвинется на период." : ""}</div></div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="rdOk">Выполнено</button></div>`);
  $("#rdOk", box).onclick = async () => { try { await api.equipment_request_status(x.id, "done", {date: $("#rdD").value, cost: $("#rdC").value, result: $("#rdR").value}); closeModal(); toast("Выполнено"); eqRequestsTab(); } catch (e) { $("#rdE").textContent = errText(e); } };
}
async function eqPlansDlg(list) {
  const plans = await api.equipment_plans(), refs = EQS.refs || (EQS.refs = await api.equipment_refs()), edit = can("equipment");
  const box = modal(`<div class="m-h"><h3>График ТО и регламенты</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="muted eqs-hint">Плановое ТО, поверка и технический осмотр с периодичностью. «Создать заявку» по строке графика — после её выполнения следующая дата сдвинется на период.</div>
      <table class="tbl compact"><thead><tr><th>Оборудование</th><th>Вид</th><th class="num">Раз в, мес.</th><th>Следующая дата</th><th>Примечание</th><th></th></tr></thead><tbody>${plans.map(p => `<tr data-p="${esc(p.id)}"><td>${esc(p.equipment_name)} <small class="muted">${esc(p.inv_number)}</small></td><td>${esc(p.kind_title)}</td><td class="num">${p.every_months}</td><td>${fmtDate(p.next_date)}</td><td class="muted">${esc(p.note || "")}</td>
        <td>${edit ? `<button class="linkbtn" data-req="${esc(p.id)}">заявка</button> <button class="linkbtn danger-t" data-del="${esc(p.id)}">убрать</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">Регламентов пока нет</td></tr>`}</tbody></table>
      ${edit ? `<h4 class="sub-h">Добавить в график</h4><div class="grid3"><label class="fl">Оборудование<select class="input" id="plE">${list.map(e => `<option value="${esc(e.id)}">${esc(e.name)}${e.inv_number ? " " + esc(e.inv_number) : ""}</option>`).join("")}</select></label>
        <label class="fl">Вид<select class="input" id="plK">${Object.entries(refs.plan_kinds).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>
        <label class="fl">Периодичность, мес.<input class="input num" type="number" min="1" max="120" id="plN" value="6"></label>
        <label class="fl">Следующая дата<input class="input" type="date" id="plD"></label><label class="fl" style="grid-column:span 2">Примечание<input class="input" id="plC" placeholder="например: по паспорту производителя"></label></div><div class="auth-err" id="plErr"></div>` : ""}</div>
    <div class="m-f"><span class="grow"></span><button class="btn ghost" data-close>Закрыть</button>${edit ? `<button class="btn" id="plOk">Добавить</button>` : ""}</div>`, {wide: true});
  const ok = $("#plOk", box); if (ok) ok.onclick = async () => { try { await api.equipment_plan_save({equipment_id: $("#plE").value, kind: $("#plK").value, every_months: $("#plN").value, next_date: $("#plD").value, note: $("#plC").value}); closeModal(); toast("Добавлено в график"); eqRequestsTab().then(() => eqPlansDlg(list)); } catch (e) { $("#plErr").textContent = errText(e); } };
  $$("[data-del]", box).forEach(b => b.onclick = async () => { await api.equipment_plan_delete(b.dataset.del); closeModal(); eqRequestsTab().then(() => eqPlansDlg(list)); });
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
          <label class="fl">Основание (документ)<input class="input" id="dsBasis" placeholder="Акт технического состояния № 14"></label>
          <div class="eqs-span2 eqs-form2" id="dsCom"><label class="fl">Председатель комиссии *<input class="input" id="dsC1"></label><label class="fl">Член комиссии *<input class="input" id="dsC2"></label></div>
          ${mon ? `<label class="fl" id="dsAmW" hidden>Сумма продажи, ₽<input class="input num" type="number" min="0" step="any" id="dsAmount"></label>` : ""}</div>
        <datalist id="dsReasons">${EQ_DISP_REASONS.map(x => `<option value="${esc(x)}">`).join("")}</datalist>
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
