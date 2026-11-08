"use strict";
/* Patient card → «Пародонтограмма»: pocket depth, recession, bleeding, mobility and furcation per tooth.
   Fast entry: a digit moves to the next site, «+» marks bleeding, Space/Enter — next, Backspace on an empty site — back.
   Voice: «зуб шестнадцать три два четыре кровоточивость, нёбная два два три, следующий». */
const PU = ["18", "17", "16", "15", "14", "13", "12", "11", "21", "22", "23", "24", "25", "26", "27", "28"];
const PL = ["48", "47", "46", "45", "44", "43", "42", "41", "31", "32", "33", "34", "35", "36", "37", "38"];
const pEmpty = () => ({pd: [null, null, null, null, null, null], rec: [null, null, null, null, null, null], bop: [false, false, false, false, false, false], mob: null, furc: null, missing: false});

function perioStats(teeth) {
  const pd = [], cal = []; let bop = 0, n = 0;
  for (const t of Object.values(teeth)) {
    if (t.missing) continue;
    let has = false;
    t.pd.forEach((p, i) => { if (p === null || p === "" || p === undefined) return; has = true; pd.push(+p); cal.push(+p + (+t.rec[i] || 0)); if (t.bop[i]) bop++; });
    if (has) n++;
  }
  const m = pd.length;
  return {teeth: n, sites: m, mean_pd: m ? Math.round(pd.reduce((a, b) => a + b, 0) / m * 10) / 10 : null, mean_cal: m ? Math.round(cal.reduce((a, b) => a + b, 0) / m * 10) / 10 : null,
    pd4: m ? Math.round(100 * pd.filter(p => p >= 4).length / m) : null, pd6: pd.filter(p => p >= 6).length, bop: m ? Math.round(100 * bop / m) : null};
}
const perioStatsLine = s => s.sites ? `Средняя глубина ${s.mean_pd} мм · уровень прикрепления ${s.mean_cal} мм · карманы ≥ 4 мм: ${s.pd4}% · ≥ 6 мм: ${s.pd6} · кровоточивость ${s.bop}% · зубов ${s.teeth}` : "Пока ничего не измерено";

async function loadPerio(p) {
  const el = $("#perioBody"); if (!el) return;
  const list = await api.perio_list(p.id);
  const edit = can("medcard_edit");
  el.innerHTML = `<div class="tab-tools">${edit ? `<button class="btn small" id="prNew">Новая пародонтограмма</button>` : ""}<span class="muted">Глубина карманов, рецессия, кровоточивость, подвижность и фуркации по каждому зубу</span></div>
    ${list.length ? `<table class="tbl"><thead><tr><th>Дата</th><th>Врач</th><th>Средняя глубина</th><th>Карманы ≥ 4 мм</th><th>Кровоточивость</th><th>Изменение</th></tr></thead><tbody>
      ${list.map((c, i) => { const prev = list[i + 1], d = prev && c.stats.mean_pd !== null && prev.stats.mean_pd !== null ? Math.round((c.stats.mean_pd - prev.stats.mean_pd) * 10) / 10 : null;
        return `<tr data-c="${esc(c.id)}"><td><b class="lnk">${esc(fmtDate(c.date))}</b></td><td>${esc(c.doctor_name || "—")}</td><td>${c.stats.mean_pd ?? "—"} мм</td><td>${c.stats.pd4 ?? "—"}%</td><td>${c.stats.bop ?? "—"}%</td>
          <td>${d === null ? "—" : `<span class="${d > 0 ? "bad-t" : d < 0 ? "ok-t" : ""}">${d > 0 ? "+" : ""}${d} мм</span>`}</td></tr>`; }).join("")}</tbody></table>`
      : `<div class="empty"><b>Пародонтограмм пока нет</b><span>${edit ? "Создайте первую — следующие можно будет сравнить с ней." : ""}</span></div>`}`;
  $$("tr[data-c]", el).forEach(r => r.onclick = async () => openPerio(p, await api.perio_get(r.dataset.c)));
  const nb = $("#prNew", el);
  if (nb) nb.onclick = async () => {
    const last = list[0] ? await api.perio_get(list[0].id) : null;  // missing teeth carry over from the last chart
    const teeth = {};
    if (last) for (const [n, t] of Object.entries(last.data.teeth || {})) if (t.missing) teeth[n] = {...pEmpty(), missing: true};
    for (const [n, s] of Object.entries(p.teeth_local || {})) if (/Отсутств/.test(s) && PU.concat(PL).includes(n)) teeth[n] = {...pEmpty(), missing: true};
    openPerio(p, {patient_id: p.id, date: iso(new Date()), data: {teeth}, doctor_id: ""});
  };
}

