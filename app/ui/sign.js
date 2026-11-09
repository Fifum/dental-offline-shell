"use strict";
/* Handwritten signatures (mouse, pen or a finger on a touch screen), signed documents, the health
   questionnaire and the patient tablet (pairing in Settings, tasks sent from the patient card). */

/** A drawing pad on a <canvas>. Returns {isEmpty, toDataURL, clear}. */
function signaturePad(canvas) {
  const ctx = canvas.getContext("2d");
  let drawing = false, empty = true, last = null;
  const fit = () => {
    const r = canvas.getBoundingClientRect(), k = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, r.width * k); canvas.height = Math.max(1, r.height * k);
    ctx.setTransform(k, 0, 0, k, 0, 0); ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#111"; ctx.lineWidth = 2.4;
    empty = true;
  };
  const pos = e => { const r = canvas.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
  canvas.style.touchAction = "none";
  canvas.onpointerdown = e => { drawing = true; last = pos(e); try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ } ctx.beginPath(); ctx.arc(last.x, last.y, 1.1, 0, Math.PI * 2); ctx.fillStyle = "#111"; ctx.fill(); empty = false; };
  canvas.onpointermove = e => {
    if (!drawing) return;
    const p = pos(e), w = Math.max(1.4, 3.2 - Math.hypot(p.x - last.x, p.y - last.y) / 12);  // faster stroke — thinner line
    ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); last = p; empty = false;
  };
  canvas.onpointerup = canvas.onpointercancel = () => { drawing = false; };
  requestAnimationFrame(fit); setTimeout(fit, 60);
  return {isEmpty: () => empty, toDataURL: () => canvas.toDataURL("image/png"), clear: () => fit()};
}

const sigPadHtml = id => `<div class="sig-pad"><canvas id="${id}"></canvas><span class="sig-line">Подпись</span><button class="linkbtn sig-clear" data-clear="${id}" type="button">Стереть</button></div>`;

/* ------------------------------------------------------------ documents */
/** Signatures under an open document. Returns {printHtml} for printing. */
async function docSignatures(box, d) {
  const el = $("#dvSigs", box);
  let list = [];
  const draw = async () => {
    list = await api.document_signatures(d.id);
    el.innerHTML = list.length ? `<div class="doc-sigs">${list.map(s => `<div class="doc-sig"><img alt="Подпись" src="${s.image}">
      <div><b>${esc(s.signer)}</b>${s.role === "representative" ? " (законный представитель)" : s.role === "doctor" ? " (врач)" : ""}<small>${esc(fmtDT(s.signed_at))} · ${esc(s.place === "screen" ? "на экране программы" : s.place)}</small>
      ${s.changed ? `<small class="bad-t">Документ изменён после подписи</small>` : ""}</div></div>`).join("")}</div>` : "";
  };
  await draw();
  const btn = $("#dvSign", box);
  if (!can("docs")) btn.remove();
  else btn.onclick = () => signChoice({title: d.title, patient_id: d.patient_id, document_id: d.id, signer: (P && P.id === d.patient_id ? P.name : "")}, () => openDocument(d.id));
  return {printHtml: () => list.length ? `<div class="doc-sigs print">${list.map(s => `<div class="doc-sig"><img alt="" src="${s.image}"><div>${esc(s.signer)}<br><small>подписано ${esc(fmtDT(s.signed_at))}</small></div></div>`).join("")}</div>` : ""};
}

/** «Подписать здесь» or «На планшет». o = {title, patient_id, document_id, signer} */
async function signChoice(o, after) {
  const tablets = await api.tablets_list().catch(() => []);
  if (!tablets.length) return signHere(o, after);
  const pick = await askLayer({title: "Где подписать?", icon: "edit", ok: "Подписать здесь", cancel: tablets.length === 1 ? `На ${tablets[0].name}` : "На планшет",
    text: "Подписать на этом экране (мышью или пером) или отправить документ на планшет пациенту."});
  if (pick) return signHere(o, after);
  const t = tablets.length === 1 ? tablets[0] : await chooseTablet(tablets);
  if (t) sendToTablet(t, "sign", o.patient_id, o.document_id, after);
}

function signHere(o, after) {
  const box = modal(`<div class="m-h"><h3>Подпись: ${esc(o.title)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b"><div class="grid2"><label class="fl">Кто подписывает<input class="input" id="sgWho" value="${esc(o.signer || "")}"></label>
      <label class="fl">Кем приходится<select class="input" id="sgRole"><option value="patient">Пациент</option><option value="representative">Законный представитель</option><option value="doctor">Врач</option></select></label></div>
      ${sigPadHtml("sgPad")}<p class="hint">Распишитесь в поле мышью, пером или пальцем (на сенсорном экране).</p></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="sgOk">Подписать</button></div>`);
  const pad = signaturePad($("#sgPad", box));
  $("[data-clear]", box).onclick = () => pad.clear();
  $("#sgOk", box).onclick = async () => {
    if (pad.isEmpty()) return toast("Распишитесь в поле", true);
    try { await api.document_sign(o.document_id, $("#sgWho", box).value, pad.toDataURL(), $("#sgRole", box).value); closeModal(); toast("Документ подписан"); if (after) after(); }
    catch (e) { toast(errText(e), true); }
  };
}

