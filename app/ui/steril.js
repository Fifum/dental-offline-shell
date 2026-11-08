"use strict";
/* Sterilization journal (Stock → «Стерилизация»): autoclave / dry-heat cycles with indicators, printable for inspections. */
let STER = null;

async function sterilJournal() {
  const body = $("#stockBody");
  STER = STER || await api.steril_options();
  const r = await api.steril_list(S.period.from, S.period.to, S.sterFilter || null);
  const edit = can("sterilization");
  body.innerHTML = `<div class="tab-tools rep-tools">${periodBar()}
      <select class="input sm-sel" id="stFilter"><option value="">Все стерилизаторы</option>${STER.sterilizers.map(s => `<option ${s === S.sterFilter ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <span class="grow"></span>${edit ? `<button class="btn" id="stAdd">Записать цикл</button>` : ""}<button class="icon-btn" id="stPrint" title="Распечатать журнал">${PRINT_ICON}</button></div>
    <div class="stat-row"><div class="stat"><span>Циклов</span><b>${r.count}</b></div><div class="stat"><span>Упаковок</span><b>${r.packs}</b></div>
      <div class="stat ${r.failed ? "warn" : ""}"><span>Брак</span><b>${r.failed}</b></div></div>
    <div class="pbody">${r.rows.length ? `<table class="tbl compact st-tbl"><thead><tr><th>№</th><th>Дата, время</th><th>Стерилизатор</th><th>Метод и режим</th><th>Что стерилизовали</th>
        <th>Хим. индикатор</th><th>Биол. индикатор</th><th>Результат</th><th>Ответственный</th><th class="no-print"></th></tr></thead><tbody>
      ${r.rows.map((x, i) => `<tr class="${x.result === "брак" ? "neg" : ""}"><td>${esc(x.cycle_no ?? "")}</td><td class="nowrap">${esc(fmtDT(x.at))}</td><td>${esc(x.sterilizer)}</td>
        <td>${esc(x.method || "")}<small class="muted" style="display:block">${esc(x.program || [x.temp ? x.temp + " °C" : "", x.pressure ? x.pressure + " МПа" : "", x.minutes ? x.minutes + " мин" : ""].filter(Boolean).join(", "))}</small></td>
        <td>${esc(x.load || "")}${x.packs ? `<small class="muted" style="display:block">упаковок: ${x.packs}</small>` : ""}</td>
        <td>${esc(x.chem_text)}</td><td>${esc(x.bio_text)}</td><td><span class="pill ${x.result === "брак" ? "st-cancel" : "st-ok"}">${esc(x.result)}</span></td>
        <td>${esc(x.operator || "")}</td><td class="row-acts no-print">${edit ? `<button class="linkbtn" data-ed="${i}">изменить</button>` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><b>За период циклов нет</b><span>${edit ? "Нажмите «Записать цикл» после каждой загрузки автоклава." : ""}</span></div>`}</div>
    <div class="muted note-line">Брак — если хотя бы один индикатор «не соответствует»: такую загрузку нужно простерилизовать заново. Номер цикла считается для каждого стерилизатора с начала года.</div>`;
  bindPeriod(body, sterilJournal);
  $("#stFilter").onchange = e => { S.sterFilter = e.target.value; sterilJournal(); };
  $("#stPrint").onclick = () => printTable("Журнал контроля работы стерилизаторов", "#stockBody table.tbl");
  const add = $("#stAdd"); if (add) add.onclick = () => sterilForm();
  $$("[data-ed]", body).forEach(b => b.onclick = () => sterilForm(r.rows[+b.dataset.ed]));
}

function sterilForm(x = null) {
  const last = STER.last || {};
  const v = x || {sterilizer: last.sterilizer || STER.sterilizers[0] || "", method: last.method || STER.methods[0], program: last.program || STER.programs[0], chem: "ok", bio: ""};
  const at = (x ? x.at : nowLocal()).replace(" ", "T").slice(0, 16);
  const ind = (id, val) => `<select class="input" id="${id}">${Object.entries(STER.indicator).map(([k, t]) => `<option value="${k}" ${k === (val || "") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  const box = modal(`<div class="m-h"><h3>${x ? `Цикл № ${esc(x.cycle_no ?? "")}` : "Новый цикл стерилизации"}</h3><button class="x" data-close>×</button></div>
    <div class="m-b">
      <div class="grid3">
        <label class="fl">Стерилизатор<input class="input" id="sfS" list="sfSl" value="${esc(v.sterilizer || "")}" placeholder="Автоклав № 1"><datalist id="sfSl">${STER.sterilizers.map(s => `<option value="${esc(s)}">`).join("")}</datalist></label>
        <label class="fl">Дата и время<input class="input" id="sfAt" type="datetime-local" value="${esc(at)}"></label>
        <label class="fl">Метод<select class="input" id="sfM">${STER.methods.map(m => `<option ${m === v.method ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>
      </div>
      <div class="grid3">
        <label class="fl">Режим<input class="input" id="sfP" list="sfPl" value="${esc(v.program || "")}"><datalist id="sfPl">${STER.programs.map(s => `<option value="${esc(s)}">`).join("")}</datalist></label>
        <label class="fl">Химический индикатор${ind("sfC", v.chem)}</label>
        <label class="fl">Биологический индикатор${ind("sfB", v.bio)}</label>
      </div>
      <div class="grid3">
        <label class="fl">Что стерилизовали<input class="input" id="sfL" value="${esc(v.load || "")}" placeholder="Наборы инструментов, боры, наконечники"></label>
        <label class="fl">Упаковок<input class="input" id="sfN" type="number" min="0" value="${esc(v.packs ?? "")}"></label>
        <label class="fl">Ответственный<input class="input" id="sfO" value="${esc(v.operator || (ME && ME.name) || "")}"></label>
      </div>
      <label class="fl">Примечание<input class="input" id="sfNote" value="${esc(v.note || "")}"></label>
      <div class="warn-line bad" id="sfFail" hidden>Индикатор не соответствует — цикл будет записан как брак. Загрузку нужно простерилизовать заново.</div>
    </div>
    <div class="m-f">${x ? `<button class="btn ghost small danger" id="sfDel">Удалить</button>` : ""}<span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="sfSave">Сохранить</button></div>`, {wide: true});
  const fail = () => { $("#sfFail", box).hidden = ![$("#sfC", box).value, $("#sfB", box).value].includes("fail"); };
  $("#sfC", box).onchange = fail; $("#sfB", box).onchange = fail; fail();
  $("#sfSave", box).onclick = async () => {
    const f = {id: x ? x.id : null, sterilizer: $("#sfS", box).value, at: $("#sfAt", box).value, method: $("#sfM", box).value, program: $("#sfP", box).value,
      chem: $("#sfC", box).value, bio: $("#sfB", box).value, load: $("#sfL", box).value, packs: $("#sfN", box).value, operator: $("#sfO", box).value, note: $("#sfNote", box).value};
    try {
      const r = await api.steril_save(f);
      STER.last = {sterilizer: f.sterilizer, method: f.method, program: f.program};
      if (!STER.sterilizers.includes(f.sterilizer)) STER.sterilizers.push(f.sterilizer);
      closeModal(); toast(r.result === "брак" ? `Цикл № ${r.cycle_no} записан как брак` : `Цикл № ${r.cycle_no} записан`, r.result === "брак"); sterilJournal();
    } catch (e) { toast(errText(e), true); }
  };
  const del = $("#sfDel", box);
  if (del) del.onclick = async () => { if (await ask("Удалить запись о цикле?", {danger: true, ok: "Удалить", text: "Запись пропадёт из журнала стерилизации."})) { await api.steril_delete(x.id); closeModal(); sterilJournal(); } };
}
