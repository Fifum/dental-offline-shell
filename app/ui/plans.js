"use strict";
/* Treatment plan presentation for the patient (2.9.0): the tooth formula with the plan teeth and stage numbers,
   the options «эконом / стандарт / премиум» side by side, stages with services, signatures.
   One HTML page serves the screen preview, printing, the PDF (headless Edge on the computer with the program),
   the document in the patient card and the patient tablet (the patient chooses the option and signs there). */

/* paper styles, scoped to .pp so the page looks the same inside the app (light or dark), on the tablet and in the PDF */
const PP_CSS = `
.pp{--panel:#fff;--line:#E5E3DF;--ink:#1E1E1E;--ink2:#4A4744;--muted:#8A8784;--accent-soft:#F5ECEA;--accent-line:#E7CFCB;--danger:#B3261E;--warn:#A8742A;
  --pp-accent:#6D0100;--pp-soft:#F7F1EF;--pp-line:#E8DFDA;color:var(--ink);background:#fff;font:13px/1.45 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  color-scheme:light;text-align:left;max-width:794px;margin:0 auto;padding:34px 38px 30px;box-sizing:border-box}
.pp *{box-sizing:border-box}
.pp .pp-h{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;border-bottom:2px solid var(--pp-accent);padding-bottom:12px}
.pp .pp-clinic{font:500 22px/1.15 "Playfair Display SC",Georgia,serif;letter-spacing:.02em;color:var(--pp-accent)}
.pp .pp-clinic small{display:block;font:12px/1.4 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;color:var(--muted);letter-spacing:0;margin-top:4px}
.pp .pp-ttl{text-align:right}
.pp .pp-ttl b{display:block;font:500 20px/1.1 "Playfair Display SC",Georgia,serif;letter-spacing:.03em}
.pp .pp-ttl span{color:var(--muted);font-size:12px}
.pp .pp-who{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 6px}
.pp .pp-who div{background:var(--pp-soft);border-radius:8px;padding:8px 11px}
.pp .pp-who small{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.pp .pp-who b{font-weight:700}
.pp h3{font:500 15px/1.2 "Playfair Display SC",Georgia,serif;letter-spacing:.03em;margin:18px 0 8px;color:var(--ink)}
.pp .pp-f{border:1px solid var(--pp-line);border-radius:10px;padding:2px 0 6px;overflow:hidden}
.pp .pp-f .formula{zoom:.86;padding:12px 6px 4px;overflow:visible}
.pp .pp-f .ft{cursor:default}
.pp .pp-f .legend{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:center;font-size:11px;color:var(--ink2);padding:2px 10px 0}
.pp .pp-f .legend span{display:inline-flex;align-items:center;gap:5px}
.pp .pp-f .legend i{display:inline-block;width:11px;height:11px}
.pp .pp-vars{display:grid;gap:10px}
.pp .pp-var{border:1px solid var(--pp-line);border-radius:10px;padding:12px 13px;position:relative;break-inside:avoid}
.pp .pp-var.on{border-color:var(--pp-accent);box-shadow:inset 0 0 0 1px var(--pp-accent)}
.pp .pp-var .nm{font:500 15px/1.2 "Playfair Display SC",Georgia,serif;letter-spacing:.03em}
.pp .pp-var .sum{font-size:21px;font-weight:700;margin:6px 0 4px;font-variant-numeric:tabular-nums;color:var(--pp-accent)}
.pp .pp-var .ln{font-size:12px;color:var(--ink2)}
.pp .pp-var .ln b{color:var(--ink);font-weight:700}
.pp .pp-var .nt{font-size:12px;margin-top:6px;color:var(--ink2)}
.pp .pp-var .mark{position:absolute;top:10px;right:10px;background:var(--pp-accent);color:#fff;border-radius:10px;font-size:10.5px;padding:1px 8px}
.pp table.pp-t{width:100%;border-collapse:collapse;margin:2px 0 4px;font-size:12.5px;table-layout:fixed}
.pp table.pp-t col.c-t{width:64px}.pp table.pp-t col.c-q{width:56px}.pp table.pp-t col.c-s{width:112px}
.pp table.pp-t th{text-align:left;font-weight:700;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--pp-line);padding:5px 6px}
.pp table.pp-t td{border-bottom:1px solid #F0EBE8;padding:5px 6px;vertical-align:top}
.pp table.pp-t td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.pp table.pp-t td.t{width:56px;white-space:nowrap;font-weight:700}
.pp table.pp-t tr.st td{background:var(--pp-soft);font-weight:700;color:var(--ink2);border-bottom:0}
.pp table.pp-t tr.tot td{border-bottom:0;font-weight:700;padding-top:7px}
.pp .pp-sub{margin:12px 0 2px;font-weight:700;break-after:avoid;page-break-after:avoid}
.pp .pp-sub span{color:var(--muted);font-weight:400}
.pp .pp-blk{break-inside:avoid;page-break-inside:avoid}
.pp .pp-note{font-size:11.5px;color:var(--muted);margin-top:12px}
.pp .pp-com{background:var(--pp-soft);border-radius:8px;padding:8px 11px;margin-top:10px}
.pp .pp-sign{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:26px;font-size:12px}
.pp .pp-sign div{border-top:1px solid var(--ink);padding-top:4px;color:var(--ink2)}
.pp .pp-choice{margin-top:14px;font-size:14px}
@media print{.pp{padding:0;max-width:none}.pp .pp-f,.pp .pp-var,.pp table.pp-t tr{break-inside:avoid}}
`;

