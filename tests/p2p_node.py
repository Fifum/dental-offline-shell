"""One clinic computer for tests/test_p2p.py: its own data folder, its own server and clinic-network node.

    python tests/p2p_node.py <data dir> <port>

Reads Python snippets (one JSON line each: {"code": "..."}) from stdin, runs them with `db`, `api`, `auth`, `p2p`,
`node` at hand and answers one JSON line: {"ok": true, "r": <value of `r`>} or {"ok": false, "error": "..."}."""
import json
import os
import sys
import traceback
from pathlib import Path

data, port = sys.argv[1], int(sys.argv[2])
os.environ["LOCALAPPDATA"] = data
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import auth as authm  # noqa: E402
import config  # noqa: E402
import p2p  # noqa: E402
import replica  # noqa: E402
from db import DB  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402

config.save_settings({"port": port})


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


db = DB()
api = Api(db, W())
srv = ClinicServer(api, db, port=port).start()
auth = srv.auth
node = p2p.Node(db, port)
node.start()
ns = {"db": db, "api": api, "auth": auth, "p2p": p2p, "node": node, "config": config, "replica": replica, "authm": authm,
      "srv": srv}
print(json.dumps({"ready": True, "node": config.node_id()}), flush=True)
for line in sys.stdin:
    try:
        ns["r"] = None
        exec(json.loads(line)["code"], ns)  # noqa: S102 — test harness
        print(json.dumps({"ok": True, "r": ns.get("r")}, ensure_ascii=False, default=str), flush=True)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-1500:]},
                         ensure_ascii=False), flush=True)
