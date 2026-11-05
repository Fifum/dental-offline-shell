"""Portfolio screenshots on demo data: python tools/screenshots.py -> docs/screenshots/*.png

Runs the dev server against a throw-away data folder (invented demo patients only),
drives the UI with Playwright + installed Microsoft Edge.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
PY = ROOT / ".venv" / "Scripts" / "python.exe"

env = dict(os.environ, LOCALAPPDATA=tempfile.mkdtemp(prefix="dd-shots-"))
srv = subprocess.Popen([str(PY), str(ROOT / "app" / "devserver.py")], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(4)

PREP = """async () => {
  await api.save_settings({clinic: {name: 'ООО «Улыбка Плюс»', address: 'г. Примерск, ул. Садовая, 1', inn: '9300000000',
                           ogrn: '1229300000000', license: '№ Л041-00000 от 01.02.2023', director: 'главного врача Иванова И. И.', phone: '+7 949 000-00-00'}});
  const today = S.day;
  const p = await api.create_patient({lname: 'Смирнова', fname: 'Алина', mname: 'Сергеевна', phone: '+7 949 000-12-34', birth_date: '1991-04-18', gender: 'Ж'});
  const v = await api.save_visit({patient_id: p.id, doctor_id: '11', branch_id: '1', start: today + ' 19:00', end: today + ' 19:45', title: 'Лечение кариеса', chair: 'Кресло 1'});
  const syn = S.dayData.visits.find(x => !x.local && x.doctor_id === '13');
  await api.save_visit({id: syn.id, patient_id: syn.patient_id, doctor_id: '13', branch_id: syn.branch_id, start: today + ' 18:30', end: today + ' 19:00', title: syn.title, action: 'move'});
  await api.save_record({patient_id: p.id, visit_id: v, doctor_id: '11', date: today, complaints: 'Боль от холодного и сладкого, проходит после устранения раздражителя.',
    objective: 'Кариозная полость в пределах дентина, зондирование болезненно по эмалево-дентинной границе.',
    diagnoses: [{code: 'K02.1', title: 'Кариес дентина', tooth: '36'}], teeth: {'36': 'Пломба', '26': 'Коронка', '46': 'Кариес', '18': 'Отсутствует', '47': 'Имплант'},
    treatment: 'Инфильтрационная анестезия. Пломба из светоотверждаемого композита. Окклюзия проверена.'});
  const iid = await api.save_invoice({patient_id: p.id, visit_id: v, doctor_id: '11', items: [{title: 'Лечение кариеса (пломба, светоотверждаемый композит)', code: 'A16.07.002.001', price: 5500, qty: 1, tooth: '36'}, {title: 'Анестезия инфильтрационная', code: 'B01.003.004.002', price: 500, qty: 1}]});
  await api.add_payment({invoice_id: iid, amount: 6000, method: 'Карта'});
  await api.save_document({patient_id: p.id, template_id: 'doc_consent_treatment', title: 'Информированное добровольное согласие на стоматологическое лечение', html: '<p>…</p>'});
  return p.id;
}"""


def shot(page, name, full=False):
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto("http://127.0.0.1:8765/")
        page.wait_for_timeout(3500)
        pid = page.evaluate(PREP)
        page.evaluate("async () => { await refreshStatus(); S.day = S.day; await loadDay(); }")
        page.evaluate("() => { const w = document.querySelector('.sched-wrap'); w.scrollTop = 9 * 60 * PX - 8 * 60 * PX; }")
        shot(page, "01-calendar")

        page.evaluate("async () => { S.days = 2; S.by = 'chair'; await loadDay(); }")
        page.evaluate("() => { document.querySelector('.sched-wrap').scrollTop = 1.2 * 60 * PX; }")
        shot(page, "02-calendar-chairs-2days")
        page.evaluate("async () => { S.days = 1; S.by = 'doctor'; localStorage.clear(); await loadDay(); }")

        page.evaluate("async () => { const v = S.dayData.visits.find(x => x.local && x.action === 'create'); await openVisit(v.id); }")
        shot(page, "03-visit-drawer")
        page.evaluate("() => closeDrawer()")

        page.evaluate(f"async () => {{ await openPatient('{pid}', 'schedule', 'visits'); }}")
        shot(page, "04-patient-card")
        page.evaluate("() => renderPatient('formula')")
        shot(page, "05-dental-formula")
        page.evaluate("() => renderPatient('feed')")
        shot(page, "06-live-feed")

        page.evaluate(f"async () => {{ const r = (await api.patient('{pid}')).records[0]; await openRecord({{patient_id: '{pid}', id: r.id}}); }}")
        shot(page, "07-medical-record")
        page.evaluate("() => closeModal()")

        page.evaluate(f"async () => {{ await openDocFill({{patient_id: '{pid}', template_id: 'doc_contract', doctor_id: '11'}}); "
                      "document.querySelector('.df-in').value = '125/11'; document.querySelector('.df-in').dispatchEvent(new Event('input')); }")
        shot(page, "08-document")
        page.evaluate("() => closeModal()")

        page.evaluate(f"async () => {{ const i = (await api.patient('{pid}')).invoices[0]; await openInvoice({{patient_id: '{pid}', id: i.id}}); }}")
        shot(page, "09-invoice")
        page.evaluate("() => closeModal()")

        page.evaluate("() => show('journal')")
        shot(page, "10-transfer-journal")
        page.evaluate("() => show('settings')")
        page.evaluate("() => document.querySelector('.mode-cards').scrollIntoView({block: 'center'})")
        shot(page, "11-settings-transfer-mode")
        b.close()
finally:
    srv.terminate()