async function openPerio(p, chart) {
  const R = await ref();
  const edit = can("medcard_edit");
  const st = {teeth: {}};
  for (const n of PU.concat(PL)) st.teeth[n] = {...pEmpty(), ...((chart.data.teeth || {})[n] || {})};
  const cur = {tooth: null, side: "b", mode: "pd", site: 0, last: null};
  const sitesRow = (teeth, key, side, label, row) => `<tr class="pr-${key}"><th>${label}</th>${teeth.map(n => {
    const t = st.teeth[n], base = side === "b" ? 0 : 3;
    return `<td class="${t.missing ? "miss" : ""}"><div class="pr-sites">${[0, 1, 2].map(i => `<span class="pr-site"><input class="pr-in" inputmode="numeric" maxlength="2" data-row="${row}" data-n="${n}" data-k="${key}" data-i="${base + i}" value="${t[key][base + i] ?? ""}" ${edit && !t.missing ? "" : "disabled"}>${key === "pd" ? `<button class="pr-bop ${t.bop[base + i] ? "on" : ""}" data-n="${n}" data-i="${base + i}" tabindex="-1" title="Кровоточивость" ${edit && !t.missing ? "" : "disabled"}></button>` : ""}</span>`).join("")}</div></td>`; }).join("")}</tr>`;
  const oneRow = (teeth, key, label, row) => `<tr class="pr-${key}"><th>${label}</th>${teeth.map(n => `<td class="${st.teeth[n].missing ? "miss" : ""}"><input class="pr-in one" inputmode="numeric" maxlength="1" data-row="${row}" data-n="${n}" data-k="${key}" value="${st.teeth[n][key] ?? ""}" ${edit && !st.teeth[n].missing ? "" : "disabled"}></td>`).join("")}</tr>`;
  const numRow = teeth => `<tr class="pr-num"><th></th>${teeth.map(n => `<td><button class="pr-tooth ${st.teeth[n].missing ? "miss" : ""}" data-n="${n}" ${edit ? "" : "disabled"} title="${st.teeth[n].missing ? "Зуб отсутствует — щёлкните, чтобы вернуть" : "Щёлкните, если зуба нет"}">${n}</button></td>`).join("")}</tr>`;
  const draw = () => `<table class="pr-tbl"><tbody>
      ${oneRow(PU, "mob", "Подвижность", "u-mob")}${oneRow(PU, "furc", "Фуркация", "u-furc")}
      ${sitesRow(PU, "rec", "b", "Рецессия, щёчн.", "u-rec-b")}${sitesRow(PU, "pd", "b", "Карман, щёчн.", "u-pd-b")}
      ${numRow(PU)}
      ${sitesRow(PU, "pd", "l", "Карман, нёбн.", "u-pd-l")}${sitesRow(PU, "rec", "l", "Рецессия, нёбн.", "u-rec-l")}
    </tbody></table>
    <table class="pr-tbl lower"><tbody>
      ${sitesRow(PL, "rec", "l", "Рецессия, язычн.", "l-rec-l")}${sitesRow(PL, "pd", "l", "Карман, язычн.", "l-pd-l")}
      ${numRow(PL)}
      ${sitesRow(PL, "pd", "b", "Карман, щёчн.", "l-pd-b")}${sitesRow(PL, "rec", "b", "Рецессия, щёчн.", "l-rec-b")}
      ${oneRow(PL, "furc", "Фуркация", "l-furc")}${oneRow(PL, "mob", "Подвижность", "l-mob")}
    </tbody></table>`;
  const box = modal(`<div class="m-h"><h3>Пародонтограмма · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b pr-wrap">
      <div class="grid3"><label class="fl">Дата<input class="input" type="date" id="prDate" value="${esc(chart.date)}" ${edit ? "" : "disabled"}></label>
        <label class="fl">Врач<select class="input" id="prDoc" ${edit ? "" : "disabled"}><option value="">—</option>${R.doctors.map(d => `<option value="${esc(d.id)}" ${d.id === chart.doctor_id ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        ${edit ? `<div class="pr-voice"><button class="btn ghost" id="prMic">🎙 Диктовать</button><small class="muted" id="prMicSt">«зуб 16: три два четыре, кровь, нёбная два два три, следующий»</small></div>` : "<span></span>"}</div>
      <div id="prChart">${draw()}</div>
      <div class="pr-stats" id="prStats"></div>
      <label class="fl">Заключение / примечание<input class="input" id="prNote" value="${esc(chart.note || "")}" ${edit ? "" : "disabled"}></label>
      <div class="muted pr-help">Цифра — следующая точка, «+» — кровоточивость, пробел или Enter — дальше, Backspace на пустой точке — назад. Щелчок по номеру зуба — «зуб отсутствует». Глубина 4–5 мм — жёлтым, от 6 мм — красным.</div>
    </div>
    <div class="m-f">${chart.id && edit ? `<button class="btn ghost small danger" id="prDel">Удалить</button>` : ""}<button class="btn ghost small" id="prPrint">Печать</button><span class="muted"></span>
      <button class="btn ghost" data-close>Закрыть</button>${edit ? `<button class="btn" id="prSave">Сохранить</button>` : ""}</div>`, {wide: true});
  box.classList.add("pr-modal");
  const paint = () => {
    $$(".pr-in[data-k=pd]", box).forEach(i => { const v = +i.value; i.classList.toggle("d4", i.value !== "" && v >= 4 && v < 6); i.classList.toggle("d6", i.value !== "" && v >= 6); });
    $("#prStats", box).textContent = perioStatsLine(perioStats(st.teeth));
  };
  const bind = () => {
    const inputs = () => $$(".pr-in:not([disabled])", box);
    $$(".pr-in", box).forEach(inp => {
      const set = () => { const t = st.teeth[inp.dataset.n], k = inp.dataset.k, v = inp.value.trim() === "" ? null : +inp.value;
        if (k === "pd" || k === "rec") t[k][+inp.dataset.i] = Number.isFinite(v) ? v : null; else t[k] = Number.isFinite(v) ? v : null; paint(); };
      const move = d => { const row = inputs().filter(x => x.dataset.row === inp.dataset.row), i = row.indexOf(inp), nx = row[i + d]; if (nx) { nx.focus(); nx.select(); } };
      inp.oninput = () => {
        inp.value = inp.value.replace(/[^\d-]/g, "");
        set();
        const v = inp.value;
        if (inp.classList.contains("one") ? v.length >= 1 : (v.length >= 2 || (v.length === 1 && v !== "1" && v !== "-"))) move(1);
      };
      inp.onkeydown = e => {
        if (e.key === " " || e.key === "Enter") { e.preventDefault(); move(1); }
        else if (e.key === "Backspace" && inp.value === "") { e.preventDefault(); move(-1); }
        else if ((e.key === "+" || e.key === "*") && inp.dataset.k === "pd") { e.preventDefault(); const b = inp.parentElement.querySelector(".pr-bop"); if (b) b.click(); }
        else if (e.key === "ArrowRight") move(1); else if (e.key === "ArrowLeft") move(-1);
      };
      inp.onfocus = () => { cur.tooth = inp.dataset.n; cur.mode = inp.dataset.k === "rec" ? "rec" : "pd"; cur.side = +inp.dataset.i >= 3 ? "l" : "b"; cur.site = (+inp.dataset.i || 0) % 3; };
    });
    $$(".pr-bop", box).forEach(b => b.onclick = () => { const t = st.teeth[b.dataset.n], i = +b.dataset.i; t.bop[i] = !t.bop[i]; b.classList.toggle("on", t.bop[i]); paint(); });
    $$(".pr-tooth", box).forEach(b => b.onclick = () => { const t = st.teeth[b.dataset.n]; t.missing = !t.missing; redraw(); });
    paint();
  };
  const redraw = () => { $("#prChart", box).innerHTML = draw(); bind(); };
  bind();

  // voice: commands from the server are applied to the chart one by one
  const order = n => (PU.includes(n) ? PU : PL);
  const nextTooth = n => { const o = order(n); let i = o.indexOf(n) + 1; while (i < o.length && st.teeth[o[i]].missing) i++; return o[i] || null; };
  const applyVoice = cmds => {
    for (const c of cmds) {
      if (c.t === "tooth") { cur.tooth = c.v; cur.site = 0; }
      else if (c.t === "side") { cur.side = c.v; cur.site = 0; }
      else if (c.t === "mode") { cur.mode = c.v; cur.site = 0; }
      else if (c.t === "next") { cur.tooth = cur.tooth ? nextTooth(cur.tooth) : PU[0]; cur.site = 0; }
      else if (c.t === "missing") { if (cur.tooth) { st.teeth[cur.tooth].missing = true; cur.tooth = nextTooth(cur.tooth); cur.site = 0; } }
      else if (c.t === "mob" || c.t === "furc") { const n = cur.tooth || (cur.last && cur.last.tooth); if (n) st.teeth[n][c.t] = c.v; }
      else if (c.t === "bop") { if (cur.last) st.teeth[cur.last.tooth].bop[cur.last.idx] = true; }
      else if (c.t === "val") {
        if (!cur.tooth) cur.tooth = PU.find(n => !st.teeth[n].missing);
        if (!cur.tooth) continue;
        // the tooth changes only when a fourth value comes, so «нёбная …» or «подвижность» still mean this tooth
        if (cur.site > 2) { const nt = nextTooth(cur.tooth); if (!nt) continue; cur.tooth = nt; cur.site = 0; }
        const idx = (cur.side === "b" ? 0 : 3) + cur.site;
        st.teeth[cur.tooth][cur.mode][idx] = c.v; cur.last = {tooth: cur.tooth, idx};
        cur.site++;
      }
    }
    redraw();
  };
  const mic = $("#prMic", box);
  if (mic) {
    let recr = null;
    mic.onclick = async () => {
      const stEl = $("#prMicSt", box);
      if (!recr) {
        try { recr = await micRecorder(); } catch (e) { toast(errText(e), true); return; }
        mic.textContent = "■ Готово"; mic.classList.add("rec-on"); stEl.textContent = cur.tooth ? `Говорите — начнём с зуба ${cur.tooth}` : "Говорите: «зуб восемнадцать, три два три…»";
        return;
      }
      const blob = await recr.stop(); recr = null; mic.textContent = "🎙 Диктовать"; mic.classList.remove("rec-on"); stEl.textContent = "Распознаём…";
      try { const r = await api.perio_voice(await blobB64(blob), blob.type); applyVoice(r.commands); stEl.textContent = `Распознано: «${r.text}»`; }
      catch (e) { stEl.textContent = ""; toast(errText(e), true); }
    };
  }
  const sv = $("#prSave", box);
  if (sv) sv.onclick = async () => {
    try {
      const r = await api.perio_save({id: chart.id || null, patient_id: p.id, date: $("#prDate", box).value, doctor_id: $("#prDoc", box).value, note: $("#prNote", box).value, data: {teeth: st.teeth}});
      chart.id = r.id; closeModal(); toast("Пародонтограмма сохранена"); P = await api.patient(p.id); renderPatient("perio");
    } catch (e) { toast(errText(e), true); }
  };
  const dl = $("#prDel", box);
  if (dl) dl.onclick = async () => { if (await ask("Удалить пародонтограмму?", {danger: true, ok: "Удалить", text: fmtDate(chart.date)})) { await api.perio_delete(chart.id); closeModal(); P = await api.patient(p.id); renderPatient("perio"); } };
  $("#prPrint", box).onclick = async () => {
    const ro = $("#prChart", box).cloneNode(true);
    $$("input", ro).forEach(i => { const s = document.createElement("span"); s.className = i.className; s.textContent = i.value; i.replaceWith(s); });
    $$("button.pr-bop", ro).forEach(b => { const s = document.createElement("i"); s.className = b.className; b.replaceWith(s); });
    $("#printArea").innerHTML = `${typeof clinicHead === "function" ? await clinicHead() : ""}<h2>Пародонтограмма</h2><div>Пациент: <b>${esc(p.name)}</b> · ${esc(fmtDate($("#prDate", box).value))} · врач ${esc($("#prDoc", box).selectedOptions[0]?.text || "—")}</div>
      <div class="pr-print">${ro.innerHTML}</div><p>${esc(perioStatsLine(perioStats(st.teeth)))}</p>${$("#prNote", box).value ? `<p>${esc($("#prNote", box).value)}</p>` : ""}`;
    window.print();
  };
}
