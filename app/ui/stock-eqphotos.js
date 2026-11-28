"use strict";
/* 3.16 «Фото оборудования» с компьютера. The gallery of the card: several photos, one main (the picture of the register, the
   lists and the cards view), added by a button or by dropping files on the card, «Сделать главным», deleting after a
   question. The strip of photos of the form of a new piece and of a line of a receipt: the photos are stored at once (made
   smaller, they go to the other computers like the other stock photos) and the card gets them when it is saved; the first
   one is the main one. */
const EQP_I = {
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.8 2.5 5.1 5.6.8-4 4 .9 5.6-5-2.6-5 2.6.9-5.6-4-4 5.6-.8z"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  drop: '<svg viewBox="0 0 24 24"><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 19.5h14"/></svg>',
  cam: '<svg viewBox="0 0 24 24"><path d="M4 8h3l1.6-2.5h6.8L17 8h3v11H4z"/><circle cx="12" cy="13.2" r="3.4"/></svg>',
  prev: '<svg viewBox="0 0 24 24"><path d="M15 5.5 8.5 12l6.5 6.5"/></svg>',
  next: '<svg viewBox="0 0 24 24"><path d="m9 5.5 6.5 6.5L9 18.5"/></svg>',
};
const EQP_STRIP_MAX = 12;  // photos of a new piece or of one line of a receipt (the server keeps as many)
const eqPhHasFiles = ev => [...((ev.dataTransfer && ev.dataTransfer.types) || [])].includes("Files");

/** Picked or dropped files → pictures made smaller here (the server makes them smaller again); what is not a photo is said. */
async function eqPhRead(files) {
  const out = [];
  for (const f of files) {
    if (!(f.type || "").startsWith("image/") && !/\.(jpe?g|png|webp|gif|bmp|tiff?)$/i.test(f.name || "")) { toast(`${f.name}: это не фото`, true); continue; }
    if (f.size > 15 * 1024 * 1024) { toast(`${f.name}: больше 15 МБ — выберите снимок поменьше`, true); continue; }
    let data;
    try { data = await shrinkImage(f, 1600); }
    catch (x) { data = await new Promise((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = bad; rd.readAsDataURL(f); }); }
    out.push({name: f.name || "фото.jpg", data});
  }
  return out;
}
function eqPhPick(onFiles) {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = "image/*"; inp.multiple = true;
  inp.onchange = () => { const files = [...(inp.files || [])]; if (files.length) onFiles(files); };
  inp.click();
}
/** `zone` takes dropped photo files and is lit (.eqp-over) while they are over it. */
function eqPhDrop(zone, onFiles) {
  let depth = 0;
  const off = () => { depth = 0; zone.classList.remove("eqp-over"); };
  zone.ondragenter = ev => { if (!eqPhHasFiles(ev)) return; ev.preventDefault(); depth++; zone.classList.add("eqp-over"); };
  zone.ondragover = ev => { if (!eqPhHasFiles(ev)) return; ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; };
  zone.ondragleave = () => { if (--depth <= 0) off(); };
  zone.ondrop = ev => { if (!eqPhHasFiles(ev)) return; ev.preventDefault(); off(); onFiles([...ev.dataTransfer.files]); };
}
// a file dropped beside a drop zone must not open in the window in place of the program
document.addEventListener("dragover", ev => { if (eqPhHasFiles(ev) && !ev.defaultPrevented) { ev.preventDefault(); ev.dataTransfer.dropEffect = "none"; } });
document.addEventListener("drop", ev => { if (eqPhHasFiles(ev) && !ev.defaultPrevented) ev.preventDefault(); });

