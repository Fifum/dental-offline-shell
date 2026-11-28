"""3.18: the AI of the program chooses the picture of a new piece of equipment while it has no photo of its own.

A new piece (or a renamed one) — the AI set in «Голос и ИИ» is asked in the background which of the pictures of
ui/img/stock fits its name; the key is kept in equipment.pic (synced with the card), the lists get it by the name
(stock_summary → eq_pics) and eqPic() takes it before the words of the name. Without the AI, or when it fails or names no
picture, the pictures by the words of the name stay. The AI here is a stand-in: nothing leaves the computer."""
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import db as dbm  # noqa: E402
import main  # noqa: E402
import replica  # noqa: E402
import stock  # noqa: E402
from main import Api  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def settle():
    """Wait for the background questions to the AI."""
    for t in [t for t in threading.enumerate() if t.name == "eq-pic"]:
        t.join(10)


d = dbm.DB()
a = Api(d, W())
replica.install(d)
S = a._stock
UI = ROOT / "app" / "ui"
js = (UI / "stock-nurse.js").read_text(encoding="utf-8")

# ------------------------------------------------------------------ the list of pictures, the answer
rules = set(re.findall(r'\["([a-z-]+)", \[', js[js.index("const EQ_PIC_RULES"):js.index("const EQ_PIC_CATS")]))
check("the AI chooses from the same pictures as the rules", set(stock.EQ_PICS) == rules, set(stock.EQ_PICS) ^ rules)
check("every picture is a file", all((UI / "img" / "stock" / f"{k}.webp").exists() for k in stock.EQ_PICS))
check("the question lists every picture and asks for one key", all(f"\n{k} — " in stock.EQ_PIC_TASK for k in stock.EQ_PICS)
      and "одним словом" in stock.EQ_PIC_TASK and "none" in stock.EQ_PIC_TASK)
for ans, key in (("autoclave", "autoclave"), ("Ответ: Autoclave.", "autoclave"), ("ultrasonic-bath", "ultrasonic-bath"),
                 ("X-ray", "xray"), ("none", ""), ("кресло", ""), ("", ""), (None, ""), ("chairs", ""),
                 ("scaler (или handpiece)", "scaler")):
    check(f"answer {ans!r} → {key!r}", stock.eq_pic_answer(ans) == key, stock.eq_pic_answer(ans))
check("names keyed the same way", stock.eq_pic_name("  Ультразвуковая   МОЙКА Ёмкость ") == "ультразвуковая мойка емкость")

# ------------------------------------------------------------------ the program's AI
check("the program gives the stock its AI", S.ai_ask is main._eq_ai_ask)
try:
    main._eq_ai_ask(stock.EQ_PIC_TASK, "Название: Автоклав")
    FAIL.append("AI off: expected a refusal")
except ValueError as e:
    check("AI off: no question is sent", "выключен" in str(e), e)

# ------------------------------------------------------------------ a new piece
asked = []


def fake(task, text):
    asked.append(text)
    name = text.split("\n")[0]
    if "Ирригатор" in name:
        raise ValueError("ИИ выключен")
    return {"Пескоструй": "scaler", "Тумба мобильная": "cabinet", "Аппарат Vector": "Ответ: scaler"}.get(name.split(": ", 1)[1], "none")


S.ai_ask = fake
e1 = a.save_equipment({"name": "Пескоструй", "category": "Гигиена"})
settle()
check("a new piece: the AI is asked with its name and category", asked == ["Название: Пескоструй\nКатегория: Гигиена"], asked)
check("the picture is kept in the card", d.one("SELECT pic FROM equipment WHERE id=?", (e1,))["pic"] == "scaler")
check("the lists get it by the name", a.stock_summary()["eq_pics"].get("пескоструй") == "scaler", a.stock_summary().get("eq_pics"))

asked.clear()
a.save_equipment({"id": e1, "name": "Пескоструй", "category": "Гигиена", "comment": "в кабинете 2"})
settle()
check("an edit with the same name asks nothing and keeps the picture", not asked and d.one("SELECT pic FROM equipment WHERE id=?", (e1,))["pic"] == "scaler", asked)

a.save_equipment({"id": e1, "name": "Тумба мобильная", "category": "Мебель"})
settle()
check("renamed: asked again, the new picture", asked == ["Название: Тумба мобильная\nКатегория: Мебель"]
      and d.one("SELECT pic FROM equipment WHERE id=?", (e1,))["pic"] == "cabinet", asked)
check("the old name is no longer in the lists", "пескоструй" not in a.stock_summary()["eq_pics"])

e2 = a.save_equipment({"name": "Ирригатор"})
e3 = a.save_equipment({"name": "Непонятная штука"})
settle()
check("the AI failed: no picture of its own, nothing broke", (d.one("SELECT pic FROM equipment WHERE id=?", (e2,))["pic"] or "") == "")
check("the AI named no picture: none kept", (d.one("SELECT pic FROM equipment WHERE id=?", (e3,))["pic"] or "") == "")
check("only real pictures reach the lists", set(a.stock_summary()["eq_pics"].values()) <= set(stock.EQ_PICS))

# renamed while the AI was thinking: the answer for the old name is not kept
e4 = a.save_equipment({"name": "Аппарат Vector"})
settle()
with d.tx() as c:
    c.execute("UPDATE equipment SET pic='', name='Аппарат Vector Paro' WHERE id=?", (e4,))
check("the answer for an old name is dropped", S.eq_pick_pic(e4, "Аппарат Vector") == "scaler"
      and (d.one("SELECT pic FROM equipment WHERE id=?", (e4,))["pic"] or "") == "")

S.ai_ask = None
asked.clear()
e5 = a.save_equipment({"name": "Холодильник для материалов"})
settle()
check("no AI: nothing asked, the words of the name decide", not asked and (d.one("SELECT pic FROM equipment WHERE id=?", (e5,))["pic"] or "") == "")

# ------------------------------------------------------------------ sync and the screen
check("the picture goes to the other computers", "pic" in replica.CATCHUP_COLS["equipment"]
      and tuple(map(int, replica.CATCHUP.split("."))) >= (3, 18))
eq = js[js.index("const eqPic = "):js.index("const matPic")]
check("eqPic: the words of the name, then the AI's picture, then the category",
      eq.index("byWords") < eq.index("STK.eq_pics[eqPicName(name)]") < eq.index("stockPicBy(EQ_PIC_RULES, EQ_PIC_CATS, name, category"),
      eq)
check("eqPic: only a real picture of the AI is taken", "EQ_PIC_RULES.some(r => r[0] === ai)" in eq)
check("names keyed the same in the window", 'replace(/ё/g, "е").replace(/\\s+/g, " ").trim()' in js)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
