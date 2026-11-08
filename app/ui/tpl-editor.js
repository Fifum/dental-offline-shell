"use strict";
/* Document template editor «like Word»: the doctor edits the page itself. Fields ({{patient.fio}} etc.)
   are shown as coloured chips with human names and cannot be broken by typing. HTML stays available
   for advanced users. */
const PH_GROUPS = [
  ["Пациент", [["patient.fio", "ФИО пациента"], ["patient.birth", "Дата рождения"], ["patient.phone", "Телефон пациента"],
    ["patient.address", "Адрес пациента"], ["patient.card", "Номер карты"]]],
  ["Врач", [["doctor.fio", "ФИО врача"], ["doctor.position", "Должность врача"]]],
  ["Клиника", [["clinic.name", "Название клиники"], ["clinic.address", "Адрес клиники"], ["clinic.phone", "Телефон клиники"],
    ["clinic.inn", "ИНН клиники"], ["clinic.ogrn", "ОГРН клиники"], ["clinic.license", "Лицензия клиники"], ["clinic.director", "Руководитель клиники"]]],
  ["Даты", [["today", "Сегодняшняя дата"], ["visit.date", "Дата приёма"]]],
  ["Медкарта", [["record.complaints", "Жалобы"], ["record.anamnesis", "Анамнез"], ["record.objective", "Объективно (осмотр)"],
    ["record.diagnoses", "Диагноз"], ["record.treatment", "Проведённое лечение"], ["record.recommendations", "Рекомендации"]]],
  ["Деньги", [["invoice.total", "Сумма счёта"], ["invoice.total_words", "Сумма прописью"]]],
  ["Таблицы", [["table:services", "Таблица услуг из счёта"], ["table:records", "Таблица записей медкарты"]]],
];
const PH_NAMES = Object.fromEntries(PH_GROUPS.flatMap(([, items]) => items));
const phLabel = key => key.startsWith("input:") ? `✎ ${key.slice(6).split("|")[0]}` : (PH_NAMES[key] || key);
const isBlockPh = key => key.startsWith("table:");

/* template HTML → editable page with chips */
function tplToVisual(html) {
  return String(html || "").replace(/\{\{([^}]+)\}\}/g, (_, key) => {
    key = key.trim();
    const title = key.startsWith("input:") ? "Заполняется при создании документа" : "Подставится автоматически";
    return isBlockPh(key)
      ? `<div class="ph ph-block" contenteditable="false" data-ph="${esc(key)}" title="${title}">${esc(phLabel(key))}</div>`
      : `<span class="ph" contenteditable="false" data-ph="${esc(key)}" title="${title}">${esc(phLabel(key))}</span>`;
  });
}

/* editable page → template HTML */
function tplFromVisual(root) {
  const c = root.cloneNode(true);
  c.querySelectorAll(".ph").forEach(el => el.replaceWith(document.createTextNode(`{{${el.dataset.ph}}}`)));
  c.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));
  c.querySelectorAll(".tpl-sel").forEach(el => el.classList.remove("tpl-sel"));
  c.querySelectorAll("[class='']").forEach(el => el.removeAttribute("class"));
  return c.innerHTML.replace(/<p><br><\/p>\s*$/g, "").replace(/&nbsp;/g, " ").trim();
}

