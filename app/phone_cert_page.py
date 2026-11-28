"""3.19: /s/ca — the page a phone installs the clinic's certificate from (the QR in Склад → Телефон leads here), and the files:
/s/ca.crt (Android), /s/ca.mobileconfig (iPhone). Opened by http, before the phone trusts anything; the same text explains why."""
from __future__ import annotations

import html

WHY = [
    "Камеру для сканера телефон даёт только защищённой странице — с адресом на https.",
    "Сайтам в интернете такой «паспорт» выдают специальные центры. Компьютеру внутри Wi-Fi клиники его не выдают — "
    "поэтому клиника выдаёт его себе сама.",
    "Один раз вы говорите телефону «доверяй клинике» — и склад со сканером открывается по Wi-Fi даже без интернета.",
    "Ключ сертификата хранится только на компьютере клиники, а сам сертификат годится только для адресов внутри сети "
    "клиники — не для сайтов в интернете. Ваши сайты, почту и переписку он не открывает.",
    "Android после установки покажет «Сеть может отслеживаться» — это обычное предупреждение для любого своего сертификата. "
    "Для установки Android попросит блокировку экрана (ПИН, графический ключ или отпечаток).",
    "Убрать сертификат можно в любой момент в настройках телефона.",
]

ANDROID = [
    "Нажмите <b>«Скачать сертификат для Android»</b> — файл сохранится в «Загрузки».",
    "Откройте <b>Настройки → Безопасность → Шифрование и учётные данные → Установить сертификат → «Сертификат ЦС»</b> "
    "(или найдите в поиске настроек «Сертификат ЦС»).",
    "Нажмите <b>«Всё равно установить»</b>, подтвердите блокировкой экрана и выберите скачанный файл.",
    "Вернитесь сюда и нажмите <b>«Открыть склад со сканером»</b>.",
]

IPHONE = [
    "Откройте эту страницу <b>в Safari</b> и нажмите <b>«Скачать профиль для iPhone»</b> → <b>«Разрешить»</b>.",
    "Откройте <b>Настройки</b> → вверху <b>«Профиль загружен»</b> → <b>«Установить»</b> (введите код-пароль телефона).",
    "Откройте <b>Настройки → Основные → Об этом устройстве → Доверие сертификатам</b> и включите «{title}».",
    "Вернитесь сюда и нажмите <b>«Открыть склад со сканером»</b>. Без интернета сканер на iPhone работает, если склад со "
    "сканером хотя бы раз открывали при интернете.",
]


def _page(body: str) -> bytes:
    return ("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            "<meta name=\"robots\" content=\"noindex\"><title>Сертификат клиники</title>"
            "<link rel=\"icon\" href=\"/s/icons/icon.svg\" type=\"image/svg+xml\"><link rel=\"stylesheet\" href=\"/s/styles.css\">"
            "</head><body><main id=\"app\" class=\"bare\"><div class=\"gate cert\">" + body + "</div></main></body></html>").encode("utf-8")


def why_html(open_=True) -> str:
    return (f"<details class=\"more why\"{' open' if open_ else ''}><summary>Зачем устанавливать сертификат клиники</summary>"
            "<ul class=\"steps\">" + "".join(f"<li>{html.escape(x)}</li>" for x in WHY) + "</ul></details>")


def serve(srv, rel: str, secure: bool):
    """(code, body, content type, extra headers) for /s/ca, /s/ca.crt, /s/ca.mobileconfig."""
    import clinic_ca
    ca = clinic_ca.get()
    on = bool(srv.httpsd is not None and ca.exists())
    if rel in ("ca.crt", "ca.pem", "ca.mobileconfig"):
        if not on:
            return 404, "Режим со сканером выключен на компьютере клиники".encode(), "text/plain; charset=utf-8", ()
        if rel == "ca.mobileconfig":
            return 200, ca.mobileconfig(), "application/x-apple-aspen-config", (
                ("Content-Disposition", 'attachment; filename="sklad-kliniki.mobileconfig"'),)
        if rel == "ca.pem":
            return 200, ca.ca_pem(), "application/x-pem-file", (("Content-Disposition", 'attachment; filename="sklad-kliniki.pem"'),)
        return 200, ca.ca_der(), "application/x-x509-ca-cert", (("Content-Disposition", 'attachment; filename="sklad-kliniki.crt"'),)
    brand = ("<div class=\"brand\"><i><svg class=\"ico c-brand\" viewBox=\"0 0 24 24\"><path d=\"M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 "
             "1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M7 12h10\"/></svg></i>Склад клиники</div>")
    if not on:
        body = (brand + "<h1>Склад со сканером</h1><p>На компьютере клиники режим со сканером выключен. Включает его директор: "
                "в программе <b>Склад → Телефон → «Со сканером»</b>.</p>" + why_html(True)
                + "<a class=\"btn soft\" href=\"/s/\">Открыть склад без сканера</a>")
        return 200, _page(body), "text/html; charset=utf-8", ()
    st = ca.state()
    # from http: through the app of this same address — it knows the phone and hands it over to https already signed in
    full = "/s/" if secure else "/s/#/tohttps"
    lis = lambda xs: "".join(f"<li>{x}</li>" for x in xs)  # noqa: E731
    body = (brand + "<h1>Склад со сканером</h1>"
            "<p>Чтобы сканер работал по Wi-Fi клиники без интернета, один раз установите на телефон сертификат клиники.</p>"
            + why_html(not secure)
            + "<div class=\"sec\">Android</div><a class=\"btn\" href=\"/s/ca.crt\" download>Скачать сертификат для Android</a>"
            f"<ol class=\"steps mt8\">{lis(ANDROID)}</ol>"
            "<div class=\"sec\">iPhone</div><a class=\"btn\" href=\"/s/ca.mobileconfig\">Скачать профиль для iPhone</a>"
            f"<ol class=\"steps mt8\">{lis(x.replace('{title}', html.escape(st.get('title') or '')) for x in IPHONE)}</ol>"
            f"<a class=\"btn soft\" href=\"{html.escape(full)}\">Открыть склад со сканером</a>"
            f"<p class=\"small muted mt8\">Сертификат: «{html.escape(st.get('title') or '')}», отпечаток {html.escape(st.get('short') or '')} — "
            "такой же показан в программе на компьютере (Склад → Телефон).</p>")
    return 200, _page(body), "text/html; charset=utf-8", ()
