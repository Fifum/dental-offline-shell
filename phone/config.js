/* Where the cloud of the stock lives (Supabase edge function «stock»). */
window.DD_API = "https://jdqlcvmcfqtvzuymxhgg.supabase.co/functions/v1/stock";
/* The scanner polyfill for phones without BarcodeDetector (iPhone): loaded once, then kept by the service worker. */
window.DD_SCAN_POLYFILL = "https://cdn.jsdelivr.net/npm/barcode-detector@3.2.3/+esm";
/* 3.19: this is the app through the internet; the computer of the clinic gives the same files under /s/ with its own config
   (app/server.py phone_config: DD_LOCAL = true, DD_BASE = "/s/"). */
window.DD_LOCAL = false;
window.DD_BASE = "/";
