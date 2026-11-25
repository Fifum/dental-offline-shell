"""3.11: the schedule laid out like the calendar of Dentist Plus, and windows that never cut or push text past their edge.

Static checks of the page (toolbar, grid, cards, menus, the doctor's month, «Настройки календаря»), the functions the
old screen relied on (dragging, double bookings, statuses, the visit panel, «Следующий пациент», the waiting list,
recurring visits, rights), and — with node, when it is installed — the release notes turned into headings and lists
and the doctor a chair column belongs to."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import updates  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


UI = ROOT / "app" / "ui"
ui = lambda n: (UI / n).read_text(encoding="utf-8")  # noqa: E731
html, app, dp, dnd, book, lounge, plat = (ui(n) for n in ("index.html", "app.js", "calendar-dp.js", "calendar-dnd.js", "booking.js", "lounge.js", "platform.js"))
css = ui("styles-calendar.css")
NODE = shutil.which("node")


def body(src, start):
    """The text of the block that starts at `start` (up to its matching closing brace)."""
    i = src.index(start)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    return src[i:]


# ------------------------------------------------------------------ the page: files and the toolbar
check("styles-calendar.css loaded with the cache tag", f'<link rel="stylesheet" href="styles-calendar.css?v={config.VERSION}">' in html)
check("calendar styles after the lounge, before the responsive sheet",
      html.index("styles-lounge.css") < html.index("styles-calendar.css") < html.index("styles-responsive.css"))
check("calendar-dp.js loaded with the cache tag", f'<script src="calendar-dp.js?v={config.VERSION}"></script>' in html)
check("calendar-dp.js after calendar-dnd.js and app.js, before lounge.js",
      html.index('src="app.js') < html.index('src="calendar-dnd.js') < html.index('src="calendar-dp.js') < html.index('src="lounge.js'))
sched = html[html.index('<section class="view" id="view-schedule">'):html.index("<!-- ===================== PATIENTS")]
for id_ in ("dayTitle", "ddDays", "ddDaysLbl", "ddBy", "ddByLbl", "ddMode", "ddModeLbl", "modeSeg", "branchSel", "ddDocs", "ddDocsLbl", "docsMenu",
            "waitBtn", "waitBadge", "todayBtn", "prevDay", "dayLabel", "dayPick", "nextDay", "calSetBtn", "printBtn", "newVisitBtn",
            "daySub", "nextCard", "weekStrip", "grid", "list", "dayEmpty", "dayEmptySub"):
    check(f"schedule keeps #{id_}", f'id="{id_}"' in sched and html.count(f'id="{id_}"') == 1)
check("«Расписание:» label first (a colon by CSS)", 'id="dayTitle">Расписание</h1>' in sched and "#dayTitle::after{content:\":\"}" in css)
bar = sched[sched.index('<header class="cal-bar dpc-bar">'):sched.index("</header>")]
order = [bar.index(f'id="{x}"') for x in ("dayTitle", "ddDays", "ddBy", "ddMode", "branchSel", "ddDocs", "waitBtn", "todayBtn", "prevDay", "dayLabel", "nextDay", "calSetBtn", "printBtn", "newVisitBtn")]
check("one toolbar in the order of Dentist Plus: views left; doctors, date, gear, «Новый визит» right", order == sorted(order), order)
check("the views are text menus (blue links)", bar.count('class="dd-btn"') >= 3 and "#view-schedule .dpc-bar .dd-btn{color:var(--dpc-blue)" in css)
check("«Выбрано докторов» is a grey pill", 'class="dd-btn dpc-pill"' in bar and ".dpc-pill" in css)
check("the date between arrows, the native picker kept under it", '<button class="dpc-day" id="dayLabel"' in bar and 'type="date" id="dayPick"' in bar
      and "i.showPicker()" in app)
check("«Новый визит» with F2, blue", ">Новый визит<kbd class=\"kb\">F2</kbd>" in bar and "#view-schedule .btn.dpc-new{" in css and "var(--dpc-blue)" in css)
check("periods kept: day, 2, 3 days, week", all(f'data-days="{n}"' in bar for n in (1, 2, 3, 7)))
check("doctors / chairs kept", 'data-by="doctor"' in bar and 'data-by="chair"' in bar)
check("grid / list kept", 'data-mode="grid"' in bar and 'data-mode="list"' in bar)
check("legend kept: five statuses", all(f'class="lg-{k}"' in sched for k in ("new", "ok", "come", "done", "cancel")))
check("waiting list still opens from the toolbar", '(() => { const b = $("#waitBtn"); if (b) b.onclick = openWaitlist; })();' in ui("waitlist.js"))

# ------------------------------------------------------------------ the grid
rg = body(app, "function renderGrid(res)")
check("day bar «25 ноября, 2026 (среда)»", "${dayLong(d)} <span>(${WD[d.getDay()]})</span>" in rg
      and "const dayLong = d => `${d.getDate()} ${MONTHS[d.getMonth()]}, ${d.getFullYear()}`;" in app)
check("a band in the doctor's colour with the working hours", 'class="gh-band"' in rg and "--dc:${c.color}" in rg and '<small>${esc(hours)}</small>' in rg
      and "`${shift.start} - ${shift.end}`" in rg)
check("chair columns: «Кресло N» above the band of the doctor working there", '<div class="gh-chair">${esc(c.name)}</div>' in rg and "colDoctor(c)" in rg)
check("time scale every half hour", "${pad(h)}:30" in rg and "${pad(h)}:00" in rg)
check("hatched hours off the shift / clinic day", rg.count('class="off-hours"') == 2)
check("column: doctor colour on the left, tinted working hours", "border-left:3px solid var(--dc" in css and "color-mix(in srgb,var(--dc,#7A8794) 6%" in css)
check("card: status icon, «09:00 - 10:00», patient, «⋮»", 'class="ev-ic"' in rg and "${hm(v.start)} - ${hm(v.end)}" in rg and 'class="ev-k"' in rg
      and "${esc(v.patient_name ||" in rg)
check("card: a status icon for every status", all(f'"{k}":' in app[app.index("const ST_IC"):app.index("const CAL_IC")] for k in ("st-new", "st-ok", "st-come", "st-done", "st-cancel")))
check("card: comment, repeat and «перенести в DP» marks", "CAL_IC.comment" in rg and "v.series_id" in rg and '<i class="lc" title="Нужно перенести в Dentist Plus">' in rg)
check("card keeps the double booking and local marks", "${v.conflict ? \"is-conflict\" : \"\"}" in rg and "${v.local ? \"is-local\" : \"\"}" in rg
      and ".ev.is-conflict .ev-t::after" in ui("styles-motion.css"))
check("short visits on one line", "is-short" in rg and "#grid .ev.is-short{display:flex" in css)
check("status colours of the legend on the cards", all(f"#grid .ev.{k}{{border-color:var(--{k})" in css for k in ("st-ok", "st-come", "st-done", "st-cancel")))
check("click opens the visit, «⋮» and the right click open the menu",
      'if (e.target.closest(".ev-k")) return menu(e, el.dataset.id); openVisit(el.dataset.id);' in rg and "el.oncontextmenu = e => menu(e, el.dataset.id);" in rg)
check("free time: click books, right click opens the menu", "openBooking({doctor_id: col.dataset.doc, chair: col.dataset.chair" in rg
      and "calSlotMenu(col, minuteAt(col, e), e)" in rg and 'if (can("schedule_edit")) $$(".g-col", grid)' in rg)
check("dragging still wired", "enableDragMove(grid)" in rg and "PX" in dnd and "let PX = calPx();" in app and "PX = calPx();" in rg)
check("the band opens the doctor's month", "calDoctorMonth(b)" in rg)
check("scale and colours from «Настройки календаря»", 'CAL.get("docColors", "1")' in rg and 'CAL.get("stColors", "1")' in rg
      and "const CAL_SCALE = {compact: 56, normal: 76, large: 96};" in app)
check("a 30-minute visit has two lines at the usual scale", 30 * 76 / 60 - 2 >= 34)
check("print header from the day label", 'Расписание: ${esc(S.dayLabel || "")}' in app)
check("the visit panel and «Следующий пациент» stay (lounge.js wraps loadDay/openVisit)", "window.loadDay = async function" in lounge
      and "window.openVisit = async function" in lounge and "renderNext()" in lounge)

# ------------------------------------------------------------------ menus, the doctor's month, settings
vm = body(dp, "function calVisitMenu(id, e)")
for st in ("Подтверждён", "Пришёл", "Завершён", "Не пришёл", "Отменён"):
    check(f"visit menu: status «{st}»", f'calSetStatus(v, "{st}")' in vm)
check("visit menu: the same rights as the visit panel", 'edit = can("schedule_edit")' in vm and 'stOk = canAny("schedule_edit", "medcard_edit")' in vm
      and 'canAny("billing", "payments")' in vm and 'can("medcard_view")' in vm and 'can("patients_view")' in vm)
check("visit menu: cancel and no-show only with schedule_edit", re.search(r'if \(edit && !\["st-cancel", "st-done"\]\.includes\(sc\)\) bad\.push\(\{t: "Не пришёл"', vm)
      and 'if (edit && sc !== "st-cancel") bad.push({t: "Отменить запись"' in vm)
ss = body(dp, "async function calSetStatus(v, st)")
check("cancel asks first, waiting list hint after", 'st === "Отменён" && !(await ask("Отменить запись?"' in ss and "waitlistHint(v)" in ss and "afterChange()" in ss)
check("visit menu: move, invoice, record, card, book again", all(x in vm for x in ("openBooking(f)", "openInvoice(", "openRecord(", "openPatient(v.patient_id", "Новый визит этому пациенту")))
check("menu closes on Esc, outside click, scroll; arrows move", all(x in dp for x in ('e.key === "Escape"', '"mousedown", calMenuOutside', '"scroll", calMenuClose', 'e.key === "ArrowDown"')))
check("menu stays inside the window", "Math.min(x, innerWidth - r.width - 8)" in dp and "Math.min(y, innerHeight - r.height - 8)" in dp)
check("slot menu: new visit at that time and the waiting list", "Новый визит в ${t}" in dp and "openWaitlist" in body(dp, "function calSlotMenu"))
dm = body(dp, "async function calDoctorMonth(band)")
check("doctor's month: working days from the shifts, a day opens", 'api.shifts_month(month)' in dm and '["d:" + docId]' in dm and "S.day = b.dataset.d" in dm
      and 'canAny("schedule_view", "shifts_edit", "staff")' in dm)
cs = body(dp, "function calSettings()")
check("calendar settings: doctor colours, status colours, legend, scale", all(x in cs for x in ("Использовать цвета врачей", "Использовать цвета статусов визита", "Показывать легенду статусов", "Масштаб сетки")))
check("calendar settings applied at once, the dialog never «unsaved»", "box._dirty = false" in cs)
check("Home: today", 'e.key !== "Home"' in dp and '$("#todayBtn").click()' in dp)

# ------------------------------------------------------------------ «Новый визит» in the order of Dentist Plus
check("booking titled like Dentist Plus", '${editing ? "Изменить визит" : "Новый визит"}' in book)
i = {k: book.index(k) for k in ('id="bkDoc"', 'id="bkDate"', 'id="bkTime"', 'id="bkDur"', 'id="bkQ"', 'id="bkTitle"')}
check("booking order: doctor, date, time, duration, patient, service", list(i.values()) == sorted(i.values()), i)
check("booking: DP labels", all(x in book for x in ("Дата визита", "Время визита", "Продолжительность", "+ Создать пациента", 'id="bkSave">Сохранить<')))
check("booking keeps repeats, double booking warning, chair", all(x in book for x in ('id="bkRep"', "api.save_visit_series", 'id="bkWarn"', "checkOverlap", 'id="bkChair"')))

# ------------------------------------------------------------------ windows: text always inside, «Что нового» whole
mo = ui("styles-motion.css")
check("dialog column can shrink (no min-content stretching)", "grid-template-columns:44px minmax(0,1fr)" in mo)
check("dialog text wraps long words", ".ask-c{min-width:0;min-height:0;overflow:auto;overflow-wrap:anywhere}" in mo)
check("dialog never taller than the window", "max-height:calc(100vh - 32px)" in mo)
check("«Что нового» in a scrolling block", ".ask-notes{" in mo and "overflow:auto" in mo[mo.index(".ask-notes{"):mo.index(".ask-notes{") + 200])
al = app[app.index("function askLayer("):app.index("/** await ask(")]
check("askLayer takes notes", 'notes = ""' in al and "notesHtml(notes)" in al)
us = body(plat, "async function updateStart(ver)")
check("update dialog: notes whole, not cut at 900", "slice(0, 900)" not in us and "notes: (st && st.notes) || \"\"" in us)
check("settings: notes formatted, not raw <pre>", "notesHtml(st.notes)" in plat and "<pre>${esc(st.notes)}</pre>" not in plat)
check("the program keeps the whole notes", updates.NOTES_MAX >= 20000 and "notes=notes[:NOTES_MAX]" in (ROOT / "app" / "updates.py").read_text(encoding="utf-8"))
us_tool = (ROOT / "tools" / "update_sign.py").read_text(encoding="utf-8")
check("the feed carries the whole notes too", "notes[:4000]" not in us_tool and us_tool.count("notes[:updates.NOTES_MAX]") == 2)
n311 = (ROOT / "docs" / "Что нового в версии 3.11.txt").read_text(encoding="utf-8-sig")
check("3.11 notes: no long unbroken line (3.10 draws this update's dialog)", max(len(w) for w in n311.split()) <= 20,
      max(n311.split(), key=len))
rs = ui("styles-responsive.css")
for rule in (".toast{width:max-content;max-width:min(640px,calc(100vw - 32px));overflow-wrap:anywhere}", ".m-h h3{min-width:0;overflow-wrap:anywhere}",
             ".upd-banner{max-width:calc(100vw - 36px);flex-wrap:wrap}", ".drawer{overflow-wrap:break-word}", ".m-f .muted{flex:1 1 0;"):
    check(f"no text past the edge: {rule[:40]}", rule in rs)

# ------------------------------------------------------------------ node: syntax, the notes, the chair's doctor
if NODE:
    for n in ("app.js", "calendar-dp.js", "booking.js", "platform.js", "calendar-dnd.js", "lounge.js"):
        r = subprocess.run([NODE, "--check", str(UI / n)], capture_output=True, text=True)
        check(f"syntax {n}", r.returncode == 0, r.stderr[-300:])
    notes = (ROOT / "docs" / "Что нового в версии 3.10.txt").read_text(encoding="utf-8-sig")
    esc = app[app.index("const esc = "):app.index("\n", app.index("const esc = "))]
    st = body(app, "function stClass(s)")
    code = "\n".join([esc, st, body(app, "function notesHtml(text)"), body(app, "function colDoctor(c)"), """