let PP_TEETH_CSS = null, PP_FONT = null;
async function ppTeethCss() {
  if (PP_TEETH_CSS !== null) return PP_TEETH_CSS;
  try {
    let css = await (await fetch("styles-teeth.css")).text();
    css = css.replace(/@media screen\{[\s\S]*?\n\}\n/, "");                 /* dark tooth colours: paper is always light */
    css = css.replace(/:root\{/, ".pp{");                                  /* light tooth colours scoped to the page */
    css = css.replace(/\/\* tooth editor[\s\S]*?(?=\/\* inside the treatment record)/, "");
    PP_TEETH_CSS = css;
  } catch (e) { PP_TEETH_CSS = ""; }
  return PP_TEETH_CSS;
}
/* the heading font, embedded only into the PDF (the PDF is printed from a temporary file without the app's fonts) */
async function ppFontFace() {
  if (PP_FONT !== null) return PP_FONT;
  try {
    const b = await (await fetch("fonts/PlayfairDisplaySC-Regular.ttf")).blob();
    const url = await new Promise(ok => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(b); });
    PP_FONT = `@font-face{font-family:"Playfair Display SC";src:url("${url}") format("truetype");font-weight:300 700}`;
  } catch (e) { PP_FONT = ""; }
  return PP_FONT;
}

function ppMoney(v) { return (Math.round((+v || 0) * 100) / 100).toLocaleString("ru-RU", {maximumFractionDigits: 2}) + " ₽"; }

