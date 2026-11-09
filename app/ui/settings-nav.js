"use strict";
/* 2.13: settings by sections — a list on the left shows one section at a time; the search above finds a setting
   in any section by its words. The chosen section is remembered on this computer. */
const SET_SECS = [
  ["general", "Общие", "Оформление, сеть клиники, обновления"],
  ["dp", "Dentist Plus", "Подключение, перенос, что хранить"],
  ["ai", "Голос и ИИ", "Диктовка, голоса, ИИ на компьютере"],
  ["money", "Касса и оплаты", "Касса (ККТ), бонусы, сертификаты, СБП"],
  ["patients", "Снимки и планшет", "Визиограф, планшет для пациентов"],
  ["data", "Данные и защита", "Копии, шифрование, облако, перенос базы"],
  ["help", "Помощь", "Отчёт для разработчика"],
];
const SET_ICON = {
  general: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>',
  dp: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.6-4.4M4 4v3.5h3.5M4 13a8 8 0 0 0 14.6 4.4M20 20v-3.5h-3.5"/></svg>',
  ai: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg>',
  money: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M7 15h3"/></svg>',
  patients: '<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M10 18h4"/></svg>',
  data: '<svg viewBox="0 0 24 24"><path d="M12 3.5 5 6v5.5c0 4.2 3 7.6 7 9 4-1.4 7-4.8 7-9V6z"/><path d="m9 12 2 2 4-4"/></svg>',
  help: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.8M12 17.2v.01"/></svg>',
};
let setSec = "general";
try { setSec = localStorage.getItem("dd.setSec") || setSec; } catch (e) { /* private mode */ }

function setPanels() { return $$("#view-settings .settings > [data-sec]"); }
function setDraw() {
  const q = $("#setSearch").value.trim().toLowerCase().replace(/ё/g, "е");
  const words = q.split(/\s+/).filter(Boolean);
  const hit = {};
  setPanels().forEach(p => {
    const text = p.textContent.toLowerCase().replace(/ё/g, "е") + " " + [...p.querySelectorAll("input,select,textarea")].map(x => x.placeholder || "").join(" ").toLowerCase();
    const show = words.length ? words.every(w => text.includes(w)) : p.dataset.sec === setSec;
    p.classList.toggle("set-off", !show);
    if (words.length && show) hit[p.dataset.sec] = (hit[p.dataset.sec] || 0) + 1;
  });
  $("#setNav").innerHTML = SET_SECS.map(([k, t, sub]) => `<button type="button" data-sec="${k}" class="${!words.length && k === setSec ? "on" : ""}${words.length && !hit[k] ? " dim" : ""}">
      ${SET_ICON[k]}<span><b>${esc(t)}</b><small>${esc(sub)}</small></span>${words.length && hit[k] ? `<i class="cnt">${hit[k]}</i>` : ""}</button>`).join("");
  $$("#setNav button").forEach(b => b.onclick = () => settingsGo(b.dataset.sec));
  let none = $("#setNone");
  if (!none) { none = document.createElement("div"); none.id = "setNone"; none.className = "empty"; $("#view-settings .settings").appendChild(none); }
  none.hidden = !words.length || Object.keys(hit).length > 0;
  none.innerHTML = `<b>Ничего не нашлось</b><span>Попробуйте другое слово или выберите раздел слева</span>`;
}
/** Open a section (or the section of a panel: settingsGo("updatePanel")) and scroll to the panel. */
function settingsGo(secOrPanel) {
  const panel = document.getElementById(secOrPanel);
  setSec = panel && panel.dataset.sec ? panel.dataset.sec : SET_SECS.some(s => s[0] === secOrPanel) ? secOrPanel : setSec;
  try { localStorage.setItem("dd.setSec", setSec); } catch (e) { /* ignore */ }
  $("#setSearch").value = "";
  setDraw();
  const box = $("#view-settings .settings");
  if (panel) setTimeout(() => panel.scrollIntoView({behavior: "smooth", block: "start"}), 60);
  else if (box) box.scrollTop = 0;
}
$("#setSearch").addEventListener("input", setDraw);
$("#setSearch").addEventListener("keydown", e => { if (e.key === "Escape") { e.target.value = ""; setDraw(); } });
setDraw();