const notes = %s;
const h = notesHtml(notes);
const chair = {chair: true, items: [{doctor_id: "7", status: "Пришёл"}, {doctor_id: "9", status: "Запланирован"}, {doctor_id: "9", status: "Подтверждён"},
  {doctor_id: "7", status: "Отменён"}, {doctor_id: "7", status: "Отменён"}]};
console.log(JSON.stringify({h, chair: colDoctor(chair), doc: colDoctor({id: "5", items: []}), none: colDoctor({id: "_", items: []}),
  esc: notesHtml("<b>x</b>\\n• <i>y</i>"), num: notesHtml("1. один\\n2. два")}));
""" % json.dumps(notes)])
    js_file = Path(tempfile.mkdtemp()) / "calendar_check.js"  # a file: the notes are too long for a command line
    js_file.write_text(code, encoding="utf-8")
    r = subprocess.run([NODE, str(js_file)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("node ran", r.returncode == 0, r.stderr[-400:])
    if r.returncode == 0:
        o = json.loads(r.stdout)
        h = o["h"]
        check("notes: no raw rules", "━" not in h and "────" not in h)
        check("notes: the title line", '<div class="nt-title">Dental Desk 3.10.2 — что нового</div>' in h, h[:200])
        check("notes: headings between rules", "<h5>ГЛАВНАЯ СКЛАДА</h5>" in h and h.count("<h5>") == len(re.findall(r"━\n([^\n━]+)\n━", notes)), h.count("<h5>"))
        bullets = len([x for x in notes.splitlines() if x.strip().startswith("•")])
        check("notes: every «•» line is a list item", h.count("<li>") == bullets and "<li>•" not in h, (h.count("<li>"), bullets))
        check("notes: the end of the notes is there (nothing cut)", notes.strip().splitlines()[-1].strip().lstrip("• ")[:30] in h.replace("&quot;", '"').replace("&#39;", "'"))
        check("notes: escaped", "&lt;b&gt;x&lt;/b&gt;" in o["esc"] and "<li>&lt;i&gt;y&lt;/i&gt;</li>" in o["esc"])
        check("notes: numbered lists", o["num"].count("<li>") == 2 and "<ol>" in o["num"])
        check("chair column: the doctor with most visits (cancelled ones not counted)", o["chair"] == "9", o["chair"])
        check("doctor column: itself", o["doc"] == "5" and o["none"] == "", (o["doc"], o["none"]))
else:
    print("node not found: JS checks skipped")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