/** The page. o = {prices: bool, days: number, onlyChosen: bool} → {html (with its <style>), plan, patient} */
async function planPresentationHtml(planId, o) {
  o = o || {};
  const plan = await api.invoice(planId);
  if (!plan) throw new Error("План не найден");
  const pat = P && P.id === plan.patient_id ? P : await api.patient(plan.patient_id);
  const ctx = await api.doc_context(plan.patient_id, plan.doctor_id || null, null, planId, null).catch(() => ({clinic: {}, doctor: {}}));
  const vs = plan.variants || [], keys = vs.map(v => v.key), by = (plan.totals && plan.totals.by_variant) || {};
  const chosen = keys.includes(plan.variant) ? plan.variant : "";
  const show = o.onlyChosen && chosen ? vs.filter(v => v.key === chosen) : vs;
  const optOf = it => keys.includes(it.opt || "") ? it.opt : "";
  const visible = plan.items.filter(it => !optOf(it) || show.some(v => v.key === optOf(it)));
  /* formula: current state + plan teeth; the badge is the earliest stage of the tooth */
  const dp = findTeeth(pat.data || {});
  const tmap = {...(dp ? dp.map : {}), ...(pat.teeth_local || {})};
  const planT = new Set(), badge = {};
  visible.forEach(it => (String(it.tooth || "").match(/\b[1-8][1-8]\b/g) || []).forEach(t => {
    planT.add(t); const sg = String(it.stage || "1"); if (!badge[t] || +sg < +badge[t]) badge[t] = sg; }));
  const milk = [...planT].some(t => +t[0] >= 5) && ![...planT].some(t => +t[0] < 5);
  const today = new Date(), until = new Date(today.getTime() + (+o.days || 30) * 864e5);
  const cl = ctx.clinic || {}, doc = ctx.doctor || {};
  const k = 1 - (+plan.discount || 0) / 100;
  const line = it => (+it.price || 0) * (+it.qty || 1) * (1 - (+it.discount || 0) / 100);
  const rows = (items, withTotal, totalVal) => {
    const stages = {};
    items.forEach(it => (stages[String(it.stage || "1")] ||= []).push(it));
    const sk = Object.keys(stages).sort((a, b) => (+a || 0) - (+b || 0) || a.localeCompare(b));
    return `<table class="pp-t"><colgroup><col class="c-t"><col>${o.prices ? '<col class="c-q"><col class="c-s">' : ""}</colgroup><thead><tr><th>Зуб</th><th>Что делаем</th>${o.prices ? "<th style=\"text-align:right\">Кол.</th><th style=\"text-align:right\">Стоимость</th>" : ""}</tr></thead><tbody>${
      sk.map(s => (sk.length > 1 || s !== "1" ? `<tr class="st"><td colspan="${o.prices ? 4 : 2}">Этап ${esc(s)}</td></tr>` : "")
        + stages[s].map(it => `<tr><td class="t">${esc(it.tooth || "—")}</td><td>${esc(it.title)}</td>${o.prices ? `<td class="n">${esc(it.qty || 1)}</td><td class="n">${ppMoney(line(it))}</td>` : ""}</tr>`).join("")).join("")}
      ${withTotal ? `<tr class="tot"><td></td><td>${plan.discount ? `Итого со скидкой ${esc(plan.discount)} %` : "Итого"}</td>${o.prices ? `<td></td><td class="n">${ppMoney(totalVal)}</td>` : ""}</tr>` : ""}</tbody></table>`;
  };
  const common = visible.filter(it => !optOf(it));
  let body = "";
  if (!vs.length) body = `<h3>Лечение по этапам</h3>${rows(visible, true, plan.total)}`;
  else {
    const ncol = Math.min(show.length, 4);
    body = `<h3>${show.length > 1 ? "Варианты лечения" : "Выбранный вариант"}</h3><div class="pp-vars" style="grid-template-columns:repeat(${ncol},1fr)">${show.map(v => `
      <div class="pp-var${v.key === chosen ? " on" : ""}">${v.key === chosen ? '<span class="mark">выбран</span>' : ""}<div class="nm">${esc(v.name)}</div>
        <div class="sum">${ppMoney(by[v.key])}</div>
        ${v.warranty ? `<div class="ln">Гарантия: <b>${esc(v.warranty)}</b></div>` : ""}${v.term ? `<div class="ln">Срок лечения: <b>${esc(v.term)}</b></div>` : ""}
        ${v.note ? `<div class="nt">${esc(v.note)}</div>` : ""}</div>`).join("")}</div>`;
    if (common.length) body += `<div class="pp-blk"><div class="pp-sub">Входит во все варианты</div>${rows(common, false)}</div>`;
    show.forEach(v => { const own = visible.filter(it => optOf(it) === v.key);
      if (own.length) body += `<div class="pp-blk"><div class="pp-sub">Вариант «${esc(v.name)}» <span>· всего ${ppMoney(by[v.key])}</span></div>${rows(own, false)}</div>`; });
    if (o.prices && plan.discount) body += `<p class="pp-note">Суммы вариантов указаны со скидкой ${esc(plan.discount)} %.</p>`;
  }
  const css = PP_CSS + await ppTeethCss();
  const html = `<style>${css}</style><div class="pp">
    <div class="pp-h"><div class="pp-clinic">${esc(cl.name || "Стоматологическая клиника")}<small>${esc([cl.address, cl.phone].filter(Boolean).join(" · "))}</small></div>
      <div class="pp-ttl"><b>${esc(plan.title || "План лечения")}</b><span>от ${esc(fmtDate(iso(today)))} · действителен до ${esc(fmtDate(iso(until)))}</span></div></div>
    <div class="pp-who"><div><small>Пациент</small><b>${esc(pat.name || "")}</b></div><div><small>Врач</small><b>${esc(doc.fio || plan.doctor_name || "—")}</b></div>
      <div><small>${vs.length && !chosen && show.length > 1 ? "Стоимость" : "Сумма плана"}</small><b>${vs.length && !chosen && show.length > 1 ? "от " + ppMoney(Math.min(...show.map(v => by[v.key] || 0))) : ppMoney(chosen ? by[chosen] : plan.total)}</b></div></div>
    <h3>Зубная формула</h3>
    <div class="pp-f">${formulaHtml(tmap, milk, {plan: planT, surf: pat.surf_local || {}, badge})}${formulaLegend(true)}</div>
    ${body}
    ${plan.comment ? `<div class="pp-com">${esc(plan.comment)}</div>` : ""}
    <p class="pp-note">Цифры на зубах — номер этапа. План составлен по результатам осмотра; если во время лечения откроются новые обстоятельства, врач предложит изменения и согласует их с вами.</p>
    <div class="pp-sign"><div>Врач: ${esc(doc.fio || plan.doctor_name || "")}</div><div>С планом ознакомлен(а): ${esc(pat.name || "")}</div></div>
  </div>`;
  return {html, plan, patient: pat, k};
}