async function chooseTablet(tablets) {
  return new Promise(ok => {
    const box = modal(`<div class="m-h"><h3>На какой планшет?</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><div class="tb-list">${tablets.map((t, i) => `<button class="btn ghost" data-i="${i}">${esc(t.name)}${t.busy ? " (занят)" : ""}</button>`).join("")}</div></div>`, {onClose: () => ok(null)});
    $$("[data-i]", box).forEach(b => b.onclick = () => { ok(tablets[+b.dataset.i]); closeModal(); });
  });
}

/** Sends a task and waits on screen until the patient finishes it on the tablet. */
async function sendToTablet(t, kind, patientId, documentId, after, extra) {
  let r;
  try { r = await api.tablet_send(t.id, kind, patientId, documentId || null, extra || null); } catch (e) { return toast(errText(e), true); }
  let stop = false;
  const box = modal(`<div class="m-h"><h3>Отправлено на «${esc(t.name)}»</h3><button class="x" data-close>×</button></div>
    <div class="m-b tb-wait"><div class="scan"><i></i><span id="tbSt">Передайте планшет пациенту. Ждём, пока он ${kind === "sign" ? "подпишет документ" : kind === "plan" ? "выберет вариант и подпишет план" : kind === "nps" ? "оценит визит" : "заполнит анкету"}…</span></div></div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" id="tbCancel">Отменить задание</button></div>`, {onClose: () => { stop = true; }});
  $("#tbCancel", box).onclick = async () => { stop = true; await api.tablet_cancel(t.id, r.task_id); closeModal(); toast("Задание на планшете отменено"); };
  while (!stop) {
    await new Promise(x => setTimeout(x, 1500));
    if (stop) break;
    let s; try { s = await api.tablet_status(t.id, r.task_id); } catch (e) { continue; }
    if (s.state === "opened") $("#tbSt", box).textContent = "Пациент открыл задание на планшете…";
    if (s.state === "done") {
      stop = true; closeModal();
      toast(kind === "sign" ? "Пациент подписал документ на планшете" : kind === "plan" ? "Пациент подписал план на планшете" : kind === "nps" ? `Пациент оценил визит: ${s.result ? s.result.score : ""}` : `Анкета заполнена${s.result && s.result.alerts && s.result.alerts.length ? ": " + s.result.alerts.join("; ") : ""}`);
      if (after) after(s.result); break;
    }
    if (["expired", "cancelled", "gone"].includes(s.state)) { stop = true; closeModal(); toast("Задание на планшете закрыто, не выполнено", true); break; }
  }
}

