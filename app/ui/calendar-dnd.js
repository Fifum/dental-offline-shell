"use strict";
/* Calendar grid: move a visit by dragging it to another time, doctor (or chair) and day column.
   A drag starts after the pointer moves a few pixels, so a plain click still opens the visit. */
const DND_MIN_MOVE = 6;

function enableDragMove(grid) {
  if (!can("schedule_edit") || !S.dayData) return;
  const slot = +S.settings.slot_min || 15;
  const wrap = grid.closest(".sched-wrap") || grid.parentElement;
  if (!grid.dataset.dnd) {  // once per grid element: swallow the click that follows a drop
    grid.addEventListener("click", e => { if (S.dndJustDropped) { e.stopPropagation(); e.preventDefault(); S.dndJustDropped = false; } }, true);
    grid.dataset.dnd = "1";
  }
  $$(".ev", grid).forEach(el => {
    const v = S.dayData.visits.find(x => x.id === el.dataset.id);
    if (!v || ["st-cancel", "st-done"].includes(stClass(v.status))) return;
    el.classList.add("can-drag");
    el.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      const r0 = el.getBoundingClientRect();
      const st = {x: e.clientX, y: e.clientY, grabY: e.clientY - r0.top, height: r0.height, ghost: null, target: null, timer: null, lastE: e};
      const startDrag = () => {
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic or already released pointer */ }
        el.classList.add("drag-src");
        st.ghost = el.cloneNode(true);
        st.ghost.classList.add("drag-ghost");
        st.ghost.classList.remove("drag-src", "is-conflict");
        st.ghost.style.height = st.height + "px";
        document.body.classList.add("dnd-on");
        st.timer = setInterval(() => autoScroll(st.lastE), 30);
      };
      const autoScroll = ev => {
        if (!ev || !wrap) return;
        const r = wrap.getBoundingClientRect(), edge = 40, sp = 14;
        if (ev.clientY < r.top + edge) wrap.scrollTop -= sp; else if (ev.clientY > r.bottom - edge) wrap.scrollTop += sp;
        if (ev.clientX < r.left + edge + 56) wrap.scrollLeft -= sp; else if (ev.clientX > r.right - edge) wrap.scrollLeft += sp;
        place(ev);
      };
      const place = ev => {
        const col = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".g-col");
        if (!col || !grid.contains(col)) return;
        const top = +col.dataset.top, cr = col.getBoundingClientRect();
        const dur = Math.max(15, (mins(v.end) || mins(v.start) + 30) - mins(v.start));
        let m = Math.round((top + (ev.clientY - cr.top - st.grabY) / PX) / slot) * slot;
        m = Math.max(top, Math.min(m, 24 * 60 - dur));
        if (st.ghost.parentElement !== col) col.appendChild(st.ghost);
        st.ghost.style.top = (m - top) * PX + 1 + "px";
        st.ghost.style.left = "4px"; st.ghost.style.width = "calc(100% - 8px)";
        const s = `${pad(Math.floor(m / 60))}:${pad(m % 60)}`, en = m + dur;
        const t = st.ghost.querySelector(".ev-t");
        if (t) t.textContent = `${s} – ${pad(Math.floor(en / 60) % 24)}:${pad(en % 60)}`;
        st.target = {col, day: col.dataset.day, minute: m, dur};
      };
      const move = ev => {
        st.lastE = ev;
        if (!st.ghost) {
          if (Math.hypot(ev.clientX - st.x, ev.clientY - st.y) < DND_MIN_MOVE) return;
          startDrag();
        }
        ev.preventDefault();
        place(ev);
      };
      const end = async () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", end);
        el.removeEventListener("pointercancel", cancel);
        if (!st.ghost) return;  // it was a click
        clearInterval(st.timer);
        st.ghost.remove(); el.classList.remove("drag-src"); document.body.classList.remove("dnd-on");
        S.dndJustDropped = true; setTimeout(() => { S.dndJustDropped = false; }, 50);
        if (st.target) await dropVisit(v, st.target);
      };
      const cancel = () => {
        clearInterval(st.timer);
        if (st.ghost) { st.ghost.remove(); el.classList.remove("drag-src"); document.body.classList.remove("dnd-on"); }
        el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", end); el.removeEventListener("pointercancel", cancel);
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", end);
      el.addEventListener("pointercancel", cancel);
    });
  });
}

/** Ask, then save the moved visit. target = {col, day, minute, dur} */
async function dropVisit(v, target) {
  const R = await ref();
  const hhmm = m => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
  const start = `${target.day} ${hhmm(target.minute)}`;
  const endM = target.minute + target.dur;
  const end = endM >= 24 * 60 ? `${target.day} 23:59` : `${target.day} ${hhmm(endM)}`;
  const byChair = !!target.col.dataset.chair || S.by === "chair";
  const doctor = byChair ? (v.doctor_id || "") : (target.col.dataset.doc || "");
  const chair = byChair ? (target.col.dataset.chair || "") : (v.chair || "");
  if (start === v.start && doctor === (v.doctor_id || "") && chair === (v.chair || "")) return;
  const docName = id => (R.doctors.find(d => d.id === id) || {}).name || "без врача";
  const when = s => `${fmtDate(s.slice(0, 10))} в ${s.slice(11, 16)}`;
  const chairTxt = c => c ? ", " + (/^кресло/i.test(c) ? c.toLowerCase() : "кресло " + c) : "";
  const lines = [`${v.patient_name || "Пациент"}`, `Было: ${when(v.start)}, ${v.doctor_name || docName(v.doctor_id)}${chairTxt(v.chair)}`,
    `Станет: ${when(start)}, ${docName(doctor)}${chairTxt(chair)}`];
  const s0 = mins(start), e0 = s0 + target.dur;
  const clash = (S.dayData.visits || []).find(x => x.id !== v.id && x.start.slice(0, 10) === target.day && doctor && x.doctor_id === doctor
    && stClass(x.status) !== "st-cancel" && mins(x.start) < e0 && (mins(x.end) || mins(x.start) + 30) > s0);
  if (clash) lines.push("", `Внимание: у врача в это время уже есть запись — ${hm(clash.start)}–${hm(clash.end)} ${clash.patient_name || ""}.`);
  if (!(await ask("Перенести запись?", {ok: "Перенести", icon: clash ? "warn" : "question", text: lines.join("\n")}))) return;
  const branch = doctor !== (v.doctor_id || "") ? ((R.doctors.find(d => d.id === doctor) || {}).branch_id || v.branch_id || "") : (v.branch_id || "");
  try {
    await api.save_visit({id: v.id, patient_id: v.patient_id, doctor_id: doctor, branch_id: branch, start, end,
      title: v.title || "", comment: v.comment || "", chair, status: v.status || "Запланирован",
      action: v.local && v.action === "create" ? "create" : "move"});
    toast(`Запись перенесена на ${when(start)}`);
    afterChange();
  } catch (e) { toast(errText(e), true); }
}