/* ------------------------------------------------------------ the gallery of the card */
function eqGalleryHtml(e, c) {
  const g = e.gallery || [], i = Math.min(EQ.gal || 0, Math.max(0, g.length - 1)), cur = g[i], edit = !!c.edit;
  const def = cur ? "" : eqPic(e.name, e.category);  // 3.18: the picture by name until the first photo
  return `<div class="eqc-gal eqp-gal" id="eqGal">
    <div class="eqc-photo ${cur ? "" : "empty"} ${def ? "def" : ""}" id="eqPhoto" ${cur ? `data-big="${esc(cur.file_id)}"` : ""}>${def ? `<img class="eqp-defpic" src="${def}" alt="" title="Картинка по названию — добавьте своё фото">` : edit && !cur ? "" : EQI.ph}
      ${cur ? `<button class="eqc-exp" id="eqExp" title="Открыть фото">${EQI.expand}</button>` : ""}
      ${cur && cur.main && g.length > 1 ? `<span class="eqp-main" title="Это фото видно в реестре">${EQP_I.star}Главное</span>` : ""}
      ${cur && edit ? `<div class="eqp-tools">${cur.main ? "" : `<button id="eqPhMain" title="Сделать главным — это фото будет видно в реестре">${EQP_I.star}</button>`}<button id="eqPhDel" class="del" title="Удалить фото">${EQP_I.trash}</button></div>` : ""}
      ${edit && !cur ? `<button class="eqp-empty" id="eqPh0">${EQP_I.cam}<b>Добавить фото</b><small>или перетащите файлы сюда</small></button>` : ""}
      ${edit ? `<div class="eqp-hint">${EQP_I.drop}<b>Отпустите, чтобы добавить фото</b></div>` : ""}</div>
    ${g.length > 1 || (edit && g.length) ? `<div class="eqp-thumbs">${g.map((p, k) => `<button class="eqp-th ${k === i ? "on" : ""}" data-gal="${k}" title="${p.main ? "Главное фото" : `Фото ${k + 1}`}">${phHtml(p.file_id)}${p.main ? `<i>${EQP_I.star}</i>` : ""}</button>`).join("")}${edit ? `<button class="eqp-th add" id="eqPhAdd" title="Добавить фото — или перетащите файлы на карточку">${EQP_I.plus}</button>` : ""}</div>` : ""}
  </div>`;
}
/** Wires the gallery: the big photo, the thumbnails (switched here, without asking the server), adding and dropping,
    the main photo and deleting. `zone` is where files may be dropped (the top of the card). */
async function eqGalleryWire(root, e, c, zone) {
  const gal = $("#eqGal", root); if (!gal) return;
  const g = e.gallery || [], i = Math.min(EQ.gal || 0, Math.max(0, g.length - 1)), cur = g[i];
  const redraw = () => { gal.outerHTML = eqGalleryHtml(e, c); eqGalleryWire(root, e, c, null); };
  const on = (s, f) => { const el = $(s, gal); if (el) el.onclick = f; };
  const add = files => eqPhAddFiles(e, files);
  on("#eqPh0", () => eqPhPick(add)); on("#eqPhAdd", () => eqPhPick(add));
  $$("[data-gal]", gal).forEach(b => b.onclick = () => { EQ.gal = +b.dataset.gal; redraw(); });
  on("#eqPhMain", async ev => { ev.stopPropagation();
    try { await api.equipment_photo_main(e.id, cur.file_id); EQ.gal = 0; toast("Главное фото выбрано — оно видно в реестре"); eqCard(); } catch (x) { toast(errText(x), true); } });
  on("#eqPhDel", async ev => { ev.stopPropagation();
    const text = cur.main && g.length > 1 ? "Это главное фото — главным станет следующее. Запись останется в истории карточки." : "Запись об этом останется в истории карточки.";
    if (!await ask("Удалить это фото из карточки?", {danger: true, ok: "Удалить", text})) return;
    try { await api.equipment_photo_delete(e.id, cur.file_id); EQ.gal = 0; toast("Фото удалено"); eqCard(); } catch (x) { toast(errText(x), true); } });
  if (c.edit && zone) { zone.classList.add("eqp-zone"); eqPhDrop(zone, add); }
  loadThumbs(gal);
  const big = $("#eqPhoto", gal);
  if (cur) {
    try {
      const ph = await api.stock_photo(cur.file_id);
      if (!big.isConnected || big.dataset.big !== cur.file_id) return;
      big.insertAdjacentHTML("afterbegin", `<img src="${ph.url}" alt="">`); big.classList.add("has");
      const open = () => eqPhViewer(e, i);
      const ex = $("#eqExp", gal); if (ex) ex.onclick = ev => { ev.stopPropagation(); open(); };
      big.onclick = ev => { if (ev.target === big || ev.target.tagName === "IMG") open(); };
    } catch (x) { /* the photo did not come from the other computer yet */ }
  }
}
async function eqPhAddFiles(e, files) {
  const list = await eqPhRead(files); if (!list.length) return;
  const gal = $("#eqGal"); if (gal) gal.classList.add("eqp-busy");
  const before = (e.gallery || []).length;
  let n = 0;
  for (const f of list) { try { await api.equipment_photo_add(e.id, f.name, f.data); n++; } catch (x) { toast(`${f.name}: ${errText(x)}`, true); } }
  if (gal) gal.classList.remove("eqp-busy");
  if (!n) return;
  toast(n > 1 ? `Добавлено фото: ${n}` : before ? "Фото добавлено" : "Фото добавлено — оно главное и видно в реестре");
  if (EQ.id === e.id) { EQ.gal = before; eqCard(); }
}
/** The photo full size, with the others of the card a click or an arrow key away. */
async function eqPhViewer(e, start) {
  const g = e.gallery || []; let i = start;
  const box = modal(`<div class="m-h"><h3>${esc(e.name)}</h3><span class="muted" id="pvN"></span><button class="x" data-close>×</button></div>
    <div class="m-b eqc-view eqp-view">${g.length > 1 ? `<button class="eqp-nav prev" id="pvP" title="Предыдущее">${EQP_I.prev}</button><button class="eqp-nav next" id="pvX" title="Следующее">${EQP_I.next}</button>` : ""}<img id="pvI" alt=""></div>`, {wide: true});
  const show = async () => {
    $("#pvN", box).textContent = g.length > 1 ? `${i + 1} из ${g.length}${g[i].main ? " · главное" : ""}` : "";
    try { const ph = await api.stock_photo(g[i].file_id); const im = $("#pvI", box); if (im) im.src = ph.url; } catch (x) { toast(errText(x), true); }
  };
  const go = d => { i = (i + d + g.length) % g.length; show(); };
  const p = $("#pvP", box), x = $("#pvX", box); if (p) p.onclick = () => go(-1); if (x) x.onclick = () => go(1);
  const keys = ev => { if (!box.isConnected || $("#modal").hidden || !$("#pvI", box)) { document.removeEventListener("keydown", keys); return; }
    if (g.length > 1 && ev.key === "ArrowLeft") go(-1); else if (g.length > 1 && ev.key === "ArrowRight") go(1); };
  document.addEventListener("keydown", keys);
  show();
}