/* ------------------------------------------------------------ questionnaire */
async function openQuestionnaire(p) {
  const tablets = await api.tablets_list().catch(() => []);
  const choice = await new Promise(ok => {
    const box = modal(`<div class="m-h"><h3>Анкета о здоровье · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
      <div class="m-b"><p class="hint">Пациент отвечает на вопросы о здоровье и расписывается. Ответы сохраняются в карте как подписанный документ, аллергия из анкеты учитывается при проверке назначений.</p>
        ${p.questionnaire ? `<div class="warn-line">Последняя анкета — ${esc(fmtDT(p.questionnaire.created_at))}${p.questionnaire.alerts.length ? ": " + esc(p.questionnaire.alerts.join("; ")) : ", без особенностей"}</div>` : ""}
        <div class="tb-list">${tablets.map((t, i) => `<button class="btn" data-t="${i}">На ${esc(t.name)}</button>`).join("")}
          <button class="btn ${tablets.length ? "ghost" : ""}" data-c="here">Заполнить на этом экране</button><button class="btn ghost" data-c="blank">Пустой бланк для печати</button></div></div>`, {onClose: () => ok(null)});
    $$("[data-t]", box).forEach(b => b.onclick = () => { ok({tablet: tablets[+b.dataset.t]}); closeModal(); });
    $$("[data-c]", box).forEach(b => b.onclick = () => { ok({c: b.dataset.c}); closeModal(); });
  });
  if (!choice) return;
  const reload = async () => { P = await api.patient(p.id); if (S.view === "patient") renderPatient(S.patientTab); };
  if (choice.tablet) return sendToTablet(choice.tablet, "anketa", p.id, null, reload);
  if (choice.c === "blank") return openDocFill({patient_id: p.id, template_id: "doc_anketa"});
  const qs = await api.questionnaire_questions();
  const box = modal(`<div class="m-h"><h3>Анкета о здоровье · ${esc(p.name)}</h3><button class="x" data-close>×</button></div>
    <div class="m-b q-form">${qs.map(q => `<div class="q-row" data-k="${q.key}"><div class="q-q">${esc(q.q)}</div>
      <div class="seg sm q-yn"><button data-v="1" type="button">Да</button><button data-v="0" type="button">Нет</button></div>
      ${q.extra ? `<input class="input q-x" placeholder="${esc(q.extra)}" hidden>` : ""}</div>`).join("")}
      ${sigPadHtml("qPad")}</div>
    <div class="m-f"><span class="muted"></span><button class="btn ghost" data-close>Отмена</button><button class="btn" id="qOk">Сохранить анкету</button></div>`, {wide: true});
  const ans = {};
  $$(".q-row", box).forEach(r => $$(".q-yn button", r).forEach(b => b.onclick = () => {
    ans[r.dataset.k] = {...(ans[r.dataset.k] || {}), yes: b.dataset.v === "1"};
    $$(".q-yn button", r).forEach(x => x.classList.toggle("on", x === b));
    const x = $(".q-x", r); if (x) { x.hidden = b.dataset.v !== "1"; if (!x.hidden) x.focus(); }
    r.classList.remove("q-miss");
  }));
  const pad = signaturePad($("#qPad", box));
  $("[data-clear]", box).onclick = () => pad.clear();
  $("#qOk", box).onclick = async () => {
    const miss = $$(".q-row", box).filter(r => !ans[r.dataset.k]);
    if (miss.length) { miss.forEach(r => r.classList.add("q-miss")); miss[0].scrollIntoView({block: "center"}); return toast("Ответьте на все вопросы", true); }
    if (pad.isEmpty()) return toast("Пациент должен расписаться", true);
    $$(".q-row", box).forEach(r => { const x = $(".q-x", r); if (x) ans[r.dataset.k].text = x.value; });
    try { const r = await api.questionnaire_save(p.id, ans, pad.toDataURL()); closeModal(); toast(`Анкета сохранена${r.alerts.length ? ": " + r.alerts.join("; ") : ""}`); reload(); }
    catch (e) { toast(errText(e), true); }
  };
}

/* ------------------------------------------------------------ settings: tablets */
async function loadTabletSettings() {
  const box = $("#tabletBody"); if (!box) return;
  let list; try { list = await api.tablets_list(); } catch (e) { return; }
  const net = await api.network_info().catch(() => ({urls: []}));
  box.innerHTML = `${list.length ? `<table class="tbl compact"><thead><tr><th>Планшет</th><th>Подключён</th><th>Был на связи</th><th></th></tr></thead><tbody>
      ${list.map(t => `<tr><td><b>${esc(t.name)}</b></td><td>${esc(fmtDT(t.created_at))}</td><td>${esc(fmtDT(t.last_seen))}</td><td class="row-acts"><button class="linkbtn" data-rv="${esc(t.id)}">отключить</button></td></tr>`).join("")}
    </tbody></table>` : `<p class="muted">Планшетов пока нет.</p>`}
    <div class="row"><button class="btn" id="tbPair">Подключить планшет</button></div>
    <p class="hint">Планшет должен быть в той же сети Wi-Fi, что и этот компьютер. Адрес для планшета: ${net.urls.length ? net.urls.map(u => `<code>${esc(u)}t</code>`).join(" или ") : "компьютер не подключён к сети"}.</p>
    ${net.public ? `<div class="warn-line">${NET_PUBLIC_HINT}</div>` : ""}`;
  $$("[data-rv]", box).forEach(b => b.onclick = async () => { if (await ask("Отключить планшет?", {danger: true, ok: "Отключить", text: "Чтобы снова пользоваться им, его нужно будет подключить новым кодом."})) { await api.tablet_revoke(b.dataset.rv); loadTabletSettings(); } });
  $("#tbPair", box).onclick = async () => {
    const v = await askInput("Подключить планшет", [{label: "Название планшета", value: list.length ? `Планшет ${list.length + 1}` : "Планшет ресепшена"}], {ok: "Получить код"});
    if (!v) return;
    const c = await api.tablet_code(v[0]);
    await ask(`Код: ${c.code.slice(0, 3)} ${c.code.slice(3)}`, {icon: "edit", ok: "Готово", cancel: "Закрыть",
      text: `На планшете откройте в браузере ${net.urls[0] ? net.urls[0] + "t" : "адрес этого компьютера с портом 8765 и /t"} и введите этот код. Код действует 10 минут.${net.public ? "\n\n" + NET_PUBLIC_HINT : ""}`});
    loadTabletSettings();
  };
}
