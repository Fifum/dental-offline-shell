"use strict";
/* Patient card → «Снимки и файлы»: X-rays (DICOM too), photos, documents; viewer with zoom, brightness,
   contrast, invert and a before/after comparison; import from the visiograph folder; paste and drag & drop. */
const PF = {kind: "", items: [], kinds: null};
const PF_ACCEPT = ".jpg,.jpeg,.png,.bmp,.gif,.webp,.tif,.tiff,.dcm,.pdf,.stl";

async function loadPatientFiles(p) {
  const el = $("#pfBody"); if (!el) return;
  const [items, st] = await Promise.all([api.files_list(p.id), PF.kinds ? Promise.resolve(null) : api.files_settings().catch(() => null)]);
  if (st) { PF.kinds = st.kinds; PF.maxMb = st.max_mb; PF.inbox = st.inbox; }
  PF.items = items; PF.pid = p.id;
  const edit = canAny("medcard_edit", "patients_edit");
  const shown = items.filter(x => !PF.kind || x.kind === PF.kind);
  el.innerHTML = `<div class="tab-tools pf-tools">
      ${edit ? `<label class="btn small pf-add">Добавить файлы<input type="file" id="pfInput" multiple accept="${PF_ACCEPT}" hidden></label>
        ${PF.inbox ? `<button class="btn ghost small" id="pfInbox">Из визиографа</button>` : ""}` : ""}
      <div class="seg sm" id="pfKinds"><button data-k="" class="${PF.kind ? "" : "on"}">Все ${items.length}</button>${Object.entries(PF.kinds || {}).map(([k, t]) => {
        const n = items.filter(x => x.kind === k).length; return n ? `<button data-k="${k}" class="${PF.kind === k ? "on" : ""}">${esc(t)} ${n}</button>` : ""; }).join("")}</div>
      <span class="grow"></span>${edit ? `<span class="muted pf-hint">Перетащите файлы сюда или вставьте снимок: Ctrl+V</span>` : ""}</div>
    <div class="pf-grid" id="pfGrid">${shown.map(x => `<button class="pf-card" data-id="${esc(x.id)}">
        <span class="pf-th">${x.image ? `<img alt="" data-th="${esc(x.id)}">` : `<span class="pf-ext">${esc(x.ext.replace(".", "").toUpperCase())}</span>`}</span>
        <span class="pf-cap"><b>${esc(x.title || x.orig_name)}</b><small>${esc(x.kind_text)}${x.tooth ? " · зуб " + esc(x.tooth) : ""} · ${esc(fmtDate(x.taken_at || x.created_at))}</small></span></button>`).join("")}
    </div>${shown.length ? "" : `<div class="empty"><b>${items.length ? "В этой группе файлов нет" : "Снимков и файлов пока нет"}</b><span>${edit ? "Добавьте рентгеновские снимки, фото «до/после», сканы документов." : ""}</span></div>`}
    <div class="muted note-line">Файлы хранятся на этом компьютере. Чтобы они пережили поломку ноутбука, включите вторую папку резервных копий (флешку) — снимки копируются туда сами.</div>`;
  $$("#pfKinds button", el).forEach(b => b.onclick = () => { PF.kind = b.dataset.k; loadPatientFiles(p); });
  $$(".pf-card", el).forEach(c => c.onclick = () => openFileViewer(c.dataset.id));
  const ids = shown.filter(x => x.image).map(x => x.id);
  if (ids.length) api.file_thumbs(ids).then(m => { for (const [id, url] of Object.entries(m)) { const im = $(`img[data-th="${id}"]`, el); if (im) im.src = url; } }).catch(() => {});
  if (!edit) return;
  $("#pfInput", el).onchange = e => uploadFiles([...e.target.files], p);
  const ib = $("#pfInbox", el); if (ib) ib.onclick = () => openInbox(p);
  el.ondragover = e => { e.preventDefault(); el.classList.add("pf-drop"); };
  el.ondragleave = () => el.classList.remove("pf-drop");
  el.ondrop = e => { e.preventDefault(); el.classList.remove("pf-drop"); uploadFiles([...e.dataTransfer.files], p); };
}

