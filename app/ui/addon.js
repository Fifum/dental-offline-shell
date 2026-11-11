"use strict";
/* 3.2: the «Надстройка над Dentist Plus» mode. Dentist Plus is the clinic's official system; this program is the
   internal one. With the mode on (body.addon):
   - sections from Dentist Plus carry a discreet «из Dentist Plus» (.dp-src);
   - our medical entries carry «Черновик для Dentist Plus — официальная запись в Dentist Plus» (.dp-draft);
   - official document templates are signed «Не для контролирующих органов…» on screen and on paper, or hidden;
   - SaaS panels ([data-saas]: cloud for many clinics with its subscription, moving a base in from IDENT) are hidden.
   Labels are always in the page and shown by CSS, so switching the mode needs no reload. */
const ADDON_DEF = {official: "Не для контролирующих органов — официальный документ печатайте из Dentist Plus",
  draft: "Черновик для Dentist Plus — официальная запись в Dentist Plus", source: "из Dentist Plus"};
const addonOn = () => !!(S.settings && S.settings.addon_mode !== false);
const addonNote = k => ((S.settings && S.settings.addon_notes) || ADDON_DEF)[k] || ADDON_DEF[k];
/** «official» | «draft» | «internal» for a document template id (only with the mode on). */
function addonDocKind(tid) {
  if (!addonOn() || !tid) return "internal";
  if ((S.settings.addon_official || []).includes(tid)) return "official";
  if ((S.settings.addon_draft || []).includes(tid)) return "draft";
  return "internal";
}
/** Small tag next to a section title: the data comes from Dentist Plus. */
function dpSrc(what) {
  return `<span class="dp-src" title="${esc(what ? what + " приходят из Dentist Plus — официальной системы клиники" : "Данные из Dentist Plus — официальной системы клиники")}">${esc(addonNote("source"))}</span>`;
}
/** A line over our medical entries: a draft, the official entry is the one in Dentist Plus. */
function dpDraft(extra) {
  return `<div class="dp-draft" role="note"><svg viewBox="0 0 24 24"><path d="M6 3.5h9l4 4v13H6z"/><path d="M14.5 3.5V8H19M9 13h6M9 16.5h4"/></svg><span>${esc(addonNote("draft"))}${extra ? `<small>${esc(extra)}</small>` : ""}</span></div>`;
}
/** A line over an official document: not for inspectors, print it from Dentist Plus. */
function dpOfficial() {
  return `<div class="dp-official" role="note"><svg viewBox="0 0 24 24"><path d="M12 3 2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg><span>${esc(addonNote("official"))}</span></div>`;
}
/** The same words at the bottom of the printed sheet (only official / draft documents, only with the mode on). */
function addonPrintFoot(tid) {
  const k = addonDocKind(tid);
  if (k === "internal") return "";
  return `<div class="dp-print-foot">${esc(addonNote(k))}</div>`;
}
function applyAddon() {
  const on = addonOn();
  document.body.classList.toggle("addon", on);
  document.body.classList.toggle("addon-hide-docs", on && S.settings.addon_docs === "hide");
  const nav = typeof SET_SECS !== "undefined" && SET_SECS.find(s => s[0] === "data");
  if (nav) nav[2] = on ? "Копии, шифрование" : "Копии, шифрование, облако, перенос базы";
  const ih = $("#importHint");
  if (ih) ih.textContent = on ? "Пациенты приходят из Dentist Plus сами — по записям на приём. Кнопка ниже скачает всю базу пациентов, а не только тех, у кого есть записи."
    : "Из IDENT, Dentist Plus или любой таблицы: выгрузите список пациентов в Excel (.xlsx) или CSV и выберите файл. Программа сама найдёт колонки (ФИО, телефон, дата рождения, номер карты), покажет, что загрузит, и пропустит пациентов, которые уже есть.";
  const ip = $("#importPanel h3");
  if (ip) ip.textContent = on ? "Вся база пациентов из Dentist Plus" : "Перенос базы пациентов";
  if (typeof setDraw === "function" && $("#setNav")) setDraw();
}
/* the 3-second status: the director may switch the mode on another computer of a client-server clinic */
function addonStatus(st) {
  const a = st && st.addon;
  if (!a || !S.settings) return;
  const was = [S.settings.addon_mode, S.settings.addon_docs].join();
  Object.assign(S.settings, a);
  if (was !== [a.addon_mode, a.addon_docs].join()) applyAddon();
}

/* ------------------------------------------------------------ Settings → Dentist Plus → «Режим работы» */
function loadAddonPanel() {
  const box = $("#addonBody"); if (!box) return;
  const s = S.settings || {}, on = s.addon_mode !== false, hide = s.addon_docs === "hide";
  const dir = !!(ME && ME.role === "director");
  box.innerHTML = `
    <label class="switch-row"><input type="checkbox" id="adOn" ${on ? "checked" : ""} ${dir ? "" : "disabled"}><span class="sw"></span>Надстройка над Dentist Plus</label>
    <p class="hint">Официальная система клиники — Dentist Plus: медкарта и документы для проверок хранятся и печатаются там. Эта программа — внутренняя: деньги, сотрудники, CRM, склад, аналитика, ИИ.
      В этом режиме разделы из Dentist Plus помечены «из Dentist Plus», медицинские записи программы — «черновик для Dentist Plus», а облако для многих клиник и перенос базы из IDENT спрятаны.
      Сеть клиники и обновления работают как обычно.</p>
    <div class="ad-docs" ${on ? "" : "hidden"}>
      <div class="fl-t">Официальные документы (договор, согласия, 043/у, выписка, справки, справка для налогового вычета)</div>
      <div class="seg" id="adDocs"><button type="button" data-d="mark" class="${hide ? "" : "on"}" ${dir ? "" : "disabled"}>Подписать «не для контролирующих органов»</button><button type="button" data-d="hide" class="${hide ? "on" : ""}" ${dir ? "" : "disabled"}>Скрыть</button></div>
      <p class="hint">Внутренние документы — анкета, памятка, презентация плана лечения, квитанция — остаются как есть.</p>
    </div>
    ${dir ? "" : `<div class="muted">Переключает только директор.</div>`}
    <span class="msg" id="adMsg"></span>`;
  if (!dir) return;
  const save = async (upd, text) => {
    try {
      const r = await api.save_settings(upd);
      Object.assign(S.settings, await api.ui_settings());
      S.settings.has_password = r.has_password;
      applyAddon(); loadAddonPanel(); toast(text);
    } catch (e) { toast(errText(e), true); loadAddonPanel(); }
  };
  $("#adOn", box).onchange = async e => {
    const v = e.target.checked;
    if (!v && !(await ask("Выключить режим «Надстройка над Dentist Plus»?", {icon: "warn", ok: "Выключить",
      text: "Пометки «из Dentist Plus» и «черновик» исчезнут, официальные шаблоны документов будут без подписи, появятся облако и перенос базы из IDENT. Делайте так, только если программа становится основной системой клиники."}))) { e.target.checked = true; return; }
    save({addon_mode: v}, v ? "Режим «Надстройка над Dentist Plus» включён" : "Режим надстройки выключен — программа работает как раньше");
  };
  $$("#adDocs [data-d]", box).forEach(b => b.onclick = () => {
    if (b.classList.contains("on")) return;
    save({addon_docs: b.dataset.d}, b.dataset.d === "hide" ? "Официальные шаблоны скрыты — печатайте их из Dentist Plus" : "Официальные шаблоны подписаны «не для контролирующих органов»");
  });
}
