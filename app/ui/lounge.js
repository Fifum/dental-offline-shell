"use strict";
/* 3.9 «Лаунж»: what makes the program easier to learn and quicker at the front desk. Loaded last; it only wraps
   functions of app.js and adds to the page, so every screen keeps working without it.
   - menu groups hide when none of their sections is allowed
   - «Следующий пациент» above today's schedule: who comes next, warnings, «Пришёл» in one click, counts of the day
   - the visit panel docks to the right of the schedule instead of covering it; the chosen visit is outlined
   - Ctrl+K finds patients, sections and actions («записать», «оплата», «новый пациент»), arrows + Enter
   - keys: F2 record a patient, F4 new patient, Alt+1…6 sections, F1 the list of keys
   - short hints on the main screens for new staff, closed with one click, can be shown again in Settings */
(() => {
  const app = document.querySelector(".app");
  const store = {
    get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage off */ } },
    del: k => { try { localStorage.removeItem(k); } catch (e) { /* storage off */ } },
  };
  const norm = s => String(s || "").toLowerCase().replace(/ё/g, "е");
  const SVG = {
    cal: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
    pat: '<svg viewBox="0 0 24 24"><circle cx="10" cy="8" r="4"/><path d="M3 20c1-4 3.5-6 7-6 1.6 0 3 .4 4.1 1.2M18 14v6M15 17h6"/></svg>',
    cash: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M7 15h3"/></svg>',
    wait: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    dp: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h10M4 17h7"/><path d="m15 17 2 2 4-4"/></svg>',
    key: '<svg viewBox="0 0 24 24"><rect x="2.5" y="6.5" width="19" height="11" rx="2.5"/><path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M7.5 14h9"/></svg>',
    moon: '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>',
    go: '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    set: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>',
    tip: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.2h5c0-.9.4-1.7 1.1-2.2A6 6 0 0 0 12 3z"/></svg>',
  };
  const typing = () => /INPUT|SELECT|TEXTAREA/.test((document.activeElement || {}).tagName || "") || (document.activeElement || {}).isContentEditable;
  const modalOpen = () => !$("#modal").hidden || !!document.querySelector(".ask-wrap");

  /* ------------------------------------------------------------- menu groups */
  function syncNavGroups() {
    $$(".rail .nav-g").forEach(h => {
      let n = h.nextElementSibling, any = false;
      for (; n && !n.classList.contains("nav-g"); n = n.nextElementSibling) if (n.classList.contains("nav") && !n.hidden) any = true;
      if (h.hidden === any) h.hidden = !any;  // only on change: the observer below would loop otherwise
    });
  }
  new MutationObserver(syncNavGroups).observe($(".rail nav"), {subtree: true, attributes: true, attributeFilter: ["hidden"]});
  syncNavGroups();

  /* ------------------------------------------------------- next patient card */
  const fmtIn = m => m <= 0 ? (m > -10 ? "сейчас" : `опаздывает на ${-m} мин`) : m < 60 ? `через ${m} мин` : `через ${Math.floor(m / 60)} ч ${m % 60 ? (m % 60) + " мин" : ""}`.trim();
  let nextFor = null, nextInfo = null;
  async function renderNext() {
    const el = $("#nextCard");
    const today = iso(new Date());
    if (!el || S.view !== "schedule" || S.day !== today || !ME || store.get("dd.nextHide") === today) { if (el) el.hidden = true; return; }
    const all = ((S.dayData || {}).visits || []).filter(v => (v.start || "").slice(0, 10) === today && (S.by === "chair" || !S.hiddenDocs.has(v.doctor_id || "_")));
    if (!all.length) { el.hidden = true; return; }
    const now = nowLocal(), nowM = mins(now);
    const kind = v => stClass(v.status);
    const come = all.filter(v => kind(v) === "st-come").length, done = all.filter(v => kind(v) === "st-done").length;
    const waiting = all.filter(v => (kind(v) === "" || kind(v) === "st-ok") && mins(v.end || v.start) > nowM - 1)
      .sort((a, b) => a.start.localeCompare(b.start));
    const stats = `<div class="nc-stats"><button title="Отмечены «Пришёл» или «В кресле»"><b>${come}</b>в клинике</button><button title="Ещё не пришли сегодня"><b>${waiting.length}</b>ожидаем</button><button title="Приём завершён"><b>${done}</b>завершено</button></div>`;
    const x = `<button class="nc-x" id="ncX" title="Скрыть до завтра">×</button>`;
    const v = waiting[0];
    if (!v) {
      el.className = "next-card done";
      el.innerHTML = `<div class="nc-who"><b>На сегодня больше никого не ждём</b><span>Все записанные пациенты пришли, приняты или отменены.</span></div>${stats}${x}`;
      el.hidden = false; bindX(el); return;
    }
    if (nextFor !== v.id) { nextFor = v.id; nextInfo = null; api.visit(v.id).then(info => { if (nextFor === v.id) { nextInfo = info; renderNext(); } }).catch(() => {}); }
    const info = nextInfo || {};
    const flags = [...(info.allergies || []).map(a => `<span class="nc-flag">Аллергия: ${esc(a)}</span>`),
      info.conflict_text ? `<span class="nc-flag w">Двойная запись</span>` : "", info.local ? `<span class="nc-flag w">Изменено в программе</span>` : ""].join("");
    const canSt = canAny("schedule_edit", "medcard_edit");
    el.className = "next-card";
    el.innerHTML = `<div class="nc-tm">${hm(v.start)}<small>${esc(fmtIn(mins(v.start) - nowM))}</small></div>
      <div class="nc-who"><b id="ncName" title="Открыть запись">${esc(v.patient_name || "Пациент")}</b>
        <span>${v.doctor_name ? "к " + esc(v.doctor_name) : ""}${v.chair ? ", " + esc(v.chair) : ""}${v.title ? " · " + esc(v.title) : ""} · <span class="pill ${kind(v)}">${esc(v.status || "Записан")}</span></span>
        ${flags ? `<div class="nc-flags">${flags}</div>` : ""}</div>
      <div class="nc-acts">${canSt ? `<button class="btn" id="ncCame" title="Отметить, что пациент пришёл">Пришёл</button>` : ""}<button class="btn ghost" id="ncOpen">Открыть запись</button></div>
      ${stats}${x}`;
    el.hidden = false;
    $("#ncName", el).onclick = () => openVisit(v.id);
    $("#ncOpen", el).onclick = () => openVisit(v.id);
    const came = $("#ncCame", el);
    if (came) came.onclick = () => busy(came, async () => { await api.set_visit_status(v.id, "Пришёл"); toast(`${v.patient_name || "Пациент"}: пришёл`); afterChange(); });
    bindX(el);
  }
  function bindX(el) { $("#ncX", el).onclick = () => { store.set("dd.nextHide", iso(new Date())); el.hidden = true; toast("Карточка «Следующий пациент» скрыта до завтра"); }; }
  setInterval(() => { if (S.view === "schedule") renderNext(); }, 30000);

  /* ------------------------------------------- the visit panel beside the grid */
  let selId = null;
  const markSel = () => $$("#grid .ev").forEach(e => e.classList.toggle("sel", !!selId && e.dataset.id === selId));
  const _loadDay = window.loadDay;
  window.loadDay = async function () { const r = await _loadDay.apply(this, arguments); markSel(); renderNext(); return r; };
  const _openVisit = window.openVisit;
  window.openVisit = async function (id) {
    await _openVisit.apply(this, arguments);
    if (S.view === "schedule") { selId = id; app.classList.add("insp-docked"); markSel(); }
  };
  const _closeDrawer = window.closeDrawer;
  window.closeDrawer = function () { _closeDrawer.apply(this, arguments); app.classList.remove("insp-docked"); selId = null; markSel(); };

  /* -------------------------------------------------------- views and hints */
  const HINTS = {
    schedule: {at: () => $("#nextCard"), text: "Щёлкните по записи: справа откроется панель, где можно отметить приход, принять оплату и заполнить медкарту. Чтобы записать пациента, щёлкните по свободному времени или нажмите <b>F2</b>. Цвет записи показывает её статус."},
    patients: {at: () => $("#view-patients .search-row"), text: "Найдите пациента по фамилии, телефону или номеру карты. Поиск в верхней строке (<b>Ctrl+K</b>) работает из любого раздела и понимает действия: «записать», «оплата», «новый пациент»."},
    cash: {at: () => $("#cashBody"), text: "Здесь оплаты за день и кассовая смена. Оплату удобнее принимать прямо из записи («Счёт и оплата») или из карточки пациента («Принять оплату»)."},
    settings: {at: () => $("#view-settings .set-wrap"), text: "Разделы настроек слева. Не знаете, где нужная настройка? Начните вводить слово в поиске справа вверху: «касса», «пароль», «планшет»."},
    patient: {at: () => $("#patientCard .phead2"), after: true, text: "Долг и бонусы видны в шапке карточки, аллергии и замечания сразу под ней. «Принять оплату» открывает неоплаченный счёт, «Записать» создаёт запись на приём. Ниже вкладки: визиты, формула, лечения, оплаты, документы."},
  };
  function showHint(view) {
    $$(".hint-bar").forEach(h => h.remove());
    const h = HINTS[view];
    if (!h || store.get("dd.hint." + view)) return;
    const at = h.at(); if (!at || !at.parentNode) return;
    const bar = document.createElement("div");
    bar.className = "hint-bar";
    bar.innerHTML = `${SVG.tip}<span>${h.text}</span><button class="hb-x" title="Больше не показывать">Понятно</button>`;
    $(".hb-x", bar).onclick = () => { store.set("dd.hint." + view, "1"); bar.remove(); };
    at.parentNode.insertBefore(bar, h.after ? at.nextSibling : at);
  }
  const _show = window.show;
  window.show = function (view) {
    if (view !== "schedule" && app.classList.contains("insp-docked")) closeDrawer();
    _show.apply(this, arguments);
    if (S.view !== "schedule") $("#nextCard").hidden = true;
    if (S.view !== "patient") showHint(S.view);
  };
  const _renderPatient = window.renderPatient;
  window.renderPatient = function () { const r = _renderPatient.apply(this, arguments); showHint("patient"); return r; };
  const resetHints = () => {
    Object.keys(HINTS).forEach(k => store.del("dd.hint." + k)); store.del("dd.nextHide");
    showHint(S.view); renderNext();
    const m = $("#hintsMsg"); if (m) { m.className = "msg ok"; m.textContent = "Подсказки снова включены"; }
  };

  /* ------------------------------------------------------------ the keys */
  const SECTION_KEYS = ["schedule", "patients", "cash", "marketing", "lab", "stock"];
  function keysHelp() {
    const rows = [
      ["Ctrl K", "Поиск: пациент, раздел или действие («записать», «оплата»)"],
      ["F2", "Записать пациента на приём"],
      ["F4", "Новый пациент"],
      ["Alt 1 … 6", "Расписание, Пациенты, Касса, CRM, Лаборатория, Склад"],
      ["← →", "Предыдущий и следующий день в расписании"],
      ["↑ ↓ Enter", "Выбор в списке поиска"],
      ["Esc", "Закрыть окно или панель записи, из карточки — назад"],
      ["F1", "Этот список"],
    ];
    modal(`<div class="m-h"><h3>Горячие клавиши</h3><button class="x" data-close>×</button></div><div class="m-b">
      <table class="keys-tbl">${rows.map(([k, t]) => `<tr><td>${k.split(" ").map(x => x === "…" ? "…" : `<kbd>${esc(x)}</kbd>`).join(" ")}</td><td>${esc(t)}</td></tr>`).join("")}</table></div>
      <div class="m-f"><button class="btn" data-close>Понятно</button></div>`);
  }
  function newVisit() {
    if (!can("schedule_edit")) return;
    if (S.view !== "schedule") show("schedule");
    $("#newVisitBtn").click();
  }
  document.addEventListener("keydown", e => {
    if (!ME || !$("#authScreen").hidden) return;
    if (e.key === "F1") { e.preventDefault(); if (!modalOpen()) keysHelp(); return; }
    if (modalOpen()) return;
    if (e.key === "F2") { e.preventDefault(); newVisit(); return; }
    if (e.key === "F4") { e.preventDefault(); if (can("patients_edit")) openNewPatient(); return; }
    if (e.altKey && !e.ctrlKey && /^Digit[1-6]$/.test(e.code)) {
      const v = SECTION_KEYS[+e.code.slice(5) - 1];
      if (v && canView(v)) { e.preventDefault(); show(v); }
    }
  });

  /* ---------------------------------------------------- Ctrl+K: search and do */
  const sectionCmds = () => $$(".rail .nav[data-view]").filter(b => !b.hidden).map(b => ({
    g: "Разделы", ic: b.querySelector("svg") ? b.querySelector("svg").outerHTML : SVG.go, t: $("span", b) ? $("span", b).textContent : b.title,
    k: b.title, run: () => show(b.dataset.view)}));
  const actionCmds = () => [
    {t: "Записать пациента на приём", k: "записать запись прием визит новая запись", kb: "F2", ic: SVG.cal, ok: () => can("schedule_edit"), run: newVisit},
    {t: "Новый пациент", k: "новый пациент добавить карточку завести", kb: "F4", ic: SVG.pat, ok: () => can("patients_edit"), run: () => openNewPatient()},
    {t: "Касса: оплаты и смена за день", k: "оплата оплатить касса деньги чек смена расход принять оплату", ic: SVG.cash, ok: () => canView("cash"), run: () => show("cash")},
    {t: "Лист ожидания", k: "ожидание лист ждут освободится", ic: SVG.wait, ok: () => canAny("schedule_view", "schedule_edit"), run: () => { if (S.view !== "schedule") show("schedule"); $("#waitBtn").click(); }},
    {t: "Перенести изменения в Dentist Plus", k: "перенос dentist plus дентист dp", ic: SVG.dp, ok: () => canView("journal"), run: () => show("journal")},
    {t: "Сменить тему: светлая или тёмная", k: "тема темная светлая ночь оформление", ic: SVG.moon, ok: () => !!window.DDTheme,
      run: () => DDTheme.set(DDTheme.isDark() ? "light" : "dark", ME && ME.login)},
    {t: "Горячие клавиши", k: "клавиши горячие помощь справка", kb: "F1", ic: SVG.key, run: keysHelp},
  ].filter(c => !c.ok || c.ok()).map(c => ({...c, g: "Действия"}));
  const match = (c, words) => { const hay = norm(c.t + " " + (c.k || "")); return words.every(w => hay.includes(w)); };

  let gsItems = [], gsSel = 0, gsSeq = 0;
  function drawDrop(q, pats) {
    const words = norm(q).split(/\s+/).filter(Boolean);
    let acts = actionCmds(), secs = [];
    if (words.length) { acts = acts.filter(c => match(c, words)).slice(0, 4); secs = sectionCmds().filter(c => match(c, words)).slice(0, 4); }
    else acts = acts.slice(0, 5);
    const patItems = (pats || []).map(p => ({g: "Пациенты", pat: p, run: () => openPatient(p.id, S.view === "patient" ? S.prevView : S.view)}));
    const extra = [];
    if (words.length && q.length >= 3 && canView("settings")) extra.push({g: "Настройки", ic: SVG.set, t: `Найти «${q}» в настройках`, run: () => { show("settings"); const i = $("#setSearch"); i.value = q; i.dispatchEvent(new Event("input")); i.focus(); }});
    if (words.length && pats && !pats.length && can("patients_edit")) extra.unshift({g: "Действия", ic: SVG.pat, t: `Новый пациент «${q}»`, run: () => openNewPatient(q)});
    gsItems = [...patItems, ...acts, ...secs, ...extra];
    if (!gsItems.length) { $("#gDrop").innerHTML = `<div class="muted" style="padding:10px 12px">${pats ? "Ничего не нашли. Проверьте написание или поищите по телефону." : "Ищем…"}</div>`; $("#gDrop").hidden = false; return; }
    gsSel = Math.min(gsSel, gsItems.length - 1);
    let html = "", last = "";
    gsItems.forEach((it, i) => {
      if (it.g !== last) { html += `<div class="gs-g">${esc(it.g)}</div>`; last = it.g; }
      if (it.pat) { const p = it.pat;
        html += `<div class="pp-row" data-i="${i}"><span class="av">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b><small>${esc(p.phone || "")}${p.birth ? " · " + fmtDate(p.birth) : ""}${p.next_visit ? " · визит " + fmtDT(p.next_visit) : ""}</small></span></div>`;
      } else html += `<div class="pp-row cmd" data-i="${i}">${it.ic || SVG.go}<span><b>${esc(it.t)}</b></span>${it.kb ? `<kbd class="kb">${esc(it.kb)}</kbd>` : ""}</div>`;
    });
    if (words.length && pats === null) html += `<div class="muted" style="padding:6px 12px 9px;font-size:12px">Ищем пациентов…</div>`;
    $("#gDrop").innerHTML = html;
    $("#gDrop").hidden = false;
    $$("#gDrop .pp-row").forEach(r => {
      r.onmousedown = e => e.preventDefault();  // keep the focus in the field until the click lands
      r.onclick = () => pick(+r.dataset.i);
      r.onmousemove = () => { if (gsSel !== +r.dataset.i) { gsSel = +r.dataset.i; paintSel(); } };
    });
    paintSel();
  }
  function paintSel() { $$("#gDrop .pp-row").forEach(r => r.classList.toggle("sel", +r.dataset.i === gsSel)); }
  function pick(i) {
    const it = gsItems[i]; if (!it) return;
    $("#gDrop").hidden = true; $("#gSearch").blur();
    if (!it.pat) $("#gSearch").value = "";
    it.run();
  }
  async function gSearchNew() {
    const q = $("#gSearch").value.trim(), seq = ++gsSeq;
    gsSel = 0;
    if (!q) { drawDrop("", []); return; }
    drawDrop(q, null);
    let pats = [];
    try { pats = (await api.search(q)).slice(0, 6); } catch (e) { pats = []; }
    if (seq !== gsSeq || $("#gSearch").value.trim() !== q) return;
    gsSel = 0; drawDrop(q, pats);
  }
  window.gSearch = gSearchNew;
  const gs = $("#gSearch");
  gs.onfocus = () => { gSearchNew(); };
  gs.onkeydown = e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if ($("#gDrop").hidden || !gsItems.length) return;
      e.preventDefault(); gsSel = (gsSel + (e.key === "ArrowDown" ? 1 : -1) + gsItems.length) % gsItems.length; paintSel();
      const r = $(`#gDrop .pp-row[data-i="${gsSel}"]`); if (r) r.scrollIntoView({block: "nearest"});
    }
    if (e.key === "Enter") { e.preventDefault(); if (!$("#gDrop").hidden) pick(gsSel); }
    if (e.key === "Escape") { $("#gDrop").hidden = true; gs.blur(); }
  };

  /* ---------------------------------------- payment: method buttons, change */
  /* The invoice keeps its own <select id="payM"> (money.js listens to it); the buttons only set it. The button
     under the sum says how much will be taken, and for cash the change is counted from what the patient gave. */
  function enhancePay(box) {
    const sel = $("#payM", box), amt = $("#payAmt", box), go = $("#payGo", box), add = sel && sel.closest(".pay-add");
    if (!sel || !amt || !go || !add || sel.dataset.chips) return;
    sel.dataset.chips = "1";
    sel.classList.add("pay-sel-hidden");
    const row = document.createElement("div");
    row.className = "pay-chips"; row.setAttribute("role", "radiogroup"); row.setAttribute("aria-label", "Способ оплаты");
    row.innerHTML = [...sel.options].map(o => `<button type="button" role="radio" data-m="${esc(o.value)}">${esc(o.value)}</button>`).join("");
    add.parentNode.insertBefore(row, add);
    const cash = document.createElement("div");
    cash.className = "pay-cash";
    cash.innerHTML = `<label>Получено наличными<input class="input" type="number" step="1" min="0" id="payGot" placeholder="сумма от пациента"></label><span class="pc-out" aria-live="polite"></span>`;
    add.parentNode.insertBefore(cash, add.nextSibling);
    const got = $("#payGot", cash), out = $(".pc-out", cash);
    const paint = () => {
      $$("button", row).forEach(b => { const on = b.dataset.m === sel.value; b.classList.toggle("on", on); b.setAttribute("aria-checked", on ? "true" : "false"); });
      go.textContent = `Принять ${money(+amt.value || 0)}`;
      cash.hidden = sel.value !== "Наличные";
      const g = +got.value || 0, a = +amt.value || 0;
      out.className = "pc-out" + (g && g < a ? " bad" : "");
      out.textContent = !g ? "" : g < a ? `Не хватает ${money(a - g)}` : `Сдача ${money(g - a)}`;
    };
    row.onclick = e => { const b = e.target.closest("button"); if (!b) return; sel.value = b.dataset.m; sel.dispatchEvent(new Event("change", {bubbles: true})); paint(); };
    sel.addEventListener("change", paint);
    amt.addEventListener("input", paint);
    got.addEventListener("input", paint);
    paint();
  }
  new MutationObserver(() => enhancePay($("#modalBox"))).observe($("#modalBox"), {childList: true, subtree: true});

  /* ------------------------------------------------------- settings, menu */
  const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };
  on("#hintsReset", resetHints);
  on("#keysHelp", keysHelp);
  on("#ucKeys", () => { $("#ucMenu").hidden = true; keysHelp(); });
})();