/* ------------------------------------------------------------ a strip of photos (new piece, a line of a receipt) */
/** Draws into `el` the photos `ids` (the first is the main one) with «+» and the drop of files; every change goes to onChange.
    opts.small — the compact strip of a table row; opts.ask — a removal is asked first (the photos already saved). */
function eqPhStrip(el, ids, onChange, opts = {}) {
  if (!el) return;
  let list = [...(ids || [])];
  const draw = () => {
    el.className = `eqp-strip ${opts.small ? "sm" : ""}`;
    el.innerHTML = list.map((id, k) => `<span class="eqp-sp ${k === 0 ? "main" : ""}" title="${k === 0 ? "Главное фото — видно в реестре" : "Сделать главным"}" data-pk="${k}">${phHtml(id)}${k === 0 && list.length > 1 ? `<i>${EQP_I.star}</i>` : ""}<button type="button" class="eqp-x" data-x="${k}" title="Убрать фото">×</button></span>`).join("")
      + (list.length < EQP_STRIP_MAX ? `<button type="button" class="eqp-sp add" title="Добавить фото — или перетащите файлы сюда">${EQP_I.plus}${opts.small || list.length ? "" : "<span>Добавить фото</span>"}</button>` : "")
      + (!opts.small && !list.length ? `<small class="muted">или перетащите файлы сюда · первое фото — главное, оно видно в реестре</small>` : "");
    loadThumbs(el);
    $$("[data-pk]", el).forEach(s => s.onclick = ev => { if (ev.target.closest("[data-x]")) return; const k = +s.dataset.pk; if (!k) return;
      list = [list[k], ...list.filter((_, j) => j !== k)]; onChange(list); draw(); });
    $$("[data-x]", el).forEach(b => b.onclick = async ev => { ev.stopPropagation();
      if (opts.ask && !await ask("Убрать это фото?", {danger: true, ok: "Убрать"})) return;
      list = list.filter((_, j) => j !== +b.dataset.x); onChange(list); draw(); });
    const a = $(".eqp-sp.add", el); if (a) a.onclick = () => eqPhPick(up);
  };
  const up = async files => {
    const room = EQP_STRIP_MAX - list.length;
    if (room <= 0) return toast(`Не больше ${EQP_STRIP_MAX} фото`, true);
    const pics = (await eqPhRead(files)).slice(0, room); if (!pics.length) return;
    el.classList.add("eqp-busy");
    for (const f of pics) {
      try { const r = await api.equipment_photo_upload(f.name, f.data); if (r.thumb) PHOTO[r.file_id] = r.thumb; if (!list.includes(r.file_id)) list.push(r.file_id); }
      catch (x) { toast(`${f.name}: ${errText(x)}`, true); }
    }
    el.classList.remove("eqp-busy"); onChange(list); draw();
  };
  eqPhDrop(el, up);
  draw();
}
