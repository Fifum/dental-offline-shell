"""3.15.1: printing (a schedule, a document, a receipt: window.print() or Ctrl+P) shows WebView2's print preview over
the whole main window. It looks like a document opened in a window of its own, and the window's × above it closed the
whole program (2026-11-27: «при закрытии документа закрывается всё приложение»).

The page tells the program when the preview opens and closes (beforeprint / afterprint). While it is open, the
window's × (Alt+F4, «Закрыть окно» on the taskbar) closes only the preview: the window gets Esc, as if the preview's
own «Отмена» was pressed. Should the preview stay open (the window could not come forward), the page is loaded again —
that closes any preview; the sign-in lives in the tab's session and survives it."""
import ctypes
import logging
import threading
import time

log = logging.getLogger("printguard")

VK_ESCAPE, KEYEVENTF_KEYUP = 0x1B, 0x0002


class PrintGuard:
    WAIT = 1.5  # seconds for the preview to close after Esc before the page is loaded again

    def __init__(self, hwnd=None, esc=None, reload=None):
        self._hwnd = hwnd      # () -> the window's handle; asked on the window's own thread
        self._esc = esc        # (hwnd) -> True when Esc went to this window
        self._reload = reload  # () -> load the page again
        self._lock = threading.Lock()
        self._seq = -1
        self._closed = threading.Event()
        self._closed.set()
        self.open = False
        self.busy = False

    def state(self, on, seq=0):
        """From the page: the preview opened (on) or closed. Each call of the page's bridge runs in a thread of its
        own, so an «opened» that comes late must not undo a newer «closed»: seq grows within a page."""
        try:
            seq = int(seq or 0)
        except (TypeError, ValueError):
            seq = 0
        with self._lock:
            if seq < self._seq:
                return self.open
            self._seq = seq
            self.open = bool(on)
            (self._closed.clear if self.open else self._closed.set)()
            return self.open

    def page_loaded(self):
        """A new page in the window: no preview is open there, and its count starts again."""
        with self._lock:
            self.open, self._seq = False, -1
            self._closed.set()

    def on_closing(self):
        """pywebview's «closing» event (runs on the window's thread). False keeps the window open."""
        if not self.open:
            return None
        if not self.busy:
            self.busy = True
            hwnd = None
            try:
                hwnd = self._hwnd() if self._hwnd else None
            except Exception as e:  # noqa: BLE001
                log.warning("window handle: %s", e)
            threading.Thread(target=self._dismiss, args=(hwnd,), daemon=True, name="print-preview-close").start()
        return False

    def _dismiss(self, hwnd):
        try:
            time.sleep(0.1)  # the window finishes its click on × first
            sent = False
            if hwnd and self._esc:
                try:
                    sent = bool(self._esc(hwnd))
                except Exception as e:  # noqa: BLE001
                    log.warning("Esc to the print preview: %s", e)
            if sent and self._closed.wait(self.WAIT):
                return
            if self.open and self._reload:
                log.info("the print preview stayed open: loading the page again")
                try:
                    self._reload()
                except Exception as e:  # noqa: BLE001
                    log.warning("reload after print: %s", e)
                self.page_loaded()
        finally:
            self.busy = False


def send_esc(hwnd) -> bool:
    """Esc to the program's window — only when it is the window in front, so nobody else's window gets the key."""
    u = ctypes.windll.user32
    u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.SetForegroundWindow(ctypes.c_void_p(int(hwnd)))  # the user has just clicked its ×: it may come forward
    if (u.GetForegroundWindow() or 0) != int(hwnd):
        return False
    u.keybd_event(VK_ESCAPE, 0, 0, 0)
    u.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
    return True


def attach(window, setup):
    """Wire the guard to the main window (pywebview) and to the page's bridge (setup.print_state)."""
    def reload():  # load_url() of the same address does nothing in WebView2 (its Source does not change)
        from System import Action  # noqa: PLC0415
        form = window.native
        form.Invoke(Action(lambda: form.browser.webview.CoreWebView2.Reload()))

    guard = PrintGuard(hwnd=lambda: int(window.native.Handle.ToInt64()), esc=send_esc, reload=reload)
    setup._print = guard
    window.events.closing += guard.on_closing
    window.events.loaded += guard.page_loaded
    return guard