async function ppFullDoc(html) {
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>План лечения</title><style>${await ppFontFace()}
@page{size:A4;margin:12mm 11mm}html,body{margin:0;background:#fff}.pp{padding:0;max-width:none}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}</style></head><body>${html}</body></html>`;
}

async function openPlanPresentation(planId, back) {
  const opt = {prices: true, days: 30, onlyChosen: false};
  let cur = null;
  const box = modal(`<div class="m-h"><h3>Презентация плана для пациента</h3><button class="x" data-close>×</button></div>
    <div class="m-b pp-wrap">
      <div class="pp-tools">
        <label class="switch-row"><input type="checkbox" id="ppPrices" checked><span class="sw"></span>Цены услуг</label>
        <label class="switch-row" id="ppOnlyW" hidden><input type="checkbox" id="ppOnly"><span class="sw"></span>Только выбранный вариант</label>
        <label class="fl pp-days">Действителен, дней<input class="input sm" type="number" min="1" max="365" id="ppDays" value="30"></label>
      </div>
      <div class="pp-stage" id="ppStage"><div class="muted" style="padding:30px">Собираем презентацию…</div></div>
    </div>
    <div class="m-f">${back ? '<button class="btn ghost" id="ppBack">← К плану</button>' : ""}<span class="muted"></span>
      <button class="btn ghost" id="ppCard">Сохранить в карту</button><button class="btn ghost" id="ppPdf">PDF</button>
      <button class="btn ghost" id="ppPrint">Печать</button><button class="btn" id="ppTab">На планшет</button></div>`, {wide: true});
  const draw = async () => {
    try { cur = await planPresentationHtml(planId, opt); }
    catch (e) { $("#ppStage", box).innerHTML = `<div class="empty"><b>${esc(errText(e))}</b></div>`; return; }
    $("#ppStage", box).innerHTML = cur.html;
    $("#ppOnlyW", box).hidden = !(cur.plan.variants || []).length || !cur.plan.variant;
  };
  $("#ppPrices", box).onchange = e => { opt.prices = e.target.checked; draw(); };
  $("#ppOnly", box).onchange = e => { opt.onlyChosen = e.target.checked; draw(); };
  let t; $("#ppDays", box).oninput = e => { clearTimeout(t); t = setTimeout(() => { opt.days = Math.max(1, Math.min(365, +e.target.value || 30)); draw(); }, 250); };
  const bk = $("#ppBack", box); if (bk) bk.onclick = () => { closeModal(); back(); };
  $("#ppPrint", box).onclick = () => { if (!cur) return; $("#printArea").innerHTML = cur.html; window.print(); };
  $("#ppPdf", box).onclick = async () => {
    if (!cur) return;
    const b = $("#ppPdf", box); b.disabled = true; b.textContent = "Готовим PDF…";
    try {
      const r = await api.plan_pdf(await ppFullDoc(cur.html), `План лечения — ${cur.patient.name || ""} — ${iso(new Date())}`);
      await saveDataUrl(r.name, r.url);
    } catch (e) {
      if (await ask("PDF не получился", {icon: "warn", ok: "Открыть печать", text: errText(e) + " В окне печати выберите принтер «Microsoft Print to PDF» или «Сохранить как PDF»."})) { $("#printArea").innerHTML = cur.html; window.print(); }
    } finally { b.disabled = false; b.textContent = "PDF"; }
  };
  $("#ppCard", box).onclick = async () => {
    if (!cur) return;
    try { await api.save_document({patient_id: cur.plan.patient_id, template_id: "plan_presentation", title: (cur.plan.title || "План лечения") + " — презентация",
      html: cur.html, data: {plan_id: planId}}); toast("Презентация сохранена в документы пациента"); afterChange(); }
    catch (e) { toast(errText(e), true); }
  };
  $("#ppTab", box).onclick = async () => {
    if (!cur) return;
    const tablets = await api.tablets_list().catch(() => []);
    if (!tablets.length) return toast("Планшет не подключён. Подключить — Настройки → «Планшет для пациентов».", true);
    const tb = tablets.length === 1 ? tablets[0] : await chooseTablet(tablets);
    if (!tb) return;
    const html = (await planPresentationHtml(planId, {...opt, onlyChosen: false})).html;  /* the patient sees every option */
    sendToTablet(tb, "plan", cur.plan.patient_id, null, () => { afterChange(); if (back) back(); }, {plan_id: planId, html});
  };
  draw();
}