function editDocTemplate(t) {
  const AL = d => `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="${d}"/></svg>`;
  const TB = (cmd, label, title, extra = "") => `<button class="tb" data-cmd="${cmd}" title="${title}" type="button" ${extra}>${label}</button>`;
  const box = modal(`<div class="m-h"><h3>Шаблон документа</h3><button class="x" data-close>×</button></div>
    <div class="m-b tpl-ed2">
      <div class="tpl-meta"><label class="fl">Название<input class="input" id="teT" value="${esc(t.title)}"></label>
        <label class="fl">Раздел<input class="input" id="teC" value="${esc(t.category || "")}"></label>
        <div class="seg" id="teMode"><button data-m="edit" class="on" type="button">Редактор</button><button data-m="preview" type="button">С примером данных</button><button data-m="html" type="button">HTML</button></div></div>
      <div class="tpl-toolbar" id="teBar">
        <select class="input tb-sel" id="teBlock" title="Стиль абзаца"><option value="p">Обычный текст</option><option value="h2">Заголовок</option><option value="h3">Подзаголовок</option></select>
        <span class="tb-sep"></span>
        ${TB("bold", "<b>Ж</b>", "Жирный (Ctrl+B)")}${TB("italic", "<i>К</i>", "Курсив (Ctrl+I)")}${TB("underline", "<u>Ч</u>", "Подчёркнутый (Ctrl+U)")}
        <span class="tb-sep"></span>
        ${TB("justifyLeft", AL("M4 6h16M4 10h10M4 14h16M4 18h10"), "По левому краю")}${TB("justifyCenter", AL("M4 6h16M7 10h10M4 14h16M7 18h10"), "По центру")}${TB("justifyRight", AL("M4 6h16M10 10h10M4 14h16M10 18h10"), "По правому краю")}${TB("justifyFull", AL("M4 6h16M4 10h16M4 14h16M4 18h16"), "По ширине")}
        <span class="tb-sep"></span>
        ${TB("insertUnorderedList", "• Список", "Маркированный список")}${TB("insertOrderedList", "1. Список", "Нумерованный список")}
        <span class="tb-sep"></span>
        <div class="dd" id="teTable"><button class="tb dd-btn" type="button" title="Таблица">▦ Таблица ▾</button>
          <div class="dd-menu"><button data-t="new" type="button">Вставить таблицу…</button><button data-t="row" type="button">Добавить строку ниже</button>
            <button data-t="col" type="button">Добавить столбец справа</button><button data-t="delrow" type="button">Удалить строку</button>
            <button data-t="delcol" type="button">Удалить столбец</button><button data-t="del" type="button">Удалить таблицу</button></div></div>
        ${TB("check", "☐ Галочка", "Квадратик для отметки")}${TB("sign", "___ Подпись", "Линия для подписи")}${TB("pagebreak", "⤓ Новая страница", "Разрыв страницы при печати")}
        <span class="tb-sep"></span>
        ${TB("undo", "↶", "Отменить (Ctrl+Z)")}${TB("redo", "↷", "Повторить (Ctrl+Y)")}
      </div>
      <div class="tpl-work">
        <div class="tpl-paper"><div class="doc-page tpl-page" id="tePage" contenteditable="true" spellcheck="true"></div>
          <div class="doc-page" id="tePrev" hidden></div>
          <textarea class="input mono tpl-html" id="teB" hidden spellcheck="false"></textarea></div>
        <aside class="tpl-fields"><b>Вставить поле</b><span class="muted">Щёлкните — поле встанет туда, где мигает курсор. При создании документа программа подставит данные сама.</span>
          ${PH_GROUPS.map(([g, items]) => `<div class="tf-g"><small>${g}</small>${items.map(([k, l]) => `<button class="tf-b" data-ph="${esc(k)}" type="button">${esc(l)}</button>`).join("")}</div>`).join("")}
          <div class="tf-g"><small>Поле для заполнения</small><button class="tf-b tf-input" id="teInput" type="button">✎ Своё поле…</button>
            <span class="muted" style="font-size:11.5px">Например «Номер договора» — врач впишет его при создании документа.</span></div>
        </aside>
      </div>
    </div>
    <div class="m-f">${t.id && !t.builtin ? '<button class="btn ghost small danger" id="teDel">Удалить</button>' : ""}${t.builtin ? '<button class="btn ghost small" id="teReset">Вернуть исходный текст</button>' : ""}
      <span class="muted">Изменения видны только в новых документах</span><button class="btn ghost" data-close>Отмена</button>${t.id ? '<button class="btn ghost" id="teCopy">Сохранить как копию</button>' : ""}<button class="btn" id="teSave">Сохранить</button></div>`, {wide: true});

  const page = $("#tePage", box), prevEl = $("#tePrev", box), ta = $("#teB", box);
  page.innerHTML = tplToVisual(t.body);
  let mode = "edit", lastRange = null;
  const demoCtx = {patient: {fio: "Иванова Анна Сергеевна", birth: "1990-03-15", phone: "+7 900 000-00-00", address: "г. Москва, ул. Примерная, 1", card: "2026-001"},
    doctor: {fio: "Петров Пётр Петрович", position: "Стоматолог-терапевт"}, clinic: (REF && REF.clinic) || {}, visit: {date: iso(new Date())},
    record: {complaints: "Боль от холодного", diagnoses: [{code: "K02.1", title: "Кариес дентина", tooth: "36"}], treatment: "Пломба"},
    invoice: {items: [{code: "A16.07.002", title: "Лечение кариеса", qty: 1, price: 5500, sum: 5500}], total: 5500}};
  try { document.execCommand("defaultParagraphSeparator", false, "p"); document.execCommand("styleWithCSS", false, false); } catch (e) {}

  const current = () => mode === "html" ? ta.value : tplFromVisual(page);
  const saveRange = () => { const s = getSelection(); if (s.rangeCount && page.contains(s.anchorNode)) lastRange = s.getRangeAt(0).cloneRange(); };
  const restore = () => {  // keep the live selection if it is in the page, otherwise go back to the last one
    const s = getSelection();
    if (s.rangeCount && page.contains(s.anchorNode)) return;
    page.focus(); if (lastRange) { s.removeAllRanges(); s.addRange(lastRange); }
  };
  page.addEventListener("keyup", saveRange); page.addEventListener("mouseup", saveRange); page.addEventListener("input", saveRange);
  document.addEventListener("selectionchange", function track() { if (!document.body.contains(page)) return document.removeEventListener("selectionchange", track); saveRange(); syncBlock(); });

  const insertNode = node => {
    restore();
    const s = getSelection();
    if (!s.rangeCount) { page.appendChild(node); return; }
    const r = s.getRangeAt(0);
    const isBlock = node.nodeType === 1 && (node.nodeName === "TABLE" || node.classList.contains("ph-block") || node.classList.contains("page-break"));
    if (isBlock) {  // tables and page breaks go after the current paragraph, never inside it
      let top = r.startContainer; while (top && top.parentNode !== page) top = top.parentNode;
      if (top) top.after(node); else page.appendChild(node);
      const p = document.createElement("p"); p.innerHTML = "<br>"; node.after(p);
      const rr = document.createRange(); rr.setStart(p, 0); rr.collapse(true); s.removeAllRanges(); s.addRange(rr); saveRange();
      return;
    }
    r.deleteContents(); r.insertNode(node);
    const space = document.createTextNode(node.classList && node.classList.contains("ph-block") ? "" : " ");
    node.after(space);
    r.setStartAfter(space); r.collapse(true); s.removeAllRanges(); s.addRange(r); saveRange();
  };
  const backTo = range => { page.focus(); if (range) { const s = getSelection(); s.removeAllRanges(); s.addRange(range); lastRange = range; } };
  const chip = key => { const w = document.createElement("div"); w.innerHTML = tplToVisual(`{{${key}}}`); return w.firstChild; };
  const cellOf = () => { const s = getSelection(); let n = s.anchorNode; while (n && n !== page) { if (n.nodeName === "TD" || n.nodeName === "TH") return n; n = n.parentNode; } return null; };

  // toolbar: keep the caret in the page while clicking buttons
  $$("#teBar button, .tpl-fields button", box).forEach(b => b.addEventListener("mousedown", e => e.preventDefault()));
  $$("#teBar [data-cmd]", box).forEach(b => b.onclick = () => {
    if (mode !== "edit") return toast("Переключитесь в «Редактор»", true);
    restore();
    const cmd = b.dataset.cmd;
    if (cmd === "check") return insertNode(document.createTextNode("☐ "));
    if (cmd === "sign") return insertNode(document.createTextNode("________________ "));
    if (cmd === "pagebreak") { const d = document.createElement("div"); d.className = "page-break"; d.setAttribute("contenteditable", "false"); d.textContent = "— новая страница —"; return insertNode(d); }
    document.execCommand(cmd, false, null);
    saveRange();
  });
  const syncBlock = () => { if (mode !== "edit") return; const s = getSelection(); let n = s.anchorNode; while (n && n !== page && !/^(P|H2|H3|DIV|LI|TD)$/.test(n.nodeName)) n = n.parentNode;
    if (n && n !== page) $("#teBlock", box).value = ["H2", "H3"].includes(n.nodeName) ? n.nodeName.toLowerCase() : "p"; };
  $("#teBlock", box).onchange = e => { restore(); document.execCommand("formatBlock", false, e.target.value); saveRange(); };

  // tables
  const ddT = $("#teTable", box);
  $(".dd-btn", ddT).onclick = e => { e.stopPropagation(); ddT.classList.toggle("open"); };
  $$("[data-t]", ddT).forEach(b => b.addEventListener("mousedown", e => e.preventDefault()));
  $$("[data-t]", ddT).forEach(b => b.onclick = async () => {
    ddT.classList.remove("open");
    const act = b.dataset.t;
    if (act === "new") {
      const keep = lastRange && lastRange.cloneRange();  // the dialog moves focus; come back to the same place
      const v = await askInput("Вставить таблицу", [{label: "Строк", type: "number", value: "3"}, {label: "Столбцов", type: "number", value: "2"}], {ok: "Вставить"});
      backTo(keep);
      if (!v) return;
      const rows = Math.min(40, Math.max(1, +v[0] || 3)), cols = Math.min(10, Math.max(1, +v[1] || 2));
      const tbl = document.createElement("table"); tbl.className = "dtab";
      tbl.innerHTML = Array.from({length: rows}, () => `<tr>${"<td><br></td>".repeat(cols)}</tr>`).join("");
      insertNode(tbl); return;
    }
    restore();
    const cell = cellOf();
    if (!cell) return toast("Поставьте курсор в ячейку таблицы", true);
    const row = cell.parentNode, table = cell.closest("table"), idx = [...row.children].indexOf(cell);
    if (act === "row") { const r = row.cloneNode(true); r.querySelectorAll("td,th").forEach(c => c.innerHTML = "<br>"); row.after(r); }
    if (act === "col") table.querySelectorAll("tr").forEach(tr => { const c = (tr.children[idx] || tr.lastElementChild).cloneNode(false); c.innerHTML = "<br>"; (tr.children[idx] || tr.lastElementChild).after(c); });
    if (act === "delrow") { if (table.rows.length > 1) row.remove(); else table.remove(); }
    if (act === "delcol") { if (row.children.length > 1) table.querySelectorAll("tr").forEach(tr => tr.children[idx] && tr.children[idx].remove()); else table.remove(); }
    if (act === "del") table.remove();
  });

  // fields
  $$(".tf-b[data-ph]", box).forEach(b => b.onclick = () => {
    if (mode === "html") { const s = ta.selectionStart; ta.value = ta.value.slice(0, s) + `{{${b.dataset.ph}}}` + ta.value.slice(ta.selectionEnd); ta.focus(); return; }
    if (mode !== "edit") return toast("Переключитесь в «Редактор»", true);
    insertNode(chip(b.dataset.ph));
  });
  $("#teInput", box).onclick = async () => {
    const keep = lastRange && lastRange.cloneRange();
    const v = await askInput("Своё поле для заполнения", [{label: "Название поля", value: ""}, {label: "Значение по умолчанию (можно пусто)", value: "", required: false}], {ok: "Вставить"});
    if (mode !== "html") backTo(keep);
    if (!v) return;
    const key = `input:${v[0].replace(/[|{}]/g, "")}${v[1] ? "|" + v[1].replace(/[|{}]/g, "") : ""}`;
    if (mode === "html") { ta.value += `{{${key}}}`; return; }
    insertNode(chip(key));
  };

  // paste: plain text only (Word brings hidden formatting that breaks documents)
  page.addEventListener("paste", e => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData("text/plain");
    const html = text.split(/\r?\n/).map(l => esc(l)).join("<br>");
    document.execCommand("insertHTML", false, html);
  });
  page.addEventListener("keydown", e => { if (e.key === "Tab") { e.preventDefault(); document.execCommand("insertText", false, "    "); } });

  // modes
  $$("#teMode button", box).forEach(b => b.onclick = () => {
    const next = b.dataset.m;
    if (next === mode) return;
    const body = current();
    if (next === "edit") page.innerHTML = tplToVisual(body);
    if (next === "html") ta.value = body;
    if (next === "preview") prevEl.innerHTML = renderDoc(body, demoCtx, []);
    page.hidden = next !== "edit"; prevEl.hidden = next !== "preview"; ta.hidden = next !== "html";
    $("#teBar", box).classList.toggle("off", next !== "edit");
    mode = next;
    $$("#teMode button", box).forEach(x => x.classList.toggle("on", x === b));
  });

  const save = async asCopy => {
    const body = current();
    const title = $("#teT", box).value.trim(), category = $("#teC", box).value.trim();
    await api.save_template({id: asCopy ? null : t.id, kind: "document", title: title + (asCopy ? " (копия)" : ""), category, body});
    closeModal(); toast("Шаблон сохранён"); loadRefs();
  };
  $("#teSave", box).onclick = () => save(false);
  const cp = $("#teCopy", box); if (cp) cp.onclick = () => save(true);
  const rs = $("#teReset", box); if (rs) rs.onclick = async () => { if (await ask("Вернуть исходный текст шаблона?", {icon: "warn", ok: "Вернуть", text: "Ваши правки в этом шаблоне пропадут."})) { await api.reset_template(t.id); closeModal(); loadRefs(); } };
  const dl = $("#teDel", box); if (dl) dl.onclick = async () => { if (await ask("Удалить шаблон?", {danger: true, ok: "Удалить", text: "Уже созданные документы останутся."})) { await api.delete_template(t.id); closeModal(); loadRefs(); } };
  setTimeout(() => { page.focus(); const r = document.createRange(); r.selectNodeContents(page); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); saveRange(); }, 60);
}