// Ctrl+V of a screenshot from the visiograph program while the files tab is open
document.addEventListener("paste", e => {
  if (S.view !== "patient" || S.patientTab !== "files" || !P || $(".modal") || !canAny("medcard_edit", "patients_edit")) return;
  const files = [...(e.clipboardData ? e.clipboardData.files : [])];
  if (!files.length) return;
  e.preventDefault();
  uploadFiles(files.map((f, i) => new File([f], f.name && f.name !== "image.png" ? f.name : `Снимок из буфера ${nowLocal().replace(":", "-")}${i ? "-" + i : ""}.png`, {type: f.type})), P);
});

async function uploadFiles(list, p) {
  if (!list.length) return;
  const max = (PF.maxMb || 15) * 1024 * 1024;
  let ok = 0, dup = 0;
  for (const f of list) {
    if (f.size > max) { toast(`«${f.name}» больше ${PF.maxMb || 15} МБ — не добавлен`, true); continue; }
    try {
      toast(`Загружаем «${f.name}»…`);
      const r = await api.file_add(p.id, f.name, await blobB64(f), {});
      r.duplicate ? dup++ : ok++;
    } catch (e) { toast(`«${f.name}»: ${errText(e)}`, true); }
  }
  if (ok || dup) toast(`Добавлено файлов: ${ok}${dup ? `, уже были в карте: ${dup}` : ""}`);
  P = await api.patient(p.id); renderPatient("files");
}

async function openInbox(p) {
  const box = modal(`<div class="m-h"><h3>Снимки из визиографа</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="scan"><i></i>Ищем новые снимки…</div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="ibGo" disabled>Добавить в карту</button></div>`, {wide: true});
  let r;
  try { r = await api.files_inbox(); } catch (e) { $(".m-b", box).innerHTML = `<div class="warn-line bad">${esc(errText(e))}</div>`; return; }
  const sel = new Set();
  $(".m-b", box).innerHTML = r.error ? `<div class="warn-line bad">${esc(r.error)}</div>`
    : `<p class="hint">Новые снимки за ${3} дня из папки <code>${esc(r.dir)}</code>, которые ещё не добавлены ни в одну карту. Отметьте снимки пациента <b>${esc(p.name)}</b>.</p>
      ${r.rows.length ? `<div class="pf-grid">${r.rows.map((x, i) => `<button class="pf-card ib" data-i="${i}"><span class="pf-th">${x.thumb ? `<img alt="" src="${x.thumb}">` : `<span class="pf-ext">?</span>`}</span>
        <span class="pf-cap"><b>${esc(x.short)}</b><small>${esc(fmtDT(x.at))} · ${esc(BK_SIZE(x.size))}</small></span></button>`).join("")}</div>
        <label class="fl" style="max-width:200px">Зуб (необязательно)<input class="input" id="ibTooth"></label>` : `<div class="empty"><b>Новых снимков нет</b><span>Сделайте снимок в программе визиографа — он появится здесь.</span></div>`}`;
  $$(".pf-card.ib", box).forEach(c => c.onclick = () => { const n = r.rows[+c.dataset.i].name; sel.has(n) ? sel.delete(n) : sel.add(n); c.classList.toggle("on", sel.has(n)); $("#ibGo", box).disabled = !sel.size; });
  $("#ibGo", box).onclick = async () => {
    try {
      const out = await api.files_inbox_import(p.id, [...sel], {tooth: ($("#ibTooth", box) || {}).value || ""});
      closeModal(); toast(`Добавлено снимков: ${out.length}`); P = await api.patient(p.id); renderPatient("files");
    } catch (e) { toast(errText(e), true); }
  };
}

