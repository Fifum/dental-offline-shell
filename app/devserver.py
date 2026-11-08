"""Dev only: run the clinic server and open the UI in a normal browser (http://127.0.0.1:8765)."""
import os
import sys
import time

# keep dev data apart from a real installation on this computer
os.environ["LOCALAPPDATA"] = os.environ.get("DEV_DATA") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".devdata")
os.makedirs(os.environ["LOCALAPPDATA"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import DB  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402
from sync import SyncWorker  # noqa: E402

if __name__ == "__main__":
    db = DB()
    worker = SyncWorker(db)
    worker.start()
    port = int(os.environ.get("PORT", 8765))
    ClinicServer(Api(db, worker), db, port=port, host=os.environ.get("HOST", "127.0.0.1")).start()
    print(f"http://127.0.0.1:{port}/")
    while True:
        time.sleep(3600)