/* ------------------------------------------------------------ viewer */
async function openFileViewer(id) {
  const x = PF.items.find(i => i.id === id); if (!x) return;
  const edit = canAny("medcard_edit", "patients_edit");
  const box = modal(`<div class="m-h"><h3>${esc(x.title || x.orig_name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b fv">
      <div class="fv-stage" id="fvStage"><div class="scan"><i></i>Открываем…</div></div>
      <div class="fv-side">
        ${x.image ? `<div class="fv-tools">
          <button class="btn ghost small" data-z="-">−</button><button class="btn ghost small" data-z="fit">По размеру</button><button class="btn ghost small" data-z="+">+</button>
          <button class="btn ghost small" id="fvRot" title="Повернуть">↻</button><button class="btn ghost small" id="fvInv">Негатив</button></div>
          <label class="fl">Яркость<input type="range" id="fvB" min="40" max="200" value="100"></label>
          <label class="fl">Контраст<input type="range" id="fvC" min="40" max="250" value="100"></label>
          <div class="fv-cmp"><b>Сравнить</b><div class="fv-strip">${PF.items.filter(o => o.image && o.id !== id).map(o => `<button data-cmp="${esc(o.id)}" title="${esc(o.title || o.orig_name)} · ${esc(fmtDate(o.taken_at || o.created_at))}"><img alt="" data-th2="${esc(o.id)}"></button>`).join("") || `<span class="muted">Других снимков нет</span>`}</div></div>` : ""}
        <dl class="kv fv-kv">${kvRow("Тип", x.kind_text)}${kvRow("Зуб", x.tooth)}${kvRow("Дата снимка", x.taken_at ? fmtDate(x.taken_at) : "")}${kvRow("Добавлен", fmtDT(x.created_at) + (x.created_by ? ", " + x.created_by : ""))}
          ${kvRow("Файл", `${x.orig_name} · ${BK_SIZE(x.size)}${x.width ? ` · ${x.width}×${x.height}` : ""}`)}${kvRow("Аппарат", [x.meta.Manufacturer, x.meta.ManufacturerModelName].filter(Boolean).join(" "))}${kvRow("Примечание", x.note)}</dl>
        ${edit ? `<div class="row"><button class="btn ghost small" id="fvEdit">Изменить описание</button><button class="btn ghost small danger" id="fvDel">Удалить</button></div>` : ""}
      </div>
    </div>`, {wide: true});
  box.classList.add("fv-modal");
  const stage = $("#fvStage", box);
  if (!x.image) {
    if (x.ext === ".pdf") {
      const f = await api.file_get(id, "orig");
      const blob = await (await fetch(f.url)).blob();
      stage.innerHTML = `<iframe class="fv-pdf" src="${URL.createObjectURL(new Blob([blob], {type: "application/pdf"}))}"></iframe>`;
    } else stage.innerHTML = `<div class="empty"><b>Файл ${esc(x.ext.toUpperCase().slice(1))}</b><span>Просмотр этого формата в программе пока не поддерживается — файл хранится в карте пациента.</span></div>`;
  } else {
    const f = await api.file_get(id, "view");
    const v = {z: 1, x: 0, y: 0, rot: 0, inv: false, cmp: null, split: 50};
    stage.innerHTML = `<div class="fv-pan" id="fvPan"><img id="fvImg" alt="" src="${f.url}" draggable="false"><img id="fvImg2" alt="" hidden draggable="false"></div>
      <input type="range" class="fv-split" id="fvSplit" min="0" max="100" value="50" hidden><div class="fv-labels" id="fvLabels" hidden><span>${esc(fmtDate(x.taken_at || x.created_at))}</span><span id="fvL2"></span></div>`;
    const pan = $("#fvPan", box), img = $("#fvImg", box), img2 = $("#fvImg2", box);
    const apply = () => {
      const filt = `brightness(${$("#fvB", box).value}%) contrast(${$("#fvC", box).value}%)${v.inv ? " invert(1)" : ""}`;
      pan.style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.z}) rotate(${v.rot}deg)`;
      img.style.filter = filt; img2.style.filter = filt;
      img2.style.clipPath = `inset(0 0 0 ${v.split}%)`;
    };
    $$("[data-z]", box).forEach(b => b.onclick = () => { if (b.dataset.z === "fit") Object.assign(v, {z: 1, x: 0, y: 0}); else v.z = Math.max(0.3, Math.min(8, v.z * (b.dataset.z === "+" ? 1.25 : 0.8))); apply(); });
    $("#fvRot", box).onclick = () => { v.rot = (v.rot + 90) % 360; apply(); };
    $("#fvInv", box).onclick = e => { v.inv = !v.inv; e.target.classList.toggle("on", v.inv); apply(); };
    $("#fvB", box).oninput = apply; $("#fvC", box).oninput = apply;
    stage.onwheel = e => { e.preventDefault(); v.z = Math.max(0.3, Math.min(8, v.z * (e.deltaY < 0 ? 1.12 : 0.89))); apply(); };
    let drag = null;
    stage.onpointerdown = e => { if (e.target.id === "fvSplit") return; drag = {x: e.clientX - v.x, y: e.clientY - v.y}; stage.setPointerCapture?.(e.pointerId); stage.classList.add("grab"); };
    stage.onpointermove = e => { if (drag) { v.x = e.clientX - drag.x; v.y = e.clientY - drag.y; apply(); } };
    stage.onpointerup = () => { drag = null; stage.classList.remove("grab"); };
    $("#fvSplit", box).oninput = e => { v.split = +e.target.value; apply(); };
    const others = PF.items.filter(o => o.image && o.id !== id).map(o => o.id);
    if (others.length) api.file_thumbs(others).then(m => { for (const [k, url] of Object.entries(m)) { const im = $(`img[data-th2="${k}"]`, box); if (im) im.src = url; } }).catch(() => {});
    $$("[data-cmp]", box).forEach(b => b.onclick = async () => {
      const on = v.cmp === b.dataset.cmp;
      $$("[data-cmp]", box).forEach(o => o.classList.remove("on"));
      if (on) { v.cmp = null; img2.hidden = true; $("#fvSplit", box).hidden = true; $("#fvLabels", box).hidden = true; return; }
      const o = PF.items.find(i => i.id === b.dataset.cmp);
      img2.src = (await api.file_get(o.id, "view")).url; v.cmp = o.id; b.classList.add("on");
      img2.hidden = false; $("#fvSplit", box).hidden = false; $("#fvLabels", box).hidden = false;
      $("#fvL2", box).textContent = fmtDate(o.taken_at || o.created_at); apply();
    });
    apply();
  }
  const ed = $("#fvEdit", box);
  if (ed) ed.onclick = async () => {
    const vals = await askInput("Описание файла", [{label: "Название", value: x.title || ""}, {label: "Зуб", value: x.tooth || "", required: false},
      {label: "Дата снимка", value: x.taken_at || "", type: "date", required: false}, {label: "Примечание", value: x.note || "", required: false}]);
    if (!vals) return;
    try { await api.file_update(x.id, {title: vals[0], tooth: vals[1], taken_at: vals[2], note: vals[3], kind: x.kind}); closeModal(); toast("Сохранено"); P = await api.patient(PF.pid); renderPatient("files"); }
    catch (e) { toast(errText(e), true); }
  };
  const dl = $("#fvDel", box);
  if (dl) dl.onclick = async () => {
    if (!(await ask("Удалить файл из карты?", {danger: true, ok: "Удалить", text: `${x.title || x.orig_name}\n\nФайл уйдёт в папку удалённых программы и пропадёт из карты пациента.`}))) return;
    await api.file_delete(x.id); closeModal(); toast("Файл удалён из карты"); P = await api.patient(PF.pid); renderPatient("files");
  };
}

/* ------------------------------------------------------------ settings: visiograph folder */
async function loadFilesSettings() {
  const box = $("#filesBody"); if (!box) return;
  let st; try { st = await api.files_settings(); } catch (e) { return; }
  const pw = window.pywebview && window.pywebview.api;
  let local = !!(pw && pw.choose_folder);
  if (local && pw.is_client) { try { local = !(await pw.is_client()); } catch (e) { local = false; } }
  box.innerHTML = `<div class="form"><label class="wide">Папка снимков визиографа<span class="bk-dir"><input class="input" id="fsIn" value="${esc(st.inbox)}" placeholder="Папка, куда программа визиографа сохраняет снимки">${local ? `<button class="btn ghost small" id="fsPick" type="button">Выбрать…</button>` : ""}</span></label></div>
    <div class="row"><button class="btn" id="fsSaveIn">Сохранить</button><span class="msg" id="fsMsgIn"></span></div>
    <p class="hint">Снимки пациентов хранятся в <code>${esc(st.folder)}</code>. Размер одного файла — до ${st.max_mb} МБ.</p>`;
  const pick = $("#fsPick", box); if (pick) pick.onclick = async () => { const d = await pw.choose_folder(); if (d) $("#fsIn", box).value = d; };
  $("#fsSaveIn", box).onclick = async () => {
    try { const r = await api.files_settings_save({inbox: $("#fsIn", box).value.trim()}); PF.inbox = r.inbox; PF.kinds = null; toast("Папка снимков сохранена"); }
    catch (e) { const m = $("#fsMsgIn", box); m.textContent = errText(e); m.className = "msg bad"; }
  };
}
